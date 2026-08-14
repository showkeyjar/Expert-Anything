"""Teacher Model — the system's own evolving understanding of an asset.

This is the "self-learning" layer. It is deliberately distinct from the
Learner Model (which tracks *what the student knows*). The Teacher Model
tracks what *the system has figured out*: a deeper, source-grounded
understanding of each concept plus a living list of anomalies / open
questions it has detected in the material.

Why this exists: a teaching navigator must stand *ahead* of the student.
It cannot merely echo a one-shot extraction skeleton. After import it
runs a self-learning pass that (1) enriches every concept with
significance, prerequisites, common misconceptions and connections, and
(2) scans the source + model for contradictions, undefined terms, logical
gaps and surprising claims. The result is persisted and the teaching
session navigates by it — surfacing "things the system is still unsure
about" as explicit exploration tasks instead of pretending omniscience.

External knowledge: when the source is thin, the model is allowed to bring
in well-established background to fill gaps, but such content is *labelled*
(source="external") so the source-grounding guarantee is never silently
broken.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from expert_anything.core.llm import LLMClient, Message, chat_json
from expert_anything.core.models import KnowledgeAsset


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# Data models (round-trip to JSON)
# --------------------------------------------------------------------------- #
@dataclass
class ConceptNote:
    concept_id: str
    name: str
    significance: str = ""          # 为什么重要
    prerequisites: list[str] = field(default_factory=list)
    misconceptions: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    external_notes: list[str] = field(default_factory=list)  # 引入的外部补充，标注来源
    learner_signals: list[str] = field(default_factory=list)  # 学生真实作答中暴露的困惑/错点
    note: str = ""                  # 系统综合理解

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "significance": self.significance,
            "prerequisites": self.prerequisites,
            "misconceptions": self.misconceptions,
            "connections": self.connections,
            "external_notes": self.external_notes,
            "learner_signals": self.learner_signals,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptNote":
        return cls(
            concept_id=d.get("concept_id", ""),
            name=d.get("name", ""),
            significance=d.get("significance", ""),
            prerequisites=d.get("prerequisites", []),
            misconceptions=d.get("misconceptions", []),
            connections=d.get("connections", []),
            external_notes=d.get("external_notes", []),
            learner_signals=d.get("learner_signals", []),
            note=d.get("note", ""),
        )


@dataclass
class Anomaly:
    id: str
    kind: str                      # contradiction | undefined_term | logical_gap | surprising_claim
    description: str
    location: str = ""            # 原文片段 / 位置
    severity: str = "medium"      # low | medium | high | info
    status: str = "open"         # open | investigating | resolved | surfaced_to_student
    resolution: str = ""
    source: str = "internal"      # internal | external

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "description": self.description,
            "location": self.location,
            "severity": self.severity,
            "status": self.status,
            "resolution": self.resolution,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Anomaly":
        return cls(
            id=d.get("id", _new_id("an")),
            kind=d.get("kind", "logical_gap"),
            description=d.get("description", ""),
            location=d.get("location", ""),
            severity=d.get("severity", "medium"),
            status=d.get("status", "open"),
            resolution=d.get("resolution", ""),
            source=d.get("source", "internal"),
        )


@dataclass
class TeacherModel:
    asset_id: str
    status: str = "pending"        # pending | done | fallback | failed
    method: str = ""
    synthesized_at: str = ""
    concept_notes: list[ConceptNote] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)

    def concept_note_by_id(self, cid: str) -> ConceptNote | None:
        return next((n for n in self.concept_notes if n.concept_id == cid), None)

    def open_anomalies(self) -> list[Anomaly]:
        return [a for a in self.anomalies if a.status in ("open", "investigating")]

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "status": self.status,
            "method": self.method,
            "synthesized_at": self.synthesized_at,
            "concept_notes": [n.to_dict() for n in self.concept_notes],
            "anomalies": [a.to_dict() for a in self.anomalies],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TeacherModel":
        return cls(
            asset_id=d.get("asset_id", ""),
            status=d.get("status", "pending"),
            method=d.get("method", ""),
            synthesized_at=d.get("synthesized_at", ""),
            concept_notes=[ConceptNote.from_dict(x) for x in d.get("concept_notes", [])],
            anomalies=[Anomaly.from_dict(x) for x in d.get("anomalies", [])],
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_KIND_LABELS = {
    "contradiction": "矛盾",
    "undefined_term": "未定义术语",
    "logical_gap": "逻辑断点",
    "surprising_claim": "反常主张",
    "learner_gap": "学习者信号",
    "needs_llm": "需要 LLM",
}


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def _parse_json(text: str) -> dict:
    """Tolerant JSON extraction from an LLM response (strips ```json fences)."""
    if not text:
        return {}
    s = text.strip()
    # strip code fences
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # fall back: grab the outermost {...} block
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


# --------------------------------------------------------------------------- #
# LLM-driven self-learning pass
# --------------------------------------------------------------------------- #
_SYSTEM = (
    "你是‘教学导航’系统的自我认知模块。你阅读已抽取的知识模型与原文，"
    "产出比‘定义’更深一层的理解，并主动发现材料里值得警惕的异常。"
    "规则：\n"
    "1. 严格基于所给材料；只有在材料明显单薄、需要背景才能成立时，才引入公认的外部知识，"
    "且必须放进 external_notes 并视为补充，不得混入主理解。\n"
    "2. 异常检测要 conservative：只有真正矛盾/未定义/断点/明显反常才列入，不臆造。\n"
    "3. 只输出 JSON，不要解释。"
)

_USER = (
    "以下关于《{title}》的知识模型与原文片段。请：\n"
    "(A) 对每个概念做深加工：significance(为什么重要)、prerequisites(前提)、"
    "misconceptions(常见误解)、connections(与别的概念/外部领域的连接)、"
    "note(系统综合理解，1-2 句)；若材料单薄，把可靠的外部背景放进 external_notes。\n"
    "(B) 扫描矛盾/未定义术语/逻辑断点/反常主张，逐条列出 anomaly："
    "kind 取 contradiction|undefined_term|logical_gap|surprising_claim，"
    "severity 取 low|medium|high，location 给原文片段或‘全局’。\n\n"
    "概念列表：\n{concepts}\n\n"
    "原文片段（前 4000 字）：\n{source}\n\n"
    "输出 JSON：\n"
    "{{\n"
    '  "concept_notes": [{{"name":"概念名","significance":"","prerequisites":[],'
    '"misconceptions":[],"connections":[],"external_notes":[],"note":""}}],\n'
    '  "anomalies": [{{"kind":"","description":"","location":"","severity":""}}]\n'
    "}}\n"
    "要求 concept_notes 覆盖全部概念；anomalies 无则空数组。"
)


def _build_user_prompt(asset: KnowledgeAsset) -> str:
    concept_lines = []
    for c in asset.concepts:
        ev = "；".join(c.evidence[:1]) if c.evidence else "（无证据）"
        concept_lines.append(
            f"- {c.name}：{c.definition or c.summary or '（无定义）'} ｜ 证据：{ev}"
        )
    concepts_block = "\n".join(concept_lines) if concept_lines else "（无概念）"
    source_snippet = asset.source_text[:4000]
    return _USER.format(
        title=asset.title,
        concepts=concepts_block,
        source=source_snippet,
    )


def _assemble(asset: KnowledgeAsset, data: dict, method: str) -> TeacherModel:
    name_to_id = {c.name.strip().lower(): c.id for c in asset.concepts}
    notes: list[ConceptNote] = []
    for c in data.get("concept_notes", []):
        name = (c.get("name") or "").strip()
        cid = name_to_id.get(name.lower(), "")
        if not cid:
            # concept name may have drifted; best-effort match by inclusion
            cid = next(
                (cc.id for cc in asset.concepts if cc.name.lower() in name.lower() or name.lower() in cc.name.lower()),
                "",
            )
        if not cid:
            continue
        notes.append(
            ConceptNote(
                concept_id=cid,
                name=name,
                significance=(c.get("significance") or "").strip(),
                prerequisites=[x for x in (c.get("prerequisites") or []) if str(x).strip()],
                misconceptions=[x for x in (c.get("misconceptions") or []) if str(x).strip()],
                connections=[x for x in (c.get("connections") or []) if str(x).strip()],
                external_notes=[x for x in (c.get("external_notes") or []) if str(x).strip()],
                note=(c.get("note") or "").strip(),
            )
        )
    # ensure every concept has at least an empty note
    seen = {n.concept_id for n in notes}
    for cc in asset.concepts:
        if cc.id not in seen:
            notes.append(ConceptNote(concept_id=cc.id, name=cc.name))

    anomalies: list[Anomaly] = []
    for a in data.get("anomalies", []):
        kind = (a.get("kind") or "logical_gap").strip()
        desc = (a.get("description") or "").strip()
        if not desc:
            continue
        anomalies.append(
            Anomaly(
                id=_new_id("an"),
                kind=kind,
                description=desc,
                location=(a.get("location") or "").strip(),
                severity=(a.get("severity") or "medium").strip(),
                status="open",
                source="internal",
            )
        )

    return TeacherModel(
        asset_id=asset.asset_id,
        status="done",
        method=method,
        synthesized_at=datetime.now(timezone.utc).isoformat(),
        concept_notes=notes,
        anomalies=anomalies,
    )


def _fallback(asset: KnowledgeAsset) -> TeacherModel:
    """No LLM: build empty notes for every concept and one informational
    anomaly telling the user that self-learning requires a key."""
    notes = [ConceptNote(concept_id=c.id, name=c.name) for c in asset.concepts]
    return TeacherModel(
        asset_id=asset.asset_id,
        status="fallback",
        method="deterministic_fallback_v1",
        synthesized_at=datetime.now(timezone.utc).isoformat(),
        concept_notes=notes,
        anomalies=[
            Anomaly(
                id=_new_id("an"),
                kind="needs_llm",
                description="未配置 LLM（EXPERTANYTHING_LLM_API_KEY）。自我学习层（概念深加工与异常检测）无法运行。配置 key 后点击「重新自检」即可生成。",
                severity="info",
                status="open",
                source="internal",
            )
        ],
    )


def build_teacher_model(
    asset: KnowledgeAsset, llm: LLMClient | None = None, on_progress=None
) -> TeacherModel:
    """Run the self-learning pass. Falls back to a marked skeleton without LLM.

    `on_progress(stage, current, total, message)` drives the UI progress bar so
    the (single) self-learning LLM call does not look like a freeze.
    """
    if llm is None:
        if on_progress:
            on_progress("selflearn", 0, 0, "未配置 LLM，跳过自我学习（可在认知导航页重新自检）")
        return _fallback(asset)
    if on_progress:
        on_progress("selflearn", 0, 0, "正在自我学习：深加工每个概念、扫描矛盾/未定义/反常…")
    try:
        # Output is one compact note per concept plus a few anomalies. Cap the
        # generation budget by concept count so a single huge call doesn't stall
        # the import for tens of seconds. chat_json retries on transient empty /
        # rate-limited responses so a burst of parallel extraction calls doesn't
        # silently kill the self-learning pass.
        max_out = max(1200, min(2500, 700 + 130 * len(asset.concepts)))
        data = chat_json(
            llm,
            [
                Message("system", _SYSTEM),
                Message("user", _build_user_prompt(asset)),
            ],
            temperature=0.3,
            max_tokens=max_out,
        )
        if not data:
            raise ValueError("empty/malformed LLM response")
        tm = _assemble(asset, data, method="teacher_self_learn_v1")
        if on_progress:
            on_progress("selflearn", 0, 0, f"自我学习完成：{len(tm.anomalies)} 条待解项")
        return tm
    except Exception:
        # Graceful degradation: never fail the import on a self-learn hiccup.
        tm = _fallback(asset)
        tm.status = "failed"
        tm.method = "llm_failed_fallback_v1"
        if on_progress:
            on_progress("selflearn", 0, 0, "自我学习调用失败，已降级（不影响导入）")
        return tm


# --------------------------------------------------------------------------- #
# Closed-loop convergence: learner answers feed back into the Teacher Model
# --------------------------------------------------------------------------- #
_REFLECT_SYSTEM = (
    "你是‘教学导航’系统的自我反思模块。系统已经对某个概念做了一轮深加工，"
    "现在一名学习者提交了练习回答并被评估。你的任务是判断：这次学习者的回答，"
    "是仅仅暴露了‘学习者个人的薄弱’，还是揭示了‘材料/讲解本身的隐患’。\n"
    "只输出 JSON，不要解释。"
)

_REFLECT_USER = (
    "概念：{name}\n定义：{definition}\n\n"
    "系统已有的常见误解预判：{miscon}\n系统已有的综合理解：{note}\n\n"
    "学习者回答：{answer}\n评估得分：{score}\n导师反馈：{feedback}\n\n"
    "请判断：\n"
    "1. 若学习者的错误指向材料/讲解本身可被改进之处（如定义含糊、缺少前提、"
    "容易产生的系统性误解未被覆盖），请在 anomaly 里给出一条系统级异常，"
    "kind 取 contradiction|undefined_term|logical_gap|surprising_claim，"
    "severity 取 low|medium|high（得分越低越可能 high），status 固定 open；"
    "否则 anomaly 为 null。\n"
    "2. 用一句话写出这种错误模式的本质 misconceptions（用于补充到概念的常见误解里）；"
    "若现有预判已覆盖则填空串。\n\n"
    "输出 JSON：\n"
    "{{\n"
    '  "anomaly": {{"kind":"","description":"","severity":""}} 或 null,\n'
    '  "misconception": ""\n'
    "}}"
)


def reflect_on_signal(
    asset: KnowledgeAsset,
    concept,  # Concept
    note: ConceptNote,
    answer: str,
    score: float,
    feedback: str,
    llm: LLMClient,
) -> dict:
    """LLM pass: turn a learner's answer into a (possibly) new system anomaly
    plus a refined misconception. Returns {anomaly: dict|None, misconception: str}."""
    content = llm.chat(
        [
            Message("system", _REFLECT_SYSTEM),
            Message(
                "user",
                _REFLECT_USER.format(
                    name=concept.name,
                    definition=concept.definition or concept.summary or "（无定义）",
                    miscon="；".join(note.misconceptions) or "（无）",
                    note=note.note or "（无）",
                    answer=answer.strip()[:600] or "（学习者未作答）",
                    score=f"{score:.2f}",
                    feedback=feedback or "（无）",
                ),
            ),
        ],
        temperature=0.2,
        json_mode=True,
        max_tokens=600,
    )
    data = _parse_json(content)
    out: dict = {"anomaly": None, "misconception": ""}
    if not data:
        return out
    an = data.get("anomaly")
    if isinstance(an, dict) and (an.get("description") or "").strip():
        out["anomaly"] = {
            "kind": (an.get("kind") or "logical_gap").strip(),
            "description": an["description"].strip(),
            "severity": (an.get("severity") or "medium").strip(),
            "status": "open",
            "source": "internal",
        }
    mc = (data.get("misconception") or "").strip()
    if mc:
        out["misconception"] = mc
    return out


def incorporate_learner_signal(
    asset: KnowledgeAsset,
    teacher: TeacherModel | None,
    concept_id: str,
    answer: str,
    score: float,
    feedback: str,
    llm: LLMClient | None = None,
) -> TeacherModel:
    """Closed-loop step: record a learner's answer as a signal in the Teacher
    Model. Always appends a `learner_gap` anomaly (so the loop is visible even
    without LLM), and — if an LLM is available — runs a reflection that may
    promote it into a real system anomaly and refine the concept's
    misconceptions. Returns the (mutated) TeacherModel; caller persists it."""
    if teacher is None:
        teacher = TeacherModel(asset_id=asset.asset_id, status="fallback", method="lazy_init")

    c = asset.concept_by_id(concept_id)
    cname = c.name if c is not None else "(未知概念)"
    note = teacher.concept_note_by_id(concept_id)
    if note is None:
        note = ConceptNote(concept_id=concept_id, name=cname)
        teacher.concept_notes.append(note)

    # 1) Always record the learner signal + a learner_gap anomaly (deterministic).
    snippet = answer.strip().replace("\n", " ")[:140]
    note.learner_signals.append(f"学习者（得分 {score:.2f}）回答片段：{snippet}")
    sev = "high" if score < 0.4 else ("medium" if score < 0.6 else "low")
    teacher.anomalies.append(
        Anomaly(
            id=_new_id("an"),
            kind="learner_gap",
            description=(
                f"学习者对「{cname}」掌握不足（评估得分 {score:.2f}）。"
                f"其回答暴露出需要补习或澄清的点，已作为教学导航的待关注信号。"
            ),
            location=cname,
            severity=sev,
            status="surfaced_to_student",
            source="internal",
        )
    )

    # 2) LLM reflection for deeper convergence (may reveal a material gap).
    if llm is not None and c is not None:
        try:
            insight = reflect_on_signal(asset, c, note, answer, score, feedback, llm)
            if insight.get("misconception"):
                mc = insight["misconception"]
                if mc not in note.misconceptions:
                    note.misconceptions.append(mc)
            an = insight.get("anomaly")
            if an:
                teacher.anomalies.append(
                    Anomaly(id=_new_id("an"), location=cname, resolution="", **an)
                )
        except Exception:
            # Reflection is best-effort; the deterministic signal already landed.
            pass

    teacher.synthesized_at = datetime.now(timezone.utc).isoformat()
    return teacher


# --------------------------------------------------------------------------- #
# Anomaly-prioritized teaching path ("walk ahead of the student")
# --------------------------------------------------------------------------- #
def record_learner_question(
    asset: KnowledgeAsset,
    teacher: TeacherModel | None,
    concept_id: str,
    question: str,
) -> TeacherModel:
    """Record a learner's follow-up question as a signal in the Teacher Model.

    Follow-up questions expose where the learner is confused, so they land in
    the concept's ``learner_signals`` (visible in the Teacher Model view) and
    the Teacher Model keeps learning about the learner even outside graded
    answers. Deterministic, no LLM needed; caller persists.
    """
    if teacher is None:
        teacher = TeacherModel(
            asset_id=asset.asset_id, status="fallback", method="lazy_init"
        )
    c = asset.concept_by_id(concept_id)
    cname = c.name if c is not None else "(未知概念)"
    note = teacher.concept_note_by_id(concept_id)
    if note is None:
        note = ConceptNote(concept_id=concept_id, name=cname)
        teacher.concept_notes.append(note)
    snippet = question.strip().replace("\n", " ")[:140]
    note.learner_signals.append(f"学习者追问：{snippet}")
    note.learner_signals = note.learner_signals[-8:]
    teacher.synthesized_at = datetime.now(timezone.utc).isoformat()
    return teacher


def anomaly_concept_ids(asset: KnowledgeAsset, teacher: TeacherModel | None) -> set[str]:
    """Concept ids that are touched by at least one open/investigating anomaly."""
    ids: set[str] = set()
    if not teacher:
        return ids
    for an in teacher.anomalies:
        if an.status not in ("open", "investigating"):
            continue
        for c in asset.concepts:
            if c.name in an.description or c.name in (an.location or ""):
                ids.add(c.id)
    return ids


def anomaly_prioritized_path(
    asset: KnowledgeAsset,
    teacher: TeacherModel | None,
    base_path: list[str] | None = None,
) -> list[str]:
    """Reorder a concept path so concepts tied to open anomalies come first
    (preserving original relative order), so teaching walks ahead of the
    student. Completed items are excluded by the caller (next_concept_id)."""
    base = list(base_path or asset.learning_path or [c.id for c in asset.concepts])
    open_ids = anomaly_concept_ids(asset, teacher)
    front = [cid for cid in base if cid in open_ids]
    rest = [cid for cid in base if cid not in open_ids]
    return front + rest
