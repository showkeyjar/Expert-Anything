"""PySide6 visualization widgets for ExpertAnything.

Migrates and extends the retired Flet UI's rich views:

- ``SourceTextView``   — source reader with concept highlighting, concept
  index chips and click-to-inspect (anchor links -> concept panels).
- ``ConceptDetailPanel`` — the "concept hub": definition, mastery, evidence,
  relation neighbours, teacher notes and anomalies, with actions that jump
  to teaching / graph focus / source location.
- ``PathLadderView``   — the adaptive learning path rendered as a ranked
  ladder (position, mastery, status), replacing plain card lists.
"""
from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor as _QColor, QFont as _QFont, QPainter as _QPainter, QPen as _QPen
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.teacher import TeacherModel

# --------------------------------------------------------------------------- #
# colour palette (consistent with pyside_graph / core.graph_viz)
# --------------------------------------------------------------------------- #
MASTERY_COLORS = {
    "mastered": "#4CAF50",
    "partial": "#FF9800",
    "weak": "#F44336",
    "unstudied": "#9E9E9E",
}

TAG_LABELS = {
    "weak": "薄弱",
    "anom": "存疑",
    "foundation": "基础",
    "ready": "可学",
    "blocked": "阻塞",
    "path": "路径",
}


def mastery_level(m: float) -> str:
    if m >= 0.6:
        return "mastered"
    if m >= 0.3:
        return "partial"
    if m > 0:
        return "weak"
    return "unstudied"


def mastery_color(m: float) -> str:
    return MASTERY_COLORS[mastery_level(m)]


def tag_chip(text: str, color: str = "#1565C0") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background-color: {color}20; color: {color};"
        "padding: 2px 8px; border-radius: 4px; font-size: 10px;"
    )
    return lbl


def _sec_title(text: str, color: str = "#0c4a6e") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-size: 12.5px; font-weight: bold; color: {color}; margin-top: 6px;")
    return lbl


# --------------------------------------------------------------------------- #
# SourceTextView
# --------------------------------------------------------------------------- #
class SourceTextView(QTextBrowser):
    """Read-only source reader.

    - every concept name found in the source is highlighted;
    - each occurrence is an anchor -> ``concept_anchor_clicked(concept_id)``;
    - ``scroll_to_concept(cid)`` jumps to the concept's first occurrence and
      temporarily highlights the surrounding paragraph.
    """

    concept_anchor_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setReadOnly(True)
        self.setStyleSheet(
            "QTextBrowser { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; padding: 16px; font-size: 13px; line-height: 1.7; }"
        )
        self.anchorClicked.connect(self._on_anchor)
        self._asset: KnowledgeAsset | None = None
        self._concept_ids_by_name: dict[str, str] = {}

    # -- data ---------------------------------------------------------------
    def set_asset(self, asset: KnowledgeAsset) -> None:
        self._asset = asset
        self._concept_ids_by_name = {
            c.name.lower(): c.id for c in asset.concepts
        }
        self._render()

    def _render(self) -> None:
        if self._asset is None:
            self.setHtml("")
            return
        text = self._asset.source_text or ""
        body = html.escape(text).replace("\n", "<br>")

        # highlight concept names (longest first to avoid sub-string clashes)
        names = sorted(
            (c.name for c in self._asset.concepts if len(c.name) >= 2),
            key=len, reverse=True,
        )
        for name in names:
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            cid = self._concept_ids_by_name.get(name.lower(), "")
            body = pattern.sub(
                lambda m: (
                    f'<a href="concept://{cid}" style="background-color:#FFF3B0;'
                    'color:#0c4a6e;text-decoration:none;border-radius:2px;">'
                    f"{m.group(0)}</a>"
                ),
                body,
            )
        self.setHtml(
            f"<div style='font-size:13px;line-height:1.7;'>{body}</div>"
        )

    # -- navigation -----------------------------------------------------------
    def scroll_to_concept(self, concept_id: str, evidence: str | None = None) -> None:
        """Jump to the first occurrence of the concept (or its evidence)."""
        if self._asset is None:
            return
        c = self._asset.concept_by_id(concept_id)
        if c is None:
            return
        needles = [evidence] if evidence else list(c.evidence or [])
        needles.append(c.name)
        doc = self.document()
        for needle in needles:
            if not needle:
                continue
            cursor = doc.find(needle[:200])
            if not cursor.isNull():
                # paragraph highlight
                sel_start = cursor.selectionStart()
                block = cursor.block()
                fmt = QTextCharFormat()
                fmt.setBackground(QColor("#B3E5FC"))
                extra = self.extraSelections()
                for s in extra:
                    if s.format.background().color().name() != "#B3E5FC":
                        extra.remove(s)
                sel = self.ExtraSelection()
                sel.format = fmt
                sel.cursor = QTextCursor(block)
                sel.cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                self.setExtraSelections([sel])
                tc = QTextCursor(doc)
                tc.setPosition(sel_start)
                self.setTextCursor(tc)
                self.ensureCursorVisible()
                return

    # -- anchor handling ------------------------------------------------------
    def _on_anchor(self, url: QUrl) -> None:
        if url.scheme() == "concept":
            self.concept_anchor_clicked.emit(url.host())


