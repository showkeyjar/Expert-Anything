"""Source text view: original content with concept highlighting and search."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)
from expert_anything.ui.widgets.source_widgets import SourceTextView


class SourceView(QWidget):
    """View 4 — Read the original source with concept highlighting."""

    # Signals
    open_concept_panel = Signal(str)  # concept_id

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._search_box = None
        self._search_status = None
        self._source_widget = None
        self._build()

    def refresh(self):
        pass  # rebuild handled by parent

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._view_header(
            self._main._t("nav_source"),
            self._main._t("source_subtitle"),
        ))

        if self._main.current_asset_id and self._main.current_asset_id in self._main.assets:
            asset = self._main.get_asset()
            layout.addWidget(self._build_search_bar())

            # Concept chips
            chips_scroll = QScrollArea()
            chips_scroll.setWidgetResizable(True)
            chips_scroll.setFixedHeight(42)
            chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
            chips_host = QWidget()
            chips_layout = QHBoxLayout(chips_host)
            chips_layout.setContentsMargins(0, 0, 0, 0)
            chips_layout.setSpacing(6)
            for c in (asset.concepts if asset else []):
                chip = QPushButton(c.name)
                chip.setStyleSheet(
                    "QPushButton { background-color: #F3E5F5; color: #7B1FA2;"
                    "border: 1px solid #E1BEE7; border-radius: 12px;"
                    "padding: 3px 12px; font-size: 11px; }"
                    "QPushButton:hover { background-color: #E1BEE7; }"
                )
                chip.clicked.connect(
                    lambda checked, cid=c.id: (
                        self._source_widget.scroll_to_concept(cid)
                        if self._source_widget else None
                    )
                )
                chips_layout.addWidget(chip)
            chips_layout.addStretch()
            chips_scroll.setWidget(chips_host)
            layout.addWidget(chips_scroll)

            self._source_widget = SourceTextView()
            self._source_widget.set_asset(asset)
            self._source_widget.concept_anchor_clicked.connect(
                lambda cid: self.open_concept_panel.emit(cid)
            )
            layout.addWidget(self._source_widget, 1)
        else:
            placeholder = QLabel(self._main._t("no_asset_placeholder"))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #757575; font-size: 14px; margin: 40px;")
            layout.addWidget(placeholder)

    def _view_header(self, title, subtitle=""):
        header = QFrame()
        header.setStyleSheet("background-color: white; border-bottom: 2px solid #1565C0;")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 7, 20, 7)
        lay.setSpacing(10)
        t = QLabel(str(title))
        t.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2933;")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(str(subtitle))
            s.setStyleSheet("color: #6B7A90; font-size: 11.5px;")
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
            "padding: 5px 10px; font-size: 12.5px; background-color: white; }"
        )
        self._search_box.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_box, 1)

        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: #9E9E9E; font-size: 11px;")
        search_row.addWidget(self._search_status)

        sbtn = QPushButton(self._main._t("search_btn"))
        sbtn.setStyleSheet(
            "QPushButton { background-color: white; color: #1565C0;"
            "border: 1px solid #BBDEFB; border-radius: 6px;"
            "padding: 5px 14px; font-size: 12.5px; }"
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
