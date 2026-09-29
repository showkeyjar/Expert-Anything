"""Tests for domain templates and electricity trading decoder."""
import json
import unittest
from pathlib import Path

from expert_anything.core.domain_templates import (
    ELECTRICITY_TRADING_TEMPLATE,
    DEFAULT_MIN_COVERAGE,
    build_concept_mapping,
    get_domain_template,
    detect_domain_from_title,
    apply_domain_template,
    resolve_template_concept_id,
)
from expert_anything.core.decoder import check_scene
from expert_anything.core import decoder
from expert_anything.core.decoder_electricity import (
    generate_market_architecture_scene,
    generate_price_formation_scene,
    generate_trading_process_scene,
    generate_lmp_scene,
    get_scene_for_concept,
    scene_for_concept_id,
    domain_scene_for,
)
from expert_anything.core.models import KnowledgeAsset, Concept, Relation
from expert_anything.core.tutor import Tutor


class TestDomainTemplates(unittest.TestCase):
    """Test domain template loading and retrieval."""
    
    def test_get_electricity_template(self):
        """Test retrieving the electricity trading template."""
        template = get_domain_template("electricity_trading")
        self.assertIsNotNone(template)
        self.assertEqual(template.name, "中国电力市场交易体系")
    
    def test_template_structure(self):
        """Test that template has expected structure."""
        template = ELECTRICITY_TRADING_TEMPLATE
        self.assertEqual(len(template.chapters), 5)
        self.assertTrue(len(template.quick_path) > 0)
        self.assertTrue(len(template.misconceptions) > 0)
        self.assertTrue(len(template.anchor_mapping) > 0)
    
    def test_chapter_count(self):
        """Test chapter distribution."""
        chapters = ELECTRICITY_TRADING_TEMPLATE.chapters
        chapter_ids = [ch["id"] for ch in chapters]
        
        self.assertIn("ch-market", chapter_ids)
        self.assertIn("ch-player", chapter_ids)
        self.assertIn("ch-price", chapter_ids)
        self.assertIn("ch-process", chapter_ids)
        self.assertIn("ch-concept", chapter_ids)
    
    def test_concept_count(self):
        """Test total concept count across all chapters."""
        total = sum(len(ch.get("concepts", [])) for ch in ELECTRICITY_TRADING_TEMPLATE.chapters)
        self.assertEqual(total, 19)
    
    def test_detect_domain_from_title(self):
        """Test domain detection from asset title."""
        self.assertEqual(
            detect_domain_from_title("中国电力市场交易体系"),
            "electricity_trading"
        )
        self.assertEqual(
            detect_domain_from_title("Electricity Market Basics"),
            "electricity_trading"
        )
        self.assertIsNone(detect_domain_from_title("Random Topic"))
        # Carbon trading detection (future domain)
        self.assertEqual(
            detect_domain_from_title("Carbon Trading Guide"),
            "carbon_trading"
        )


class TestElectricityScenes(unittest.TestCase):
    """Test electricity trading SceneSpec generators."""
    
    def test_market_architecture_scene(self):
        """Test market architecture scene generation."""
        scene = generate_market_architecture_scene()
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "中国电力市场两级架构")
        self.assertEqual(len(scene["nodes"]), 5)
        self.assertEqual(len(scene["edges"]), 5)
        self.assertEqual(len(scene["steps"]), 3)
        self.assertIsNone(scene["game"])
    
    def test_price_formation_scene(self):
        """Test price formation scene generation."""
        scene = generate_price_formation_scene()
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "电价形成机制")
        self.assertEqual(len(scene["nodes"]), 5)
        self.assertIsNotNone(scene["game"])
        self.assertEqual(scene["game"]["type"], "sort")
        self.assertEqual(len(scene["game"]["items"]), 4)
    
    def test_trading_process_scene(self):
        """Test trading process scene generation."""
        scene = generate_trading_process_scene()
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "日前市场交易流程")
        self.assertEqual(len(scene["nodes"]), 5)
        self.assertEqual(len(scene["steps"]), 5)
        self.assertEqual(scene["game"]["answer"], [1, 3, 0, 4, 2])
    
    def test_lmp_scene(self):
        """Test LMP scene generation."""
        scene = generate_lmp_scene()
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "节点边际电价(LMP)构成")
        self.assertEqual(len(scene["nodes"]), 4)
        self.assertEqual(len(scene["steps"]), 4)
    
    def test_scene_validation(self):
        """Test that all scenes pass check_scene validation."""
        from expert_anything.core.decoder import check_scene
        
        scenes = [
            generate_market_architecture_scene(),
            generate_price_formation_scene(),
            generate_trading_process_scene(),
            generate_lmp_scene(),
        ]
        
        for scene in scenes:
            if scene:
                verdict, _ = check_scene(scene)
                self.assertTrue(verdict, f"Scene failed validation: {scene['title']}")


