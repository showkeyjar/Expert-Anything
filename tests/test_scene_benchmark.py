"""Tests for the scene-quality benchmark (curated vs fallback)."""
import unittest

from expert_anything.core.domain_templates import DOMAIN_TEMPLATES
from expert_anything.core.models import Concept, KnowledgeAsset, Relation
from expert_anything.core.scene_benchmark import (
    SceneScore,
    BenchmarkReport,
    build_toy_asset,
    compare_for_asset,
    run_scene_benchmark,
    score_scene,
)


def _concept(name, definition="", evidence=None, summary=""):
    return Concept(
        id=f"c-{name}",
        name=name,
        definition=definition,
        evidence=list(evidence or []),
        summary=summary,
    )


def _asset(*concepts, relations=None):
    return KnowledgeAsset(
        asset_id="a", type="text", title="Test", source_name="Test",
        created_at="t", concepts=list(concepts), relations=list(relations or []),
    )


class TestScoreScene(unittest.TestCase):
    def test_dimensions(self):
        concept = _concept("X", definition="X 是一种 Y 的结构")
        asset = _asset(concept)
        spec = {
            "title": "t",
            "nodes": [{"id": "c0", "label": "X"}, {"id": "d1", "label": "Y"}],
            "edges": [{"from": "c0", "to": "d1", "label": "定义", "type": "is_a"}],
            "steps": [
                {"caption": "定位 X", "show": ["c0"], "active": "c0"},
                {"caption": "X 是一种 Y", "show": ["d1"], "active": "d1"},
            ],
            "game": {"type": "sort", "goal": "g", "items": ["1", "2", "3"], "answer": [0, 1, 2]},
        }
        s = score_scene(spec, concept, asset, "curated")
        self.assertEqual(s.path, "curated")
        self.assertEqual(s.node_count, 2)
        self.assertEqual(s.edge_count, 1)
        self.assertEqual(s.typed_edge_count, 1)  # edge carries semantic type
        self.assertEqual(s.step_count, 2)
        self.assertTrue(s.has_game)
        self.assertGreater(s.source_overlap, 0.0)  # overlaps concept definition
        self.assertGreater(s.structure_score, 0.0)
        self.assertGreaterEqual(s.total, s.structure_score)

    def test_source_overlap_precision(self):
        concept = _concept("Z", definition="唯一来源短语出现在定义里")
        asset = _asset(concept)
        # scene text unrelated to the source -> ~0 overlap
        spec = {
            "title": "t",
            "nodes": [{"id": "c0", "label": "无关词"}, {"id": "d1", "label": "另一个无关"}],
            "edges": [],
            "steps": [{"caption": "完全无关的步骤", "show": ["c0"], "active": "c0"},
                      {"caption": "再来一句", "show": ["d1"], "active": "d1"}],
        }
        s = score_scene(spec, concept, asset, "fallback")
        self.assertEqual(s.step_count, 2)
        self.assertAlmostEqual(s.source_overlap, 0.0, places=4)

    def test_relation_anchor(self):
        c1 = _concept("父概念")
        c2 = _concept("子概念")
        asset = _asset(c1, c2, relations=[
            Relation(id="r", source=c2.id, target=c1.id, type="part_of", label="组成部分")
        ])
        spec = {
            "title": "t",
            "nodes": [{"id": "c0", "label": "子概念"}, {"id": "d1", "label": "父概念"}],
            "edges": [{"from": "c0", "to": "d1", "label": "组成部分"}],
            "steps": [{"caption": "子概念 的父概念", "show": ["c0"], "active": "c0"},
                      {"caption": "父概念 提供上下文", "show": ["d1"], "active": "d1"}],
        }
        s = score_scene(spec, c2, asset, "curated")
        self.assertTrue(s.relation_anchored)


class TestBuildToyAsset(unittest.TestCase):
    def test_valid_and_resolvable(self):
        for domain in ("electricity_trading", "carbon_trading", "renewable_forecasting"):
            asset = build_toy_asset(domain)
            self.assertTrue(asset.concepts, domain)
            ids = {c.id for c in asset.concepts}
            for r in asset.relations:
                self.assertIn(r.source, ids, f"{domain}: bad source {r.source}")
                self.assertIn(r.target, ids, f"{domain}: bad target {r.target}")


class TestCompareForAsset(unittest.TestCase):
    def test_electricity(self):
        asset = build_toy_asset("electricity_trading")
        comps = compare_for_asset(asset, domain="electricity_trading")
        self.assertEqual(len(comps), len(asset.concepts))
        names = {c.name for c in asset.concepts}
        for c in comps:
            self.assertIsInstance(c.curated, SceneScore)
            self.assertIsInstance(c.fallback, SceneScore)
            self.assertGreaterEqual(c.curated.step_count, 2)
            self.assertGreaterEqual(c.fallback.step_count, 2)
            self.assertIn(c.concept_name, names)

    def test_no_domain_returns_empty(self):
        asset = _asset(_concept("X"))
        self.assertEqual(compare_for_asset(asset, domain="does_not_exist"), [])


class TestRunBenchmark(unittest.TestCase):
    def test_all_domains(self):
        reports = run_scene_benchmark()
        self.assertEqual(len(reports), len(DOMAIN_TEMPLATES))
        for r in reports:
            self.assertIsInstance(r, BenchmarkReport)
            self.assertGreater(r.n_concepts, 0)
            self.assertIn("curated_structure_score", r.averages)
            self.assertIn("gain_structure", r.averages)
            self.assertIn("gain_source", r.averages)
            self.assertTrue(r.summary)

    def test_report_str_has_columns(self):
        r = run_scene_benchmark(["carbon_trading"])[0]
        text = str(r)
        self.assertIn("carbon_trading", text)
        self.assertIn("curated", text)
        self.assertIn("fallback", text)
        self.assertIn("typed_edge_count", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
