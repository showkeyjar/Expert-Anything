"""Tutor Agent: the teaching brain.

Replaces the legacy deterministic loop with an LLM-driven tutor that
explains with source evidence, maps examples to the learner's goal, and
evaluates answers semantically (not by a confidence button).
"""
from __future__ import annotations

import json

from expert_anything.core.learner import load as load_learner
from expert_anything.core.llm import LLMClient, LLMError, LLMNotConfigured, Message
from expert_anything.core.models import Concept, KnowledgeAsset

TEACH_SYSTEM_BASE = (
    "你是耐心的私人导师。根据给出的【概念】和【原文证据】，用中文向学习者讲解。\n"
    "铁律：只基于给定证据讲解，不编造原文没有的内容；用学习者能理解的方式表达。\n"
    "最重要的一条：你讲到的【每一个概念都必须是独一无二的】——必须紧扣该概念自己的原文证据、"
    "它在知识网络里的具体位置与关系，绝不能给出放之四海皆准的通用套话或只替换概念名的模板。"
    "如果不同概念的讲解彼此雷同，说明你没有真正结合该概念的证据与关系，这是失败。"
)

# Style-specific emphasis. The alignment step captures the learner's preferred
# way to understand (例子 / 图示 / 拆解步骤); the teaching must actually change
# shape per choice or the selector feels "无效".
STYLE_HINT = {
    "例子": (
        "学习者偏好通过【具体例子】理解。请：① 先用一句话点出概念本质；"
        "② 给出一个与学习者目标高度相关、且【明确用到本概念原文证据】的具体例子，并说明例子里哪一步对应了概念；"
        "③ 再给一个‘反例’帮助区分。example 必须因概念而异，禁止模板化。把重点放在 example 字段。"
    ),
    "图示": (
        "学习者偏好【图示/结构】理解。请：① 用文字讲清这个概念在知识网络中的位置——它依赖什么、被什么依赖、"
        "和哪些概念相连（必须引用本概念的 relations）；② 说明它的组成或流程步骤。本系统会另行生成结构图，"
        "你只需把‘关系与位置’讲清楚。把重点放在 explanation 字段。"
    ),
    "拆解步骤": (
        "学习者偏好【拆解步骤】理解。请：① 一句话定义；"
        "② 把概念拆成 4-6 个可执行的小步骤，让人能照着做（steps 字段要详尽、可操作，且每一步都要落到本概念的证据/关系上，不要笼统）。"
        "把重点放在 steps 字段。"
    ),
}

TEACH_USER = (
    "学习者目标：{goal}\n"
    "学习基础：{baseline}\n"
    "偏好方式：{style}\n\n"
    "当前概念：{name}\n"
    "定义：{definition}\n"
    "原文证据：\n{evidence}\n"
    "本概念的关系网络（来自知识模型）：\n{relations}\n\n"
    "请输出 JSON：\n"
    "{{\n"
    '  "explanation": "讲解（基于本概念自己的证据与关系；若偏好图示，请重点讲清它在知识网络中的位置）",\n'
    '  "example": "结合学习者目标、且明确用到本概念证据的具体例子（偏好例子时尤其重要，必须因概念而异）",\n'
    '  "steps": ["步骤1", "步骤2", "步骤3"…（偏好拆解步骤时给出 4-6 个可操作小步骤，每步落到本概念）],\n'
    '  "practice": "请学习者用一两句话回答的练习问题（针对本概念）"\n'
    "}}"
)


def _neighbor_context(asset: "KnowledgeAsset", concept: "Concept") -> str:
    """Relations involving this concept, as readable lines for the prompt."""
    parts = []
    name = concept.name
    for r in asset.relations:
        if r.source == concept.id:
            tgt = asset.concept_by_id(r.target)
            if tgt:
                parts.append(f"- 「{name}」{r.label or '关联'} → 「{tgt.name}」")
        elif r.target == concept.id:
            src = asset.concept_by_id(r.source)
            if src:
                parts.append(f"- 「{src.name}」{r.label or '关联'} → 「{name}」")
    if not parts:
        return "（该概念在模型中暂无显式关系连线）"
    return "\n".join(parts)


