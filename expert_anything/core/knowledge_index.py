"""Hybrid Knowledge index — persistent, offline cross-asset retrieval.

Two layers, only the first ships by default:

Layer 1 (always on): a SQLite-backed *substring* index over every concept in
every asset. It replaces the per-call O(N) scan across the on-disk JSON files
(see ``search.py``) with an indexed lookup that stays fast as the corpus grows
into book-sized assets with hundreds of concepts. Fully deterministic, no
network, no extra dependency — ``sqlite3`` is in the standard library.

Why a hand-rolled bigram index instead of FTS5? FTS5's default ``unicode61``
tokenizer *drops CJK characters entirely* (verified: a phrase MATCH over
Chinese text returns zero rows), and the ``trigram`` tokenizer needs queries of
>= 3 characters. A bigram (2-character) index handles Chinese substrings of any
length, plus Latin words, and intersects cleanly. Each concept stores its
searchable text; candidate concept-ids come from a bigram lookup, then a cheap
Python substring check removes coincidental bigram collisions.

Layer 2 (optional, pluggable): a *semantic* backend (embeddings). Register one
with ``KnowledgeIndex.set_semantic_backend(...)``; when present, semantic hits
are merged with the substring results and boosted. No backend ships by default,
so the product stays 100% offline until you plug one in. The interface is
intentionally tiny so any backend can be dropped in without touching the search
path.

The returned ``SearchHit`` objects are shape-compatible with
``expert_anything.core.search`` so the UI can consume either path unchanged.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from expert_anything.core import config
from expert_anything.core.models import Concept, KnowledgeAsset
from expert_anything.core.search import SearchHit, _snippet

# Field priority mirrors search.py: name wins, then definition/summary/evidence/source.
_FIELD_RANK = {"name": 0, "definition": 1, "summary": 2, "evidence": 3, "source": 4}
_MAX_TOTAL = 40


def _bigrams(s: str) -> list[str]:
    """All overlapping 2-character grams of a (already lowercased) string."""
    grams = [s[i : i + 2] for i in range(len(s) - 1)]
    return grams


class SemanticBackend(Protocol):
    """Minimal contract for a pluggable semantic (embedding) retriever.

    Implementations may be online (an API) or offline (a local model / an
    on-disk vector store). They only need to turn a free-text query into a
    ranked list of ``(concept_id, score)`` pairs drawn from concepts that have
    been indexed via ``index_concepts``.
    """

    def index_concepts(self, rows: Sequence[tuple[str, str, str]]) -> None:
        """Index ``(asset_id, concept_id, text)`` triples."""
        ...

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Return ``(concept_id, score)`` pairs for ``query``, best first."""
        ...


class _NullSemanticBackend:
    """Default backend: no semantic signal, system stays fully offline."""

    def index_concepts(self, rows: Sequence[tuple[str, str, str]]) -> None:
        return None

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        return []


def _combined_text(concept: Concept) -> str:
    """All searchable text for one concept, joined for the index."""
    from expert_anything.core.domain_templates import concept_name_variants

    parts = [concept.name]
    parts.extend(concept_name_variants(concept.name))
    if concept.definition:
        parts.append(concept.definition)
    if concept.summary:
        parts.append(concept.summary)
    parts.extend(concept.evidence or [])
    parts.extend((loc.snippet or "") for loc in concept.locations)
    return "\n".join(p for p in parts if p)


def _first_page(concept: Concept) -> int | None:
    for loc in concept.locations:
        if loc.page:
            return loc.page
    return None


