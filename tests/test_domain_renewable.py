"""Tests for the renewable energy power forecasting domain (third domain).

Mirrors ``test_domain_templates.py`` (electricity) / the carbon coverage: the
renewable template must register, detect from a title, ship scenes that pass
``check_scene``, resolve concept references by every route, and gate on its own
domain so a non-renewable asset never pulls in renewable visuals.
"""
import unittest

from expert_anything.core.domain_templates import (
    RENEWABLE_FORECASTING_TEMPLATE,
    get_domain_template,
    detect_domain_from_title,
    apply_domain_template,
    resolve_template_concept_id,
)
from expert_anything.core.decoder import check_scene, scene_for_concept
from expert_anything.core.decoder_renewable import (
    generate_forecast_horizons_scene,
    generate_nwp_driver_scene,
    generate_power_curve_scene,
    generate_uncertainty_scene,
    get_scene_for_concept,
    scene_for_concept_id,
    domain_scene_for,
)
from expert_anything.core.models import KnowledgeAsset, Concept
from expert_anything.core.tutor import Tutor


def _asset(concepts, learning_path=None, title="新能源功率预测体系"):
    """Build a throwaway renewable KnowledgeAsset for application tests."""
    return KnowledgeAsset(
        asset_id="rf-tmp",
        type="article",
        title=title,
        source_name="t.md",
        created_at="2026-10-12T00:00:00Z",
        source_text="Test content",
        concepts=concepts,
        relations=[],
        learning_path=list(learning_path or []),
    )


class TestRenewableTemplate(unittest.TestCase):
    """Renewable template registration and structure."""

    def test_registered(self):
        self.assertIs(get_domain_template("renewable_forecasting"),
                      RENEWABLE_FORECASTING_TEMPLATE)

    def test_name(self):
        self.assertEqual(RENEWABLE_FORECASTING_TEMPLATE.name, "新能源功率预测体系")

    def test_chapters_and_concepts(self):
        chapters = RENEWABLE_FORECASTING_TEMPLATE.chapters
        self.assertEqual(len(chapters), 4)
        # 预测尺度(4) + 输入(4) + 预测对象(3) + 不确定性(3)
        self.assertEqual(
            sum(len(ch.get("concepts", [])) for ch in chapters), 14
        )
        self.assertTrue(RENEWABLE_FORECASTING_TEMPLATE.quick_path)
        self.assertEqual(len(RENEWABLE_FORECASTING_TEMPLATE.quick_path), 7)

    def test_quick_path_ids_exist(self):
        known = {
            c["id"]
            for ch in RENEWABLE_FORECASTING_TEMPLATE.chapters
            for c in ch.get("concepts", [])
        }
        for cid in RENEWABLE_FORECASTING_TEMPLATE.quick_path:
            self.assertIn(cid, known, f"quick_path id missing from template: {cid}")


class TestRenewableDetection(unittest.TestCase):
    """Title detection must not bleed into the electricity/carbon domains."""

    def test_renewable_keywords(self):
        for title in ("风电功率预测方法", "光伏功率预测导论",
                      "新能源预测技术", "Renewable Energy Forecasting",
                      "基于NWP的功率预测"):
            self.assertEqual(detect_domain_from_title(title),
                             "renewable_forecasting", title)

    def test_not_captured_by_electricity(self):
        # A purely renewable title must NOT resolve to the electricity template.
        self.assertNotEqual(detect_domain_from_title("风电功率预测"),
                            "electricity_trading")

    def test_strong_power_wins_over_renewable(self):
        # "电力系统新能源预测" names 电力 (strong) -> electricity, as intended.
        self.assertEqual(detect_domain_from_title("电力系统新能源预测"),
                         "electricity_trading")

    def test_carbon_still_detected(self):
        self.assertEqual(detect_domain_from_title("碳排放权交易"),
                         "carbon_trading")

    def test_unknown(self):
        self.assertIsNone(detect_domain_from_title("随机话题"))


class TestRenewableScenes(unittest.TestCase):
    """Every curated scene must pass check_scene admission."""

    def test_all_scenes_valid(self):
        scenes = [
            generate_forecast_horizons_scene(),
            generate_nwp_driver_scene(),
            generate_power_curve_scene(),
            generate_uncertainty_scene(),
        ]
        for scene in scenes:
            self.assertIsNotNone(scene)
            verdict, _ = check_scene(scene)
            self.assertTrue(bool(verdict), f"{scene['title']}: {verdict.reason}")

    def test_horizons_scene(self):
        scene = generate_forecast_horizons_scene()
        self.assertEqual(scene["title"], "新能源预测尺度时间轴")
        self.assertEqual(len(scene["nodes"]), 6)
        self.assertEqual(scene["game"]["answer"], [1, 2, 0])

    def test_power_curve_scene(self):
        scene = generate_power_curve_scene()
        self.assertEqual(scene["title"], "功率曲线：风速到出力的映射")
        self.assertEqual(len(scene["steps"]), 5)

    def test_nwp_scene(self):
        scene = generate_nwp_driver_scene()
        self.assertEqual(scene["title"], "NWP 驱动的功率预测链路")
        self.assertIsNotNone(scene["game"])


