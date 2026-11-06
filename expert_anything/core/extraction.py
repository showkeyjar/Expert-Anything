"""Knowledge extraction.

Primary path uses an LLM to produce *source-grounded* concepts, relations
and an ordered learning path. The fallback is a deterministic heuristic used
only when no LLM key is configured -- it is explicitly marked so the UI can
warn the user that depth is limited.
"""
from __future__ import annotations

import concurrent.futures
import functools
import json
import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from expert_anything.core.llm import (
    LLMClient,
    Message,
    _profile_min_output_tokens,
    chat_json,
    parse_llm_json,
)
from expert_anything.core.models import (
    Chapter,
    Concept,
    KnowledgeAsset,
    Relation,
    SourceLocation,
)
from expert_anything.core.domain_templates import (
    detect_domain_from_title,
    domain_concept_skeleton,
)
from expert_anything.core.parsers import title_from
from expert_anything.core.prompt_registry import get_domain_prompt
from expert_anything.core import i18n
_t = i18n.t

logger = logging.getLogger(__name__)


def _extract_temperature() -> float:
    """Temperature for extraction calls (default 0 for reproducibility)."""
    try:
        return float(os.environ.get("EXPERTANYTHING_EXTRACT_TEMPERATURE", "0"))
    except ValueError:
        return 0.0


def _extract_seed() -> int | None:
    """Fixed sampling seed so repeated local runs stay comparable."""
    raw = os.environ.get("EXPERTANYTHING_LLM_SEED", "0").strip().lower()
    if raw in ("", "none", "off", "disabled"):
        return None
    try:
        return int(raw)
    except ValueError:
        return 0


_OUTPUT_RATIO_DEFAULT = 0.55
_OUTPUT_FLOOR = 1024
_OUTPUT_CEILING = 8192


def _output_budget(snippet: str) -> int:
    """Derive ``max_tokens`` from the chunk length instead of a fixed 1500.

    A 9000-char Chinese chunk on this model needed ~2700–4400 output tokens
    (AGENTS.md #48), so the old 1500 cap truncated the JSON. ``ratio=0.55``
    plus 600 head-room yields ~5550 for that chunk; the floor protects small
    chunks and the ceiling keeps prompt+output inside ``n_ctx=16384``.
    """
    try:
        ratio = float(
            os.environ.get("EXPERTANYTHING_LLM_OUTPUT_RATIO", str(_OUTPUT_RATIO_DEFAULT))
        )
    except ValueError:
        ratio = _OUTPUT_RATIO_DEFAULT
    try:
        ceiling = int(
            os.environ.get("EXPERTANYTHING_LLM_MAX_TOKENS_CEILING", str(_OUTPUT_CEILING))
        )
    except ValueError:
        ceiling = _OUTPUT_CEILING
    budget = int(len(snippet) * ratio) + 600
    return max(_OUTPUT_FLOOR, min(ceiling, budget))


def _provenance_from_reports(method: str, reports: list[dict]) -> dict:
    """Aggregate per-call chat_json reports into one queryable provenance block."""
    attempts = [a for r in reports for a in r.get("attempts", [])]
    caps = [r["json_mode_capability"] for r in reports if r.get("json_mode_capability")]
    return {
        "source": method,
        "llm": True,
        "explicit_fallback": False,
        "json_mode": any(a.get("json_mode") for a in attempts),
        "json_mode_capability": caps[0] if caps else "unknown",
        "json_mode_source": next(
            (r["json_mode_source"] for r in reports if r.get("json_mode_source")), "default"
        ),
        "grammar_early_stop": any(r.get("grammar_early_stop") for r in reports),
        "json_mode_downgraded": any(r.get("json_mode_downgraded") for r in reports),
        "attempts": len(attempts),
        "max_tokens": max((a.get("max_tokens") or 0) for a in attempts) if attempts else 0,
        "finish_reasons": [a.get("finish_reason", "") for a in attempts],
        "parse_repairs": sorted(
            {rep for a in attempts for rep in a.get("repairs", [])}
        ),
        "truncation_retries": sum(r.get("truncation_retries", 0) for r in reports),
        "truncated_partial": any(r.get("truncated_partial") for r in reports),
        # Per-attempt facts: enough to tell "grammar stopped early" apart from
        # "ran out of budget" without re-running the extraction.
        "attempt_details": [
            {
                "json_mode": a.get("json_mode"),
                "max_tokens": a.get("max_tokens"),
                "finish_reason": a.get("finish_reason"),
                "chars": a.get("chars"),
                "tokens": a.get("tokens"),
                "keys": a.get("keys"),
            }
            for a in attempts
        ],
        "temperature": _extract_temperature(),
        "seed": _extract_seed(),
    }


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


