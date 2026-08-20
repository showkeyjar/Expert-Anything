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
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
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

from expert_anything.core.i18n import t as _t
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

def _tag_label(tag: str) -> str:
    """Translated tag label — looked up at render time so language switches
    take effect immediately (module-level _t() would freeze the first lang)."""
    return {
        "weak": _t("legend_weak"),
        "anom": _t("legend_anomaly"),
        "foundation": _t("legend_unstudied"),
        "ready": _t("legend_mastered"),
        "blocked": _t("legend_learning"),
        "path": _t("legend_focus"),
        "stuck": _t("tag_stuck"),
    }.get(tag, tag)


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
        """Jump to the first occurrence of the concept (or its evidence).

        If the concept carries a chapter, the search starts at the chapter
        heading so we land in the right section instead of a duplicate that
        appears earlier/later in a different chapter.
        """
        if self._asset is None:
            return
        c = self._asset.concept_by_id(concept_id)
        if c is None:
            return
        needles = [evidence] if evidence else list(c.evidence or [])
        needles.append(c.name)
        doc = self.document()
        # Chapter-scoped search: begin from the chapter heading when present.
        from_pos = 0
        chapter = getattr(c, "chapter", "") or ""
        if chapter:
            ch_cursor = doc.find(chapter[:80])
            if not ch_cursor.isNull():
                from_pos = ch_cursor.selectionStart()
        for needle in needles:
            if not needle:
                continue
            cursor = doc.find(needle[:200], from_pos)
            if cursor.isNull() and from_pos:
                # not found within the chapter -> fall back to the whole doc
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

    def search_all(self, term: str) -> int:
        """Highlight every occurrence of ``term`` and jump to the first.
        Returns the match count."""
        if not term:
            return 0
        doc = self.document()
        selections = []
        cursor = doc.find(term)
        count = 0
        while not cursor.isNull() and count < 200:
            sel = self.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#FFD54F"))
            sel.format = fmt
            sel.cursor = QTextCursor(cursor)
            selections.append(sel)
            count += 1
            cursor = doc.find(term, cursor.selectionEnd())
        if count == 0:
            return 0
        self.setExtraSelections(selections)
        tc = QTextCursor(doc)
        tc.setPosition(selections[0].cursor.selectionStart())
        self.setTextCursor(tc)
        self.ensureCursorVisible()
        return count

    def scroll_to_text(self, needle: str) -> None:
        """Scroll to the first occurrence of an arbitrary text (e.g. a chapter
        title) and highlight its paragraph."""
        if not needle:
            return
        doc = self.document()
        cursor = doc.find(needle[:200])
        if cursor.isNull():
            return
        block = cursor.block()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#B3E5FC"))
        sel = self.ExtraSelection()
        sel.format = fmt
        sel.cursor = QTextCursor(block)
        sel.cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        self.setExtraSelections([sel])
        tc = QTextCursor(doc)
        tc.setPosition(cursor.selectionStart())
        self.setTextCursor(tc)
        self.ensureCursorVisible()

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
    incorporate_requested = Signal(str, str)  # a_id, b_id (sink comparison)

    def __init__(self, asset: KnowledgeAsset, concept_id: str,
                 learner_state: dict, teacher: TeacherModel | None = None,
                 parent=None):
        super().__init__(parent)
        self._asset = asset
        self._concept_id = concept_id
        self._teacher = teacher
        self._learner = learner_state
        self._name_to_id = {c.id: c.name for c in asset.concepts}
        concept = asset.concept_by_id(concept_id)

        self.setWindowTitle(_t("panel_title"))
        self.setMinimumSize(560, 640)
        self.setStyleSheet("QDialog { background-color: white; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        if concept is None:
            root.addWidget(QLabel(_t("panel_not_exist")))
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
        m_lbl = QLabel(_t("panel_mastery", m=mastery))
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

        # source-location attribution (chapter + precise line)
        loc0 = (getattr(concept, "locations", []) or [None])[0]
        loc_line = getattr(loc0, "line", 0) if loc0 else 0
        if getattr(concept, "chapter", "") or loc_line:
            parts = []
            if getattr(concept, "chapter", ""):
                parts.append(_t("chapter_label", ch=concept.chapter))
            if loc_line:
                parts.append(_t("loc_line", n=loc_line))
            ch_lbl = QLabel("  ·  ".join(parts))
            ch_lbl.setStyleSheet("font-size: 11.5px; color: #0284C7;")
            root.addWidget(ch_lbl)

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
            body_l.addWidget(_sec_title(_t("panel_evidence", n=len(concept.evidence)), "#2E7D32"))
            ev_list = QListWidget()
            ev_list.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px; font-size: 12px; }"
                "QListWidget::item { padding: 6px; border-bottom: 1px solid #F0F0F0; }"
            )
            loc_by_ev: dict[str, int] = {}
            for loc in (getattr(concept, "locations", []) or []):
                key = (getattr(loc, "snippet", "") or "")[:180]
                if key and getattr(loc, "line", 0):
                    loc_by_ev.setdefault(key, loc.line)
            for ev in concept.evidence:
                label = ev[:180] + ("…" if len(ev) > 180 else "")
                line_no = loc_by_ev.get(ev[:180])
                if line_no:
                    label += f"　({_t('loc_line', n=line_no)})"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, ev)
                item.setToolTip(ev)
                ev_list.addItem(item)
            ev_list.itemClicked.connect(self._on_evidence_clicked)
            body_l.addWidget(ev_list)

        # -- relations -----------------------------------------------------
        rels = self._collect_relations(concept)
        if rels:
            body_l.addWidget(_sec_title(_t("panel_position"), "#0284C7"))
            rel_list = QListWidget()
            rel_list.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px; font-size: 12px; }"
                "QListWidget::item { padding: 5px; border-bottom: 1px solid #F0F0F0; }"
            )
            for label, other_id, direction in rels:
                other = asset.concept_by_id(other_id)
                arrow = "→" if direction == "out" else "←"
                item = QListWidgetItem(f"{arrow} {label or _t('edge_related')}　{other.name if other else other_id}")
                item.setData(Qt.ItemDataRole.UserRole, other_id)
                rel_list.addItem(item)
            rel_list.itemClicked.connect(self._on_neighbor_clicked)
            body_l.addWidget(rel_list)

        # -- peers & next level (position sense: alongside / where it leads)
        self._append_position(body_l)

        # -- teacher notes ---------------------------------------------------
        if self._teacher is not None:
            note = self._teacher.concept_note_by_id(concept_id)
            if note is not None:
                blocks: list[tuple[str, str]] = []
                if note.significance:
                    blocks.append((_t("panel_why"), note.significance))
                if note.prerequisites:
                    blocks.append((_t("panel_prereq"), "；".join(note.prerequisites)))
                if note.misconceptions:
                    blocks.append((_t("panel_miscon"), "；".join(note.misconceptions)))
                if note.connections:
                    blocks.append((_t("panel_conn"), "；".join(note.connections)))
                if note.external_notes:
                    blocks.append((_t("panel_ext"), "；".join(note.external_notes)))
                if note.note:
                    blocks.append((_t("panel_understanding"), note.note))
                if blocks:
                    body_l.addWidget(_sec_title(_t("panel_teacher_notes"), "#7C3AED"))
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
                body_l.addWidget(_sec_title(_t("panel_anomalies"), "#E65100"))
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
        teach_btn = QPushButton(_t("panel_teach"))
        teach_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(
            lambda: (self.teach_requested.emit(concept.name), self.accept())
        )
        btn_row.addWidget(teach_btn)

        focus_btn = QPushButton(_t("panel_focus"))
        focus_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7; border: 1px solid #0284C7;"
            "border-radius: 6px; padding: 8px 18px; font-size: 13px; }"
            "QPushButton:hover { background-color: #E1F0FA; }"
        )
        focus_btn.clicked.connect(
            lambda: (self.focus_requested.emit(concept_id), self.accept())
        )
        btn_row.addWidget(focus_btn)

        cmp_btn = QPushButton(_t("detail_compare_with"))
        cmp_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #00695C;"
            "border: 1px solid #80CBC4; border-radius: 6px; padding: 8px 18px;"
            "font-size: 13px; }"
            "QPushButton:hover { background-color: #E0F2F1; }"
        )
        cmp_btn.clicked.connect(self._open_compare)
        btn_row.addWidget(cmp_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # -- helpers --------------------------------------------------------------
    def _append_position(self, body_l: QVBoxLayout) -> None:
        """Same-level peers + next-level points, clickable to roam."""
        try:
            from expert_anything.core.map_context import siblings, next_level
            peers = siblings(self._asset, self._concept_id, max_n=6,
                             learner_state=self._learner)
            nxt = next_level(self._asset, self._concept_id, max_n=8,
                             learner_state=self._learner)
        except Exception:
            peers, nxt = [], []

        if peers:
            body_l.addWidget(_sec_title(_t("detail_siblings"), "#6D4C41"))
            plist = QListWidget()
            plist.setToolTip(_t("detail_dbl_teach"))
            plist.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px;"
                "font-size: 12px; }"
                "QListWidget::item { padding: 5px; border-bottom: 1px solid #F0F0F0; }"
            )
            for p in peers:
                ch = f"　·　{p['chapter'][:24]}" if p.get("chapter") else ""
                item = QListWidgetItem(f"◆ {p['name']}{ch}")
                item.setData(Qt.ItemDataRole.UserRole, p["id"])
                plist.addItem(item)
            plist.itemClicked.connect(self._on_neighbor_clicked)
            plist.itemDoubleClicked.connect(self._on_neighbor_activated)
            body_l.addWidget(plist)

        if nxt:
            body_l.addWidget(_sec_title(_t("detail_next_level"), "#00695C"))
            nlist = QListWidget()
            nlist.setToolTip(_t("detail_dbl_teach"))
            nlist.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px;"
                "font-size: 12px; }"
                "QListWidget::item { padding: 5px; border-bottom: 1px solid #F0F0F0; }"
            )
            for n in nxt:
                arrow = "→" if n["dir"] in ("out", "path") else "←"
                label = f"{arrow} {n['label']}　{n['name']}" if n["label"] \
                    else f"{arrow} {n['name']}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, n["id"])
                nlist.addItem(item)
            nlist.itemClicked.connect(self._on_neighbor_clicked)
            nlist.itemDoubleClicked.connect(self._on_neighbor_activated)
            body_l.addWidget(nlist)

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

    def _open_compare(self) -> None:
        """Open the comparison dialog against the first peer / next-level point."""
        try:
            from expert_anything.core.map_context import siblings, next_level
            cands = (siblings(self._asset, self._concept_id, max_n=1)
                     + next_level(self._asset, self._concept_id, max_n=1))
            target = cands[0]["id"] if cands else None
        except Exception:
            target = None
        if target is None:
            return
        dlg = ConceptCompareDialog(self._asset, self._concept_id, target,
                                   self._learner, self._teacher, self)
        dlg.focus_requested.connect(self.focus_requested)
        dlg.teach_requested.connect(self.teach_requested)
        dlg.incorporate_requested.connect(self.incorporate_requested)
        self._compare_dialog = dlg
        dlg.show()

    def _on_neighbor_clicked(self, item: QListWidgetItem) -> None:
        other_id = item.data(Qt.ItemDataRole.UserRole) or ""
        if other_id:
            self.focus_requested.emit(other_id)

    def _on_neighbor_activated(self, item: QListWidgetItem) -> None:
        """Double-click a peer / next-level point → teach it directly."""
        other_id = item.data(Qt.ItemDataRole.UserRole) or ""
        c = self._asset.concept_by_id(other_id) if other_id else None
        if c is not None:
            self.teach_requested.emit(c.name)
            self.accept()


