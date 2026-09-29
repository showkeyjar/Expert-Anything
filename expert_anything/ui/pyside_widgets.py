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
from PySide6.QtGui import (
    QColor as _QColor,
    QFont as _QFont,
    QPainter as _QPainter,
    QPen as _QPen,
)
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
from expert_anything.ui.widgets._helpers import (
    MASTERY_COLORS,
    _tag_label,
    mastery_level,
    mastery_color,
    tag_chip,
    _sec_title,
)


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
            "border-radius: 8px; padding: 16px; font-size: 15px; line-height: 1.7; }"
        )
        self.anchorClicked.connect(self._on_anchor)
        self._asset: KnowledgeAsset | None = None
        self._concept_ids_by_name: dict[str, str] = {}
        self._learner_state: dict = {}

    # -- data ---------------------------------------------------------------
    def set_asset(self, asset: KnowledgeAsset, learner_state: dict | None = None) -> None:
        self._asset = asset
        self._concept_ids_by_name = {c.name.lower(): c.id for c in asset.concepts}
        self._learner_state = learner_state or {}
        self._render()

    def _render(self) -> None:
        if self._asset is None:
            self.setHtml("")
            return
        text = self._asset.source_text or ""
        body = html.escape(text).replace("\n", "<br>")

        # Build mastery lookup from learner state
        from expert_anything.core.learner import normalize as _norm
        mastery_map: dict[str, float] = {}
        for k, v in self._learner_state.get("concepts", {}).items():
            mastery_map[_norm(k)] = float(v.get("mastery", 0.0))

        # highlight concept names (longest first to avoid sub-string clashes)
        names = sorted(
            (c.name for c in self._asset.concepts if len(c.name) >= 2),
            key=len,
            reverse=True,
        )
        for name in names:
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            cid = self._concept_ids_by_name.get(name.lower(), "")
            # Mastery-based highlight: green=mastered, amber=learning, red=weak, yellow=unstudied
            m = mastery_map.get(_norm(name), 0.0)
            if m >= 0.6:
                bg, fg = "#C8E6C9", "#1B5E20"
            elif m >= 0.3:
                bg, fg = "#FFF8E1", "#E65100"
            elif m > 0:
                bg, fg = "#FFEBEE", "#C62828"
            else:
                bg, fg = "#FFF3B0", "#0c4a6e"
            body = pattern.sub(
                lambda m_match: (
                    f'<a href="concept://{cid}" style="background-color:{bg};'
                    f'color:{fg};text-decoration:none;border-radius:2px;'
                    f'padding:0 2px;">'
                    f"{m_match.group(0)}</a>"
                ),
                body,
            )
        self.setHtml(f"<div style='font-size: 15px;line-height:1.7;'>{body}</div>")

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

    teach_requested = Signal(str)  # concept name
    focus_requested = Signal(str)  # concept id (graph focus)
    evidence_requested = Signal(str, str)  # concept_id, evidence text
    incorporate_requested = Signal(str, str)  # a_id, b_id (sink comparison)

    def __init__(
        self,
        asset: KnowledgeAsset,
        concept_id: str,
        learner_state: dict,
        teacher: TeacherModel | None = None,
        parent=None,
    ):
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
        name_lbl.setStyleSheet("font-size: 22px; font-weight: bold; color: #0c3d5f;")
        title_row.addWidget(name_lbl)
        title_row.addStretch()

        key = next(
            (
                k
                for k, v in learner_state.get("concepts", {}).items()
                if v.get("name") == concept.name
            ),
            None,
        )
        rec = learner_state.get("concepts", {}).get(key or "", {})
        mastery = float(rec.get("mastery", 0.0))
        m_lbl = QLabel(_t("panel_mastery", m=mastery))
        m_lbl.setStyleSheet(
            f"background-color: {mastery_color(mastery)}; color: white;"
            "padding: 4px 12px; border-radius: 10px; font-size: 14px; font-weight: bold;"
        )
        title_row.addWidget(m_lbl)
        root.addLayout(title_row)

        # definition
        if concept.definition or concept.summary:
            def_lbl = QLabel(concept.definition or concept.summary)
            def_lbl.setWordWrap(True)
            def_lbl.setStyleSheet("font-size: 15.5px; color: #37474F;")
            root.addWidget(def_lbl)

        # source-location attribution (page + precise line + chapter)
        loc0 = (getattr(concept, "locations", []) or [None])[0]
        loc_line = getattr(loc0, "line", 0) if loc0 else 0
        loc_page = getattr(loc0, "page", None) if loc0 else None
        if getattr(concept, "chapter", "") or loc_line or loc_page:
            parts = []
            if loc_page:
                parts.append(_t("loc_page", n=loc_page))
            if getattr(concept, "chapter", ""):
                parts.append(_t("chapter_label", ch=concept.chapter))
            if loc_line:
                parts.append(_t("loc_line", n=loc_line))
            ch_lbl = QLabel("  ·  ".join(parts))
            ch_lbl.setStyleSheet("font-size: 13.5px; color: #0284C7;")
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
            body_l.addWidget(
                _sec_title(_t("panel_evidence", n=len(concept.evidence)), "#2E7D32")
            )
            ev_list = QListWidget()
            ev_list.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px; font-size: 14px; }"
                "QListWidget::item { padding: 6px; border-bottom: 1px solid #F0F0F0; }"
            )
            loc_by_ev: dict[str, int] = {}
            page_by_ev: dict[str, int] = {}
            for loc in getattr(concept, "locations", []) or []:
                key = (getattr(loc, "snippet", "") or "")[:180]
                if key and getattr(loc, "line", 0):
                    loc_by_ev.setdefault(key, loc.line)
                if key and getattr(loc, "page", None):
                    page_by_ev.setdefault(key, loc.page)
            for ev in concept.evidence:
                label = ev[:180] + ("…" if len(ev) > 180 else "")
                line_no = loc_by_ev.get(ev[:180])
                page_no = page_by_ev.get(ev[:180])
                suffix_parts = []
                if page_no:
                    suffix_parts.append(_t("loc_page", n=page_no))
                if line_no:
                    suffix_parts.append(_t("loc_line", n=line_no))
                if suffix_parts:
                    label += "　(" + " · ".join(suffix_parts) + ")"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, ev)
                item.setToolTip(ev)
                ev_list.addItem(item)
            ev_list.itemClicked.connect(self._on_evidence_clicked)
            body_l.addWidget(ev_list)

        # -- mini scene preview (visual deconstruction) ---------------------
        try:
            from expert_anything.core import decoder
            # Unified entry point: a curated domain scene when the asset
            # belongs to a domain that ships one, the generic relation graph
            # otherwise (non-domain concepts keep the old fallback behaviour).
            scene = decoder.scene_for_concept(asset, concept)
            if scene and scene.get("nodes"):
                svg_data = decoder.render_svg(scene)
                if svg_data:
                    try:
                        from PySide6.QtSvgWidgets import QSvgWidget
                        from PySide6.QtCore import QByteArray
                        svg_widget = QSvgWidget()
                        svg_widget.load(QByteArray(svg_data.encode("utf-8")))
                        svg_widget.setMinimumHeight(160)
                        svg_widget.setMaximumHeight(220)
                        svg_widget.setStyleSheet(
                            "background-color: #FAFAFA; border: 1px solid #E8E8E8;"
                            "border-radius: 8px;"
                        )
                        body_l.addWidget(svg_widget)
                    except Exception:
                        pass
        except Exception:
            pass

        # -- relations (grouped by semantic type) ---------------------------
        rels = self._collect_relations(concept)
        if rels:
            from expert_anything.core.decoder import classify_relation, REL_SEMANTICS
            # group by semantic type so the learner sees structure, not a flat blob
            by_sem: dict[str, list[tuple[str, str, str]]] = {}
            for label, other_id, direction, rtype in rels:
                sem = classify_relation(label or "", rtype or "")
                by_sem.setdefault(sem, []).append((label, other_id, direction))

            body_l.addWidget(_sec_title(_t("panel_position"), "#0284C7"))
            rel_list = QListWidget()
            rel_list.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px; font-size: 14px; }"
                "QListWidget::item { padding: 5px; border-bottom: 1px solid #F0F0F0; }"
            )
            for sem, items in by_sem.items():
                sem_info = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])
                color = sem_info["color"]
                sem_label = _t("rel_" + sem)
                # semantic group header
                header = QListWidgetItem(f"  ── {sem_label} ──")
                header.setFlags(
                    header.flags()
                    & ~Qt.ItemFlag.ItemIsSelectable
                    & ~Qt.ItemFlag.ItemIsEnabled
                )
                header.setBackground(_QColor(color + "18"))
                header.setForeground(_QColor(color))
                f = header.font()
                f.setBold(True)
                header.setFont(f)
                rel_list.addItem(header)
                for label, other_id, direction in items:
                    other = asset.concept_by_id(other_id)
                    arrow = "→" if direction == "out" else "←"
                    item = QListWidgetItem(
                        f"  {arrow} {label or _t('edge_related')}　"
                        f"{other.name if other else other_id}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, other_id)
                    item.setForeground(_QColor(color))
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
                        t.setStyleSheet(
                            "font-size: 13.5px; color: #7C3AED; font-weight: bold; margin-top: 4px;"
                        )
                        body_l.addWidget(t)
                        c = QLabel(content)
                        c.setWordWrap(True)
                        c.setStyleSheet("font-size: 14.5px; color: #37474F;")
                        body_l.addWidget(c)

        # -- anomalies -------------------------------------------------------
        if self._teacher is not None:
            mine = [
                a
                for a in self._teacher.open_anomalies()
                if concept.name in (a.location or "") or concept.name in a.description
            ]
            if mine:
                body_l.addWidget(_sec_title(_t("panel_anomalies"), "#E65100"))
                for a in mine:
                    lbl = QLabel(f"[{a.kind} · {a.severity}] {a.description}")
                    lbl.setWordWrap(True)
                    lbl.setStyleSheet(
                        "font-size: 14px; color: #BF360C; background-color: #FFF3E0;"
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
            "border-radius: 6px; padding: 8px 18px; font-size: 15px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(
            lambda: (self.teach_requested.emit(concept.name), self.accept())
        )
        btn_row.addWidget(teach_btn)

        focus_btn = QPushButton(_t("panel_focus"))
        focus_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7; border: 1px solid #0284C7;"
            "border-radius: 6px; padding: 8px 18px; font-size: 15px; }"
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
            "font-size: 15px; }"
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

            peers = siblings(
                self._asset, self._concept_id, max_n=6, learner_state=self._learner
            )
            nxt = next_level(
                self._asset, self._concept_id, max_n=8, learner_state=self._learner
            )
        except Exception:
            peers, nxt = [], []

        if peers:
            body_l.addWidget(_sec_title(_t("detail_siblings"), "#6D4C41"))
            plist = QListWidget()
            plist.setToolTip(_t("detail_dbl_teach"))
            plist.setStyleSheet(
                "QListWidget { border: 1px solid #E0E0E0; border-radius: 6px;"
                "font-size: 14px; }"
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
                "font-size: 14px; }"
                "QListWidget::item { padding: 5px; border-bottom: 1px solid #F0F0F0; }"
            )
            for n in nxt:
                arrow = "→" if n["dir"] in ("out", "path") else "←"
                sem_label = n.get("sem_label", "")
                sem_color = n.get("sem_color", "#00695C")
                if n["label"] and sem_label:
                    label = f"{arrow} [{sem_label}] {n['label']}　{n['name']}"
                elif n["label"]:
                    label = f"{arrow} {n['label']}　{n['name']}"
                else:
                    label = f"{arrow} {n['name']}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, n["id"])
                if sem_color:
                    item.setForeground(_QColor(sem_color))
                nlist.addItem(item)
            nlist.itemClicked.connect(self._on_neighbor_clicked)
            nlist.itemDoubleClicked.connect(self._on_neighbor_activated)
            body_l.addWidget(nlist)

    def _collect_relations(self, concept):
        out = []
        for r in self._asset.relations:
            if r.source == concept.id and r.target != concept.id:
                out.append((r.label, r.target, "out", getattr(r, "type", "")))
            elif r.target == concept.id and r.source != concept.id:
                out.append((r.label, r.source, "in", getattr(r, "type", "")))
        return out

    def _on_evidence_clicked(self, item: QListWidgetItem) -> None:
        ev = item.data(Qt.ItemDataRole.UserRole) or ""
        if ev:
            self.evidence_requested.emit(self._concept_id, ev)

    def _open_compare(self) -> None:
        """Open the comparison dialog against the first peer / next-level point."""
        try:
            from expert_anything.core.map_context import siblings, next_level

            cands = siblings(self._asset, self._concept_id, max_n=1) + next_level(
                self._asset, self._concept_id, max_n=1
            )
            target = cands[0]["id"] if cands else None
        except Exception:
            target = None
        if target is None:
            return
        dlg = ConceptCompareDialog(
            self._asset, self._concept_id, target, self._learner, self._teacher, self
        )
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

    focus_requested = Signal(str)  # concept id
    teach_requested = Signal(str)  # concept name
    incorporate_requested = Signal(str, str)  # a_id, b_id (sink into teacher)

    def __init__(
        self,
        asset: KnowledgeAsset,
        id_a: str,
        id_b: str,
        learner_state: dict,
        teacher: TeacherModel | None = None,
        parent=None,
    ):
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
        a_lbl.setStyleSheet("font-size: 17px; font-weight: bold; color: #0c3d5f;")
        sel.addWidget(a_lbl)
        sel.addWidget(QLabel("⇄"))
        self._b_combo = QComboBox()
        self._b_combo.setStyleSheet(
            "QComboBox { border: 1px solid #B0BEC5; border-radius: 6px;"
            "padding: 4px 10px; font-size: 15px; }"
        )
        self._populate_candidates()
        sel.addWidget(self._b_combo, 1)
        go_btn = QPushButton(_t("compare_select"))
        go_btn.setStyleSheet(
            "QPushButton { background-color: #00695C; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 14.5px; font-weight: bold; }"
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

            for item in siblings(self._asset, self._id_a, max_n=12) + next_level(
                self._asset, self._id_a, max_n=12
            ):
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
                    seen.index(self._id_b) if self._id_b in seen else 0
                )
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
            r = compare_concepts(
                self._asset,
                self._id_a,
                self._id_b,
                teacher=self._teacher,
                learner_state=self._learner,
            )
        except ValueError:
            body = QLabel(_t("panel_not_exist"))
            self._scroll.setWidget(body)
            return

        # similarity banner
        sim_pct = f"{r['similarity']:.0%}"
        sim_word = (
            _t("compare_sim_high") if r["similarity"] >= 0.6 else _t("compare_sim_low")
        )
        banner = QLabel(f"{_t('compare_similarity', pct=sim_pct)} · {sim_word}")
        banner.setStyleSheet(
            "background-color: #E0F2F1; color: #00695C; border-radius: 6px;"
            "padding: 6px 10px; font-size: 14px; font-weight: bold;"
        )
        lay.addWidget(banner)

        # side-by-side columns
        cols = QHBoxLayout()
        cols.setSpacing(12)
        cols.addWidget(
            self._col(r["a"], _t("compare_definition"), r["rel_only_a"], is_a=True), 1
        )
        cols.addWidget(
            self._col(r["b"], _t("compare_definition"), r["rel_only_b"], is_a=False), 1
        )
        lay.addLayout(cols)

        # evidence points — color-coded by the semantic type embedded in [brackets]
        lay.addWidget(
            _sec_title(_t("compare_relations") + " · " + _t("compare_notes"), "#00695C")
        )
        from expert_anything.core.decoder import REL_SEMANTICS
        for p in r["points"]:
            # detect [semantic_label] in the point text and pick a colour
            sem_color = "#78909C"  # default grey
            for sem_key, sem_info in REL_SEMANTICS.items():
                tag = f"[{sem_info['label']}]"
                if tag in p:
                    sem_color = sem_info["color"]
                    break
            lbl = QLabel("• " + p)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"font-size: 14.5px; color: #37474F; background-color: {sem_color}18;"
                f"border-left: 3px solid {sem_color}; border-radius: 4px; padding: 6px 8px;"
            )
            lay.addWidget(lbl)

        # learning hint
        hint = QLabel(r["learning_hint"])
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "font-size: 15px; color: #1B5E20; background-color: #E8F5E9;"
            "border-radius: 6px; padding: 8px 10px; font-weight: bold;"
        )
        lay.addWidget(hint)

        # Direct relation + learning order banner
        if r.get("direct_rel") or r.get("learn_order"):
            info_banner = QFrame()
            info_banner.setStyleSheet(
                "QFrame { background-color: #E3F2FD; border-radius: 6px;"
                "padding: 0; }"
            )
            info_lay = QVBoxLayout(info_banner)
            info_lay.setContentsMargins(10, 8, 10, 8)
            info_lay.setSpacing(4)

            if r.get("direct_rel"):
                dr = r["direct_rel"]
                if dr["a_to_b"]:
                    order_text = f"{r['a']['name']}  →[{dr['sem_label']}]→  {r['b']['name']}"
                else:
                    order_text = f"{r['b']['name']}  →[{dr['sem_label']}]→  {r['a']['name']}"
                dr_lbl = QLabel(_t("compare_direct_rel", rel=order_text))
                dr_lbl.setWordWrap(True)
                dr_lbl.setStyleSheet(
                    f"font-size: 14.5px; color: {dr['sem_color']}; font-weight: 600;"
                )
                info_lay.addWidget(dr_lbl)

            if r.get("learn_order"):
                if r["learn_order"] == "a_first":
                    order_str = f"{r['a']['name']}  →  {r['b']['name']}"
                else:
                    order_str = f"{r['b']['name']}  →  {r['a']['name']}"
                lo_lbl = QLabel(_t("compare_learn_order", order=order_str))
                lo_lbl.setWordWrap(True)
                lo_lbl.setStyleSheet(
                    "font-size: 14.5px; color: #0D47A1; font-weight: 500;"
                )
                info_lay.addWidget(lo_lbl)

            lay.addWidget(info_banner)

        # Actionable learning suggestions
        suggestions = r.get("suggestions", [])
        if suggestions:
            lay.addWidget(_sec_title(_t("compare_suggestions_title"), "#E65100"))
            for s in suggestions:
                s_lbl = QLabel(s)
                s_lbl.setWordWrap(True)
                s_lbl.setStyleSheet(
                    "font-size: 14.5px; color: #BF360C; background-color: #FFF3E0;"
                    "border-radius: 6px; padding: 8px 10px; font-weight: 500;"
                )
                lay.addWidget(s_lbl)

        # actions
        act = QHBoxLayout()
        for cid, key in (
            (r["a"]["id"], "compare_learn_a"),
            (r["b"]["id"], "compare_learn_b"),
        ):
            btn = QPushButton(_t("compare_teach", name=self._name_of(cid)))
            btn.setStyleSheet(
                "QPushButton { background-color: #1565C0; color: white; border: none;"
                "border-radius: 6px; padding: 6px 14px; font-size: 14px; font-weight: bold; }"
                "QPushButton:hover { background-color: #0D47A1; }"
            )
            btn.clicked.connect(
                lambda checked=False, c=cid: self.teach_requested.emit(self._name_of(c))
            )
            act.addWidget(btn)

        # sink the comparison into the Teacher Model (bridging anchors +
        # mastery gap → the weaker concept is pushed up the teaching order)
        self._incorporate_btn = QPushButton(_t("compare_incorporate"))
        self._incorporate_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #6D4C41;"
            "border: 1px solid #BCAAA4; border-radius: 6px; padding: 6px 14px;"
            "font-size: 14px; }"
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

    def _col(
        self, info: dict, def_title: str, rel_only: list[str], is_a: bool
    ) -> QWidget:
        """One concept column: chapter, definition, unique relations, notes."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(QLabel(""))  # spacer keeps the two columns aligned

        name = QLabel(info["name"])
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 18px; font-weight: bold; color: #0c3d5f;")
        lay.addWidget(name)

        m = float(info.get("mastery", 0.0))
        m_lbl = QLabel(_t("panel_mastery", m=m))
        m_lbl.setStyleSheet(
            f"background-color: {mastery_color(m)}; color: white;"
            "padding: 2px 10px; border-radius: 9px; font-size: 13px; font-weight: bold;"
        )
        lay.addWidget(m_lbl)

        ch = info.get("chapter", "")
        if ch:
            c_lbl = QLabel(_t("chapter_label", ch=ch))
            c_lbl.setStyleSheet("font-size: 13.5px; color: #0284C7;")
            lay.addWidget(c_lbl)

        ev_n = int(info.get("evidence_count", 0))
        ev_lbl = QLabel(_t("compare_evidence", n=ev_n))
        ev_lbl.setStyleSheet("font-size: 13.5px; color: #2E7D32;")
        lay.addWidget(ev_lbl)

        # definition
        if info.get("definition"):
            d = QLabel(info["definition"])
            d.setWordWrap(True)
            d.setStyleSheet(
                "font-size: 14.5px; color: #37474F; background-color: #F5F7F8;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(d)

        # unique relations (the high-signal part)
        if rel_only:
            lay.addWidget(_sec_title(_t("compare_relations"), "#0284C7"))
            for rr in rel_only[:4]:
                lbl = QLabel("• " + rr)
                lbl.setWordWrap(True)
                lbl.setStyleSheet("font-size: 14px; color: #0369A1;")
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
            lbl.setStyleSheet("color: #757575; font-size: 14px;")
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
            "border-radius: 13px; font-size: 14px; font-weight: bold;"
        )
        row.addWidget(rank_lbl)

        # name + status
        col = QVBoxLayout()
        col.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        n = QLabel(name)
        n.setStyleSheet("font-size: 15px; font-weight: bold; color: #1F2933;")
        name_row.addWidget(n)
        badge = item.get("badge", "")
        if badge:
            bmap = {
                "hot": ("🔥 " + _t("badge_hot"), "#D32F2F"),
                "important": ("⭐ " + _t("badge_important"), "#B45309"),
                "new": ("💡 " + _t("badge_new"), "#0284C7"),
            }
            if badge in bmap:
                text, color = bmap[badge]
                name_row.addWidget(tag_chip(text, color))
        if cid in completed:
            name_row.addWidget(tag_chip(_t("legend_mastered"), "#2E7D32"))
        for tag in tags[:3]:
            color = {
                "weak": "#F44336",
                "anom": "#E67828",
                "foundation": "#0284C7",
                "ready": "#2E7D32",
                "blocked": "#78909C",
                "path": "#64748B",
                "stuck": "#B71C1C",
            }.get(tag, "#64748B")
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
        hint.setStyleSheet("color: #9E9E9E; font-size: 12.5px;")
        row.addWidget(hint)

        rung.mousePressEvent = lambda e, c=cid: self.concept_clicked.emit(c)
        return rung