class TestRenewableSceneResolution(unittest.TestCase):
    """Concept reference resolution onto curated scenes (3 routes)."""

    def test_by_template_id(self):
        for tid, title in (
            ("rf-004", "新能源预测尺度时间轴"),
            ("rf-005", "NWP 驱动的功率预测链路"),
            ("rf-006", "功率曲线：风速到出力的映射"),
            ("rf-012", "预测误差与集合预报"),
        ):
            scene = get_scene_for_concept(tid)
            self.assertIsNotNone(scene, tid)
            self.assertEqual(scene["title"], title)

    def test_by_name_and_alias(self):
        # NWP concept (with parenthetical alias) resolves to the NWP scene.
        for ref in ("数值天气预报(NWP)", "数值天气预报", "NWP", "nwp"):
            scene = get_scene_for_concept(ref)
            self.assertIsNotNone(scene, ref)
            self.assertEqual(scene["title"], "NWP 驱动的功率预测链路")
        # A different concept name resolves to its own scene.
        self.assertEqual(get_scene_for_concept("功率曲线")["title"],
                         "功率曲线：风速到出力的映射")

    def test_no_curated_scene_returns_none(self):
        self.assertIsNone(get_scene_for_concept("rf-009"))   # 风电功率预测
        self.assertIsNone(get_scene_for_concept("rf-011"))   # 负荷预测
        self.assertIsNone(get_scene_for_concept("未知概念"))

    def test_direct_id_route(self):
        self.assertIsNotNone(scene_for_concept_id("rf-004"))
        self.assertIsNone(scene_for_concept_id("rf-010"))
        self.assertIsNone(scene_for_concept_id(""))


class TestRenewableGateAndDispatch(unittest.TestCase):
    """domain gate + the teaching-pipeline dispatch (renewable vs generic)."""

    def _renewable_asset(self):
        return _asset([
            Concept(id="c001", name="预测时间尺度", definition="", evidence=[]),
            Concept(id="c002", name="数值天气预报(NWP)", definition="", evidence=[]),
            Concept(id="c003", name="风电功率预测", definition="", evidence=[]),
        ])

    def _generic_asset(self, title="如何设计缓存"):
        """Non-domain asset whose concept name collides with the template."""
        return _asset(
            [Concept(id="c001", name="功率曲线",
                     definition="一种查找表。", evidence=["某原文。"])],
            title=title,
        )

    def test_domain_asset_uses_domain_scene(self):
        asset = self._renewable_asset()
        spec = scene_for_concept(asset, asset.concept_by_id("c001"))
        self.assertEqual(spec["title"], "新能源预测尺度时间轴")

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
                                              domain="renewable_forecasting"))

    def test_tutor_lesson_carries_domain_scene_without_llm(self):
        asset = self._renewable_asset()
        tutor = Tutor(asset, llm=None)
        lesson = tutor.teach(asset.concept_by_id("c002"), style="diagram")
        self.assertEqual(lesson["scene"]["title"], "NWP 驱动的功率预测链路")
        verdict, _ = check_scene(lesson["scene"])
        self.assertTrue(bool(verdict), verdict.reason)


class TestRenewableTemplateApplication(unittest.TestCase):
    """apply_domain_template must enrich + rewrite path name-based, not by ID."""

    def test_apply_enriches_definition(self):
        asset = _asset([
            Concept(id="c001", name="功率曲线", definition="", evidence=[]),
        ])
        result = apply_domain_template(asset, "renewable_forecasting")
        self.assertTrue(result)
        c = asset.concept_by_id("c001")
        self.assertTrue(c.definition)
        self.assertIn("风速", c.definition)

    def test_gounded_text_not_overwritten(self):
        original = "资产自带、已锚定原文的定义。"
        asset = _asset([
            Concept(id="c001", name="功率曲线", definition=original,
                    evidence=["原文证据"]),
        ])
        result = apply_domain_template(asset, "renewable_forecasting")
        self.assertEqual(asset.concept_by_id("c001").definition, original)
        self.assertEqual(result.enriched_count, 0)

    def test_resolve_template_id_in_own_domain(self):
        self.assertEqual(
            resolve_template_concept_id("rf-006", None,
                                        domain_id="renewable_forecasting"), "rf-006")
        # A template ID of another domain must not resolve inside renewable.
        self.assertEqual(
            resolve_template_concept_id("et-001", None,
                                        domain_id="renewable_forecasting"), "")

    def test_unknown_domain_falsy(self):
        asset = _asset([])
        result = apply_domain_template(asset, "fusion_energy")
        self.assertFalse(result)
        self.assertEqual(result.reason, "unknown_domain")


if __name__ == "__main__":
    unittest.main()
