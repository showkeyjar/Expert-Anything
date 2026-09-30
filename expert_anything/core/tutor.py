"""Tutor Agent: the teaching brain.

Replaces the legacy deterministic loop with an LLM-driven tutor that
explains with source evidence, maps examples to the learner's goal, and
evaluates answers semantically (not by a confidence button).
"""
from __future__ import annotations

import logging

from expert_anything.core import checks
from expert_anything.core import decoder
from expert_anything.core.learner import load as load_learner
from expert_anything.core.llm import (
    LLMClient,
    LLMError,
    LLMNotConfigured,
    Message,
    parse_llm_json,
)
from expert_anything.core.models import Concept, KnowledgeAsset
from expert_anything.core.prompt_registry import get_prompt

# Canonical style codes (used internally; UI labels are i18n translated).
STYLE_CODES = ["example", "diagram", "steps"]
STYLES = STYLE_CODES  # backward compat alias
# Legacy Chinese style literals (old learner profiles / not-yet-migrated tests)
_LEGACY_STYLE_MAP = {"例子": "example", "图示": "diagram", "拆解步骤": "steps"}


def _next_style(style: str) -> str:
    try:
        return STYLE_CODES[(STYLE_CODES.index(style) + 1) % len(STYLE_CODES)]
    except ValueError:
        return STYLE_CODES[0]

def _tolerant_json(text: str) -> dict:
    """Parse JSON from an LLM response, tolerating fences and prose.

    Thin wrapper over the canonical ``llm.parse_llm_json`` (kept for the
    ``isinstance(dict)`` guard this module relies on).
    """
    d = parse_llm_json(text)
    return d if isinstance(d, dict) else {}


def _degraded(where: str, reason: str) -> None:
    """Log a deterministic-fallback event so degradation is observable.

    The tutor degrades rather than crashes by design, but silent degradation
    is undiagnosable: a fenced-JSON parse failure used to look identical to
    'no LLM'. One debug log line per degradation keeps the fallback path
    auditable without polluting normal output.
    """
    logging.getLogger("expert_anything.tutor").debug(
        "tutor degraded at %s: %s", where, reason
    )


def _lang_instruction() -> str:
    """Instruction that makes LLM output follow the active UI language."""
    from expert_anything.core.i18n import get_lang as _gl
    return {
        "zh-CN": "",
        "en": "Answer in English.",
        "ja": "日本語で回答してください。",
    }.get(_gl(), "")


TEACH_SYSTEM_BASE = (
    "你是耐心的私人导师。根据给出的【概念】和【原文证据】，向学习者讲解。\n"
    "铁律：只基于给定证据讲解，不编造原文没有的内容；用学习者能理解的方式表达。\n"
    "最重要的一条：你讲到的【每一个概念都必须是独一无二的】——必须紧扣该概念自己的原文证据、"
    "它在知识网络里的具体位置与关系，绝不能给出放之四海皆准的通用套话或只替换概念名的模板。"
    "如果不同概念的讲解彼此雷同，说明你没有真正结合该概念的证据与关系，这是失败。"
)

_EXPLANATION_RULE = (
    "无论采用哪种风格，【explanation 字段都必须给出 1-2 句直觉性讲解】"
    "（这个为什么重要、它解决什么困惑、和一个你熟悉的领域的类比），"
    "绝不能只抄定义原文或留空——否则讲解卡片会显得空洞。"
    "example / steps / 关系位置 是补充，不是 explanation 的替代品。"
)

# Internal style hints keyed by canonical code.
_STYLE_HINTS = {
    "example": (
        "学习者偏好通过【具体例子】理解。请：① 先用一句话点出概念本质（写入 explanation，见下方铁律）；"
        "② 给出一个与学习者目标高度相关、且【明确用到本概念原文证据】的具体例子，并说明例子里哪一步对应了概念；"
        "③ 再给一个'反例'帮助区分。example 必须因概念而异，禁止模板化。把重点放在 example 字段，"
        "但 explanation 仍需满足铁律（一句话本质 + 为什么重要）。\n"
        + _EXPLANATION_RULE
    ),
    "diagram": (
        "学习者偏好【图示/结构】理解。请：① 用文字讲清这个概念在知识网络中的位置——它依赖什么、被什么依赖、"
        "和哪些概念相连（必须引用本概念的 relations），写入 explanation（见下方铁律，需含 1-2 句直觉+为什么重要）；"
        "② 说明它的组成或流程步骤。本系统会另行生成结构图，你只需把'关系与位置'讲清楚。"
        "把重点放在 explanation 字段的关系与位置部分。\n"
        + _EXPLANATION_RULE
    ),
    "steps": (
        "学习者偏好【拆解步骤】理解。请：① 一句话定义 + 1-2 句为什么重要/直觉（写入 explanation，见下方铁律）；"
        "② 把概念拆成 4-6 个可执行的小步骤，让人能照着做（steps 字段要详尽、可操作，且每一步都要落到本概念的证据/关系上，不要笼统）。"
        "把重点放在 steps 字段，但 explanation 不能只抄定义。\n"
        + _EXPLANATION_RULE
    ),
}


def _neighbor_context(asset: "KnowledgeAsset", concept: "Concept") -> str:
    """Relations involving this concept, grouped by semantic type.

    The grouping helps the LLM understand *what kind* of connection each
    relation is (causes / part-of / prerequisite / contrast / …), so it
    can produce a more structurally aware lesson instead of a flat list.
    """
    from expert_anything.core.decoder import classify_relation, REL_SEMANTICS

    name = concept.name
    by_sem: dict[str, list[str]] = {}
    for r in asset.relations:
        if r.source == concept.id:
            tgt = asset.concept_by_id(r.target)
            if tgt:
                sem = classify_relation(r.label or "", r.type or "")
                sem_label = REL_SEMANTICS.get(sem, {}).get("label", "关联")
                by_sem.setdefault(sem_label, []).append(
                    f"「{name}」{r.label or '关联'} → 「{tgt.name}」"
                )
        elif r.target == concept.id:
            src = asset.concept_by_id(r.source)
            if src:
                sem = classify_relation(r.label or "", r.type or "")
                sem_label = REL_SEMANTICS.get(sem, {}).get("label", "关联")
                by_sem.setdefault(sem_label, []).append(
                    f"「{src.name}」{r.label or '关联'} → 「{name}」"
                )
    if not by_sem:
        return "(该概念在模型中暂无显式关系连线)"
    parts = []
    for sem_label, lines in by_sem.items():
        parts.append(f"【{sem_label}】")
        for ln in lines:
            parts.append(f"  - {ln}")
    return "\n".join(parts)


def _teach_system(style: str) -> str:
    """Build the full system prompt for teach(). Style-hint is always
    read from the registry at call time so the i18n language switch takes
    effect even after module import (avoiding the i18n module-level eval trap).
    """
    # Try the registry first (multi-language).  Fall back to the embedded
    # Chinese dict so deterministic mode keeps working.
    hint_key = f"tutor_teach_style_{style}"
    hint = get_prompt(hint_key, default=None)  # type: ignore[attr-defined]
    if hint is None:
        hint = _STYLE_HINTS.get(style, _STYLE_HINTS["example"])
    base = get_prompt("tutor_teach_system", default=None)  # type: ignore[attr-defined]
    if base is None:
        base = TEACH_SYSTEM_BASE
    return base + _lang_instruction() + "\n" + hint


# Rotating "fresh angle" seeds for the vary/「换一个例子」mechanism. Each value
# forces a structurally different example domain so repeated teach() calls on the
# same concept actually diverge (otherwise the LLM tends to return the same
# canonical example every time).
VAR_Y_ANGLES = [
    "从日常生活中的一个具体场景举例",
    "从工程或系统架构的角度举例",
    "从另一个学科(如生物学、经济学或物理学)的类比举例",
    "从初学者最容易踩坑的反例 / 误区角度举例",
]


