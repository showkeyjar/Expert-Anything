"""AutoHarness — 教学 Harness 的生成系统（meta-harness）。

背景（2026-08 快照）
==================
Harness 工具爆发：DeepSeek Harness（"一切皆插件"、MIT、一周 8 万 star）、
Claude Code / Codex（工程团队建基础设施而非写业务代码）、lm-evaluation-harness
（评测事实标准）、METR/Inspect（agent 能力评估 harness）、SWE-agent（ACI 设计）。
行业共识：**Agent = Model + Harness**。Harness-Bench 实测同一模型换 harness，
能力分可差 **24 点** —— harness 设计本身是能力的一等变量。

用户直觉（本模块的出发点）：既然 harness 设计如此关键、又如此昂贵（prompt
engineering → ACI engineering → harness engineering），那么 harness 的发展
也必将逐步自动化 —— 由 LLM 设计 harness、由代码准入、由差分评估演化。

本模块把 decoder.py 已验证的模式（开放推理 + 确定性外壳）提升一个抽象层级，
作用于 harness 自身。铁律与 decoder 同源：

  * LLM 只产出 **HarnessSpec**（类型化 JSON 规范），绝不直接产出执行逻辑；
  * `check_harness()` 代码准入（结构合法 + 工具/守卫引用存在 + 预算有界 + 沙箱安全）；
  * `build_harness()` 确定性装配（能力接缝：工具槽位 = 接口，provider = 实现，
    一次替换处处生效，对应 dsh 的 Capability Seam）；
  * `run()` 产出 **append-only 轨迹**（模型可见即已记录 → 回放/审计/教师模型复用）；
  * `evolve()` 的候选必须过准入；采纳与否由 `compare_harnesses()` **差分评估**
    （OFF/ON 双配置取差分 + 噪声底噪）决定，绝对分数不做采纳依据。

本模块只依赖标准库 + core（无 UI、无网络），无 LLM key 时全链路确定性可跑。
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from expert_anything.core.checks import CheckResult
from expert_anything.core import checks as _checks
from expert_anything.core import decoder as _decoder

# --- harness 类型域 ---------------------------------------------------------

# 工具槽位（能力接缝的 Service Definition）：每种工具一个稳定 id
TOOL_SLOTS = ("teach", "scene", "quiz", "practice", "review")
# 单步成本（token/算力预算的粗粒度代理，用于 budget_ok 守卫）
TOOL_COST = {"teach": 5, "scene": 4, "quiz": 2, "practice": 3, "review": 3}
# 内容规模折算：每 COST_CHARS_PER_UNIT 个字符（≈token）计 1 个成本单位。
# 中英文混合教学文本 1 字符≈1 token；短内容（测试/小请求）增量≈0，
# 长讲解/长输出显著抬升成本 —— budget_ok 守卫据此感知"昂贵的调用"。
COST_CHARS_PER_UNIT = 100


def _text_len(v) -> int:
    """递归统计 dict/list/str 中的字符数（近似 token 数，仅用于成本估算）。"""
    if isinstance(v, str):
        return len(v)
    if isinstance(v, dict):
        return sum(_text_len(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return sum(_text_len(x) for x in v)
    return 0


def estimate_cost(tool: str, args: dict, result: dict | None = None) -> int:
    """估算一次工具调用的成本（成本单位，用于 budget_ok 守卫）。

    成本 = 基础固定开销（TOOL_COST：协议/模板的最小成本）
         + 内容规模成本（输入 args 与输出 result 的字符数折算 token，
           每 COST_CHARS_PER_UNIT 字符计 1 单位，向上取整到单位）。

    相比固定 TOOL_COST：长讲解/长输出会显著抬升成本，预算耗尽更早触发；
    短内容（最小请求、测试替身）增量≈0，保持既有行为。确定性、无网络、
    与 LLM key 无关 —— 成本模型本身是纯函数，可 headless 测试。
    """
    base = TOOL_COST.get(tool, 1)
    content = _text_len(args) + _text_len(result if result else {})
    return base + content // COST_CHARS_PER_UNIT
# 哪些工具需要在沙箱中执行（safe_only 守卫据此 fail-closed）
TOOL_SANDBOX = {"teach": False, "scene": False, "quiz": False,
                "practice": True, "review": False}
# 守卫 id（check_harness 只放行注册过的守卫）
GUARD_IDS = ("no_definition_copy", "evidence_grounded", "budget_ok", "safe_only")
# 守卫分类（O2 误伤裁守卫的依据）：
#   safety  —— safe_only 安全铁律，永不裁（安全不是演化参数）；
#   quality —— no_definition_copy / evidence_grounded 来源约束（项目铁律），
#              裁掉会放宽来源约束，仅生成候选、由采纳环节显式确认；
#   cost    —— budget_ok 成本纪律，裁掉=不惜成本，"误伤"最可能的来源。
SAFE_GUARDS = frozenset({"safe_only"})
TRIMABLE_GUARDS = frozenset(g for g in GUARD_IDS if g not in SAFE_GUARDS)
# 运行模式 = 策略分层（dsh 四模式的最小对应：完整/快速/最小评测）
MODES = ("minimal", "fast", "full")
MODE_PRESETS = {
    "minimal": ["teach"],
    "fast": ["teach", "quiz"],
    "full": ["teach", "scene", "quiz", "practice"],
}
# 评估指标
METRICS = ("learning_gain", "task_success")
# 讲解风格轮换环（对应 tutor 的 style 参数）
STYLE_CYCLE = ("例子", "图示", "拆解步骤")
# 沙箱档位
SANDBOX_MODES = ("none", "local", "remote")

MAX_TOOLS = 6
MAX_STEPS = 10
MAX_RETRY = 2
MAX_BUDGET = 2000


# --- 小工具 ----------------------------------------------------------------

def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _clamp_float(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _next_style(cur: str) -> str:
    if cur in STYLE_CYCLE:
        return STYLE_CYCLE[(STYLE_CYCLE.index(cur) + 1) % len(STYLE_CYCLE)]
    return STYLE_CYCLE[0]


def _tolerant_json(text: str | None) -> dict:
    """容错 JSON 解析（同 decoder.tolerant_scene_json：容忍围栏/尾注）。"""
    return _decoder.tolerant_scene_json(text or "")


# --- HarnessSpec 准入 -------------------------------------------------------

def check_harness(spec: Any) -> tuple[CheckResult, dict | None]:
    """HarnessSpec 代码准入（与 check_scene 同构）。

    LLM 产出的规范必须通过此处才能被装配。返回 (verdict, normalized_spec)。
    规范化后：工具去重保序、style 有默认、retry/预算/步数被夹紧、
    未知引用一律拒绝 —— 规范性字段放行，结构性字段拒绝。
    """
    if not isinstance(spec, dict):
        return CheckResult(False, "harness_not_dict", "HarnessSpec 必须是 JSON 对象"), None

    name = _as_str(spec.get("name"))
    if not name:
        return CheckResult(False, "harness_no_name", "HarnessSpec 缺少 name"), None

    mode = _as_str(spec.get("mode"), "fast")
    if mode not in MODES:
        return CheckResult(False, "harness_bad_mode", f"mode 必须是 {MODES} 之一"), None

    raw_tools = spec.get("tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        return CheckResult(False, "harness_no_tools", "tools 必须是非空数组"), None
    tools: list[str] = []
    for t in raw_tools:
        t = _as_str(t)
        if t not in TOOL_SLOTS:
            return CheckResult(False, "harness_bad_tool", f"未知工具槽位：{t}"), None
        if t not in tools:
            tools.append(t)
    if len(tools) > MAX_TOOLS:
        return CheckResult(False, "harness_too_many_tools", f"tools 最多 {MAX_TOOLS} 个"), None

    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {}
    styles = [_as_str(s) for s in (policy.get("teach_styles") or []) if _as_str(s)]
    if not styles:
        styles = ["例子"]
    guards: list[str] = []
    for g in (policy.get("guard_ids") or []):
        g = _as_str(g)
        if g and g not in GUARD_IDS:
            return CheckResult(False, "harness_bad_guard", f"未知守卫：{g}"), None
        if g and g not in guards:
            guards.append(g)
    retry = _clamp_int(policy.get("retry"), 0, MAX_RETRY, 1)
    fallback = _as_str(policy.get("fallback"), "deterministic")
    if fallback != "deterministic":
        return CheckResult(False, "harness_bad_fallback",
                           "fallback 目前仅支持 deterministic"), None

    loop = spec.get("loop") if isinstance(spec.get("loop"), dict) else {}
    max_steps = _clamp_int(loop.get("max_steps"), 1, MAX_STEPS, 4)

    evaluation = spec.get("evaluation") if isinstance(spec.get("evaluation"), dict) else {}
    metric = _as_str(evaluation.get("metric"), "learning_gain")
    if metric not in METRICS:
        return CheckResult(False, "harness_bad_metric", f"未知评估指标：{metric}"), None
    threshold = _clamp_float(evaluation.get("threshold"), 0.0, 1.0, 0.6)

    meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    budget_cost = _clamp_int(meta.get("budget_cost"), 0, MAX_BUDGET, 50)
    sandbox = _as_str(meta.get("sandbox"), "local")
    if sandbox not in SANDBOX_MODES:
        return CheckResult(False, "harness_bad_sandbox",
                           f"sandbox 必须是 {SANDBOX_MODES} 之一"), None

    norm = {
        "name": name[:40],
        "mode": mode,
        "tools": tools,
        "policy": {"teach_styles": styles[:3], "guard_ids": guards,
                   "retry": retry, "fallback": fallback},
        "loop": {"max_steps": max_steps},
        "evaluation": {"metric": metric, "threshold": round(threshold, 2)},
        "meta": {"budget_cost": budget_cost, "sandbox": sandbox,
                 "lang": _as_str(meta.get("lang"), "zh-CN"),
                 "note": _as_str(meta.get("note"))[:120]},
    }
    return CheckResult(True), norm


def fallback_harness(concept_name: str = "") -> dict:
    """确定性兜底 harness：无 LLM 也能跑通的最小教学 harness，必过准入。"""
    return {
        "name": f"默认教学 Harness·{concept_name[:12]}" if concept_name else "默认教学 Harness",
        "mode": "fast",
        "tools": ["teach", "quiz"],
        "policy": {"teach_styles": ["例子"],
                   "guard_ids": ["no_definition_copy", "budget_ok"],
                   "retry": 1, "fallback": "deterministic"},
        "loop": {"max_steps": 4},
        "evaluation": {"metric": "learning_gain", "threshold": 0.6},
        "meta": {"budget_cost": 50, "sandbox": "local", "lang": "zh-CN",
                 "note": "确定性兜底：无 LLM 的最小教学 harness"},
    }


# --- 确定性 provider（能力接缝的默认实现，可注入替换） ----------------------

def _sim_score(mastery: float, definition_len: int = 0) -> float:
    """仿真得分（原型占位）：学习者答对的概率随掌握度单调上升，
    并随概念定义丰富度微调 —— 定义充分的资产，确定性自测/实践的
    内容底座更好，基准分略高。

    definition_len 让「资产结构画像 → 迁移效果」产生合法的跨资产差异
    （定义覆盖率是 asset_profile 的特征之一）；生产接入后由真实答题/
    实践评估通道取代，此处仅保证 run→report 的指标回路在无 UI、无网络、
    无 LLM 时仍可确定性演示。
    """
    base = round(min(1.0, 0.45 + mastery), 2)
    if definition_len <= 0:
        return base
    bonus = round(min(0.2, definition_len / 300 * 0.2), 2)
    return round(min(1.0, base + bonus), 2)


def _prov_teach(tool: str, args: dict, ctx: dict) -> dict:
    """讲解槽位。有 llm 且 asset 时走 Tutor.teach（内置准入+降级），否则确定性 stub。"""
    concept = ctx["concept"]
    style = args.get("style", "例子")
    definition = (concept.definition or "").strip()
    if ctx["llm"] is not None and ctx["asset"] is not None and style:
        try:
            from expert_anything.core.tutor import Tutor
            lesson = Tutor(ctx["asset"], llm=ctx["llm"]).teach(concept, style=style)
            explanation = (lesson.get("explanation") or definition).strip()
            if explanation:
                return {"payload": lesson, "summary": f"[{style}] {explanation[:40]}…",
                        "score": None}
        except Exception:
            pass  # 确定性降级
    explanation = (f"{concept.name}：{definition[:36] or '（原文无显式定义）'}"
                   "——先从原文证据出发理解它的位置与作用（确定性讲解）。")
    payload = {
        "style": style,
        "explanation": explanation,
        "example": f"回到原文证据，用一句话说出「{concept.name[:12]}」在上下文里的角色。",
        "practice": f"用自己的话复述「{concept.name[:12]}」的定义，并指出它依赖或支撑了哪些相邻概念。",
    }
    return {"payload": payload, "summary": f"[{style}] {explanation[:40]}…", "score": None}


def _prov_scene(tool: str, args: dict, ctx: dict) -> dict:
    """图示解码槽位：优先领域专用场景，否则回退 decoder 通用场景（确定性渲染）。"""
    concept = ctx["concept"]
    asset = ctx["asset"]
    if asset is not None:
        spec = _decoder.scene_for_concept(asset, concept)
    else:
        v, spec = _decoder.check_scene({
            "title": f"「{concept.name}」的知识结构",
            "nodes": [
                {"id": "c0", "label": concept.name[:20], "kind": "current"},
                {"id": "c1", "label": "原文证据", "kind": "note"},
                {"id": "c2", "label": "相邻概念", "kind": "box"},
            ],
            "edges": [{"from": "c0", "to": "c1"}, {"from": "c0", "to": "c2"}],
            "steps": [
                {"caption": "定位概念", "show": ["c0"], "active": "c0"},
                {"caption": "联系证据与相邻概念", "show": ["c0", "c1", "c2"]},
            ],
        })
        if not v:
            spec = {"title": concept.name, "nodes": [], "edges": [],
                    "steps": [], "game": None}
    return {"payload": spec, "summary": f"图示：{_decoder.scene_summary(spec)}", "score": None}


def _prov_quiz(tool: str, args: dict, ctx: dict) -> dict:
    """快速自测槽位：基于定义的判断题（确定性出题）。"""
    concept = ctx["concept"]
    definition = (concept.definition or "该概念在原文中被定义。").strip()
    payload = {
        "type": "true_false",
        "question": f"判断正误：{definition[:36]}{'…' if len(definition) > 36 else ''}",
        "correct": True,
    }
    return {"payload": payload, "summary": "自测：判断题（基于定义）",
            "score": _sim_score(ctx["mastery"], len(definition))}


def _prov_practice(tool: str, args: dict, ctx: dict) -> dict:
    """实践任务槽位：构造/复现 + 反例（确定性生成）。"""
    concept = ctx["concept"]
    payload = {
        "task": (f"构造/复现：「{concept.name[:20]}」——用原文证据支撑你的表述，"
                 "并给出一个反例场景。"),
        "reference": "对照概念定义逐点核对自己的表述；找不到证据支撑的判断标为「待确认」。",
    }
    return {"payload": payload, "summary": "实践任务：构造 + 反例",
            "score": _sim_score(ctx["mastery"], len(concept.definition))}


def _prov_review(tool: str, args: dict, ctx: dict) -> dict:
    """到期复习槽位：vary=1 换角度重讲（间隔效应）。"""
    concept = ctx["concept"]
    definition = (concept.definition or "").strip()
    explanation = (f"换一个角度复习「{concept.name}」（{args.get('style', '例子')}）："
                   f"{definition[:30] or '回看证据'}……")
    payload = {"style": args.get("style", "例子"), "vary": 1, "explanation": explanation}
    return {"payload": payload, "summary": "到期复习（vary=1 换角度）",
            "score": _sim_score(ctx["mastery"], len(concept.definition))}


_DEFAULT_PROVIDERS: dict[str, Callable] = {
    "teach": _prov_teach, "scene": _prov_scene, "quiz": _prov_quiz,
    "practice": _prov_practice, "review": _prov_review,
}


# --- 守卫（gatekeeper：门禁是强制不是请求） ----------------------------------

def _guard_no_copy(tool: str, args: dict, result: dict | None, ctx: dict) -> tuple | None:
    """讲解不得只是抄写定义（checks.explanation_is_definition 的 harness 层镜像）。"""
    if tool not in ("teach", "review"):
        return None
    payload = (result or {}).get("payload") or {}
    explanation = str(payload.get("explanation") or "").strip()
    definition = (ctx["concept"].definition or "").strip()
    if definition and explanation == definition:
        return ("no_definition_copy", "讲解只是抄写了定义原文，未加入直觉性内容")
    return None


def _guard_grounded(tool: str, args: dict, result: dict | None, ctx: dict) -> tuple | None:
    """讲解/图示必须扣住本概念（复用 checks._name_hits，anti-template）。"""
    if tool not in ("teach", "review", "scene"):
        return None
    payload = (result or {}).get("payload") or {}
    if tool == "scene":
        text = str(payload.get("title") or "") + " " + " ".join(
            str(n.get("label") or "") for n in (payload.get("nodes") or []))
    else:
        text = str(payload.get("explanation") or "") + " " + str(payload.get("example") or "")
    if not _checks._name_hits(ctx["concept"].name, text):
        return ("evidence_grounded", "内容未提及本概念，疑似套用模板")
    return None


def _guard_safe(tool: str, args: dict, result: dict | None, ctx: dict) -> tuple | None:
    """ToolTrust gatekeeper 模式：需要沙箱的工具在 sandbox=none 时 fail-closed。

    不是二进制的 allow/deny，而是按工具语义分级：只拦真正要执行外部动作的工具。
    """
    if TOOL_SANDBOX.get(tool) and ctx["sandbox"] == "none":
        return ("safe_only", f"「{tool}」需要执行沙箱，当前 sandbox=none，拒绝放行")
    return None


_DEFAULT_GUARDS: dict[str, Callable] = {
    "no_definition_copy": _guard_no_copy,
    "evidence_grounded": _guard_grounded,
    "safe_only": _guard_safe,
    # budget_ok 由 run() 循环本身强制执行（步数/成本双上限），不在守卫表内重复实现；
    # 保留其 id 是为了让 spec 能显式声明预算纪律，触发时计入 guard_triggers。
}


# --- Harness 运行时 ----------------------------------------------------------

class Harness:
    """装配好的教学 harness：确定性执行外壳 + 可替换 provider（能力接缝）。

    provider 注入（capability seam）：任何工具槽位都可以用外部实现替换，
    替换一个 provider 即替换该能力，其余不动 —— 对应 dsh 的
    Service Definition / Provider / Consumer 三角色。
    """

    def __init__(self, spec: dict, asset=None, learner_state: dict | None = None,
                 llm=None, providers: dict | None = None, guards: dict | None = None):
        v, self.spec = check_harness(spec)
        if not v or self.spec is None:
            raise ValueError(f"无效 HarnessSpec：{v.reason}")
        self.asset = asset
        self.learner_state = learner_state or {}
        self.llm = llm
        self.providers = dict(_DEFAULT_PROVIDERS)
        if providers:
            self.providers.update(providers)
        self.guards = dict(_DEFAULT_GUARDS)
        if guards:
            self.guards.update(guards)

    # -- 执行 ---------------------------------------------------------------
    def run(self, task: dict) -> tuple[list[dict], dict]:
        """执行 harness 循环。

        task: {"concept": Concept, "goal": str, "due": bool(可选，review 是否到期)}

        返回 (trajectory, report)。trajectory 是 append-only 事件流 ——
        唯一事实源：模型可见的一切都在事件里（"Model-visible means logged"），
        回放、审计、教师模型都读它而非叙述文本。
        """
        concept = task["concept"]
        spec = self.spec
        steps_max = spec["loop"]["max_steps"]
        budget = spec["meta"]["budget_cost"]
        guards_on = spec["policy"]["guard_ids"]
        retry = spec["policy"]["retry"]
        styles = spec["policy"]["teach_styles"]
        has_budget_guard = "budget_ok" in guards_on

        ctx = {"concept": concept, "asset": self.asset,
               "learner_state": self.learner_state, "llm": self.llm,
               "mastery": self._mastery(concept),
               "sandbox": spec["meta"]["sandbox"], "lang": spec["meta"]["lang"],
               "task": task}

        trajectory: list[dict] = []
        guard_triggers: dict[str, int] = {}
        scores: list[float] = []
        blocked = 0
        cost = 0
        seq = 0
        queue = list(spec["tools"])
        i = 0
        while i < len(queue) and len(trajectory) < steps_max:
            tool = queue[i]
            if has_budget_guard and cost >= budget:
                trajectory.append(self._event(seq, tool, {}, False,
                                              "预算耗尽，停止新增步骤",
                                              blocked_by="budget_ok", cost=0))
                guard_triggers["budget_ok"] = guard_triggers.get("budget_ok", 0) + 1
                blocked += 1
                break
            if tool == "review" and not task.get("due", False):
                trajectory.append(self._event(seq, tool, {"vary": 1}, True,
                                              "复习未到期，跳过", skipped="not_due", cost=0))
                seq += 1
                i += 1
                continue

            args = self._args_for(tool, styles, concept)
            # pre 守卫（gatekeeper：预算/沙箱在调用前 fail-closed）
            veto = self._run_guards("pre", tool, args, None, guards_on, ctx)
            if veto:
                code, reason = veto
                trajectory.append(self._event(seq, tool, args, False,
                                              f"被守卫拦截：{reason}",
                                              blocked_by=code, cost=1))
                guard_triggers[code] = guard_triggers.get(code, 0) + 1
                blocked += 1
                cost += 1
                seq += 1
                i += 1
                continue

            cost_before = cost
            result = self._call(tool, args, concept)
            cost += estimate_cost(tool, args, result)
            # post 准入：内容类守卫 → 带原因轮换重试（有界）→ 显式确定性降级
            veto = self._run_guards("post", tool, args, result, guards_on, ctx)
            attempts = 0
            while veto and attempts < retry:
                args = self._rotate_args(tool, args, styles)
                result = self._call(tool, args, concept)
                cost += estimate_cost(tool, args, result)
                attempts += 1
                veto = self._run_guards("post", tool, args, result, guards_on, ctx)
            if veto:
                result = self._call(tool, args, concept, force_deterministic=True)
                blocked += 1
                guard_triggers[veto[0]] = guard_triggers.get(veto[0], 0) + 1

            score = result.get("score")
            if score is not None:
                scores.append(float(score))
            trajectory.append(self._event(
                seq, tool, args, True, result.get("summary", ""),
                score=score, blocked_by=veto[0] if veto else "",
                cost=cost - cost_before))
            seq += 1
            i += 1

        return trajectory, self._report(trajectory, scores, guard_triggers,
                                        blocked, cost, spec, concept)

    # -- 内部 ---------------------------------------------------------------
    def _mastery(self, concept) -> float:
        try:
            from expert_anything.core import learner as _learner
        except Exception:
            return 0.0
        key = _learner.normalize(concept.name)
        rec = (self.learner_state.get("concepts") or {}).get(key)
        return float(rec.get("mastery", 0.0)) if isinstance(rec, dict) else 0.0

    def _event(self, seq, tool, args, ok, summary, *, blocked_by="",
               skipped="", cost=0, score=None) -> dict:
        return {"seq": seq, "tool": tool, "args": dict(args), "ok": bool(ok),
                "summary": str(summary)[:120], "blocked_by": blocked_by,
                "skipped": skipped, "cost": cost,
                "score": None if score is None else round(float(score), 2)}

    def _args_for(self, tool: str, styles: list[str], concept) -> dict:
        if tool in ("teach", "review"):
            return {"style": styles[0], "concept": concept.name}
        if tool == "practice":
            return {"concept": concept.name}
        return {}

    def _rotate_args(self, tool: str, args: dict, styles: list[str]) -> dict:
        """卡壳轮换：讲解/复习换下一个风格（对应现有 stuck 闭环的样式轮换）。"""
        out = dict(args)
        if tool in ("teach", "review"):
            cur = args.get("style", styles[0] if styles else "例子")
            nxt = _next_style(cur)
            out["style"] = nxt
        return out

    def _call(self, tool: str, args: dict, concept, force_deterministic: bool = False) -> dict:
        provider = (_DEFAULT_PROVIDERS.get(tool) if force_deterministic
                    else self.providers.get(tool))
        if provider is None:
            return {"payload": {}, "summary": f"无可用 provider：{tool}", "score": None}
        try:
            res = provider(tool, args, {
                "concept": concept, "asset": self.asset,
                "learner_state": self.learner_state, "llm": None if force_deterministic else self.llm,
                "mastery": self._mastery(concept),
                "sandbox": self.spec["meta"]["sandbox"], "lang": self.spec["meta"]["lang"],
            })
            return res if isinstance(res, dict) else {}
        except Exception as exc:  # provider 异常也必须落进轨迹，不允许静默
            return {"payload": {}, "summary": f"provider 异常：{exc}", "score": None}

    def _run_guards(self, phase: str, tool: str, args: dict, result: dict | None,
                    guard_ids: list[str], ctx: dict) -> tuple | None:
        for gid in guard_ids:
            if gid == "budget_ok":
                continue  # 由 run() 循环强制执行
            fn = self.guards.get(gid)
            if fn is None:
                continue
            try:
                veto = fn(tool, args, result, ctx)
            except Exception:
                veto = (gid, "守卫执行异常，fail-closed 拦截")
            if veto:
                return tuple(veto)
        return None

    def _report(self, trajectory, scores, guard_triggers, blocked, cost,
                spec, concept) -> dict:
        metric = spec["evaluation"]["metric"]
        threshold = spec["evaluation"]["threshold"]
        ok_steps = [e for e in trajectory if e["ok"] and not e.get("skipped")]
        task_success = 1.0 if (not blocked and ok_steps) else 0.0
        learning_gain = round(sum(scores) / len(scores), 2) if scores else 0.0
        value = learning_gain if metric == "learning_gain" else task_success
        return {
            "spec_name": spec["name"], "concept": concept.name,
            "metric": metric, "threshold": threshold, "value": round(value, 2),
            "learning_gain": learning_gain, "task_success": task_success,
            "steps_used": len(trajectory), "scores": scores,
            "guard_triggers": dict(guard_triggers), "blocked": blocked,
            "cost": cost, "trajectory_len": len(trajectory),
        }


def build_harness(spec: dict, asset=None, learner_state: dict | None = None,
                  llm=None, providers: dict | None = None, guards: dict | None = None) -> Harness:
    """确定性装配入口：非法 spec 直接抛错（fail-fast），合法 spec 才可运行。"""
    return Harness(spec, asset=asset, learner_state=learner_state,
                   llm=llm, providers=providers, guards=guards)


# --- 演化（"auto" 所在） -----------------------------------------------------

def evolve(spec: dict, report: dict, candidates_limit: int = 3) -> list[dict]:
    """确定性演化算子：从一次会话报告生成下一代 harness 候选。

    每个候选必须再过 check_harness —— 演化也不允许绕过准入。
    O1 卡壳：value < threshold → 换讲解风格 + 补图示（现有 stuck 闭环的泛化）；
    O2 误伤：裁掉触发最多的**可裁**守卫（SAFE_GUARDS 安全铁律永不裁）；
    O3 吃紧：步数用满 → 扩容（预算/步数双上限）。

    单算子提取为 ``_candidate_o1/_candidate_o2/_candidate_o3``，
    与 ``evolve_from_sessions``（多会话统计信号）共用同一套演化逻辑。
    """
    base = copy.deepcopy(spec)
    cands: list[dict] = []
    if report.get("value", 1.0) < float(spec["evaluation"].get("threshold", 0.6)):
        c = _candidate_o1(base, spec)
        if c is not None:
            cands.append(c)
    if report.get("guard_triggers"):
        # 只统计可裁守卫：safe_only 触发再多也不裁（安全铁律不是演化参数）
        trig = {k: v for k, v in report["guard_triggers"].items()
                if k in TRIMABLE_GUARDS}
        if trig:
            worst = max(trig, key=lambda k: trig[k])
            if worst in base["policy"]["guard_ids"] and len(base["policy"]["guard_ids"]) > 1:
                c = _candidate_o2(base, worst)
                if c is not None:
                    cands.append(c)
    if report.get("steps_used", 0) >= int(spec["loop"].get("max_steps", 4)):
        c = _candidate_o3(base, spec)
        if c is not None:
            cands.append(c)
    if not cands:
        cands.append(copy.deepcopy(base))
    return _admit_candidates(cands, candidates_limit)


def _candidate_o1(base: dict, spec: dict) -> dict | None:
    """O1 换风格：讲解换下一个风格 + 补 scene 工具（图示教学）。"""
    c = copy.deepcopy(base)
    cur = (c["policy"]["teach_styles"] or ["例子"])[0]
    nxt = _next_style(cur)
    c["policy"]["teach_styles"] = [nxt] + [s for s in c["policy"]["teach_styles"] if s != nxt]
    if "scene" not in c["tools"]:
        c["tools"].append("scene")
    c["name"] = f"{spec['name']}·换风格+图示"
    return c


def _candidate_o2(base: dict, worst_guard: str) -> dict | None:
    """O2 裁守卫：从守卫列表移除触发最多的守卫（调用方保证其可裁）。"""
    if worst_guard not in base["policy"]["guard_ids"]:
        return None
    if len(base["policy"]["guard_ids"]) <= 1:
        return None  # 最后一个守卫不裁（留一条纪律底线）
    c = copy.deepcopy(base)
    c["policy"]["guard_ids"] = [g for g in c["policy"]["guard_ids"] if g != worst_guard]
    tag = "裁成本守卫" if worst_guard == "budget_ok" else f"裁守卫{worst_guard}"
    c["name"] = f"{c['name']}·{tag}"
    return c


def _candidate_o3(base: dict, spec: dict) -> dict | None:
    """O3 扩容：步数/预算双上限放宽（差一点就够 → 给更多空间）。"""
    c = copy.deepcopy(base)
    c["loop"]["max_steps"] = min(MAX_STEPS, c["loop"]["max_steps"] + 3)
    c["meta"]["budget_cost"] = min(MAX_BUDGET, c["meta"]["budget_cost"] + 30)
    c["name"] = f"{spec['name']}·扩容"
    return c


def _admit_candidates(cands: list[dict], limit: int) -> list[dict]:
    """候选准入：演化也不允许绕过 check_harness。"""
    out: list[dict] = []
    for c in cands[:limit]:
        v, norm = check_harness(c)
        if v and norm is not None:
            out.append(norm)
    return out


def aggregate_reports(reports: list[dict]) -> dict:
    """跨会话汇总真实运行报告 → 演化信号（O2/O3 的正统信号源）。

    单次会话的 ``report``（Harness.run 产出）只有单点事实；演化需要一段
    时间的统计：达标率、守卫触发累计、步数满额率。确定性纯函数。

    返回：{n, pass_rate, avg_value, guard_triggers, steps_exhausted_rate,
           avg_cost}。空输入全部取中性值（n=0，不触发任何算子）。
    """
    n = len(reports)
    if n == 0:
        return {"n": 0, "pass_rate": 0.0, "avg_value": 0.0,
                "guard_triggers": {}, "steps_exhausted_rate": 0.0,
                "avg_cost": 0.0}
    passed = 0
    values: list[float] = []
    costs: list[float] = []
    trig: dict[str, int] = {}
    exhausted = 0
    for r in reports:
        try:
            val = float(r.get("value", 0.0))
        except (TypeError, ValueError):
            val = 0.0
        try:
            thr = float(r.get("threshold", 0.6))
        except (TypeError, ValueError):
            thr = 0.6
        values.append(val)
        passed += 1 if val >= thr else 0
        try:
            costs.append(float(r.get("cost", 0)))
        except (TypeError, ValueError):
            costs.append(0.0)
        gt = r.get("guard_triggers")
        if isinstance(gt, dict):
            for g, c in gt.items():
                try:
                    trig[g] = trig.get(g, 0) + int(c)
                except (TypeError, ValueError):
                    continue
        try:
            steps = float(r.get("steps_used", 0))
            max_steps = float(r.get("max_steps", 4))
        except (TypeError, ValueError):
            steps, max_steps = 0.0, 4.0
        if max_steps > 0 and steps >= max_steps:
            exhausted += 1
    return {
        "n": n,
        "pass_rate": round(passed / n, 2),
        "avg_value": round(sum(values) / n, 2),
        "guard_triggers": trig,
        "steps_exhausted_rate": round(exhausted / n, 2),
        "avg_cost": round(sum(costs) / n, 2),
    }


def evolve_from_sessions(spec: dict, reports: list[dict],
                         candidates_limit: int = 3) -> list[dict]:
    """从多份真实会话报告批量演化 —— O2/O3 的完整信号源。

    与 ``evolve`` 的差异：evolve 吃调用方手工构造的单会话启发式字段
    （guard_triggers / steps_used 常被写死 0 而空转）；本函数先
    ``aggregate_reports`` 跨会话聚合统计信号，再驱动三个算子：

      O1 卡壳   ：avg_value < threshold 或 pass_rate < 0.5 → 换风格+补 scene；
      O2 误伤   ：可裁守卫跨会话触发累计 → 裁掉触发最多者（safe_only 永不裁）；
      O3 吃紧   ：steps_exhausted_rate >= 0.5 → 步数/预算双扩容。

    候选必须再过 check_harness（演化也不允许绕过准入）。空报告输入
    （n=0）不触发任何算子，退回原 spec。
    """
    agg = aggregate_reports(reports)
    if agg["n"] == 0:
        ok, norm = check_harness(spec)
        return [norm] if (ok and norm is not None) else [copy.deepcopy(spec)]
    base = copy.deepcopy(spec)
    cands: list[dict] = []
    thr = float(spec["evaluation"].get("threshold", 0.6))
    if agg["avg_value"] < thr or agg["pass_rate"] < 0.5:
        c = _candidate_o1(base, spec)
        if c is not None:
            cands.append(c)
    if agg["guard_triggers"]:
        trig = {k: v for k, v in agg["guard_triggers"].items()
                if k in TRIMABLE_GUARDS}
        if trig:
            worst = max(trig, key=lambda k: trig[k])
            if worst in base["policy"]["guard_ids"] and len(base["policy"]["guard_ids"]) > 1:
                c = _candidate_o2(base, worst)
                if c is not None:
                    cands.append(c)
    if agg["steps_exhausted_rate"] >= 0.5:
        c = _candidate_o3(base, spec)
        if c is not None:
            cands.append(c)
    if not cands:
        cands.append(copy.deepcopy(base))
    return _admit_candidates(cands, candidates_limit)


def evolve_for_stuck(spec: dict, learner_state: dict,
                     concept_name: str | None = None,
                     attempts: int = 3,
                     threshold: float | None = None,
                     candidates_limit: int = 3) -> dict:
    """卡壳信号自动驱动 harness 演化 —— stuck 闭环与 evolve 的桥。

    学习轨迹（record_evaluation 写出的 history）是唯一事实源：若某概念
    连续 ``attempts`` 次评估均未达标（learner.stuck_concepts 判定），
    说明当前 harness 的策略已经失败，自动触发 evolve —— 无需调用方
    手动构造报告。这就是 "harness 自动化的自动化"：现有 stuck 闭环
    （Tutor.teach 换风格 + incorporate_stuck_signal 记教师模型）只轮换
    讲解风格本身，本函数让 *harness 结构*（补 scene / 后续 O2/O3 算子）
    也随卡壳信号演化。

    阈值语义与 stuck_concepts 对齐：显式 ``threshold`` 优先，其次
    spec.evaluation.threshold（harness 自己的达标线，规范化后必存在），
    最后退回 config.WEAKNESS_THRESHOLD。

    返回：
    {
      "evolved": bool,                      # 是否触发了演化
      "source": "stuck" | "steady",
      "trigger": {key, name, attempts, avg} | None,  # 卡壳概念（avg 最低者）
      "candidates": [规范过的 HarnessSpec...],       # evolve 候选，必过 check_harness
    }
    """
    from expert_anything.core import learner as _learner
    if threshold is None:
        threshold = float(spec.get("evaluation", {}).get("threshold", 0.6))
    stuck = _learner.stuck_concepts(learner_state, attempts=attempts,
                                    threshold=threshold)
    if concept_name:
        key = _learner.normalize(concept_name)
        trigger = next((s for s in stuck if s["key"] == key), None)
    else:
        trigger = stuck[0] if stuck else None
    if trigger is None:
        return {"evolved": False, "source": "steady",
                "trigger": None, "candidates": []}
    # 把卡壳信号映射成 evolve 可消费的会话报告：value 低于阈值 → O1 触发
    # （换讲解风格 + 补 scene）；无守卫误伤、步数未用满 → O2/O3 不触发。
    report = {
        "value": float(trigger["avg"]),
        "threshold": threshold,
        "guard_triggers": {},
        "steps_used": 0,
    }
    candidates = evolve(spec, report, candidates_limit=candidates_limit)
    return {"evolved": True, "source": "stuck", "trigger": trigger,
            "candidates": candidates}


def regression_detection(learner_state: dict, threshold: float | None = None,
                         attempts: int = 3, window: int = 6) -> list[dict]:
    """从学习轨迹检测"表现回退"—— 误伤的 learner 侧早期信号。

    与 ``stuck_concepts`` 互补：
      stuck（卡壳）    = 持续不达标 —— 可能本来就难，也可能是策略无效；
      regression（回归）= 曾经达标、最近连续不达标 —— 策略变化产生负效应的
                          强信号（"以前讲得懂，现在讲不懂了"）。若最近变化
                          的是 harness（守卫/工具/预算），回归正是 O2 误伤
                          的指控证据。

    对每个概念取最近 ``window`` 条**教学通道**评估（history 是唯一事实源，
    newest-first；``meta.review`` 记录跳过——复习低分是遗忘/巩固失败的证据，
    由 review_gain→gain_weak 管道处置，不是 harness 变化产生负效应的证据，
    混入会拿复习样本误触发 O2 裁守卫）：
    最近 ``attempts`` 条全部低于 threshold，且更早的窗口内存在 >= threshold
    的达标记录 → 判为回归。返回 [{key, name, before_avg, after_avg, drop,
    attempts}]，按 drop（before_avg - after_avg）降序。纯函数，无 LLM。
    """
    from expert_anything.core import learner as _learner
    if attempts < 2:
        attempts = 2
    if threshold is None:
        from expert_anything.core import config as _config
        threshold = _config.WEAKNESS_THRESHOLD
    rows: dict[str, list[float]] = {}
    names: dict[str, str] = {}
    for h in learner_state.get("history", []):  # newest first
        if (h.get("meta") or {}).get("review"):
            continue  # retention evidence — not teaching-channel regression
        key = h.get("key") or _learner.normalize(h.get("concept", ""))
        if not key:
            continue
        names.setdefault(key, h.get("concept", key))
        bucket = rows.setdefault(key, [])
        if len(bucket) >= window:
            continue  # 只关心最近 window 条
        try:
            bucket.append(float(h.get("score", 0.0)))
        except (TypeError, ValueError):
            continue
    out: list[dict] = []
    for key, scores in rows.items():
        if len(scores) < attempts:
            continue
        recent = scores[:attempts]       # 最新 attempts 条
        earlier = scores[attempts:]      # 更早的窗口内记录
        if max(recent) >= threshold:
            continue                     # 最近仍有达标 → 不是回归
        if not earlier or max(earlier) < threshold:
            continue                     # 从未达标 → 是 stuck，不是回归
        before = sum(earlier) / len(earlier)
        after = sum(recent) / len(recent)
        out.append({
            "key": key,
            "name": names.get(key, key),
            "before_avg": round(before, 2),
            "after_avg": round(after, 2),
            "drop": round(before - after, 2),
            "attempts": len(recent),
        })
    out.sort(key=lambda x: x["drop"], reverse=True)
    return out


def evolve_for_regression(spec: dict, learner_state: dict,
                          concept_name: str | None = None,
                          attempts: int = 3,
                          threshold: float | None = None,
                          candidates_limit: int = 3) -> dict:
    """回归信号驱动 harness 演化 —— O2（误伤裁守卫）的真实信号源。

    语义对照：
      stuck（evolve_for_stuck）→ "一直讲不懂" → O1 换风格（harness 结构变化
      的假设是"风格不对"）；
      regression（本函数）     → "以前讲得懂、最近讲不懂" → 强烈暗示 harness
      的某个守卫误伤教学。守卫里最可能造成"内容变浅"的是成本纪律
      budget_ok（预算卡住长讲解 → 讲解被截短 → 表现回退），因此把回归信号
      映射成 evolve 可消费的会话报告：guard_triggers = {budget_ok: attempts}，
      触发 O2 裁守卫（safe_only 永不裁；budget_ok 不在守卫列表时无抓手，
      退回稳态）。

    返回：
    {
      "evolved": bool,
      "source": "regression" | "steady",
      "trigger": {key, name, before_avg, after_avg, drop} | None,
      "candidates": [规范过的 HarnessSpec...],   # 必过 check_harness
    }
    """
    from expert_anything.core import learner as _learner
    regs = regression_detection(learner_state, threshold=threshold,
                                attempts=attempts)
    if concept_name:
        key = _learner.normalize(concept_name)
        trigger = next((r for r in regs if r["key"] == key), None)
    else:
        trigger = regs[0] if regs else None
    if trigger is None:
        return {"evolved": False, "source": "steady",
                "trigger": None, "candidates": []}
    guard_ids = spec.get("policy", {}).get("guard_ids", [])
    if "budget_ok" not in guard_ids:
        # 无预算守卫可裁 → 回归无对应 O2 抓手，退回稳态（不硬造候选）
        return {"evolved": False, "source": "steady",
                "trigger": trigger, "candidates": []}
    if threshold is None:
        threshold = float(spec.get("evaluation", {}).get("threshold", 0.6))
    report = {
        "value": float(trigger["after_avg"]),
        "threshold": threshold,
        "guard_triggers": {"budget_ok": trigger["attempts"]},
        "steps_used": 0,
    }
    candidates = evolve(spec, report, candidates_limit=candidates_limit)
    return {"evolved": True, "source": "regression", "trigger": trigger,
            "candidates": candidates}


# --- 联合演化（三层信号融合成一个决策，2026-08-18 第八轮） ---------------------
#
# 三个单信号入口（evolve_for_stuck / evolve_for_regression /
# evolve_from_sessions）各自触发自己的算子，但真实场景里信号是**并发**的：
# 一个概念可以同时"一直差"（stuck）且"从好变差"（regression，且回归 ⊆
# 卡壳，因为两者都要求最近 N 次不达标），会话报告统计也可能同时给出
# 守卫触发与步数吃紧。联合演化做三件单信号入口做不到的事：
#
#   1. 去重 —— 多信号同指同一算子时只产出一个候选（stuck 与会话达标率低
#      同时触发 O1 → 一个 O1 候选，不再重复出卡）；
#   2. 仲裁 —— O2 的裁守卫目标由「回归假设 × 会话实际触发」融合决定
#      （_o2_target_fusion）：实际触发数据存在时以实际为准，回归指向
#      budget_ok 但统计显示 no_definition_copy 触发最多 → 裁后者，
#      仲裁过程写进 diagnosis（数据方法论 6b：真实数据优先于假设）；
#   3. 诊断 —— 输出人类可读 evidence 行（diagnosis）与合并 reason
#      （如 "stuck+regression"），演化可解释性继续延伸。

def detect_signals(spec: dict, learner_state: dict,
                   reports: list[dict] | None = None,
                   concept_name: str | None = None,
                   attempts: int = 3,
                   threshold: float | None = None,
                   window: int = 6) -> dict:
    """统一信号检测：stuck / regression / sessions 三层信号一次算齐。

    三层信号（§8.4）：
      stuck      —— 最近 ``attempts`` 次评估全部不达标（learner.stuck_concepts）；
      regression —— 曾经达标、最近连续不达标（regression_detection，从好变差）；
      sessions   —— 真实会话报告聚合统计（aggregate_reports，reports 非空时）。

    焦点概念（focused）选择（确定性）：
      concept_name 显式指定 > 双信号并发概念（stuck ∩ regression，按
      drop 降序、after_avg 升序取最严重者）> regression（因果故事更强：
      策略变化产生负效应）> stuck（一直差）。focused 为 None 表示纯会话
      信号驱动（无 learner 侧焦点）。

    返回 {threshold, stuck, regression, sessions, focused}。
    """
    from expert_anything.core import learner as _learner
    from expert_anything.core import config as _config
    if threshold is None:
        threshold = float(spec.get("evaluation", {}).get("threshold")
                          or _config.WEAKNESS_THRESHOLD)
    stuck = _learner.stuck_concepts(learner_state, attempts=attempts,
                                    threshold=threshold)
    regs = regression_detection(learner_state, threshold=threshold,
                                attempts=attempts, window=window)
    if concept_name:
        key = _learner.normalize(concept_name)
        stuck = [s for s in stuck if s["key"] == key]
        regs = [r for r in regs if r["key"] == key]
    sessions = None
    if reports:
        agg = aggregate_reports(reports)
        sessions = agg if agg["n"] > 0 else None
    stuck_keys = {s["key"] for s in stuck}
    reg_keys = {r["key"] for r in regs}
    focused: dict | None = None
    both_keys = sorted(stuck_keys & reg_keys)  # 字典序保证确定性
    if both_keys:
        def _severity(k: str) -> tuple:
            r = next(x for x in regs if x["key"] == k)
            return (r["drop"], -r["after_avg"])
        k = max(both_keys, key=_severity)
        s = next(x for x in stuck if x["key"] == k)
        r = next(x for x in regs if x["key"] == k)
        focused = {"key": s["key"], "name": s["name"], "stuck": True,
                   "regression": True, "attempts": s["attempts"],
                   "avg": s["avg"], "before_avg": r["before_avg"],
                   "after_avg": r["after_avg"], "drop": r["drop"]}
    elif regs:
        r = regs[0]
        focused = {"key": r["key"], "name": r["name"],
                   "stuck": r["key"] in stuck_keys, "regression": True,
                   "attempts": r["attempts"], "avg": None,
                   "before_avg": r["before_avg"], "after_avg": r["after_avg"],
                   "drop": r["drop"]}
    elif stuck:
        s = stuck[0]
        focused = {"key": s["key"], "name": s["name"], "stuck": True,
                   "regression": False, "attempts": s["attempts"],
                   "avg": s["avg"], "before_avg": None, "after_avg": None,
                   "drop": None}
    return {"threshold": round(threshold, 2), "stuck": stuck,
            "regression": regs, "sessions": sessions, "focused": focused}


def _o2_target_fusion(signals: dict, spec: dict) -> tuple[str | None, list[str]]:
    """O2 裁守卫目标融合：回归假设 × 会话实际触发统计。

    回归信号的默认假设是成本纪律 budget_ok（预算卡住长讲解 → 内容变浅
    → 表现回退）；会话统计是**实际触发数据**。融合规则（真实数据优先于
    假设）：

      - 会话实际触发存在 → 以实际为准：裁累计触发最多的可裁守卫；
        若与回归假设同指 → 双证据（sources=[sessions, regression]）；
        若不同指 → 回归假设被数据修正（sources=[sessions]，仲裁过程
        由调用方写进 diagnosis）；
      - 会话数据缺失 → 保留回归假设（弱置信，sources=[regression]）；
      - 两者都没有 → 无抓手（None, []），不硬造候选。

    返回 (guard, sources)；sources 表示该目标的证据来源。
    """
    guard_ids = spec.get("policy", {}).get("guard_ids", [])
    if len(guard_ids) <= 1:
        return None, []          # 最后一个守卫不裁（纪律底线）
    sess_guard: str | None = None
    agg = signals.get("sessions") if isinstance(signals, dict) else None
    if isinstance(agg, dict) and isinstance(agg.get("guard_triggers"), dict):
        trig = {k: v for k, v in agg["guard_triggers"].items()
                if k in TRIMABLE_GUARDS}
        if trig:
            sess_guard = max(trig, key=lambda k: trig[k])
    regs = signals.get("regression") if isinstance(signals, dict) else None
    hyp = "budget_ok" if (regs and "budget_ok" in guard_ids) else None
    if sess_guard and sess_guard in guard_ids:
        sources = ["sessions"]
        if sess_guard == hyp:
            sources.append("regression")
        return sess_guard, sources
    if hyp:
        return hyp, ["regression"]
    return None, []


def evolve_joint(spec: dict, learner_state: dict,
                 reports: list[dict] | None = None,
                 concept_name: str | None = None,
                 attempts: int = 3,
                 threshold: float | None = None,
                 window: int = 6,
                 candidates_limit: int = 3) -> dict:
    """联合演化：三层信号融合成一个演化决策（推荐入口，取代单信号入口）。

    与三个单信号入口（``evolve_for_stuck`` / ``evolve_for_regression`` /
    ``evolve_from_sessions``）的差异：一次算齐全部信号（``detect_signals``），
    并做去重 / 仲裁 / 诊断三件事（见本节头部说明）。

    候选顺序按因果强度：回归驱动的 O2（"以前懂现在不懂"最急迫）优先，
    O1 换风格次之，O3 扩容殿后。全部候选再过 check_harness（演化也不
    允许绕过准入）。

    返回：
    {
      "evolved": bool,
      "source": "joint" | "steady",
      "signals": {"stuck": [...], "regression": [...], "sessions": agg|None},
      "focused": 触发概念 {key,name,stuck,regression,avg,drop,...} | None,
      "diagnosis": [str, ...],       # 人类可读 evidence 行（可解释性）
      "reason": "stuck" | "stuck+regression" | "sessions" | ...,
               # 触发家族（去重保序：stuck → regression → sessions），
               # 只含实际驱动了候选的家族；被数据修正的假设留在 diagnosis
      "candidates": [规范过的 HarnessSpec...],  # 必过 check_harness
    }
    """
    signals = detect_signals(spec, learner_state, reports=reports,
                             concept_name=concept_name, attempts=attempts,
                             threshold=threshold, window=window)
    threshold = signals["threshold"]
    agg = signals["sessions"]
    focused = signals["focused"]
    base = copy.deepcopy(spec)
    diagnosis: list[str] = []
    fired: list[str] = []
    cands: list[dict] = []

    # 回归证据行（无论最终裁谁，回归事实都要写进诊断）
    if focused and focused.get("regression"):
        diagnosis.append(
            f"回归：{focused['name']} 从 {focused['before_avg']:.2f} 回退到 "
            f"{focused['after_avg']:.2f}（drop {focused['drop']:.2f}，"
            f"最近 {focused['attempts']} 次未达标）")

    # O2 误伤：回归假设 × 会话实际触发融合（回归驱动时因果最强，候选优先）
    o2_guard, o2_sources = _o2_target_fusion(signals, spec)
    if o2_guard is not None:
        if set(o2_sources) == {"sessions", "regression"}:
            diagnosis.append(
                f"融合：回归假设与会话实际触发同指 {o2_guard} → 裁守卫")
        elif "sessions" in o2_sources and focused and focused.get("regression"):
            diagnosis.append(
                f"仲裁：回归假设指向 budget_ok，但会话实际触发最多的是 "
                f"{o2_guard} → 以实际数据为准")
        elif "sessions" in o2_sources:
            diagnosis.append(
                f"会话统计：{o2_guard} 触发累计最多 → 裁守卫")
        else:
            diagnosis.append(
                f"回归假设：{o2_guard}（成本纪律）疑似卡住讲解深度 → 裁守卫")
        c = _candidate_o2(base, o2_guard)
        if c is not None:
            cands.append(c)
            fired.extend(o2_sources)

    # O1 卡壳：持续不达标（focused.stuck）或会话达标率低（去重：同算子只出一个）
    o1_fired = False
    if focused and focused.get("stuck"):
        o1_fired = True
        diagnosis.append(
            f"卡壳：{focused['name']} 连续 {focused['attempts']} 次不达标"
            f"（均值 {focused['avg']:.2f}，阈值 {threshold:.2f}）")
    if agg and (agg["avg_value"] < threshold or agg["pass_rate"] < 0.5):
        o1_fired = True
        diagnosis.append(
            f"会话统计：n={agg['n']} 达标率 {agg['pass_rate']:.2f}，"
            f"均值 {agg['avg_value']:.2f}（阈值 {threshold:.2f}）")
    if o1_fired:
        c = _candidate_o1(base, spec)
        if c is not None:
            cands.append(c)
            if focused and focused.get("stuck"):
                fired.append("stuck")
            if agg and (agg["avg_value"] < threshold or agg["pass_rate"] < 0.5):
                fired.append("sessions")

    # O3 吃紧：会话步数满额率
    if agg and agg["steps_exhausted_rate"] >= 0.5:
        diagnosis.append(
            f"步数满额率 {agg['steps_exhausted_rate']:.2f} ≥ 0.5 → 扩容")
        c = _candidate_o3(base, spec)
        if c is not None:
            cands.append(c)
            fired.append("sessions")

    if not cands:
        return {"evolved": False, "source": "steady", "signals": signals,
                "focused": focused, "diagnosis": [], "reason": "",
                "candidates": []}
    # 触发家族去重保序（stuck → regression → sessions）
    reason = "+".join(p for p in ("stuck", "regression", "sessions")
                      if p in fired)
    return {"evolved": True, "source": "joint", "signals": signals,
            "focused": focused, "diagnosis": diagnosis, "reason": reason,
            "candidates": _admit_candidates(cands, candidates_limit)}


def suggest_harness(goal: str, context: str | None = None, llm=None,
                    lang: str = "zh-CN") -> tuple[dict, str]:
    """LLM 设计 HarnessSpec → 准入 → 失败带原因重试 1 次 → 确定性兜底。

    返回 (spec, source)，source ∈ {"llm", "llm_retry", "fallback"}。
    llm 约定：llm.chat(messages, temperature=..., json_mode=False) -> str
    （与 core.llm 一致；普通模式 + 容错解析，规避 json_mode 长 prompt 空返回）。
    """
    prompt = (
        "你是 AutoHarness 设计器：为「知识解码与学习系统」设计一个教学 Harness。\n"
        "Harness 是包裹在大模型外的确定性外壳（Agent = Model + Harness）。\n"
        "只输出一个 HarnessSpec JSON，不要任何解释、不要 Markdown 围栏。\n"
        "字段规范：\n"
        '  name: 字符串（≤40 字符）\n'
        f'  mode: {" / ".join(MODES)}（minimal 仅 teach，fast 加 quiz，full 加 scene/practice）\n'
        f'  tools: 非空数组，取值 {list(TOOL_SLOTS)}，按教学顺序排列\n'
        '  policy.teach_styles: 数组，取值 例子/图示/拆解步骤（讲解风格）\n'
        f'  policy.guard_ids: 数组，取值 {list(GUARD_IDS)}（守卫是强制门禁）\n'
        '  policy.retry: 0-2 整数（内容准入失败时的轮换重试次数）\n'
        '  policy.fallback: "deterministic"（失败后的显式降级）\n'
        f'  loop.max_steps: 1-{MAX_STEPS} 整数\n'
        f'  evaluation.metric: {" / ".join(METRICS)}；evaluation.threshold: 0-1 浮点\n'
        f'  meta.budget_cost: 0-{MAX_BUDGET} 整数；meta.sandbox: none/local/remote；'
        'meta.lang: 界面语言；meta.note: 一句话设计意图（≤120 字符）\n'
        "设计原则：工具顺序即教学节奏（先讲后测）；需要外部执行的工具（practice）"
        "必须配合 sandbox=local/remote，否则会被 safe_only 守卫拦截。"
    )
    if context:
        prompt += f"\n背景：{context}"
    if goal:
        prompt += f"\n本次教学目标：{goal}"
    # 语言指令在调用时拼接（项目规则 10：模块级常量拼接会在 import 时冻结语言）
    prompt += ("\n请使用" + lang + "撰写 note 与 name（字段名保持英文）。")

    def _ask(extra: str = "") -> str | None:
        if llm is None:
            return None
        try:
            return llm.chat([{"role": "user", "content": prompt + extra}],
                            temperature=0.3, json_mode=False, max_tokens=800)
        except Exception:
            return None

    spec = _tolerant_json(_ask())
    v, norm = check_harness(spec)
    if v and norm is not None:
        return norm, "llm"
    reason = v.reason if isinstance(v, CheckResult) else "解析失败"
    spec2 = _tolerant_json(_ask(f"\n\n上次产出被准入检查拒绝：{reason}。"
                                "请修正结构后重新输出完整 JSON。"))
    v2, norm2 = check_harness(spec2)
    if v2 and norm2 is not None:
        return norm2, "llm_retry"
    return fallback_harness(goal[:12]), "fallback"


# --- 差分评估（采纳的唯一依据） ----------------------------------------------

def compare_harnesses(control_reports: list[dict], treated_reports: list[dict],
                      key: str = "learning_gain", noise_floor: float = 0.05) -> dict:
    """OFF/ON 差分评估：同一镜像内双配置取差分，绝不能拿 ON 直接对标准答案比。

    项目数据方法论（BFCL 教训）的代码化：
      * 镜像自身的偏差必须被差分掉 —— 只比较 treated−control，不比较绝对分；
      * 噪声底噪标尺 —— |diff| ≤ noise_floor 判为 "noise"，即使方向看起来对
        也不采纳；非确定性系统先量噪声，|噪声| ≥ |信号| 时总体指标无效；
      * 结论至少三态 —— gain / loss / noise / inconclusive（前提不成立不可验证）。
    """
    def _mean(xs: list[dict]) -> float | None:
        vals = [r.get(key, 0.0) for r in xs if isinstance(r, dict)]
        return sum(vals) / len(vals) if vals else None

    ctrl, trt = _mean(control_reports), _mean(treated_reports)
    if ctrl is None or trt is None:
        return {"control": ctrl, "treated": trt, "diff": None,
                "noise_floor": noise_floor, "verdict": "inconclusive"}
    diff = trt - ctrl
    if abs(diff) <= noise_floor:
        verdict = "noise"
    elif diff > 0:
        verdict = "gain"
    else:
        verdict = "loss"
    return {"control": round(ctrl, 3), "treated": round(trt, 3),
            "diff": round(diff, 3), "noise_floor": noise_floor,
            "verdict": verdict}


# --- 结果回写与汇总 ----------------------------------------------------------

def apply_to_learner(report: dict, learner_state: dict, asset_id: str,
                     feedback: str = "") -> float:
    """把 harness 会话结果经既有 record_evaluation 通道回写掌握度。

    学习轨迹（meta）是唯一事实源：通道=harness、策略=spec_name、指标与
    守卫触发一并记录 —— 后续卡壳检测/报告/教师模型都读这条轨迹。
    """
    from expert_anything.core import learner as _learner
    meta = {"channel": "harness", "harness": report["spec_name"],
            "metric": report["metric"], "value": report["value"],
            "blocked": report["blocked"], "steps": report["steps_used"],
            "guard_triggers": json.dumps(report["guard_triggers"],
                                         ensure_ascii=False)}
    return _learner.record_evaluation(
        learner_state, report["concept"], asset_id, report["value"],
        answer="harness 会话", feedback=feedback or
        f"AutoHarness 会话完成（{report['spec_name']}，{report['metric']}={report['value']}）",
        meta=meta)


def harness_summary(spec: dict | None) -> str:
    """一行确定性描述（日志/课程卡片）。"""
    if not spec:
        return ""
    p = spec.get("policy", {})
    return (f"mode={spec.get('mode')} "
            f"tools={','.join(spec.get('tools', []))} "
            f"guards={len(p.get('guard_ids', []))} "
            f"steps={spec.get('loop', {}).get('max_steps')} "
            f"budget={spec.get('meta', {}).get('budget_cost')}")


# --- harness 状态持久化（UI 采纳环节） ---------------------------------------

def load_harness_state(path) -> dict[str, dict]:
    """读取按资产归档的 harness 状态（asset_id -> 规范化 HarnessSpec）。

    损坏/缺失 → 空 dict（调用方回退到默认 spec），不抛错。仅标准库
    json，无 UI 依赖 —— 采纳环节的持久化可 headless 测试。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict] = {}
        for aid, spec in data.items():
            if not isinstance(aid, str) or not isinstance(spec, dict):
                continue
            ok, norm = check_harness(spec)
            if ok and norm is not None:
                out[aid] = norm
        return out
    except (OSError, ValueError):
        return {}