def _ground_evidence(text: str, evidence: list[str], name: str) -> list[str]:
    """Keep evidence that literally appears in the source; otherwise try to
    pull a sentence that actually contains the concept name."""
    out: list[str] = []
    for ev in evidence or []:
        if ev and ev.strip() in text:
            out.append(ev.strip())
    if out:
        return out[:3]
    # best-effort: find a sentence containing the concept name
    lowered = text.lower()
    needle = name.lower()
    if needle and needle in lowered:
        for sent in re.split(r"(?<=[。!?.!?])\s+|\n+", text):
            if needle in sent.lower():
                return [sent.strip()[:360]]
    return []


def _parse_json(text: str) -> dict:
    """Tolerant JSON extraction (canonical implementation: llm.parse_llm_json)."""
    return parse_llm_json(text)


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _as_str(v) -> str:
    """Coerce an LLM-returned field to a clean string.

    The model sometimes emits a list where the schema expects a string
    (e.g. ``"name": ["A", "B"]``). Naive ``.strip()`` then raises
    AttributeError and - because extract_knowledge swallows all exceptions -
    the whole import silently falls back to deterministic extraction. Flatten
    lists here so a single malformed field never aborts the extraction.
    """
    if v is None:
        return ""
    if isinstance(v, list):
        return " ".join(str(x).strip() for x in v if x is not None).strip()
    return str(v).strip()


