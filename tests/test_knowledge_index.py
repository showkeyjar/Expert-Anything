"""Tests for the Hybrid Knowledge persistent index (knowledge_index.py)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core.models import Concept, KnowledgeAsset, SourceLocation
from expert_anything.core import knowledge_index as ki
from expert_anything.core.knowledge_index import (
    KnowledgeIndex,
    SemanticBackend,
    _NullSemanticBackend,
    _bigrams,
    indexed_search,
)


def _asset(asset_id, title, concepts):
    return KnowledgeAsset(
        asset_id=asset_id,
        type="text",
        title=title,
        source_name=title,
        created_at="2026-01-01",
        concepts=concepts,
    )


def _concept(cid, name, definition="", summary="", evidence=None, page=None):
    locs = [SourceLocation(snippet=evidence[0][:60] if evidence else "", page=page)] if (evidence and page) else []
    return Concept(
        id=cid,
        name=name,
        definition=definition,
        summary=summary,
        evidence=evidence or [],
        locations=locs,
    )


class TestBigrams(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_bigrams("abc"), ["ab", "bc"])

    def test_cjk(self):
        self.assertEqual(_bigrams("电力交易"), ["电力", "力交", "交易"])

    def test_single_char_empty(self):
        self.assertEqual(_bigrams("a"), [])


class TestKnowledgeIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "idx.sqlite"
        self.idx = KnowledgeIndex(self.db)
        self.assets = [
            _asset(
                "a1",
                "电力市场导论",
                [
                    _concept("c1", "电力交易", definition="电力交易是在市场中买卖电力的行为", summary="核心概念"),
                    _concept("c2", "节点边际电价", definition="LMP 反映输电阻塞", evidence=["节点边际电价体现阻塞成本"], page=5),
                ],
            ),
            _asset(
                "a2",
                "碳市场基础",
                [
                    _concept("c3", "碳价", definition="碳排放权的市场价格", evidence=["碳价由配额供需决定"], page=12),
                    _concept("c4", "配额", definition="可交易的排放上限", summary="总量控制"),
                ],
            ),
        ]

    def tearDown(self):
        self.idx.close()

    def test_rebuild_and_count(self):
        n = self.idx.rebuild(self.assets)
        self.assertEqual(n, 4)
        self.assertEqual(self.idx.count(), 4)

    def test_search_finds_concept(self):
        self.idx.rebuild(self.assets)
        hits = self.idx.search("电力交易")
        self.assertTrue(hits)
        self.assertEqual(hits[0].concept_id, "c1")
        self.assertEqual(hits[0].field, "name")

    def test_search_definition_field(self):
        self.idx.rebuild(self.assets)
        hits = self.idx.search("阻塞")
        self.assertTrue(any(h.concept_id == "c2" for h in hits))
        hit = next(h for h in hits if h.concept_id == "c2")
        self.assertIn(hit.field, ("definition", "evidence"))

    def test_search_cross_asset(self):
        self.idx.rebuild(self.assets)
        # "市场" appears in a definition of each asset -> cross-asset hit.
        hits = self.idx.search("市场")
        cids = {h.concept_id for h in hits}
        self.assertIn("c1", cids)  # 电力市场导论 / 电力交易是在市场中…
        self.assertIn("c3", cids)  # 碳市场基础 / 碳排放权的市场价格
        # A carbon-only term must not bleed into the electricity asset.
        carbon_hits = self.idx.search("碳价")
        self.assertTrue(any(h.concept_id == "c3" for h in carbon_hits))
        self.assertNotIn("c1", {h.concept_id for h in carbon_hits})

    def test_page_anchor_carried(self):
        self.idx.rebuild(self.assets)
        hits = self.idx.search("配额")
        hit = next(h for h in hits if h.concept_id == "c4")
        self.assertEqual(hit.page, None)  # c4 has no page
        hit2 = next(h for h in hits if h.concept_id == "c3")
        self.assertEqual(hit2.page, 12)

    def test_add_asset_idempotent(self):
        self.idx.rebuild(self.assets)
        # Re-add a1 -> should not duplicate its concepts.
        self.idx.add_asset(self.assets[0])
        self.idx.add_asset(self.assets[0])
        self.assertEqual(self.idx.count(), 4)

    def test_drop_asset(self):
        self.idx.rebuild(self.assets)
        self.idx.drop_asset("a2")
        self.assertEqual(self.idx.count(), 2)
        hits = self.idx.search("碳")
        self.assertEqual(hits, [])

    def test_empty_query(self):
        self.idx.rebuild(self.assets)
        self.assertEqual(self.idx.search(""), [])

    def test_two_char_cjk_query(self):
        self.idx.rebuild(self.assets)
        # 2-char CJK substring should hit via bigram intersection.
        hits = self.idx.search("电力")
        self.assertTrue(any(h.concept_id == "c1" for h in hits))

    def test_latin_substring(self):
        self.idx.rebuild(self.assets)
        hits = self.idx.search("阻塞")
        self.assertTrue(any(h.concept_id == "c2" for h in hits))

    def test_substring_collision_filtered(self):
        # "电力" appears in c1 ("电力交易") but NOT as a standalone concept
        # somewhere containing both bigrams non-adjacently. Ensure only real
        # substrings surface.
        self.idx.rebuild(self.assets)
        hits = self.idx.search("电力")
        cids = [h.concept_id for h in hits]
        self.assertIn("c1", cids)
        # c3/c4 are carbon concepts without "电力" -> must not appear.
        self.assertNotIn("c3", cids)
        self.assertNotIn("c4", cids)

    def test_semantic_backend_noop_does_not_break(self):
        # Default null backend: search still works, no exception.
        self.idx.rebuild(self.assets)
        self.assertIsInstance(self.idx._semantic, _NullSemanticBackend)
        hits = self.idx.search("电力")
        self.assertTrue(hits)

    def test_pluggable_semantic_backend_merges(self):
        # A trivial backend that returns a known concept id for any query.
        class FakeSem(SemanticBackend):
            def index_concepts(self, rows):
                self._rows = list(rows)

            def search(self, query, top_k=20):
                # Promote c3 (碳价) regardless of query.
                return [("c3", 0.9)]

        self.idx.set_semantic_backend(FakeSem())
        self.idx.rebuild(self.assets)
        hits = self.idx.search("无关词")
        cids = [h.concept_id for h in hits]
        self.assertIn("c3", cids)


class TestIndexedSearchSessionCache(unittest.TestCase):
    """indexed_search must build the index once and reuse it within a session,
    rebuilding only when the loaded corpus actually changes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.idx = KnowledgeIndex(self.tmp / "idx.sqlite")
        # Point the module singleton at our isolated index so we don't touch
        # the real data/.search_index.sqlite.
        ki._DEFAULT_INDEX = self.idx
        ki._DEFAULT_SIG = None
        self.rebuild_calls = 0
        self._orig_rebuild = self.idx.rebuild

        def _counting(assets):
            self.rebuild_calls += 1
            return self._orig_rebuild(assets)

        self.idx.rebuild = _counting

    def tearDown(self):
        ki._DEFAULT_INDEX = None
        ki._DEFAULT_SIG = None
        self.idx.close()

    def _corpus(self, n, asset_id="a1"):
        cs = [
            Concept(
                id=f"c{i}",
                name=f"电能概念{i}",
                definition=f"此处定义包含电能与关键词{i}",
            )
            for i in range(n)
        ]
        return _asset(asset_id, f"书{asset_id}", cs)

    def test_rebuild_once_then_cached(self):
        a = self._corpus(10)
        indexed_search([a], "电能")
        self.assertEqual(self.rebuild_calls, 1)
        # Same corpus -> subsequent searches must NOT rebuild.
        indexed_search([a], "电能")
        indexed_search([a], "概念3")
        self.assertEqual(self.rebuild_calls, 1)
        hits = indexed_search([a], "概念3")
        self.assertTrue(any(h.concept_id == "c3" for h in hits))
        self.assertEqual(self.rebuild_calls, 1)

    def test_rebuild_when_corpus_grows(self):
        a = self._corpus(10)
        indexed_search([a], "电能")
        self.assertEqual(self.rebuild_calls, 1)
        # Concept count changed -> signature differs -> rebuild again.
        b = self._corpus(25)
        indexed_search([b], "电能")
        self.assertEqual(self.rebuild_calls, 2)
        hits = indexed_search([b], "概念24")
        self.assertTrue(any(h.concept_id == "c24" for h in hits))

    def test_rebuild_when_asset_added(self):
        a = self._corpus(10, asset_id="a1")
        indexed_search([a], "电能")
        self.assertEqual(self.rebuild_calls, 1)
        b = self._corpus(10, asset_id="a2")
        indexed_search([a, b], "电能")
        self.assertEqual(self.rebuild_calls, 2)

    def test_dict_input_accepted(self):
        a = self._corpus(10)
        hits = indexed_search({"a1": a}, "电能")
        self.assertEqual(self.rebuild_calls, 1)
        self.assertTrue(any(h.field for h in hits))


if __name__ == "__main__":
    unittest.main(verbosity=2)