def _teach_system(style: str) -> str:
    hint = STYLE_HINT.get(style, STYLE_HINT["例子"])
    return TEACH_SYSTEM_BASE + "\n" + hint


def _teach_user(goal, baseline, style, name, definition, evidence, relations, vary: int = 0) -> str:
    vary_suffix = ""
    if vary > 0:
        vary_suffix = (
            f"\n\n注意：这是第 {vary+1} 次讲解，example 必须与之前【明显不同】、"
            f"换个领域或换个角度，但仍须紧扣本概念「{name}」自己的证据与关系。"
        )
    return TEACH_USER.format(
        goal=goal, baseline=baseline, style=style, name=name,
        definition=definition, evidence=evidence, relations=relations,
    ) + vary_suffix

EVALUATE_SYSTEM = (
    "你是严格的导师，评估学习者对概念的掌握。只依据【原文证据】和【概念定义】判断，"
    "不因为回答长就给高分。输出 JSON："
    "{score: 0-1, understood: bool, feedback: 中文点评, "
    "reference: 基于原文证据的参考回答（120 字内，要点式），"
    "gap: 学习者的回答与参考回答的主要差距（40 字内；若已掌握则空串）}。"
)

EVALUATE_USER = (
    "概念：{name}\n定义：{definition}\n原文证据：{evidence}\n\n"
    "学习者回答：{answer}\n\n"
    "请评估，并给出参考回答与差距分析。"
)


FOLLOWUP_SYSTEM = (
    "你是耐心的私人导师，正在辅导学习者学习《{title}》中的「{name}」概念。"
    "回答学习者的追问。铁律：只基于【原文证据】和【已有讲解】回答，"
    "不编造原文没有的内容；回答具体、简洁（150 字内），优先引用原文证据；"
    "如果追问超出材料范围，明确说明材料里没有相关内容，不要硬答。"
)