def save_harness_state(path, states: dict[str, dict]) -> None:
    """持久化 harness 状态；写入前全部再过准入（演化也不允许绕过准入）。

    保留既有 ``_history`` 审计链与 ``_sessions`` 会话报告（顶层键，与
    asset_id 空间隔离）：本函数全量覆盖文件，若不保留会把演化历史与
    O2/O3 的信号底座冲掉 —— 两者都必须 append-only。
    """
    clean: dict[str, dict] = {}
    for aid, spec in states.items():
        ok, norm = check_harness(spec)
        if ok and norm is not None:
            clean[aid] = norm
    hist = load_harness_history(path)
    if hist:
        clean["_history"] = hist
    sess = load_session_reports(path)
    if sess:
        clean["_sessions"] = sess
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


# --- 演化历史审计链（append-only，唯一事实源在 harness 层的延伸） ---------------

def load_harness_history(path) -> list[dict]:
    """读 harness_state.json 的 ``_history`` 审计链（演化事件，时间正序）。

    损坏/缺失/类型不符 → 空 list，不抛错。只读，不修改文件。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        hist = data.get("_history") if isinstance(data, dict) else None
        if not isinstance(hist, list):
            return []
        return [e for e in hist if isinstance(e, dict)]
    except (OSError, ValueError):
        return []


def evolution_event(reason: str, old_spec: dict | None, new_spec: dict | None,
                    asset_id: str = "", concept: str = "",
                    extra: dict | None = None) -> dict:
    """构造一条演化审计事件（不落盘，由 record_harness_evolution 写入）。

    reason 取值约定：stuck（卡壳自动演化）/ steady（稳态复核）/
    manual（用户手动采纳候选）。old/new 是一行 harness_summary，
    spec_name 是新候选名 —— 展示与排查只需摘要，完整 spec 仍在状态里。
    """
    ev = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "asset_id": asset_id,
        "concept": concept,
        "reason": reason,
        "old": harness_summary(old_spec),
        "new": harness_summary(new_spec),
        "spec_name": (new_spec or {}).get("name", ""),
    }
    if extra:
        ev.update(extra)
    return ev


def record_harness_evolution(path, event: dict) -> list[dict]:
    """把一次演化事件追加进 harness_state.json 的 ``_history`` 审计链。

    append-only：读旧文件 → 取 history → append → 连各资产 spec 原样写回
    （spec 是 save_harness_state 时已过准入的，此处不重复校验）。
    损坏/缺失时以单事件文件重建。返回新 history，供调用方立即展示。
    """
    events = load_harness_history(path)
    ev = dict(event)
    ev.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    events.append(ev)
    data: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["_history"] = events
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return events


# --- 会话报告持久化（O2/O3 的真实信号底座） -----------------------------------
#
# Harness.run 产出的 ``report`` 包含 guard_triggers / steps_used / value /
# cost —— 这正是 O2（裁守卫）与 O3（扩容）需要的真实统计。单次报告只是
# 单点事实，演化需要一段时间的统计（aggregate_reports）；因此把真实会话
# 报告 append-only 落盘到 harness_state.json 顶层 ``_sessions``（与 _history
# 同一纪律：有界保留、只追加、不冲掉其它顶层键）。

def _norm_guard_triggers(v) -> dict:
    """把 guard_triggers 规范化为 {str: int}：非法值剔除，不抛错。"""
    if not isinstance(v, dict):
        return {}
    out: dict[str, int] = {}
    for g, c in v.items():
        try:
            out[str(g)] = int(c)
        except (TypeError, ValueError):
            continue
    return out


def load_session_reports(path) -> list[dict]:
    """读 harness_state.json 的 ``_sessions`` 会话报告（append-only，时间正序）。

    损坏/缺失/类型不符 → 空 list，不抛错。只读，不修改文件。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        sess = data.get("_sessions") if isinstance(data, dict) else None
        if not isinstance(sess, list):
            return []
        return [r for r in sess if isinstance(r, dict)]
    except (OSError, ValueError):
        return []