def _as_str_list(v) -> list[str]:
    """Coerce an LLM-returned field to a list of clean strings."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


def _extract_with_llm(
    text: str, filename: str, llm: LLMClient, on_progress=None,
    page_offsets: list[int] | None = None, domain_id: str | None = None,
) -> KnowledgeAsset:
    """Single- or multi-call extraction.

    For short inputs one call is enough. For long inputs (e.g. a whole book)
    we split into overlapping chunks, extract each, then merge concepts by
    normalized name and resolve relations against the merged id map. This both
    improves coverage (the previous 12k-char hard cut dropped later chapters)
    and lets us dedupe across chunks.

    `on_progress(stage, current, total, message)` is called to drive a progress
    bar in the UI so long extractions do not look like a freeze.

    `domain_id` selects the domain-specific prompts (Phase 3): ``None`` (default)
    auto-detects the domain from the asset title, an explicit id forces that
    domain, and ``""`` disables domain prompts.  Without a detected domain the
    generic prompts are used unchanged; with one, the template concept skeleton
    is injected as alignment guidance only — grounding checks in `_assemble`
    stay exactly as strict.
    """
    # Domain detection: title-based, deterministic, no extra LLM call. The
    # skeleton is rendered once and reused for every chunk.
    if domain_id is None:
        domain_id = detect_domain_from_title(title_from(text, filename))
    concept_skeleton = domain_concept_skeleton(domain_id)
    CHUNK = 9000
    OVERLAP = 600
    if len(text) <= CHUNK + OVERLAP:
        if on_progress:
            on_progress("extract", 0, 1, _t("ext_analyzing"))
        report: dict = {}
        data = _call_extract(
            llm, text[: CHUNK + OVERLAP],
            domain_id=domain_id, concept_skeleton=concept_skeleton,
            report=report,
        )
        if not data:
            raise ValueError(_t("ext_llm_failed"))
        asset = _assemble(data, text, filename, method="llm_extraction_v1",
                         page_offsets=page_offsets)
        asset.provenance = _provenance_from_reports("llm_extraction_v1", [report])
        if on_progress:
            on_progress(
                "extract", 1, 1,
                _t("ext_done", n=len(asset.concepts), r=len(asset.relations)),
            )
        return asset

    merged: dict = {"concepts": [], "relations": [], "learning_path": []}
    seen: set[str] = set()
    chunks = _split_text(text, CHUNK, OVERLAP)
    total = len(chunks)
    if on_progress:
        on_progress("extract", 0, total, _t("ext_chunks_start", n=total))
    # Run chunk extractions concurrently, but never let network completion order
    # define the knowledge model. Store each result by its source chunk index,
    # then merge in document order so concepts, first definitions and paths are
    # deterministic across runs while retaining the parallel latency benefit.
    done = 0
    chunk_results: list[dict | None] = [None] * total
    reports: list[dict] = [{} for _ in range(total)]
    # Reproducibility: the local Vulkan endpoint is not deterministic at temp 0
    # even with a fixed seed, and concurrent slots make it worse. Keep the pool
    # in step with the client's concurrency cap (1 slot => strictly serial).
    workers = min(4, total)
    if getattr(llm, "max_concurrency", workers) <= 1:
        workers = 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        # Bind the domain prompt inputs and the per-chunk report with partial()
        # so the executor keeps receiving the same (fn, llm, chunk) call shape.
        futures = {
            pool.submit(
                functools.partial(
                    _call_extract,
                    domain_id=domain_id,
                    concept_skeleton=concept_skeleton,
                    report=reports[index],
                ),
                llm,
                chunk,
            ): index
            for index, chunk in enumerate(chunks)
        }
        for fut in concurrent.futures.as_completed(futures):
            index = futures[fut]
            chunk_results[index] = fut.result() if not fut.exception() else None
            done += 1
            if on_progress:
                extracted = sum(
                    len(result.get("concepts", []))
                    for result in chunk_results
                    if result
                )
                on_progress(
                    "extract", done, total,
                    _t("ext_chunk_progress", d=done, t=total, n=extracted),
                )

    for d in chunk_results:
        if not d:
            continue
        for c in d.get("concepts", []):
            nm = _as_str(c.get("name"))
            if not nm:
                continue
            key = _norm(nm)
            existing = next(
                (x for x in merged["concepts"] if _norm(x["name"]) == key), None
            )
            if existing is not None:
                for ev in _as_str_list(c.get("evidence")):
                    if ev and ev not in existing["evidence"]:
                        existing["evidence"].append(ev)
                continue
            if key in seen:
                continue
            seen.add(key)
            merged["concepts"].append(
                {
                    "name": nm,
                    "definition": _as_str(c.get("definition")),
                    "evidence": _as_str_list(c.get("evidence")),
                }
            )
        merged["relations"].extend(d.get("relations", []))
        for p in _as_str_list(d.get("learning_path", [])):
            if p not in merged["learning_path"]:
                merged["learning_path"].append(p)
    # A failed chunk must leave a trace: silently dropping it made the whole
    # document look "successfully extracted but empty".
    chunk_failures = [
        {"chunk": index, "reason": reports[index].get("failure_reason") or "empty_result"}
        for index, result in enumerate(chunk_results)
        if not result
    ]
    if not merged["concepts"]:
        detail = "; ".join(f"#{f['chunk']}: {f['reason']}" for f in chunk_failures[:3])
        raise ValueError(
            f"{_t('ext_chunks_failed')}"
            + (f" ({detail})" if detail else "")
        )
    # Drop TOC-like noise concepts (chapter/section headings) so the focused
    # model keeps real concepts, then cap the merged set.
    _NOISE = {
        "part i", "part ii", "part iii", "part iv", "introduction",
        "conclusion", "definitions", "results", "contents",
        "table of contents", "preface", "acknowledgments", "index",
        "bibliography", "appendix",
    }
    merged["concepts"] = [
        c for c in merged["concepts"] if _norm(c.get("name", "")) not in _NOISE
    ]
    merged["concepts"] = merged["concepts"][:40]
    asset = _assemble(merged, text, filename, method="llm_extraction_chunked_v1",
                      page_offsets=page_offsets)
    asset.provenance = _provenance_from_reports("llm_extraction_chunked_v1", reports)
    asset.provenance["chunk_failures"] = chunk_failures
    asset.provenance["chunks_total"] = total
    asset.provenance["chunks_failed"] = len(chunk_failures)
    if on_progress:
        on_progress(
            "extract", total, total,
            _t("ext_chunks_done", n=len(asset.concepts), r=len(asset.relations)),
        )
    return asset


def _call_extract(
    llm: LLMClient, snippet: str,
    domain_id: str | None = None, concept_skeleton: str = "",
    report: dict | None = None,
) -> dict:
    """One extraction call.

    With a detected ``domain_id`` that has a registered prompt variant, the
    domain-specific system/user prompts are used and the template's concept
    skeleton is injected as *alignment guidance*.  Otherwise the generic prompts
    are used and the request is byte-identical to the pre-Phase-3 behaviour.

    Grounding is enforced entirely in :func:`_assemble` (verbatim evidence,
    hallucinated concepts dropped); a domain prompt never relaxes those checks,
    and the skeleton is explicitly labelled as "not a knowledge source" there.

    ``report`` (when supplied) receives the endpoint-capability / budget /
    truncation / parse-repair facts recorded by :func:`chat_json`, so the
    resulting asset can say *how* it was produced.
    """
    system = get_domain_prompt("extraction_system", domain_id)
    user = get_domain_prompt("extraction_user", domain_id).format(
        chunk_text=snippet, concept_skeleton=concept_skeleton
    )
    # Start from a budget this endpoint already proved sufficient (round 34:
    # 2286 truncated on a 3067-char doc, 3886 finished). The dynamic estimate is
    # still the baseline for first-time endpoints / larger chunks.
    budget = max(_output_budget(snippet), _profile_min_output_tokens(llm))
    return chat_json(
        llm,
        [Message("system", system), Message("user", user)],
        temperature=_extract_temperature(),
        # Length-scaled budget: a fixed 1500 truncated a 9000-char chunk.
        max_tokens=budget,
        # `concepts` must carry content (an empty extraction is not an answer);
        # `relations` only has to be *present* — an empty list is legitimate,
        # but a missing key means the model stopped after the first field
        # (llama.cpp JSON grammar, AGENTS.md #48) and json_mode must be dropped.
        require_keys=("concepts", "relations"),
        require_nonempty=("concepts",),
        seed=_extract_seed(),
        report=report,
    )


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        out.append(text[start : start + size])
        start += size - overlap
    return out


def _assign_chapters(asset: "KnowledgeAsset") -> "KnowledgeAsset":
    """Deterministically attach each concept to a chapter.

    Uses the first evidence's position in the source: the nearest preceding
    chapter heading becomes the chapter. Section headings and numbered prose
    are deliberately not treated as chapters. If the text
    has no detectable headings, the source is split into 6 equal parts named
    Part 1..6. Concepts whose evidence was already grounded keep LLM-provided
    chapters; this is a source-location light (P0-3), independent of LLM.
    """
    text = asset.source_text
    if not text or not asset.concepts:
        return asset

    lines = text.splitlines()
    heads: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if (
            re.match(r"^(chapter|part|unit|section)\b", s, re.I)
            or re.match(r"^第\s*\d+\s*章\b", s)
            or re.match(r"^附录\s*[A-ZＡ-Ｚ一二三四五六七八九十0-9]", s, re.I)
        ) and len(s) < 100 and not s.startswith("http"):
            heads.append((i, s[:80]))
    if len(heads) < 2:
        n = len(lines) or 1
        heads = [(int(i * n / 6), f"Part {i + 1}") for i in range(6)]

    def _line_of(needle: str) -> int:
        pos = text.find(needle)
        return text[:pos].count("\n") if pos >= 0 else -1

    for c in asset.concepts:
        if getattr(c, "chapter", ""):
            continue
        ln = -1
        for ev in c.evidence or []:
            ln = _line_of(ev)
            if ln >= 0:
                break
        if ln < 0:
            continue
        best = heads[0][1]
        for hl, ht in heads:
            if hl <= ln:
                best = ht
            else:
                break
        c.chapter = best[:80]
    return asset


def _page_of(char_start: int, page_offsets: list[int] | None) -> int | None:
    """Map a character offset to its 1-based page number (PDF only)."""
    if not page_offsets:
        return None
    page = 0
    for i, off in enumerate(page_offsets):
        if char_start >= off:
            page = i
        else:
            break
    return page + 1


_SENTENCE_RE = re.compile(r"[^。！？!?\.\n]+[。！？!?\.]?")


def _recover_relation_evidence(
    text: str, source_name: str, target_name: str, evidence: str
) -> str:
    """Return a verbatim source span for a relation, or "".

    LLM relation evidence is usually an exact quote, but paraphrases happen.
    Instead of silently dropping the edge we look for one *sentence* that names
    both endpoints; only such a sentence is admissible. This keeps the
    source-grounding rule intact while recovering edges the model really
    supports, so the semantic network stays as dense as the text allows.
    """
    if not text:
        return ""
    evidence = (evidence or "").strip()
    if evidence and evidence in text:
        return evidence
    s_name, t_name = (source_name or "").strip(), (target_name or "").strip()
    if not s_name or not t_name:
        return ""
    s_low, t_low = s_name.lower(), t_name.lower()
    for match in _SENTENCE_RE.finditer(text):
        span = match.group(0).strip()
        low = span.lower()
        if s_low in low and t_low in low:
            return span
    return ""


def _canonical_relation_type(label: str, rtype: str) -> str:
    """Fold free-form LLM relation types into the six canonical semantics."""
    from expert_anything.core.decoder import classify_relation

    return classify_relation(label or "", rtype or "")


def _stamp_locations(
    asset: "KnowledgeAsset", page_offsets: list[int] | None = None
) -> "KnowledgeAsset":
    """Record each concept's evidence position in the raw source text.

    For every grounded evidence snippet we store its character offset in
    ``source_text``, derive the 1-based line number, and attach the concept's
    chapter. When ``page_offsets`` is supplied (PDF only) we also record the
    1-based page number. This powers a truthful 'source location' label and a
    precise jump in the reader. Works on both LLM and deterministic-fallback
    assets because evidence is always grounded in the source.
    """
    text = asset.source_text or ""
    for c in asset.concepts:
        locs: list[SourceLocation] = []
        for ev in c.evidence or []:
            if not ev:
                continue
            start = text.find(ev)
            if start < 0 and len(ev) > 60:
                # evidence may have been truncated; fall back to a long prefix
                start = text.find(ev[:60])
            if start < 0:
                continue
            line = text.count("\n", 0, start) + 1
            locs.append(
                SourceLocation(
                    char_start=start,
                    char_end=start + len(ev),
                    chapter=getattr(c, "chapter", "") or "",
                    snippet=ev[:200],
                    line=line,
                    page=_page_of(start, page_offsets),
                )
            )
        c.locations = locs

    # Relation evidence gets the same anchor treatment: an edge without a
    # locatable span is exactly the kind of unverifiable claim the UI must be
    # able to expose, so we stamp what we can and leave the rest unanchored.
    for r in asset.relations:
        ev = (r.evidence or "").strip()
        if not ev:
            r.location = None
            continue
        start = text.find(ev)
        if start < 0:
            r.location = None
            continue
        r.location = SourceLocation(
            char_start=start,
            char_end=start + len(ev),
            chapter="",
            snippet=ev[:200],
            line=text.count("\n", 0, start) + 1,
            page=_page_of(start, page_offsets),
        )
    return asset


def _assemble(
    data: dict, text: str, filename: str, method: str,
    page_offsets: list[int] | None = None,
) -> KnowledgeAsset:
    concepts: list[Concept] = []
    name_to_id: dict[str, str] = {}
    for c in data.get("concepts", []):
        name = _as_str(c.get("name"))
        if not name:
            continue
        evidence = _ground_evidence(text, _as_str_list(c.get("evidence")), name)
        # A concept without a verbatim source span cannot be located, audited or
        # safely taught.  _ground_evidence may recover a sentence containing the
        # exact concept name, but if that also fails the candidate is rejected.
        if not evidence:
            continue
        cid = _new_id("c")
        name_to_id[_norm(name)] = cid
        definition = _as_str(c.get("definition"))
        # The project treats definition as source-grounded content, not an LLM
        # paraphrase.  Keep it only when it is a literal source span; otherwise
        # use the already validated evidence as the conservative definition.
        if not definition or definition not in text:
            definition = evidence[0][:200]
        concepts.append(
            Concept(
                id=cid,
                name=name,
                definition=definition,
                summary=definition,
                evidence=evidence,
                chapter=_as_str(c.get("chapter"))[:80],
            )
        )

    relations: list[Relation] = []
    name_by_id = {c.id: c.name for c in concepts}
    seen_relations: set[tuple[str, str, str]] = set()
    for r in data.get("relations", []):
        s, t = _norm(r.get("source", "")), _norm(r.get("target", ""))
        if not (s in name_to_id and t in name_to_id) or s == t:
            continue
        source_id, target_id = name_to_id[s], name_to_id[t]
        # Relations affect the graph, prerequisite order and adaptive path, so
        # accepting an unsupported edge is more harmful than omitting one:
        # evidence must be a verbatim span, or recoverable from a sentence that
        # names both endpoints.
        relation_evidence = _recover_relation_evidence(
            text,
            name_by_id[source_id],
            name_by_id[target_id],
            _as_str(r.get("evidence")),
        )
        if not relation_evidence:
            continue
        rtype = _canonical_relation_type(
            _as_str(r.get("label")), _as_str(r.get("type"))
        )
        # Chunked extraction overlaps, so the same claim often arrives twice.
        # Contrast is symmetric (A↔B and B↔A are one claim); other semantics
        # are directed and must stay distinct.
        if rtype == "contrast":
            key = (min(source_id, target_id), max(source_id, target_id), rtype)
        else:
            key = (source_id, target_id, rtype)
        if key in seen_relations:
            continue
        seen_relations.add(key)
        relations.append(
            Relation(
                id=_new_id("r"),
                source=source_id,
                target=target_id,
                label=_as_str(r.get("label")),
                type=rtype,
                evidence=relation_evidence,
            )
        )

    path_names = [_norm(n) for n in _as_str_list(data.get("learning_path", []))]
    learning_path = [name_to_id[n] for n in path_names if n in name_to_id]
    # any concept not on the path gets appended
    for c in concepts:
        if c.id not in learning_path:
            learning_path.append(c.id)

    chapters = [
        Chapter(id=_new_id("ch"), title=_as_str(ch.get("title")), order=i)
        for i, ch in enumerate(data.get("chapters", []))
        if (ch.get("title") or "").strip()
    ]

    asset = KnowledgeAsset(
        asset_id=_new_id("a"),
        type=(filename.split(".")[-1] if "." in filename else "text").lower(),
        title=title_from(text, filename),
        source_name=filename,
        created_at=datetime.now(timezone.utc).isoformat(),
        source_text=text,
        chapters=chapters,
        concepts=concepts,
        relations=relations,
        learning_path=learning_path,
        method=method,
    )
    asset = _assign_chapters(asset)
    return _stamp_locations(asset, page_offsets)


# --- Deterministic fallback (no LLM) -----------------------------------------
def _fallback(
    text: str, filename: str,
    page_offsets: list[int] | None = None,
) -> KnowledgeAsset:
    """No-LLM structural index.

    The old fallback invented placeholder concept names ("核心概念"/"实践与反馈")
    that never appeared in the source, so definitions, evidence and relations all
    came out empty - which is exactly the "everything is empty" complaint. This
    version instead builds a *grounded* index from the actual text:

    - If the document has headings (#, numbered, or ALL-CAPS short lines), one
      concept per heading, with a real evidence sentence pulled from the body.
    - Otherwise it chunks the body into paragraphs and makes one concept per
      substantial paragraph, using the paragraph's own first sentence as the
      definition stub and the paragraph as evidence.

    Relations require semantic inference and are left empty here on purpose; the
    UI warns that a real model is needed for relations. No fabricated content.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 20]
    if not paragraphs:
        paragraphs = [s.strip() for s in re.split(r"(?<=[。!?.!?])\s+", text) if len(s.strip()) >= 20]

    # EPUB books often contain hundreds of numbered lines in tables and prose
    # (for example ``0.2 ...`` at the beginning of a paragraph).  Treat only
    # short, actual heading-shaped lines as structure, and keep chapter-level
    # Chinese headings used by this book family as well.
    raw_lines = text.splitlines()
    # Character offset of every line start. Evidence is sliced from source_text
    # through these offsets (never re-joined), so a quote stays verbatim even
    # when the original text uses its own whitespace.
    line_starts: list[int] = [0]
    for _m in re.finditer("\n", text):
        line_starts.append(_m.end())
    # heading rows: (line number, concept name, nesting level, evidence line).
    # The raw heading line is kept separately because it is the verbatim span
    # a structural relation is derived from.
    heading_rows: list[tuple[int, str, int, str]] = []
    # A fenced code block may contain lines that begin with '#' (shell comments,
    # comments in samples). Those are content, not document structure; treating
    # them as headings created pseudo-concepts that never exist in the topic.
    in_fence = False
    for line_no, raw_line in enumerate(raw_lines):
        s = raw_line.strip()
        if not s or len(s) > 100:
            continue
        if s.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # _extract_html_blocks surrounds real h1-h6 blocks with blank lines.
        # Requiring blank lines on both sides prevents the first paragraph
        # after a heading from being mistaken for another heading merely
        # because it follows a heading boundary.
        prev_blank = line_no > 0 and not raw_lines[line_no - 1].strip()
        next_blank = line_no + 1 < len(raw_lines) and not raw_lines[line_no + 1].strip()
        semantic_heading = (
            (prev_blank and next_blank)
            or (line_no == 0 and next_blank)
            or (prev_blank and line_no == len(raw_lines) - 1)
        )
        if s.startswith("#") and len(s.lstrip("# ")) >= 2:
            # Markdown encodes the real nesting depth in the '#' count. Collapsing
            # every heading to chapter level threw away the document tree, so
            # parent/child (hierarchy) relations could never be produced.
            depth = len(s) - len(s.lstrip("#"))
            heading_rows.append((line_no, re.sub(r"^#+\s*", "", s), depth - 1, s))
            continue
        chapter_match = re.match(r"^第\s*\d+\s*章\s*(.*)$", s)
        if chapter_match:
            chapter_title = chapter_match.group(1).strip()
            if (
                semantic_heading
                and chapter_title
                and not re.fullmatch(r"[\d. /]+", chapter_title)
                and "/" not in chapter_title
                and not any(mark in s for mark in "。！？“”‘’；")
                and len(s) <= 60
            ):
                heading_rows.append((line_no, s, 0, s))
            continue
        appendix_match = re.match(r"^附录\s*[A-ZＡ-Ｚ一二三四五六七八九十0-9]+\s*(.*)$", s, re.I)
        if appendix_match:
            if (
                semantic_heading
                and appendix_match.group(1).strip()
                and not any(mark in s for mark in "。！？“”‘’；")
                and len(s) <= 60
            ):
                heading_rows.append((line_no, s, 0, s))
            continue
        m = re.match(r"^(\d+(?:\.\d+)*)\s+\S", s)
        if m:
            # Keep chapter, first-level and second-level section headings.
            # The latter is important for technical books: stopping at four
            # headings per chapter made the fallback look like a table of
            # contents teaser rather than a usable knowledge index.
            level = m.group(1).count(".")
            # A short heading may contain a colon, but prose-like quotes,
            # sentence punctuation, or a slash are strong signals that this is
            # a numbered paragraph/reference rather than a section title.
            looks_like_prose = any(mark in s for mark in "。！？“”‘’/；")
            if (
                semantic_heading
                and level <= 2
                and "." in m.group(1)
                and len(s) <= 60
                and not looks_like_prose
            ):
                heading_rows.append((line_no, s, level + 1, s))
            continue

        # EPUBs commonly use semantic h3/h4 headings without a numeric
        # prefix (for example “午餐一：可复制性” or “延迟限制带宽”). Once the
        # parser has preserved a real heading boundary, keep these short,
        # punctuation-light lines as leaf concepts too. Long/sentence-like
        # paragraphs remain excluded.
        if (
            semantic_heading
            and len(s) <= 60
            and not any(mark in s for mark in "。！？“”‘’/；")
            and not s.startswith(("http://", "https://", ">", "|"))
            # A blank-line-surrounded line that ends with a colon is a lead-in
            # label for the text below ("关键观测："), not a section title; a
            # punctuation-only line ("---") is a separator. Both used to become
            # pseudo headings that produced bogus structure edges.
            and not s.endswith(("：", ":"))
            and re.search(r"[^\W_]", s)
        ):
            # Unnumbered semantic headings are most often h3 leaf sections in
            # this EPUB family. Keeping them one level below numbered h2
            # headings preserves the useful chapter → subsection → leaf walk.
            heading_rows.append((line_no, s, 3, s))

    # De-duplicate repeated references that happen to look like headings. Keep
    # every real chapter and a bounded but broad set of sections per chapter;
    # this keeps the graph readable while retaining the book's structure.
    seen_headings: set[str] = set()
    unique_rows: list[tuple[int, str, int, str]] = []
    for row in heading_rows:
        key = row[1].lower()
        if key in seen_headings:
            continue
        seen_headings.add(key)
        unique_rows.append(row)
    chapter_rows = [row for row in unique_rows if row[2] == 0]
    if chapter_rows:
        selected_rows = []
        for index, chapter in enumerate(chapter_rows):
            selected_rows.append(chapter)
            start = chapter[0]
            end = chapter_rows[index + 1][0] if index + 1 < len(chapter_rows) else 10**12
            sections = [
                row for row in unique_rows
                if row[2] > 0 and start < row[0] < end
            ][:80]
            selected_rows.extend(sections)
    else:
        selected_rows = unique_rows[:80]
    concepts: list[Concept] = []
    name_to_id: dict[str, str] = {}
    structural_rows: list[tuple[str, int, str]] = []
    selected_names = {row[1] for row in selected_rows}

    def _first_sentence(p: str) -> str:
        return re.split(r"(?<=[。!?.!?])\s*", p)[0].strip()

    def _following_span(line_no: int) -> str:
        """Evidence for a heading: a verbatim (ideally unique) source slice.

        The old code kept only the first physical line, so code-fence markers
        such as ```powershell became "evidence" and repeated lines produced
        ambiguous anchors. Start at the first non-blank line that is neither a
        fence marker nor another heading, then extend downward (max 3 lines)
        until the slice occurs exactly once in the source. Slicing uses
        character offsets, so the quote is never re-joined text.
        """
        index = line_no + 1
        while index < len(raw_lines):
            candidate = raw_lines[index].strip()
            if not candidate or candidate.startswith(("```", "~~~")):
                index += 1
                continue
            if candidate in selected_names:
                return ""
            break
        if index >= len(raw_lines):
            return ""
        end = index
        while end < len(raw_lines) and end - index < 3:
            candidate = raw_lines[end].strip()
            if end > index and (
                not candidate
                or candidate.startswith(("```", "~~~"))
                or candidate in selected_names
            ):
                break
            end += 1
            span = text[
                line_starts[index] : line_starts[end - 1] + len(raw_lines[end - 1])
            ].strip()[:360]
            if span and text.count(span) == 1:
                return span
        span = text[
            line_starts[index] : line_starts[end - 1] + len(raw_lines[end - 1])
        ].strip()
        return span[:360]

    if selected_rows:
        current_chapter_title = ""
        for i, (line_no, h, _level, evidence_line) in enumerate(selected_rows):
            if _level == 0:
                current_chapter_title = h[:80]
            name = re.sub(r"^#+\s*", "", h).strip()
            name = re.sub(r"^\d+(\.\d+)*\s*", "", name).strip()
            name = re.sub(r"^第\s*\d+\s*章\s*", "", name).strip()
            name = name or f"章节 {i + 1}"
            cid = _new_id("c")
            name_to_id[name.lower()] = cid
            block = _following_span(line_no)
            ev = [block] if block else []
            if not ev and paragraphs:
                ev = [paragraphs[min(i, len(paragraphs) - 1)][:360]]
            concepts.append(
                Concept(
                    id=cid,
                    name=name,
                    definition=(
                        re.split(r"(?<=[。.!?])\s*", ev[0])[0][:200]
                        if ev else ""
                    ),
                    evidence=ev,
                    # The selected heading already carries its structural
                    # chapter. Set it directly instead of recovering it from
                    # evidence text, which may be repeated elsewhere in a
                    # book and otherwise jumps concepts into the wrong chapter.
                    chapter=current_chapter_title,
                )
            )
            structural_rows.append((cid, _level, evidence_line))
    else:
        # No headings: chunk the body into small groups of sentences so a long
        # single-block document (typical pasted/PDF text) still yields several
        # grounded concepts instead of one mega-chunk. Evidence is sliced from
        # the text through sentence offsets: joining sentences with spaces
        # produced strings that never occur in the source (0% locatable).
        sent_spans = [
            (m.start(), m.end()) for m in re.finditer(r"[^。!?.!?\n]+", text)
            if len(text[m.start() : m.end()].strip()) >= 8
        ]
        if len(sent_spans) > len(paragraphs):
            groups = [sent_spans[i : i + 3] for i in range(0, len(sent_spans), 3)][:10]
            blocks = [
                text[group[0][0] : group[-1][1]].strip()[:360] for group in groups
            ]
        else:
            blocks = [p[:360] for p in paragraphs[:10]]
        for i, block in enumerate(blocks):
            cid = _new_id("c")
            hint = _first_sentence(block)[:12].strip()
            name = (hint + "...") if len(_first_sentence(block)) > 12 else (hint or f"片段 {i + 1}")
            name_to_id[name.lower()] = cid
            concepts.append(
                Concept(id=cid, name=name, definition=_first_sentence(block)[:200], evidence=[block])
            )

    # Even without an LLM, heading nesting is a source-grounded relation:
    # the parent heading contains the following subsection. Preserve it so a
    # learner can walk from chapter -> section -> leaf instead of stopping at
    # the first overview row. Semantic relations still require the LLM path.
    relations: list[Relation] = []
    hierarchy_stack: list[tuple[int, str]] = []
    for cid, level, heading in structural_rows:
        while hierarchy_stack and hierarchy_stack[-1][0] >= level:
            hierarchy_stack.pop()
        if hierarchy_stack:
            parent_id = hierarchy_stack[-1][1]
            relations.append(
                Relation(
                    id=_new_id("r"),
                    source=parent_id,
                    target=cid,
                    label=_t("rel_part_of"),
                    type="contains",
                    evidence=heading,
                )
            )
        hierarchy_stack.append((level, cid))
    chapters = (
        [Chapter(id=_new_id("ch"), title=h, order=i) for i, h in enumerate(
            [h for _line, h, level, _ev in selected_rows if level == 0]
        )]
        if selected_rows
        else []
    )
    asset = KnowledgeAsset(
        asset_id=_new_id("a"),
        type=(filename.split(".")[-1] if "." in filename else "text").lower(),
        title=title_from(text, filename),
        source_name=filename,
        created_at=datetime.now(timezone.utc).isoformat(),
        source_text=text,
        chapters=chapters,
        concepts=concepts,
        relations=relations,
        learning_path=[c.id for c in concepts],
        method="deterministic_fallback_v1",
        provenance={"source": "deterministic_index", "llm": False,
                    "explicit_fallback": False},
    )
    asset = _assign_chapters(asset)
    return _stamp_locations(asset, page_offsets)