class KnowledgeIndex:
    """Persistent cross-asset concept index backed by SQLite (bigram substring)."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = Path(db_path) if db_path else (config.DATA_DIR / ".search_index.sqlite")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._semantic: SemanticBackend = _NullSemanticBackend()
        self._sem_indexed: set[str] = set()  # asset_ids pushed to the semantic backend
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS concepts (
                rid INTEGER PRIMARY KEY,
                asset_id TEXT,
                asset_title TEXT,
                concept_id TEXT UNIQUE,
                name TEXT,
                chapter TEXT,
                page INTEGER,
                c_def TEXT,
                c_sum TEXT,
                c_ev TEXT,
                c_src TEXT,
                text TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS bigram (g TEXT, rid INTEGER, "
            "PRIMARY KEY (g, rid))"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS ix_bigram ON bigram(g)")
        self._conn.commit()

    # -- semantic backend ----------------------------------------------------
    def set_semantic_backend(self, backend: SemanticBackend | None) -> None:
        """Plug in (or remove) a semantic retriever. None => offline-only."""
        self._semantic = backend if backend is not None else _NullSemanticBackend()
        self._sem_indexed.clear()

    # -- writes --------------------------------------------------------------
    def _row_for(self, asset: KnowledgeAsset, concept: Concept) -> dict:
        return {
            "asset_id": asset.asset_id,
            "asset_title": asset.title or asset.source_name or asset.asset_id,
            "concept_id": concept.id,
            "name": concept.name,
            "chapter": concept.chapter or "",
            "page": _first_page(concept) or -1,
            "c_def": concept.definition or "",
            "c_sum": concept.summary or "",
            "c_ev": "\n".join(concept.evidence or []),
            "c_src": "\n".join((loc.snippet or "") for loc in concept.locations),
            "text": _combined_text(concept),
        }

    def _insert_concept(self, asset: KnowledgeAsset, concept: Concept) -> None:
        row = self._row_for(asset, concept)
        cur = self._conn.execute(
            """
            INSERT OR REPLACE INTO concepts
                (asset_id, asset_title, concept_id, name, chapter, page,
                 c_def, c_sum, c_ev, c_src, text)
            VALUES (:asset_id, :asset_title, :concept_id, :name, :chapter, :page,
                    :c_def, :c_sum, :c_ev, :c_src, :text)
            """,
            row,
        )
        rid = cur.lastrowid
        # If INSERT OR REPLACE hit an existing concept_id, lastrowid may be the
        # old row; fetch the canonical rid for this concept_id.
        if rid is None:
            rid = self._conn.execute(
                "SELECT rid FROM concepts WHERE concept_id = ?", (concept.id,)
            ).fetchone()[0]
        text_lc = row["text"].lower()
        for g in _bigrams(text_lc):
            self._conn.execute(
                "INSERT OR IGNORE INTO bigram (g, rid) VALUES (?, ?)", (g, rid)
            )

    def add_asset(self, asset: KnowledgeAsset) -> None:
        """Upsert one asset's concepts (idempotent)."""
        self._conn.execute(
            "DELETE FROM concepts WHERE asset_id = ?", (asset.asset_id,)
        )
        # Remove orphan bigrams (rows no longer referenced).
        self._conn.execute(
            "DELETE FROM bigram WHERE rid NOT IN (SELECT rid FROM concepts)"
        )
        for c in asset.concepts or []:
            self._insert_concept(asset, c)
        self._conn.commit()
        self._push_semantic(asset)

    def rebuild(self, assets: Iterable[KnowledgeAsset]) -> int:
        """Rebuild the whole index from scratch. Returns concept count."""
        self._conn.execute("DELETE FROM bigram")
        self._conn.execute("DELETE FROM concepts")
        n = 0
        sem_rows: list[tuple[str, str, str]] = []
        for asset in assets:
            for c in asset.concepts or []:
                self._insert_concept(asset, c)
                n += 1
                sem_rows.append((asset.asset_id, c.id, _combined_text(c)))
        self._conn.commit()
        self._sem_indexed.clear()
        self._semantic.index_concepts(sem_rows)
        self._sem_indexed.update(a.asset_id for a in assets)
        return n

    def _push_semantic(self, asset: KnowledgeAsset) -> None:
        if asset.asset_id in self._sem_indexed:
            return
        rows = [(asset.asset_id, c.id, _combined_text(c)) for c in asset.concepts or []]
        if rows:
            self._semantic.index_concepts(rows)
            self._sem_indexed.add(asset.asset_id)

    def drop_asset(self, asset_id: str) -> None:
        self._conn.execute("DELETE FROM concepts WHERE asset_id = ?", (asset_id,))
        self._conn.execute(
            "DELETE FROM bigram WHERE rid NOT IN (SELECT rid FROM concepts)"
        )
        self._conn.commit()
        self._sem_indexed.discard(asset_id)

    def count(self) -> int:
        return self._conn.execute("SELECT count(*) FROM concepts").fetchone()[0]

    # -- reads ---------------------------------------------------------------
    def search(self, keyword: str, limit: int = _MAX_TOTAL) -> list[SearchHit]:
        """Ranked cross-asset substring search.

        Candidate concept-ids come from a bigram lookup (fast, indexed), then a
        cheap Python substring check removes coincidental bigram collisions.
        Results are ordered by field priority (name > definition > summary >
        evidence > source) to mirror ``search.py``. Semantic hits (if a backend
        is registered) are merged in and boosted.
        """
        kw = (keyword or "").strip().lower()
        if not kw:
            return []

        candidate_rids = self._candidate_rids(kw)
        if not candidate_rids:
            # Still give the semantic backend a chance.
            return self._merge_semantic([], kw, limit)

        placeholders = ",".join("?" for _ in candidate_rids)
        rows = self._conn.execute(
            f"""
            SELECT rid, asset_id, asset_title, concept_id, name, chapter, page,
                   c_def, c_sum, c_ev, c_src, text
            FROM concepts WHERE rid IN ({placeholders})
            """,
            candidate_rids,
        ).fetchall()

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for (
            _rid,
            asset_id,
            asset_title,
            concept_id,
            name,
            chapter,
            page,
            c_def,
            c_sum,
            c_ev,
            c_src,
            text,
        ) in rows:
            if kw not in text.lower():
                continue  # bigram collision, not a real substring
            field, snippet = self._best_field(kw, name, c_def, c_sum, c_ev, c_src)
            if field is None or concept_id in seen:
                continue
            seen.add(concept_id)
            hits.append(
                SearchHit(
                    asset_id=asset_id,
                    asset_title=asset_title,
                    concept_id=concept_id,
                    concept_name=name,
                    field=field,
                    snippet=snippet,
                    chapter=chapter or "",
                    page=page if page and page > 0 else None,
                )
            )

        hits = self._merge_semantic(hits, kw, limit)
        # Re-rank: field priority first, then insertion order.
        hits.sort(key=lambda h: _FIELD_RANK.get(h.field, 9))
        return hits[:limit]

    def _candidate_rids(self, kw: str) -> list[int]:
        if len(kw) == 1:
            # Single character: LIKE over the (small) text column.
            rows = self._conn.execute(
                "SELECT rid FROM concepts WHERE lower(text) LIKE ?",
                (f"%{kw}%",),
            ).fetchall()
            return [r[0] for r in rows]
        grams = _bigrams(kw)
        if not grams:
            return []
        # Intersect rids containing ALL bigrams (=> substring present).
        result: set[int] | None = None
        for g in grams:
            rids = {
                r[0]
                for r in self._conn.execute(
                    "SELECT rid FROM bigram WHERE g = ?", (g,)
                ).fetchall()
            }
            if not rids:
                return []
            result = rids if result is None else (result & rids)
        return list(result or set())

    def _merge_semantic(
        self, hits: list[SearchHit], kw: str, limit: int
    ) -> list[SearchHit]:
        sem = self._semantic.search(kw, top_k=limit)
        if not sem:
            return hits
        by_cid = {h.concept_id: h for h in hits}
        for cid, _s in sorted(sem, key=lambda x: -x[1]):
            if cid in by_cid:
                continue  # already present via substring search
            row = self._conn.execute(
                """
                SELECT asset_id, asset_title, concept_id, name, chapter, page,
                       c_def, c_sum, c_ev, c_src
                FROM concepts WHERE concept_id = ? LIMIT 1
                """,
                (cid,),
            ).fetchone()
            if not row:
                continue
            (
                asset_id,
                asset_title,
                _cid,
                name,
                chapter,
                page,
                c_def,
                c_sum,
                c_ev,
                c_src,
            ) = row
            field, snippet = self._best_field(kw, name, c_def, c_sum, c_ev, c_src)
            field = field or "summary"
            snippet = snippet or (c_sum or c_def or name)[:140]
            hits.append(
                SearchHit(
                    asset_id=asset_id,
                    asset_title=asset_title,
                    concept_id=cid,
                    concept_name=name,
                    field=field,
                    snippet=snippet,
                    chapter=chapter or "",
                    page=page if page and page > 0 else None,
                )
            )
        return hits

    @staticmethod
    def _best_field(
        kw: str, name: str, c_def: str, c_sum: str, c_ev: str, c_src: str
    ) -> tuple[str | None, str]:
        if kw and kw in (name or "").lower():
            return "name", name
        if kw and kw in (c_def or "").lower():
            return "definition", _snippet(c_def, kw)
        if kw and kw in (c_sum or "").lower():
            return "summary", _snippet(c_sum, kw)
        if kw and kw in (c_ev or "").lower():
            return "evidence", _snippet(c_ev, kw)
        if kw and kw in (c_src or "").lower():
            return "source", _snippet(c_src, kw)
        return None, ""

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> "KnowledgeIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# -- module-level convenience ------------------------------------------------
_DEFAULT_INDEX: KnowledgeIndex | None = None
_DEFAULT_SIG: str | None = None  # signature of the corpus currently indexed


