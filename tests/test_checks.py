"""Tests for the code-enforced admission checks (OmniScientist-inspired)
and the stuck-detection / learning-trace loop.

All tests are deterministic: no LLM, no GUI.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import checks
from expert_anything.core.learner import (
    adaptive_path,
    normalize,
    record_evaluation,
    register_asset,
    stuck_concepts,
    is_stuck,
)
from expert_anything.core.models import Concept, KnowledgeAsset
from expert_anything.core.teacher import (
    TeacherModel,
    incorporate_stuck_signal,
    anomaly_concept_ids,
)
from expert_anything.core.tutor import Tutor, _next_style


def _concept(name="Agent Memory", definition="Memory 让 Agent 跨回合保留关键信息。"):
    return Concept(id="c1", name=name, definition=definition,
                   evidence=["Agent 在执行多轮任务时会丢失上下文，Memory 让 Agent 跨回合保留关键信息。"])


def _asset():
    return KnowledgeAsset(
        asset_id="a1", type="txt", title="T", source_name="t.txt",
        created_at="2026", source_text="x",
        concepts=[_concept()],
        relations=[],
    )


class _FakeLLM:
    """Fake client returning a scripted sequence of JSON responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.3, json_mode=False, max_tokens=500):
        self.calls.append(messages)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _lesson(explanation, example="例：...", practice="用自己的话解释。", concept=None):
    return {
        "concept": (concept or _concept()).name,
        "style": "例子",
        "explanation": explanation,
        "example": example,
        "analogy": "",
        "cross_link": None,
        "steps": [],
        "practice": practice,
        "evidence": [],
    }


class TestCheckLesson(unittest.TestCase):
    def test_ok_lesson_passes(self):
        c = _concept()
        ok = checks.check_lesson(c, _lesson(
            "Agent Memory 之所以重要，是因为多轮任务里上下文会丢；"
            "它像便签一样把关键信息留给下一回合。"))
        self.assertTrue(bool(ok), ok.reason)

    def test_empty_explanation_rejected(self):
        v = checks.check_lesson(_concept(), _lesson("   "))
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "empty_explanation")

    def test_definition_copy_rejected(self):
        c = _concept()
        v = checks.check_lesson(c, _lesson(c.definition))
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "explanation_is_definition")

    def test_short_explanation_rejected(self):
        v = checks.check_lesson(_concept(), _lesson("太短"))
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "explanation_too_short")

    def test_missing_practice_rejected(self):
        v = checks.check_lesson(_concept(), _lesson(
            "这个概念很关键，它解决多轮任务丢上下文的问题。", practice=""))
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "empty_practice")

    def test_template_duplicate_rejected(self):
        c1 = _concept()
        c2 = _concept(name="Context Engineering")
        text1 = ("Agent Memory 在系统里处于枢纽位置，非常重要，"
                 "它通过一套机制把信息在合适的时机放回上下文，"
                 "解决了多轮任务中信息丢失的核心痛点，务必掌握，"
                 "建议结合实际项目反复练习才能体会。")
        text2 = text1.replace("Agent Memory", "Context Engineering")
        self.assertNotEqual(text1, text2)  # names differ, rest identical
        recent = [{"name": c1.name, "explanation": text1, "example": "例：一样"}]
        v = checks.check_lesson(c2, _lesson(text2, example="例：一样"), recent=recent)
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "template_duplicate")

    def test_same_concept_reteach_allowed_to_overlap(self):
        c = _concept()
        text = ("Agent Memory 很重要，通过机制 A 把信息留到下一回合，"
                "解决了多轮任务的核心痛点，值得深入理解。")
        recent = [{"name": c.name, "explanation": text, "example": "例：一样"}]
        v = checks.check_lesson(c, _lesson(text, example="例：一样"), recent=recent)
        self.assertTrue(bool(v), v.reason)


class TestCheckQuiz(unittest.TestCase):
    def test_true_false_ok(self):
        v, norm = checks.check_quiz({
            "type": "true_false", "question": "Memory 让 Agent 跨回合保留信息。",
            "correct": "true", "explanation": "证据原句。"})
        self.assertTrue(bool(v))
        self.assertIs(norm["correct"], True)

    def test_ordering_normalizes_string_indices(self):
        v, norm = checks.check_quiz({
            "type": "ordering", "question": "排序",
            "options": ["定义要记什么", "选择存储介质", "做召回与压缩"],
            "correct_order": ["0", "2", "1"]})
        self.assertTrue(bool(v))
        self.assertEqual(norm["correct_order"], [0, 2, 1])

    def test_ordering_option_text_mapped(self):
        v, norm = checks.check_quiz({
            "type": "ordering", "question": "排序",
            "options": ["定义要记什么", "选择存储介质", "做召回与压缩"],
            "correct_order": ["定义要记什么", "选择存储介质", "做召回与压缩"]})
        self.assertTrue(bool(v))
        self.assertEqual(norm["correct_order"], [0, 1, 2])

    def test_ordering_not_a_permutation_rejected(self):
        v, _ = checks.check_quiz({
            "type": "ordering", "question": "排序",
            "options": ["A", "B", "C"], "correct_order": [0, 0, 1]})
        self.assertFalse(bool(v))
        self.assertEqual(v.code, "not_a_permutation")

    def test_bad_type_rejected(self):
        v, _ = checks.check_quiz({"type": "essay", "question": "写论文"})
        self.assertFalse(bool(v))


