"""Tests for the distributed energy resources (DER) domain (fourth domain).

Mirrors ``test_domain_renewable.py``: the DER template must register, detect
from a title, ship scenes that pass ``check_scene``, resolve concept references
by every route, and gate on its own domain so a non-DER asset never pulls in
DER visuals.
"""
import unittest

from expert_anything.core.domain_templates import (
    DISTRIBUTED_ENERGY_TEMPLATE,
    get_domain_template,
    detect_domain_from_title,
    apply_domain_template,
    resolve_template_concept_id,
)
from expert_anything.core.decoder import check_scene, scene_for_concept
from expert_anything.core.decoder_distributed_energy import (
    generate_resource_form_scene,
    generate_aggregation_scene,
    generate_balance_scene,
    generate_value_scene,
    get_scene_for_concept,
    scene_for_concept_id,
    domain_scene_for,
)
from expert_anything.core.models import KnowledgeAsset, Concept
from expert_anything.core.tutor import Tutor


def _asset(concepts, learning_path=None, title="分布式能源资源体系"):
    """Build a throwaway DER KnowledgeAsset for application tests."""
    return KnowledgeAsset(
        asset_id="de-tmp",
        type="article",
        title=title,
        source_name="t.md",
        created_at="2026-10-12T00:00:00Z",
        source_text="Test content",
        concepts=concepts,
        relations=[],
        learning_path=list(learning_path or []),
    )


class TestDistributedTemplate(unittest.TestCase):
    """DER template registration and structure."""

    def test_registered(self):
        self.assertIs(get_domain_template("distributed_energy"),
                      DISTRIBUTED_ENERGY_TEMPLATE)

    def test_name(self):
        self.assertEqual(DISTRIBUTED_ENERGY_TEMPLATE.name, "分布式能源资源体系")

    def test_chapters_and_concepts(self):
        chapters = DISTRIBUTED_ENERGY_TEMPLATE.chapters
        self.assertEqual(len(chapters), 4)
        # 资源(4) + 聚合(3) + 平衡(3) + 价值(4)
        self.assertEqual(
            sum(len(ch.get("concepts", [])) for ch in chapters), 14
        )
        self.assertTrue(DISTRIBUTED_ENERGY_TEMPLATE.quick_path)
        self.assertEqual(len(DISTRIBUTED_ENERGY_TEMPLATE.quick_path), 7)

    def test_quick_path_ids_exist(self):
        known = {
            c["id"]
            for ch in DISTRIBUTED_ENERGY_TEMPLATE.chapters
            for c in ch.get("concepts", [])
        }
        for cid in DISTRIBUTED_ENERGY_TEMPLATE.quick_path:
            self.assertIn(cid, known, f"quick_path id missing from template: {cid}")


class TestDistributedDetection(unittest.TestCase):
    """Title detection must not bleed into the electricity/carbon/renewable domains."""

    def test_der_keywords(self):
        for title in ("微电网调度技术", "虚拟电厂聚合优化",
                      "分布式能源资源体系", "Distributed Energy Resources",
                      "需求响应策略", "隔墙售电机制"):
            self.assertEqual(detect_domain_from_title(title),
                             "distributed_energy", title)

    def test_not_captured_by_renewable(self):
        # A purely DER title must NOT resolve to the renewable template.
        self.assertNotEqual(detect_domain_from_title("微电网调度"),
                            "renewable_forecasting")

    def test_strong_power_wins_over_der(self):
        # "电力系统微电网" names 电力 (strong) -> electricity, as intended.
        self.assertEqual(detect_domain_from_title("电力系统微电网"),
                         "electricity_trading")

    def test_renewable_still_wins_on_pure_renewable(self):
        # A pure renewable title keeps resolving to renewable, not DER.
        self.assertEqual(detect_domain_from_title("分布式光伏功率预测"),
                         "renewable_forecasting")

    def test_carbon_still_detected(self):
        self.assertEqual(detect_domain_from_title("碳排放权交易"),
                         "carbon_trading")

    def test_unknown(self):
        self.assertIsNone(detect_domain_from_title("随机话题"))


class TestDistributedScenes(unittest.TestCase):
    """Every curated scene must pass check_scene admission."""

    def test_all_scenes_valid(self):
        scenes = [
            generate_resource_form_scene(),
            generate_aggregation_scene(),
            generate_balance_scene(),
            generate_value_scene(),
        ]
        for scene in scenes:
            self.assertIsNotNone(scene)
            verdict, _ = check_scene(scene)
            self.assertTrue(bool(verdict), f"{scene['title']}: {verdict.reason}")

    def test_resource_scene(self):
        scene = generate_resource_form_scene()
        self.assertEqual(scene["title"], "分布式发电资源形态")
        self.assertEqual(len(scene["nodes"]), 6)
        self.assertEqual(len(scene["steps"]), 6)
        self.assertEqual(scene["game"]["answer"], [2, 1, 0])

    def test_aggregation_scene(self):
        scene = generate_aggregation_scene()
        self.assertEqual(scene["title"], "分布式资源的三种聚合形态")
        self.assertIsNotNone(scene["game"])

    def test_value_scene(self):
        scene = generate_value_scene()
        self.assertEqual(scene["title"], "分布式能源的价值与场景")
        self.assertEqual(len(scene["steps"]), 6)


