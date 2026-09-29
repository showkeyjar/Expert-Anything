"""Teacher Model - the system's own evolving understanding of an asset.

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
session navigates by it - surfacing "things the system is still unsure
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

from expert_anything.core.domain_templates import (
    detect_domain_from_title,
    domain_concept_skeleton,
)
from expert_anything.core.llm import LLMClient, Message, parse_llm_json, chat_json
from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.prompt_registry import get_domain_prompt, get_prompt
from expert_anything.core import i18n

_t = i18n.t


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# Data models (round-trip to JSON)
# --------------------------------------------------------------------------- #
@dataclass
class ConceptNote:
    concept_id: str
    name: str
    significance: str = ""  # 为什么重要
    prerequisites: list[str] = field(default_factory=list)
    misconceptions: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    external_notes: list[str] = field(default_factory=list)  # 引入的外部补充,标注来源
    external_concepts: list[str] = field(
        default_factory=list
    )  # LLM 压缩层的相关外部概念
    learner_signals: list[str] = field(
        default_factory=list
    )  # 学生真实作答中暴露的困惑/错点
    note: str = ""  # 系统综合理解

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "significance": self.significance,
            "prerequisites": self.prerequisites,
            "misconceptions": self.misconceptions,
            "connections": self.connections,
            "external_notes": self.external_notes,
            "external_concepts": self.external_concepts,
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
            external_concepts=d.get("external_concepts", []),
            learner_signals=d.get("learner_signals", []),
            note=d.get("note", ""),
        )


@dataclass
class Anomaly:
    id: str
    kind: str  # contradiction | undefined_term | logical_gap | surprising_claim
    description: str
    location: str = ""  # 原文片段 / 位置
    severity: str = "medium"  # low | medium | high | info
    status: str = "open"  # open | investigating | resolved | surfaced_to_student
    resolution: str = ""
    source: str = "internal"  # internal | external

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
    status: str = "pending"  # pending | done | fallback | failed
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
            concept_notes=[
                ConceptNote.from_dict(x) for x in d.get("concept_notes", [])
            ],
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
    """Tolerant JSON extraction (canonical implementation: llm.parse_llm_json)."""
    return parse_llm_json(text)


def _build_user_prompt(
    asset: KnowledgeAsset, concepts=None, domain_id: str | None = None
) -> str:
    """Render the teacher user prompt for one batch of concepts.

    ``domain_id`` selects the domain-specific teacher template (Phase 3).  When
    it is ``None`` the domain is detected from the asset title; when nothing is
    detected (or the domain has no translation) the generic ``teacher_user``
    template is used and the rendered request is byte-identical to before.
    """
    concept_lines = []
    for c in concepts if concepts is not None else asset.concepts:
        ev = ";".join(c.evidence[:1]) if c.evidence else "(无证据)"
        concept_lines.append(
            f"- {c.name}:{c.definition or c.summary or '(无定义)'} | 证据:{ev}"
        )
    concepts_block = "\n".join(concept_lines) if concept_lines else "(无概念)"

    # Build the relation network block so the LLM teacher can see *what
    # kind* of connection each relation is — significance and prerequisites
    # are much better when the model knows "A causes B" vs "A is a part of B".
    from expert_anything.core.decoder import classify_relation, REL_SEMANTICS

    rel_lines = []
    for r in asset.relations or []:
        src = asset.concept_by_id(r.source)
        tgt = asset.concept_by_id(r.target)
        if not src or not tgt:
            continue
        sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
        sem_label = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["label"]
        rel_lines.append(f"- [{sem_label}] {src.name} {r.label or '关联'} → {tgt.name}")
    relations_block = "\n".join(rel_lines) if rel_lines else "(无显式关系)"
    source_snippet = asset.source_text[:4000]
    # Build the user prompt using the registry's teacher_user template (or its
    # domain variant). The skeleton is guidance for naming/organising notes —
    # it is never a fact source, hence the explicit "not a source" wording.
    if domain_id is None:
        domain_id = detect_domain_from_title(getattr(asset, "title", "") or "")
    tmpl = get_domain_prompt("teacher_user", domain_id)
    return tmpl.format(
        title=asset.title,
        concept_list=concepts_block,
        relations=relations_block,
        source_snippets=source_snippet,
        concept_skeleton=domain_concept_skeleton(domain_id),
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
                (
                    cc.id
                    for cc in asset.concepts
                    if cc.name.lower() in name.lower()
                    or name.lower() in cc.name.lower()
                ),
                "",
            )
        if not cid:
            continue
        notes.append(
            ConceptNote(
                concept_id=cid,
                name=name,
                significance=(c.get("significance") or "").strip(),
                prerequisites=[
                    x for x in (c.get("prerequisites") or []) if str(x).strip()
                ],
                misconceptions=[
                    x for x in (c.get("misconceptions") or []) if str(x).strip()
                ],
                connections=[x for x in (c.get("connections") or []) if str(x).strip()],
                external_notes=[
                    x for x in (c.get("external_notes") or []) if str(x).strip()
                ],
                external_concepts=[
                    x for x in (c.get("external_concepts") or []) if str(x).strip()
                ],
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
    """No LLM: build deterministic notes from the relation network so the
    teacher model still has *some* self-understanding layer. The notes are
    not as deep as LLM-generated ones, but they give the learner structural
    context (significance from relation count, prerequisites from prereq-type
    edges, connections from all neighbours) rather than blank emptiness."""
    from expert_anything.core.decoder import classify_relation, REL_SEMANTICS

    # Build per-concept relation maps
    by_cid: dict[str, list] = {}  # cid -> list of (other_name, label, sem, dir)
    for r in asset.relations or []:
        sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
        src_c = asset.concept_by_id(r.source)
        tgt_c = asset.concept_by_id(r.target)
        # Validate endpoints by the asset's own concept index: dangling
        # relations (IDs that no longer exist) are skipped, never assumed.
        if not src_c or not tgt_c:
            continue
        by_cid.setdefault(r.source, []).append(
            (tgt_c.name, r.label or "关联", sem, "out")
        )
        by_cid.setdefault(r.target, []).append(
            (src_c.name, r.label or "关联", sem, "in")
        )

    notes: list[ConceptNote] = []
    for c in asset.concepts:
        rels = by_cid.get(c.id, [])
        prereqs = [n for n, _, sem, d in rels if sem == "prereq" and d == "in"]
        # significance: derived from relation count and dominant semantic type
        if rels:
            sem_counts: dict[str, int] = {}
            for _, _, sem, _ in rels:
                sem_counts[sem] = sem_counts.get(sem, 0) + 1
            dom_sem = max(sem_counts, key=lambda k: sem_counts[k])
            dom_label = REL_SEMANTICS.get(dom_sem, REL_SEMANTICS["related"])["label"]
            sig = f"该概念有 {len(rels)} 条关系，以「{dom_label}」为主。"
        else:
            sig = ""

        # connections: all neighbour names with their semantic label
        connections = []
        seen = set()
        for n, label, sem, _ in rels:
            if n not in seen:
                seen.add(n)
                sem_label = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["label"]
                connections.append(f"[{sem_label}] {n}")

        notes.append(
            ConceptNote(
                concept_id=c.id,
                name=c.name,
                significance=sig,
                prerequisites=prereqs,
                connections=connections,
            )
        )

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
                description=_t("teacher_no_llm_anomaly"),
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
            on_progress("selflearn", 0, 0, _t("teacher_no_llm_skip"))
        return _fallback(asset)
    if on_progress:
        on_progress("selflearn", 0, 0, _t("teacher_self_learning"))
    try:
        # Batch the pass: ≤ BATCH concepts per LLM call so the output stays
        # well under the endpoint's limit (a 33-concept single call reliably
        # overflows agnes-2.0-flash and degrades to 'failed'). Each batch
        # yields notes + anomalies which are merged into one TeacherModel.
        BATCH = 12
        # Domain detection once per asset (deterministic, title-based): with a
        # detected domain both prompts use their domain variants; otherwise the
        # generic prompts are used exactly as before.
        domain_id = detect_domain_from_title(asset.title or "")
        merged_data: dict = {"concept_notes": [], "anomalies": []}
        total_batches = (len(asset.concepts) + BATCH - 1) // BATCH
        for b in range(total_batches):
            chunk = asset.concepts[b * BATCH : (b + 1) * BATCH]
            try:
                # NOTE: json_mode is deliberately OFF here - agnes-2.0-flash
                # returns empty bodies for json_object + long prompts. We parse
                # the plain text response with the tolerant _parse_json instead.
                content = llm.chat(
                    [
                        Message(
                            "system", get_domain_prompt("teacher_system", domain_id)
                        ),
                        Message(
                            "user",
                            _build_user_prompt(
                                asset, concepts=chunk, domain_id=domain_id
                            ),
                        ),
                    ],
                    temperature=0.3,
                    max_tokens=3500,
                )
                data = _parse_json(content)
                if not data:
                    raise ValueError("empty/malformed LLM response")
                merged_data["concept_notes"].extend(data.get("concept_notes", []))
                merged_data["anomalies"].extend(data.get("anomalies", []))
            except Exception:
                # a single failed batch must not discard the successful ones;
                # missing notes are better than an all-empty teacher model.
                pass
            if on_progress:
                on_progress(
                    "selflearn",
                    b + 1,
                    total_batches,
                    _t("teacher_batch_progress", b=b + 1, t=total_batches),
                )
        tm = _assemble(asset, merged_data, method="teacher_self_learn_v1")
        if on_progress:
            on_progress(
                "selflearn", 0, 0, _t("teacher_self_learning_done", n=len(tm.anomalies))
            )
        return tm
    except Exception:
        # Graceful degradation: never fail the import on a self-learn hiccup.
        tm = _fallback(asset)
        tm.status = "failed"
        tm.method = "llm_failed_fallback_v1"
        if on_progress:
            on_progress("selflearn", 0, 0, _t("teacher_self_learn_fail"))
        return tm


# --------------------------------------------------------------------------- #
# Closed-loop convergence: learner answers feed back into the Teacher Model
# --------------------------------------------------------------------------- #
_REFLECT_SYSTEM = (
    "你是'教学导航'系统的自我反思模块。系统已经对某个概念做了一轮深加工,"
    "现在一名学习者提交了练习回答并被评估。你的任务是判断:这次学习者的回答,"
    "是仅仅暴露了'学习者个人的薄弱',还是揭示了'材料/讲解本身的隐患'。\n"
    "只输出 JSON,不要解释。"
)

_REFLECT_USER = (
    "概念:{name}\n定义:{definition}\n\n"
    "系统已有的常见误解预判:{miscon}\n系统已有的综合理解:{note}\n\n"
    "学习者回答:{answer}\n评估得分:{score}\n导师反馈:{feedback}\n\n"
    "请判断:\n"
    "1. 若学习者的错误指向材料/讲解本身可被改进之处(如定义含糊、缺少前提、"
    "容易产生的系统性误解未被覆盖),请在 anomaly 里给出一条系统级异常,"
    "kind 取 contradiction|undefined_term|logical_gap|surprising_claim,"
    "severity 取 low|medium|high(得分越低越可能 high),status 固定 open;"
    "否则 anomaly 为 null。\n"
    "2. 用一句话写出这种错误模式的本质 misconceptions(用于补充到概念的常见误解里);"
    "若现有预判已覆盖则填空串。\n\n"
    "输出 JSON:\n"
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
    sys_prompt = get_prompt("teacher_reflect_system", default=None) or _REFLECT_SYSTEM
    user_tmpl = get_prompt("teacher_reflect_user", default=None)
    if user_tmpl is None:
        user_tmpl = _REFLECT_USER
    content = llm.chat(
        [
            Message("system", sys_prompt),
            Message(
                "user",
                user_tmpl.format(
                    name=concept.name,
                    definition=concept.definition or concept.summary or "(无定义)",
                    miscon=";".join(note.misconceptions) or "(无)",
                    note=note.note or "(无)",
                    answer=answer.strip()[:600] or "(学习者未作答)",
                    score=f"{score:.2f}",
                    feedback=feedback or "(无)",
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
    without LLM), and - if an LLM is available - runs a reflection that may
    promote it into a real system anomaly and refine the concept's
    misconceptions. Returns the (mutated) TeacherModel; caller persists it."""
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

    # 1) Always record the learner signal + a learner_gap anomaly (deterministic).
    snippet = answer.strip().replace("\n", " ")[:140]
    note.learner_signals.append(f"学习者(得分 {score:.2f})回答片段:{snippet}")
    sev = "high" if score < 0.4 else ("medium" if score < 0.6 else "low")
    teacher.anomalies.append(
        Anomaly(
            id=_new_id("an"),
            kind="learner_gap",
            description=(
                f"学习者对「{cname}」掌握不足(评估得分 {score:.2f})。"
                f"其回答暴露出需要补习或澄清的点,已作为教学导航的待关注信号。"
            ),
            location=cname,
            severity=sev,
            status="surfaced_to_student",
            source="internal",
        )
    )

    # 1b) Structural anomaly detection via relation semantics (zero LLM cost).
    # If this concept scores poorly but its prerequisite(s) score well, or
    # vice versa (dependent scores well but prerequisite is weak), that's a
    # logical gap worth flagging — either the prerequisite was never properly
    # learned, or the dependency's "mastery" is superficial.
    from expert_anything.core.decoder import classify_relation
    from expert_anything.core.learner import load as _load_learner, normalize as _norm

    try:
        _lst = _load_learner()
        _mm = _lst.get("concepts", {})
    except Exception:
        _mm = {}
    _prereq_issues = 0
    _prereq_names: list[str] = []
    for r in getattr(asset, "relations", []) or []:
        sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
        if sem not in ("prereq", "causes"):
            continue
        # source → target means: source is prerequisite for target
        if r.target == concept_id:
            prereq_id = r.source
            prereq_c = asset.concept_by_id(prereq_id)
            if prereq_c:
                prereq_m = float(_mm.get(_norm(prereq_c.name), {}).get("mastery", 0.0))
                # If concept scored poorly AND its prereq is also weak, that's
                # expected — not an anomaly. The anomaly is when the concept
                # was *thought* to be okay but its foundation isn't, OR when
                # the concept scores high but the prereq doesn't (impossible).
                if score >= 0.6 and prereq_m < 0.4:
                    _prereq_issues += 1
                    _prereq_names.append(prereq_c.name)
    if _prereq_issues > 0:
        _gap_sev = "high" if _prereq_issues >= 2 else "medium"
        teacher.anomalies.append(
            Anomaly(
                id=_new_id("an"),
                kind="logical_gap",
                description=(
                    f"「{cname}」评估得分 {score:.2f},但其前提概念"
                    f"{'、'.join(_prereq_names[:3])}掌握度不足。"
                    f"这可能意味着学习者对「{cname}」的理解停留在表面,"
                    f"尚未真正建立在基础之上。建议先复习前提概念。"
                ),
                location=cname,
                severity=_gap_sev,
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
    note.learner_signals.append(f"学习者追问:{snippet}")
    note.learner_signals = note.learner_signals[-8:]
    teacher.synthesized_at = datetime.now(timezone.utc).isoformat()
    return teacher


def incorporate_stuck_signal(
    asset: KnowledgeAsset,
    teacher: TeacherModel | None,
    concept_id: str,
    attempts: int,
    avg_score: float,
) -> TeacherModel:
    """Closed-loop step for STUCK concepts (repeated failed attempts).

    OmniScientist backtracks to ideation when an experiment keeps yielding
    null results; here repeated low scores mean the *teaching strategy*
    must be re-ideated, not just retried. This records the situation as a
    visible ``learner_gap`` anomaly (kind stays compatible with existing
    filters) so the Teacher Model - and the anomaly-prioritized path -
    keeps the concept in front of the learner while Tutor.teach rotates
    its style. Deterministic, no LLM; caller persists.
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
    note.learner_signals.append(
        f"卡壳信号:连续 {attempts} 次评估均未达标(平均 {avg_score:.2f}),"
        f"当前教学策略可能不适合该学习者,已触发换角度重讲。"
    )
    note.learner_signals = note.learner_signals[-8:]
    teacher.anomalies.append(
        Anomaly(
            id=_new_id("an"),
            kind="learner_gap",
            description=(
                f"学习者对「{cname}」连续 {attempts} 次评估未达标(平均得分 {avg_score:.2f})。"
                f"这不是单次失误而是系统性卡壳:教学将自动更换讲解风格"
                f"({_t('style_example')}/{_t('style_diagram')}/{_t('style_steps')}轮换),"
                f"并优先安排复习。"
            ),
            location=cname,
            severity="high",
            status="surfaced_to_student",
            source="internal",
        )
    )
    teacher.synthesized_at = datetime.now(timezone.utc).isoformat()
    return teacher


def incorporate_comparison(
    asset: KnowledgeAsset,
    teacher: TeacherModel | None,
    id_a: str,
    id_b: str,
    comparison: dict | None = None,
    learner_state: dict | None = None,
) -> TeacherModel:
    """Closed-loop step: sink a two-concept comparison into the Teacher Model.

    Cognitive-map comparisons (``map_context.compare_concepts``) currently
    inform the *reader*; this makes them inform the *system* too, so the
    comparison is not a one-off display. Two deterministic signals land:

    - **shared neighbours** → written into BOTH concepts' ``connections`` as
      bridging anchors (衔接锚点), so the system's own map of how concepts
      hang together grows from comparison;
    - **mastery gap ≥ 0.2** → a ``learner_gap`` anomaly pinned to the weaker
      concept (plus a learner signal on it), which
      ``anomaly_prioritized_path`` then walks ahead of the student - the
      comparison literally re-orders teaching.

    Idempotent: repeated calls on the same pair never duplicate entries
    (exact-string dedup on connections / learner_signals / anomaly
    description). Deterministic, no LLM; caller persists the teacher.
    """
    if teacher is None:
        teacher = TeacherModel(
            asset_id=asset.asset_id, status="fallback", method="lazy_init"
        )
    ca = asset.concept_by_id(id_a)
    cb = asset.concept_by_id(id_b)
    if ca is None or cb is None or id_a == id_b:
        return teacher

    if comparison is None:
        from expert_anything.core.map_context import compare_concepts

        try:
            comparison = compare_concepts(
                asset, id_a, id_b, teacher=teacher, learner_state=learner_state
            )
        except ValueError:
            return teacher
    if not isinstance(comparison, dict):
        return teacher

    a_info = comparison.get("a") or {}
    b_info = comparison.get("b") or {}
    shared = comparison.get("shared_neighbors") or []
    na = teacher.concept_note_by_id(id_a)
    if na is None:
        na = ConceptNote(concept_id=id_a, name=ca.name)
        teacher.concept_notes.append(na)
    nb = teacher.concept_note_by_id(id_b)
    if nb is None:
        nb = ConceptNote(concept_id=id_b, name=cb.name)
        teacher.concept_notes.append(nb)

    # 1) shared neighbours → bridging anchors on both sides
    if shared:
        names = "、".join(str(x) for x in shared[:5])
        for note, other_name in ((na, cb.name), (nb, ca.name)):
            text = f"对比锚点:与「{other_name}」共享概念邻居:{names}"
            if text not in note.connections:
                note.connections.append(text)

    # 2) mastery gap → learner_gap anomaly pinned to the weaker concept
    ma = float(a_info.get("mastery", 0.0) or 0.0)
    mb = float(b_info.get("mastery", 0.0) or 0.0)
    gap = abs(ma - mb)
    if gap >= 0.2:
        low, high = (ca, cb) if ma <= mb else (cb, ca)
        low_name, high_name = low.name, high.name
        m_low, m_high = (ma, mb) if low is ca else (mb, ma)
        signal = (
            f"对比发现:对「{low_name}」的掌握度({m_low:.0%})低于"
            f"「{high_name}」({m_high:.0%}),优先补学「{low_name}」。"
        )
        note_low = na if low is ca else nb
        if signal not in note_low.learner_signals:
            note_low.learner_signals.append(signal)
            note_low.learner_signals = note_low.learner_signals[-8:]
        desc = (
            f"对比「{ca.name}」与「{cb.name}」发现:学习者对「{low_name}」"
            f"掌握度({m_low:.0%})明显低于「{high_name}」({m_high:.0%})。"
            f"已建议优先补学并提入教学排序。"
        )
        if not any(
            a.kind == "learner_gap" and a.description == desc for a in teacher.anomalies
        ):
            teacher.anomalies.append(
                Anomaly(
                    id=_new_id("an"),
                    kind="learner_gap",
                    description=desc,
                    location=low_name,
                    severity="high" if gap >= 0.4 else "medium",
                    status="surfaced_to_student",
                    source="internal",
                )
            )

    teacher.synthesized_at = datetime.now(timezone.utc).isoformat()
    return teacher


def anomaly_concept_ids(
    asset: KnowledgeAsset, teacher: TeacherModel | None
) -> set[str]:
    """Concept ids that are touched by at least one open/investigating anomaly."""
    ids: set[str] = set()
    if not teacher:
        return ids
    for an in teacher.anomalies:
        # A learner gap may already be surfaced to the student while still
        # requiring remediation. Keep it in the teaching loop until resolved;
        # other surfaced anomalies remain informational.
        actionable = an.status in ("open", "investigating")
        surfaced_gap = an.kind == "learner_gap" and an.status == "surfaced_to_student"
        if not (actionable or surfaced_gap):
            continue
        for c in asset.concepts:
            if c.name in an.description or c.name in (an.location or ""):
                ids.add(c.id)
    return ids


def concept_anomalies(
    concept, teacher: TeacherModel | None, limit: int = 3
) -> list[Anomaly]:
    """Actionable anomalies touching *this one* concept, severity-first.

    Same matching rule as :func:`anomaly_concept_ids` (concept name appears
    in the anomaly description or location; actionable = open/investigating,
    plus learner-gap anomalies already surfaced to the student). Severity
    order high > medium > low > info; unknown severities sort last.
    """
    if not teacher or concept is None:
        return []
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    hits: list[Anomaly] = []
    for an in teacher.anomalies:
        actionable = an.status in ("open", "investigating")
        surfaced_gap = (
            an.kind == "learner_gap" and an.status == "surfaced_to_student"
        )
        if not (actionable or surfaced_gap):
            continue
        if concept.name and (
            concept.name in an.description or concept.name in (an.location or "")
        ):
            hits.append(an)
    hits.sort(key=lambda a: order.get(a.severity, 9))
    return hits[:limit]


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