class TestCheckEvalPracticeTemper(unittest.TestCase):
    def test_practice_too_short_rejected(self):
        v, _ = checks.check_practice({"task": "做一下"})
        self.assertFalse(bool(v))

    def test_practice_ok(self):
        v, norm = checks.check_practice({"task": "请写出 Agent Memory 的三步设计并说明每步依据。"})
        self.assertTrue(bool(v))
        self.assertEqual(norm["task"][:4], "请写出 ")

    def test_evaluation_clamps_and_fills_feedback(self):
        v, norm = checks.check_evaluation({"score": 1.7, "feedback": "  "})
        self.assertTrue(bool(v))
        self.assertEqual(norm["score"], 1.0)
        self.assertTrue(norm["feedback"].strip())

    def test_evaluation_bad_score_rejected(self):
        v, _ = checks.check_evaluation({"score": "high"})
        self.assertFalse(bool(v))

    def test_temper_claims(self):
        out = checks.temper_claims("你肯定能掌握它，这是唯一的方法，第一次提出。")
        self.assertNotIn("肯定", out)
        self.assertNotIn("唯一的方法", out)
        self.assertNotIn("第一次提出", out)


class TestTeachAdmissionLoop(unittest.TestCase):
    """Tutor.teach must admit only checked lessons, retry once, then fall back."""

    def test_bad_then_good_lesson_admitted_on_retry(self):
        c = _concept()
        good = ('{"explanation": "Memory 像便签：多轮任务里上下文会丢，'
                '它把关键信息留给下一回合，解决断档痛点。", '
                '"example": "例：客服 Agent 记住用户偏好", "practice": "说说它解决什么。"}')
        llm = _FakeLLM([
            '{"explanation": "太短", "example": "", "practice": ""}',  # fails check
            good,
        ])
        t = Tutor(_asset(), llm)
        res = t.teach(c)
        self.assertEqual(len(llm.calls), 2)  # retried once
        self.assertIn("未通过系统代码校验", llm.calls[1][1].content)  # failure quoted
        self.assertTrue(len(res["explanation"]) > 12)
        self.assertEqual(t._recent_lessons[-1]["name"], c.name)

    def test_persistently_bad_lesson_falls_back(self):
        c = _concept()
        llm = _FakeLLM(['{"explanation": "短", "example": "", "practice": ""}'] * 2)
        t = Tutor(_asset(), llm)
        res = t.teach(c)
        self.assertEqual(len(llm.calls), 2)  # budget of 2 used
        # deterministic fallback still renders a usable, grounded lesson
        self.assertTrue(res["explanation"])
        self.assertTrue(res["practice"])

    def test_temper_applied_to_admitted_lesson(self):
        c = _concept()
        llm = _FakeLLM([(
            '{"explanation": "掌握 Memory 肯定能提升 Agent 稳定性，'
            '它解决多轮任务的上下文断档。", "example": "例：x", '
            '"practice": "说说它解决什么。"}')])
        t = Tutor(_asset(), llm)
        res = t.teach(c)
        self.assertNotIn("肯定", res["explanation"])

    def test_style_rotation_for_stuck_concept(self):
        self.assertEqual(_next_style("example"), "diagram")
        self.assertEqual(_next_style("steps"), "example")


