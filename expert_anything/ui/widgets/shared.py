"""Shared widget classes used across multiple views."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from expert_anything.core.i18n import t as _t
from expert_anything.ui import theme


class PageHeader(QFrame):
    """One page header, one look.

    Every view used to hand-roll this row and paint a 2px Material-blue
    underline beneath it, which is most of what made the app feel dated.
    The header now sits flat on the surface: title, muted subtitle, generous
    breathing room, and a hairline separator only.
    """

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("page_header")
        self.setStyleSheet(theme.page_header_style())
        # Keep the header compact when the page is taller than its content;
        # otherwise the hbox centres the title inside a giant empty band.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(10)
        self.title_label = QLabel(str(title))
        self.title_label.setStyleSheet(
            f"font-size: 19px; font-weight: 600; color: {theme.TEXT};"
        )
        lay.addWidget(self.title_label)
        self.subtitle_label = None
        if subtitle:
            self.subtitle_label = QLabel(str(subtitle))
            self.subtitle_label.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 13px;"
            )
            lay.addWidget(self.subtitle_label)
        self._layout = lay
        lay.addStretch()

    def add_widget(self, widget) -> None:
        """Append an accessory (e.g. a domain chip) before the trailing stretch."""
        self._layout.insertWidget(self._layout.count() - 1, widget)


class KnowledgeCard(QFrame):
    """A card widget displaying a knowledge concept with mastery status."""

    clicked = Signal(str)

    def __init__(self, concept_name, mastery=0.0, tags=None, is_top=False,
                 urgency=None, parent=None):
        super().__init__(parent)
        self.concept_name = concept_name
        self.mastery = mastery
        self.tags = tags or []
        self.is_top = is_top
        self.urgency = urgency  # urgency accent colour for left border
        self.setup_ui()
        self.apply_style()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title_label = QLabel(self.concept_name)
        title_label.setStyleSheet(
            f"font-size: 14.5px; font-weight: 600; color: {theme.TEXT};"
        )
        title_row.addWidget(title_label)

        # Tags
        for tag in self.tags[:2]:
            tag_label = QLabel(tag)
            tag_label.setStyleSheet(
                f"background-color: {theme.ACCENT_TINT}; color: {theme.ACCENT};"
                " padding: 2px 8px; border-radius: 6px; font-size: 11.5px;"
            )
            title_row.addWidget(tag_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Mastery indicator: colour dot + percent (no horizontal bar)
        dot_row = QHBoxLayout()
        dot_row.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {self._get_mastery_hex()}; font-size: 14px;")
        dot_row.addWidget(dot)
        pct = QLabel(f"{self.mastery:.0%}")
        pct.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 14px; font-weight: 600;"
        )
        dot_row.addWidget(pct)
        dot_row.addStretch()
        layout.addLayout(dot_row)

        # Action button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        learn_btn = QPushButton(_t("panel_teach"))
        learn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        learn_btn.setStyleSheet(theme.primary_button_style(compact=True))
        learn_btn.clicked.connect(lambda: self.clicked.emit(self.concept_name))
        btn_row.addWidget(learn_btn)
        layout.addLayout(btn_row)

    def apply_style(self):
        if self.is_top:
            self.setStyleSheet(
                f"QFrame {{ background-color: {theme.ACCENT_TINT};"
                f" border: 1px solid {theme.ACCENT_SOFT};"
                f" border-radius: {theme.RADIUS_LG}px; }}"
            )
        elif self.urgency:
            self.setStyleSheet(
                f"QFrame {{ background-color: {theme.SURFACE};"
                f" border: 1px solid {self.urgency};"
                f" border-radius: {theme.RADIUS_LG}px; }}"
                f"QFrame:hover {{ border-color: {theme.ACCENT_SOFT}; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {theme.SURFACE};"
                f" border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.RADIUS_LG}px; }}"
                f"QFrame:hover {{ border-color: {theme.ACCENT_SOFT}; }}"
            )

    def _get_mastery_color(self):
        if self.mastery >= 0.6:
            return "background-color: #4CAF50;"
        elif self.mastery >= 0.3:
            return "background-color: #FF9800;"
        else:
            return "background-color: #F44336;"

    def _get_mastery_hex(self):
        if self.mastery >= 0.6:
            return "#4CAF50"
        elif self.mastery >= 0.3:
            return "#FF9800"
        else:
            return "#F44336"

    def mousePressEvent(self, event):
        self.clicked.emit(self.concept_name)
        super().mousePressEvent(event)


class StatCard(QFrame):
    """Dashboard statistic card."""

    def __init__(self, icon, label, value, color, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        # Icon circle
        icon_circle = QFrame(self)
        icon_circle.setFixedSize(32, 32)
        icon_circle.setStyleSheet(
            f"background-color: {theme.rgba(color)}; border-radius: 16px;"
        )
        icon_layout = QVBoxLayout(icon_circle)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"color: {color}; font-size: 18px;")
        icon_layout.addWidget(icon_label)

        header = QHBoxLayout()
        header.addWidget(icon_circle)
        header.addWidget(QLabel(label))
        header.addStretch()
        layout.addLayout(header)

        value_widget = QLabel(str(value))
        value_widget.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: 600;"
        )
        layout.addWidget(value_widget)

        # Stat cards keep their natural height; a stretch inside the card made
        # them balloon into empty outlined boxes when the page had spare room.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_LG}px; }}"
        )