# --------------------------------------------------------------------------- #
# ConceptDetailPanel
# --------------------------------------------------------------------------- #
class ConceptDetailPanel(QDialog):
    """Concept hub: everything the system knows about one concept."""

    teach_requested = Signal(str)            # concept name
    focus_requested = Signal(str)            # concept id (graph focus)
    evidence_requested = Signal(str, str)    # concept_id, evidence text

    def __init__(self, asset: KnowledgeAsset, concept_id: str,
                 learner_state: dict, teacher: TeacherModel | None = None,
                 parent=None):
        super().__init__(parent)
        self._asset = asset
        self._concept_id = concept_id
        self._teacher = teacher
        self._name_to_id = {c.id: c.name for c in asset.concepts}
        concept = asset.concept_by_id(concept_id)

        self.setWindowTitle("概念详情")
        self.setMinimumSize(560, 640)
        self.setStyleSheet("QDialog { background-color: white; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        if concept is None:
            root.addWidget(QLabel("（概念不存在）"))
            return

        # title row: name + mastery badge
        title_row = QHBoxLayout()
        name_lbl = QLabel(concept.name)
        name_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #0c3d5f;")
        title_row.addWidget(name_lbl)
        title_row.addStretch()

        key = next(
            (k for k, v in learner_state.get("concepts", {}).items()
             if v.get("name") == concept.name),
            None,
        )
        rec = learner_state.get("concepts", {}).get(key or "", {})
        mastery = float(rec.get("mastery", 0.0))
        m_lbl = QLabel(f"掌握度 {mastery:.0%}")
        m_lbl.setStyleSheet(
            f"background-color: {mastery_color(mastery)}; color: white;"
            "padding: 4px 12px; border-radius: 10px; font-size: 12px; font-weight: bold;"
        )
        title_row.addWidget(m_lbl)
        root.addLayout(title_row)

        # definition
        if concept.definition or concept.summary:
            def_lbl = QLabel(concept.definition or concept.summary)
            def_lbl.setWordWrap(True)
            def_lbl.setStyleSheet("font-size: 13.5px; color: #37474F;")
            root.addWidget(def_lbl)

        # mastery bar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(mastery * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(
            f"QProgressBar {{ background-color: #EEEEEE; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background-color: {mastery_color(mastery)}; border-radius: 4px; }}"
        )
        root.addWidget(bar)

        # scrollable detail body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 4, 0, 0)
        body_l.setSpacing(6)

        # -- evidence -----------------------------------------------------
        if concept.evidence:
            body_l.addWidget(_sec_title(f"原文证据（{len(concept.evidence)} 条）", "#2E7D32"))
            ev_list = QListWidget()
            ev_list.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px; font-size: 12px; }"
                "QListWidget::item { padding: 6px; border-bottom: 1px solid #F0F0F0; }"
            )
            for ev in concept.evidence:
                item = QListWidgetItem(ev[:180] + ("…" if len(ev) > 180 else ""))
                item.setData(Qt.ItemDataRole.UserRole, ev)
                item.setToolTip(ev)
                ev_list.addItem(item)
            ev_list.itemClicked.connect(self._on_evidence_clicked)
            body_l.addWidget(ev_list)

        # -- relations -----------------------------------------------------
        rels = self._collect_relations(concept)
        if rels:
            body_l.addWidget(_sec_title("知识网络中的位置", "#0284C7"))
            rel_list = QListWidget()
            rel_list.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px; font-size: 12px; }"
                "QListWidget::item { padding: 5px; border-bottom: 1px solid #F0F0F0; }"
            )
            for label, other_id, direction in rels:
                other = asset.concept_by_id(other_id)
                arrow = "→" if direction == "out" else "←"
                item = QListWidgetItem(f"{arrow} {label or '关联'}　{other.name if other else other_id}")
                item.setData(Qt.ItemDataRole.UserRole, other_id)
                rel_list.addItem(item)
            rel_list.itemClicked.connect(self._on_neighbor_clicked)
            body_l.addWidget(rel_list)

        # -- teacher notes ---------------------------------------------------
        if self._teacher is not None:
            note = self._teacher.concept_note_by_id(concept_id)
            if note is not None:
                blocks: list[tuple[str, str]] = []
                if note.significance:
                    blocks.append(("为什么重要", note.significance))
                if note.prerequisites:
                    blocks.append(("前置知识", "；".join(note.prerequisites)))
                if note.misconceptions:
                    blocks.append(("常见误解", "；".join(note.misconceptions)))
                if note.connections:
                    blocks.append(("外部连接", "；".join(note.connections)))
                if note.external_notes:
                    blocks.append(("外部补充（非原文）", "；".join(note.external_notes)))
                if note.note:
                    blocks.append(("系统理解", note.note))
                if blocks:
                    body_l.addWidget(_sec_title("教师笔记", "#7C3AED"))
                    for title, content in blocks:
                        t = QLabel(title)
                        t.setStyleSheet("font-size: 11.5px; color: #7C3AED; font-weight: bold; margin-top: 4px;")
                        body_l.addWidget(t)
                        c = QLabel(content)
                        c.setWordWrap(True)
                        c.setStyleSheet("font-size: 12.5px; color: #37474F;")
                        body_l.addWidget(c)

        # -- anomalies -------------------------------------------------------
        if self._teacher is not None:
            mine = [
                a for a in self._teacher.open_anomalies()
                if concept.name in (a.location or "") or concept.name in a.description
            ]
            if mine:
                body_l.addWidget(_sec_title("相关待解项", "#E65100"))
                for a in mine:
                    lbl = QLabel(
                        f"[{a.kind} · {a.severity}] {a.description}"
                    )
                    lbl.setWordWrap(True)
                    lbl.setStyleSheet(
                        "font-size: 12px; color: #BF360C; background-color: #FFF3E0;"
                        "border-radius: 6px; padding: 6px 8px;"
                    )
                    body_l.addWidget(lbl)

        body_l.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # -- actions ---------------------------------------------------------
        btn_row = QHBoxLayout()
        teach_btn = QPushButton("开始教学")
        teach_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(
            lambda: (self.teach_requested.emit(concept.name), self.accept())
        )
        btn_row.addWidget(teach_btn)

        focus_btn = QPushButton("在图谱中聚焦")
        focus_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7; border: 1px solid #0284C7;"
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; }"
            "QPushButton:hover { background-color: #E1F0FA; }"
        )
        focus_btn.clicked.connect(
            lambda: (self.focus_requested.emit(concept_id), self.accept())
        )
        btn_row.addWidget(focus_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # -- helpers --------------------------------------------------------------
    def _collect_relations(self, concept):
        out = []
        for r in self._asset.relations:
            if r.source == concept.id and r.target != concept.id:
                out.append((r.label, r.target, "out"))
            elif r.target == concept.id and r.source != concept.id:
                out.append((r.label, r.source, "in"))
        return out

    def _on_evidence_clicked(self, item: QListWidgetItem) -> None:
        ev = item.data(Qt.ItemDataRole.UserRole) or ""
        if ev:
            self.evidence_requested.emit(self._concept_id, ev)

    def _on_neighbor_clicked(self, item: QListWidgetItem) -> None:
        other_id = item.data(Qt.ItemDataRole.UserRole) or ""
        if other_id:
            self.focus_requested.emit(other_id)


# --------------------------------------------------------------------------- #
# PathLadderView
# --------------------------------------------------------------------------- #
class PathLadderView(QWidget):
    """Ranked adaptive learning path as a visual ladder.

    Each rung shows rank, concept name, mastery bar, status chips and a
    'why' hint; the top recommendation is highlighted. Clicking a rung
    emits ``concept_clicked(concept_id)``.
    """

    concept_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

    def set_items(self, items: list[dict], completed: set | None = None) -> None:
        """items: list of adaptive_path() dicts (cid/name/mastery/tags/score)."""
        while self._layout.count():
            w = self._layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        completed = completed or set()

        if not items:
            lbl = QLabel("暂无推荐——所有概念已掌握或模型为空。")
            lbl.setStyleSheet("color: #757575; font-size: 12px;")
            self._layout.addWidget(lbl)
            return

        for rank, item in enumerate(items):
            self._layout.addWidget(self._rung(rank, item, completed))

        self._layout.addStretch()

    def _rung(self, rank: int, item: dict, completed: set) -> QFrame:
        cid = item.get("cid", "")
        name = item.get("name", "?")
        mastery = float(item.get("mastery", 0.0))
        tags = item.get("tags", [])
        is_top = rank == 0

        rung = QFrame()
        border = "2px solid #0284C7" if is_top else "1px solid #E0E0E0"
        bg = "#E3F2FD" if is_top else ("#FAFAFA" if cid in completed else "white")
        rung.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: {border}; border-radius: 10px; }}"
            "QFrame:hover { border: 1px solid #90CAF9; }"
        )
        row = QHBoxLayout(rung)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        # rank badge
        rank_lbl = QLabel("★" if is_top else str(rank + 1))
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_lbl.setFixedSize(26, 26)
        rank_lbl.setStyleSheet(
            f"background-color: {'#0284C7' if is_top else '#ECEFF1'};"
            f"color: {'white' if is_top else '#546E7A'};"
            "border-radius: 13px; font-size: 12px; font-weight: bold;"
        )
        row.addWidget(rank_lbl)

        # name + status
        col = QVBoxLayout()
        col.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        n = QLabel(name)
        n.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #1F2933;"
        )
        name_row.addWidget(n)
        if cid in completed:
            name_row.addWidget(tag_chip("已完成", "#2E7D32"))
        for tag in tags[:3]:
            color = {"weak": "#F44336", "anom": "#E67828",
                     "foundation": "#0284C7", "ready": "#2E7D32",
                     "blocked": "#78909C", "path": "#64748B"}.get(tag, "#64748B")
            name_row.addWidget(tag_chip(TAG_LABELS.get(tag, tag), color))
        name_row.addStretch()
        col.addLayout(name_row)

        # mastery bar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(mastery * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setStyleSheet(
            "QProgressBar { background-color: #EEEEEE; border: none; border-radius: 2px; }"
            f"QProgressBar::chunk {{ background-color: {mastery_color(mastery)}; border-radius: 2px; }}"
        )
        col.addWidget(bar)
        row.addLayout(col, 1)

        # score hint
        hint = QLabel(f"优先级 {item.get('score', 0):.2f}")
        hint.setStyleSheet("color: #9E9E9E; font-size: 10.5px;")
        row.addWidget(hint)

        rung.mousePressEvent = lambda e, c=cid: self.concept_clicked.emit(c)
        return rung

