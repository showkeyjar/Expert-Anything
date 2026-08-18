"""Code-enforced admission checks for LLM-generated learning artifacts.

Design borrowed from OmniScientist (arXiv:2608.13558): around every
open-ended LLM stage sits a *thin deterministic pipeline*, and a stage's
output is admitted only after a check enforced in code. OmniScientist
audits its manuscripts against the execution record rather than the
agent's prose; ExpertAnything analogously audits every teaching artifact
(lesson / quiz / practice / evaluation) against the knowledge model's
grounded evidence and structural rules — the prompt's "铁律" is a request,
the check here is enforcement.

The checks are deliberately cheap and deterministic (no LLM calls):
  * structural completeness — required fields exist and are usable;
  * grounding / substance   — an explanation must add intuition beyond a
                              verbatim copy of the definition;
  * anti-template           — lessons for different concepts must differ
                              (difflib similarity), enforcing the tutor's
                              own "每一个概念都必须独一无二" rule in code;
  * tempering               — absolute claims are softened, mirroring
                              OmniScientist rewriting "first" into
                              "appears under-explored" after a bounded search.

A failed check is not fatal: callers retry once with a stricter prompt
and then degrade to the deterministic fallback — the same bounded
fallback budget OmniScientist uses (max 2 returns to ideation).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass
class CheckResult:
    """Outcome of an admission check.

    ``code`` is a machine-readable reason (stable identifiers callers can
    quote back into the retry prompt); ``reason`` is human-readable zh-CN.
    """

    ok: bool
    code: str = ""
    reason: str = ""

    def __bool__(self) -> bool:  # allow `if check_lesson(...):`
        return self.ok


# --------------------------------------------------------------------------- #
# Lesson admission check
# --------------------------------------------------------------------------- #
def _name_hits(name: str, text: str) -> bool:
    """Does ``text`` visibly refer to the concept? The full name is the
    strongest signal; any meaningful token of it (>= 2 chars, split on
    whitespace) also counts, so "Memory" satisfies "Agent Memory"."""
    if not name:
        return True
    if name in text:
        return True
    tokens = [t for t in re.split(r"[\s/·、，,]+", name) if len(t) >= 2]
    return any(t in text for t in tokens)


def check_lesson(
    concept,
    lesson: dict,
    recent: list[dict] | None = None,
    sim_threshold: float = 0.84,
) -> CheckResult:
    """Admission check for a teach() lesson.

    ``recent`` carries the last few admitted lessons of *other* concepts
    ({"name", "explanation", "example"}) so template duplication across
    concepts can be rejected in code, not just requested in the prompt.
    """
    if not isinstance(lesson, dict):
        return CheckResult(False, "not_dict", "讲解结果不是对象")
    explanation = (lesson.get("explanation") or "").strip()
    if not explanation:
        return CheckResult(False, "empty_explanation", "讲解为空")
    if len(explanation) < 12:
        return CheckResult(False, "explanation_too_short", "讲解过短，缺少直觉性内容")
    definition = (getattr(concept, "definition", "") or "").strip()
    if definition and explanation.strip() == definition.strip():
        return CheckResult(
            False, "explanation_is_definition",
            "讲解只是抄写了定义原文，未加入直觉性内容",
        )
    if not (lesson.get("practice") or "").strip():
        return CheckResult(False, "empty_practice", "缺少练习问题")

    # anti-template: the lesson must be recognisably about THIS concept.
    name = (getattr(concept, "name", "") or "").strip()
    if name and not _name_hits(name, explanation) and not _name_hits(
        name, (lesson.get("example") or "") + "\n" + "\n".join(lesson.get("steps") or [])
    ):
        return CheckResult(
            False, "lesson_not_about_concept",
            f"讲解未提及本概念「{name}」或其证据，疑似套用模板",
        )

    if recent:
        cand = explanation + "\n" + (lesson.get("example") or "")
        for r in recent:
            if (r.get("name") or "") == name:
                continue  # same concept re-teaching is allowed to overlap
            other = (r.get("explanation") or "") + "\n" + (r.get("example") or "")
            if not other.strip():
                continue
            ratio = difflib.SequenceMatcher(None, cand, other).ratio()
            if ratio > sim_threshold:
                return CheckResult(
                    False, "template_duplicate",
                    f"讲解与概念「{r.get('name')}」的讲解相似度 {ratio:.2f}，"
                    f"超过阈值 {sim_threshold}，属于模板复用",
                )
    return CheckResult(True)


# --------------------------------------------------------------------------- #
# Quiz admission check (+ tolerant normalisation)
# --------------------------------------------------------------------------- #
def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "yes", "对", "正确", "√", "1"):
            return True
        if s in ("false", "f", "no", "错", "错误", "×", "0"):
            return False
    return None


def check_quiz(quiz) -> tuple[CheckResult, dict | None]:
    """Admission check for a generated self-test.

    Returns (result, normalized_quiz_or_None). Normalisation coerces the
    common LLM sloppiness (string indices, option-text instead of index,
    correct given as the negation wording) so a recoverable quiz is not
    thrown away, but a structurally broken one is rejected.
    """
    if not isinstance(quiz, dict):
        return CheckResult(False, "not_dict", "自测题不是对象"), None
    qtype = (quiz.get("type") or "").strip()
    question = (quiz.get("question") or "").strip()
    if not question:
        return CheckResult(False, "empty_question", "题干为空"), None

    if qtype == "true_false":
        correct = _as_bool(quiz.get("correct"))
        if correct is None:
            return CheckResult(False, "bad_correct", "判断题缺少可解析的对错答案"), None
        norm = dict(quiz)
        norm["type"] = "true_false"
        norm["correct"] = correct
        return CheckResult(True), norm

    if qtype == "ordering":
        options = quiz.get("options")
        if not isinstance(options, list) or not (3 <= len(options) <= 6):
            return CheckResult(False, "bad_options", "排序题需要 3-6 个选项"), None
        options = [str(o).strip() for o in options if str(o).strip()]
        if len(options) < 3:
            return CheckResult(False, "bad_options", "排序题有效选项不足 3 个"), None
        raw = quiz.get("correct_order")
        if not isinstance(raw, list) or not raw:
            return CheckResult(False, "bad_correct_order", "排序题缺少正确顺序"), None
        idx: list[int] = []
        for v in raw:
            if isinstance(v, bool):
                idx.append(int(v))
            elif isinstance(v, (int, float)):
                idx.append(int(v))
            elif isinstance(v, str):
                s = v.strip()
                if s.isdigit():
                    idx.append(int(s))
                elif s in options:
                    idx.append(options.index(s))
                else:
                    return CheckResult(False, "bad_correct_order",
                                       f"排序顺序含无法解析的项：{s!r}"), None
            else:
                return CheckResult(False, "bad_correct_order", "排序顺序含非法项"), None
        n = len(options)
        if sorted(idx) != list(range(n)) or len(idx) != n:
            return CheckResult(
                False, "not_a_permutation",
                f"正确顺序必须是 0..{n - 1} 的一个排列（含重复索引也会被拒绝）",
            ), None
        norm = dict(quiz)
        norm["type"] = "ordering"
        norm["options"] = options
        norm["correct_order"] = idx
        return CheckResult(True), norm

    return CheckResult(False, "bad_type", f"未知题型：{qtype!r}"), None


# --------------------------------------------------------------------------- #
# Practice-task / evaluation admission checks
# --------------------------------------------------------------------------- #
def check_practice(practice) -> tuple[CheckResult, dict | None]:
    if not isinstance(practice, dict):
        return CheckResult(False, "not_dict", "实践任务不是对象"), None
    task = (practice.get("task") or "").strip()
    if len(task) < 10:
        return CheckResult(False, "task_too_short", "任务描述过短，无法操作"), None
    norm = dict(practice)
    norm["task"] = task
    return CheckResult(True), norm


def check_evaluation(result) -> tuple[CheckResult, dict]:
    """Admission check for an evaluate() result.

    Scores outside [0, 1] are clamped (a bounded score always wins over a
    rejected one — the learner answered, that fact must land), an empty
    feedback gets an explicit placeholder so the UI never renders nothing.
    """
    if not isinstance(result, dict):
        return CheckResult(False, "not_dict", "评估结果不是对象"), {}
    try:
        score = float(result.get("score", 0.0))
    except (TypeError, ValueError):
        return CheckResult(False, "bad_score", "评估得分不可解析"), {}
    if not (0.0 <= score <= 1.0):
        score = max(0.0, min(1.0, score))
    norm = dict(result)
    norm["score"] = round(score, 2)
    if not str(norm.get("feedback") or "").strip():
        norm["feedback"] = "（导师未给出点评，已按得分记录本次作答。）"
    return CheckResult(True), norm


# --------------------------------------------------------------------------- #
# Tempering overconfident claims
# --------------------------------------------------------------------------- #
# OmniScientist rewrites "first" / "never explored" into "appears
# under-explored" because a bounded search cannot establish absolute
# priority. The learning-loop analog: generated explanations must not
# make absolute promises about learning outcomes or necessity that the
# evidence cannot support.
_TEMPER_RULES: list[tuple[str, str]] = [
    ("肯定会", "很可能会"),
    ("肯定会让你", "通常能帮你"),
    ("肯定能", "往往能"),
    ("一定能", "通常能"),
    ("一定能让你", "往往能让你"),
    ("绝对要", "建议"),
    ("绝对不能", "通常不建议"),
    ("必须要先", "建议先"),
    ("永远记住", "建议记住"),
    ("唯一的方法", "常用的方法之一"),
    ("唯一的办法", "常用的办法之一"),
    ("第一次提出", "较早提出"),
    ("首创了", "较早提出了"),
]


def temper_claims(text: str) -> str:
    """Soften absolute claims in generated teaching text (idempotent)."""
    if not text:
        return text
    out = text
    for old, new in _TEMPER_RULES:
        out = out.replace(old, new)
    return out