class TestCrossJudgeArbitration(unittest.TestCase):
    """Boundary-band scores (0.4–0.6) get a second, independent judge."""

    def _eval_json(self, score):
        return (
            '{"score": %s, "understood": %s, "feedback": "点评", '
            '"reference": "参考", "gap": ""}' % (score, "true" if score >= 0.6 else "false")
        )

    def _tutor(self, responses):
        return Tutor(_asset(), _FakeLLM(responses))

    def test_boundary_score_triggers_second_judge(self):
        t = self._tutor([
            self._eval_json(0.5),
            '{"score": 0.9, "note": "答出了关键证据"}',
        ])
        res = t.evaluate(_concept(), "Memory 像便签，把关键信息留给下一回合。")
        self.assertEqual(len(t.llm.calls), 2)          # arbiter was consulted
        self.assertEqual(res["judges"], 2)
        self.assertEqual(res["score"], 0.7)            # (0.5 + 0.9) / 2
        self.assertIn("复核", res["feedback"])

    def test_clear_pass_skips_arbiter(self):
        t = self._tutor([self._eval_json(0.9)])
        res = t.evaluate(_concept(), "Memory 像便签，把关键信息留给下一回合。")
        self.assertEqual(len(t.llm.calls), 1)
        self.assertEqual(res["judges"], 1)
        self.assertEqual(res["score"], 0.9)

    def test_clear_fail_skips_arbiter(self):
        t = self._tutor([self._eval_json(0.1)])
        res = t.evaluate(_concept(), "不知道")
        self.assertEqual(len(t.llm.calls), 1)
        self.assertEqual(res["judges"], 1)

    def test_arbiter_failure_keeps_first_verdict(self):
        t = self._tutor([
            self._eval_json(0.5),
            RuntimeError("network down"),               # arbiter call fails
        ])
        res = t.evaluate(_concept(), "Memory 像便签，把关键信息留给下一回合。")
        self.assertEqual(res["judges"], 1)
        self.assertEqual(res["score"], 0.5)             # first verdict stands

    def test_arbiter_unparseable_score_ignored(self):
        t = self._tutor([
            self._eval_json(0.5),
            '{"note": "没有分数"}',                      # no parseable score
        ])
        res = t.evaluate(_concept(), "Memory 像便签，把关键信息留给下一回合。")
        self.assertEqual(res["judges"], 1)
        self.assertEqual(res["score"], 0.5)

    def test_arbitrated_understood_follows_final_score(self):
        t = self._tutor([
            self._eval_json(0.5),                        # first judge: fail
            '{"score": 0.9, "note": "证据完整"}',         # arbiter: strong pass
        ])
        res = t.evaluate(_concept(), "Memory 像便签，把关键信息留给下一回合。")
        self.assertEqual(res["score"], 0.7)
        self.assertTrue(res["understood"])               # 0.7 >= 0.6


class TestStuckLoop(unittest.TestCase):
    def _state(self):
        return {"profile": {"goal": "g", "baseline": "b", "style": "例子"},
                "assets": {}, "concepts": {}, "history": []}

    def test_stuck_after_three_failures(self):
        s = self._state()
        for _ in range(3):
            record_evaluation(s, "Agent Memory", "a1", 0.2, "ans", "fb")
        stuck = stuck_concepts(s)
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0]["key"], normalize("Agent Memory"))
        self.assertTrue(is_stuck(s, "agent memory"))

    def test_not_stuck_with_one_success(self):
        s = self._state()
        record_evaluation(s, "Agent Memory", "a1", 0.2, "ans", "fb")
        record_evaluation(s, "Agent Memory", "a1", 0.2, "ans", "fb")
        record_evaluation(s, "Agent Memory", "a1", 0.9, "ans", "fb")
        self.assertEqual(stuck_concepts(s), [])

    def test_not_stuck_below_attempt_count(self):
        s = self._state()
        record_evaluation(s, "Agent Memory", "a1", 0.1, "ans", "fb")
        record_evaluation(s, "Agent Memory", "a1", 0.1, "ans", "fb")
        self.assertEqual(stuck_concepts(s), [])

    def test_meta_trace_recorded(self):
        s = self._state()
        record_evaluation(s, "Agent Memory", "a1", 0.5, "ans", "fb",
                          meta={"channel": "answer", "style": "图示"})
        row = s["history"][0]
        self.assertEqual(row["meta"]["channel"], "answer")
        self.assertEqual(row["meta"]["style"], "图示")

    def test_adaptive_path_tags_stuck(self):
        asset = _asset()
        s = self._state()
        register_asset(s, asset)
        for _ in range(3):
            record_evaluation(s, "Agent Memory", asset.asset_id, 0.1, "a", "f")
        items = adaptive_path(asset, s)
        self.assertTrue(items)
        self.assertIn("stuck", items[0]["tags"])

    def test_incorporate_stuck_signal_creates_anomaly(self):
        asset = _asset()
        tm = TeacherModel(asset_id=asset.asset_id)
        tm = incorporate_stuck_signal(asset, tm, "c1", attempts=3, avg_score=0.2)
        self.assertEqual(len(tm.anomalies), 1)
        self.assertEqual(tm.anomalies[0].kind, "learner_gap")
        self.assertEqual(tm.anomalies[0].severity, "high")
        ids = anomaly_concept_ids(asset, tm)
        # anomaly is surfaced_to_student -> not "open", matches existing semantics
        self.assertTrue(isinstance(ids, set))


if __name__ == "__main__":
    unittest.main()