class TestSceneMapping(unittest.TestCase):
    """Test concept ID to scene mapping."""
    
    def test_get_scene_for_concept(self):
        """Test scene retrieval for specific concepts."""
        # Market architecture concept
        scene = get_scene_for_concept("et-001")
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "中国电力市场两级架构")
        
        # Price formation concept
        scene = get_scene_for_concept("et-010")
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "电价形成机制")
        
        # Trading process concept
        scene = get_scene_for_concept("et-015")
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "日前市场交易流程")
        
        # LMP concept
        scene = get_scene_for_concept("et-013")
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "节点边际电价(LMP)构成")
    
    def test_unknown_concept(self):
        """Test that unknown concepts return None."""
        scene = get_scene_for_concept("unknown-concept")
        self.assertIsNone(scene)


def _make_asset(concepts, learning_path=None, title="中国电力市场交易体系"):
    """Build a throwaway KnowledgeAsset for template-application tests."""
    return KnowledgeAsset(
        asset_id="test-tmp",
        type="article",
        title=title,
        source_name="test.md",
        created_at="2026-09-08T00:00:00Z",
        source_text="Test content",
        concepts=concepts,
        relations=[],
        learning_path=list(learning_path or []),
    )


class TestTemplateApplication(unittest.TestCase):
    """Test applying domain templates to assets."""
    
    def test_apply_to_asset(self):
        """Test applying electricity template to a KnowledgeAsset."""
        asset = KnowledgeAsset(
            asset_id="test-001",
            type="article",
            title="中国电力市场交易体系",
            source_name="test.md",
            created_at="2026-09-08T00:00:00Z",
            source_text="Test content",
            concepts=[
                Concept(id="et-001", name="两级市场架构", definition="", evidence=[]),
                Concept(id="et-010", name="上网电价", definition="", evidence=[]),
            ],
            relations=[],
            learning_path=[]
        )
        
        result = apply_domain_template(asset, "electricity_trading")
        self.assertTrue(result)
        
        c001 = asset.concept_by_id("et-001")
        self.assertIsNotNone(c001)
        self.assertEqual(
            c001.definition,
            "中国电力市场实行省级市场与区域市场两级运作，分别负责省内和跨省跨区交易组织。"
        )
        
        c010 = asset.concept_by_id("et-010")
        self.assertIsNotNone(c010)
        # Definition should be enriched from template
        self.assertEqual(c010.name, "上网电价")
        self.assertTrue(len(c010.definition) > 0)
        self.assertTrue("发电企业" in c010.definition or "上网电价" in c010.definition)
    
    def test_apply_stamps_locations_for_verbatim_evidence(self):
        """Template evidence written into an asset whose source_text contains
        the sentence verbatim must get a SourceLocation (badge can anchor);
        paraphrase-only sources stay location-free (silent degradation)."""
        from expert_anything.core.domain_templates import get_domain_template

        tpl = get_domain_template("electricity_trading")
        tpl_concept = next(
            c for ch in tpl.chapters for c in ch.get("concepts", [])
        )
        verbatim = tpl_concept["evidence"][0]
        # a source that genuinely contains the template sentence verbatim
        source_text = "背景介绍。\n" + verbatim + "\n后续说明段落。"

        def make_asset(text: str) -> KnowledgeAsset:
            return KnowledgeAsset(
                asset_id="stamp-001",
                type="article",
                title="中国电力市场交易体系",
                source_name="test.md",
                created_at="2026-09-08T00:00:00Z",
                source_text=text,
                concepts=[
                    Concept(
                        id="et-001",
                        name=tpl_concept["name"],
                        definition="",
                        evidence=[],
                    )
                ],
                relations=[],
                learning_path=[],
            )

        hit = make_asset(source_text)
        apply_domain_template(hit, "electricity_trading")
        c = hit.concept_by_id("et-001")
        self.assertEqual(c.evidence, [verbatim])
        self.assertTrue(
            c.locations, "verbatim template evidence should be anchored"
        )
        self.assertEqual(c.locations[0].snippet[:40], verbatim[:40])

        miss = make_asset("完全无关的正文，不含任何模板语句。")
        apply_domain_template(miss, "electricity_trading")
        c2 = miss.concept_by_id("et-001")
        self.assertEqual(c2.evidence, [verbatim])  # enrichment unchanged
        self.assertFalse(c2.locations)  # silent degradation, no anchor

    def test_apply_to_unknown_domain(self):
        """Test applying unknown domain returns a falsy, explicitly-marked result."""
        asset = _make_asset([])
        
        result = apply_domain_template(asset, "unknown_domain")
        self.assertFalse(result)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "unknown_domain")
        self.assertEqual(result.matched_count, 0)

    def test_definition_not_overwritten(self):
        """Grounded asset text must survive template enrichment."""
        original = "这是资产自带、已锚定原文的定义。"
        asset = _make_asset([
            Concept(id="c001", name="两级市场架构", definition=original,
                    evidence=["原文证据"]),
        ])

        result = apply_domain_template(asset, "electricity_trading")

        self.assertEqual(asset.concept_by_id("c001").definition, original)
        self.assertEqual(asset.concept_by_id("c001").evidence, ["原文证据"])
        self.assertEqual(result.enriched_count, 0)

    def test_quick_path_not_applied_without_mapping(self):
        """Without a single name match the original path must stay untouched."""
        asset = _make_asset([], learning_path=["old-path"])

        result = apply_domain_template(asset, "electricity_trading")

        self.assertEqual(asset.learning_path, ["old-path"])
        self.assertFalse(result.learning_path_applied)
        self.assertTrue(result.degraded)
        self.assertEqual(result.reason, "degraded_no_mapping")


