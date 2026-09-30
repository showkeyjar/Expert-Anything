"""Tests for AutoHarness (meta-harness: HarnessSpec admission + deterministic
run + guards + evolution + differential comparison). All deterministic: no
network, no GUI, no LLM key required.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import auto_harness as ah
from expert_anything.core.models import Concept


def _concept(mastery: float = 0.0):
    return Concept(
        id="c1", name="混合记忆架构",
        definition="把短期记忆和长期记忆组合，分别负责当前任务工作集和跨会话领域知识。",
        evidence=["短期记忆保存在当前会话内；长期记忆写入外部存储可跨会话复用。"],
    )


def _spec(**over):
    s = {
        "name": "测试 Harness", "mode": "fast", "tools": ["teach", "quiz"],
        "policy": {"teach_styles": ["例子", "图示"],
                   "guard_ids": ["no_definition_copy", "budget_ok"],
                   "retry": 1, "fallback": "deterministic"},
        "loop": {"max_steps": 4},
        "evaluation": {"metric": "learning_gain", "threshold": 0.6},
        "meta": {"budget_cost": 50, "sandbox": "local", "lang": "zh-CN", "note": "x"},
    }
    s.update(over)
    return s


class _LLM:
    """Fake client: scripted chat() responses (same contract as core.llm)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.3, json_mode=False, max_tokens=500):
        self.calls.append(messages)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestCheckHarness(unittest.TestCase):
    def test_valid_passes_and_normalizes(self):
        v, spec = ah.check_harness(_spec())
        self.assertTrue(bool(v), v.reason)
        self.assertIsNotNone(spec)
        self.assertEqual(spec["tools"], ["teach", "quiz"])
        self.assertEqual(spec["policy"]["teach_styles"], ["例子", "图示"])
        self.assertEqual(spec["loop"]["max_steps"], 4)

    def test_duplicate_tools_deduped_preserving_order(self):
        v, spec = ah.check_harness(_spec(tools=["quiz", "teach", "quiz"]))
        self.assertTrue(bool(v), v.reason)
        self.assertEqual(spec["tools"], ["quiz", "teach"])

    def test_non_dict_rejected(self):
        v, spec = ah.check_harness(["nope"])
        self.assertFalse(bool(v))
        self.assertIsNone(spec)

    def test_missing_name_rejected(self):
        s = _spec()
        del s["name"]
        v, _ = ah.check_harness(s)
        self.assertEqual(v.code, "harness_no_name")

    def test_bad_mode_rejected(self):
        v, _ = ah.check_harness(_spec(mode="turbo"))
        self.assertEqual(v.code, "harness_bad_mode")

    def test_unknown_tool_rejected(self):
        v, _ = ah.check_harness(_spec(tools=["teach", "teleport"]))
        self.assertEqual(v.code, "harness_bad_tool")

    def test_empty_tools_rejected(self):
        v, _ = ah.check_harness(_spec(tools=[]))
        self.assertEqual(v.code, "harness_no_tools")

    def test_unknown_guard_rejected(self):
        s = _spec()
        s["policy"]["guard_ids"] = ["no_definition_copy", "mind_control"]
        v, _ = ah.check_harness(s)
        self.assertEqual(v.code, "harness_bad_guard")

    def test_bad_fallback_rejected(self):
        s = _spec()
        s["policy"]["fallback"] = "llm_everything"
        v, _ = ah.check_harness(s)
        self.assertEqual(v.code, "harness_bad_fallback")

    def test_bad_metric_rejected(self):
        s = _spec()
        s["evaluation"]["metric"] = "vibes"
        v, _ = ah.check_harness(s)
        self.assertEqual(v.code, "harness_bad_metric")

    def test_bad_sandbox_rejected(self):
        v, _ = ah.check_harness(_spec(meta={"sandbox": "cloud9"}))
        self.assertEqual(v.code, "harness_bad_sandbox")

    def test_retry_and_steps_clamped(self):
        s = _spec()
        s["policy"]["retry"] = -3
        s["loop"]["max_steps"] = 999
        v, spec = ah.check_harness(s)
        self.assertTrue(bool(v), v.reason)
        self.assertEqual(spec["policy"]["retry"], 0)
        self.assertEqual(spec["loop"]["max_steps"], ah.MAX_STEPS)

    def test_defaults_applied(self):
        v, spec = ah.check_harness({
            "name": "裸 spec", "tools": ["teach"],
        })
        self.assertTrue(bool(v), v.reason)
        self.assertEqual(spec["mode"], "fast")
        self.assertEqual(spec["policy"]["teach_styles"], ["例子"])
        self.assertEqual(spec["policy"]["retry"], 1)
        self.assertEqual(spec["evaluation"]["threshold"], 0.6)
        self.assertEqual(spec["meta"]["sandbox"], "local")

    def test_fallback_harness_passes_admission(self):
        v, spec = ah.check_harness(ah.fallback_harness("某概念"))
        self.assertTrue(bool(v), v.reason)
        self.assertEqual(spec["tools"], ["teach", "quiz"])


