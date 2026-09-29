"""Cross-asset full-text search over knowledge assets.

Search scope: concept name (exact/prefix first), aliases, definition, summary,
evidence snippets, and the raw source text (via SourceLocation anchors).
Returns ranked hits with a human-readable snippet and a chapter/page anchor so
the UI can jump straight to the passage. Fully deterministic — no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from expert_anything.core.models import KnowledgeAsset

# Field ranks: name matches win, then definitions, then evidence/summary/source.
_FIELD_ORDER = ["name", "alias", "definition", "summary", "evidence", "source"]

# Maximum hits returned per field type (keeps the UI list bounded).
_MAX_PER_FIELD = 12
_MAX_TOTAL = 40

_SNIPPET_RADIUS = 70  # characters around the match in long texts
_SNIPPET_ELLIPSIS = "…"


@dataclass
class SearchHit:
    """One matched concept with the context where the keyword was found."""

    asset_id: str
    asset_title: str
    concept_id: str
    concept_name: str
    field: str  # name / alias / definition / summary / evidence / source
    snippet: str  # human-readable context around the match
    chapter: str = ""  # owning chapter ('' if unknown)
    page: int | None = None  # 1-based page (PDF only, None otherwise)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "asset_title": self.asset_title,
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "field": self.field,
            "snippet": self.snippet,
            "chapter": self.chapter,
            "page": self.page,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SearchHit":
        return cls(
            asset_id=d.get("asset_id", ""),
            asset_title=d.get("asset_title", ""),
            concept_id=d.get("concept_id", ""),
            concept_name=d.get("concept_name", ""),
            field=d.get("field", "source"),
            snippet=d.get("snippet", ""),
            chapter=d.get("chapter", ""),
            page=d.get("page"),
        )


def _lower(text: str) -> str:
    return (text or "").lower()


def _snippet(text: str, keyword: str, radius: int = _SNIPPET_RADIUS) -> str:
    """Center a window of ±radius chars around the first keyword occurrence."""
    text = (text or "").strip()
    if not text:
        return ""
    pos = _lower(text).find(_lower(keyword))
    if pos < 0:
        # Keyword not in this text (caller should have checked) — return head.
        return text if len(text) <= radius * 2 else text[:radius] + _SNIPPET_ELLIPSIS
    start = max(0, pos - radius)
    end = min(len(text), pos + len(keyword) + radius)
    prefix = _SNIPPET_ELLIPSIS if start > 0 else ""
    suffix = _SNIPPET_ELLIPSIS if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def search_assets(
    assets: Iterable[KnowledgeAsset],
    keyword: str,
    limit: int = _MAX_TOTAL,
) -> list[SearchHit]:
    """Search concepts across assets by keyword in name/alias/definition/
    summary/evidence/source-text. Results are ranked: name > alias > definition
    > summary > evidence > source-text passages.

    ``assets`` may be a dict (asset_id -> asset), a list, or any iterable.
    """
    kw = (keyword or "").strip()
    if not kw:
        return []

    from expert_anything.core.domain_templates import concept_name_variants

    hits: list[SearchHit] = []
    seen: set[tuple[str, str, str]] = set()  # (concept_id, field, snippet)

    def add(asset, concept, field, snippet, chapter="", page=None):
        key = (concept.id, field, snippet)
        if key in seen:
            return
        seen.add(key)
        hits.append(
            SearchHit(
                asset_id=asset.asset_id,
                asset_title=asset.title or asset.source_name or asset.asset_id,
                concept_id=concept.id,
                concept_name=concept.name,
                field=field,
                snippet=snippet,
                chapter=chapter or concept.chapter,
                page=page,
            )
        )

    if isinstance(assets, dict):
        assets = assets.values()

    for asset in assets:
        title = asset.title or asset.source_name or asset.asset_id
        for concept in asset.concepts or []:
            # 1) name — the strongest signal
            if kw.lower() in concept.name.lower():
                add(asset, concept, "name", concept.name)
                continue  # name hit dominates; skip weaker fields for clarity
            # 2) aliases (from domain templates / terminology normalization)
            for alias in concept_name_variants(concept.name):
                if kw.lower() in alias.lower():
                    add(asset, concept, "alias", f"{concept.name}（{alias}）")
                    break
            # 3) definition
            if kw.lower() in concept.definition.lower():
                add(asset, concept, "definition", _snippet(concept.definition, kw))
            # 4) summary
            if kw.lower() in concept.summary.lower():
                add(asset, concept, "summary", _snippet(concept.summary, kw))
            # 5) evidence list (bounded)
            ev_hits = 0
            for ev in concept.evidence or []:
                if kw.lower() in ev.lower():
                    page = None
                    # Only use a loc page if it aligns with a real source page.
                    if concept.locations and ev.strip():
                        for loc in concept.locations:
                            if (
                                ev[:60].strip()
                                and ev.strip()[:60] == (loc.snippet or "")[:60]
                            ):
                                page = loc.page
                                break
                    add(asset, concept, "evidence", _snippet(ev, kw), page=page)
                    ev_hits += 1
                    if ev_hits >= 3:
                        break
            # 6) source-text passages (only via stored SourceLocation anchors)
            if concept.locations:
                src_hits = 0
                for loc in concept.locations:
                    if kw.lower() in (loc.snippet or "").lower():
                        add(
                            asset,
                            concept,
                            "source",
                            _snippet(loc.snippet, kw),
                            chapter=loc.chapter or concept.chapter,
                            page=loc.page,
                        )
                        src_hits += 1
                        if src_hits >= 2:
                            break

    # Rank by field order, then keep first occurrences stable.
    hits.sort(key=lambda h: _FIELD_ORDER.index(h.field))
    return hits[:limit]


def search_assets_by_name(
    assets: Iterable[KnowledgeAsset], keyword: str
) -> list[SearchHit]:
    """Quick name-only search (used by the map toolbar's fast-path)."""
    kw = (keyword or "").strip().lower()
    if not kw:
        return []
    if isinstance(assets, dict):
        assets = assets.values()
    out: list[SearchHit] = []
    for asset in assets:
        for concept in asset.concepts or []:
            if kw in concept.name.lower():
                out.append(
                    SearchHit(
                        asset_id=asset.asset_id,
                        asset_title=asset.title or asset.source_name or asset.asset_id,
                        concept_id=concept.id,
                        concept_name=concept.name,
                        field="name",
                        snippet=concept.name,
                        chapter=concept.chapter,
                    )
                )
    return out