class TestTemplateGuardRails(unittest.TestCase):
    """Regression guards for the silent-failure defect (dangling path IDs).

    The old implementation matched template concepts by ID (``et-*``) while
    assets carry ``c*`` IDs, so enrichment never fired and the learning path
    was overwritten with IDs absent from the asset. These assertions fail on
    that behaviour.
    """

    def _demo_asset(self):
        asset_path = (Path(__file__).parent.parent / "data" / "_demo"
                      / "electricity_trading_asset.json")
        if not asset_path.exists():
            self.skipTest("Demo asset not found")
        with open(asset_path, "r", encoding="utf-8") as f:
            return KnowledgeAsset.from_dict(json.load(f))

    def test_mapping_is_name_based_not_id_based(self):
        """Template ``et-*`` concepts must map onto the asset's ``c*`` IDs."""
        asset = self._demo_asset()

        report = build_concept_mapping(asset, ELECTRICITY_TRADING_TEMPLATE)

        self.assertEqual(report["template_concept_count"], 19)
        self.assertGreaterEqual(report["matched_count"], 10)
        self.assertGreaterEqual(report["coverage"], DEFAULT_MIN_COVERAGE)
        # The exact pair that used to silently never match.
        self.assertEqual(report["mapping"].get("et-001"), "c001")
        self.assertEqual(report["mapping"].get("et-013"), "c008")
        # Parenthetical alias: 节点边际电价(LMP) ↔ 节点边际电价(LMP)
        self.assertEqual(report["mapping"].get("et-019"), "c010")

    def test_learning_path_ids_exist_in_asset(self):
        """Every ID written to learning_path must exist in asset.concepts."""
        asset = self._demo_asset()

        result = apply_domain_template(asset, "electricity_trading")

        self.assertTrue(result.learning_path_applied)
        self.assertTrue(asset.learning_path)
        known = {c.id for c in asset.concepts}
        for cid in asset.learning_path:
            self.assertIn(cid, known, f"dangling learning_path ID: {cid}")
        self.assertEqual(asset.learning_path, result.learning_path)

    def test_enrichment_reaches_matched_concepts(self):
        """Enrichment must actually fire on a name-matched concept."""
        asset = _make_asset([
            Concept(id="c001", name="两级市场架构", definition="", evidence=[]),
            Concept(id="c002", name="现货交易", definition="", evidence=[]),
        ])

        result = apply_domain_template(asset, "electricity_trading")

        self.assertEqual(result.mapping_details[0]["asset_id"], "c001")
        self.assertIn("definition", result.mapping_details[0]["enriched_fields"])
        self.assertTrue(asset.concept_by_id("c001").definition)
        self.assertTrue(asset.concept_by_id("c002").evidence)

    def test_low_coverage_keeps_original_path(self):
        """Low coverage must degrade instead of rewriting the path."""
        asset = _make_asset(
            [Concept(id="c001", name="两级市场架构", definition="d", evidence=["e"])],
            learning_path=["c001"],
        )

        result = apply_domain_template(asset, "electricity_trading")

        self.assertEqual(asset.learning_path, ["c001"])
        self.assertFalse(result.learning_path_applied)
        self.assertTrue(result.degraded)
        self.assertEqual(result.reason, "degraded_low_coverage")
        self.assertLess(result.coverage, DEFAULT_MIN_COVERAGE)

    def test_no_matching_concept_leaves_path_and_stats(self):
        """Unrelated concepts: no enrichment, no path rewrite, stats reported."""
        asset = _make_asset(
            [Concept(id="c001", name="无关概念", definition="d", evidence=["e"])],
            learning_path=["c001"],
        )

        result = apply_domain_template(asset, "electricity_trading")

        self.assertTrue(result)                       # template exists
        self.assertFalse(result.learning_path_applied)
        self.assertEqual(asset.learning_path, ["c001"])
        self.assertEqual(result.matched_count, 0)
        self.assertEqual(len(result.unmatched_template_concepts), 19)
        # UI-facing payload stays JSON-serialisable.
        self.assertEqual(result.to_dict()["learning_path"], ["c001"])


