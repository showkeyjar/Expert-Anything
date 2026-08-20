# -*- coding: utf-8 -*-
"""Tests for core.map_context — siblings / next level / concept comparison.

The cognitive map must yield *information gain* on every click: siblings give
"what stands next to it", next_level gives "where it leads", compare gives
"what makes it different". These tests pin the deterministic derivation rules.
"""
import unittest

from expert_anything.core.map_context import (
    siblings, next_level, compare_concepts,
)
from expert_anything.core.models import KnowledgeAsset, Concept, Relation


def _asset():
    """Six concepts in two chapters, with relations and a learning path."""
    cs = [
        Concept(id="c1", name="命题逻辑", definition="研究命题及其真值。",
                chapter="第一章 逻辑基础"),
        Concept(id="c2", name="合取", definition="两个命题同时为真。",
                chapter="第一章 逻辑基础"),
        Concept(id="c3", name="析取", definition="至少一个命题为真。",
                chapter="第一章 逻辑基础"),
        Concept(id="c4", name="蕴含", definition="条件命题的真值关系。",
                chapter="第二章 推理"),
        Concept(id="c5", name="自然演绎", definition="从前提推出结论的规则系统。",
                chapter="第二章 推理"),
        Concept(id="c6", name="孤立概念", definition="没有任何关系。",
                chapter=""),  # 无章节、无关系、不在路径
        Concept(id="c7", name="归谬法", definition="假设反命题推出矛盾。",
                chapter=""),  # 无章节，但通过关系连到 c5 → 主题兜底可用
    ]
    rels = [
        Relation(id="r1", source="c1", target="c2", label="包含"),
        Relation(id="r2", source="c1", target="c3", label="包含"),
        Relation(id="r3", source="c2", target="c4", label="用于定义"),
        Relation(id="r4", source="c3", target="c5", label="用于证明"),
        Relation(id="r5", source="c7", target="c5", label="用于证明"),
    ]
    return KnowledgeAsset(
        asset_id="a1", type="book", title="逻辑学", source_name="",
        created_at="", source_text="",
        concepts=cs, relations=rels,
        learning_path=["c1", "c2", "c3", "c4", "c5"],
    )


class TestSiblings(unittest.TestCase):
    def test_same_chapter_first(self):
        a = _asset()
        out = siblings(a, "c2")
        names = [x["name"] for x in out]
        # c2 的同级：同章节的 c1、c3（不混入 cluster 里的全书概念）
        self.assertEqual(names, ["命题逻辑", "析取"])
        self.assertNotIn("蕴含", names)
        self.assertNotIn("自然演绎", names)

    def test_topic_cluster_fallback(self):
        a = _asset()
        # c7 无章节 → 用关系连通分量兜底：c5 与整本书同分量
        out = siblings(a, "c7")
        names = [x["name"] for x in out]
        self.assertIn("自然演绎", names)
        self.assertIn("命题逻辑", names)

    def test_lonely_concept_empty(self):
        a = _asset()
        self.assertEqual(siblings(a, "c6"), [])

    def test_mastery_attached(self):
        a = _asset()
        ls = {"concepts": {"命题逻辑": {"name": "命题逻辑", "mastery": 0.9}}}
        out = siblings(a, "c2", learner_state=ls)
        hit = next((x for x in out if x["name"] == "命题逻辑"), None)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit["mastery"], 0.9)

    def test_max_n(self):
        a = _asset()
        out = siblings(a, "c2", max_n=1)
        self.assertEqual(len(out), 1)


class TestNextLevel(unittest.TestCase):
    def test_relation_neighbours_labelled(self):
        a = _asset()
        out = next_level(a, "c1")
        by_name = {x["name"]: x for x in out}
        self.assertIn("合取", by_name)
        self.assertEqual(by_name["合取"]["label"], "包含")
        self.assertEqual(by_name["合取"]["dir"], "out")

    def test_incoming_relation_dir(self):
        a = _asset()
        out = next_level(a, "c2")
        by_name = {x["name"]: x for x in out}
        self.assertIn("命题逻辑", by_name)
        self.assertEqual(by_name["命题逻辑"]["dir"], "in")  # c1 -> c2 是入边

    def test_learning_path_successors(self):
        a = _asset()
        # c4 的关系邻居：c2（入）；路径后继：c5
        out = next_level(a, "c4")
        names = [x["name"] for x in out]
        self.assertIn("自然演绎", names)
        self.assertIn("合取", names)

    def test_no_rel_no_path_empty(self):
        a = _asset()
        self.assertEqual(next_level(a, "c6"), [])

    def test_no_rel_path_fallback(self):
        a = KnowledgeAsset(
            asset_id="a2", type="book", title="t", source_name="",
            created_at="", source_text="",
            concepts=[
                Concept(id="x1", name="X1", definition="d"),
                Concept(id="x2", name="X2", definition="d"),
                Concept(id="x3", name="X3", definition="d"),
            ],
            relations=[], learning_path=["x1", "x2", "x3"],
        )
        out = next_level(a, "x2")
        names = [x["name"] for x in out]
        self.assertIn("X1", names)
        self.assertIn("X3", names)
        self.assertEqual({x["dir"] for x in out}, {"path"})