def persist_session_report(path, report: dict, max_keep: int = 20) -> list[dict]:
    """把一次 Harness.run 的真实会话报告追加进 ``_sessions``。

    append-only（演化信号必须有真实数据底座，不允许覆盖历史）；
    有界保留最近 ``max_keep`` 条（防无限增长）；字段规范化后写入
    （缺失键取默认值，损坏字段不抛错）。返回新列表，供调用方立即使用。
    """
    reports = load_session_reports(path)
    try:
        value = round(float(report.get("value", 0.0)), 2)
    except (TypeError, ValueError):
        value = 0.0
    try:
        threshold = round(float(report.get("threshold", 0.6)), 2)
    except (TypeError, ValueError):
        threshold = 0.6
    try:
        scores = [round(float(s), 2) for s in (report.get("scores") or [])
                  if isinstance(s, (int, float)) and not isinstance(s, bool)]
    except (TypeError, ValueError):
        scores = []
    slim = {
        "ts": _as_str(report.get("ts")) or datetime.now().isoformat(timespec="seconds"),
        "spec_name": _as_str(report.get("spec_name")),
        "concept": _as_str(report.get("concept")),
        "value": value,
        "threshold": threshold,
        "steps_used": _clamp_int(report.get("steps_used"), 0, MAX_STEPS * 2, 0),
        "max_steps": _clamp_int(report.get("max_steps"), 1, MAX_STEPS, 4),
        "guard_triggers": _norm_guard_triggers(report.get("guard_triggers")),
        "cost": _clamp_int(report.get("cost"), 0, MAX_BUDGET * 2, 0),
        "scores": scores,
    }
    reports.append(slim)
    reports = reports[-max_keep:]
    data: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["_sessions"] = reports
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return reports


