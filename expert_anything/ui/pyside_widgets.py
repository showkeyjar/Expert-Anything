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