def _teach_user(goal, baseline, style, name, definition, evidence, relations,
                context: str = "", recent: str = "", vary: int = 0) -> str:
    # Use registry prompts when available; fall back to embedded zh-CN.
    tmpl = get_prompt("tutor_teach_user", default=None)  # type: ignore[attr-defined]
    if tmpl is None:
        # Embedded zh-CN fallback (deterministic mode)
        tmpl = (
            "学习者目标：{goal}\n"
            "学习基础：{baseline}\n"
            "偏好方式：{style}\n\n"
            "当前概念：{name}\n"
            "定义：{definition}\n"
            "原文证据：\n{evidence}\n"
            "本概念的关系网络（已按语义分组：因果/组成/前提/对比/分类/关联）：\n{relations}\n\n"
            "学习者已掌握的其他书概念（来自学习记录）：\n{context}\n"
            "（如果当前概念与其中某个有直接关联——相似/前置/对照/应用关系——在 cross_link 中给出；"
            "确实无关或列表为空则 cross_link 为 null。这是个性化学习的关键，请认真判断。）\n\n"
            "请输出 JSON：\n"
            "{{\n"
            '  "explanation": "讲解（基于本概念自己的证据与关系；必须含 1-2 句直觉性内容：为什么重要/它解决什么困惑/类比；绝不能只抄定义原文）",\n'
            '  "example": "结合学习者目标、且明确用到本概念证据的具体例子（偏好例子时尤其重要，必须因概念而异）",\n'
            '  "analogy": "一个能快速建立直觉的类比：把本概念映射到学习者可能熟悉的领域（编程/系统架构/日常生活/其它学科），一句话讲清对应关系（若概念抽象，此字段尤其重要；若难以类比可填空串）",\n'
            '  "cross_link": {{"name": "已学概念名", "asset": "来源书标题", "relation": "与当前概念的关系说明（30字内）"}} 或 null,\n'
            '  "connected": "用2-4句话总结本概念在知识网络中的位置：它和哪些概念有什么类型的关系（因果/组成/前提/对比等），这些关系为什么重要。基于上面已分组的关系网络。",\n'
            '  "steps": ["步骤1", "步骤2", "步骤3"…（偏好拆解步骤时给出 4-6 个可操作小步骤，每步落到本概念）],\n'
            '  "practice": "请学习者用一两句话回答的练习问题（针对本概念）"\n'
            "}}"
        )

    vary_suffix = ""
    if vary > 0:
        angle_key = f"tutor_vary_{(((vary - 1) % len(VAR_Y_ANGLES)) + 1)}"
        angle = get_prompt(angle_key, default=None)  # type: ignore[attr-defined]
        if angle is None:
            angle = VAR_Y_ANGLES[(vary - 1) % len(VAR_Y_ANGLES)]
        notice = get_prompt(
            "tutor_vary_notice",
            default="注意:这是第 {n} 次讲解,必须与之前【明显不同】。",
        )
        try:
            notice = notice.format(n=vary + 1)
        except Exception:
            pass
        vary_suffix = (
            f"\n\n{notice} "
            f"{angle}——"
            f"例子、类比、steps 都要全新,不得重复上次的任何例子或角度,"
            f"但仍须紧扣本概念「{name}」自己的证据与关系。"
        )
    return tmpl.format(
        goal=goal, baseline=baseline, style=style, name=name,
        definition=definition, evidence=evidence, relations=relations,
        context=context or get_prompt("tutor_learned_none", default="（无相关已学概念）"),
        recent=recent,
    ) + vary_suffix

EVALUATE_SYSTEM = (
    "你是严格的导师,评估学习者对概念的掌握。只依据【原文证据】和【概念定义】判断,"
    "不因为回答长就给高分。输出 JSON:"
    "{score: 0-1, understood: bool, feedback: 中文点评, "
    "reference: 基于原文证据的参考回答(120 字内,要点式),"
    "gap: 学习者的回答与参考回答的主要差距(40 字内;若已掌握则空串)}。"
)

EVALUATE_USER = (
    "概念:{name}\n定义:{definition}\n原文证据:{evidence}\n"
    "关系网络:\n{relations}\n\n"
    "学习者回答:{answer}\n\n"
    "请评估,并给出参考回答与差距分析。"
    "参考回答应涵盖概念的定义及其在关系网络中的位置（它和什么概念有什么类型的关系）。"
)


# Cross-judge arbitration (OmniScientist uses two cross-family judges).
# A single verdict is most uncertain exactly in the middle score band, so
# only boundary scores pay for a second, independently-framed evaluation -
# clearly-passing / clearly-failing answers are trusted as-is (budget).
JUDGE_BOUNDARY = (0.4, 0.6)

ARBITER_SYSTEM = (
    "你是第二位独立裁判,从不同视角复核学习者的回答。不要参考任何已有评分,"
    "只依据【原文证据】和【概念定义】独立判断掌握程度:不给同情分,也不刻意压分。"
    "只输出 JSON:{score: 0-1, note: 20 字内复核意见}。"
)

ARBITER_USER = (
    "概念:{name}\n定义:{definition}\n原文证据:\n{evidence}\n"
    "关系网络:\n{relations}\n\n"
    "学习者回答:{answer}\n\n请独立复核并打分。"
)


# --- knowledge decoder: SceneSpec generation -------------------------------
# The LLM only describes the scene (typed JSON); decoder.py renders it
# deterministically. Literal braces below are fine: never .format() this.
SCENE_SYSTEM = (
    "你是知识可视化设计师。根据【概念】【定义】【原文证据】【关系网络】,设计一个"
    "把该抽象概念'解译'成可视化场景的规范(SceneSpec)。"
    "铁律:节点与步骤必须源于给定的证据与关系,不得编造原文外的实体;"
    "节点的 kind 从 box(普通概念)/store(存储)/flow(动作或流程)/note(补充说明)/"
    "current(当前概念本身) 中选;steps 按理解的先后顺序逐步揭示节点;"
    "game 是可选的排序小游戏,把概念的关键流程打乱让学习者重排。"
    "只输出 JSON,不要输出任何其他文字:\n"
    "{\n"
    '  "title": "场景标题(15字内)",\n'
    '  "nodes": [{"id": "n1", "label": "节点名(10字内)", "kind": "box"}](3-8个,布局由系统自动完成,不要提供坐标;当前概念本身必须是 kind="current" 的节点),\n'
    '  "edges": [{"from": "n1", "to": "n2", "label": "关系(8字内)", "dashed": false}](from/to 必须是上面的节点 id),\n'
    '  "steps": [{"caption": "这一步发生了什么(30字内)", "show": ["n1", "n2"], "active": "n1"}](2-6步,show 是到该步为止累计可见的节点 id,active 是本步焦点节点),\n'
    '  "game": {"type": "sort", "goal": "把什么按正确顺序排列(20字内)", "items": ["打乱顺序的条目"], "answer": [2, 0, 1]}(items 3-6 条,answer 是 items 按正确顺序的索引排列;不需要游戏则填 null)\n'
    "}"
)

SCENE_USER = (
    "概念:{name}\n定义:{definition}\n原文证据:\n{evidence}\n"
    "关系网络:\n{relations}\n\n请设计 SceneSpec。"
)


FOLLOWUP_SYSTEM = (
    "你是耐心的私人导师,正在辅导学习者学习《{title}》中的「{name}」概念。"
    "回答学习者的追问。铁律:只基于【原文证据】和【已有讲解】回答,"
    "不编造原文没有的内容;回答具体、简洁(150 字内),优先引用原文证据;"
    "如果追问超出材料范围,明确说明材料里没有相关内容,不要硬答。"
)