# --------------------------------------------------------------------------- #
# TeachResultView
# --------------------------------------------------------------------------- #
class TeachResultView(QWidget):
    """Structured lesson view: explanation / example / steps / practice / evidence.

    Replaces the plain QTextEdit dump with colour-coded cards, a numbered
    step ladder and a dedicated practice area. ``submit_requested`` fires
    when the learner submits an answer (the answer box is exposed as
    ``answer_input``).
    """

    submit_requested = Signal()
    followup_requested = Signal(str)
    neighbor_clicked = Signal(str)  # concept name

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.answer_input: QWidget | None = None
        self._build(result)

    def _card(self, title: str, body: str, bg: str, border: str, title_color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {title_color};")
        lay.addWidget(t)
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet("font-size: 13px; color: #37474F; line-height: 1.6;")
        lay.addWidget(b)
        return card

    def _build(self, result: dict) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # header: concept + style badge
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(result.get("concept", "概念"))
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1565C0;")
        head.addWidget(title)
        style = result.get("style", "")
        if style:
            head.addWidget(tag_chip(f"风格 · {style}", "#0284C7"))
        head.addStretch()
        root.addLayout(head)

        def _txt(v):
            return str(v).strip() if v is not None else ""

        def _lst(v):
            if isinstance(v, list):
                return [str(s) for s in v if str(s).strip()]
            if isinstance(v, str) and v.strip():
                return [s.strip() for s in v.splitlines() if s.strip()]
            return []

        # explanation
        explanation = _txt(result.get("explanation"))
        if explanation:
            root.addWidget(self._card(
                "讲解", explanation, "#E3F2FD", "#90CAF9", "#1565C0"))

        # example
        example = _txt(result.get("example"))
        if example:
            root.addWidget(self._card(
                "示例", example, "#FFF8E1", "#FFE082", "#B45309"))

        # steps (numbered ladder)
        steps = _lst(result.get("steps"))
        if steps:
            steps_title = QLabel("学习步骤")
            steps_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #37474F;")
            root.addWidget(steps_title)
            for i, s in enumerate(steps, 1):
                row = QHBoxLayout()
                row.setSpacing(8)
                num = QLabel(str(i))
                num.setAlignment(Qt.AlignmentFlag.AlignCenter)
                num.setFixedSize(22, 22)
                num.setStyleSheet(
                    "background-color: #1565C0; color: white; border-radius: 11px;"
                    "font-size: 11px; font-weight: bold;"
                )
                row.addWidget(num, 0)
                txt = QLabel(str(s))
                txt.setWordWrap(True)
                txt.setStyleSheet("font-size: 13px; color: #37474F;")
                row.addWidget(txt, 1)
                root.addLayout(row)

        # practice
        practice = _txt(result.get("practice"))
        if practice:
            prac_card = QFrame()
            prac_card.setStyleSheet(
                "QFrame { background-color: #F1F8E9; border: 1px solid #AED581;"
                "border-radius: 8px; }"
            )
            prac_lay = QVBoxLayout(prac_card)
            prac_lay.setContentsMargins(12, 10, 12, 10)
            prac_lay.setSpacing(6)
            p_t = QLabel("练习")
            p_t.setStyleSheet("font-size: 12px; font-weight: bold; color: #2E7D32;")
            prac_lay.addWidget(p_t)
            p_q = QLabel(practice)
            p_q.setWordWrap(True)
            p_q.setStyleSheet("font-size: 13px; color: #37474F;")
            prac_lay.addWidget(p_q)

            self.answer_input = QTextEdit()
            self.answer_input.setPlaceholderText("请用自己的话回答这个问题...")
            self.answer_input.setMinimumHeight(80)
            self.answer_input.setStyleSheet(
                "QTextEdit { border: 1px solid #C5E1A5; border-radius: 6px;"
                "padding: 8px; font-size: 13px; background-color: white; }"
            )
            prac_lay.addWidget(self.answer_input)

            submit_btn = QPushButton("提交答案")
            submit_btn.setStyleSheet(
                "QPushButton { background-color: #4CAF50; color: white; border: none;"
                "border-radius: 6px; padding: 8px 18px; font-size: 13px; font-weight: bold; }"
                "QPushButton:hover { background-color: #388E3C; }"
            )
            submit_btn.clicked.connect(self.submit_requested)
            prac_lay.addWidget(submit_btn, 0, Qt.AlignmentFlag.AlignRight)
            root.addWidget(prac_card)

        # evidence
        evidence = [str(e) for e in (result.get("evidence") or []) if str(e).strip()]
        if evidence:
            root.addWidget(self._card(
                "原文证据（来源约束）",
                "\n".join(f"• {e}" for e in evidence[:3]),
                "#E8EAF6", "#C5CAE9", "#3F51B5",
            ))

        root.addStretch()
        self._build_followup()

    # -- evaluation feedback ---------------------------------------------------
    def append_evaluation(self, score: float, feedback: str,
                          reference: str = "", gap: str = "") -> None:
        """Append an evaluation card (score + feedback + reference answer)."""
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F3E5F5; border: 1px solid #CE93D8;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # score row
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_sec_title("评估结果", "#6A1B9A"))
        score_lbl = QLabel(f"{score:.0%}")
        score_lbl.setStyleSheet(
            f"background-color: {mastery_color(score)}; color: white;"
            "padding: 3px 12px; border-radius: 9px; font-size: 13px; font-weight: bold;"
        )
        head.addWidget(score_lbl)
        head.addStretch()
        lay.addLayout(head)

        if feedback:
            fb = QLabel(feedback)
            fb.setWordWrap(True)
            fb.setStyleSheet("font-size: 13px; color: #37474F;")
            lay.addWidget(fb)

        if reference:
            ref_title = QLabel("参考回答（基于原文证据）")
            ref_title.setStyleSheet("font-size: 11.5px; font-weight: bold; color: #6A1B9A; margin-top: 2px;")
            lay.addWidget(ref_title)
            ref = QLabel(reference)
            ref.setWordWrap(True)
            ref.setStyleSheet(
                "font-size: 12.5px; color: #37474F; background-color: #EDE7F6;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(ref)

        if gap:
            gap_title = QLabel("与参考的差距")
            gap_title.setStyleSheet("font-size: 11.5px; font-weight: bold; color: #C62828; margin-top: 2px;")
            lay.addWidget(gap_title)
            gp = QLabel(gap)
            gp.setWordWrap(True)
            gp.setStyleSheet(
                "font-size: 12.5px; color: #B71C1C; background-color: #FFEBEE;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(gp)

        root.insertWidget(root.count() - 1, card)

    # -- related concepts --------------------------------------------------------
    def set_neighbors(self, neighbors: list[tuple[str, str, str]]) -> None:
        """Show related concepts as chips (label, name, concept_id).

        Clicking a chip emits ``neighbor_clicked(name)`` so the learner can
        follow the knowledge network concept by concept.
        """
        if not neighbors:
            return
        root = self.layout()
        t = QLabel("关联概念（顺藤摸瓜）")
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #0c4a6e;")
        root.insertWidget(root.count() - 1, t)

        chips = QWidget()
        chips_lay = QHBoxLayout(chips)
        chips_lay.setContentsMargins(0, 0, 0, 0)
        chips_lay.setSpacing(6)
        for label, name, _cid in neighbors:
            chip = QPushButton(name)
            chip.setToolTip(label or "关联概念")
            chip.setStyleSheet(
                "QPushButton { background-color: #E1F0FA; color: #0369A1;"
                "border: 1px solid #BAE6FD; border-radius: 12px; padding: 4px 12px;"
                "font-size: 11.5px; }"
                "QPushButton:hover { background-color: #BAE6FD; }"
            )
            chip.clicked.connect(
                lambda checked, n=name: self.neighbor_clicked.emit(n)
            )
            chips_lay.addWidget(chip)
        chips_lay.addStretch()
        root.insertWidget(root.count() - 1, chips)

    # -- follow-up conversation -------------------------------------------------
    def _build_followup(self) -> None:
        """Question box below the practice card -> grounded Q&A."""
        self._lesson = None
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F5F5F5; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        t = QLabel("还有疑问？追问导师（基于原文证据回答）")
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #37474F;")
        lay.addWidget(t)

        self._followup_input = QTextEdit()
        self._followup_input.setPlaceholderText("例如：这个概念和刚才讲的另一个概念有什么区别？")
        self._followup_input.setMaximumHeight(64)
        self._followup_input.setStyleSheet(
            "QTextEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 6px; font-size: 12.5px; background-color: white; }"
        )
        lay.addWidget(self._followup_input)

        ask_btn = QPushButton("追问")
        ask_btn.setStyleSheet(
            "QPushButton { background-color: #0284C7; color: white; border: none;"
            "border-radius: 6px; padding: 7px 18px; font-size: 12.5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0369A1; }"
        )
        ask_btn.clicked.connect(self._ask)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(ask_btn)
        lay.addLayout(btn_row)

        self.layout().insertWidget(self.layout().count() - 1, card)

    def _ask(self) -> None:
        q = self._followup_input.toPlainText().strip()
        if not q:
            return
        self._followup_input.clear()
        self.followup_requested.emit(q)

    def append_exchange(self, question: str, answer: str) -> None:
        """Append a Q&A bubble pair to the conversation."""
        root = self.layout()
        q_lbl = QLabel(question)
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet(
            "background-color: #E1F5FE; color: #01579B; border-radius: 8px;"
            "padding: 8px 10px; font-size: 12.5px;"
        )
        a_lbl = QLabel(answer)
        a_lbl.setWordWrap(True)
        a_lbl.setStyleSheet(
            "background-color: #F5F5F5; color: #37474F; border-radius: 8px;"
            "padding: 8px 10px; font-size: 12.5px;"
        )
        q_row = QHBoxLayout()
        q_row.addStretch()
        q_row.addWidget(q_lbl, 3)
        root.insertLayout(root.count() - 1, q_row)
        a_row = QHBoxLayout()
        a_row.addWidget(a_lbl, 3)
        a_row.addStretch()
        root.insertLayout(root.count() - 1, a_row)

# --------------------------------------------------------------------------- #
# TrendChartView
# --------------------------------------------------------------------------- #
class TrendChartView(QWidget):
    """QPainter bar chart of recent evaluation scores (learning gain).

    Each bar is one evaluation, coloured by score (green >= 0.6, amber
    >= 0.3, red < 0.3). Reading left -> right shows whether the learner is
    improving across attempts — the Learning Gain metric made visible.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self.setMinimumHeight(170)

    def set_data(self, items: list[dict]) -> None:
        """items: [{"label": short concept name, "score": 0..1}] in time order."""
        self._items = list(items)
        self.update()

    def paintEvent(self, event) -> None:
        painter = _QPainter(self)
        painter.setRenderHint(_QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if not self._items:
            painter.setPen(_QColor("#9E9E9E"))
            font = _QFont()
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "暂无评估记录——完成答题后这里会显示你的成长曲线")
            return

        margin_l, margin_r, margin_t, margin_b = 44, 12, 18, 34
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b
        n = len(self._items)
        slot = plot_w / max(1, n)
        bar_w = min(46, slot * 0.62)

        # grid lines (0, 0.5, 1.0)
        painter.setPen(_QPen(_QColor("#E0E0E0"), 1))
        for frac, lab in ((0.0, "0"), (0.5, "0.5"), (1.0, "1.0")):
            y = margin_t + plot_h * (1 - frac)
            painter.drawLine(margin_l, int(y), w - margin_r, int(y))
            painter.setPen(_QColor("#9E9E9E"))
            small = _QFont()
            small.setPointSize(8)
            painter.setFont(small)
            painter.drawText(2, int(y) + 4, w - margin_l - 2, 14,
                             Qt.AlignmentFlag.AlignRight, lab)
            painter.setPen(_QPen(_QColor("#E0E0E0"), 1))

        # bars
        for i, item in enumerate(self._items):
            score = max(0.0, min(1.0, float(item.get("score", 0.0))))
            x = margin_l + i * slot + (slot - bar_w) / 2
            bar_h = plot_h * score
            y = margin_t + plot_h - bar_h
            color = _QColor("#4CAF50") if score >= 0.6 else (
                _QColor("#FF9800") if score >= 0.3 else _QColor("#F44336"))
            painter.setPen(_QPen(color.darker(130), 1))
            painter.setBrush(color)
            painter.drawRoundedRect(int(x), int(y), int(bar_w), max(1, int(bar_h)), 3, 3)

            # label under bar
            label = item.get("label", "") or ""
            short = label[:6] + ("…" if len(label) > 6 else "")
            painter.setPen(_QColor("#757575"))
            small = _QFont()
            small.setPointSize(7)
            painter.setFont(small)
            painter.drawText(int(x - slot / 2 + 2), margin_t + plot_h + 6,
                             int(slot - 4), 26,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             short)

        painter.end()

# --------------------------------------------------------------------------- #
# MasteryDistributionBar
# --------------------------------------------------------------------------- #
class MasteryDistributionBar(QWidget):
    """Single horizontal bar showing the mastery distribution.

    Segments (left -> right): mastered (green) / learning (amber) /
    weak (orange) / unstudied (grey), widths proportional to counts.
    """

    def __init__(self, counts: dict[str, int] | None = None, parent=None):
        super().__init__(parent)
        self._counts = counts or {"mastered": 0, "learning": 0, "weak": 0, "unstudied": 0}
        self.setMinimumHeight(22)

    def set_counts(self, counts: dict[str, int]) -> None:
        self._counts = counts
        self.update()

    def paintEvent(self, event) -> None:
        painter = _QPainter(self)
        painter.setRenderHint(_QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        segs = [
            ("mastered", "#4CAF50"),
            ("learning", "#FF9800"),
            ("weak", "#F44336"),
            ("unstudied", "#BDBDBD"),
        ]
        total = sum(self._counts.get(k, 0) for k, _ in segs)
        if total <= 0:
            painter.setPen(_QColor("#9E9E9E"))
            small = _QFont()
            small.setPointSize(9)
            painter.setFont(small)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无学习数据")
            painter.end()
            return
        x = 0.0
        for key, color in segs:
            frac = self._counts.get(key, 0) / total
            width = w * frac
            if width >= 1:
                painter.setPen(_QColor(color).darker(120))
                painter.setBrush(_QColor(color))
                painter.drawRect(int(x), 0, max(1, int(width)), h)
            x += width
        painter.end()

# --------------------------------------------------------------------------- #
# NodeDetailCard — in-graph detail sidebar (changes per clicked node)
# --------------------------------------------------------------------------- #
class NodeDetailCard(QFrame):
    """Right-hand detail card that follows the clicked node.

    Clicking a node in the living graph updates this card: definition,
    mastery, relation neighbours (clickable to roam), first evidence and
    teacher-note highlights. '开始教学' starts a lesson, '完整详情' opens
    the full ConceptDetailPanel.
    """

    teach_requested = Signal(str)           # concept name
    full_detail_requested = Signal(str)     # concept id
    neighbor_clicked = Signal(str)          # concept id (roam)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(270)
        self.setMaximumWidth(320)
        self.setStyleSheet(
            "NodeDetailCard { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 10px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)
        self._empty()

    # -- state ---------------------------------------------------------------
    def _empty(self) -> None:
        self._clear()
        t = QLabel("点击左侧节点 - 查看它的定义、关系与教师理解")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("color: #9E9E9E; font-size: 12.5px; padding: 30px 0;")
        self._layout.addWidget(t)
        self._layout.addStretch()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    @staticmethod
    def _clear_layout(lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                NodeDetailCard._clear_layout(item.layout())

    # -- content --------------------------------------------------------------
    def set_concept(self, asset, concept_id: str,
                    learner_state: dict, teacher=None) -> None:
        """Fill the card for one concept (asset is the global map asset)."""
        self._clear()
        concept = asset.concept_by_id(concept_id)
        if concept is None:
            self._empty()
            return

        # header: name + mastery
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(concept.name)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 15px; font-weight: bold; color: #0c3d5f;")
        head.addWidget(name, 1)
        key = next(
            (k for k, v in learner_state.get("concepts", {}).items()
             if v.get("name") == concept.name), None)
        rec = learner_state.get("concepts", {}).get(key or "", {})
        mastery = float(rec.get("mastery", 0.0))
        m_lbl = QLabel(f"{mastery:.0%}")
        m_lbl.setStyleSheet(
            f"background-color: {mastery_color(mastery)}; color: white;"
            "padding: 2px 10px; border-radius: 9px; font-size: 11px; font-weight: bold;"
        )
        head.addWidget(m_lbl, 0)
        self._layout.addLayout(head)

        # definition
        if concept.definition or concept.summary:
            d = QLabel((concept.definition or concept.summary)[:140])
            d.setWordWrap(True)
            d.setStyleSheet("font-size: 12.5px; color: #37474F;")
            self._layout.addWidget(d)

        # relations (roam)
        rels = []
        for r in asset.relations:
            if r.source == concept.id:
                other = asset.concept_by_id(r.target)
                if other:
                    rels.append((r.label or "关联", other.name, other.id))
            elif r.target == concept.id:
                other = asset.concept_by_id(r.source)
                if other:
                    rels.append((r.label or "关联", other.name, other.id))
        if rels:
            self._layout.addWidget(_sec_title("关系 · 点击继续游走", "#0284C7"))
            for label, other_name, other_id in rels[:6]:
                btn = QPushButton(f"{label} → {other_name}")
                btn.setStyleSheet(
                    "QPushButton { background-color: #E1F0FA; color: #0369A1;"
                    "border: 1px solid #BAE6FD; border-radius: 6px; padding: 4px 10px;"
                    "font-size: 11.5px; text-align: left; }"
                    "QPushButton:hover { background-color: #BAE6FD; }"
                )
                btn.clicked.connect(
                    lambda checked, cid=other_id: self.neighbor_clicked.emit(cid)
                )
                self._layout.addWidget(btn)

        # first evidence
        if concept.evidence:
            self._layout.addWidget(_sec_title("原文依据", "#2E7D32"))
            ev = QLabel(concept.evidence[0][:160] + ("…" if len(concept.evidence[0]) > 160 else ""))
            ev.setWordWrap(True)
            ev.setStyleSheet(
                "font-size: 11.5px; color: #546E7A; background-color: #F0F8F0;"
                "border-radius: 6px; padding: 8px;"
            )
            self._layout.addWidget(ev)

        # teacher notes
        if teacher is not None:
            note = teacher.concept_note_by_id(concept_id)
            if note is not None:
                bits = []
                if note.significance:
                    bits.append(f"为什么重要：{note.significance[:80]}")
                if note.misconceptions:
                    bits.append(f"常见误解：{note.misconceptions[0][:60]}")
                if bits:
                    self._layout.addWidget(_sec_title("教师理解", "#7C3AED"))
                    for b in bits:
                        lbl = QLabel(b)
                        lbl.setWordWrap(True)
                        lbl.setStyleSheet("font-size: 11.5px; color: #5E35B1;")
                        self._layout.addWidget(lbl)

        # actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        teach_btn = QPushButton("开始教学")
        teach_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(
            lambda: self.teach_requested.emit(concept.name))
        btn_row.addWidget(teach_btn)
        full_btn = QPushButton("完整详情")
        full_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7;"
            "border: 1px solid #BAE6FD; border-radius: 6px; padding: 6px 12px;"
            "font-size: 12px; }"
            "QPushButton:hover { background-color: #E1F0FA; }"
        )
        full_btn.clicked.connect(
            lambda: self.full_detail_requested.emit(concept_id))
        btn_row.addWidget(full_btn)
        btn_row.addStretch()
        self._layout.addLayout(btn_row)
        self._layout.addStretch()
