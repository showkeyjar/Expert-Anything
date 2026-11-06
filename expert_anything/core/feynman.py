"""费曼复述自检 — 学习者用自己的话复述 vs 概念要点的确定性覆盖对照。

Feynman self-check (Part: deterministic comprehension check).  The learner
explains a concept in their own words; this module compares that explanation
against the concept's *own* evidence (or, failing that, the registered
template key points / definition) and reports — deterministically, with no
LLM and no invented content — how much of the concept was actually covered.

Why this matters: active recall ("explain it back") is the highest-yield
study technique, and the *gap* it surfaces ("you left out these points") is
the actionable part.  Everything here is a pure function of the learner's
text + the concept, so the GUI, the teaching loop and the tests share one
implementation.

Public entry point: :func:`coverage`.
"""
from __future__ import annotations

import unicodedata

from expert_anything.core import terminology

#: 一条要点被视为"讲到了"的最小字符二元组覆盖率。 0.4 已经足够宽松：复述
#: 即使换词，只要抓住要点的主要词语就能命中，而完全没提的要点几乎为 0。
POINT_COVERED = 0.4

#: 复述里出现核心概念名（未登记术语时的兜底）判定阈值。
NAME_MENTIONED = 0.5


def _content_chars(text: str) -> str:
    """有意义字符序列：NFKC + casefold + 仅保留字母/数字/汉字。"""
    norm = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(ch for ch in norm if ch.isalnum())


def _bigrams(chars: str) -> set[str]:
    """字符二元组集合（单字符文本退化为该字符本身）。"""
    if len(chars) < 2:
        return {chars} if chars else set()
    return {chars[i : i + 2] for i in range(len(chars) - 1)}


def _points(concept, domain_id: str) -> list[str]:
    """对照要点：优先原文证据，其次登记术语要点，最后概念定义。

    一律来自既有事实源（概念自身 / 领域模板），绝不新增内容——复述自检
    衡量的是"学习者覆盖了多少已经存在的要点"，不是系统另造的标准答案。
    """
    evidence = [
        str(e).strip()
        for e in (getattr(concept, "evidence", None) or [])
        if str(e).strip()
    ]
    if evidence:
        return evidence
    term = terminology.get_term(getattr(concept, "name", ""), domain_id)
    if term is not None and term.key_points:
        return [str(p) for p in term.key_points if str(p).strip()]
    definition = str(getattr(concept, "definition", "") or "").strip()
    return [definition] if definition else []


def _related_terms(concept, domain_id: str, limit: int = 3) -> list[dict]:
    """概念自身证据/定义里提到的、除本概念外的登记术语（可再提到的术语）。

    与 ``Tutor.enrich`` 的 related 逻辑同源：只在既有文本里做术语匹配，
    不推断、不新增。
    """
    term = terminology.get_term(getattr(concept, "name", ""), domain_id)
    haystack = "\n".join([
        str(getattr(concept, "definition", "") or ""),
        str(getattr(concept, "summary", "") or ""),
        *[str(e) for e in (getattr(concept, "evidence", None) or [])],
    ])
    out: list[dict] = []
    seen: set[str] = set()
    for hit in terminology.match_terms(haystack, domain_id):
        if term is not None and hit["id"] == term.id:
            continue
        if hit["id"] in seen:
            continue
        seen.add(hit["id"])
        out.append({"id": hit["id"], "name": hit["name"]})
        if len(out) >= limit:
            break
    return out


def coverage(
    text: str,
    concept,
    domain_id: str = terminology.DEFAULT_DOMAIN,
) -> dict:
    """对照学习者复述与概念要点的覆盖度（纯函数，无 LLM）。

    Returns a JSON-friendly dict:

    * ``coverage``        — 要点覆盖比例（0..1），无要点时为 0.0；
    * ``covered_count`` / ``point_count`` — 命中要点数 / 要点总数；
    * ``points``          — 每条要点 ``{text, overlap, covered}``（可显示进度）；
    * ``missed_points``   — 未覆盖要点原文（"还没讲到的要点"）；
    * ``matched_terms``   — 复述中出现的登记术语（含别名命中）；
    * ``self_name`` / ``self_mentioned`` — 核心术语名 / 是否被复述提到；
    * ``missed_terms``    — 概念语境里出现、但复述没提到的相关术语。
    """
    raw = str(text or "")
    text_bigrams = _bigrams(_content_chars(raw))

    rows: list[dict] = []
    for point in _points(concept, domain_id):
        p = _bigrams(_content_chars(point))
        overlap = (len(p & text_bigrams) / len(p)) if p else 0.0
        rows.append({
            "text": point,
            "overlap": round(overlap, 3),
            "covered": overlap >= POINT_COVERED,
        })

    covered = sum(1 for r in rows if r["covered"])
    total = len(rows)

    hits = terminology.match_terms(raw, domain_id)
    matched_ids = {h["id"] for h in hits}

    self_term = terminology.get_term(getattr(concept, "name", ""), domain_id)
    name = str(getattr(concept, "name", "") or "")
    if self_term is not None:
        self_name = self_term.name
        self_mentioned = self_term.id in matched_ids
    else:
        self_name = name
        name_bigrams = _bigrams(_content_chars(name))
        self_mentioned = bool(
            name
            and (
                name.lower() in raw.lower()
                or (
                    name_bigrams
                    and len(name_bigrams & text_bigrams) / len(name_bigrams)
                    >= NAME_MENTIONED
                )
            )
        )

    related = _related_terms(concept, domain_id)
    missed_terms = [r for r in related if r["id"] not in matched_ids]

    return {
        "coverage": round(covered / total, 3) if total else 0.0,
        "covered_count": covered,
        "point_count": total,
        "points": rows,
        "missed_points": [r["text"] for r in rows if not r["covered"]],
        "matched_terms": [
            {"id": h["id"], "name": h["name"], "matched": h["matched"]}
            for h in hits
        ],
        "self_name": self_name,
        "self_mentioned": self_mentioned,
        "missed_terms": missed_terms,
    }


__all__ = ["POINT_COVERED", "coverage"]