class Tutor:
    def __init__(
        self,
        asset: KnowledgeAsset,
        llm: LLMClient | None = None,
        learner_state: dict | None = None,
    ) -> None:
        self.asset = asset
        self.llm = llm
        # Live learner state (shared dict with the UI). Reading it from disk on
        # every teach/intro call raced the UI's in-memory state: the disk copy
        # could lag behind (record_evaluation → save happens later), so stuck
        # rotation and personalisation decided on stale data. The state dict is
        # read-only here; the learning loop writes via record_evaluation.
        self._learner_state: dict | None = learner_state
        # Last few admitted lessons (other concepts) - feeds the anti-template
        # admission check so template-duplicated lessons get rejected in code.
        self._recent_lessons: list[dict] = []
        self._last_check_fail: str = ""

    def _learner(self) -> dict:
        """Current learner state: injected live state, else disk (standalone use)."""
        if self._learner_state is not None:
            return self._learner_state
        try:
            return load_learner()
        except Exception:
            return {"profile": {}, "concepts": {}, "assets": {}, "history": []}

    def _remember_lesson(self, lesson: dict) -> None:
        self._recent_lessons.append({
            "name": lesson.get("concept", ""),
            "explanation": lesson.get("explanation", ""),
            "example": lesson.get("example", ""),
        })
        self._recent_lessons = self._recent_lessons[-5:]

    def _decode_scene(self, concept: Concept) -> dict | None:
        """Knowledge decoding (vision: abstract → visible/playable).

        LLM emits a SceneSpec; decoder.check_scene is the code-enforced gate;
        bounded budget = 2 attempts, failure reason quoted back on attempt 2.
        Returns the normalized spec, or None (caller falls back to the
        deterministic relation-graph scene).
        """
        if self.llm is None:
            return None
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))
        relations = _neighbor_context(self.asset, concept)
        user = SCENE_USER.format(
            name=concept.name,
            definition=concept.definition or concept.summary or "",
            evidence=evidence,
            relations=relations,
        )
        last_fail = ""
        for attempt in (1, 2):
            try:
                suffix = "" if attempt == 1 else (
                    f"\n\n注意:你上一次的场景规范未通过代码校验:{last_fail}。"
                    "请严格按 schema 重写(节点 id 一致、步骤引用存在的节点、"
                    "answer 是 0..n-1 的排列)。"
                )
                content = self.llm.chat(
                    [
                        Message("system", SCENE_SYSTEM + _lang_instruction()),
                        Message("user", user + suffix),
                    ],
                    temperature=0.3,
                    max_tokens=900,
                )
                raw = decoder.tolerant_scene_json(content)
                verdict, spec = decoder.check_scene(raw)
                if verdict and spec is not None:
                    return spec
                last_fail = verdict.reason
            except Exception:
                return None  # network/parse failure: retrying won't help
        return None

    # --- Phase 4: terminology + domain profile ------------------------------
    def domain_id(self) -> str:
        """Domain pack used for terminology / profile lookups.

        Falls back to the shared default pack, so a plain knowledge asset
        (which carries no domain) still gets the domain terminology table.
        """
        from expert_anything.core import terminology
        return str(getattr(self.asset, "domain_id", "") or terminology.DEFAULT_DOMAIN)

    def enrich(self, lesson: dict, concept: Concept, state: dict | None = None) -> dict:
        """Attach the Phase 4 blocks to a lesson — 术语对照 + 领域画像.

        * ``terminology``: the registered template term for this concept (or
          ``None`` when the template does not register it) plus the template
          terms mentioned in the concept's own definition / evidence;
        * ``profile``: :func:`learner.detect_user_profile` output for the
          current learner state, with ``difficulty_hint`` mirrored at the top
          level so the UI can pick a difficulty without unpacking the dict.

        Purely additive and guarded: any failure leaves the lesson untouched,
        because teaching must never break over an optional enrichment.
        """
        try:
            from expert_anything.core import learner as learner_mod
            from expert_anything.core import terminology
            domain_id = self.domain_id()

            term = terminology.get_term(concept.name, domain_id)
            haystack = "\n".join([
                concept.definition or "",
                concept.summary or "",
                *[str(e) for e in (concept.evidence or [])],
            ])
            related: list[dict] = []
            for hit in terminology.match_terms(haystack, domain_id):
                if term is not None and hit["id"] == term.id:
                    continue
                if any(r["id"] == hit["id"] for r in related):
                    continue
                related.append({
                    "id": hit["id"],
                    "name": hit["name"],
                    "matched": hit["matched"],
                    "definition": hit["definition"],
                })
                if len(related) >= 3:
                    break

            lesson["terminology"] = {
                "self": term.to_dict() if term is not None else None,
                "related": related,
            }
            if state is None:
                state = learner_mod.load()
            profile = learner_mod.detect_user_profile(state, domain_id)
            lesson["profile"] = profile
            lesson["difficulty_hint"] = profile.get("difficulty_hint", "unknown")
        except Exception:
            pass
        return lesson

    # --- alignment ---------------------------------------------------------
    def intro(self) -> dict:
        state = self._learner()
        profile = state.get("profile", {})
        if profile.get("goal"):
            return {
                "phase": "teach",
                "title": f"继续学习《{self.asset.title}》",
                "message": "已对齐你的目标,我们直接开始。",
            }
        return {
            "phase": "align",
            "title": f"开始学习《{self.asset.title}》",
            "message": "我先了解你的目标和基础,再决定怎么讲。",
            "concept_count": len(self.asset.concepts),
        }

    # --- teaching ----------------------------------------------------------
    def teach(self, concept: Concept, vary: int = 0, style: str | None = None) -> dict:
        state = self._learner()
        profile = state.get("profile", {})
        # An explicit style (e.g. the live dropdown in the UI) wins over the
        # persisted profile so the selector takes effect without a disk round-trip.
        explicit_style = style is not None
        if style is None:
            style = profile.get("style", "example")
        # Stuck-aware strategy rotation (OmniScientist: null result -> re-ideate).
        # When the trace shows repeated failed attempts on this concept, the
        # current style is exactly what already failed - advance to the next.
        rotated = False
        rotation_reason = ""
        if not explicit_style:
            try:
                from expert_anything.core.learner import is_stuck
                if is_stuck(state, concept.name):
                    nxt = _next_style(style)
                    try:
                        from expert_anything.core.learner import (
                            style_rotation_hint,
                        )

                        style, rotation_reason = style_rotation_hint(
                            state, style, nxt, STYLES
                        )
                    except Exception:
                        style = nxt
                    rotated = True
            except Exception:
                pass
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))
        # Ground every generation in THIS concept's own relations so different
        # concepts produce genuinely different lessons (not one shared template).
        relations = _neighbor_context(self.asset, concept)
        goal = profile.get("goal", "理解这份知识资产")
        learned = self._learned_context()
        recent = [r for r in self._recent_lessons if r.get("name") != concept.name]
        if self.llm is not None:
            base_user = _teach_user(
                goal=goal,
                baseline=profile.get("baseline", "不确定"),
                style=style,
                name=concept.name,
                definition=concept.definition or concept.summary,
                evidence=evidence,
                relations=relations,
                context=learned,
                recent=recent,  # recent is defined earlier in teach()
                vary=vary,
            )
            # Bounded retry budget (2 attempts, mirroring OmniScientist's max-2
            # fallbacks): attempt 1 normal; attempt 2 quotes the exact admission
            # failure so the model knows what to fix.
            for attempt in (1, 2):
                try:
                    suffix = ""
                    if attempt > 1 and self._last_check_fail:
                        suffix = (
                            f"\n\n注意:你上一次的输出未通过系统代码校验,原因:{self._last_check_fail}。"
                            f"必须修正:请紧扣本概念「{concept.name}」自己的原文证据与关系重写,"
                            f"加入直觉性讲解(为什么重要/解决什么困惑),严禁与其他概念雷同的模板套话。"
                        )
                    content = self.llm.chat(
                        [
                            Message("system", _teach_system(style)),
                            Message("user", base_user + suffix),
                        ],
                        # a fresh angle (vary>0) asks for a different example, so give
                        # the sampler more room to diverge from the canonical one.
                        temperature=0.4 if vary == 0 else 0.7,
                        json_mode=True,
                        max_tokens=900,
                    )
                    data = _tolerant_json(content)
                    if not data:
                        _degraded("teach.parse", "LLM 返回空或非 JSON 内容")
                        break

                    def _text(v, default=""):
                        return str(v).strip() if v is not None else default

                    def _steps(v):
                        if isinstance(v, list):
                            return [str(s) for s in v if str(s).strip()]
                        if isinstance(v, str) and v.strip():
                            return [s.strip() for s in v.splitlines() if s.strip()]
                        return []

                    lesson = {
                        "concept": concept.name,
                        "style": style,
                        "explanation": _text(data.get("explanation"), concept.definition or concept.summary),
                        "example": _text(data.get("example")),
                        "analogy": _text(data.get("analogy")),
                        "connected": _text(data.get("connected")),
                        "cross_link": data.get("cross_link") if isinstance(data.get("cross_link"), dict) else None,
                        "steps": _steps(data.get("steps")),
                        "practice": _text(data.get("practice"), "用自己的话解释这个概念,并指出原文依据。"),
                        "evidence": concept.evidence,
                        "definition": concept.definition or concept.summary or "",
                    }
                    # Code-enforced admission (OmniScientist-style check): the
                    # prompt's 铁律 is a request; this is enforcement.
                    verdict = checks.check_lesson(concept, lesson, recent=recent)
                    if not verdict:
                        self._last_check_fail = verdict.reason
                        continue  # retry once with the failure quoted back
                    self._last_check_fail = ""
                    lesson["explanation"] = checks.temper_claims(lesson["explanation"])
                    lesson["analogy"] = checks.temper_claims(lesson["analogy"])
                    if rotated:
                        lesson["rotated_style"] = True
                        if rotation_reason:
                            lesson["rotation_reason"] = rotation_reason
                    # Knowledge decoding: every style gets a SceneSpec →
                    # step-by-step animation + interactive ordering game. The
                    # visual scene is a core part of the learning experience,
                    # not just a "diagram style" extra. We try the LLM-driven
                    # spec first; if it fails checks, the deterministic
                    # relation-graph fallback guarantees a valid scene.
                    lesson["scene"] = (
                        self._decode_scene(concept)
                        or decoder.scene_for_concept(self.asset, concept)
                    )
                    self._remember_lesson(lesson)
                    return self.enrich(lesson, concept, state)
                except Exception:
                    # Network/JSON/parse failure → retrying won't help; fall
                    # back to the deterministic, style-aware stub rather than
                    # crashing the lesson render (fallback is explicitly marked).
                    break
        # Normalize style to canonical code (handles legacy Chinese literals from
        # existing learner profiles or tests that haven't migrated yet).
        if style not in STYLE_CODES:
            style = _LEGACY_STYLE_MAP.get(style, "example")
        # deterministic fallback - used when no LLM is reachable. Every field is
        # grounded in THIS concept's own definition / evidence / relations so that
        # different concepts produce genuinely different lessons.
        #
        # Cognitive structure (what → why → how → connected):
        #   1. what      — definition + core attributes
        #   2. why       — significance / what problem it solves
        #   3. how       — how it works / steps to use it
        #   4. connected — relations to other concepts (with semantic types)
        ev_list = list(concept.evidence or [])
        ev0 = ev_list[0] if ev_list else (concept.definition or concept.summary or "")
        defs = concept.definition or concept.summary or "(请阅读原文获取定义)"
        rel_lines = [ln for ln in (relations.splitlines() if relations else [])
                     if ln.strip() and "暂无" not in ln]
        rel_first = rel_lines[0] if rel_lines else ""

        # Gather relation neighbours with semantic classification
        from expert_anything.core.decoder import classify_relation, REL_SEMANTICS
        neighbours: list[dict] = []
        for r in (self.asset.relations or []):
            other = None
            direction = ""
            if r.source == concept.id:
                other = self.asset.concept_by_id(r.target)
                direction = "out"
            elif r.target == concept.id:
                other = self.asset.concept_by_id(r.source)
                direction = "in"
            if other is None:
                continue
            sem = classify_relation(r.label or "", r.type or "")
            sem_label = REL_SEMANTICS.get(sem, {}).get("label", "关联")
            neighbours.append({
                "name": other.name, "id": other.id, "label": r.label or "",
                "sem": sem, "sem_label": sem_label, "direction": direction,
            })
            if len(neighbours) >= 5:
                break

        def _clip(s: str, n: int = 46) -> str:
            s = s or ""
            return s[:n] + ("..." if len(s) > n else "")

        # Build "what" block — definition + key attributes
        what_text = defs
        if ev_list:
            what_text += f"\n\n原文证据：「{_clip(ev0, 80)}」"

        # Build "why" block — extract the *problem* this concept solves,
        # not just restate the definition. Use relation semantics to infer
        # significance: if it "causes" X, the why is about X; if it's a
        # "prerequisite" for Y, the why is about enabling Y; if it's
        # "part_of" Z, the why is about Z needing this piece.
        why_text = ""
        if defs and len(defs) > 10:
            # Try to extract the "problem" from definition heuristics:
            # look for purpose clues (为了/用于/目的是/解决/确保/使得)
            purpose = ""
            for marker in ["为了", "用于", "目的是", "解决", "确保", "使得", "以便"]:
                if marker in defs:
                    idx = defs.index(marker) + len(marker)
                    purpose = defs[idx:idx + 50].strip()
                    break
            if not purpose and len(defs) > 20:
                # No explicit purpose marker — take the second half of the
                # definition (often the "so that..." part in Chinese defs)
                mid = len(defs) // 2
                purpose = defs[mid:mid + 50].strip()

            # Enrich with relation-derived significance
            rel_significance = ""
            if neighbours:
                causes = [n["name"] for n in neighbours if n["sem"] == "causes"]
                prereqs = [n["name"] for n in neighbours if n["sem"] == "prereq"]
                parts = [n["name"] for n in neighbours if n["sem"] == "part_of"]
                bits = []
                if causes:
                    bits.append(f"它导致了「{'、'.join(causes[:2])}」")
                if prereqs:
                    bits.append(f"它是「{'、'.join(prereqs[:2])}」的前提")
                if parts:
                    bits.append(f"它是「{'、'.join(parts[:2])}」的组成部分")
                if bits:
                    rel_significance = "；".join(bits)

            why_lines = [f"为什么需要「{concept.name}」？"]
            if purpose:
                why_lines.append(f"它要解决的问题是：{_clip(purpose, 60)}")
            elif rel_significance:
                why_lines.append(f"从它的关系来看：{rel_significance}")
            else:
                why_lines.append(f"从定义来看：{_clip(defs, 60)}")
            if rel_significance and purpose:
                why_lines.append(f"同时，{rel_significance}")
            why_lines.append("试着想一想：如果没有它，整个体系会缺什么？")
            why_text = "\n".join(why_lines)

        # Build "how" block — steps to understand/apply
        how_steps = [
            f"在原文里定位「{concept.name}」的定义句",
        ]
        if ev_list:
            how_steps.append(f"读它的关键证据：「{_clip(ev0)}」")
        if rel_first:
            how_steps.append(f"对照它的关系——{rel_first}——理解它在整体中的位置")
        how_steps += [
            f"用你自己的话把「{concept.name}」讲给一个外行听",
            f"在「{goal}」里找一个能用上它的具体环节并写下来",
            f"自检：抽掉「{concept.name}」，这一步还成立吗？",
        ]

        # Build "connected" block — semantic relation summary
        connected_text = ""
        if neighbours:
            by_sem: dict[str, list[str]] = {}
            for nb in neighbours:
                by_sem.setdefault(nb["sem_label"], []).append(nb["name"])
            parts = []
            for sem_label, names in by_sem.items():
                parts.append(f"• {sem_label}：{'、'.join(names[:3])}")
            connected_text = "\n".join(parts)

        # Build analogy prompt
        analogy_text = ""
        if defs and len(defs) > 15:
            analogy_text = (
                f"如果把「{concept.name}」比作一个日常事物，它像什么？\n"
                f"试着找一个类比，帮助你快速记住它的核心特征。"
            )

        # Style-specific emphasis
        if style == "diagram":
            # Diagram style: visual structure is primary
            return self.enrich({
                "concept": concept.name, "style": style,
                "cross_link": None,
                **({"rotated_style": True,
                   "rotation_reason": rotation_reason}
                  if rotated else {}),
                "scene": decoder.scene_for_concept(self.asset, concept),
                "explanation": f"{what_text}\n\n{why_text}" if why_text else what_text,
                "analogy": analogy_text,
                "connected": connected_text,
                "example": (
                    f"看结构图：居中的是「{concept.name}」。"
                    f"连线颜色表示不同的关系类型——绿色是组成关系，蓝色是分类关系，"
                    f"红色是因果关系，紫色是前提关系，橙色是对比关系。"
                    f"\n数一数：它有几种关系？分别和谁有关？"
                ),
                "steps": how_steps,
                "practice": f"用自己的话说明「{concept.name}」和哪些概念有关，分别是什么关系。",
                "evidence": concept.evidence,
                "definition": defs,
            }, concept, state)

        if style == "steps":
            # Steps style: procedural understanding is primary
            return self.enrich({
                "concept": concept.name, "style": style,
                "cross_link": None,
                **({"rotated_style": True,
                   "rotation_reason": rotation_reason}
                  if rotated else {}),
                "explanation": f"{what_text}\n\n{why_text}" if why_text else what_text,
                "analogy": analogy_text,
                "connected": connected_text,
                "scene": decoder.scene_for_concept(self.asset, concept),
                "example": (
                    f"以《{self.asset.title}》为例，「{concept.name}」的原文证据是：「{ev0}」。"
                    f"把它放进你的目标「{goal}」——哪个具体环节会用到它？"
                ),
                "steps": how_steps,
                "practice": f"列出使用「{concept.name}」的 3 个具体步骤，并说明每一步为什么需要它。",
                "evidence": concept.evidence,
                "definition": defs,
            }, concept, state)

        # default: example style
        ev_explanation = what_text
        if why_text:
            ev_explanation += f"\n\n{why_text}"
        if ev_list and len(ev_list) > 1:
            ev_explanation += f"\n\n原文还提到：「{_clip(ev_list[1], 80)}」"
        return self.enrich({
            "concept": concept.name, "style": style,
            "cross_link": None,
            **({"rotated_style": True,
                "rotation_reason": rotation_reason}
               if rotated else {}),
            "scene": decoder.scene_for_concept(self.asset, concept),
            "explanation": ev_explanation,
            "analogy": analogy_text,
            "connected": connected_text,
            "example": (
                f"在《{self.asset.title}》里，「{concept.name}」是这样体现的：{ev0}。"
                f"把它放进你的目标「{goal}」中——具体哪个环节会用到「{concept.name}」？"
            ),
            "steps": how_steps,
            "practice": f"用自己的话解释「{concept.name}」，并指出原文中支持你回答的关键句。",
            "evidence": concept.evidence,
            "definition": defs,
        }, concept, state)

    # --- hands-on practice task ------------------------------------------------
    def generate_practice(self, concept: Concept) -> dict | None:
        """Generate a hands-on practice task for a concept.

        Technical-book style: prove / construct / write pseudo-code / design,
        grounded in the concept's evidence. Returns None without an LLM.
        """
        if self.llm is None:
            return self._fallback_practice(concept)
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))
        # Build relation context so practice tasks can test structural
        # understanding (e.g. "draw the causal chain starting from X").
        rel_lines = []
        for r in self.asset.relations or []:
            src_c = self.asset.concept_by_id(r.source)
            tgt_c = self.asset.concept_by_id(r.target)
            if not src_c or not tgt_c:
                continue
            from expert_anything.core.decoder import classify_relation, REL_SEMANTICS
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            sem_label = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["label"]
            rel_lines.append(f"- [{sem_label}] {src_c.name} {r.label or '关联'} → {tgt_c.name}")
        relations = "\n".join(rel_lines) if rel_lines else "(无关系)"
        sys_prompt = get_prompt("tutor_practice_system", default=None) or (
            "你是严格的导师。根据【概念】和【原文证据】,设计一个『动手实践任务』,"
            "让学习者通过动手真正掌握这个概念。任务类型优先:证明/构造/设计/伪代码/复现,"
            "取决于概念性质(例如命题→证明或构造反例,算法→写伪代码,架构→画流程并解释)。"
            "可以利用概念的关系网络设计跨概念的综合性任务。"
        )
        user_tmpl = get_prompt("tutor_practice_user", default=None) or (
            "概念:{name}\n定义:{defn}\n原文证据:\n{evidence}\n"
            "关系网络:\n{relations}\n\n请设计实践任务。\n"
            "只输出 JSON:{task:'任务描述(具体、可操作,60-120字)', "
            "hint:'提示(30字内,不给答案)', reference:'参考解答要点(3-5条,基于证据)'}。"
        )
        user = user_tmpl.format(
            name=concept.name,
            defn=concept.definition or concept.summary or "(无定义)",
            evidence=evidence,
            relations=relations,
        )
        try:
            for attempt in (1, 2):
                suffix = "" if attempt == 1 else (
                    "\n\n注意:你上一次的任务描述未通过校验(过短或不可操作),"
                    "请给出 60-120 字、具体可操作的任务描述。"
                )
                content = self.llm.chat(
                    [Message("system", sys_prompt + _lang_instruction()), Message("user", user + suffix)],
                    temperature=0.3,
                    max_tokens=700,
                )
                data = _tolerant_json(content)
                verdict, norm = checks.check_practice(data if isinstance(data, dict) else None)
                if verdict:
                    norm["concept"] = concept.name
                    return norm
            return self._fallback_practice(concept)
        except Exception:
            return self._fallback_practice(concept)

    def _fallback_practice(self, concept: "Concept") -> dict:
        """Deterministic practice task when LLM is unavailable.

        Generates a constructive task based on the concept's relations:
        - prereq/causes → "trace the dependency chain"
        - part_of → "decompose the parent concept"
        - is_a → "classify and contrast with siblings"
        - otherwise → "paraphrase and verify with evidence"
        """
        from expert_anything.core.decoder import classify_relation

        defn = concept.definition or concept.summary or ""
        ev_list = concept.evidence or []
        ev0 = ev_list[0] if ev_list else ""

        # Scan relations for task type
        has_prereq = False
        has_causes = False
        has_part = False
        has_is_a = False
        prereq_names: list[str] = []
        causes_names: list[str] = []
        for r in self.asset.relations or []:
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            other = None
            if r.source == concept.id:
                other = self.asset.concept_by_id(r.target)
            elif r.target == concept.id:
                other = self.asset.concept_by_id(r.source)
            if other is None:
                continue
            if sem == "prereq":
                has_prereq = True
                prereq_names.append(other.name)
            elif sem == "causes":
                has_causes = True
                causes_names.append(other.name)
            elif sem == "part_of":
                has_part = True
            elif sem == "is_a":
                has_is_a = True

        if has_causes and causes_names:
            task = (
                f"构造一个场景，说明「{concept.name}」如何导致「{causes_names[0]}」。"
                f"写出因果链条上的每一步，并标注每步的原文依据。"
            )
            hint = "从定义出发，找到因果方向，逐步推导。"
            ref = f"1. 定义：{defn[:80]}\n2. 原文证据：{ev0[:80]}\n3. 因果目标：{causes_names[0]}"
        elif has_prereq and prereq_names:
            task = (
                f"说明为什么「{prereq_names[0]}」是「{concept.name}」的前提条件。"
                f"如果缺少这个前提，「{concept.name}」还能成立吗？"
            )
            hint = "试着抽掉前提概念，看定义是否还自洽。"
            ref = f"1. 前提：{prereq_names[0]}\n2. 定义：{defn[:80]}\n3. 原文证据：{ev0[:80]}"
        elif has_part:
            task = (
                f"画出「{concept.name}」所属的更大概念的组成结构，"
                f"标注「{concept.name}」在其中的位置和职责。"
            )
            hint = "先找上级概念，再列同级组成部分。"
            ref = f"1. 定义：{defn[:80]}\n2. 原文证据：{ev0[:80]}"
        elif has_is_a:
            task = (
                f"找一个与「{concept.name}」同类的概念，对比它们的定义差异、"
                f"各自独有的关系、以及共同点。"
            )
            hint = "在知识图谱中找 is-a 兄弟节点。"
            ref = f"1. 定义：{defn[:80]}\n2. 原文证据：{ev0[:80]}"
        else:
            task = (
                f"用你自己的话重新定义「{concept.name}」，"
                f"然后对照原文证据，标注你的定义中哪些有原文支撑、哪些是你的推测。"
            )
            hint = "先写定义，再逐句找原文依据。"
            ref = f"1. 原文定义：{defn[:80]}\n2. 原文证据：{ev0[:80]}"

        return {
            "task": task,
            "hint": hint,
            "reference": ref,
            "concept": concept.name,
        }

    def evaluate_practice(self, concept: Concept, task: str, answer: str) -> dict:
        """Evaluate a practice submission (score + feedback + reference)."""
        if self.llm is None:
            return self._fallback_evaluate_practice(concept, task, answer)
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))
        sys_prompt = get_prompt("tutor_evaluate_system", default=None) or (
            "你是严格的导师,评估学习者完成的实践任务。对照任务要求与原文证据判断,"
            "不因为回答长就给高分。"
        )
        user_tmpl = get_prompt("tutor_evaluate_user", default=None) or (
            "概念：{name}\n定义：{definition}\n原文证据：\n{evidence}\n\n"
            "实践任务：{task}\n\n"
            "学习者作答：{answer}\n\n请评估。\n"
            "输出 JSON：{{score: 0-1, feedback: 中文点评（指出对错与缺漏，60字内），"
            "reference: 参考解答要点（3-5条）}}。"
        )
        task_block = f"实践任务：{task}\n\n" if task else ""
        user = user_tmpl.format(
            name=concept.name,
            definition=concept.definition or concept.summary or "",
            evidence=evidence,
            task_block=task_block,
            answer=(answer or "(未作答)")[:1200],
        )
        try:
            content = self.llm.chat(
                [Message("system", sys_prompt + _lang_instruction()), Message("user", user)],
                temperature=0.2,
                max_tokens=700,
            )
            data = _tolerant_json(content)
            score = max(0.0, min(1.0, float(data.get("score", 0.0))))
            return {
                "score": round(score, 2),
                "feedback": str(data.get("feedback", "")),
                "reference": str(data.get("reference", "")),
            }
        except Exception:
            return self._fallback_evaluate_practice(concept, task, answer)

    def _fallback_evaluate_practice(self, concept: "Concept", task: str, answer: str) -> dict:
        """Keyword-matching fallback for practice evaluation.

        Checks how many key terms from the concept's definition, evidence,
        and relation neighbours appear in the learner's answer, plus whether
        the answer has substantive length. Not a real evaluation, but better
        than a fixed 0.5 score that pollutes mastery tracking.
        """
        import re as _re

        key_terms: set[str] = set()
        _stop = {"的", "了", "是", "在", "和", "与", "或", "为", "以", "及",
                 "the", "a", "an", "is", "are", "of", "to", "in", "for", "and", "or", "it", "this", "that"}
        defn = concept.definition or concept.summary or ""
        for m in _re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", defn):
            if m.lower() not in _stop:
                key_terms.add(m)
        for ev in concept.evidence or []:
            for m in _re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", ev):
                if m.lower() not in _stop:
                    key_terms.add(m)
        for r in self.asset.relations or []:
            other_id = r.target if r.source == concept.id else (r.source if r.target == concept.id else None)
            if other_id:
                other = self.asset.concept_by_id(other_id)
                if other and other.name and len(other.name) >= 2:
                    key_terms.add(other.name)

        ans_lower = answer.lower()
        ans_len = len(answer.strip())
        # Length factor: very short answers get a penalty
        length_factor = min(1.0, ans_len / 80.0) if ans_len > 0 else 0.0

        if key_terms:
            hits = sum(1 for t in key_terms if t.lower() in ans_lower)
            ratio = hits / len(key_terms)
            # Combine keyword hit ratio with length factor
            score = round(max(0.1, min(0.85, 0.15 + ratio * 0.55 + length_factor * 0.15)), 2)
            missed = [t for t in sorted(key_terms) if t.lower() not in ans_lower][:5]
            feedback = (
                f"(未接入 LLM,基于关键术语匹配的粗略评估。"
                f"命中 {hits}/{len(key_terms)} 个关键术语。)"
                + (f"\n可能遗漏的要点：{'、'.join(missed)}" if missed else "")
            )
        else:
            score = round(max(0.1, 0.2 + length_factor * 0.5), 2)
            feedback = "(未接入 LLM,基于回答长度的粗略估计,不是真实评估。)"

        return {
            "score": score,
            "feedback": feedback,
            "reference": defn,
        }

    def _learned_context(self) -> str:
        """Concepts the learner already mastered in OTHER assets (cross-book
        anchors for personalised teaching)."""
        state = self._learner()
        concepts = state.get("concepts", {})
        assets = state.get("assets", {})
        lines = []
        for key, rec in concepts.items():
            try:
                if float(rec.get("mastery", 0.0)) < 0.6:
                    continue
            except (TypeError, ValueError):
                continue
            for s in rec.get("sources", []) or []:
                if s != self.asset.asset_id:
                    title = assets.get(s, {}).get("title", s)
                    lines.append(f"- {rec.get('name', key)}(来自《{title}》)")
                    break
        return "\n".join(lines) if lines else "(无)"

    # --- quick self-test -------------------------------------------------------
    def generate_quiz(self, concept: Concept, qtype: str = "") -> dict | None:
        """Generate a quick self-test for a concept.

        ``qtype`` alternates "true_false" / "ordering"; empty picks by a
        simple counter. Returns None when no LLM is configured. Payload:
          true_false: {type, question, correct(bool), explanation}
          ordering:   {type, question, options[list], correct_order[list], explanation}
        """
        if self.llm is None:
            return self._fallback_quiz(concept, qtype)
        qtype = qtype or (["true_false", "ordering"][getattr(self, "_quiz_i", 0) % 2])
        self._quiz_i = getattr(self, "_quiz_i", 0) + 1

        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))

        # Build relation context so quiz questions can test structural
        # understanding (e.g. "which concept is a prerequisite for X?")
        # rather than only definition recall.
        rel_lines = []
        for r in self.asset.relations or []:
            src_c = self.asset.concept_by_id(r.source)
            tgt_c = self.asset.concept_by_id(r.target)
            if not src_c or not tgt_c:
                continue
            from expert_anything.core.decoder import classify_relation, REL_SEMANTICS
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            sem_label = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["label"]
            rel_lines.append(f"- [{sem_label}] {src_c.name} {r.label or '关联'} → {tgt_c.name}")
        relations = "\n".join(rel_lines) if rel_lines else "(无关系)"

        if qtype == "ordering":
            sys_prompt = get_prompt("tutor_quiz_ordering_system", default=None) or (
                "你是严格的导师。根据【概念】和【原文证据】,设计一道「步骤排序」自测题。"
                "把该概念的关键流程/逻辑步骤打乱顺序,让学习者重排。"
                "如果有前提/因果关系,可以基于这些关系的顺序出题。"
            )
            user_tmpl = get_prompt("tutor_quiz_ordering_user", default=None) or (
                "概念:{name}\n定义:{defn}\n原文证据:\n{evidence}\n"
                "关系网络:\n{relations}\n\n请生成步骤排序题。\n"
                "只输出 JSON:{type:'ordering', question:'题目', "
                "options:['步骤A','步骤B',...](乱序), correct_order:[正确顺序的选项索引], "
                "explanation:'基于证据的解释'}。步骤 3-5 个,必须来自原文。"
            )
        else:
            sys_prompt = get_prompt("tutor_quiz_truefalse_system", default=None) or (
                "你是严格的导师。根据【概念】和【原文证据】,设计一道「判断正误」自测题。"
                "给出一个关于该概念的陈述,学习者判断对错。"
                "可以基于概念的关系出题（如判断两个概念之间的关系类型是否正确）。"
            )
            user_tmpl = get_prompt("tutor_quiz_truefalse_user", default=None) or (
                "概念:{name}\n定义:{defn}\n原文证据:\n{evidence}\n"
                "关系网络:\n{relations}\n\n请生成判断题。\n"
                "只输出 JSON:{type:'true_false', question:'陈述', correct:true或false, "
                "explanation:'基于证据的解释'}。陈述必须能由证据直接判定,不许模棱两可。"
            )
        user = user_tmpl.format(
            name=concept.name,
            defn=concept.definition or concept.summary or "(无定义)",
            evidence=evidence,
            relations=relations,
        )
        try:
            for attempt in (1, 2):
                suffix = "" if attempt == 1 else (
                    "\n\n注意:你上一次的题目未通过结构校验。判断题必须给出可解析的 true/false;"
                    "排序题必须给出 3-6 个选项,且 correct_order 是 0..n-1 的一个排列。"
                )
                content = self.llm.chat(
                    [Message("system", sys_prompt + _lang_instruction()), Message("user", user + suffix)],
                    temperature=0.3,
                    max_tokens=700,
                )
                data = _tolerant_json(content)
                verdict, norm = checks.check_quiz(data if isinstance(data, dict) else None)
                if verdict and norm is not None:
                    norm["concept"] = concept.name
                    return norm
            return self._fallback_quiz(concept, qtype)
        except Exception:
            return self._fallback_quiz(concept, qtype)

    def _fallback_quiz(self, concept: "Concept", qtype: str = "") -> dict:
        """Deterministic quiz fallback when LLM is unavailable.

        Builds an ordering quiz from prereq/causes relation chains so the
        learner is tested on structural understanding, not just definition
        recall. Falls back to a true_false quiz from evidence when there
        are not enough ordering relations.
        """
        from expert_anything.core.decoder import classify_relation

        asset = self.asset
        # Try to build an ordering quiz from prereq/causes chains
        chain: list[str] = [concept.name]
        for r in asset.relations or []:
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            if sem in ("prereq", "causes") and r.source == concept.id:
                other = asset.concept_by_id(r.target)
                if other and other.name not in chain:
                    chain.append(other.name)
            elif sem in ("prereq", "causes") and r.target == concept.id:
                other = asset.concept_by_id(r.source)
                if other and other.name not in chain:
                    chain.insert(0, other.name)
            if len(chain) >= 5:
                break

        if len(chain) >= 3:
            import random
            rng = random.Random(hash(concept.name) & 0xFFFFFFFF)
            perm = list(range(len(chain)))
            rng.shuffle(perm)
            shuffled = [chain[i] for i in perm]
            answer = [perm.index(j) for j in range(len(chain))]
            return {
                "type": "ordering",
                "question": f"把下列概念按从基础到进阶的逻辑顺序排列（以「{concept.name}」为中心）",
                "options": shuffled,
                "correct_order": answer,
                "explanation": "顺序基于前提/因果关系链",
                "concept": concept.name,
            }

        # Not enough relations for ordering — build a true_false from evidence
        ev_list = concept.evidence or []
        if ev_list:
            import random
            rng = random.Random(hash(concept.name) & 0xFFFFFFFF)
            ev = rng.choice(ev_list)
            # 50% chance: true statement (evidence as-is) vs negated
            negate = rng.random() < 0.5
            if negate:
                question = f"判断正误：以下说法是错误的——{ev[:60]}"
                correct = False
            else:
                question = f"判断正误：以下说法正确——{ev[:60]}"
                correct = True
            return {
                "type": "true_false",
                "question": question,
                "correct": correct,
                "explanation": f"原文证据：{ev[:80]}",
                "concept": concept.name,
            }

        # Last resort
        return {
            "type": "true_false",
            "question": f"判断正误：「{concept.name}」的定义如原文所述",
            "correct": True,
            "explanation": "请查阅原文确认",
            "concept": concept.name,
        }

    def check_quiz(self, quiz: dict, answer) -> tuple[float, str]:
        """Score an answer against a generated quiz.

        Returns (score 0..1, feedback). true_false: right/wrong.
        ordering: fraction of items placed correctly.
        """
        qtype = quiz.get("type")
        if qtype == "true_false":
            ok = bool(answer) == bool(quiz.get("correct"))
            return (1.0 if ok else 0.2), quiz.get("explanation", "")
        if qtype == "ordering":
            correct = quiz.get("correct_order", [])
            if not correct or len(answer) != len(correct):
                return 0.0, quiz.get("explanation", "")
            hits = sum(1 for a, c in zip(answer, correct) if a == c)
            return round(hits / len(correct), 2), quiz.get("explanation", "")
        return 0.0, quiz.get("explanation", "")

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
            return self._fallback_followup(concept, question, lesson)
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))
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
                f"学习者问:{q}\n导师答:{a}" for q, a in history[-2:]
            )
        user = (
            "概念定义:{defn}\n"
            "原文证据:\n{evidence}\n"
            "关系网络:\n{relations}\n\n"
            "已有讲解:\n{lesson}\n\n"
            "最近对话:\n{hist}\n\n"
            "学习者追问:{question}\n\n请回答。"
        ).format(
            defn=concept.definition or concept.summary or "(无定义)",
            evidence=evidence,
            relations=relations,
            lesson=lesson_txt or "(无)",
            hist=hist_txt or "(无)",
            question=question.strip(),
        )
        try:
            return self.llm.chat(
                [
                    Message("system", FOLLOWUP_SYSTEM.format(
                        title=self.asset.title, name=concept.name) + _lang_instruction()),
                    Message("user", user),
                ],
                temperature=0.4,
                max_tokens=500,
            )
        except (LLMNotConfigured, LLMError):
            return self._fallback_followup(concept, question, lesson)

    def _fallback_followup(self, concept: "Concept", question: str,
                           lesson: dict | None = None) -> str:
        """Deterministic follow-up answer when LLM is unavailable.

        Instead of a hardcoded placeholder, builds a structured answer from
        the concept's definition, evidence, and relation network so the
        learner gets at least some grounding information.
        """
        from expert_anything.core.decoder import classify_relation, REL_SEMANTICS

        parts: list[str] = []

        # 1. Definition
        defn = concept.definition or concept.summary or ""
        if defn:
            parts.append(f"【定义】{defn}")

        # 2. Evidence
        ev_list = concept.evidence or []
        if ev_list:
            parts.append(f"【原文证据】{ev_list[0][:120]}")

        # 3. Relation summary by semantic type
        by_sem: dict[str, list[str]] = {}
        for r in self.asset.relations or []:
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            other = None
            if r.source == concept.id:
                other = self.asset.concept_by_id(r.target)
            elif r.target == concept.id:
                other = self.asset.concept_by_id(r.source)
            if other:
                sem_label = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["label"]
                by_sem.setdefault(sem_label, []).append(other.name)

        if by_sem:
            rel_parts = []
            for sem_label, names in by_sem.items():
                rel_parts.append(f"{sem_label}：{'、'.join(names[:3])}")
            parts.append(f"【关系网络】{'；'.join(rel_parts)}")

        # 4. Lesson context if available
        if lesson and lesson.get("explanation"):
            parts.append(f"【教学要点】{str(lesson['explanation'])[:100]}")

        # 5. Question echo
        parts.append(f"\n关于「{question}」——以上是基于原文和知识模型的结构化参考。"
                     "配置 API Key 后可获得对话式追问。")

        return "\n\n".join(parts)

    # --- evaluation --------------------------------------------------------
    def evaluate(self, concept: Concept, answer: str) -> dict:
        evidence = "\n".join(f"- {e}" for e in (concept.evidence or ["(无原文证据)"]))
        # Build relation context so evaluation can assess whether the
        # learner understands the concept's position in the network, not
        # just whether they can recite the definition.
        rel_lines = []
        for r in self.asset.relations or []:
            src_c = self.asset.concept_by_id(r.source)
            tgt_c = self.asset.concept_by_id(r.target)
            if not src_c or not tgt_c:
                continue
            from expert_anything.core.decoder import classify_relation, REL_SEMANTICS
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            sem_label = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["label"]
            rel_lines.append(f"- [{sem_label}] {src_c.name} {r.label or '关联'} → {tgt_c.name}")
        relations = "\n".join(rel_lines) if rel_lines else "(无关系)"
        if self.llm is not None:
            try:
                ev_sys = get_prompt("tutor_evaluate_system", default=None)  # type: ignore[attr-defined]
                ev_usr = get_prompt("tutor_evaluate_user", default=None)  # type: ignore[attr-defined]
                content = self.llm.chat(
                    [
                        Message("system", (ev_sys if ev_sys else EVALUATE_SYSTEM) + _lang_instruction()),
                        Message(
                            "user",
                            (ev_usr if ev_usr else EVALUATE_USER).format(
                                name=concept.name,
                                definition=concept.definition or concept.summary,
                                evidence=evidence,
                                relations=relations,
                                task_block="",
                                answer=answer or "(学习者未作答)",
                            ),
                        ),
                    ],
                    temperature=0.2,
                    json_mode=True,
                    max_tokens=500,
                )
                data = _tolerant_json(content)
                if not data:
                    _degraded("evaluate.parse", "LLM 返回空或非 JSON 内容")
                    raise LLMError("LLM 返回空或非 JSON 内容")
                score = max(0.0, min(1.0, float(data.get("score", 0.0))))
                feedback = str(data.get("feedback", ""))
                # Cross-judge arbitration: only boundary-band scores (the
                # most uncertain verdicts) pay for a second, independently
                # framed evaluation; the two scores are averaged.
                judges = 1
                lo, hi = JUDGE_BOUNDARY
                if lo <= score < hi:
                    try:
                        arb_sys = get_prompt("tutor_arbiter_system", default=None)  # type: ignore[attr-defined]
                        arb_usr = get_prompt("tutor_arbiter_user", default=None)  # type: ignore[attr-defined]
                        content2 = self.llm.chat(
                            [
                                Message("system", (arb_sys if arb_sys else ARBITER_SYSTEM) + _lang_instruction()),
                                Message(
                                    "user",
                                    (arb_usr if arb_usr else ARBITER_USER).format(
                                        name=concept.name,
                                        definition=concept.definition or concept.summary,
                                        evidence=evidence,
                                        relations=relations,
                                        answer=answer or "(学习者未作答)",
                                    ),
                                ),
                            ],
                            temperature=0.1,
                            json_mode=True,
                            max_tokens=200,
                        )
                        d2 = _tolerant_json(content2)
                        if "score" not in d2:
                            raise ValueError("arbiter returned no score")
                        s2 = max(0.0, min(1.0, float(d2.get("score"))))
                        score = round((score + s2) / 2.0, 2)
                        judges = 2
                        note = str(d2.get("note", "")).strip()
                        if note:
                            feedback = (
                                f"{feedback}(复核:{note})" if feedback else f"复核:{note}"
                            )
                    except Exception:
                        # Second judge unavailable/unparseable → the first
                        # verdict stands alone (bounded budget: no retry
                        # loop here, the evaluation must not stall).
                        pass
                # Admission check: clamp is idempotent, but it also guarantees a
                # non-empty feedback so the UI never renders a silent result.
                _v, norm = checks.check_evaluation({
                    "score": score,
                    "feedback": feedback,
                })
                return {
                    "score": norm.get("score", round(score, 2)),
                    "understood": (
                        score >= 0.6 if judges == 2
                        else bool(data.get("understood", score >= 0.6))
                    ),
                    "feedback": norm.get("feedback", "已记录你的回答。"),
                    "reference": (data.get("reference") or "").strip(),
                    "gap": (data.get("gap") or "").strip(),
                    "judges": judges,
                }
            except (LLMNotConfigured, LLMError, ValueError, KeyError):
                # Network/JSON/parse failure → fall back to the length heuristic.
                pass
        # keyword-matching fallback: extract key terms from the concept's
        # definition, evidence, and relation neighbours, then check how
        # many appear in the learner's answer. This is a rough proxy for
        # understanding — not a real evaluation — but far better than
        # answer-length heuristics.
        import re as _re
        key_terms: set[str] = set()
        # definition terms (≥2 chars, not stopwords)
        _stop = {"的", "了", "是", "在", "和", "与", "或", "为", "以", "及",
                 "the", "a", "an", "is", "are", "of", "to", "in", "for", "and", "or", "it", "this", "that"}
        defn = concept.definition or concept.summary or ""
        for m in _re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", defn):
            if m.lower() not in _stop:
                key_terms.add(m)
        # evidence terms
        for ev in concept.evidence or []:
            for m in _re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", ev):
                if m.lower() not in _stop:
                    key_terms.add(m)
        # relation neighbour names
        for r in self.asset.relations or []:
            other_id = r.target if r.source == concept.id else (r.source if r.target == concept.id else None)
            if other_id:
                other = self.asset.concept_by_id(other_id)
                if other and other.name and len(other.name) >= 2:
                    key_terms.add(other.name)
        # check how many key terms appear in the answer
        ans_lower = answer.lower()
        if key_terms:
            hits = sum(1 for t in key_terms if t.lower() in ans_lower)
            ratio = hits / len(key_terms)
            score = round(max(0.2, min(0.9, 0.2 + ratio * 0.7)), 2)
            missed = [t for t in sorted(key_terms) if t.lower() not in ans_lower][:5]
            feedback = (
                f"(未接入 LLM,基于关键术语匹配的粗略估计。"
                f"命中 {hits}/{len(key_terms)} 个关键术语。)"
                + (f"\n可能遗漏的要点：{'、'.join(missed)}" if missed else "")
            )
        else:
            # no key terms available — fall back to length
            words = len(answer.strip())
            score = 0.3 if words < 5 else (0.6 if words < 30 else 0.8)
            feedback = "(未接入 LLM,基于回答长度的粗略估计,不是真实评估。)"
        return {
            "score": score,
            "understood": score >= 0.6,
            "feedback": feedback,
            "reference": defn,
            "gap": "",
        }