class TestHarnessRun(unittest.TestCase):
    def test_fast_harness_runs_end_to_end(self):
        _, spec = ah.check_harness(_spec())
        h = ah.build_harness(spec, learner_state={"concepts": {}})
        traj, report = h.run({"concept": _concept(), "goal": "理解"})
        self.assertGreaterEqual(len(traj), 2)          # teach + quiz
        tools = [e["tool"] for e in traj]
        self.assertEqual(tools, ["teach", "quiz"])
        for e in traj:
            self.assertIn("seq", e)                    # append-only events
            self.assertIn("summary", e)
            self.assertTrue(e["ok"])
            self.assertEqual(e["blocked_by"], "")
        self.assertEqual(report["blocked"], 0)
        self.assertEqual(report["metric"], "learning_gain")
        self.assertGreaterEqual(report["learning_gain"], 0.0)
        self.assertLessEqual(report["learning_gain"], 1.0)

    def test_budget_guard_stops_early(self):
        _, spec = ah.check_harness(_spec(
            tools=["teach", "quiz", "practice"], loop={"max_steps": 10},
            meta={"budget_cost": 1, "sandbox": "local"}))
        h = ah.build_harness(spec)
        traj, report = h.run({"concept": _concept(), "goal": "x"})
        self.assertIn("budget_ok", report["guard_triggers"])
        self.assertGreater(report["blocked"], 0)
        # 预算为 1：teach 成本 5 已超支 → 实际执行事件 ≤ 1；
        # 预算耗尽事件本身也落轨迹（append-only），且是最后一条，blocked_by=budget_ok
        executed = [e for e in traj if (e.get("cost") or 0) > 0]
        self.assertLessEqual(len(executed), 1)
        self.assertEqual(traj[-1]["blocked_by"], "budget_ok")

    def test_safe_only_gatekeeper_blocks_sandbox_tools(self):
        # ToolTrust gatekeeper: practice 需要沙箱，sandbox=none 时 fail-closed。
        # 守卫必须显式声明才生效（policy 部分覆盖时其余字段由准入规范化补默认值）。
        _, spec = ah.check_harness(_spec(
            tools=["practice"], policy={"guard_ids": ["safe_only"]},
            meta={"budget_cost": 50, "sandbox": "none"}))
        h = ah.build_harness(spec)
        traj, report = h.run({"concept": _concept(), "goal": "x"})
        self.assertIn("safe_only", report["guard_triggers"])
        self.assertEqual(report["blocked"], 1)
        self.assertEqual(report["task_success"], 0.0)
        self.assertEqual(traj[0]["blocked_by"], "safe_only")

    def test_review_skipped_when_not_due(self):
        _, spec = ah.check_harness(_spec(tools=["review"]))
        h = ah.build_harness(spec)
        traj, _ = h.run({"concept": _concept(), "goal": "x", "due": False})
        self.assertEqual(traj[0]["skipped"], "not_due")
        traj2, _ = h.run({"concept": _concept(), "goal": "x", "due": True})
        self.assertEqual(traj2[0]["skipped"], "")

    def test_no_definition_copy_rotation_then_fallback(self):
        # provider 连续两次返回定义原文 → 轮换重试后仍被拒 → 显式确定性降级
        def bad_provider(tool, args, ctx):
            return {"payload": {"explanation": ctx["concept"].definition,
                                "example": "x", "practice": "y"},
                    "summary": "抄定义", "score": None}
        _, spec = ah.check_harness(_spec(
            tools=["teach"], policy={"teach_styles": ["例子", "图示"],
                                     "guard_ids": ["no_definition_copy"],
                                     "retry": 1, "fallback": "deterministic"}))
        h = ah.build_harness(spec, providers={"teach": bad_provider})
        traj, report = h.run({"concept": _concept(), "goal": "x"})
        self.assertEqual(report["blocked"], 1)
        self.assertIn("no_definition_copy", report["guard_triggers"])
        # 兜底用的是确定性 stub，最终事件必须 ok
        self.assertTrue(traj[-1]["ok"])
        self.assertNotEqual(traj[-1]["summary"], "抄定义")

    def test_evidence_grounded_vetoes_off_concept(self):
        def generic_provider(tool, args, ctx):
            return {"payload": {"explanation": "这是一个与任何概念都无关的通用模板讲解内容。",
                                "example": "通用例子", "practice": "通用练习"},
                    "summary": "通用", "score": None}
        _, spec = ah.check_harness(_spec(
            tools=["teach"], policy={"teach_styles": ["例子"],
                                     "guard_ids": ["evidence_grounded"],
                                     "retry": 1, "fallback": "deterministic"}))
        h = ah.build_harness(spec, providers={"teach": generic_provider})
        _, report = h.run({"concept": _concept(), "goal": "x"})
        self.assertIn("evidence_grounded", report["guard_triggers"])
        self.assertEqual(report["blocked"], 1)

    def test_llm_path_used_when_provided(self):
        from tests.test_checks import _FakeLLM
        from expert_anything.core.models import KnowledgeAsset, Relation
        c1 = _concept()
        c2 = Concept(id="c2", name="短期记忆", definition="会话内记忆。",
                     evidence=["会话结束即消失。"])
        c3 = Concept(id="c3", name="长期记忆", definition="跨会话记忆。",
                     evidence=["写入外部存储。"])
        asset = KnowledgeAsset(
            asset_id="a1", type="txt", title="设计 Agent Memory",
            source_name="t.txt", created_at="2026", source_text="x",
            concepts=[c1, c2, c3],
            relations=[
                Relation(id="r1", source="c1", label="组合", target="c2"),
                Relation(id="r2", source="c1", label="组合", target="c3"),
            ],
        )
        lesson = ('{"explanation": "混合记忆架构把短期记忆和长期记忆组合起来，'
                  '像工作台与仓库的分工。", "example": "当前会话放短期记忆。",'
                  ' "practice": "说说两种记忆各放什么。"}')
        _, spec = ah.check_harness(_spec(tools=["teach"]))
        # asset 非空 + llm 提供 → _prov_teach 走 Tutor.teach（内置准入+降级）
        h = ah.build_harness(spec, asset=asset, llm=_FakeLLM([lesson]))
        traj, _ = h.run({"concept": _concept(), "goal": "x"})
        self.assertIn("记忆", traj[0]["summary"])   # LLM 讲解进了轨迹


class TestEvolution(unittest.TestCase):
    def test_stuck_rotates_style_and_adds_scene(self):
        _, spec = ah.check_harness(_spec())
        report = {"value": 0.3, "guard_triggers": {}, "steps_used": 2}  # 卡壳
        cands = ah.evolve(spec, report)
        self.assertGreaterEqual(len(cands), 1)
        c = cands[0]
        v, _ = ah.check_harness(c)                    # 候选必须过准入
        self.assertTrue(v)
        self.assertIn("scene", c["tools"])
        self.assertEqual(c["policy"]["teach_styles"][0], "图示")  # 例子→图示

    def test_guard_trim_never_trims_safety(self):
        # 安全铁律不是演化参数：safe_only 触发最多也绝不裁，
        # O2 只裁可裁守卫中触发最多者（此处 budget_ok 被裁）。
        _, spec = ah.check_harness(_spec(
            policy={"teach_styles": ["例子"],
                    "guard_ids": ["no_definition_copy", "budget_ok", "safe_only"],
                    "retry": 0, "fallback": "deterministic"}))
        report = {"value": 0.9, "guard_triggers": {"safe_only": 3, "budget_ok": 1},
                  "steps_used": 2}
        cands = ah.evolve(spec, report)
        names = [c["name"] for c in cands]
        self.assertTrue(any("裁成本守卫" in n for n in names), names)
        for c in cands:
            v, _ = ah.check_harness(c)
            self.assertTrue(v)
            self.assertIn("safe_only", c["policy"]["guard_ids"])  # 安全守卫保留
        trimmed = [c for c in cands if "裁成本守卫" in c["name"]]
        self.assertTrue(trimmed)
        self.assertNotIn("budget_ok", trimmed[0]["policy"]["guard_ids"])

    def test_guard_trim_skips_quality_without_explicit_signal(self):
        # 质量类守卫（no_definition_copy/evidence_grounded）是来源约束铁律：
        # 只有触发统计可裁性都满足时才出候选，绝不自动裁 —— 此处验证
        # 仅 quality 触发时 O2 仍生成候选（名称标注），但 safe_only 永不入列。
        _, spec = ah.check_harness(_spec(
            policy={"teach_styles": ["例子"],
                    "guard_ids": ["no_definition_copy", "safe_only"],
                    "retry": 0, "fallback": "deterministic"}))
        report = {"value": 0.9,
                  "guard_triggers": {"no_definition_copy": 4, "safe_only": 2},
                  "steps_used": 2}
        cands = ah.evolve(spec, report)
        names = [c["name"] for c in cands]
        self.assertTrue(any("裁守卫no_definition_copy" in n for n in names), names)
        for c in cands:
            self.assertIn("safe_only", c["policy"]["guard_ids"])

    def test_budget_exhaustion_expands(self):
        _, spec = ah.check_harness(_spec(loop={"max_steps": 4}))
        report = {"value": 0.9, "guard_triggers": {}, "steps_used": 4}  # 用满
        cands = ah.evolve(spec, report)
        names = [c["name"] for c in cands]
        self.assertTrue(any("扩容" in n for n in names), names)

    def test_steady_returns_base(self):
        _, spec = ah.check_harness(_spec())
        report = {"value": 0.9, "guard_triggers": {}, "steps_used": 2}
        cands = ah.evolve(spec, report)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["name"], spec["name"])