class Tutor:
    def __init__(self, asset: KnowledgeAsset, llm: LLMClient | None = None) -> None:
        self.asset = asset
        self.llm = llm

    # --- alignment ---------------------------------------------------------
    def intro(self) -> dict:
        state = load_learner()
        profile = state.get("profile", {})
        if profile.get("goal"):
            return {
                "phase": "teach",
                "title": f"继续学习《{self.asset.title}》",
                "message": "已对齐你的目标，我们直接开始。",
            }
        return {
            "phase": "align",
            "title": f"开始学习《{self.asset.title}》",
            "message": "我先了解你的目标和基础，再决定怎么讲。",
            "concept_count": len(self.asset.concepts),
        }

    # --- teaching ----------------------------------------------------------
    def teach(self, concept: Concept, vary: int = 0, style: str | None = None) -> dict:
        profile = load_learner().get("profile", {})
        # An explicit style (e.g. the live dropdown in the UI) wins over the
        # persisted profile so the selector takes effect without a disk round-trip.
        if style is None:
            style = profile.get("style", "例子")
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["（无原文证据）"]))
        # Ground every generation in THIS concept's own relations so different
        # concepts produce genuinely different lessons (not one shared template).
        relations = _neighbor_context(self.asset, concept)
        goal = profile.get("goal", "理解这份知识资产")
        if self.llm is not None:
            try:
                content = self.llm.chat(
                    [
                        Message("system", _teach_system(style)),
                        Message(
                            "user",
                            _teach_user(
                                goal=goal,
                                baseline=profile.get("baseline", "不确定"),
                                style=style,
                                name=concept.name,
                                definition=concept.definition or concept.summary,
                                evidence=evidence,
                                relations=relations,
                                vary=vary,
                            ),
                        ),
                    ],
                    temperature=0.4,
                    json_mode=True,
                    max_tokens=900,
                )
                data = json.loads(content)

                def _text(v, default=""):
                    return str(v).strip() if v is not None else default

                def _steps(v):
                    if isinstance(v, list):
                        return [str(s) for s in v if str(s).strip()]
                    if isinstance(v, str) and v.strip():
                        return [s.strip() for s in v.splitlines() if s.strip()]
                    return []

                return {
                    "concept": concept.name,
                    "style": style,
                    "explanation": _text(data.get("explanation"), concept.definition or concept.summary),
                    "example": _text(data.get("example")),
                    "steps": _steps(data.get("steps")),
                    "practice": _text(data.get("practice"), "用自己的话解释这个概念，并指出原文依据。"),
                    "evidence": concept.evidence,
                }
            except (LLMNotConfigured, LLMError, ValueError, KeyError):
                # Network/JSON/parse failure → fall back to the deterministic,
                # style-aware stub rather than crashing the lesson render.
                pass
        # deterministic fallback — used when no LLM is reachable. Every field is
        # grounded in THIS concept's own definition / evidence / relations so that
        # different concepts produce genuinely different lessons (not one shared
        # template with only the name swapped).
        ev_list = list(concept.evidence or [])
        ev0 = ev_list[0] if ev_list else (concept.definition or concept.summary or "")
        defs = concept.definition or concept.summary or "（请阅读原文获取定义）"
        rel_lines = [ln for ln in (relations.splitlines() if relations else [])
                     if ln.strip() and "暂无" not in ln]
        rel_first = rel_lines[0] if rel_lines else ""

        def _clip(s: str, n: int = 46) -> str:
            s = s or ""
            return s[:n] + ("…" if len(s) > n else "")

        if style == "拆解步骤":
            steps = [
                f"1) 在原文里定位「{concept.name}」的定义句：{_clip(defs)}",
            ]
            if ev_list:
                steps.append(f"2) 读它的关键证据：「{_clip(ev0)}」")
            else:
                steps.append("2) 找出原文中支撑它的句子并抄录下来。")
            if rel_first:
                steps.append(f"3) 对照它的关系——{rel_first}——理解它在整体中的位置。")
            else:
                steps.append("3) 找出它与相邻概念的区别与联系。")
            steps += [
                f"4) 用你自己的话把「{concept.name}」讲给一个外行听。",
                f"5) 在「{goal}」里找一个能用上「{concept.name}」的具体环节并写下来。",
                f"6) 自检：抽掉「{concept.name}」，这一步还成立吗？",
            ]
            return {
                "concept": concept.name, "style": style,
                "explanation": defs,
                "example": (
                    f"以《{self.asset.title}》为例，「{concept.name}」的原文证据是：「{ev0}」。"
                    f"把它放进你的目标「{goal}」——哪个具体环节会用到它？"
                ),
                "steps": steps,
                "practice": f"列出使用「{concept.name}」的 3 个具体步骤。",
                "evidence": concept.evidence,
            }

        if style == "图示":
            rel_text = rel_first or "（暂无显式关系，可在原文里对照它的上下文与学习路径）"
            step_list = (
                ["定位「{concept.name}」", f"它依赖：{rel_first}", "它支撑的概念", f"在「{goal}」中定位"]
                if rel_first else
                ["定位「{concept.name}」", "对照学习路径理解前后概念", "在「{goal}」中定位", "用自己的话复述"]
            )
            return {
                "concept": concept.name, "style": style,
                "explanation": (
                    f"{defs}\n"
                    f"（已为你生成结构图：当前概念居中高亮，连线表示它与其它概念的关系。"
                    f"本概念的关系：{rel_text}）"
                ),
                "example": f"在结构图里找到居中的「{concept.name}」，看它与哪些概念相连：{rel_text}",
                "steps": step_list,
                "practice": f"用自己的话说明「{concept.name}」依赖什么、又被什么依赖。",
                "evidence": concept.evidence,
            }

        # default: 例子
        return {
            "concept": concept.name, "style": style,
            "explanation": defs,
            "example": (
                f"在《{self.asset.title}》里，「{concept.name}」是这样体现的：{ev0}。"
                f"把它放进你的目标「{goal}」中——具体哪个环节会用到「{concept.name}」？"
            ),
            "steps": [
                f"1) 定位原文中关于「{concept.name}」的句子。",
                f"2) 用自己的话复述它的定义：{_clip(defs)}",
                f"3) 在「{goal}」里找一个能用上它的真实场景。",
                f"4) 验证：如果抽掉「{concept.name}」，这一步会怎样？",
            ],
            "practice": f"用自己的话解释「{concept.name}」，并指出原文中支持你回答的关键句。",
            "evidence": concept.evidence,
        }

    # --- follow-up questions -------------------------------------------------
    def follow_up(self, concept: Concept, question: str,
                  lesson: dict | None = None,
                  history: list[tuple[str, str]] | None = None) -> str:
        """Answer a follow-up question grounded in the concept + prior lesson.

        ``lesson`` is the last teach() result (explanation/example/steps);
        ``history`` carries the last few (question, answer) pairs so the
        conversation stays coherent. Returns plain text; degrades to a
        marked message when no LLM is available.
        """
        if self.llm is None:
            return "（未接入 LLM，无法追问。配置 API Key 后可进行对话式追问。）"
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["（无原文证据）"]))
        relations = _neighbor_context(self.asset, concept)
        lesson_txt = ""
        if lesson:
            parts = []
            for k in ("explanation", "example", "practice"):
                if lesson.get(k):
                    parts.append(f"{k}: {lesson[k]}")
            lesson_txt = "\n".join(parts)[:1000]
        hist_txt = ""
        if history:
            hist_txt = "\n".join(
                f"学习者问：{q}\n导师答：{a}" for q, a in history[-2:]
            )
        user = (
            "概念定义：{defn}\n"
            "原文证据：\n{evidence}\n"
            "关系网络：\n{relations}\n\n"
            "已有讲解：\n{lesson}\n\n"
            "最近对话：\n{hist}\n\n"
            "学习者追问：{question}\n\n请回答。"
        ).format(
            defn=concept.definition or concept.summary or "（无定义）",
            evidence=evidence,
            relations=relations,
            lesson=lesson_txt or "（无）",
            hist=hist_txt or "（无）",
            question=question.strip(),
        )
        try:
            return self.llm.chat(
                [
                    Message("system", FOLLOWUP_SYSTEM.format(
                        title=self.asset.title, name=concept.name)),
                    Message("user", user),
                ],
                temperature=0.4,
                max_tokens=500,
            )
        except (LLMNotConfigured, LLMError):
            return "（LLM 暂时不可用，无法回答追问。）"

    # --- evaluation --------------------------------------------------------
    def evaluate(self, concept: Concept, answer: str) -> dict:
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["（无原文证据）"]))
        if self.llm is not None:
            try:
                content = self.llm.chat(
                    [
                        Message("system", EVALUATE_SYSTEM),
                        Message(
                            "user",
                            EVALUATE_USER.format(
                                name=concept.name,
                                definition=concept.definition or concept.summary,
                                evidence=evidence,
                                answer=answer or "（学习者未作答）",
                            ),
                        ),
                    ],
                    temperature=0.2,
                    json_mode=True,
                    max_tokens=500,
                )
                data = json.loads(content)
                score = max(0.0, min(1.0, float(data.get("score", 0.0))))
                return {
                    "score": round(score, 2),
                    "understood": bool(data.get("understood", score >= 0.6)),
                    "feedback": data.get("feedback", "已记录你的回答。"),
                    "reference": (data.get("reference") or "").strip(),
                    "gap": (data.get("gap") or "").strip(),
                }
            except (LLMNotConfigured, LLMError, ValueError, KeyError):
                # Network/JSON/parse failure → fall back to the length heuristic.
                pass
        # heuristic fallback: clearly marked, not a real evaluation
        words = len(answer.strip())
        score = 0.3 if words < 5 else (0.6 if words < 30 else 0.8)
        return {
            "score": score,
            "understood": score >= 0.6,
            "feedback": "（未接入 LLM，这是基于回答长度的粗略估计，不是真实评估。）",
            "reference": "",
            "gap": "",
        }