# --- 跨资产 harness 泛化（迁移效果评估） --------------------------------------
#
# 一个 harness 在资产 A 上因卡壳演化/LLM 设计而变好，能否迁移到资产 B？
# 迁移评估回答的是「这个 harness 搬到那边值不值」，不是「它本身好不好」——
# 因此评估在**目标资产**上跑 OFF(本地默认) vs ON(待迁移) 双配置取差分
# （数据方法论 6b：同一镜像内双配置取差分，绝不拿 ON 直接对绝对线比），
# 并先校验前提（方法论 11：结论至少三态，前提不成立不可验证）。
# 迁移采纳同样走审计链：_history 追加 reason="transfer" 事件。

def asset_profile(asset) -> dict:
    """资产结构画像：迁移评估的前提特征（轻量、确定性、无 LLM）。

    - concepts / relations / path_steps：规模（full mode 需要结构支撑）
    - definition_rate：定义覆盖率（teach/quiz 的内容底座）
    - density：关系密度（scene 图示的支撑度）
    空资产除零保护，字段全部可 JSON 序列化。
    """
    concepts = list(getattr(asset, "concepts", None) or [])
    relations = list(getattr(asset, "relations", None) or [])
    path = list(getattr(asset, "learning_path", None) or [])
    defined = sum(1 for c in concepts if (c.definition or "").strip())
    return {
        "asset_id": _as_str(getattr(asset, "asset_id", "")),
        "title": _as_str(getattr(asset, "title", ""))[:40],
        "concepts": len(concepts),
        "relations": len(relations),
        "path_steps": len(path),
        "definition_rate": round(defined / len(concepts), 2) if concepts else 0.0,
        "density": round(len(relations) / len(concepts), 2) if concepts else 0.0,
    }


