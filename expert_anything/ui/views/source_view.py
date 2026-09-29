"""Source text view: original content with concept highlighting and search."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
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
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._build()

    def refresh(self):
        # Mastery colours and concept anchors depend on learner state.  They
        # must be rebuilt after an evaluation, not only after asset switches.
        self._source_widget = None
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
                    chip_bg, chip_color, chip_border = "#E8F5E9", "#2E7D32", "#A5D6A7"
                elif m >= 0.3:
                    chip_bg, chip_color, chip_border = "#FFF8E1", "#E65100", "#FFCC80"
                elif m > 0:
                    chip_bg, chip_color, chip_border = "#FFEBEE", "#C62828", "#EF9A9A"
                else:
                    chip_bg, chip_color, chip_border = "#F3E5F5", "#7B1FA2", "#E1BEE7"
                chip = _ChipButton(c.name)
                chip.setStyleSheet(
                    f"QPushButton {{ background-color: {chip_bg}; color: {chip_color};"
                    f"border: 1px solid {chip_border}; border-radius: 12px;"
                    "padding: 3px 12px; font-size: 13px; }"
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
            layout.addWidget(self._source_widget, 1)

            # Mastery legend for the highlight colors
            legend = QHBoxLayout()
            legend.setContentsMargins(20, 4, 20, 4)
            legend.setSpacing(12)
            for color, label_key in [
                ("#C8E6C9", "legend_mastered"),
                ("#FFF8E1", "legend_partial"),
                ("#FFEBEE", "legend_weak"),
                ("#FFF3B0", "legend_unstudied"),
            ]:
                dot = QLabel("●")
                dot.setStyleSheet(f"color: {color.replace('#', '#')}; font-size: 16px;")
                dot.setFixedWidth(16)
                legend.addWidget(dot)
                lbl = QLabel(self._main._t(label_key))
                lbl.setStyleSheet("font-size: 13px; color: #6B7A90;")
                legend.addWidget(lbl)
            legend.addStretch()
            legend_widget = QWidget()
            legend_widget.setLayout(legend)
            legend_widget.setStyleSheet("background-color: #FAFBFC;")
            layout.addWidget(legend_widget)
        else:
            placeholder = QLabel(self._main._t("no_asset_placeholder"))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #757575; font-size: 16px; margin: 40px;")
            layout.addWidget(placeholder)

    def _view_header(self, title, subtitle=""):
        header = QFrame()
        header.setStyleSheet(
            "background-color: white; border-bottom: 2px solid #1565C0;"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 7, 20, 7)
        lay.setSpacing(10)
        t = QLabel(str(title))
        t.setStyleSheet("font-size: 18px; font-weight: bold; color: #1F2933;")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(str(subtitle))
            s.setStyleSheet("color: #6B7A90; font-size: 13.5px;")
            lay.addWidget(s)
        lay.addStretch()
        return header

    def _build_search_bar(self):
        search_widget = QWidget()
        search_row = QHBoxLayout(search_widget)
        search_row.setContentsMargins(20, 8, 20, 8)
        search_row.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(self._main._t("search_in_source"))
        self._search_box.setStyleSheet(
            "QLineEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 5px 10px; font-size: 14.5px; background-color: white; }"
        )
        self._search_box.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_box, 1)

        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: #9E9E9E; font-size: 13px;")
        search_row.addWidget(self._search_status)

        sbtn = QPushButton(self._main._t("search_btn"))
        sbtn.setStyleSheet(
            "QPushButton { background-color: white; color: #1565C0;"
            "border: 1px solid #BBDEFB; border-radius: 6px;"
            "padding: 5px 14px; font-size: 14.5px; }"
            "QPushButton:hover { background-color: #E3F2FD; }"
        )
        sbtn.clicked.connect(self._on_search)
        search_row.addWidget(sbtn)

        return search_widget

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