class TestDemoAsset(unittest.TestCase):
    """Test loading and using the demo electricity trading asset."""
    
    def test_load_demo_asset(self):
        """Test loading the demo electricity trading asset from JSON."""
        asset_path = Path(__file__).parent.parent / "data" / "_demo" / "electricity_trading_asset.json"
        
        if not asset_path.exists():
            self.skipTest("Demo asset not found")
        
        with open(asset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        asset = KnowledgeAsset.from_dict(data)
        
        self.assertEqual(asset.asset_id, "a20260908-001")
        self.assertEqual(
            asset.title,
            "中国电力市场交易体系：从政策到实践的快速理解"
        )
        self.assertEqual(len(asset.concepts), 10)
        self.assertEqual(len(asset.relations), 5)
        self.assertEqual(len(asset.learning_path), 10)
    
    def test_asset_scenes(self):
        """Test generating scenes for concepts in demo asset."""
        asset_path = Path(__file__).parent.parent / "data" / "_demo" / "electricity_trading_asset.json"
        
        if not asset_path.exists():
            self.skipTest("Demo asset not found")
        
        with open(asset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        asset = KnowledgeAsset.from_dict(data)
        
        from expert_anything.core.decoder import fallback_scene
        
        for concept in asset.concepts:
            scene = fallback_scene(asset, concept)
            self.assertIsNotNone(scene)
            self.assertIn("nodes", scene)
            self.assertGreaterEqual(len(scene["nodes"]), 3)


class TestConceptReferenceResolution(unittest.TestCase):
    """``resolve_template_concept_id``: template ID / asset ID / name routes.

    Deterministic, no LLM: every route must land on the template's own ID
    space so downstream scene lookup stops depending on which ID space the
    caller happens to speak.
    """

    def _demo_asset(self):
        asset_path = (Path(__file__).parent.parent / "data" / "_demo"
                      / "electricity_trading_asset.json")
        if not asset_path.exists():
            self.skipTest("Demo asset not found")
        with open(asset_path, "r", encoding="utf-8") as f:
            return KnowledgeAsset.from_dict(json.load(f))

    def test_template_id_route(self):
        self.assertEqual(resolve_template_concept_id("et-001"), "et-001")
        self.assertEqual(resolve_template_concept_id("et-013"), "et-013")
        self.assertEqual(resolve_template_concept_id(" et-015 "), "et-015")

    def test_asset_id_route(self):
        """Asset ``c*`` IDs resolve through the asset concept's name."""
        asset = self._demo_asset()

        self.assertEqual(resolve_template_concept_id("c001", asset), "et-001")
        self.assertEqual(resolve_template_concept_id("c007", asset), "et-011")
        self.assertEqual(resolve_template_concept_id("c008", asset), "et-013")

    def test_name_route(self):
        self.assertEqual(resolve_template_concept_id("两级市场架构"), "et-001")
        self.assertEqual(resolve_template_concept_id(" 两级市场架构 "), "et-001")
        self.assertEqual(resolve_template_concept_id("输配电价"), "et-011")

    def test_parenthetical_alias_route(self):
        """Full name, name without brackets and the bracket body all hit et-013."""
        for ref in ("节点边际电价(LMP)", "节点边际电价（LMP）",
                    "节点边际电价", "LMP", "lmp"):
            self.assertEqual(resolve_template_concept_id(ref), "et-013", ref)

    def test_unknown_reference_returns_empty(self):
        """Unresolvable references return "" so callers fall back."""
        asset = self._demo_asset()

        self.assertEqual(resolve_template_concept_id("c999", asset), "")
        self.assertEqual(resolve_template_concept_id("不存在的概念"), "")
        self.assertEqual(resolve_template_concept_id(""), "")
        self.assertEqual(resolve_template_concept_id(None), "")

    def test_unregistered_domain_returns_empty(self):
        # ``carbon_trading`` is a registered domain now, so a template ID of
        # *another* domain must not resolve inside it either.
        self.assertEqual(
            resolve_template_concept_id("et-001", None,
                                        domain_id="carbon_trading"), "")
        self.assertEqual(
            resolve_template_concept_id("ct-001", None,
                                        domain_id="fusion_energy"), "")

    def test_carbon_template_id_resolves_in_its_own_domain(self):
        self.assertEqual(
            resolve_template_concept_id("ct-001", None,
                                        domain_id="carbon_trading"), "ct-001")


class TestSceneResolution(unittest.TestCase):
    """``get_scene_for_concept``: the same three routes, on curated scenes."""

    def _demo_asset(self):
        asset_path = (Path(__file__).parent.parent / "data" / "_demo"
                      / "electricity_trading_asset.json")
        if not asset_path.exists():
            self.skipTest("Demo asset not found")
        with open(asset_path, "r", encoding="utf-8") as f:
            return KnowledgeAsset.from_dict(json.load(f))

    def test_scene_by_template_id(self):
        for tid, title in (("et-001", "中国电力市场两级架构"),
                           ("et-011", "电价形成机制"),
                           ("et-013", "节点边际电价(LMP)构成"),
                           ("et-015", "日前市场交易流程")):
            scene = get_scene_for_concept(tid)
            self.assertIsNotNone(scene, tid)
            self.assertEqual(scene["title"], title)

    def test_scene_by_asset_id(self):
        """Regression: ``c001`` used to return None while ``et-001`` worked."""
        asset = self._demo_asset()

        scene = get_scene_for_concept("c001", asset)
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "中国电力市场两级架构")

        scene = get_scene_for_concept("c008", asset)
        self.assertIsNotNone(scene)
        self.assertEqual(scene["title"], "节点边际电价(LMP)构成")

    def test_scene_by_name_and_alias(self):
        for ref in ("节点边际电价(LMP)", "节点边际电价（LMP）",
                    "节点边际电价", "LMP", "lmp"):
            scene = get_scene_for_concept(ref)
            self.assertIsNotNone(scene, ref)
            self.assertEqual(scene["title"], "节点边际电价(LMP)构成")

    def test_scene_by_other_names(self):
        self.assertEqual(get_scene_for_concept("两级市场架构")["title"],
                         "中国电力市场两级架构")
        self.assertEqual(get_scene_for_concept("上网电价")["title"],
                         "电价形成机制")
        self.assertEqual(get_scene_for_concept("日前市场流程")["title"],
                         "日前市场交易流程")

    def test_resolved_scenes_pass_admission(self):
        asset = self._demo_asset()
        for ref in ("c001", "c007", "c008", "节点边际电价(LMP)"):
            scene = get_scene_for_concept(ref, asset)
            verdict, norm = check_scene(scene)
            self.assertTrue(bool(verdict), f"{ref}: {verdict.reason}")
            self.assertIsNotNone(norm)

    def test_concept_without_curated_scene_returns_none(self):
        """No curated scene -> None, so the caller falls back instead of guessing."""
        asset = self._demo_asset()

        self.assertIsNone(get_scene_for_concept("et-004"))
        self.assertIsNone(get_scene_for_concept("现货交易"))
        self.assertIsNone(get_scene_for_concept("c004", asset))  # 现货交易
        self.assertIsNone(get_scene_for_concept("c999", asset))

    def test_scene_for_concept_id_direct(self):
        self.assertEqual(scene_for_concept_id("et-010")["title"], "电价形成机制")
        self.assertIsNone(scene_for_concept_id("et-004"))
        self.assertIsNone(scene_for_concept_id(""))


class TestDomainSceneChain(unittest.TestCase):
    """The teaching/reading call point: domain scene when it exists, else fallback."""

    def _demo_asset(self):
        asset_path = (Path(__file__).parent.parent / "data" / "_demo"
                      / "electricity_trading_asset.json")
        if not asset_path.exists():
            self.skipTest("Demo asset not found")
        with open(asset_path, "r", encoding="utf-8") as f:
            return KnowledgeAsset.from_dict(json.load(f))

    def _generic_asset(self, title="设计 Agent Memory"):
        """Non-domain asset whose concept name collides with the electricity template."""
        return KnowledgeAsset(
            asset_id="generic-001", type="txt", title=title,
            source_name="t.txt", created_at="2026", source_text="x",
            concepts=[
                Concept(id="c001", name="两级市场架构",
                        definition="把短期记忆与长期记忆组合使用。",
                        evidence=["短期记忆保存在当前会话内。"]),
            ],
            relations=[],
        )

    def test_domain_asset_uses_domain_scene(self):
        asset = self._demo_asset()
        spec = decoder.scene_for_concept(asset, asset.concept_by_id("c001"))
        self.assertEqual(spec["title"], "中国电力市场两级架构")

    def test_non_domain_asset_falls_back(self):
        """A name collision in a non-electricity asset must not pull in domain visuals."""
        asset = self._generic_asset()
        spec = decoder.scene_for_concept(asset, asset.concept_by_id("c001"))

        self.assertIn("知识结构", spec["title"])
        self.assertEqual(spec["nodes"][0]["kind"], "current")
        verdict, _ = decoder.check_scene(spec)
        self.assertTrue(bool(verdict), verdict.reason)

    def test_domain_concept_without_scene_falls_back(self):
        """Domain asset, concept outside the curated set -> generic fallback."""
        asset = self._demo_asset()
        spec = decoder.scene_for_concept(asset, asset.concept_by_id("c004"))  # 现货交易

        self.assertIn("知识结构", spec["title"])
        verdict, _ = decoder.check_scene(spec)
        self.assertTrue(bool(verdict), verdict.reason)

    def test_domain_gate(self):
        asset = self._generic_asset()
        concept = asset.concept_by_id("c001")

        # Title says nothing about electricity -> gated out.
        self.assertIsNone(domain_scene_for(asset, concept))
        # Unknown/other domain -> no electricity scene.
        self.assertIsNone(domain_scene_for(asset, concept, domain="carbon_trading"))
        # Explicit override (used when the caller already knows the domain).
        self.assertIsNotNone(domain_scene_for(asset, concept,
                                              domain="electricity_trading"))

    def test_asset_less_call_falls_back(self):
        """No asset -> nothing to gate on -> generic fallback, never a crash."""
        spec = decoder.scene_for_concept(None, self._generic_asset().concept_by_id("c001"))
        self.assertIn("知识结构", spec["title"])

    def test_tutor_lesson_carries_domain_scene_without_llm(self):
        asset = self._demo_asset()
        tutor = Tutor(asset, llm=None)

        lesson = tutor.teach(asset.concept_by_id("c001"), style="diagram")

        self.assertIn("scene", lesson)
        self.assertEqual(lesson["scene"]["title"], "中国电力市场两级架构")
        verdict, _ = decoder.check_scene(lesson["scene"])
        self.assertTrue(bool(verdict), verdict.reason)

    def test_tutor_lesson_falls_back_outside_domain(self):
        asset = self._generic_asset()
        tutor = Tutor(asset, llm=None)

        lesson = tutor.teach(asset.concept_by_id("c001"), style="diagram")

        self.assertIn("知识结构", lesson["scene"]["title"])
        verdict, _ = decoder.check_scene(lesson["scene"])
        self.assertTrue(bool(verdict), verdict.reason)


if __name__ == "__main__":
    unittest.main()