class TestDistributedSceneResolution(unittest.TestCase):
    """Concept reference resolution onto curated scenes (3 routes)."""

    def test_by_template_id(self):
        for tid, title in (
            ("de-001", "分布式发电资源形态"),
            ("de-005", "分布式资源的三种聚合形态"),
            ("de-008", "分布式资源的平衡与支撑作用"),
            ("de-011", "分布式能源的价值与场景"),
        ):
            scene = get_scene_for_concept(tid)
            self.assertIsNotNone(scene, tid)
            self.assertEqual(scene["title"], title)

    def test_by_name_and_alias(self):
        # VPP concept (with parenthetical alias) resolves to the aggregation scene.
        for ref in ("虚拟电厂(VPP)", "虚拟电厂", "VPP", "vpp"):
            scene = get_scene_for_concept(ref)
            self.assertIsNotNone(scene, ref)
            self.assertEqual(scene["title"], "分布式资源的三种聚合形态")
        # A different concept name resolves to its own scene.
        self.assertEqual(get_scene_for_concept("微电网")["title"],
                         "分布式资源的三种聚合形态")

    def test_no_curated_scene_returns_none(self):
        self.assertIsNone(get_scene_for_concept("de-015"))   # non-existent id
        self.assertIsNone(get_scene_for_concept("风电功率预测"))
        self.assertIsNone(get_scene_for_concept("未知概念"))

    def test_direct_id_route(self):
        self.assertIsNotNone(scene_for_concept_id("de-005"))
        self.assertIsNone(scene_for_concept_id("de-015"))
        self.assertIsNone(scene_for_concept_id(""))


class TestDistributedGateAndDispatch(unittest.TestCase):
    """domain gate + the teaching-pipeline dispatch (DER vs generic)."""

    def _der_asset(self):
        return _asset([
            Concept(id="c001", name="虚拟电厂(VPP)", definition="", evidence=[]),
            Concept(id="c002", name="微电网", definition="", evidence=[]),
            Concept(id="c003", name="需求响应(DR)", definition="", evidence=[]),
        ])

    def _generic_asset(self, title="如何设计缓存"):
        """Non-domain asset whose concept name collides with the template."""
        return _asset(
            [Concept(id="c001", name="微电网",
                     definition="一种局部网络。", evidence=["某原文。"])],
            title=title,
        )

    def test_domain_asset_uses_domain_scene(self):
        asset = self._der_asset()
        spec = scene_for_concept(asset, asset.concept_by_id("c001"))
        self.assertEqual(spec["title"], "分布式资源的三种聚合形态")

    def test_non_domain_asset_falls_back(self):
        asset = self._generic_asset()
        spec = scene_for_concept(asset, asset.concept_by_id("c001"))
        self.assertIn("知识结构", spec["title"])
        verdict, _ = check_scene(spec)
        self.assertTrue(bool(verdict), verdict.reason)

    def test_domain_gate(self):
        asset = self._generic_asset()
        concept = asset.concept_by_id("c001")
        self.assertIsNone(domain_scene_for(asset, concept))
        self.assertIsNone(domain_scene_for(asset, concept, domain="carbon_trading"))
        self.assertIsNotNone(domain_scene_for(asset, concept,
                                              domain="distributed_energy"))

    def test_tutor_lesson_carries_domain_scene_without_llm(self):
        asset = self._der_asset()
        tutor = Tutor(asset, llm=None)
        lesson = tutor.teach(asset.concept_by_id("c001"), style="diagram")
        self.assertEqual(lesson["scene"]["title"], "分布式资源的三种聚合形态")
        verdict, _ = check_scene(lesson["scene"])
        self.assertTrue(bool(verdict), verdict.reason)


class TestDistributedTemplateApplication(unittest.TestCase):
    """apply_domain_template must enrich + rewrite path name-based, not by ID."""

    def test_apply_enriches_definition(self):
        asset = _asset([
            Concept(id="c001", name="微电网", definition="", evidence=[]),
        ])
        result = apply_domain_template(asset, "distributed_energy")
        self.assertTrue(result)
        c = asset.concept_by_id("c001")
        self.assertTrue(c.definition)
        self.assertIn("局部电力系统", c.definition)

    def test_gounded_text_not_overwritten(self):
        original = "资产自带、已锚定原文的定义。"
        asset = _asset([
            Concept(id="c001", name="微电网", definition=original,
                    evidence=["原文证据"]),
        ])
        result = apply_domain_template(asset, "distributed_energy")
        self.assertEqual(asset.concept_by_id("c001").definition, original)
        self.assertEqual(result.enriched_count, 0)

    def test_resolve_template_id_in_own_domain(self):
        self.assertEqual(
            resolve_template_concept_id("de-006", None,
                                        domain_id="distributed_energy"), "de-006")
        # A template ID of another domain must not resolve inside DER.
        self.assertEqual(
            resolve_template_concept_id("et-001", None,
                                        domain_id="distributed_energy"), "")

    def test_unknown_domain_falsy(self):
        asset = _asset([])
        result = apply_domain_template(asset, "fusion_energy")
        self.assertFalse(result)
        self.assertEqual(result.reason, "unknown_domain")


if __name__ == "__main__":
    unittest.main()