class TestCompare(unittest.TestCase):
    def test_basic_fields_and_similarity(self):
        a = _asset()
        r = compare_concepts(a, "c2", "c3")
        self.assertEqual(r["a"]["name"], "合取")
        self.assertEqual(r["b"]["name"], "析取")
        self.assertGreaterEqual(r["similarity"], 0.0)
        self.assertLessEqual(r["similarity"], 1.0)
        self.assertTrue(r["chapter_same"])  # 同一章
        self.assertIn("共享", "".join(r["points"]))  # 共享邻居 c1

    def test_unique_relations(self):
        a = _asset()
        r = compare_concepts(a, "c2", "c3")
        # c2 独有：→ c4；c3 独有：→ c5
        self.assertTrue(any("蕴含" in p for p in r["rel_only_a"]))
        self.assertTrue(any("自然演绎" in p for p in r["rel_only_b"]))

    def test_chapter_diff(self):
        a = _asset()
        r = compare_concepts(a, "c2", "c5")
        self.assertFalse(r["chapter_same"])
        self.assertTrue(any("第一章" in p and "第二章" in p for p in r["points"]))

    def test_mastery_gap_hint(self):
        a = _asset()
        ls = {"concepts": {
            "合取": {"name": "合取", "mastery": 0.9},
            "析取": {"name": "析取", "mastery": 0.3},
        }}
        r = compare_concepts(a, "c2", "c3", learner_state=ls)
        self.assertAlmostEqual(r["mastery_diff"], -0.6)  # b - a
        self.assertIn("析取", r["learning_hint"])  # 提示先学低掌握度一方

    def test_teacher_note_diff(self):
        from expert_anything.core.teacher import TeacherModel, ConceptNote
        a = _asset()
        t = TeacherModel(asset_id="a1")
        t.concept_notes = [
            ConceptNote(
                concept_id="c2", name="合取",
                significance="合取是基础", prerequisites=["命题逻辑"],
                misconceptions=["把合取当成析取"], connections=["蕴含"]),
            ConceptNote(
                concept_id="c3", name="析取",
                significance="析取是基础", prerequisites=["命题逻辑"],
                misconceptions=["把析取当成合取"], connections=["蕴含"]),
        ]
        r = compare_concepts(a, "c2", "c3", teacher=t)
        self.assertEqual(r["note_diff"]["prereq_only_a"], [])
        self.assertEqual(r["note_diff"]["miscon_only_a"], ["把合取当成析取"])
        self.assertEqual(r["note_diff"]["miscon_only_b"], ["把析取当成合取"])
        self.assertTrue(any("合取当成析取" in p for p in r["points"]))

    def test_no_points_fallback(self):
        # 两个完全孤立、无共享的概念
        a = KnowledgeAsset(
            asset_id="a3", type="book", title="t", source_name="",
            created_at="", source_text="",
            concepts=[
                Concept(id="p1", name="P1", definition="甲的定义。"),
                Concept(id="p2", name="P2", definition="乙的定义。"),
            ],
            relations=[], learning_path=[],
        )
        r = compare_concepts(a, "p1", "p2")
        from expert_anything.core.i18n import t as _t
        self.assertEqual(r["points"], [_t("compare_no_points")])

    def test_invalid_inputs(self):
        a = _asset()
        with self.assertRaises(ValueError):
            compare_concepts(a, "c2", "c2")  # 同一点
        with self.assertRaises(ValueError):
            compare_concepts(a, "c2", "nope")  # 不存在

    def test_default_hint(self):
        a = _asset()
        r = compare_concepts(a, "c2", "c5")
        self.assertTrue(r["learning_hint"])


if __name__ == "__main__":
    unittest.main()