class TestStuckDrivenEvolution(unittest.TestCase):
    """卡壳信号自动驱动 harness 演化（stuck 闭环 → evolve 的桥）。"""

    @staticmethod
    def _state(scores, name="混合记忆架构", extra_histories=None):
        from expert_anything.core import learner as _learner
        key = _learner.normalize(name)
        rows = [{"concept": name, "key": key, "asset_id": "a1", "score": s,
                 "answer": "x", "feedback": "f",
                 "at": f"2026-08-18T00:00:{i:02d}+00:00"}
                for i, s in enumerate(scores)]
        if extra_histories:
            rows += extra_histories
        return {"concepts": {}, "history": rows}

    def test_stuck_triggers_evolution(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_for_stuck(spec, self._state([0.2, 0.3, 0.4]))
        self.assertTrue(out["evolved"])
        self.assertEqual(out["source"], "stuck")
        self.assertEqual(out["trigger"]["name"], "混合记忆架构")
        self.assertEqual(out["trigger"]["attempts"], 3)
        self.assertTrue(out["candidates"])
        c = out["candidates"][0]
        v, _ = ah.check_harness(c)
        self.assertTrue(v)
        self.assertIn("scene", c["tools"])                     # O1：补图示
        self.assertEqual(c["policy"]["teach_styles"][0], "图示")  # 例子→图示

    def test_steady_no_evolution(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_for_stuck(spec, self._state([0.8, 0.9, 0.85]))
        self.assertFalse(out["evolved"])
        self.assertEqual(out["source"], "steady")
        self.assertIsNone(out["trigger"])
        self.assertEqual(out["candidates"], [])

    def test_harness_threshold_wins_over_default(self):
        # harness 达标线 0.8：0.5/0.6/0.7 全不达标 → 卡壳；
        # 若退到默认 0.6，max=0.7 ≥ 0.6 不会卡壳 —— 证明用的是 harness 自己的线
        _, spec = ah.check_harness(_spec(
            evaluation={"metric": "learning_gain", "threshold": 0.8}))
        out = ah.evolve_for_stuck(spec, self._state([0.5, 0.6, 0.7]))
        self.assertTrue(out["evolved"])

    def test_concept_filter_targets_only_asked_concept(self):
        _, spec = ah.check_harness(_spec())
        state = self._state([0.2, 0.3, 0.4])
        other = self._state([0.1, 0.1, 0.1], name="别的概念")
        state["history"] = other["history"] + state["history"]
        out = ah.evolve_for_stuck(spec, state, concept_name="别的概念")
        self.assertTrue(out["evolved"])
        self.assertEqual(out["trigger"]["name"], "别的概念")
        out2 = ah.evolve_for_stuck(spec, state, concept_name="不存在的概念")
        self.assertFalse(out2["evolved"])

    def test_attempts_boundary(self):
        _, spec = ah.check_harness(_spec())
        out3 = ah.evolve_for_stuck(spec, self._state([0.2, 0.3]), attempts=3)
        self.assertFalse(out3["evolved"])      # 只有 2 次记录，不足 3 次
        out2 = ah.evolve_for_stuck(spec, self._state([0.2, 0.3]), attempts=2)
        self.assertTrue(out2["evolved"])

    def test_candidates_always_pass_admission(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_for_stuck(spec, self._state([0.1, 0.2, 0.3]))
        self.assertTrue(out["candidates"])
        for c in out["candidates"]:
            v, norm = ah.check_harness(c)
            self.assertTrue(bool(v), v.reason)
            self.assertIsNotNone(norm)


class TestSuggest(unittest.TestCase):
    def test_no_llm_returns_fallback(self):
        spec, source = ah.suggest_harness("理解混合记忆架构", llm=None)
        self.assertEqual(source, "fallback")
        v, _ = ah.check_harness(spec)
        self.assertTrue(v)

    def test_valid_llm_spec_admitted_as_llm(self):
        ok = ('{"name": "图示强化 Harness", "mode": "full", '
              '"tools": ["teach", "scene", "quiz"], '
              '"policy": {"teach_styles": ["图示"], "guard_ids": ["no_definition_copy"], '
              '"retry": 1, "fallback": "deterministic"}, '
              '"loop": {"max_steps": 6}, '
              '"evaluation": {"metric": "learning_gain", "threshold": 0.7}, '
              '"meta": {"budget_cost": 60, "sandbox": "local", "lang": "zh-CN", "note": "图示优先"}}')
        spec, source = ah.suggest_harness("目标", llm=_LLM([ok]))
        self.assertEqual(source, "llm")
        self.assertIn("scene", spec["tools"])

    def test_invalid_twice_returns_fallback(self):
        bad1 = '{"name": "坏", "tools": ["teleport"]}'
        bad2 = '{"name": "还是坏", "mode": "turbo", "tools": ["teach"]}'
        spec, source = ah.suggest_harness("目标", llm=_LLM([bad1, bad2]))
        self.assertEqual(source, "fallback")
        v, _ = ah.check_harness(spec)
        self.assertTrue(v)

    def test_retry_recovers_after_rejection(self):
        bad = '{"name": "缺 tools", "mode": "fast"}'
        good = ('{"name": "修正版", "mode": "fast", "tools": ["teach"], '
                '"policy": {"guard_ids": [], "retry": 0, "fallback": "deterministic"}, '
                '"loop": {"max_steps": 2}, "evaluation": {"metric": "learning_gain"}, '
                '"meta": {}}')
        spec, source = ah.suggest_harness("目标", llm=_LLM([bad, good]))
        self.assertEqual(source, "llm_retry")
        self.assertEqual(spec["tools"], ["teach"])


class TestCompare(unittest.TestCase):
    def test_gain(self):
        r = ah.compare_harnesses(
            [{"learning_gain": 0.5}, {"learning_gain": 0.5}],
            [{"learning_gain": 0.7}, {"learning_gain": 0.7}],
            noise_floor=0.05)
        self.assertEqual(r["verdict"], "gain")
        self.assertAlmostEqual(r["diff"], 0.2)

    def test_loss(self):
        r = ah.compare_harnesses(
            [{"learning_gain": 0.7}], [{"learning_gain": 0.5}], noise_floor=0.05)
        self.assertEqual(r["verdict"], "loss")

    def test_noise_within_floor(self):
        # |diff| ≤ noise_floor → 不采纳，即使方向看起来是正的
        r = ah.compare_harnesses(
            [{"learning_gain": 0.50}], [{"learning_gain": 0.53}], noise_floor=0.05)
        self.assertEqual(r["verdict"], "noise")

    def test_inconclusive_when_data_missing(self):
        r = ah.compare_harnesses([], [{"learning_gain": 0.6}])
        self.assertEqual(r["verdict"], "inconclusive")


class TestApplyToLearner(unittest.TestCase):
    def test_mastery_written_with_harness_trace(self):
        state = {"concepts": {}, "history": []}
        report = {"spec_name": "测试 Harness", "concept": "混合记忆架构",
                  "metric": "learning_gain", "value": 0.7, "blocked": 0,
                  "steps_used": 2, "guard_triggers": {}}
        ah.apply_to_learner(report, state, asset_id="a1")
        from expert_anything.core import learner as _learner
        key = _learner.normalize("混合记忆架构")
        self.assertGreater(state["concepts"][key]["mastery"], 0.0)
        self.assertEqual(state["history"][0]["meta"]["channel"], "harness")
        self.assertEqual(state["history"][0]["meta"]["harness"], "测试 Harness")


class TestSummary(unittest.TestCase):
    def test_harness_summary(self):
        _, spec = ah.check_harness(_spec())
        s = ah.harness_summary(spec)
        self.assertIn("mode=fast", s)
        self.assertIn("tools=teach,quiz", s)
        self.assertEqual(ah.harness_summary(None), "")


class TestCostModel(unittest.TestCase):
    """真实成本模型：固定基础 + 内容规模折算（token 近似），纯函数可测。"""

    def test_short_content_costs_base_only(self):
        # 短内容增量≈0：基础固定开销不变（既有行为保持）
        self.assertEqual(ah.estimate_cost("teach", {}, None), 5)
        self.assertEqual(ah.estimate_cost("quiz", {"concept": "x"},
                                          {"summary": "s"}), 2)

    def test_unknown_tool_falls_back_to_one(self):
        self.assertEqual(ah.estimate_cost("hack", {}, None), 1)

    def test_long_content_raises_cost(self):
        # args 240 字符（6 字 × 40）+ result 150 字符 → 390//100 = 3 个单位增量
        args = {"style": "例子", "concept": "混合记忆架构" * 40}
        result = {"summary": "长" * 150, "score": 0.8}
        cost = ah.estimate_cost("teach", args, result)
        self.assertEqual(cost, 5 + (240 + 150) // 100)

    def test_nested_payload_counts(self):
        # result.payload 的嵌套 dict 也计入内容规模（讲解正文在 payload 里）
        result = {"payload": {"explanation": "长" * 200}, "summary": "x"}
        self.assertEqual(ah.estimate_cost("scene", {}, result), 4 + 200 // 100)

    def test_run_adopts_content_cost(self):
        # 集成：注入长输出的 provider → run 总成本高于固定基础
        def _long(tool, args, ctx):
            return {"payload": {}, "summary": "长" * 500, "score": 0.9}
        _, spec = ah.check_harness(_spec(tools=["teach"], loop={"max_steps": 2}))
        h = ah.build_harness(spec, providers={"teach": _long})
        _, report = h.run({"concept": _concept(), "goal": "x"})
        self.assertGreaterEqual(report["cost"], 5 + 500 // 100)

    def test_budget_guard_senses_expensive_output(self):
        # 预算设为固定基础值 5：teach 长输出（成本 10）→ 后续步骤被 budget_ok 拦下
        def _long(tool, args, ctx):
            return {"payload": {}, "summary": "长" * 500, "score": 0.9}
        _, spec = ah.check_harness(_spec(
            tools=["teach", "quiz"], loop={"max_steps": 2},
            meta={"budget_cost": 5, "sandbox": "local"}))
        h = ah.build_harness(spec, providers={"teach": _long})
        traj, report = h.run({"concept": _concept(), "goal": "x"})
        self.assertIn("budget_ok", report["guard_triggers"])
        self.assertEqual(traj[-1]["blocked_by"], "budget_ok")


class TestHarnessState(unittest.TestCase):
    """harness 状态持久化：UI 采纳环节的存储层（headless 可测）。"""

    def _tmp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        return str(self._dir.name) + "/harness_state.json"

    def test_save_load_roundtrip(self):
        path = self._tmp()
        _, spec = ah.check_harness(_spec())
        ah.save_harness_state(path, {"a1": spec})
        loaded = ah.load_harness_state(path)
        self.assertEqual(list(loaded), ["a1"])
        self.assertEqual(loaded["a1"]["name"], spec["name"])
        # 规范化后字段完整（准入补默认值）
        self.assertIn("policy", loaded["a1"])
        self.assertIn("evaluation", loaded["a1"])

    def test_missing_file_returns_empty(self):
        import os
        path = self._tmp()
        if os.path.exists(path):
            os.remove(path)
        self.assertEqual(ah.load_harness_state(path), {})

    def test_corrupt_file_returns_empty(self):
        path = self._tmp()
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json!")
        self.assertEqual(ah.load_harness_state(path), {})

    def test_save_filters_invalid_specs(self):
        # 写入前再过准入：非法 spec 被过滤，不落盘（演化铁律延伸到存储层）
        path = self._tmp()
        bad = {"name": "x", "tools": ["hack"], "policy": {"style": "例子"}}
        _, good = ah.check_harness(_spec())
        ah.save_harness_state(path, {"b1": bad, "g1": good})
        loaded = ah.load_harness_state(path)
        self.assertEqual(list(loaded), ["g1"])

    def test_load_returns_normalized(self):
        # 盘上是手写的非规范化 spec → 读入时被规范化
        path = self._tmp()
        raw = {"name": "raw", "tools": ["teach", "teach", "quiz"],
               "policy": {"style": "例子"}}
        with open(path, "w", encoding="utf-8") as f:
            import json as _json
            _json.dump({"a9": raw}, f)
        loaded = ah.load_harness_state(path)
        self.assertEqual(loaded["a9"]["tools"], ["teach", "quiz"])  # 去重保序


class TestHarnessHistory(unittest.TestCase):
    """演化历史审计链：append-only、与状态文件共存、损坏容错。"""

    def _tmp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        return str(self._dir.name) + "/harness_state.json"

    def _events(self, n=3):
        _, old = ah.check_harness(_spec())
        _, new = ah.check_harness(_spec(
            tools=["teach", "scene", "quiz"], policy={"style": "图示"}))
        return [ah.evolution_event("stuck", old, new, asset_id="a1",
                                   concept="混合记忆架构")
                for _ in range(n)]

    def test_record_and_load_roundtrip(self):
        path = self._tmp()
        events = self._events()
        for ev in events:
            ah.record_harness_evolution(path, ev)
        loaded = ah.load_harness_history(path)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[0]["reason"], "stuck")
        self.assertIn("tools=teach,scene,quiz", loaded[0]["new"])
        self.assertIn("ts", loaded[0])  # 未提供 ts 时自动补时间戳
        self.assertEqual(loaded[-1]["spec_name"], events[-1]["spec_name"])

    def test_missing_file_returns_empty(self):
        path = self._tmp()
        self.assertEqual(ah.load_harness_history(path), [])

    def test_corrupt_file_returns_empty(self):
        path = self._tmp()
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json!")
        self.assertEqual(ah.load_harness_history(path), [])
        # 损坏时 record 以单事件文件重建，不抛错
        _, old = ah.check_harness(_spec())
        ah.record_harness_evolution(
            path, ah.evolution_event("manual", old, old, asset_id="a1"))
        self.assertEqual(len(ah.load_harness_history(path)), 1)

    def test_save_state_preserves_history(self):
        # save_harness_state 全量覆盖文件 —— 必须保留 _history 审计链
        path = self._tmp()
        for ev in self._events(2):
            ah.record_harness_evolution(path, ev)
        _, spec = ah.check_harness(_spec())
        ah.save_harness_state(path, {"a1": spec})
        self.assertEqual(len(ah.load_harness_history(path)), 2)  # 未被冲掉
        self.assertEqual(list(ah.load_harness_state(path)), ["a1"])

    def test_history_hidden_from_state_loader(self):
        # _history 是审计键，不混入 asset 状态（load_harness_state 只出 spec）
        path = self._tmp()
        for ev in self._events(1):
            ah.record_harness_evolution(path, ev)
        states = ah.load_harness_state(path)
        self.assertNotIn("_history", states)


class TestTransfer(unittest.TestCase):
    """跨资产 harness 泛化：画像 → 前提三态 → OFF/ON 差分 → 迁移采纳审计链。"""

    def _asset(self, aid, title, concepts, relations=None, path=None):
        from expert_anything.core.models import KnowledgeAsset
        return KnowledgeAsset(
            asset_id=aid, type="epub", title=title, source_name=f"{title}.md",
            created_at="2026-08-18T00:00:00", source_text="",
            concepts=concepts, relations=relations or [],
            learning_path=path or [c.id for c in concepts],
            method="llm", source_length=1000,
        )

    def _concepts(self, defined=True):
        return [
            Concept(id="a", name="短期记忆",
                    definition=("保存当前任务工作集，容量小、易失。" if defined else ""),
                    evidence=["短期记忆位于当前会话工作区。"], chapter="第1章"),
            Concept(id="b", name="长期记忆",
                    definition=("保存跨会话领域知识，容量大、持久。" if defined else ""),
                    evidence=["长期记忆写入外部存储。"], chapter="第1章"),
            Concept(id="c", name="工作记忆",
                    definition=("执行当前任务时被激活的短期存储。" if defined else ""),
                    evidence=["工作记忆是执行态。"], chapter="第2章"),
        ]

    def _tmp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        return str(self._dir.name) + "/harness_state.json"

    # -- 资产画像 ----------------------------------------------------------
    def test_profile_counts(self):
        asset = self._asset("src", "源书", self._concepts(),
                            relations=[("a", "b")])
        prof = ah.asset_profile(asset)
        self.assertEqual(prof["concepts"], 3)
        self.assertEqual(prof["relations"], 1)
        self.assertEqual(prof["path_steps"], 3)
        self.assertEqual(prof["definition_rate"], 1.0)
        self.assertEqual(prof["density"], round(1 / 3, 2))

    def test_profile_empty_asset_no_divzero(self):
        prof = ah.asset_profile(self._asset("empty", "空书", []))
        self.assertEqual(prof["concepts"], 0)
        self.assertEqual(prof["definition_rate"], 0.0)
        self.assertEqual(prof["density"], 0.0)

    # -- 迁移前提三态（方法论 11：先校验前提再下结论） ---------------------
    def test_eligibility_eligible(self):
        _, spec = ah.check_harness(_spec())
        r = ah.transfer_eligibility(spec, ah.asset_profile(
            self._asset("t1", "目标", self._concepts())))
        self.assertEqual(r["state"], "eligible")

    def test_eligibility_no_concepts_inconclusive(self):
        _, spec = ah.check_harness(_spec())
        r = ah.transfer_eligibility(spec, ah.asset_profile(
            self._asset("t2", "空目标", [])))
        self.assertEqual(r["state"], "inconclusive")
        self.assertEqual(r["reason"], "target_no_concepts")

    def test_eligibility_invalid_spec_inconclusive(self):
        r = ah.transfer_eligibility({"name": "x", "tools": ["hack"]},
                                    {"concepts": 5})
        self.assertEqual(r["state"], "inconclusive")
        self.assertEqual(r["reason"], "invalid_spec")

    def test_eligibility_full_sparse_mismatch(self):
        # full mode 需要 ≥3 概念结构支撑，目标资产稀疏 → mismatch 拦截
        _, spec = ah.check_harness(_spec(mode="full", tools=["teach", "quiz", "practice"]))
        r = ah.transfer_eligibility(spec, ah.asset_profile(
            self._asset("t3", "稀疏目标", self._concepts()[:1])))
        self.assertEqual(r["state"], "mismatch")
        self.assertEqual(r["reason"], "structure_too_sparse")

    def test_eligibility_no_definition_warns(self):
        _, spec = ah.check_harness(_spec())
        r = ah.transfer_eligibility(spec, ah.asset_profile(
            self._asset("t4", "无定义目标", self._concepts(defined=False))))
        self.assertEqual(r["state"], "eligible")  # 警告不阻断
        self.assertTrue(any("定义覆盖率" in w for w in r["warnings"]))

    # -- 差分迁移评估（方法论 6b：OFF/ON 双配置取差分） ----------------------
    def _eval(self, on_spec, target=None, local_spec=None):
        src = self._asset("src", "源书", self._concepts())
        tgt = target or self._asset("tgt", "目标书", self._concepts())
        return ah.evaluate_transfer(on_spec, src, tgt, local_spec=local_spec)

    def test_transfer_gain_minimal_to_fast(self):
        # OFF=minimal(仅 teach，无得分) vs ON=fast(teach+quiz，有得分)
        # → learning_gain 0 → 0.46，diff 远超噪声底噪 → migrate
        _, minimal = ah.check_harness(_spec(mode="minimal", tools=["teach"]))
        _, fast = ah.check_harness(_spec())
        r = self._eval(fast, local_spec=minimal)
        self.assertEqual(r["comparison"]["verdict"], "gain")
        self.assertEqual(r["recommendation"], "migrate")
        self.assertEqual(r["concepts_evaluated"], 3)
        self.assertEqual(r["comparison"]["control"], 0.0)
        self.assertGreater(r["comparison"]["treated"], 0.4)

    def test_transfer_noise_same_tools(self):
        # OFF/ON 工具相同 → 差分=0 → noise，且无成本差 → no_change
        _, spec = ah.check_harness(_spec())
        r = self._eval(spec, local_spec=spec)
        self.assertEqual(r["comparison"]["verdict"], "noise")
        self.assertEqual(r["recommendation"], "no_change")
        self.assertEqual(r["cost_diff"], 0)

    def test_transfer_coverage_diff_migrates(self):
        # 工具集相同时仿真分不可区分 → noise；但 ON 多 practice 槽位 →
        # 计分覆盖度差分 +1（结构性收益，非仿真噪声），成本 ≤ 预算 30% → migrate
        _, control = ah.check_harness(_spec())
        _, on = ah.check_harness(_spec(
            tools=["teach", "scene", "quiz", "practice"],
            meta={"budget_cost": 200}))
        r = self._eval(on, local_spec=control)
        self.assertEqual(r["comparison"]["verdict"], "noise")
        self.assertEqual(r["coverage_control"], 1.0)
        self.assertEqual(r["coverage_treated"], 2.0)
        self.assertEqual(r["coverage_diff"], 1.0)
        self.assertEqual(r["recommendation"], "migrate")

    def test_transfer_coverage_gain_too_expensive(self):
        # 覆盖度提升但成本超预算 30% → 迁移不是免费的 → no_change
        _, control = ah.check_harness(_spec())
        _, on = ah.check_harness(_spec(
            tools=["teach", "scene", "quiz", "practice"],
            meta={"budget_cost": 20}))   # 门槛 max(5, 6)=6，cost_diff 必然超
        r = self._eval(on, local_spec=control)
        self.assertEqual(r["coverage_diff"], 1.0)
        self.assertEqual(r["recommendation"], "no_change")

    def test_transfer_loss_fast_to_minimal(self):
        # ON 反而删掉了测验 → 差分显著为负 → keep_local
        _, minimal = ah.check_harness(_spec(mode="minimal", tools=["teach"]))
        _, fast = ah.check_harness(_spec())
        r = self._eval(minimal, local_spec=fast)
        self.assertEqual(r["comparison"]["verdict"], "loss")
        self.assertEqual(r["recommendation"], "keep_local")

    def test_transfer_no_concepts_inconclusive(self):
        _, spec = ah.check_harness(_spec())
        r = self._eval(spec, target=self._asset("tgt", "空目标", []))
        self.assertEqual(r["comparison"]["verdict"], "inconclusive")
        self.assertEqual(r["recommendation"], "verify")

    def test_transfer_per_concept_detail(self):
        _, minimal = ah.check_harness(_spec(mode="minimal", tools=["teach"]))
        _, fast = ah.check_harness(_spec())
        r = self._eval(fast, local_spec=minimal)
        self.assertEqual(len(r["per_concept"]), 3)
        row = r["per_concept"][0]
        self.assertEqual(set(row), {"concept", "control", "treated",
                                    "cost_control", "cost_treated"})
        # 成本差分随工具增多而上升（ON 多跑 quiz）
        self.assertGreater(r["cost_diff"], 0)

    # -- 迁移采纳（持久化 + 审计链 reason="transfer"） -----------------------
    def test_adopt_persists_and_logs(self):
        path = self._tmp()
        _, old = ah.check_harness(_spec())
        ah.record_harness_evolution(  # 既有审计链：1 条 stuck
            path, ah.evolution_event("stuck", old, old, asset_id="tgt"))
        _, candidate = ah.check_harness(_spec(
            tools=["teach", "scene", "quiz"], policy={"style": "图示"}))
        ok, ev = ah.adopt_harness_for_asset(
            path, "tgt", candidate, source_asset_id="src",
            concept="短期记忆", note="卡壳演化候选迁移")
        self.assertTrue(ok)
        self.assertEqual(ev["reason"], "transfer")
        self.assertEqual(ev["source_asset_id"], "src")
        self.assertEqual(ev["concept"], "短期记忆")
        # 状态已持久化（写入前再过准入）
        states = ah.load_harness_state(path)
        self.assertEqual(states["tgt"]["tools"], ["teach", "scene", "quiz"])
        # 审计链 append-only：既有 stuck 事件未被冲掉，transfer 追加在末尾
        hist = ah.load_harness_history(path)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["reason"], "stuck")
        self.assertEqual(hist[1]["reason"], "transfer")
        self.assertIn("tools=teach,scene,quiz", hist[1]["new"])

    def test_adopt_invalid_spec_noop(self):
        path = self._tmp()
        ok, ev = ah.adopt_harness_for_asset(path, "tgt", {"name": "x"})
        self.assertFalse(ok)
        self.assertEqual(ev, {})
        self.assertEqual(ah.load_harness_state(path), {})
        self.assertEqual(ah.load_harness_history(path), [])


class TestSignalization(unittest.TestCase):
    """演化算子信号化：O2/O3 从"测试手工构造"走向"真实闭环可触发"。

    三层信号：stuck（持续不达标 → O1）、regression（先达标后回退 → O2）、
    会话报告聚合（guard_triggers / steps_exhausted_rate → O2/O3）。
    """

    @staticmethod
    def _state(scores, name="混合记忆架构", extra_histories=None):
        # history 为 newest-first（与 record_evaluation 的 insert(0) 一致）
        from expert_anything.core import learner as _learner
        key = _learner.normalize(name)
        rows = [{"concept": name, "key": key, "asset_id": "a1", "score": s,
                 "answer": "x", "feedback": "f",
                 "at": f"2026-08-18T00:00:{i:02d}+00:00"}
                for i, s in enumerate(scores)]
        if extra_histories:
            rows += extra_histories
        return {"concepts": {}, "history": rows}

    @staticmethod
    def _report(value, *, trig=None, steps=2, max_steps=4, cost=10,
                threshold=0.6):
        return {"value": value, "threshold": threshold, "steps_used": steps,
                "max_steps": max_steps, "guard_triggers": trig or {},
                "cost": cost, "scores": [value]}

    # -- aggregate_reports --------------------------------------------------
    def test_aggregate_reports_stats(self):
        reps = [self._report(0.8, trig={"budget_ok": 2}, cost=10),
                self._report(0.4, trig={"budget_ok": 3}, cost=30,
                             steps=4, max_steps=4)]
        agg = ah.aggregate_reports(reps)
        self.assertEqual(agg["n"], 2)
        self.assertEqual(agg["pass_rate"], 0.5)          # 1/2 达标
        self.assertEqual(agg["avg_value"], 0.6)          # (0.8+0.4)/2
        self.assertEqual(agg["guard_triggers"], {"budget_ok": 5})
        self.assertEqual(agg["steps_exhausted_rate"], 0.5)  # 1/2 用满
        self.assertEqual(agg["avg_cost"], 20)

    def test_aggregate_reports_empty_neutral(self):
        agg = ah.aggregate_reports([])
        self.assertEqual(agg["n"], 0)
        self.assertEqual(agg["pass_rate"], 0.0)
        self.assertEqual(agg["guard_triggers"], {})
        self.assertEqual(agg["steps_exhausted_rate"], 0.0)

    def test_aggregate_reports_tolerates_dirty_fields(self):
        agg = ah.aggregate_reports([
            {"value": "nope", "threshold": None, "guard_triggers": "x",
             "steps_used": None, "cost": "?"},
            self._report(0.9),
        ])
        self.assertEqual(agg["n"], 2)
        self.assertEqual(agg["pass_rate"], 0.5)          # 脏行按 0 计
        self.assertEqual(agg["guard_triggers"], {})

    # -- evolve_from_sessions（O2/O3 的正统信号源） --------------------------
    def test_sessions_o1_rotates_style(self):
        _, spec = ah.check_harness(_spec())
        cands = ah.evolve_from_sessions(
            spec, [self._report(0.4), self._report(0.5)])  # avg 0.45 < 0.6
        self.assertTrue(any("换风格" in c["name"] for c in cands), cands)
        o1 = [c for c in cands if "换风格" in c["name"]][0]
        self.assertIn("scene", o1["tools"])
        self.assertEqual(o1["policy"]["teach_styles"][0], "图示")

    def test_sessions_o2_trims_worst_trimable(self):
        _, spec = ah.check_harness(_spec())
        cands = ah.evolve_from_sessions(spec, [
            self._report(0.8, trig={"budget_ok": 1, "no_definition_copy": 3}),
            self._report(0.9, trig={"no_definition_copy": 2}),
        ])
        names = [c["name"] for c in cands]
        self.assertTrue(any("裁守卫no_definition_copy" in n for n in names), names)
        trimmed = [c for c in cands if "裁守卫no_definition_copy" in c["name"]][0]
        self.assertNotIn("no_definition_copy", trimmed["policy"]["guard_ids"])

    def test_sessions_o2_never_trims_safety(self):
        _, spec = ah.check_harness(_spec(policy={
            "teach_styles": ["例子"],
            "guard_ids": ["no_definition_copy", "budget_ok", "safe_only"],
            "retry": 0, "fallback": "deterministic"}))
        cands = ah.evolve_from_sessions(spec, [
            self._report(0.8, trig={"safe_only": 7, "budget_ok": 1}),
            self._report(0.9, trig={"safe_only": 5}),
        ])
        self.assertTrue(any("裁成本守卫" in c["name"] for c in cands), cands)
        for c in cands:
            self.assertIn("safe_only", c["policy"]["guard_ids"])  # 安全铁律保留

    def test_sessions_o3_expands_when_exhausted(self):
        _, spec = ah.check_harness(_spec(loop={"max_steps": 4},
                                         meta={"budget_cost": 50}))
        cands = ah.evolve_from_sessions(spec, [
            self._report(0.7, steps=4, max_steps=4),
            self._report(0.65, steps=4, max_steps=4),
            self._report(0.9, steps=2, max_steps=4),
        ])  # exhausted_rate = 2/3 ≥ 0.5
        names = [c["name"] for c in cands]
        self.assertTrue(any("扩容" in n for n in names), names)
        o3 = [c for c in cands if "扩容" in c["name"]][0]
        self.assertGreater(o3["loop"]["max_steps"], 4)
        self.assertGreater(o3["meta"]["budget_cost"], 50)

    def test_sessions_empty_returns_base(self):
        _, spec = ah.check_harness(_spec())
        cands = ah.evolve_from_sessions(spec, [])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["name"], spec["name"])

    def test_sessions_steady_returns_base(self):
        _, spec = ah.check_harness(_spec())
        cands = ah.evolve_from_sessions(spec, [
            self._report(0.9), self._report(0.85)])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["name"], spec["name"])

    # -- regression_detection（误伤的 learner 侧早期信号） -------------------
    def test_regression_finds_drop(self):
        regs = ah.regression_detection(
            self._state([0.2, 0.3, 0.4, 0.8, 0.9]))  # 最近 3 次回退，早期达标
        self.assertEqual(len(regs), 1)
        r = regs[0]
        self.assertEqual(r["name"], "混合记忆架构")
        self.assertEqual(r["before_avg"], 0.85)
        self.assertEqual(r["after_avg"], 0.3)
        self.assertEqual(r["drop"], 0.55)

    def test_regression_ignores_review_channel(self):
        # 复习低分是遗忘证据（gain_weak 管道处置），不是教学回归——
        # 混入会拿复习样本误触发 O2 裁 budget_ok 守卫
        name = "混合记忆架构"
        from expert_anything.core import learner as _learner
        key = _learner.normalize(name)
        review_low = {"concept": name, "key": key, "asset_id": "a1",
                      "score": 0.2, "answer": "x", "feedback": "f",
                      "at": "2026-08-18T00:00:00+00:00",
                      "meta": {"review": True}}
        regs = ah.regression_detection(
            self._state([0.3, 0.35, 0.8, 0.9], extra_histories=[review_low]))
        self.assertEqual(
            regs, [],
            "review-channel low scores must not fire teaching regression")

    def test_regression_fires_on_teaching_channel_only(self):
        # 教学通道内部的真实回退仍要触发（复习记录不遮蔽真实信号）
        regs = ah.regression_detection(
            self._state([0.2, 0.3, 0.4, 0.8, 0.9]))
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0]["drop"], 0.55)

    def test_regression_ignores_steady_failures(self):
        # 一直不达标 → 是 stuck 不是 regression（两信号互补）
        regs = ah.regression_detection(
            self._state([0.2, 0.3, 0.4, 0.3, 0.2]))
        self.assertEqual(regs, [])

    def test_regression_ignores_recent_pass(self):
        regs = ah.regression_detection(
            self._state([0.7, 0.8, 0.2, 0.1, 0.3]))
        self.assertEqual(regs, [])

    def test_regression_respects_harness_threshold(self):
        regs = ah.regression_detection(
            self._state([0.5, 0.6, 0.7, 0.85, 0.9]), threshold=0.75)
        # 0.5/0.6/0.7 低于 0.75 且早期 0.85/0.9 达标 → 回归（默认 0.6 则不算）
        self.assertEqual(len(regs), 1)

    # -- evolve_for_regression（O2 的真实信号源） ----------------------------
    def test_regression_evolves_to_trim_budget_guard(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_for_regression(
            spec, self._state([0.2, 0.3, 0.4, 0.8, 0.9]))
        self.assertTrue(out["evolved"])
        self.assertEqual(out["source"], "regression")
        self.assertEqual(out["trigger"]["before_avg"], 0.85)
        names = [c["name"] for c in out["candidates"]]
        self.assertTrue(any("裁成本守卫" in n for n in names), names)
        for c in out["candidates"]:
            v, _ = ah.check_harness(c)
            self.assertTrue(v)

    def test_regression_no_budget_guard_steady(self):
        _, spec = ah.check_harness(_spec(policy={
            "teach_styles": ["例子"], "guard_ids": ["no_definition_copy"],
            "retry": 0, "fallback": "deterministic"}))
        out = ah.evolve_for_regression(
            spec, self._state([0.2, 0.3, 0.4, 0.8, 0.9]))
        self.assertFalse(out["evolved"])       # 无预算守卫可裁 → 无抓手
        self.assertEqual(out["source"], "steady")
        self.assertIsNotNone(out["trigger"])   # 回归事实仍在（供 UI 展示）

    # -- 会话报告持久化（_sessions append-only + 有界） ----------------------
    def _tmp(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        return str(self._dir.name) + "/harness_state.json"

    def test_persist_appends_and_bounds(self):
        path = self._tmp()
        r1 = ah.persist_session_report(path, self._report(0.8))
        r2 = ah.persist_session_report(path, self._report(0.4), max_keep=1)
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)           # 有界：只留最近 1 条
        self.assertEqual(r2[0]["value"], 0.4)
        self.assertEqual(ah.load_session_reports(path), r2)

    def test_persist_normalizes_fields(self):
        path = self._tmp()
        reps = ah.persist_session_report(path, {
            "value": "0.85", "threshold": None,
            "guard_triggers": {"budget_ok": "3"},
            "steps_used": 99, "max_steps": None,
            "scores": [0.9, "x", 0.8], "cost": -5,
        })
        r = reps[0]
        self.assertEqual(r["value"], 0.85)
        self.assertEqual(r["threshold"], 0.6)       # 缺省
        self.assertEqual(r["guard_triggers"], {"budget_ok": 3})
        self.assertEqual(r["steps_used"], 20)       # 钳到 MAX_STEPS*2
        self.assertEqual(r["max_steps"], 4)         # 缺省
        self.assertEqual(r["scores"], [0.9, 0.8])   # 非法项剔除
        self.assertEqual(r["cost"], 0)              # 负值钳 0
        self.assertTrue(r["ts"])                    # 自动补时间戳

    def test_save_state_preserves_sessions(self):
        path = self._tmp()
        ah.persist_session_report(path, self._report(0.8))
        ah.persist_session_report(path, self._report(0.4))
        _, spec = ah.check_harness(_spec())
        ah.save_harness_state(path, {"a1": spec})
        sess = ah.load_session_reports(path)
        self.assertEqual(len(sess), 2)             # 全量覆盖不冲掉信号底座
        self.assertEqual(sess[0]["value"], 0.8)
        self.assertEqual(ah.load_harness_state(path)["a1"]["name"], spec["name"])


class TestJointEvolution(unittest.TestCase):
    """联合演化：三层信号融合成一个决策（去重 / 仲裁 / 诊断）。

    detect_signals 统一信号检测 → _o2_target_fusion（回归假设 × 会话实际
    触发，真实数据优先）→ evolve_joint 按因果强度排序候选（O2>O1>O3），
    reason 触发家族去重保序（stuck → regression → sessions），诊断行可解释。
    """

    @staticmethod
    def _state(scores, name="混合记忆架构", extra_histories=None):
        # history 为 newest-first（与 record_evaluation 的 insert(0) 一致）
        from expert_anything.core import learner as _learner
        key = _learner.normalize(name)
        rows = [{"concept": name, "key": key, "asset_id": "a1", "score": s,
                 "answer": "x", "feedback": "f",
                 "at": f"2026-08-18T00:00:{i:02d}+00:00"}
                for i, s in enumerate(scores)]
        if extra_histories:
            rows += extra_histories
        return {"concepts": {}, "history": rows}

    @staticmethod
    def _report(value, *, trig=None, steps=2, max_steps=4, cost=10,
                threshold=0.6):
        return {"value": value, "threshold": threshold, "steps_used": steps,
                "max_steps": max_steps, "guard_triggers": trig or {},
                "cost": cost, "scores": [value]}

    # -- evolve_joint 主路径 -------------------------------------------------
    def test_stuck_only_o1(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_joint(spec, self._state([0.2, 0.3, 0.4]))
        self.assertTrue(out["evolved"])
        self.assertEqual(out["source"], "joint")
        self.assertEqual(out["reason"], "stuck")
        f = out["focused"]
        self.assertTrue(f["stuck"])
        self.assertFalse(f["regression"])          # 无早先达标 → 纯 stuck
        self.assertEqual([c["name"] for c in out["candidates"]],
                         ["测试 Harness·换风格+图示"])
        diag = "\n".join(out["diagnosis"])
        self.assertIn("卡壳：", diag)
        self.assertIn("连续 3 次不达标", diag)
        for c in out["candidates"]:
            v, _ = ah.check_harness(c)
            self.assertTrue(v)                     # 演化候选仍须过准入

    def test_stuck_plus_regression_o2_first(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_joint(spec, self._state([0.2, 0.3, 0.4, 0.8, 0.9]))
        self.assertEqual(out["reason"], "stuck+regression")
        f = out["focused"]
        self.assertTrue(f["stuck"] and f["regression"])
        self.assertEqual(f["drop"], 0.55)
        names = [c["name"] for c in out["candidates"]]
        # 因果强度：回归驱动的 O2 优先于 O1 换风格
        self.assertEqual(names[0], "测试 Harness·裁成本守卫")
        self.assertEqual(names[1], "测试 Harness·换风格+图示")
        diag = "\n".join(out["diagnosis"])
        self.assertIn("回归：混合记忆架构 从 0.85 回退到 0.30", diag)
        self.assertIn("回归假设：budget_ok", diag)  # 会话数据缺失 → 弱置信假设
        self.assertIn("卡壳：", diag)

    def test_sessions_only_all_three_ops(self):
        _, spec = ah.check_harness(_spec())
        reps = [self._report(0.4, trig={"budget_ok": 2}, steps=4, max_steps=4),
                self._report(0.5, trig={"budget_ok": 1}, steps=4, max_steps=4),
                self._report(0.4, trig={"budget_ok": 2})]
        out = ah.evolve_joint(spec, {"concepts": {}, "history": []},
                              reports=reps)
        self.assertEqual(out["reason"], "sessions")
        self.assertIsNone(out["focused"])          # 纯会话信号，无 learner 焦点
        names = [c["name"] for c in out["candidates"]]
        # O1（avg 0.43<0.6） + O2（budget_ok 累计 5） + O3（满额 2/3）
        self.assertEqual(names, ["测试 Harness·裁成本守卫",
                                 "测试 Harness·换风格+图示",
                                 "测试 Harness·扩容"])
        diag = "\n".join(out["diagnosis"])
        self.assertIn("会话统计：budget_ok 触发累计最多", diag)
        self.assertIn("步数满额率 0.67 ≥ 0.5", diag)

    def test_regression_confirmed_by_sessions(self):
        _, spec = ah.check_harness(_spec())
        state = self._state([0.2, 0.3, 0.4, 0.8, 0.9])
        reps = [self._report(0.8, trig={"budget_ok": 3}),
                self._report(0.85, trig={"budget_ok": 3})]
        out = ah.evolve_joint(spec, state, reports=reps)
        # 回归假设与真实触发同指 → 双证据，三家族都进 reason
        self.assertEqual(out["reason"], "stuck+regression+sessions")
        diag = "\n".join(out["diagnosis"])
        self.assertIn("融合：回归假设与会话实际触发同指 budget_ok", diag)
        self.assertTrue(diag.startswith("回归："))  # 回归事实行排最前（可解释）
        self.assertEqual(out["candidates"][0]["name"], "测试 Harness·裁成本守卫")
        self.assertNotIn("budget_ok",
                         out["candidates"][0]["policy"]["guard_ids"])

    def test_regression_refuted_by_sessions(self):
        _, spec = ah.check_harness(_spec())
        state = self._state([0.2, 0.3, 0.4, 0.8, 0.9])
        reps = [self._report(0.8, trig={"no_definition_copy": 4}),
                self._report(0.85, trig={"no_definition_copy": 3}),
                self._report(0.9, trig={"budget_ok": 1})]
        out = ah.evolve_joint(spec, state, reports=reps)
        # 真实数据修正假设 → 回归家族不进 reason，留在 diagnosis（可追溯）
        self.assertEqual(out["reason"], "stuck+sessions")
        diag = "\n".join(out["diagnosis"])
        self.assertIn("仲裁：回归假设指向 budget_ok，但会话实际触发最多的是 "
                      "no_definition_copy", diag)
        first = out["candidates"][0]
        self.assertEqual(first["name"], "测试 Harness·裁守卫no_definition_copy")
        self.assertNotIn("no_definition_copy", first["policy"]["guard_ids"])
        self.assertIn("budget_ok", first["policy"]["guard_ids"])  # 假设守卫未动

    def test_steady_no_candidates(self):
        _, spec = ah.check_harness(_spec())
        out = ah.evolve_joint(spec, self._state([0.8, 0.9]),
                              reports=[self._report(0.9),
                                       self._report(0.85)])
        self.assertFalse(out["evolved"])
        self.assertEqual(out["source"], "steady")
        self.assertEqual(out["reason"], "")
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["diagnosis"], [])     # 不折腾，也无诊断噪音

    # -- 去重 --------------------------------------------------------------
    def test_o1_cross_source_dedup(self):
        _, spec = ah.check_harness(_spec())
        state = self._state([0.2, 0.3, 0.4])       # stuck
        reps = [self._report(0.4), self._report(0.5)]  # sessions avg 0.45<0.6
        out = ah.evolve_joint(spec, state, reports=reps)
        names = [c["name"] for c in out["candidates"]]
        # 两信号同指 O1 → 只出一个换风格候选
        self.assertEqual(sum("换风格" in n for n in names), 1)
        self.assertEqual(out["reason"], "stuck+sessions")  # 家族都记录
        diag = "\n".join(out["diagnosis"])
        self.assertIn("卡壳：", diag)
        self.assertIn("会话统计：", diag)

    def test_candidates_order_and_limit(self):
        _, spec = ah.check_harness(_spec())
        reps = [self._report(0.4, trig={"budget_ok": 2}, steps=4, max_steps=4),
                self._report(0.5, trig={"budget_ok": 1}, steps=4, max_steps=4),
                self._report(0.4, trig={"budget_ok": 2})]
        out = ah.evolve_joint(spec, {"concepts": {}, "history": []},
                              reports=reps, candidates_limit=2)
        self.assertEqual(len(out["candidates"]), 2)  # 上限生效（O2+O1 在前）

    # -- detect_signals 焦点优先级 ------------------------------------------
    def test_detect_signals_pure_stuck(self):
        _, spec = ah.check_harness(_spec())
        sig = ah.detect_signals(spec, self._state([0.2, 0.3, 0.4]))
        f = sig["focused"]
        self.assertTrue(f["stuck"])
        self.assertFalse(f["regression"])
        self.assertEqual(sig["sessions"], None)

    def test_detect_signals_intersection_beats_pure_stuck(self):
        from expert_anything.core import learner as _learner
        _, spec = ah.check_harness(_spec())
        def row(name, s, i):
            return {"concept": name, "key": _learner.normalize(name),
                    "asset_id": "a1", "score": s, "answer": "x",
                    "feedback": "f", "at": f"2026-08-18T00:00:{i:02d}+00:00"}
        hist = ([row("A", s, i) for i, s in enumerate([0.2, 0.3, 0.4])]   # stuck
                + [row("B", s, i + 5)
                   for i, s in enumerate([0.2, 0.3, 0.4, 0.8, 0.9])])   # 交集
        sig = ah.detect_signals(spec, {"concepts": {}, "history": hist})
        f = sig["focused"]
        self.assertEqual(f["name"], "B")            # 交集（回归因果更强）胜出
        self.assertTrue(f["stuck"] and f["regression"])

    def test_detect_signals_concept_name_overrides(self):
        _, spec = ah.check_harness(_spec())
        extra = [{"concept": "另一个概念", "key": "另一个概念", "asset_id": "a1",
                  "score": 0.9, "answer": "x", "feedback": "f",
                  "at": "2026-08-18T00:00:30+00:00"}]
        state = self._state([0.2, 0.3, 0.4, 0.8, 0.9], extra_histories=extra)
        out = ah.evolve_joint(spec, state, concept_name="另一个概念")
        self.assertIsNone(out["focused"])           # 指定概念无异常
        self.assertFalse(out["evolved"])
        out2 = ah.evolve_joint(spec, state, concept_name="混合记忆架构")
        self.assertEqual(out2["reason"], "stuck+regression")
        self.assertEqual(out2["focused"]["name"], "混合记忆架构")

    # -- _o2_target_fusion 仲裁规则（单元级） --------------------------------
    def test_o2_target_fusion_rules(self):
        spec = _spec()                              # guard_ids 含 budget_ok
        # 会话实际触发存在 → 以实际为准
        sig = {"regression": [], "sessions":
               {"guard_triggers": {"no_definition_copy": 5, "budget_ok": 1}}}
        guard, sources = ah._o2_target_fusion(sig, spec)
        self.assertEqual(guard, "no_definition_copy")
        self.assertEqual(sources, ["sessions"])
        # 与回归假设同指 → 双证据
        sig2 = {"regression": [{"key": "x"}], "sessions":
                {"guard_triggers": {"budget_ok": 5}}}
        guard, sources = ah._o2_target_fusion(sig2, spec)
        self.assertEqual(guard, "budget_ok")
        self.assertEqual(set(sources), {"sessions", "regression"})
        # 会话数据缺失 → 保留回归假设（弱置信）
        sig3 = {"regression": [{"key": "x"}], "sessions": None}
        guard, sources = ah._o2_target_fusion(sig3, spec)
        self.assertEqual(guard, "budget_ok")
        self.assertEqual(sources, ["regression"])
        # 两者皆无 → 无抓手，不硬造候选
        guard, sources = ah._o2_target_fusion(
            {"regression": [], "sessions": None}, spec)
        self.assertIsNone(guard)
        self.assertEqual(sources, [])
        # 纪律底线：只剩一个守卫不裁
        spec1 = _spec(policy={"teach_styles": ["例子"],
                              "guard_ids": ["budget_ok"],
                              "retry": 0, "fallback": "deterministic"})
        guard, sources = ah._o2_target_fusion(sig2, spec1)
        self.assertIsNone(guard)


if __name__ == "__main__":
    unittest.main()
