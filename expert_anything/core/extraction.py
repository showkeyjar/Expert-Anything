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
import re
from datetime import datetime, timezone
from uuid import uuid4

from expert_anything.core.llm import LLMClient, Message, parse_llm_json, chat_json
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
        data = _call_extract(
            llm, text[: CHUNK + OVERLAP],
            domain_id=domain_id, concept_skeleton=concept_skeleton,
        )
        if not data:
            raise ValueError(_t("ext_llm_failed"))
        asset = _assemble(data, text, filename, method="llm_extraction_v1",
                         page_offsets=page_offsets)
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        # Bind the domain prompt inputs with partial() so the executor keeps
        # receiving the same (fn, llm, chunk) call shape as before.
        extract_chunk = functools.partial(
            _call_extract, domain_id=domain_id, concept_skeleton=concept_skeleton,
        )
        futures = {
            pool.submit(extract_chunk, llm, chunk): index
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
    if not merged["concepts"]:
        raise ValueError(_t("ext_chunks_failed"))
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
    if on_progress:
        on_progress(
            "extract", total, total,
            _t("ext_chunks_done", n=len(asset.concepts), r=len(asset.relations)),
        )
    return asset


def _call_extract(
    llm: LLMClient, snippet: str,
    domain_id: str | None = None, concept_skeleton: str = "",
) -> dict:
    """One extraction call.

    With a detected ``domain_id`` that has a registered prompt variant, the
    domain-specific system/user prompts are used and the template's concept
    skeleton is injected as *alignment guidance*.  Otherwise the generic prompts
    are used and the request is byte-identical to the pre-Phase-3 behaviour.

    Grounding is enforced entirely in :func:`_assemble` (verbatim evidence,
    hallucinated concepts dropped); a domain prompt never relaxes those checks,
    and the skeleton is explicitly labelled as "not a knowledge source" there.
    """
    system = get_domain_prompt("extraction_system", domain_id)
    user = get_domain_prompt("extraction_user", domain_id).format(
        chunk_text=snippet, concept_skeleton=concept_skeleton
    )
    return chat_json(
        llm,
        [Message("system", system), Message("user", user)],
        temperature=0.2,
        max_tokens=1500,
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
    for r in data.get("relations", []):
        s, t = _norm(r.get("source", "")), _norm(r.get("target", ""))
        relation_evidence = _as_str(r.get("evidence"))
        # Relations affect the graph, prerequisite order and adaptive path, so
        # accepting an unsupported edge is more harmful than omitting one.
        # Require the LLM-provided evidence to be a verbatim source span, just
        # as concept evidence is required to be grounded.
        if (
            s in name_to_id
            and t in name_to_id
            and s != t
            and relation_evidence
            and relation_evidence in text
        ):
            relations.append(
                Relation(
                    id=_new_id("r"),
                    source=name_to_id[s],
                    target=name_to_id[t],
                    label=_as_str(r.get("label")),
                    type=_as_str(r.get("type")) or "related",
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
    heading_rows: list[tuple[int, str, int]] = []
    for line_no, raw_line in enumerate(raw_lines):
        s = raw_line.strip()
        if not s or len(s) > 100:
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
            heading_rows.append((line_no, re.sub(r"^#+\s*", "", s), 0))
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
                heading_rows.append((line_no, s, 0))
            continue
        appendix_match = re.match(r"^附录\s*[A-ZＡ-Ｚ一二三四五六七八九十0-9]+\s*(.*)$", s, re.I)
        if appendix_match:
            if (
                semantic_heading
                and appendix_match.group(1).strip()
                and not any(mark in s for mark in "。！？“”‘’；")
                and len(s) <= 60
            ):
                heading_rows.append((line_no, s, 0))
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
                heading_rows.append((line_no, s, level + 1))
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
            and not s.startswith(("http://", "https://"))
        ):
            # Unnumbered semantic headings are most often h3 leaf sections in
            # this EPUB family. Keeping them one level below numbered h2
            # headings preserves the useful chapter → subsection → leaf walk.
            heading_rows.append((line_no, s, 3))

    # De-duplicate repeated references that happen to look like headings. Keep
    # every real chapter and a bounded but broad set of sections per chapter;
    # this keeps the graph readable while retaining the book's structure.
    seen_headings: set[str] = set()
    unique_rows: list[tuple[int, str, int]] = []
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
    heading_lines = [row[1] for row in selected_rows]

    concepts: list[Concept] = []
    name_to_id: dict[str, str] = {}
    structural_rows: list[tuple[str, int, str]] = []

    def _first_sentence(p: str) -> str:
        return re.split(r"(?<=[。!?.!?])\s*", p)[0].strip()

    if selected_rows:
        current_chapter_title = ""
        for i, (line_no, h, _level) in enumerate(selected_rows):
            if _level == 0:
                current_chapter_title = h[:80]
            name = re.sub(r"^#+\s*", "", h).strip()
            name = re.sub(r"^\d+(\.\d+)*\s*", "", name).strip()
            name = re.sub(r"^第\s*\d+\s*章\s*", "", name).strip()
            name = name or f"章节 {i + 1}"
            cid = _new_id("c")
            name_to_id[name.lower()] = cid
            # Evidence should describe the selected heading's nearby section,
            # not repeat the first paragraph of the whole book for every node.
            following: list[str] = []
            for next_line in raw_lines[line_no + 1:]:
                candidate = next_line.strip()
                if not candidate:
                    if following:
                        break
                    continue
                if any(candidate == other[1] for other in selected_rows):
                    break
                following.append(candidate)
                if len(" ".join(following)) >= 360:
                    break
            # Keep the first physical source line as evidence. Joining several
            # XHTML lines would create text that is not literally present in
            # source_text and would break source-location highlighting.
            block = following[0].strip() if following else ""
            ev = [block[:360]] if block else []
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
            structural_rows.append((cid, _level, h))
    else:
        # No headings: chunk the body into small groups of sentences so a long
        # single-block document (typical pasted/PDF text) still yields several
        # grounded concepts instead of one mega-chunk.
        sentences = [s.strip() for s in re.split(r"(?<=[。!?.!?])\s+|\n+", text) if len(s.strip()) >= 8]
        if len(sentences) > len(paragraphs):
            chunks = [sentences[i : i + 3] for i in range(0, len(sentences), 3)][:10]
        else:
            chunks = paragraphs[:10]
        for i, chunk in enumerate(chunks):
            block = " ".join(chunk) if isinstance(chunk, list) else chunk
            cid = _new_id("c")
            hint = _first_sentence(block)[:12].strip()
            name = (hint + "...") if len(_first_sentence(block)) > 12 else (hint or f"片段 {i + 1}")
            name_to_id[name.lower()] = cid
            concepts.append(
                Concept(id=cid, name=name, definition=_first_sentence(block)[:200], evidence=[block[:360]])
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
            [h for _line, h, level in selected_rows if level == 0]
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
        except Exception:
            # Degrade gracefully: never fail the import on an LLM hiccup.
            asset = _fallback(text, filename, page_offsets=page_offsets)
            asset.method = "llm_failed_fallback_v1"
            if on_progress:
                on_progress("extract", 1, 1, _t("ext_llm_fallback"))
            return asset
    if on_progress:
        on_progress("extract", 1, 1, _t("ext_no_llm"))
    return _fallback(text, filename, page_offsets=page_offsets)
