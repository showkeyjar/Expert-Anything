"""Cross-asset full-text search tests (core/search.py)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core.models import (
    Concept,
    KnowledgeAsset,
    SourceLocation,
)
from expert_anything.core.search import (
    search_assets,
    search_assets_by_name,
)


def _make_asset(asset_id: str, title: str, concepts: list[Concept]) -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_id=asset_id,
        type="text",
        title=title,
        source_name=f"{title}.md",
        created_at="2026-01-01T00:00:00+00:00",
        concepts=concepts,
    )


class SearchAssetsTest(unittest.TestCase):
    def setUp(self):
        c1 = Concept(
            id="c1",
            name="节点边际电价(LMP)",
            definition="节点边际电价反映电网不同位置的供电边际成本。",
            summary="LMP 是价格信号。",
            evidence=[
                "节点边际电价包含电能价值、阻塞成本和网损成本。",
                "LMP 在拥挤线路上会升高。",
            ],
            chapter="电价机制",
        )
        # Concept with a real source location anchor.
        c2 = Concept(
            id="c2",
            name="调度机构",
            definition="调度机构负责电网安全运行。",
            summary="",
            evidence=["调度机构执行发电计划，保障实时平衡。"],
            chapter="参与主体",
            locations=[
                SourceLocation(
                    char_start=100,
                    char_end=150,
                    chapter="参与主体",
                    snippet="调度机构负责电网安全运行，执行发电计划，保障实时平衡。",
                    line=8,
                    page=3,
                )
            ],
        )
        c3 = Concept(
            id="c3",
            name="电力现货",
            definition="现货市场反映实时供需关系。",
            summary="",
            evidence=[],
            chapter="市场架构",
        )
        self.assets = {
            "a1": _make_asset("a1", "电力市场入门", [c1, c2, c3]),
            "a2": _make_asset(
                "a2",
                "碳市场指南",
                [Concept(id="c4", name="配额拍卖", definition="拍卖法分配配额。")],
            ),
        }

    def test_name_match_ranks_first(self):
        hits = search_assets(self.assets, "LMP")
        self.assertTrue(hits)
        self.assertEqual(hits[0].field, "name")
        self.assertEqual(hits[0].concept_name, "节点边际电价(LMP)")
        self.assertEqual(hits[0].chapter, "电价机制")

    def test_definition_and_evidence_match(self):
        hits = search_assets(self.assets, "实时")
        fields = {h.field for h in hits}
        self.assertIn("definition", fields)  # 电力现货 的定义含"实时供需"
        self.assertIn("evidence", fields)  # 调度机构 的证据含"实时平衡"
        self.assertTrue(any(h.concept_name == "调度机构" for h in hits))
        self.assertTrue(any(h.concept_name == "电力现货" for h in hits))

    def test_source_anchor_match_carries_page(self):
        hits = search_assets(self.assets, "保障实时平衡")
        self.assertTrue(hits)
        h = next((x for x in hits if x.field == "source"), None)
        self.assertIsNotNone(h, f"expected a source hit, got {[x.field for x in hits]}")
        self.assertEqual(h.page, 3)
        self.assertEqual(h.concept_name, "调度机构")

    def test_cross_asset(self):
        hits = search_assets(self.assets, "拍卖")
        self.assertTrue(hits)
        self.assertEqual(hits[0].asset_id, "a2")
        self.assertEqual(hits[0].concept_name, "配额拍卖")

    def test_empty_and_no_match(self):
        self.assertEqual(search_assets(self.assets, "   "), [])
        self.assertEqual(search_assets(self.assets, "zzz-not-exist"), [])

    def test_name_only_query(self):
        hits = search_assets_by_name(self.assets, "现货")
        self.assertTrue(hits)
        self.assertEqual(hits[0].concept_name, "电力现货")


if __name__ == "__main__":
    unittest.main()
