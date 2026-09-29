"""Tests for the Knowledge Decoder (SceneSpec admission + renderers + the
teach → scene pipeline). All deterministic: no network, no GUI.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import decoder
from expert_anything.core.models import Concept, KnowledgeAsset, Relation
from expert_anything.core.tutor import Tutor

from tests.test_checks import _FakeLLM


def _concept():
    return Concept(
        id="c1", name="混合记忆架构",
        definition="把短期记忆和长期记忆组合，分别负责当前任务工作集和跨会话领域知识。",
        evidence=["短期记忆保存在当前会话内；长期记忆写入外部存储可跨会话复用。"],
    )


def _asset():
    c1 = _concept()
    c2 = Concept(id="c2", name="短期记忆", definition="会话内记忆。", evidence=["会话结束即消失。"])
    c3 = Concept(id="c3", name="长期记忆", definition="跨会话记忆。", evidence=["写入外部存储。"])
    return KnowledgeAsset(
        asset_id="a1", type="txt", title="设计 Agent Memory", source_name="t.txt",
        created_at="2026", source_text="x",
        concepts=[c1, c2, c3],
        relations=[
            Relation(id="r1", source="c1", label="组合", target="c2"),
            Relation(id="r2", source="c1", label="组合", target="c3"),
        ],
    )


def _valid_scene():
    return {
        "title": "混合记忆架构",
        "nodes": [
            {"id": "n0", "label": "混合记忆架构", "kind": "current"},
            {"id": "n1", "label": "短期记忆", "kind": "store"},
            {"id": "n2", "label": "长期记忆", "kind": "store"},
            {"id": "n3", "label": "检索", "kind": "flow"},
        ],
        "edges": [
            {"from": "n0", "to": "n1", "label": "组合"},
            {"from": "n0", "to": "n2", "label": "组合"},
            {"from": "n2", "to": "n3", "label": "需要"},
        ],
        "steps": [
            {"caption": "混合架构居中", "show": ["n0"], "active": "n0"},
            {"caption": "组合两种记忆", "show": ["n0", "n1", "n2"], "active": "n1"},
            {"caption": "长期记忆靠检索", "show": ["n0", "n1", "n2", "n3"], "active": "n3"},
        ],
        "game": {
            "type": "sort",
            "goal": "按信息流向排序",
            "items": ["检索", "长期记忆", "混合架构"],
            "answer": [2, 1, 0],
        },
    }


class TestCheckScene(unittest.TestCase):
    def test_valid_scene_passes_and_normalizes(self):
        v, spec = decoder.check_scene(_valid_scene())
        self.assertTrue(bool(v), v.reason)
        self.assertIsNotNone(spec)
        self.assertEqual(len(spec["nodes"]), 4)
        # geometry auto-filled by deterministic layout
        for n in spec["nodes"]:
            self.assertIn("x", n)
            self.assertIn("y", n)

    def test_layout_ignores_llm_coordinates(self):
        s = _valid_scene()
        # adversarial coordinates from the LLM: everything stacked in a corner
        for n in s["nodes"]:
            n["x"], n["y"] = 1, 1
        v, spec = decoder.check_scene(s)
        self.assertTrue(bool(v), v.reason)
        pts = {(n["x"], n["y"]) for n in spec["nodes"]}
        self.assertEqual(len(pts), len(spec["nodes"]))  # no two nodes coincide

    def test_layout_never_overlaps(self):
        # adversarial scene: many nodes, every node linked to every other
        nodes = [{"id": f"n{i}", "label": f"概念节点{i}", "kind": "box"}
                 for i in range(decoder.MAX_NODES)]
        edges = [{"from": f"n{i}", "to": f"n{j}", "label": ""}
                 for i in range(decoder.MAX_NODES)
                 for j in range(i + 1, decoder.MAX_NODES)]
        s = _valid_scene()
        s["nodes"], s["edges"] = nodes, edges
        v, spec = decoder.check_scene(s)
        self.assertTrue(bool(v), v.reason)
        rects = [(n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"])
                 for n in spec["nodes"]]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                overlap = not (a[2] <= b[0] or b[2] <= a[0] or
                               a[3] <= b[1] or b[3] <= a[1])
                self.assertFalse(
                    overlap, f"nodes {i} and {j} overlap: {a} vs {b}")
        # everything stays on the canvas
        for n in spec["nodes"]:
            self.assertGreaterEqual(n["x"], 0)
            self.assertLessEqual(n["x"] + n["w"], spec["width"])
            self.assertGreaterEqual(n["y"], 0)
            self.assertLessEqual(n["y"] + n["h"], spec["height"])

    def test_bad_node_count_rejected(self):
        s = _valid_scene()
        s["nodes"] = s["nodes"][:2]
        v, spec = decoder.check_scene(s)
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "scene_bad_node_count")
        self.assertIsNone(spec)

    def test_duplicate_node_id_rejected(self):
        s = _valid_scene()
        s["nodes"][1]["id"] = "n0"
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_dup_node_id")

    def test_edge_unknown_ref_rejected(self):
        s = _valid_scene()
        s["edges"][0]["to"] = "ghost"
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_edge_bad_ref")

    def test_step_unknown_ref_rejected(self):
        s = _valid_scene()
        s["steps"][1]["show"].append("ghost")
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_step_bad_ref")

    def test_step_without_caption_rejected(self):
        s = _valid_scene()
        s["steps"][0]["caption"] = "  "
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_step_no_caption")

    def test_bad_step_count_rejected(self):
        s = _valid_scene()
        s["steps"] = s["steps"][:1]
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_bad_step_count")

    def test_game_answer_not_permutation_rejected(self):
        s = _valid_scene()
        s["game"]["answer"] = [0, 0, 1]
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_game_not_permutation")

    def test_game_bad_item_count_rejected(self):
        s = _valid_scene()
        s["game"]["items"] = ["a", "b"]
        s["game"]["answer"] = [0, 1]
        v, _ = decoder.check_scene(s)
        self.assertEqual(v.code, "scene_game_bad_items")

    def test_unknown_kind_falls_back_to_box(self):
        s = _valid_scene()
        s["nodes"][3]["kind"] = "weird"
        v, spec = decoder.check_scene(s)
        self.assertTrue(bool(v))
        self.assertEqual(spec["nodes"][3]["kind"], "box")

    def test_non_dict_rejected(self):
        v, spec = decoder.check_scene(["nope"])
        self.assertFalse(bool(v))
        self.assertIsNone(spec)


class TestRenderers(unittest.TestCase):
    def setUp(self):
        v, self.spec = decoder.check_scene(_valid_scene())
        assert v

    def test_static_svg_contains_labels(self):
        svg = decoder.render_svg(self.spec)
        self.assertIn("<svg", svg)
        self.assertIn("混合记忆架构", svg)
        self.assertIn("组合", svg)  # edge label

    def test_step_svg_fades_not_yet_shown(self):
        svg = decoder.render_svg(self.spec, step=0)
        # only n0 visible at step 0 → the other nodes fade to 0.12
        self.assertIn('opacity="0.12"', svg)
        full = decoder.render_svg(self.spec)
        self.assertNotIn('opacity="0.12"', full)

    def test_step_frames_match_steps(self):
        frames = decoder.render_step_svgs(self.spec)
        self.assertEqual(len(frames), 3)
        self.assertIn("检索", frames[2]["caption"] + frames[2]["svg"])

    def test_interactive_html_self_contained(self):
        from expert_anything.core.i18n import set_lang
        set_lang("zh-CN")
        html = decoder.render_interactive_html(self.spec, "混合记忆架构", "设计 Agent Memory")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("混合记忆架构", html)
        self.assertIn("长期记忆", html)          # game items present
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))  # no CDN
        self.assertNotIn("</script>", html.split("var FRAMES")[1].split("\n")[0])
        # answer permutation inlined for the game
        self.assertIn("ANSWER", html)

    def test_html_static_overview_is_default(self):
        # progressive representation: L1 static overview first — the player
        # starts in overview mode; steps are opt-in, never auto-animated
        from expert_anything.core.i18n import set_lang
        set_lang("zh-CN")
        html = decoder.render_interactive_html(self.spec, "混合记忆架构", "t")
        self.assertIn("showStatic();", html)
        self.assertIn('id="start"', html)            # opt-in step button
        self.assertIn('id="back"', html)             # back-to-overview button
        self.assertIn('id="dots" style="display:none"', html)
        from expert_anything.core.i18n import t
        self.assertIn(t("decoder_overview_hint")[:6], html)  # hint text rendered
        self.assertIn("全景", html)                   # overview pill visible

    def test_html_without_game(self):
        spec = dict(self.spec)
        spec["game"] = None
        html = decoder.render_interactive_html(spec, "x", "y")
        self.assertNotIn("ANSWER", html)


class TestFallbackScene(unittest.TestCase):
    def test_fallback_scene_passes_admission(self):
        asset = _asset()
        spec = decoder.fallback_scene(asset, asset.concepts[0])
        v, norm = decoder.check_scene({
            "title": spec.get("title"), "nodes": spec["nodes"],
            "edges": spec["edges"], "steps": spec["steps"],
            "game": spec.get("game"),
        })
        self.assertTrue(bool(v), v.reason)
        self.assertGreaterEqual(len(spec["nodes"]), decoder.MIN_NODES)

    def test_fallback_scene_without_relations_still_valid(self):
        # a concept with no relation links at all must still yield a valid
        # scene (>= MIN_NODES, >= MIN_STEPS, passes admission)
        lonely = Concept(id="z1", name="孤立概念", definition="无关系。",
                         evidence=["证据。"])
        asset = KnowledgeAsset(
            asset_id="a2", type="txt", title="T2", source_name="t.txt",
            created_at="2026", source_text="x", concepts=[lonely], relations=[],
        )
        spec = decoder.fallback_scene(asset, lonely)
        v, _ = decoder.check_scene({
            "title": spec.get("title"), "nodes": spec["nodes"],
            "edges": spec["edges"], "steps": spec["steps"], "game": spec.get("game"),
        })
        self.assertTrue(bool(v), v.reason)
        self.assertGreaterEqual(len(spec["steps"]), decoder.MIN_STEPS)

    def test_scene_summary(self):
        spec = decoder.fallback_scene(_asset(), _concept())
        self.assertIn("nodes=", decoder.scene_summary(spec))
        self.assertEqual(decoder.scene_summary(None), "")


class TestTeachScenePipeline(unittest.TestCase):
    LESSON = (
        '{"explanation": "混合记忆架构之所以重要，是因为单一记忆要么丢上下文要么太慢；'
        '它像工作台与仓库的分工。", "example": "当前会话放短期记忆，用户偏好放长期记忆。",'
        ' "analogy": "工作台与仓库", "cross_link": null, "steps": [],'
        ' "practice": "说说两种记忆各放什么。"}'
    )
    SCENE_OK = (
        '{"title": "混合记忆架构", "nodes": ['
        '{"id": "n0", "label": "混合记忆架构", "kind": "current"},'
        '{"id": "n1", "label": "短期记忆", "kind": "store"},'
        '{"id": "n2", "label": "长期记忆", "kind": "store"},'
        '{"id": "n3", "label": "检索", "kind": "flow"}], '
        '"edges": [{"from": "n0", "to": "n1", "label": "组合"}], '
        '"steps": [{"caption": "定位", "show": ["n0"], "active": "n0"},'
        '{"caption": "组合", "show": ["n0", "n1"], "active": "n1"}], '
        '"game": null}'
    )
    SCENE_BAD = '{"nodes": [{"id": "n0"}]}'  # missing label -> rejected

    def test_llm_diagram_style_gets_scene(self):
        asset = _asset()
        tutor = Tutor(asset, llm=_FakeLLM([self.LESSON, self.SCENE_OK]))
        lesson = tutor.teach(asset.concepts[0], style="diagram")
        self.assertIn("scene", lesson)
        v, spec = decoder.check_scene(lesson["scene"])
        self.assertTrue(bool(v), v.reason)
        # the admitted spec is the normalized LLM scene (4 nodes, title kept)
        self.assertEqual(len(lesson["scene"]["nodes"]), 4)
        self.assertEqual(lesson["scene"]["title"], "混合记忆架构")

    def test_llm_scene_rejected_falls_back_to_relation_graph(self):
        asset = _asset()
        tutor = Tutor(asset, llm=_FakeLLM([self.LESSON, self.SCENE_BAD, self.SCENE_BAD]))
        lesson = tutor.teach(asset.concepts[0], style="diagram")
        # deterministic fallback: current node is the concept, neighbours linked
        scene = lesson["scene"]
        v, _ = decoder.check_scene(scene)
        self.assertTrue(bool(v), v.reason)
        self.assertEqual(scene["nodes"][0]["kind"], "current")
        labels = [n["label"] for n in scene["nodes"]]
        self.assertIn("短期记忆", labels)

    def test_no_llm_diagram_style_still_gets_scene(self):
        asset = _asset()
        tutor = Tutor(asset, llm=None)
        lesson = tutor.teach(asset.concepts[0], style="diagram")
        self.assertIn("scene", lesson)
        v, _ = decoder.check_scene(lesson["scene"])
        self.assertTrue(bool(v), v.reason)

    def test_other_styles_have_no_scene(self):
        # Every fallback style now includes a visual scene (scene key),
        # so the learner gets a diagram regardless of teaching style.
        asset = _asset()
        tutor = Tutor(asset, llm=None)
        lesson = tutor.teach(asset.concepts[0], style="example")
        self.assertIn("scene", lesson)
        self.assertTrue(lesson["scene"].get("nodes"))


if __name__ == "__main__":
    unittest.main()