def transfer_eligibility(spec: dict, target_profile: dict) -> dict:
    """迁移前提检查（三态，对应数据方法论 11：先校验前提再下结论）。

    - eligible：目标资产可跑该 harness，可进入差分评估；
    - mismatch：结构不匹配 —— full mode 需要足够的概念/关系支撑，
      目标资产过于稀疏时迁移必然失败，直接拦截（不浪费差分执行）；
    - inconclusive：前提数据缺失 —— 目标资产无概念 / spec 非法，
      不可验证，返回 verify 而非结论。
    附加 warnings（不阻断）：定义覆盖率 0、sandbox 与内容底座不匹配等提示。
    """
    v, norm = check_harness(spec)
    if not v or norm is None:
        return {"state": "inconclusive", "reason": "invalid_spec",
                "spec_name": _as_str(spec.get("name"))[:40], "warnings": []}
    n = int(target_profile.get("concepts", 0))
    if n <= 0:
        return {"state": "inconclusive", "reason": "target_no_concepts",
                "spec_name": norm["name"], "warnings": []}
    warnings: list[str] = []
    if norm["mode"] == "full" and n < 3:
        return {"state": "mismatch", "reason": "structure_too_sparse",
                "spec_name": norm["name"],
                "warnings": [f"full mode 需要 ≥3 概念支撑，目标资产仅 {n} 个"]}
    if norm["meta"]["sandbox"] != "none" and n < 2:
        warnings.append("sandbox 非 none 但概念过少，practice 槽位可能无内容可练")
    rate = float(target_profile.get("definition_rate", 0.0))
    if rate <= 0.0:
        warnings.append("定义覆盖率为 0：teach/quiz 内容底座缺失，得分基准会偏低")
    return {"state": "eligible", "reason": "", "spec_name": norm["name"],
            "warnings": warnings}