def default_index() -> KnowledgeIndex:
    """Process-wide singleton so repeated searches reuse one indexed corpus."""
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is None:
        _DEFAULT_INDEX = KnowledgeIndex()
    return _DEFAULT_INDEX


def _assets_signature(assets: Iterable[KnowledgeAsset]) -> str:
    """Cheap, stable signature of the loaded corpus.

    Used to decide whether the on-disk index is still valid. It changes when an
    asset is added/removed or when an asset's concept count or creation stamp
    differs — which covers re-imports and incremental updates without having to
    re-tokenize the whole corpus on every keystroke.
    """
    h = hashlib.sha1()
    seq = assets.values() if isinstance(assets, dict) else assets
    for asset in seq:
        h.update(asset.asset_id.encode("utf-8"))
        h.update(b"|")
        h.update(str(len(asset.concepts or [])).encode("utf-8"))
        h.update(b"|")
        h.update((asset.created_at or "").encode("utf-8"))
        h.update(b";")
    return h.hexdigest()


def indexed_search(
    assets: Iterable[KnowledgeAsset], keyword: str, limit: int = _MAX_TOTAL
) -> list[SearchHit]:
    """Search across assets using the persistent index.

    The index is built once per session and reused: a second search over the
    same corpus serves straight from disk, so it is an indexed lookup rather
    than a full rescan. The index is transparently rebuilt only when the loaded
    corpus changes (detected via :func:`_assets_signature`), so importing a new
    book or re-importing a changed one stays correct without manual invalidation.
    """
    global _DEFAULT_SIG
    idx = default_index()
    sig = _assets_signature(assets)
    if sig != _DEFAULT_SIG:
        seq = assets.values() if isinstance(assets, dict) else assets
        idx.rebuild(seq)
        _DEFAULT_SIG = sig
    return idx.search(keyword, limit=limit)
