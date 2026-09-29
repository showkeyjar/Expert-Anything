"""Terminology cross-reference table, sourced exclusively from domain templates.

Phase 4 — deterministic user guidance (part 1/2).

``core/domain_templates.py`` is the **only** source of terminology in this
module: every term returned from here is a concept a template has registered,
so an unregistered (invented, guessed or fetched) term can never be produced.
The module is pure — no LLM, no network, no disk writes — which lets the
teaching loop, the GUI and the tests share one implementation.

Public entry points (all deterministic pure functions):

``get_term``             look a concept up by reference: template concept ID
                         (``et-013``), canonical name, or any registered alias
``match_terms``          find every registered term occurring in a free text,
                         reporting character offsets into the original string
``bidirectional_table``  alias -> canonical name **and** canonical name ->
                         registered aliases, both directions

Supporting helpers: :func:`iter_terms`, :func:`term_by_id`,
:func:`terms_for_text`, :func:`glossary`, :func:`stats`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from expert_anything.core.domain_templates import (
    DomainTemplate,
    concept_name_variants,
    get_domain_template,
    resolve_template_concept_id,
)

#: Domain used when the caller does not name one (the first domain pack).
DEFAULT_DOMAIN = "electricity_trading"

#: Bracket styles used by the templates to record an alias next to the name
#: (``节点边际电价(LMP)``, ``节点边际电价（LMP）``, ``节点边际电价[LMP]`` ...).
_PARENTHETICAL_RE = re.compile(r"[（(\[【]([^）)\]】]*)[）)\]】]")

#: Minimum length of a match variant — single letters are too ambiguous to
#: match on inside free text.
MIN_VARIANT_LENGTH = 2


@dataclass(frozen=True)
class Term:
    """One registered terminology entry.

    Every field is copied verbatim from the template concept it was built
    from — this class never synthesises content.
    """

    id: str
    name: str
    chapter_id: str = ""
    chapter_title: str = ""
    definition: str = ""
    evidence: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    significance: str = ""
    misconceptions: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()

    @property
    def key_points(self) -> tuple[str, ...]:
        """释义要点: original-text evidence first, then the significance note."""
        points = tuple(self.evidence)
        if points:
            return points
        return (self.significance,) if self.significance else ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "chapter_id": self.chapter_id,
            "chapter_title": self.chapter_title,
            "definition": self.definition,
            "evidence": list(self.evidence),
            "aliases": list(self.aliases),
            "significance": self.significance,
            "misconceptions": list(self.misconceptions),
            "prerequisites": list(self.prerequisites),
            "key_points": list(self.key_points),
        }


# --------------------------------------------------------------------------- #
# internal helpers
# --------------------------------------------------------------------------- #

def _match_key(value: str) -> str:
    """Free-text matching key: NFKC + casefold + no whitespace.

    Punctuation is *kept*, unlike the concept-identity key
    (``domain_templates._normalize_name``): text matching needs the brackets
    of ``节点边际电价(LMP)`` to line up with the text, and only whitespace
    differences (``节点边际电价 (LMP)``) must be tolerated.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).casefold()


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize ``text`` for matching while remembering source indices.

    Returns ``(normalized, index_map)`` where ``index_map[i]`` is the index in
    the original string of ``normalized[i]`` — so a hit on the normalized
    string can be sliced back out of the original text (whitespace is dropped,
    NFKC expansion maps every produced character to its source character).
    """
    chars: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        expanded = unicodedata.normalize("NFKC", ch)
        for c in expanded:
            if c.isspace():
                continue
            chars.append(c.casefold())
            index_map.append(i)
    return "".join(chars), index_map


def _match_variants(name: str) -> set[str]:
    """All spellings of ``name`` that may occur inside free text.

    ``节点边际电价(LMP)`` yields the full spelling, the spelling without the
    parenthetical part (``节点边际电价``) and the parenthetical body itself
    (``lmp``) — the last only when long enough to be unambiguous.
    """
    raw = unicodedata.normalize("NFKC", str(name or ""))
    variants = {_match_key(raw), _match_key(_PARENTHETICAL_RE.sub("", raw))}
    for inner in _PARENTHETICAL_RE.findall(raw):
        variants.add(_match_key(inner))
    return {v for v in variants if len(v) >= MIN_VARIANT_LENGTH}


def _declared_aliases(data: dict) -> list[str]:
    """Aliases a template concept declares: bracketed part + ``aliases`` list.

    Header-free, deterministic: returns the *original* alias spellings the
    template records (``节点边际电价(LMP)`` -> ``LMP``) so they can be shown
    and looked up in both directions.  Candidates whose matching key equals the
    concept's own full or bare name are dropped (an alias that only restates
    the canonical name is noise), as are single-character bodies.
    """
    raw_name = unicodedata.normalize("NFKC", str(data.get("name", "")))
    seen = {_match_key(raw_name), _match_key(_PARENTHETICAL_RE.sub("", raw_name))}
    candidates = [inner.strip() for inner in _PARENTHETICAL_RE.findall(raw_name)]
    candidates += [str(alias).strip() for alias in (data.get("aliases") or [])]

    out: list[str] = []
    for candidate in candidates:
        key = _match_key(candidate)
        if len(key) < MIN_VARIANT_LENGTH or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


# --------------------------------------------------------------------------- #
# term construction
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=None)
def iter_terms(domain_id: str = DEFAULT_DOMAIN) -> tuple[Term, ...]:
    """All terms registered by ``domain_id``, in template order.

    Returns ``()`` for an unknown domain — no template, no terminology.
    """
    template = get_domain_template(domain_id)
    if template is None:
        return ()
    terms: list[Term] = []
    for chapter in template.chapters:
        chapter_id = str(chapter.get("id", ""))
        chapter_title = str(chapter.get("title", ""))
        for data in chapter.get("concepts", []) or []:
            term_id = str(data.get("id", "") or "")
            if not term_id:
                continue
            terms.append(Term(
                id=term_id,
                name=str(data.get("name", "")),
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                definition=str(data.get("definition", "")),
                evidence=tuple(str(e) for e in (data.get("evidence") or [])),
                aliases=tuple(_declared_aliases(data)),
                significance=str(data.get("significance", "")),
                misconceptions=tuple(str(m) for m in (data.get("misconceptions") or [])),
                prerequisites=tuple(str(p) for p in (data.get("prerequisites") or [])),
            ))
    return tuple(terms)


def term_by_id(term_id: str, domain_id: str = DEFAULT_DOMAIN) -> Term | None:
    """Look a term up by its template concept ID (``et-013``)."""
    ref = str(term_id or "").strip()
    if not ref:
        return None
    for term in iter_terms(domain_id):
        if term.id == ref:
            return term
    return None


def get_term(concept_ref, domain_id: str = DEFAULT_DOMAIN) -> Term | None:
    """按概念查询 — resolve any concept reference to its registered term.

    ``concept_ref`` may be a template concept ID (``et-013``), the canonical
    name (``节点边际电价(LMP)`` / ``节点边际电价``) or any registered alias
    (``LMP``), insensitive to case, width and separators.  Returns ``None``
    when the template does not register the reference — nothing is guessed.
    """
    ref = str(concept_ref or "").strip()
    if not ref:
        return None
    term_id = resolve_template_concept_id(ref, None, domain_id)
    if not term_id:
        return None
    return term_by_id(term_id, domain_id)


def terms_for_concept(concept_ref, domain_id: str = DEFAULT_DOMAIN) -> list[Term]:
    """Alias of :func:`get_term` returning a list, for pipeline friendliness."""
    term = get_term(concept_ref, domain_id)
    return [term] if term is not None else []


# --------------------------------------------------------------------------- #
# free-text matching
# --------------------------------------------------------------------------- #

def match_terms(text: str, domain_id: str = DEFAULT_DOMAIN) -> list[dict]:
    """按文本匹配术语 — every registered term occurring in ``text``.

    Longest spelling wins: a variant is only reported when its span is not
    already claimed by a longer variant, so ``节点边际电价(LMP)`` inside the
    text does not also produce a bare ``LMP`` hit on the same characters.

    Each hit is a dict with ``id`` / ``name`` / ``chapter_title`` /
    ``definition`` / ``aliases`` plus ``matched`` (the text actually matched)
    and ``start`` / ``end`` (offsets into the original ``text``).  No match
    yields ``[]``.
    """
    raw = str(text or "")
    if not raw:
        return []
    normalized, index_map = _normalize_with_map(raw)
    if not normalized:
        return []

    candidates: list[tuple[str, Term]] = []
    seen: set[tuple[str, str]] = set()
    for term in iter_terms(domain_id):
        for variant in (term.name, *term.aliases):
            for spelling in _match_variants(variant):
                pair = (spelling, term.id)
                if pair in seen:
                    continue
                seen.add(pair)
                candidates.append((spelling, term))
    candidates.sort(key=lambda item: (-len(item[0]), item[1].id))

    claimed = [False] * len(normalized)
    hits: list[dict] = []
    for spelling, term in candidates:
        start = normalized.find(spelling)
        while start != -1:
            end = start + len(spelling)
            if not any(claimed[start:end]):
                for i in range(start, end):
                    claimed[i] = True
                src_start = index_map[start]
                src_end = index_map[end - 1] + 1
                hits.append({
                    "id": term.id,
                    "name": term.name,
                    "matched": raw[src_start:src_end],
                    "start": src_start,
                    "end": src_end,
                    "chapter_id": term.chapter_id,
                    "chapter_title": term.chapter_title,
                    "definition": term.definition,
                    "aliases": list(term.aliases),
                })
            start = normalized.find(spelling, start + 1)

    hits.sort(key=lambda hit: (hit["start"], -hit["end"]))
    return hits


def terms_for_text(text: str, domain_id: str = DEFAULT_DOMAIN) -> list[Term]:
    """Registered terms mentioned in ``text``, deduplicated, in text order."""
    out: list[Term] = []
    seen: set[str] = set()
    for hit in match_terms(text, domain_id):
        if hit["id"] in seen:
            continue
        seen.add(hit["id"])
        term = term_by_id(hit["id"], domain_id)
        if term is not None:
            out.append(term)
    return out


# --------------------------------------------------------------------------- #
# alias <-> canonical name, both directions
# --------------------------------------------------------------------------- #

def bidirectional_table(domain_id: str = DEFAULT_DOMAIN) -> dict:
    """别名与正名双向对照表.

    Returns ``{"domain_id", "alias_to_name", "name_to_aliases",
    "name_to_id"}``:

    * ``alias_to_name``  — every normalized spelling (canonical name,
      parenthetical body, declared alias) mapped to the canonical name;
      first registration wins, mirroring the template-order rule used by
      ``build_concept_mapping`` / ``resolve_template_concept_id``.
    * ``name_to_aliases`` — canonical name -> its registered aliases.
    * ``name_to_id``      — canonical name -> template concept ID.
    """
    alias_to_name: dict[str, str] = {}
    name_to_aliases: dict[str, list[str]] = {}
    name_to_id: dict[str, str] = {}
    for term in iter_terms(domain_id):
        for spelling in sorted(concept_name_variants(term.name),
                               key=lambda v: (-len(v), v)):
            alias_to_name.setdefault(spelling, term.name)
        for alias in term.aliases:
            for spelling in sorted(concept_name_variants(alias),
                                   key=lambda v: (-len(v), v)):
                alias_to_name.setdefault(spelling, term.name)
        name_to_aliases[term.name] = list(term.aliases)
        name_to_id[term.name] = term.id
    return {
        "domain_id": domain_id,
        "alias_to_name": alias_to_name,
        "name_to_aliases": name_to_aliases,
        "name_to_id": name_to_id,
    }


def resolve_alias(alias: str, domain_id: str = DEFAULT_DOMAIN) -> str:
    """Canonical name behind ``alias`` (``""`` when the alias is unknown)."""
    term = get_term(alias, domain_id)
    return term.name if term is not None else ""


def aliases_of(concept_ref, domain_id: str = DEFAULT_DOMAIN) -> list[str]:
    """Registered aliases of a concept (``[]`` when it is not registered)."""
    term = get_term(concept_ref, domain_id)
    return list(term.aliases) if term is not None else []


# --------------------------------------------------------------------------- #
# tabular / reporting helpers
# --------------------------------------------------------------------------- #

def glossary(domain_id: str = DEFAULT_DOMAIN) -> dict[str, list[dict]]:
    """术语对照表 rows grouped by chapter title (empty dict without a template)."""
    grouped: dict[str, list[dict]] = {}
    for term in iter_terms(domain_id):
        group = term.chapter_title or term.chapter_id or ""
        grouped.setdefault(group, []).append({
            "term": term.name,
            "id": term.id,
            "aliases": list(term.aliases),
            "definition": term.definition,
            "key_points": list(term.key_points),
            "significance": term.significance,
            "evidence_count": len(term.evidence),
        })
    return grouped


def stats(domain_id: str = DEFAULT_DOMAIN) -> dict:
    """Coverage numbers for the terminology table (0s without a template)."""
    template: DomainTemplate | None = get_domain_template(domain_id)
    terms = iter_terms(domain_id)
    return {
        "domain_id": domain_id,
        "template_name": template.name if template is not None else "",
        "term_count": len(terms),
        "chapter_count": len({t.chapter_id for t in terms}),
        "alias_count": sum(len(t.aliases) for t in terms),
        "terms_with_aliases": sum(1 for t in terms if t.aliases),
    }


__all__ = [
    "DEFAULT_DOMAIN",
    "Term",
    "aliases_of",
    "bidirectional_table",
    "get_term",
    "glossary",
    "iter_terms",
    "match_terms",
    "resolve_alias",
    "stats",
    "term_by_id",
    "terms_for_concept",
    "terms_for_text",
]