def evaluate_transfer(spec: dict, source_asset, target_asset,
                      learner_state: dict | None = None, llm=None,
                      local_spec: dict | None = None,
                      noise_floor: float = 0.05,
                      concept_limit: int = 3) -> dict:
    """跨资产迁移差分评估：在目标资产上跑 OFF(本地默认) vs ON(待迁移)。

    逐概念跑双配置（最多 ``concept_limit`` 个，按学习路径顺序优先取样），
    聚合出差分（compare_harnesses 三态 + noise_floor）；同时报告成本/阻塞
    差分 —— 迁移可能有可测收益，也可能只是更贵。前提不成立（目标资产
    无概念 / spec 非法 / 本地对照非法）→ inconclusive，不产出推荐结论。

    返回：
    {
      "source"/"target": 资产画像,
      "eligibility": 前提检查结果,
      "spec_name": 待迁移 harness 名, "metric": 评估指标,
      "concepts_evaluated": n, "per_concept": [逐概念对照...],
      "comparison": compare_harnesses 差分结果,
      "cost_diff": 总成本差分（ON−OFF）, "blocked_diff": 阻塞差分,
      "coverage_control"/"coverage_treated": 每概念平均 score 事件数（验证宽度）,
      "coverage_diff": 覆盖度差分 —— 收益差分不可测（noise）时的结构性兜底,
      "recommendation": "migrate" | "no_change" | "keep_local" | "verify",
    }
    """
    def _inc(reason: str) -> dict:
        return {"source": asset_profile(source_asset),
                "target": asset_profile(target_asset),
                "eligibility": {"state": "inconclusive", "reason": reason,
                                "spec_name": _as_str(spec.get("name"))[:40],
                                "warnings": []},
                "spec_name": _as_str(spec.get("name"))[:40], "metric": "",
                "concepts_evaluated": 0, "per_concept": [],
                "comparison": {"control": None, "treated": None, "diff": None,
                               "noise_floor": noise_floor, "verdict": "inconclusive"},
                "cost_diff": 0, "blocked_diff": 0,
                "coverage_control": 0.0, "coverage_treated": 0.0,
                "coverage_diff": 0.0, "recommendation": "verify"}

    v, trt_norm = check_harness(spec)
    if not v or trt_norm is None:
        return _inc("invalid_spec")
    target_concepts = list(getattr(target_asset, "concepts", None) or [])
    if not target_concepts:
        return _inc("target_no_concepts")
    elig = transfer_eligibility(trt_norm, asset_profile(target_asset))
    control_spec = local_spec or fallback_harness(getattr(target_asset, "title", ""))
    vc, ctrl_norm = check_harness(control_spec)
    if not vc or ctrl_norm is None:
        return _inc("invalid_control")

    # 概念取样：学习路径顺序优先，其余按概念声明顺序
    path = list(getattr(target_asset, "learning_path", None) or [])
    by_id = {c.id: c for c in target_concepts}
    ordered = [by_id[p] for p in path if p in by_id]
    ordered += [c for c in target_concepts if c not in ordered]
    concepts = ordered[:concept_limit]

    key = trt_norm["evaluation"]["metric"]
    control_reports: list[dict] = []
    treated_reports: list[dict] = []
    per_concept: list[dict] = []
    for c in concepts:
        task = {"concept": c, "goal": f"学习 {c.name}"}
        cr = build_harness(ctrl_norm, asset=target_asset,
                           learner_state=learner_state, llm=llm).run(task)[1]
        tr = build_harness(trt_norm, asset=target_asset,
                           learner_state=learner_state, llm=llm).run(task)[1]
        control_reports.append(cr)
        treated_reports.append(tr)
        per_concept.append({
            "concept": c.name,
            "control": cr["value"], "treated": tr["value"],
            "cost_control": cr["cost"], "cost_treated": tr["cost"],
        })

    cmp = compare_harnesses(control_reports, treated_reports, key=key,
                            noise_floor=noise_floor)
    cost_diff = round(sum(r["cost"] for r in treated_reports) -
                      sum(r["cost"] for r in control_reports), 2)
    blocked_diff = sum(r["blocked"] for r in treated_reports) - \
                   sum(r["blocked"] for r in control_reports)

    # 计分覆盖度：一次 run 里产生 score 的事件数（quiz/practice/review 槽位），
    # 即验证闭环的宽度。确定性仿真下 learning_gain 只由 mastery×definition_len
    # 决定，工具集相同时 OFF/ON 必然同分 —— 收益差分不可测。此时覆盖度是唯一
    # 的结构性差分来源（由工具集决定，非仿真噪声）：ON 若比 OFF 多验证槽位，
    # 迁移在结构上提供了更强的掌握度信号。
    def _coverage(reports):
        return round(sum(len(r.get("scores") or []) for r in reports) /
                     len(reports), 2) if reports else 0.0

    coverage_control = _coverage(control_reports)
    coverage_treated = _coverage(treated_reports)
    coverage_diff = round(coverage_treated - coverage_control, 2)

    # recommendation：收益差分优先；收益不可测（noise）时用覆盖度差分兜底，
    # 且成本必须可接受（≤ 预算 30%，下限 5）——迁移不是免费的，覆盖度提升
    # 但显著更贵 → 维持 no_change。
    rec = "no_change"
    if cmp["verdict"] == "gain":
        rec = "migrate"
    elif cmp["verdict"] == "loss":
        rec = "keep_local"
    elif cmp["verdict"] == "inconclusive":
        rec = "verify"
    elif coverage_diff > 0 and \
            cost_diff <= max(5, int(trt_norm["meta"]["budget_cost"]) * 0.3):
        rec = "migrate"      # 结构性收益：验证槽位更多且成本可接受
    elif coverage_diff < 0:
        rec = "keep_local"   # 验证更弱，即使分数持平也不迁移

    return {
        "source": asset_profile(source_asset),
        "target": asset_profile(target_asset),
        "eligibility": elig,
        "spec_name": trt_norm["name"],
        "metric": key,
        "concepts_evaluated": len(concepts),
        "per_concept": per_concept,
        "comparison": cmp,
        "cost_diff": cost_diff,
        "blocked_diff": blocked_diff,
        "coverage_control": coverage_control,
        "coverage_treated": coverage_treated,
        "coverage_diff": coverage_diff,
        "recommendation": rec,
    }


def adopt_harness_for_asset(path, target_asset_id: str, spec: dict,
                            source_asset_id: str = "", concept: str = "",
                            note: str = "") -> tuple[bool, dict]:
    """把候选 harness 迁移采纳到目标资产：持久化 + 审计链。

    - spec 经 check_harness 后写入 harness_state.json 的 target_asset_id 键
      （迁移也不允许绕过准入）；旧 spec 摘要进审计事件 old 字段；
    - _history 追加 reason="transfer" 事件（append-only，保留既有审计链）；
    - 返回 (ok, event)；spec 非法 → (False, {})，不落盘不记史。
    """
    v, norm = check_harness(spec)
    if not v or norm is None:
        return False, {}
    states = load_harness_state(path)
    old = states.get(target_asset_id)
    states[target_asset_id] = norm
    save_harness_state(path, states)
    event = evolution_event("transfer", old, norm, asset_id=target_asset_id,
                            concept=concept,
                            extra={"source_asset_id": source_asset_id,
                                   "note": _as_str(note)[:120]})
    record_harness_evolution(path, event)
    return True, event