# --------------------------------------------------------------------------- #
# ConceptCompareDialog
# --------------------------------------------------------------------------- #
class ConceptCompareDialog(QDialog):
    """Side-by-side comparison of two concepts — the "information gain" the
    map owes the reader: shared neighbours, relations unique to each side,
    chapter, mastery gap and teacher-note differences."""

    focus_requested = Signal(str)            # concept id
    teach_requested = Signal(str)            # concept name
    incorporate_requested = Signal(str, str)  # a_id, b_id (sink into teacher)

    def __init__(self, asset: KnowledgeAsset, id_a: str, id_b: str,
                 learner_state: dict, teacher: TeacherModel | None = None,
                 parent=None):
        super().__init__(parent)
        self._asset = asset
        self._learner = learner_state
        self._teacher = teacher
        self._id_a = id_a
        self._id_b = id_b
        self._cand_ids: list[str] = []

        self.setWindowTitle(_t("compare_title"))
        self.setMinimumSize(860, 620)
        self.setStyleSheet("QDialog { background-color: white; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        # --- selector row: A ⇄ [dropdown] --------------------------------
        sel = QHBoxLayout()
        sel.setSpacing(8)
        a_name = self._name_of(id_a)
        a_lbl = QLabel(a_name)
        a_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #0c3d5f;")
        sel.addWidget(a_lbl)
        sel.addWidget(QLabel("⇄"))
        self._b_combo = QComboBox()
        self._b_combo.setStyleSheet(
            "QComboBox { border: 1px solid #B0BEC5; border-radius: 6px;"
            "padding: 4px 10px; font-size: 13px; }"
        )
        self._populate_candidates()
        sel.addWidget(self._b_combo, 1)
        go_btn = QPushButton(_t("compare_select"))
        go_btn.setStyleSheet(
            "QPushButton { background-color: #00695C; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 12.5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #004D40; }"
        )
        go_btn.clicked.connect(self._on_switch)
        sel.addWidget(go_btn)
        root.addLayout(sel)

        # --- scrollable comparison body ------------------------------------
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self._scroll, 1)
        self._rebuild()

    # -- internals -----------------------------------------------------------
    def _name_of(self, cid: str) -> str:
        c = self._asset.concept_by_id(cid)
        return c.name if c else cid

    def _populate_candidates(self) -> None:
        """Candidates: the second concept first, then peers + next level."""
        seen: list[str] = []
        for cid in (self._id_b,):
            if cid != self._id_a and cid not in seen:
                seen.append(cid)
        try:
            from expert_anything.core.map_context import siblings, next_level
            for item in (siblings(self._asset, self._id_a, max_n=12)
                         + next_level(self._asset, self._id_a, max_n=12)):
                cid = item["id"]
                if cid != self._id_a and cid not in seen:
                    seen.append(cid)
        except Exception:
            pass
        self._cand_ids = seen
        self._b_combo.clear()
        for cid in seen:
            c = self._asset.concept_by_id(cid)
            label = c.name if c else cid
            if c and getattr(c, "chapter", ""):
                label += f"　·　{c.chapter[:22]}"
            self._b_combo.addItem(label, cid)
        if seen:
            try:
                self._b_combo.setCurrentIndex(
                    seen.index(self._id_b) if self._id_b in seen else 0)
            except ValueError:
                self._b_combo.setCurrentIndex(0)

    def _on_switch(self) -> None:
        cid = self._b_combo.currentData()
        if cid:
            self._id_b = cid
            self._rebuild()

    def _on_incorporate(self) -> None:
        """Emit the sink request once; the button then reports success so a
        re-click on the same pair cannot double-sink (idempotent anyway)."""
        self.incorporate_requested.emit(self._id_a, self._id_b)
        self._incorporate_btn.setEnabled(False)
        self._incorporate_btn.setText(_t("compare_incorporated"))

    def _rebuild(self) -> None:
        from expert_anything.core.map_context import compare_concepts
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)

        try:
            r = compare_concepts(self._asset, self._id_a, self._id_b,
                                 teacher=self._teacher,
                                 learner_state=self._learner)
        except ValueError:
            body = QLabel(_t("panel_not_exist"))
            self._scroll.setWidget(body)
            return

        # similarity banner
        sim_pct = f"{r['similarity']:.0%}"
        sim_word = (_t("compare_sim_high") if r["similarity"] >= 0.6
                    else _t("compare_sim_low"))
        banner = QLabel(f"{_t('compare_similarity', pct=sim_pct)} · {sim_word}")
        banner.setStyleSheet(
            "background-color: #E0F2F1; color: #00695C; border-radius: 6px;"
            "padding: 6px 10px; font-size: 12px; font-weight: bold;")
        lay.addWidget(banner)

        # side-by-side columns
        cols = QHBoxLayout()
        cols.setSpacing(12)
        cols.addWidget(self._col(r["a"], _t("compare_definition"),
                                 r["rel_only_a"], is_a=True), 1)
        cols.addWidget(self._col(r["b"], _t("compare_definition"),
                                 r["rel_only_b"], is_a=False), 1)
        lay.addLayout(cols)

        # evidence points
        lay.addWidget(_sec_title(_t("compare_relations") + " · " + _t("compare_notes"), "#00695C"))
        for p in r["points"]:
            lbl = QLabel("• " + p)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                "font-size: 12.5px; color: #37474F; background-color: #F5F7F8;"
                "border-radius: 6px; padding: 6px 8px;")
            lay.addWidget(lbl)

        # learning hint
        hint = QLabel(r["learning_hint"])
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "font-size: 13px; color: #1B5E20; background-color: #E8F5E9;"
            "border-radius: 6px; padding: 8px 10px; font-weight: bold;")
        lay.addWidget(hint)

        # actions
        act = QHBoxLayout()
        for cid, key in ((r["a"]["id"], "compare_learn_a"), (r["b"]["id"], "compare_learn_b")):
            btn = QPushButton(_t("compare_teach", name=self._name_of(cid)))
            btn.setStyleSheet(
                "QPushButton { background-color: #1565C0; color: white; border: none;"
                "border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: bold; }"
                "QPushButton:hover { background-color: #0D47A1; }")
            btn.clicked.connect(
                lambda checked=False, c=cid: self.teach_requested.emit(
                    self._name_of(c)))
            act.addWidget(btn)

        # sink the comparison into the Teacher Model (bridging anchors +
        # mastery gap → the weaker concept is pushed up the teaching order)
        self._incorporate_btn = QPushButton(_t("compare_incorporate"))
        self._incorporate_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #6D4C41;"
            "border: 1px solid #BCAAA4; border-radius: 6px; padding: 6px 14px;"
            "font-size: 12px; }"
            "QPushButton:hover { background-color: #EFEBE9; }"
            "QPushButton:disabled { color: #A1887F; border-color: #D7CCC8; }"
        )
        self._incorporate_btn.setToolTip(_t("compare_incorporate"))
        self._incorporate_btn.clicked.connect(self._on_incorporate)
        act.addWidget(self._incorporate_btn)
        act.addStretch()
        lay.addLayout(act)
        lay.addStretch()
        self._scroll.setWidget(body)

    def _col(self, info: dict, def_title: str,
             rel_only: list[str], is_a: bool) -> QWidget:
        """One concept column: chapter, definition, unique relations, notes."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(QLabel(""))  # spacer keeps the two columns aligned

        name = QLabel(info["name"])
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16px; font-weight: bold; color: #0c3d5f;")
        lay.addWidget(name)

        m = float(info.get("mastery", 0.0))
        m_lbl = QLabel(_t("panel_mastery", m=m))
        m_lbl.setStyleSheet(
            f"background-color: {mastery_color(m)}; color: white;"
            "padding: 2px 10px; border-radius: 9px; font-size: 11px; font-weight: bold;")
        lay.addWidget(m_lbl)

        ch = info.get("chapter", "")
        if ch:
            c_lbl = QLabel(_t("chapter_label", ch=ch))
            c_lbl.setStyleSheet("font-size: 11.5px; color: #0284C7;")
            lay.addWidget(c_lbl)

        ev_n = int(info.get("evidence_count", 0))
        ev_lbl = QLabel(_t("compare_evidence", n=ev_n))
        ev_lbl.setStyleSheet("font-size: 11.5px; color: #2E7D32;")
        lay.addWidget(ev_lbl)

        # definition
        if info.get("definition"):
            d = QLabel(info["definition"])
            d.setWordWrap(True)
            d.setStyleSheet(
                "font-size: 12.5px; color: #37474F; background-color: #F5F7F8;"
                "border-radius: 6px; padding: 8px;")
            lay.addWidget(d)

        # unique relations (the high-signal part)
        if rel_only:
            lay.addWidget(_sec_title(
                _t("compare_relations"), "#0284C7"))
            for rr in rel_only[:4]:
                lbl = QLabel("• " + rr)
                lbl.setWordWrap(True)
                lbl.setStyleSheet("font-size: 12px; color: #0369A1;")
                lay.addWidget(lbl)
        lay.addStretch()
        return w


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
            lbl = QLabel(_t("path_empty"))
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
        badge = item.get("badge", "")
        if badge:
            bmap = {"hot": ("🔥 " + _t("badge_hot"), "#D32F2F"),
                    "important": ("⭐ " + _t("badge_important"), "#B45309"),
                    "new": ("💡 " + _t("badge_new"), "#0284C7")}
            if badge in bmap:
                text, color = bmap[badge]
                name_row.addWidget(tag_chip(text, color))
        if cid in completed:
            name_row.addWidget(tag_chip(_t("legend_mastered"), "#2E7D32"))
        for tag in tags[:3]:
            color = {"weak": "#F44336", "anom": "#E67828",
                     "foundation": "#0284C7", "ready": "#2E7D32",
                     "blocked": "#78909C", "path": "#64748B",
                     "stuck": "#B71C1C"}.get(tag, "#64748B")
            name_row.addWidget(tag_chip(_tag_label(tag), color))
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
        hint = QLabel(_t("priority_fmt", s=item.get("score", 0)))
        hint.setStyleSheet("color: #9E9E9E; font-size: 10.5px;")
        row.addWidget(hint)

        rung.mousePressEvent = lambda e, c=cid: self.concept_clicked.emit(c)
        return rung

# --------------------------------------------------------------------------- #
# TeachResultView
# --------------------------------------------------------------------------- #
class DecoderSceneCard(QWidget):
    """Knowledge decoding card: SceneSpec → step-animated SVG + sort game.

    The spec is produced by Tutor (LLM SceneSpec with code admission, or the
    deterministic relation-graph fallback) and rendered here by pure code —
    the step player (QtSvg), an in-app ordering mini-game whose score re-enters
    the mastery loop via ``game_scored``, and a richer self-contained HTML
    (animation + game) that opens in the browser.
    """

    game_scored = Signal(float)

    def __init__(self, scene: dict, concept: str = "", source_title: str = "",
                 parent=None):
        super().__init__(parent)
        self._scene = scene
        self._concept = concept
        self._source_title = source_title
        self._frames: list[dict] = []
        self._idx = 0
        self._picked: list[int] = []
        self._build()

    # --- shell ---------------------------------------------------------------
    def _build(self) -> None:
        from expert_anything.core import decoder

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #FFF3E0; border: 1px solid #FFCC80;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        root.addWidget(card)

        head = QHBoxLayout()
        t = QLabel(_t("decoder_card_title"))
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #E65100;")
        head.addWidget(t)
        head.addStretch()
        open_btn = QPushButton(_t("decoder_open_html"))
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(
            "font-size: 12px; color: #E65100; border: 1px solid #FFCC80;"
            "border-radius: 6px; padding: 2px 10px; background: white;"
        )
        open_btn.clicked.connect(self._open_html)
        head.addWidget(open_btn)
        lay.addLayout(head)

        # --- step player -----------------------------------------------------
        self._frames = decoder.render_step_svgs(self._scene)
        self._dot_btns: list[QPushButton] = []
        self._svg_host: QWidget | None = None
        self._fade: QGraphicsOpacityEffect | None = None
        self._fade_anim = None
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            self._svg_widget = QSvgWidget()
            self._svg_widget.setMinimumHeight(240)
            self._svg_widget.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                " stop:0 #FBFDFF, stop:1 #F0F5FA);"
                "border: 1px solid #EDF2F8; border-radius: 10px;"
            )
            lay.addWidget(self._svg_widget)
            self._svg_host = self._svg_widget
            self._fade = QGraphicsOpacityEffect(self._svg_widget)
            self._svg_widget.setGraphicsEffect(self._fade)
        except Exception:
            self._svg_widget = None
            note = QLabel("（当前环境不支持内嵌 SVG，请点击右上角打开互动演示。）")
            note.setWordWrap(True)
            lay.addWidget(note)

        self._caption = QLabel("")
        self._caption.setWordWrap(True)
        self._caption.setStyleSheet("font-size: 13.5px; color: #123B66;")
        lay.addWidget(self._caption)

        # clickable step dots (jump to any step)
        dots = QHBoxLayout()
        dots.setSpacing(6)
        for k in range(len(self._frames)):
            d = QPushButton(str(k + 1))
            d.setFixedSize(24, 24)
            d.setCursor(Qt.CursorShape.PointingHandCursor)
            d.clicked.connect(lambda _=False, j=k: self._show(j))
            dots.addWidget(d)
            self._dot_btns.append(d)
        dots.addStretch()
        lay.addLayout(dots)

        from PySide6.QtCore import QTimer
        ctrl = QHBoxLayout()
        self._btn_back = QPushButton("◎ " + _t("decoder_overview_btn"))
        self._btn_start = QPushButton(_t("decoder_step_btn") + " ›")
        self._btn_prev = QPushButton(_t("decoder_prev"))
        self._btn_next = QPushButton(_t("decoder_next"))
        self._btn_play = QPushButton(_t("decoder_play"))
        for b in (self._btn_back, self._btn_start, self._btn_prev,
                  self._btn_next, self._btn_play):
            b.setStyleSheet(
                "font-size: 12px; padding: 3px 12px; border: 1px solid #FFCC80;"
                "border-radius: 6px; background: white; color: #E65100;"
            )
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setStyleSheet(
            "font-size: 12px; padding: 3px 14px; border: none;"
            "border-radius: 6px; background: #E65100; color: white;"
            "font-weight: bold;"
        )
        ctrl.addWidget(self._btn_back)
        ctrl.addWidget(self._btn_start)
        ctrl.addWidget(self._btn_prev)
        ctrl.addWidget(self._btn_play)
        ctrl.addWidget(self._btn_next)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        self._btn_back.clicked.connect(self._show_static)
        self._btn_start.clicked.connect(lambda: self._show(0))
        self._btn_prev.clicked.connect(lambda: self._show(self._idx - 1))
        self._btn_next.clicked.connect(lambda: self._show(self._idx + 1))
        self._timer = QTimer(self)
        self._timer.setInterval(2200)
        self._timer.timeout.connect(self._auto_advance)
        self._btn_play.clicked.connect(self._toggle_play)
        # L1 by default: static overview first — animation is opt-in
        self._show_static()

        # --- ordering mini-game (score re-enters the mastery loop) -----------
        game = self._scene.get("game")
        if isinstance(game, dict) and game.get("items"):
            gh = QLabel(_t("decoder_game_title"))
            gh.setStyleSheet("font-size: 12px; font-weight: bold; color: #BF360C;")
            lay.addWidget(gh)
            goal = QLabel(str(game.get("goal", "")))
            goal.setWordWrap(True)
            goal.setStyleSheet("font-size: 12px; color: #5D4037;")
            lay.addWidget(goal)

            grid = QGridLayout()
            grid.setSpacing(4)
            self._chip_btns: list[QPushButton] = []
            for i, item in enumerate(game["items"]):
                b = QPushButton(str(item))
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setCheckable(False)
                b.setStyleSheet(
                    "font-size: 12px; padding: 4px 10px; border-radius: 12px;"
                    "border: 1px solid #FFB74D; background: #FFF8E1; color: #5D4037;"
                    "text-align: center;"
                )
                b.clicked.connect(lambda _=False, k=i: self._pick(k))
                grid.addWidget(b, i // 3, i % 3)
                self._chip_btns.append(b)
            lay.addLayout(grid)

            hint = QLabel(_t("decoder_your_order"))
            hint.setStyleSheet("font-size: 11px; color: #8D6E63;")
            lay.addWidget(hint)
            self._picked_label = QLabel("—")
            self._picked_label.setWordWrap(True)
            self._picked_label.setStyleSheet(
                "font-size: 13px; color: #37474F; background: white;"
                "border-radius: 6px; padding: 4px;"
            )
            lay.addWidget(self._picked_label)

            gctrl = QHBoxLayout()
            self._btn_check = QPushButton(_t("decoder_game_check"))
            self._btn_check.setStyleSheet(
                "font-size: 12px; padding: 3px 12px; border-radius: 6px;"
                "background: #E65100; color: white;"
            )
            self._btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_check.clicked.connect(self._check_game)
            retry = QPushButton(_t("decoder_game_retry"))
            retry.setStyleSheet(
                "font-size: 12px; padding: 3px 12px; border-radius: 6px;"
                "border: 1px solid #FFCC80; background: white; color: #E65100;"
            )
            retry.setCursor(Qt.CursorShape.PointingHandCursor)
            retry.clicked.connect(self._reset_game)
            reveal = QPushButton(_t("decoder_game_answer"))
            reveal.setStyleSheet(
                "font-size: 12px; padding: 3px 12px; border-radius: 6px;"
                "border: 1px solid #FFCC80; background: white; color: #E65100;"
            )
            reveal.setCursor(Qt.CursorShape.PointingHandCursor)
            reveal.clicked.connect(self._reveal_game)
            for b in (self._btn_check, retry, reveal):
                gctrl.addWidget(b)
            gctrl.addStretch()
            lay.addLayout(gctrl)
            self._verdict = QLabel("")
            self._verdict.setWordWrap(True)
            self._verdict.setStyleSheet("font-size: 12px;")
            lay.addWidget(self._verdict)

    # --- step player behaviour ----------------------------------------------
    def _set_step_ui(self, on: bool) -> None:
        """Toggle between L1 (overview) and L2 (step-by-step) chrome."""
        widgets = [self._btn_back, self._btn_prev, self._btn_play,
                   self._btn_next, *self._dot_btns]
        for w in widgets:
            w.setVisible(on)
        self._btn_start.setVisible(not on)

    def _show_static(self) -> None:
        """L1 — static overview: full diagram, minimal cognitive cost.

        Nothing animates by default; the walkthrough is one explicit
        click away (progressive representation)."""
        from expert_anything.core import decoder
        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText(_t("decoder_play"))
        self._set_step_ui(False)
        self._load_frame(decoder.render_svg(self._scene))
        self._caption.setText(
            f"<span style='background-color:#1976D2; color:white;"
            f"border-radius:4px; padding:1px 8px; font-size:11px;'>◎</span>"
            f"&nbsp; {html.escape(_t('decoder_overview_hint'))}"
        )

    def _show(self, i: int) -> None:
        if not self._frames:
            return
        self._set_step_ui(True)
        self._idx = max(0, min(i, len(self._frames) - 1))
        f = self._frames[self._idx]
        self._load_frame(f["svg"])
        self._caption.setText(
            f"<span style='background-color:#1976D2; color:white;"
            f"border-radius:4px; padding:1px 8px; font-size:11px;'>"
            f"&nbsp;{self._idx + 1}/{len(self._frames)}&nbsp;</span>"
            f"&nbsp; {html.escape(f['caption'])}"
        )
        for k, d in enumerate(self._dot_btns):
            if k == self._idx:
                style = ("background: #1976D2; color: white; border: none;"
                         "font-weight: bold;")
            elif k < self._idx:
                style = ("background: #DCEBFB; color: #1565C0;"
                         "border: 1px solid #64B5F6;")
            else:
                style = ("background: white; color: #7B8FA3;"
                         "border: 1px solid #C6D4E4;")
            d.setStyleSheet(style + "border-radius: 12px; font-size: 11px;")

    def _load_frame(self, svg: str) -> None:
        """Swap the frame SVG with a gentle fade-in (keeps steps feeling
        animated even though QtSvg ignores SMIL)."""
        if self._svg_widget is None:
            return
        data = svg.encode("utf-8")
        try:
            from PySide6.QtCore import QByteArray
            self._svg_widget.load(QByteArray(data))
        except Exception:
            self._svg_widget.load(data)
        if self._fade is not None:
            try:
                from PySide6.QtCore import (QEasingCurve, QPropertyAnimation)
                self._fade_anim = QPropertyAnimation(self._fade, b"opacity", self)
                self._fade_anim.setDuration(280)
                self._fade_anim.setStartValue(0.0)
                self._fade_anim.setEndValue(1.0)
                self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._fade_anim.start()
            except Exception:
                self._fade.setOpacity(1.0)

    def _auto_advance(self) -> None:
        if self._idx >= len(self._frames) - 1:
            self._timer.stop()
            self._btn_play.setText(_t("decoder_play"))
            return
        self._show(self._idx + 1)

    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText(_t("decoder_play"))
        else:
            self._show(0)
            self._timer.start()
            self._btn_play.setText("⏸")

    # --- game behaviour -------------------------------------------------------
    def _pick(self, i: int) -> None:
        if i in self._picked:
            self._picked.remove(i)
        else:
            self._picked.append(i)
        items = self._scene["game"]["items"]
        txt = " → ".join(str(items[k]) for k in self._picked) if self._picked else "—"
        self._picked_label.setText(txt)
        for k, b in enumerate(self._chip_btns):
            b.setStyleSheet(
                ("background: #E65100; color: white; border-color: #E65100;"
                 if k in self._picked else
                 "background: #FFF8E1; color: #5D4037; border-color: #FFB74D;")
                + "font-size: 12px; padding: 4px 10px; border-radius: 12px;"
                "border: 1px solid; text-align: center;"
            )

    def _check_game(self) -> None:
        game = self._scene["game"]
        n = len(game["items"])
        if len(self._picked) != n:
            return
        answer = list(game.get("answer") or range(n))
        hits = sum(1 for a, c in zip(self._picked, answer) if a == c)
        score = round(hits / n, 2)
        ok = hits == n
        self._verdict.setText(
            _t("decoder_game_correct") if ok
            else f"{_t('decoder_game_wrong')}（{hits}/{n}）"
        )
        self._verdict.setStyleSheet(
            f"font-size: 12px; font-weight: {'bold' if ok else 'normal'};"
            f"color: {'#2E7D32' if ok else '#C62828'};"
        )
        self.game_scored.emit(score)

    def _reset_game(self) -> None:
        self._picked = []
        self._picked_label.setText("—")
        self._verdict.setText("")
        for k in range(len(self._chip_btns)):
            self._chip_btns[k].setStyleSheet(
                "font-size: 12px; padding: 4px 10px; border-radius: 12px;"
                "border: 1px solid #FFB74D; background: #FFF8E1; color: #5D4037;"
                "text-align: center;"
            )

    def _reveal_game(self) -> None:
        game = self._scene["game"]
        items = game["items"]
        answer = list(game.get("answer") or range(len(items)))
        self._verdict.setText(
            f"{_t('decoder_game_answer')}： " + " → ".join(str(items[k]) for k in answer)
        )
        self._verdict.setStyleSheet("font-size: 12px; color: #1565C0;")

    # --- browser demo ---------------------------------------------------------
    def _open_html(self) -> None:
        import os
        import tempfile

        from PySide6.QtGui import QDesktopServices
        from expert_anything.core import decoder

        safe = re.sub(r"[^\w\-]+", "_", self._concept or "scene")[:32]
        path = os.path.join(tempfile.gettempdir(), f"ea_decoder_{safe}.html")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(decoder.render_interactive_html(
                    self._scene, self._concept, self._source_title))
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            pass


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
    quiz_requested = Signal()       # user asked for a quick self-test
    quiz_result = Signal(float)     # scored quiz (record into mastery)
    practice_requested = Signal()   # user asked for a hands-on task
    practice_submit = Signal(str)   # answer submitted (score via quiz_result)
    harness_adopt_requested = Signal(dict)  # learner adopts an evolved HarnessSpec
    harness_transfer_requested = Signal(dict)  # learner migrates a harness from another asset

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
        title = QLabel(result.get("concept", _t("stat_total")))
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1565C0;")
        head.addWidget(title)
        style = result.get("style", "")
        if style:
            head.addWidget(tag_chip(_t("style_" + {"例子": "example", "图示": "diagram", "拆解步骤": "steps"}.get(style, "example")), "#0284C7"))
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
                _t("explanation"), explanation, "#E3F2FD", "#90CAF9", "#1565C0"))

        # example
        example = _txt(result.get("example"))
        if example:
            root.addWidget(self._card(
                _t("example"), example, "#FFF8E1", "#FFE082", "#B45309"))

        # analogy bridge (LLM compressed-knowledge layer)
        analogy = _txt(result.get("analogy"))
        if analogy:
            root.addWidget(self._card(
                _t("analogy_title"), analogy, "#E0F2F1", "#80CBC4", "#00695C"))

        # cross-book anchor (personalised link to a previously learned concept)
        cross = result.get("cross_link")
        if isinstance(cross, dict) and cross.get("name"):
            root.addWidget(self._card(
                _t("crosslink_title").format(name=cross.get("name", ""),
                                             asset=cross.get("asset", "") or ""),
                cross.get("relation", ""),
                "#E3F2FD", "#90CAF9", "#0D47A1"))

        # steps (numbered ladder)
        steps = _lst(result.get("steps"))
        if steps:
            steps_title = QLabel(_t("steps_title"))
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

        # knowledge decoding card (SceneSpec → step animation + sort game)
        scene = result.get("scene")
        if isinstance(scene, dict) and scene.get("nodes"):
            dec_card = DecoderSceneCard(scene, _txt(result.get("concept")))
            dec_card.game_scored.connect(self.quiz_result)
            root.addWidget(dec_card)

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
            p_t = QLabel(_t("practice"))
            p_t.setStyleSheet("font-size: 12px; font-weight: bold; color: #2E7D32;")
            prac_lay.addWidget(p_t)
            p_q = QLabel(practice)
            p_q.setWordWrap(True)
            p_q.setStyleSheet("font-size: 13px; color: #37474F;")
            prac_lay.addWidget(p_q)

            self.answer_input = QTextEdit()
            self.answer_input.setPlaceholderText(_t("answer_placeholder"))
            self.answer_input.setMinimumHeight(80)
            self.answer_input.setStyleSheet(
                "QTextEdit { border: 1px solid #C5E1A5; border-radius: 6px;"
                "padding: 8px; font-size: 13px; background-color: white; }"
            )
            prac_lay.addWidget(self.answer_input)

            submit_btn = QPushButton(_t("submit_answer"))
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
                _t("evidence_label"),
                "\n".join(f"• {e}" for e in evidence[:3]),
                "#E8EAF6", "#C5CAE9", "#3F51B5",
            ))

        root.addStretch()
        self._build_followup()
        self._build_quiz_area()
        self._build_practice_area()

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
        head.addWidget(_sec_title(_t("eval_result"), "#6A1B9A"))
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
            ref_title = QLabel(_t("eval_reference"))
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
            gap_title = QLabel(_t("eval_gap"))
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

    # -- AutoHarness evolution suggestion --------------------------------------
    def append_harness_suggestion(self, title: str, body: str,
                                  candidate: dict,
                                  source: str = "stuck",
                                  extra: dict | None = None) -> None:
        """Append an AutoHarness evolution suggestion card with an adopt button.

        The candidate (a normalized HarnessSpec) was produced by the stuck
        loop's ``evolve_for_stuck`` (source="stuck", amber card), by
        ``evolve_for_regression`` (source="regression", violet card — the
        regression signal points to a guard that may be backfiring, e.g.
        budget_ok throttling explanations), or by ``evolve_joint`` when
        multiple signal families fire together (source="joint", cyan card —
        the fusion decision with its diagnosis; ``extra`` carries metadata
        for the audit chain, e.g. {"_joint_reason": "stuck+regression"}).
        Adopting any of them fires ``harness_adopt_requested`` so the window
        can persist the spec and re-teach with its style.
        """
        if source == "joint":
            bg, border, title_c, text_c, btn_bg, btn_hover = (
                "#E0F7FA", "#4DD0E1", "#006064", "#00363D", "#00838F", "#006064")
            btn_text = _t("harness_adopt_joint")
        elif source == "regression":
            bg, border, title_c, text_c, btn_bg, btn_hover = (
                "#F3E5F5", "#CE93D8", "#4A148C", "#311B3A", "#6A1B9A", "#4A148C")
            btn_text = _t("harness_adopt_regress")
        else:
            bg, border, title_c, text_c, btn_bg, btn_hover = (
                "#FFF8E1", "#FFE082", "#E65100", "#4E342E", "#E65100", "#BF360C")
            btn_text = _t("harness_adopt")
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        lay.addWidget(_sec_title(title, title_c))
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet(f"font-size: 12.5px; color: {text_c};")
        lay.addWidget(b)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn = QPushButton(btn_text)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {btn_bg}; color: white;"
            "border: none; border-radius: 6px; padding: 7px 16px;"
            "font-size: 12.5px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: {btn_hover}; }}"
        )
        btn.clicked.connect(
            lambda checked=False, c=candidate, s=source, x=extra or {}:
                self.harness_adopt_requested.emit(dict(c, _source=s, **x))
        )
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)

        root.insertWidget(root.count() - 1, card)

    def append_transfer_suggestion(self, title: str, body: str,
                                   payload: dict) -> None:
        """Append a cross-asset harness migration suggestion card.

        Unlike the amber evolution card (``append_harness_suggestion``), this
        light-blue card carries a *transfer payload* built by the window's
        ``_find_transfer_candidates``::

            {"source_asset_id", "source_title", "spec", "evaluation", "gain"}

        Adopting it fires ``harness_transfer_requested`` with the whole payload
        so the window can persist via ``adopt_harness_for_asset`` (audit trail
        reason="transfer") and re-teach with the migrated style.
        """
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E3F2FD; border: 1px solid #90CAF9;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        lay.addWidget(_sec_title(title, "#0D47A1"))
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet("font-size: 12.5px; color: #0D2B45;")
        lay.addWidget(b)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn = QPushButton(_t("harness_transfer_adopt"))
        btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 7px 16px; font-size: 12.5px;"
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        btn.clicked.connect(
            lambda checked=False, p=payload: self.harness_transfer_requested.emit(p)
        )
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)

        root.insertWidget(root.count() - 1, card)

    def append_harness_history(self, events: list[dict], limit: int = 5) -> None:
        """Append an evolution history block (audit trail) to the teach area.

        Events come from ``auto_harness.load_harness_history`` (append-only
        audit chain). Only *new* events since the last call on this view are
        rendered (dedup by count), capped at ``limit``, so repeated calls
        (e.g. stuck branch + fresh teaching view) never duplicate lines.
        """
        if not events:
            return
        shown = getattr(self, "_harness_shown_count", 0)
        new_events = events[shown:]
        if not new_events:
            return
        self._harness_shown_count = len(events)

        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F5F5F5; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(_sec_title(_t("harness_history"), "#455A64"))

        _reason_labels = {
            "stuck": _t("harness_reason_stuck"),
            "manual": _t("harness_reason_manual"),
            "steady": _t("harness_reason_steady"),
            "transfer": _t("harness_reason_transfer"),
            "regression": _t("harness_reason_regression"),
            "joint": _t("harness_reason_joint"),
            "sessions": _t("harness_reason_sessions"),
        }

        def _fmt(reason: str) -> str:
            # 联合演化 reason 是触发家族串（如 stuck+regression+sessions），
            # 逐个家族本地化后拼接，保证审计链可读。
            if reason in _reason_labels:
                return _reason_labels[reason]
            return "+".join(_reason_labels.get(p, p)
                            for p in str(reason).split("+"))

        for ev in new_events[-limit:]:
            ts = ev.get("ts", "")
            ts_show = ts[:16].replace("T", " ") if isinstance(ts, str) else ""
            reason = _fmt(ev.get("reason", ""))
            old = ev.get("old", "")
            new = ev.get("new", "")
            line = (f"{ts_show}  {reason}\n  {old}  →  {new}"
                    if ts_show else f"{reason}\n  {old}  →  {new}")
            b = QLabel(line)
            b.setWordWrap(True)
            b.setStyleSheet("font-size: 11.5px; color: #37474F;")
            lay.addWidget(b)

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
        t = QLabel(_t("related_concepts"))
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #0c4a6e;")
        root.insertWidget(root.count() - 1, t)

        chips = QWidget()
        chips_lay = QHBoxLayout(chips)
        chips_lay.setContentsMargins(0, 0, 0, 0)
        chips_lay.setSpacing(6)
        for label, name, _cid in neighbors:
            chip = QPushButton(name)
            chip.setToolTip(label or _t("related_concepts"))
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

    # -- quick self-test ----------------------------------------------------------
    def _build_quiz_area(self) -> None:
        """Button that asks the tutor to generate a self-test."""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F3E5F5; border: 1px solid #CE93D8;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        t = QLabel(_t("quiz_title"))
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #6A1B9A;")
        lay.addWidget(t)
        hint = QLabel(_t("quiz_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11.5px; color: #7B5A9E;")
        lay.addWidget(hint)
        self._quiz_btn = QPushButton(_t("quiz_start"))
        self._quiz_btn.setStyleSheet(
            "QPushButton { background-color: #6A1B9A; color: white; border: none;"
            "border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #4A148C; }"
        )
        self._quiz_btn.clicked.connect(self.quiz_requested)
        lay.addWidget(self._quiz_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.layout().insertWidget(self.layout().count() - 1, card)

    def show_quiz(self, quiz: dict | None) -> None:
        """Render a generated quiz (or a hint when generation failed)."""
        if quiz is None:
            t = QLabel(_t("quiz_failed"))
            t.setStyleSheet("font-size: 12px; color: #9E9E9E; padding: 6px;")
            self.layout().insertWidget(self.layout().count() - 1, t)
            return
        qtype = quiz.get("type")
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F3E5F5; border: 2px solid #AB47BC;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        badge = QLabel(_t("quiz_true_false") if qtype == "true_false" else _t("quiz_ordering"))
        badge.setStyleSheet(
            "background-color: #AB47BC; color: white; padding: 2px 10px;"
            "border-radius: 8px; font-size: 10px; font-weight: bold;"
        )
        head.addWidget(badge)
        head.addStretch()
        lay.addLayout(head)

        q = QLabel(quiz.get("question", ""))
        q.setWordWrap(True)
        q.setStyleSheet("font-size: 13px; color: #37474F; font-weight: bold;")
        lay.addWidget(q)

        self._quiz_data = quiz
        self._quiz_answer: list[int] = []

        if qtype == "true_false":
            row = QHBoxLayout()
            row.setSpacing(8)
            for val, label in [(True, _t("quiz_true")), (False, _t("quiz_false"))]:
                b = QPushButton(label)
                b.setStyleSheet(
                    "QPushButton { background-color: white; color: #6A1B9A;"
                    "border: 1px solid #CE93D8; border-radius: 6px; padding: 6px 18px;"
                    "font-size: 12.5px; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                b.clicked.connect(
                    lambda checked, v=val: self._check_quiz(v))
                row.addWidget(b)
            row.addStretch()
            lay.addLayout(row)
        else:
            self._quiz_order_label = QLabel("")
            self._quiz_order_label.setStyleSheet("font-size: 12px; color: #6A1B9A;")
            lay.addWidget(self._quiz_order_label)
            for i, opt in enumerate(quiz.get("options", [])):
                b = QPushButton(f"{i + 1}. {opt}")
                b.setStyleSheet(
                    "QPushButton { background-color: white; color: #37474F;"
                    "border: 1px solid #E1BEE7; border-radius: 6px; padding: 5px 10px;"
                    "font-size: 12px; text-align: left; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                b.clicked.connect(
                    lambda checked, idx=i: self._pick_order(idx))
                lay.addWidget(b)
            check = QPushButton(_t("quiz_check"))
            check.setStyleSheet(
                "QPushButton { background-color: #6A1B9A; color: white; border: none;"
                "border-radius: 6px; padding: 5px 14px; font-size: 12px; }"
            )
            check.clicked.connect(lambda: self._check_quiz(self._quiz_answer))
            lay.addWidget(check, 0, Qt.AlignmentFlag.AlignRight)

        self.layout().insertWidget(self.layout().count() - 1, card)

    def _pick_order(self, idx: int) -> None:
        if idx not in self._quiz_answer:
            self._quiz_answer.append(idx)
        self._quiz_order_label.setText(
            " → ".join(str(i + 1) for i in self._quiz_answer))

    def _check_quiz(self, answer) -> None:
        """Score locally, show result, emit quiz_result for mastery recording."""
        quiz = getattr(self, "_quiz_data", None)
        if quiz is None:
            return
        # local scoring: true_false exact; ordering fraction of correct positions
        qtype = quiz.get("type")
        if qtype == "true_false":
            ok = bool(answer) == bool(quiz.get("correct"))
            score = 1.0 if ok else 0.2
        else:
            correct = quiz.get("correct_order", [])
            if len(answer) != len(correct):
                score = 0.0
            else:
                hits = sum(1 for a, c in zip(answer, correct) if a == c)
                score = round(hits / len(correct), 2)

        result = QFrame()
        result.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border-left: 4px solid #2E7D32;"
            "border-radius: 6px; }"
        )
        rl = QVBoxLayout(result)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(4)
        head = QHBoxLayout()
        verdict = _t("quiz_correct") if score >= 0.6 else _t("quiz_wrong")
        v = QLabel(f"{verdict}  ({score:.0%})")
        v.setStyleSheet(
            f"color: {'#2E7D32' if score >= 0.6 else '#C62828'};"
            "font-size: 12.5px; font-weight: bold;"
        )
        head.addWidget(v)
        head.addStretch()
        rl.addLayout(head)
        if qtype == "ordering" and quiz.get("correct_order"):
            right = " → ".join(str(i + 1) for i in quiz["correct_order"])
            rl.addWidget(QLabel(f"{_t('quiz_correct_order')}: {right}"))
        expl = quiz.get("explanation", "")
        if expl:
            e = QLabel(expl)
            e.setWordWrap(True)
            e.setStyleSheet("font-size: 12px; color: #37474F;")
            rl.addWidget(e)
        self.layout().insertWidget(self.layout().count() - 1, result)
        self.quiz_result.emit(float(score))

    # -- hands-on practice -------------------------------------------------------
    def _build_practice_area(self) -> None:
        """Button that asks the tutor to generate a hands-on task."""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border: 1px solid #A5D6A7;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        t = QLabel(_t("practice_title"))
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #2E7D32;")
        lay.addWidget(t)
        hint = QLabel(_t("practice_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11.5px; color: #558B2F;")
        lay.addWidget(hint)
        self._practice_btn = QPushButton(_t("practice_start"))
        self._practice_btn.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; border: none;"
            "border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1B5E20; }"
        )
        self._practice_btn.clicked.connect(self.practice_requested)
        lay.addWidget(self._practice_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.layout().insertWidget(self.layout().count() - 1, card)

    def show_practice(self, task: dict | None) -> None:
        """Render the hands-on task with an answer box."""
        if task is None:
            t = QLabel(_t("practice_failed"))
            t.setStyleSheet("font-size: 12px; color: #9E9E9E; padding: 6px;")
            self.layout().insertWidget(self.layout().count() - 1, t)
            return
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border: 2px solid #66BB6A;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        badge = QLabel(_t("practice_badge"))
        badge.setStyleSheet(
            "background-color: #2E7D32; color: white; padding: 2px 10px;"
            "border-radius: 8px; font-size: 10px; font-weight: bold;"
        )
        lay.addWidget(badge)

        tk = QLabel(task.get("task", ""))
        tk.setWordWrap(True)
        tk.setStyleSheet("font-size: 13px; color: #1B5E20; font-weight: bold;")
        lay.addWidget(tk)

        hint = task.get("hint", "")
        if hint:
            h = QLabel(f"{_t('practice_hint_label')} {hint}")
            h.setWordWrap(True)
            h.setStyleSheet("font-size: 11.5px; color: #558B2F; font-style: italic;")
            lay.addWidget(h)

        self._practice_answer = QTextEdit()
        self._practice_answer.setPlaceholderText(_t("practice_answer_ph"))
        self._practice_answer.setMinimumHeight(90)
        self._practice_answer.setStyleSheet(
            "QTextEdit { border: 1px solid #A5D6A7; border-radius: 6px;"
            "padding: 8px; font-size: 12.5px; background-color: white; }"
        )
        lay.addWidget(self._practice_answer)

        submit = QPushButton(_t("practice_submit"))
        submit.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 12.5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1B5E20; }"
        )
        submit.clicked.connect(
            lambda: self.practice_submit.emit(self._practice_answer.toPlainText()))
        lay.addWidget(submit, 0, Qt.AlignmentFlag.AlignRight)

        self._practice_data = task
        self.layout().insertWidget(self.layout().count() - 1, card)

    def show_practice_result(self, result: dict) -> None:
        """Verdict card for a practice submission (score/feedback/reference)."""
        score = float(result.get("score", 0.0))
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border-left: 4px solid #2E7D32;"
            "border-radius: 6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        verdict = _t("quiz_correct") if score >= 0.6 else _t("quiz_wrong")
        v = QLabel(f"{verdict}  ({score:.0%})")
        v.setStyleSheet(
            f"color: {'#2E7D32' if score >= 0.6 else '#C62828'};"
            "font-size: 12.5px; font-weight: bold;"
        )
        lay.addWidget(v)
        fb = result.get("feedback", "")
        if fb:
            f = QLabel(fb)
            f.setWordWrap(True)
            f.setStyleSheet("font-size: 12px; color: #37474F;")
            lay.addWidget(f)
        ref = result.get("reference", "")
        if ref:
            rt = QLabel(_t("eval_reference"))
            rt.setStyleSheet("font-size: 11px; font-weight: bold; color: #2E7D32; margin-top: 2px;")
            lay.addWidget(rt)
            r = QLabel(ref)
            r.setWordWrap(True)
            r.setStyleSheet(
                "font-size: 12px; color: #37474F; background-color: #F1F8E9;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(r)
        self.layout().insertWidget(self.layout().count() - 1, card)

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

        t = QLabel(_t("followup_title"))
        t.setStyleSheet("font-size: 12px; font-weight: bold; color: #37474F;")
        lay.addWidget(t)

        self._followup_input = QTextEdit()
        self._followup_input.setPlaceholderText(_t("followup_placeholder"))
        self._followup_input.setMaximumHeight(64)
        self._followup_input.setStyleSheet(
            "QTextEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 6px; font-size: 12.5px; background-color: white; }"
        )
        lay.addWidget(self._followup_input)

        ask_btn = QPushButton(_t("ask"))
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
                             _t("trend_empty"))
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _t("trend_empty"))
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
# MapLegend — visual legend chips for the cognitive map
# --------------------------------------------------------------------------- #
class MapLegend(QFrame):
    """A horizontal row of visual chips explaining the cognitive map.

    Each chip is a tiny rendered preview + label so the user understands what
    each style on the map means at a glance. Especially important for the
    orange *dashed* frontier ring, which without context looks like an
    unexplained empty box.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = self.layout()
        if lay is None:
            lay = QHBoxLayout(self)
            self.setLayout(lay)
        # suppress framework type checker complaint
        assert isinstance(lay, QHBoxLayout)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(14)
        lay.addWidget(self._chip("#E1E4E8", "#78909C", solid=1, text=_t("legend_unstudied")))
        lay.addWidget(self._chip("#FDEBCE", "#78909C", solid=1, text=_t("legend_partial")))
        lay.addWidget(self._chip("#C5E6C6", "#78909C", solid=1, text=_t("legend_mastered")))
        lay.addWidget(self._chip("#E1E4E8", "#E67828", solid=1, dashed=True, text=_t("legend_frontier")))
        lay.addWidget(self._chip("#E1E4E8", "#E67828", solid=3, text=_t("legend_anomaly")))
        lay.addWidget(self._chip("#E1E4E8", "#0284C7", solid=3, text=_t("legend_current")))
        lay.addStretch()
        self.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
            "QLabel { font-size: 11px; color: #455A64; }"
        )

    def _chip(self, fill: str, border: str, solid: int = 1, dashed: bool = False,
              text: str = "") -> QWidget:
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(5)
        box = QFrame()
        w = 22
        h = 12
        box.setFixedSize(w, h)
        border_style = " dashed" if dashed else ""
        box.setStyleSheet(
            f"QFrame {{ background-color: {fill}; border: {solid}px{border_style} {border};"
            f" border-radius: 4px; }}"
        )
        wrap.addWidget(box)
        lbl = QLabel(text)
        wrap.addWidget(lbl)
        host = QWidget()
        host.setLayout(wrap)
        host.setStyleSheet("background: transparent; border: none;")
        return host


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
    compare_requested = Signal(str, str)    # concept_a_id, concept_b_id

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
        t = QLabel(_t("detail_click_hint"))
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
                    rels.append((r.label or _t("edge_related"), other.name, other.id))
            elif r.target == concept.id:
                other = asset.concept_by_id(r.source)
                if other:
                    rels.append((r.label or _t("edge_related"), other.name, other.id))
        if rels:
            self._layout.addWidget(_sec_title(_t("detail_relations"), "#0284C7"))
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

        # peers & next level — the reader's "position sense": clicking a node
        # must show what stands alongside it and where it leads, never a dead end
        self._append_peers(asset, concept_id, learner_state)
        self._append_next_level(asset, concept_id, learner_state)

        # first evidence
        if concept.evidence:
            self._layout.addWidget(_sec_title(_t("detail_evidence"), "#2E7D32"))
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
                    bits.append(_t("detail_why", s=note.significance[:80]))
                if note.misconceptions:
                    bits.append(_t("detail_miscon", s=note.misconceptions[0][:60]))
                if bits:
                    self._layout.addWidget(_sec_title(_t("detail_teacher"), "#7C3AED"))
                    for b in bits:
                        lbl = QLabel(b)
                        lbl.setWordWrap(True)
                        lbl.setStyleSheet("font-size: 11.5px; color: #5E35B1;")
                        self._layout.addWidget(lbl)

        # actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        teach_btn = QPushButton(_t("panel_teach"))
        teach_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(
            lambda: self.teach_requested.emit(concept.name))
        btn_row.addWidget(teach_btn)
        full_btn = QPushButton(_t("detail_full"))
        full_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7;"
            "border: 1px solid #BAE6FD; border-radius: 6px; padding: 6px 12px;"
            "font-size: 12px; }"
            "QPushButton:hover { background-color: #E1F0FA; }"
        )
        full_btn.clicked.connect(
            lambda: self.full_detail_requested.emit(concept_id))
        btn_row.addWidget(full_btn)

        # compare — only meaningful when a peer / next-level candidate exists
        if self._compare_target(asset, concept_id):
            cmp_btn = QPushButton(_t("detail_compare"))
            cmp_btn.setStyleSheet(
                "QPushButton { background-color: white; color: #00695C;"
                "border: 1px solid #80CBC4; border-radius: 6px; padding: 6px 12px;"
                "font-size: 12px; }"
                "QPushButton:hover { background-color: #E0F2F1; }"
            )
            cmp_btn.clicked.connect(
                lambda: self.compare_requested.emit(
                    concept_id, self._compare_target(asset, concept_id)[0]))
            btn_row.addWidget(cmp_btn)

        btn_row.addStretch()
        self._layout.addLayout(btn_row)
        self._layout.addStretch()

    # -- peers / next level ----------------------------------------------------
    @staticmethod
    def _compare_target(asset, concept_id: str) -> list[str]:
        try:
            from expert_anything.core.map_context import siblings, next_level
            cands = (siblings(asset, concept_id, max_n=1)
                     + next_level(asset, concept_id, max_n=1))
            return [c["id"] for c in cands][:1]
        except Exception:
            return []

    def _pill(self, text: str, cid: str, name: str, color: str) -> QWidget:
        """A roam pill + a small teach button: a peer / next-level point can be
        *studied* in one click, not just roamed to (cognitive-map → lesson)."""
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        roam = QPushButton(text)
        roam.setObjectName("pill_roam_btn")
        roam.setStyleSheet(
            f"QPushButton {{ background-color: {color}18; color: {color};"
            f"border: 1px solid {color}55; border-radius: 6px; padding: 4px 10px;"
            "font-size: 11.5px; text-align: left; }"
            f"QPushButton:hover {{ background-color: {color}33; }}"
        )
        roam.setToolTip(_t("detail_pill_roam"))
        roam.clicked.connect(
            lambda checked=False, c=cid: self.neighbor_clicked.emit(c))
        h.addWidget(roam, 1)
        teach = QPushButton("▶")
        teach.setObjectName("pill_teach_btn")
        teach.setFixedWidth(30)
        teach.setToolTip(_t("detail_pill_teach"))
        teach.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: white; border: none;"
            "border-radius: 6px; padding: 4px 0; font-size: 11px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: {color}BB; }}"
        )
        teach.clicked.connect(
            lambda checked=False, n=name: self.teach_requested.emit(n))
        h.addWidget(teach, 0)
        return wrap

    def _append_peers(self, asset, concept_id: str, learner_state: dict) -> None:
        try:
            from expert_anything.core.map_context import siblings
            peers = siblings(asset, concept_id, max_n=5, learner_state=learner_state)
        except Exception:
            peers = []
        self._layout.addWidget(_sec_title(_t("detail_siblings"), "#6D4C41"))
        if not peers:
            empty = QLabel(_t("detail_peers_empty"))
            empty.setStyleSheet("font-size: 11px; color: #BDBDBD;")
            self._layout.addWidget(empty)
            return
        for p in peers:
            self._layout.addWidget(
                self._pill(p["name"], p["id"], p["name"], "#6D4C41"))

    def _append_next_level(self, asset, concept_id: str, learner_state: dict) -> None:
        try:
            from expert_anything.core.map_context import next_level
            nxt = next_level(asset, concept_id, max_n=6, learner_state=learner_state)
        except Exception:
            nxt = []
        self._layout.addWidget(_sec_title(_t("detail_next_level"), "#00695C"))
        if not nxt:
            empty = QLabel(_t("detail_next_empty"))
            empty.setStyleSheet("font-size: 11px; color: #BDBDBD;")
            self._layout.addWidget(empty)
            return
        for n in nxt:
            arrow = "→" if n["dir"] == "out" else ("←" if n["dir"] == "in" else "→")
            label = f"{arrow} {n['label']}　{n['name']}" if n["label"] else f"{arrow} {n['name']}"
            self._layout.addWidget(
                self._pill(label, n["id"], n["name"], "#00695C"))
