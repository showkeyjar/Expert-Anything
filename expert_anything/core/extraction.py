"""Knowledge extraction.

Primary path uses an LLM to produce *source-grounded* concepts, relations
and an ordered learning path. The fallback is a deterministic heuristic used
only when no LLM key is configured -- it is explicitly marked so the UI can
warn the user that depth is limited.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from expert_anything.core.llm import LLMClient, Message, chat_json
from expert_anything.core.models import (
    Chapter,
    Concept,
    KnowledgeAsset,
    Relation,
    SourceLocation,
)
from expert_anything.core.parsers import title_from


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


SYSTEM_PROMPT = (
    "你是严谨的知识建模助手。阅读用户提供的内容，抽取结构化知识。\n"
    "铁律：\n"
    "1. 只基于原文，绝不编造原文没有的概念、事实或术语。\n"
    "2. 每个概念的 name（概念名）必须是【原文里真实出现的词或短语】，逐字照搬，不要改写、不要概括、不要自己造词。\n"
    "3. 每个概念的 definition 必须是【一句】基于原文证据的简要定义（不超过 40 字），不得引入原文之外的知识。\n"
    "4. 每个概念的 evidence 必须是【原文中真实存在的连续句子片段】，直接复制原文，不要改写、不要翻译、不要拼接。\n"
    "5. relations 只描述原文中确实存在的关系（依赖/包含/对比/因果/顺序/流程先后），label 用中文短句，evidence 同样是原文片段。"
    "技术类书籍请特别标注机制/流程上的依赖关系（如 A 是 B 的前置步骤）。\n"
    "6. 每个概念尽量给出 chapter（它主要出现在哪一章/哪一节，用章节标题原文）。\n"
    "7. learning_path 是按‘先修→后修’顺序排列的概念名列表，从基础到进阶。\n"
    "只输出 JSON，不要任何解释或前缀。"
)

USER_TEMPLATE = (
    "请对以下内容建模：\n\n{text}\n\n"
    "输出 JSON，结构：\n"
    "{{\n"
    '  "chapters": [{{"title": "章节标题"}}],\n'
    '  "concepts": [{{"name": "原文里真实出现的概念名", "definition": "一句基于证据的定义（≤40字）", '
    '"chapter": "所属章节标题（原文）", '
    '"evidence": ["原文连续句子片段1", "原文连续句子片段2"]}}],\n'
    '  "relations": [{{"source": "概念名A", "target": "概念名B", '
    '"label": "关系说明", "evidence": "原文片段"}}],\n'
    '  "learning_path": ["概念名1", "概念名2", ...]\n'
    "}}\n"
    "要求：concepts 不超过 15 个且必须是本节最核心的概念（宁多勿漏，可含子概念）；"
    "所有 name 必须逐字出自原文；所有 evidence 必须是原文连续片段；"
    "每个概念给出 chapter（所属章节标题，取自原文）；"
    "relations 尽量完整（依赖/包含/对比/因果/流程先后都算），label 用中文短句；"
    "若某概念在原文中找不到支撑句，就不要把它作为概念列出。"
)


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
        for sent in re.split(r"(?<=[。！？.!?])\s+|\n+", text):
            if needle in sent.lower():
                return [sent.strip()[:360]]
    return []


def _parse_json(text: str) -> dict:
    """Tolerant JSON extraction from an LLM response.

    Many OpenAI-compatible endpoints wrap JSON in ```json fences or include
    prose around it. A naive json.loads would throw and — because
    extract_knowledge swallows exceptions — silently fall back to the
    placeholder heuristic, which is exactly the 'everything is empty' bug.
    So we strip fences and grab the outermost {...} block before parsing.
    """
    if not text:
        return {}
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _as_str(v) -> str:
    """Coerce an LLM-returned field to a clean string.

    The model sometimes emits a list where the schema expects a string
    (e.g. ``"name": ["A", "B"]``). Naive ``.strip()`` then raises
    AttributeError and — because extract_knowledge swallows all exceptions —
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
    text: str, filename: str, llm: LLMClient, on_progress=None
) -> KnowledgeAsset:
    """Single- or multi-call extraction.

    For short inputs one call is enough. For long inputs (e.g. a whole book)
    we split into overlapping chunks, extract each, then merge concepts by
    normalized name and resolve relations against the merged id map. This both
    improves coverage (the previous 12k-char hard cut dropped later chapters)
    and lets us dedupe across chunks.

    `on_progress(stage, current, total, message)` is called to drive a progress
    bar in the UI so long extractions do not look like a freeze.
    """
    CHUNK = 9000
    OVERLAP = 600
    if len(text) <= CHUNK + OVERLAP:
        if on_progress:
            on_progress("extract", 0, 1, "正在分析文本，抽取概念、关系与学习路径…")
        data = _call_extract(llm, text[: CHUNK + OVERLAP])
        if not data:
            raise ValueError("LLM 返回无法解析为 JSON")
        asset = _assemble(data, text, filename, method="llm_extraction_v1")
        if on_progress:
            on_progress(
                "extract", 1, 1,
                f"已抽取 {len(asset.concepts)} 个概念、{len(asset.relations)} 条关系",
            )
        return asset

    merged: dict = {"concepts": [], "relations": [], "learning_path": []}
    seen: set[str] = set()
    chunks = _split_text(text, CHUNK, OVERLAP)
    total = len(chunks)
    if on_progress:
        on_progress("extract", 0, total, f"开始逐段分析（共 {total} 段，并行处理）…")
    # Run chunk extractions concurrently (bounded pool) so wall-clock time drops
    # roughly by the worker count instead of doing N serial LLM calls. Each worker
    # only reads its chunk + the shared (stateless) client; results are merged
    # back in the main thread via as_completed, so there is no shared-state race.
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        futures = [pool.submit(_call_extract, llm, ch) for ch in chunks]
        for fut in concurrent.futures.as_completed(futures):
            d = fut.result() if not fut.exception() else None
            if d:
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
                for r in d.get("relations", []):
                    merged["relations"].append(r)
                for p in d.get("learning_path", []):
                    if (p or "").strip() and (p.strip() not in merged["learning_path"]):
                        merged["learning_path"].append(p.strip())
            done += 1
            if on_progress:
                on_progress(
                    "extract", done, total,
                    f"已分析 {done}/{total} 段，累计 {len(merged['concepts'])} 个概念…",
                )
    if not merged["concepts"]:
        raise ValueError("所有分块都未能解析为 JSON")
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
    asset = _assemble(merged, text, filename, method="llm_extraction_chunked_v1")
    if on_progress:
        on_progress(
            "extract", total, total,
            f"已完成抽取：{len(asset.concepts)} 个概念、{len(asset.relations)} 条关系",
        )
    return asset


def _call_extract(llm: LLMClient, snippet: str) -> dict:
    return chat_json(
        llm,
        [
            Message("system", SYSTEM_PROMPT),
            Message("user", USER_TEMPLATE.format(text=snippet)),
        ],
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
    heading line (``1.2 Some Title`` style) becomes the chapter. If the text
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
        if re.match(r"^\d+(\.\d+)*\s+[A-Za-z]", s) and len(s) < 80 and not s.startswith("http"):
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


def _stamp_locations(asset: "KnowledgeAsset") -> "KnowledgeAsset":
    """Record each concept's evidence position in the raw source text.

    For every grounded evidence snippet we store its character offset in
    ``source_text``, derive the 1-based line number, and attach the concept's
    chapter. This powers a truthful 'source location' label and a precise jump
    in the reader. Works on both LLM and deterministic-fallback assets because
    evidence is always grounded in the source.
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
                )
            )
        c.locations = locs
    return asset


def _assemble(data: dict, text: str, filename: str, method: str) -> KnowledgeAsset:
    concepts: list[Concept] = []
    name_to_id: dict[str, str] = {}
    lowered = text.lower()
    for c in data.get("concepts", []):
        name = _as_str(c.get("name"))
        if not name:
            continue
        evidence = _ground_evidence(text, _as_str_list(c.get("evidence")), name)
        # Hallucination guard: drop concepts whose name does not appear in the
        # source AND have no grounded evidence. They are almost certainly
        # invented terms the model slipped in despite the prompt.
        if not evidence and _norm(name) not in lowered:
            continue
        cid = _new_id("c")
        name_to_id[_norm(name)] = cid
        definition = _as_str(c.get("definition"))
        # If the model gave no definition but we have evidence, derive a stub
        # from the first evidence sentence instead of leaving it empty.
        if not definition and evidence:
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
        if s in name_to_id and t in name_to_id and s != t:
            relations.append(
                Relation(
                    id=_new_id("r"),
                    source=name_to_id[s],
                    target=name_to_id[t],
                    label=_as_str(r.get("label")),
                    type="related",
                    evidence=_as_str(r.get("evidence")),
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
    return _stamp_locations(asset)


# --- Deterministic fallback (no LLM) -----------------------------------------
def _fallback(text: str, filename: str) -> KnowledgeAsset:
    """No-LLM structural index.

    The old fallback invented placeholder concept names ("核心概念"/"实践与反馈")
    that never appeared in the source, so definitions, evidence and relations all
    came out empty — which is exactly the "everything is empty" complaint. This
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
        paragraphs = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s+", text) if len(s.strip()) >= 20]

    heading_lines = [
        l.strip()
        for l in text.splitlines()
        if (l.startswith("#") and 2 <= len(l.strip()) <= 80)
        or re.match(r"^\d+(\.\d+)*\s+[A-Za-z一-鿿]", l.strip())
    ]

    concepts: list[Concept] = []
    name_to_id: dict[str, str] = {}

    def _first_sentence(p: str) -> str:
        return re.split(r"(?<=[。！？.!?])\s*", p)[0].strip()

    if heading_lines:
        for i, h in enumerate(heading_lines[:12]):
            name = re.sub(r"^#+\s*", "", h).strip()
            name = re.sub(r"^\d+(\.\d+)*\s*", "", name).strip() or f"章节 {i + 1}"
            cid = _new_id("c")
            name_to_id[name.lower()] = cid
            ev = [s[:360] for s in paragraphs if name[:4] and name[:4].lower() in s.lower()][:3]
            if not ev and paragraphs:
                ev = [paragraphs[min(i, len(paragraphs) - 1)][:360]]
            concepts.append(
                Concept(
                    id=cid,
                    name=name,
                    definition=(ev[0][:200] if ev else ""),
                    evidence=ev,
                )
            )
    else:
        # No headings: chunk the body into small groups of sentences so a long
        # single-block document (typical pasted/PDF text) still yields several
        # grounded concepts instead of one mega-chunk.
        sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s+|\n+", text) if len(s.strip()) >= 8]
        if len(sentences) > len(paragraphs):
            chunks = [sentences[i : i + 3] for i in range(0, len(sentences), 3)][:10]
        else:
            chunks = paragraphs[:10]
        for i, chunk in enumerate(chunks):
            block = " ".join(chunk) if isinstance(chunk, list) else chunk
            cid = _new_id("c")
            hint = _first_sentence(block)[:12].strip()
            name = (hint + "…") if len(_first_sentence(block)) > 12 else (hint or f"片段 {i + 1}")
            name_to_id[name.lower()] = cid
            concepts.append(
                Concept(id=cid, name=name, definition=_first_sentence(block)[:200], evidence=[block[:360]])
            )

    # Relations need semantic understanding -> only meaningful with an LLM.
    relations: list[Relation] = []
    chapters = (
        [Chapter(id=_new_id("ch"), title=h, order=i) for i, h in enumerate(heading_lines[:12])]
        if heading_lines
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
    return _stamp_locations(asset)


def extract_knowledge(
    text: str, filename: str, llm: LLMClient | None = None, on_progress=None
) -> KnowledgeAsset:
    if not text.strip():
        raise ValueError("请提供材料内容")
    if llm is not None:
        try:
            return _extract_with_llm(text, filename, llm, on_progress=on_progress)
        except Exception:
            # Degrade gracefully: never fail the import on an LLM hiccup.
            asset = _fallback(text, filename)
            asset.method = "llm_failed_fallback_v1"
            if on_progress:
                on_progress("extract", 1, 1, "LLM 抽取失败，已降级为确定性结构索引")
            return asset
    if on_progress:
        on_progress("extract", 1, 1, "未配置 LLM，使用确定性结构索引（无需联网）")
    return _fallback(text, filename)