def extract_knowledge(
    text: str, filename: str, llm: LLMClient | None = None, on_progress=None,
    page_offsets: list[int] | None = None, domain_id: str | None = None,
) -> KnowledgeAsset:
    """Extract a knowledge model from ``text``.

    ``domain_id`` is passed through to the LLM path (``None`` = auto-detect from
    the title, ``""`` = force generic prompts).  The deterministic fallback is
    domain-agnostic on purpose: it must stay source-only.
    """
    if not text.strip():
        raise ValueError(_t("ext_no_content"))
    if llm is not None:
        try:
            return _extract_with_llm(
                text, filename, llm, on_progress=on_progress,
                page_offsets=page_offsets, domain_id=domain_id,
            )
        except Exception as exc:
            # Degrade gracefully: never fail the import on an LLM hiccup. But
            # never degrade *silently*: the reason is logged and stamped into
            # asset.provenance so callers and the UI can query it.
            reason = f"{type(exc).__name__}: {exc}"[:400]
            logger.warning(
                "extract_knowledge: LLM extraction failed, using explicit "
                "deterministic fallback (%s)", reason,
            )
            asset = _fallback(text, filename, page_offsets=page_offsets)
            asset.method = "llm_failed_fallback_v1"
            asset.provenance = {
                "source": "deterministic_fallback_after_llm_error",
                "llm": False,
                "explicit_fallback": True,
                "fallback_reason": reason,
            }
            if on_progress:
                on_progress("extract", 1, 1, _t("ext_llm_fallback"))
            return asset
    if on_progress:
        on_progress("extract", 1, 1, _t("ext_no_llm"))
    return _fallback(text, filename, page_offsets=page_offsets)
