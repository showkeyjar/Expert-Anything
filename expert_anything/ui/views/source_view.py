"""Source text view: original content with concept highlighting and search."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core.learner import get_note, has_note, is_favorite
from expert_anything.ui.widgets._helpers import (
    open_feynman_check,
    open_note_editor,
)
from expert_anything.ui import theme
from expert_anything.ui.widgets.shared import PageHeader
from expert_anything.ui.widgets.source_widgets import SourceTextView


class _ChipButton(QPushButton):
    """Concept chip: single-click scrolls to the concept, double-click
    starts teaching. QPushButton has no doubleClicked signal, so we
    emit it from a mouseDoubleClickEvent override (clicked still fires
    on the first press of a double-click, which is the desired
    "scroll then teach" behaviour)."""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.doubleClicked.emit()
        event.accept()


class SourceView(QWidget):
    """View 4 — Read the original source with concept highlighting."""

    # Signals
    open_concept_panel = Signal(str)  # concept_id
    teach_requested = Signal(str)  # concept_name

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._search_box = None
        self._search_status = None
        self._source_widget = None
        self._concept_combo = None
        self._reader_star = None
        self._reader_note = None
        self._reader_recall = None
        self._focus_btn = None
        self._reader_note_box = None
        self._reader_note_summary = None
        self._reader_note_more = None
        self._focus_active = False
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._build()

    def refresh(self):
        # Mastery colours and concept anchors depend on learner state.  They
        # must be rebuilt after an evaluation, not only after asset switches.
        self._source_widget = None
        self._focus_active = False  # a rebuilt reader starts in full-text mode
        while self._root_layout.count():
            item = self._root_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._build()

    def _build(self):
        layout = self._root_layout

        layout.addWidget(
            self._view_header(
                self._main._t("nav_source"),
                self._main._t("source_subtitle"),
            )
        )

        if (
            self._main.current_asset_id
            and self._main.current_asset_id in self._main.assets
        ):
            asset = self._main.get_asset()
            layout.addWidget(self._build_search_bar())
            layout.addWidget(self._build_concept_toolbar(asset))

            # Concept chips — single-click scrolls to concept in text,
            # double-click jumps straight into teaching (reduces friction
            # in the reading → learning loop).
            chips_scroll = QScrollArea()
            chips_scroll.setWidgetResizable(True)
            chips_scroll.setFixedHeight(42)
            chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
            chips_host = QWidget()
            chips_layout = QHBoxLayout(chips_host)
            chips_layout.setContentsMargins(0, 0, 0, 0)
            chips_layout.setSpacing(6)
            from expert_anything.core.learner import normalize as _norm

            for c in asset.concepts if asset else []:
                # Color chip by mastery
                nk = _norm(c.name)
                m = float(
                    self._main.learner.get("concepts", {})
                    .get(nk, {})
                    .get("mastery", 0.0)
                )
                if m >= 0.6:
                    chip_bg, chip_color, chip_border = (
                        theme.SUCCESS_TINT,
                        theme.SUCCESS,
                        theme.SUCCESS,
                    )
                elif m >= 0.3:
                    chip_bg, chip_color, chip_border = (
                        theme.WARNING_TINT,
                        theme.WARNING,
                        theme.WARNING,
                    )
                elif m > 0:
                    chip_bg, chip_color, chip_border = (
                        theme.DANGER_TINT,
                        theme.DANGER,
                        theme.DANGER,
                    )
                else:
                    chip_bg, chip_color, chip_border = (
                        theme.SURFACE_MUTED,
                        theme.TEXT_FAINT,
                        theme.BORDER,
                    )
                chip = _ChipButton(c.name)
                chip.setStyleSheet(
                    f"QPushButton {{ background-color: {chip_bg}; color: {chip_color};"
                    f"border: 1px solid {chip_border}; border-radius: 10px;"
                    "padding: 3px 11px; font-size: 12.5px; }"
                    f"QPushButton:hover {{ background-color: {chip_border}; }}"
                )
                chip.clicked.connect(
                    lambda checked, cid=c.id: (
                        self._source_widget.scroll_to_concept(cid)
                        if self._source_widget
                        else None
                    )
                )
                chip.doubleClicked.connect(
                    lambda checked, cname=c.name: self.teach_requested.emit(cname)
                )
                chips_layout.addWidget(chip)
            chips_layout.addStretch()
            chips_scroll.setWidget(chips_host)
            layout.addWidget(chips_scroll)

            self._source_widget = SourceTextView()
            self._source_widget.set_asset(asset, self._main.learner)
            self._source_widget.concept_anchor_clicked.connect(
                lambda cid: self.open_concept_panel.emit(cid)
            )
            # Focus card actions: teach this concept / open its decoded scene /
            # leave focus mode (all deterministic, no LLM involved).
            self._source_widget.teach_requested.connect(
                lambda name: self.teach_requested.emit(name)
            )
            self._source_widget.decode_requested.connect(self._show_decode_scene)
            self._source_widget.focus_exit_requested.connect(self._exit_focus)
            # Persist the resting scroll offset so reading resumes in place
            # across view switches and app restarts (debounced in the widget).
            self._source_widget.reading_position_changed.connect(
                lambda _aid, _pos: self._main.save_learner_state()
            )
            layout.addWidget(self._source_widget, 1)

            # Mastery legend for the highlight colors
            legend = QHBoxLayout()
            legend.setContentsMargins(20, 4, 20, 4)
            legend.setSpacing(12)
            for color, label_key in [
                (theme.SUCCESS, "legend_mastered"),
                (theme.WARNING, "legend_partial"),
                (theme.DANGER, "legend_weak"),
                (theme.TEXT_FAINT, "legend_unstudied"),
            ]:
                dot = QLabel("●")
                dot.setStyleSheet(f"color: {color.replace('#', '#')}; font-size: 16px;")
                dot.setFixedWidth(16)
                legend.addWidget(dot)
                lbl = QLabel(self._main._t(label_key))
                lbl.setStyleSheet(
                    f"font-size: 12px; color: {theme.TEXT_MUTED};"
                )
                legend.addWidget(lbl)
            legend.addStretch()
            legend_widget = QWidget()
            legend_widget.setLayout(legend)
            legend_widget.setStyleSheet(
                f"background-color: {theme.SURFACE_MUTED};"
            )
            layout.addWidget(legend_widget)
        else:
            placeholder = QLabel(self._main._t("no_asset_placeholder"))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 15px; margin: 40px;"
            )
            layout.addWidget(placeholder)

    def _view_header(self, title, subtitle=""):
        return PageHeader(title, subtitle)

    def _build_search_bar(self):
        search_widget = QWidget()
        search_row = QHBoxLayout(search_widget)
        search_row.setContentsMargins(20, 8, 20, 8)
        search_row.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(self._main._t("search_in_source"))
        self._search_box.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; padding: 5px 10px;"
            f" font-size: 13px; background-color: {theme.SURFACE}; }}"
        )
        self._search_box.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_box, 1)

        self._search_status = QLabel("")
        self._search_status.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 12px;"
        )
        search_row.addWidget(self._search_status)

        sbtn = QPushButton(self._main._t("search_btn"))
        sbtn.setCursor(Qt.CursorShape.PointingHandCursor)
        sbtn.setStyleSheet(theme.secondary_button_style())
        sbtn.clicked.connect(self._on_search)
        search_row.addWidget(sbtn)

        return search_widget

    # -- concept-scoped reading tools (★ / 📝 / 🔍 聚焦) -----------------------
    def _build_concept_toolbar(self, asset):
        """Bookmark, own-words note and focused reading for ONE concept.

        The reading site is where the insight happens, so ★/📝 live here too;
        focus mode then re-projects the text onto that single concept
        (deterministic: source lines + evidence anchors only).
        """
        bar = QWidget()
        bar_lay = QVBoxLayout(bar)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.setSpacing(4)
        self._reader_note_expanded = False
        row_host = QWidget()
        row = QHBoxLayout(row_host)
        row.setContentsMargins(20, 0, 20, 8)
        row.setSpacing(6)
        bar_lay.addWidget(row_host)

        lbl = QLabel(self._main._t("reader_toolbar"))
        lbl.setStyleSheet(f"font-size: 12px; color: {theme.TEXT_MUTED};")
        row.addWidget(lbl)

        self._concept_combo = QComboBox()
        self._concept_combo.setObjectName("reader_concept_combo")
        self._concept_combo.setFixedWidth(220)
        self._concept_combo.setStyleSheet(
            f"QComboBox {{ border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; padding: 3px 8px;"
            f" font-size: 12.5px; background-color: {theme.SURFACE}; }}"
        )
        self._concept_combo.addItem(self._main._t("reader_pick_concept"), "")
        for c in asset.concepts if asset else []:
            self._concept_combo.addItem(c.name, c.id)
        self._concept_combo.currentIndexChanged.connect(
            self._on_reader_concept_changed
        )
        row.addWidget(self._concept_combo, 0)

        self._reader_star = QPushButton("☆")
        self._reader_star.setObjectName("reader_fav_btn")
        self._reader_star.setToolTip(self._main._t("fav_toggle_tip"))
        self._reader_star.setStyleSheet(
            f"QPushButton {{ background-color: {theme.WARNING_TINT};"
            f" color: {theme.WARNING}; border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px;"
            " padding: 2px 8px; font-size: 12.5px; }"
            f"QPushButton:hover {{ border-color: {theme.WARNING}; }}"
        )
        self._reader_star.clicked.connect(self._toggle_reader_favorite)
        row.addWidget(self._reader_star, 0)

        self._reader_note = QPushButton(self._main._t("note_edit"))
        self._reader_note.setObjectName("reader_note_btn")
        self._reader_note.setToolTip(self._main._t("note_hint"))
        self._reader_note.setStyleSheet(theme.secondary_button_style())
        self._reader_note.clicked.connect(self._edit_reader_note)
        row.addWidget(self._reader_note, 0)

        self._reader_recall = QPushButton(self._main._t("recall_btn"))
        self._reader_recall.setObjectName("reader_recall_btn")
        self._reader_recall.setToolTip(self._main._t("recall_btn_tip"))
        self._reader_recall.setStyleSheet(theme.secondary_button_style())
        self._reader_recall.clicked.connect(self._recall_reader)
        row.addWidget(self._reader_recall, 0)

        self._focus_btn = QPushButton(self._main._t("reader_focus_on"))
        self._focus_btn.setObjectName("reader_focus_btn")
        self._focus_btn.setToolTip(self._main._t("reader_focus_hint"))
        self._focus_btn.setStyleSheet(theme.secondary_button_style())
        self._focus_btn.clicked.connect(self._toggle_focus_read)
        row.addWidget(self._focus_btn, 0)
        row.addStretch()

        # Note summary — the learner's own words surface right where they read,
        # not only inside the editor. Long notes collapse to an excerpt with
        # an explicit expand toggle.
        self._reader_note_box = QWidget()
        self._reader_note_box.setObjectName("reader_note_box")
        note_row = QHBoxLayout(self._reader_note_box)
        note_row.setContentsMargins(20, 0, 20, 6)
        note_row.setSpacing(6)
        self._reader_note_summary = QLabel("")
        self._reader_note_summary.setObjectName("reader_note_summary_lbl")
        self._reader_note_summary.setWordWrap(True)
        self._reader_note_summary.setStyleSheet(
            f"font-size: 12px; color: {theme.TEXT_MUTED};"
            f" background-color: {theme.SURFACE_MUTED};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_SM}px; padding: 3px 8px;"
        )
        note_row.addWidget(self._reader_note_summary, 1)
        self._reader_note_more = QPushButton(self._main._t("reader_note_more"))
        self._reader_note_more.setObjectName("reader_note_more_btn")
        self._reader_note_more.setStyleSheet(theme.secondary_button_style())
        self._reader_note_more.clicked.connect(self._toggle_reader_note_more)
        note_row.addWidget(self._reader_note_more, 0)
        self._reader_note_box.setVisible(False)
        bar_lay.addWidget(self._reader_note_box)

        self._on_reader_concept_changed()
        return bar

    def _reader_concept(self) -> tuple[str, str]:
        if self._concept_combo is None:
            return "", ""
        return (
            self._concept_combo.currentText(),
            str(self._concept_combo.currentData() or ""),
        )

    def _on_reader_concept_changed(self, *_args):
        """Keep the ★/📝 labels and button availability in sync with the pick."""
        name, cid = self._reader_concept()
        has = bool(cid and name)
        if self._reader_star is not None:
            self._reader_star.setEnabled(has)
            self._reader_star.setText(
                "★" if has and is_favorite(self._main.learner, name) else "☆"
            )
        if self._reader_note is not None:
            self._reader_note.setEnabled(has)
            self._reader_note.setText(
                self._main._t("note_edit_has")
                if has and has_note(self._main.learner, name)
                else self._main._t("note_edit")
            )
        if self._focus_btn is not None:
            self._focus_btn.setEnabled(has)
        if self._reader_recall is not None:
            self._reader_recall.setEnabled(has)
        self._update_reader_note_summary(name if has else "")

    def _update_reader_note_summary(self, name: str) -> None:
        """Render the picked concept's note under the toolbar (if it has one).

        Notes were write-only from the reading seat: the learner typed their
        own words and they vanished.  Showing them here turns the note into a
        live reference while reading the source.
        """
        box = getattr(self, "_reader_note_box", None)
        if box is None:
            return
        text = str(get_note(self._main.learner, name) if name else "").strip()
        if not text:
            self._reader_note_expanded = False
            box.setVisible(False)
            return
        self._reader_note_expanded = bool(
            getattr(self, "_reader_note_expanded", False)
        )
        limit = 70
        long_note = len(text) > limit
        shown = text if (self._reader_note_expanded or not long_note) else (
            text[:limit] + "…"
        )
        self._reader_note_summary.setText(
            self._main._t("reader_note_summary", s=shown)
        )
        more = getattr(self, "_reader_note_more", None)
        if more is not None:
            more.setVisible(long_note)
            more.setText(
                self._main._t(
                    "reader_note_less"
                    if self._reader_note_expanded
                    else "reader_note_more"
                )
            )
        box.setVisible(True)

    def _toggle_reader_note_more(self):
        self._reader_note_expanded = not getattr(
            self, "_reader_note_expanded", False
        )
        name, cid = self._reader_concept()
        self._update_reader_note_summary(name if cid else "")

    def _toggle_reader_favorite(self):
        name, _cid = self._reader_concept()
        if not name:
            return
        from expert_anything.core.learner import save as save_learner, toggle_favorite

        toggle_favorite(self._main.learner, name)
        save_learner(self._main.learner)
        self._reader_star.setText(
            "★" if is_favorite(self._main.learner, name) else "☆"
        )

    def _edit_reader_note(self):
        name, _cid = self._reader_concept()
        if not name:
            return
        text = open_note_editor(self, self._main.learner, name)
        if text is None:  # cancelled
            return
        self._reader_note.setText(
            self._main._t("note_edit_has") if text else self._main._t("note_edit")
        )
        self._update_reader_note_summary(name)

    def _recall_reader(self):
        """Own-words recall check for the picked concept (deterministic)."""
        _name, cid = self._reader_concept()
        if not cid:
            return
        asset = self._main.get_asset()
        concept = asset.concept_by_id(cid) if asset is not None else None
        open_feynman_check(self, self._main.learner, asset, concept)

    def _toggle_focus_read(self):
        if self._focus_active:
            self._exit_focus()
            return
        _name, cid = self._reader_concept()
        if not cid or self._source_widget is None:
            return
        self._source_widget.set_focus_concept(cid)
        self._focus_active = True
        self._focus_btn.setText(self._main._t("reader_focus_off"))

    def _exit_focus(self):
        if self._source_widget is not None and self._focus_active:
            self._source_widget.set_focus_concept(None)
        self._focus_active = False
        if self._focus_btn is not None:
            self._focus_btn.setText(self._main._t("reader_focus_on"))

    def _show_decode_scene(self, concept_id: str):
        """Open the concept's decoded scene (deterministic renderer) in a dialog."""
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_id(concept_id)
        if concept is None:
            return
        try:
            from expert_anything.core import decoder

            scene = decoder.scene_for_concept(asset, concept)
        except Exception:
            scene = None
        if not scene or not scene.get("nodes"):
            return
        from expert_anything.ui.widgets.teach_widgets import DecoderSceneCard

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self._main._t('focus_decode_btn')} · {concept.name}")
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        card = DecoderSceneCard(
            scene,
            concept.name,
            definition=concept.definition or concept.summary or "",
            evidence=concept.evidence or [],
        )
        card.game_scored.connect(
            lambda score, c=concept: self._on_decode_scored(c, score)
        )
        lay.addWidget(card)
        dlg.exec()

    def _on_decode_scored(self, concept, score: float) -> None:
        """The decoded game's score re-enters the mastery loop (quiz channel)."""
        from expert_anything.core.learner import mark_completed, record_evaluation

        asset_id = self._main.current_asset_id or ""
        record_evaluation(
            self._main.learner,
            concept.name,
            asset_id,
            float(score),
            "",
            "decoder game",
            meta={
                "channel": "quiz",
                "style": "diagram",
                "vary": False,
                "review": False,
            },
        )
        if score >= 0.6:
            mark_completed(self._main.learner, asset_id, concept.id)
        self._main.save_learner_state()

    def _on_search(self):
        if self._source_widget is None:
            return
        term = self._search_box.text().strip()
        n = self._source_widget.search_all(term) if term else 0
        if n:
            self._search_status.setText(self._main._t("search_hits", n=n))
        else:
            self._search_status.setText(self._main._t("search_none"))


from PySide6.QtCore import Qt, Signal
