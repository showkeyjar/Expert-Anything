"""Shared widget classes used across multiple views."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from expert_anything.core.i18n import t as _t


class KnowledgeCard(QFrame):
    """A card widget displaying a knowledge concept with mastery status."""

    clicked = Signal(str)

    def __init__(self, concept_name, mastery=0.0, tags=None, is_top=False, parent=None):
        super().__init__(parent)
        self.concept_name = concept_name
        self.mastery = mastery
        self.tags = tags or []
        self.is_top = is_top
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
        font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        title_label.setFont(font)
        title_row.addWidget(title_label)

        # Tags
        for tag in self.tags[:2]:
            tag_label = QLabel(tag)
            tag_label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    padding: 2px 8px;
                    border-radius: 4px;
                    font-size: 10px;
                }
            """)
            title_row.addWidget(tag_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Mastery indicator: colour dot + percent (no horizontal bar)
        dot_row = QHBoxLayout()
        dot_row.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {self._get_mastery_hex()}; font-size: 12px;")
        dot_row.addWidget(dot)
        pct = QLabel(f"{self.mastery:.0%}")
        pct.setStyleSheet("color: #616161; font-size: 12px; font-weight: bold;")
        dot_row.addWidget(pct)
        dot_row.addStretch()
        layout.addLayout(dot_row)

        # Action button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        learn_btn = QPushButton(_t("panel_teach"))
        learn_btn.setStyleSheet("""
            QPushButton {
                background-color: #1565C0;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0D47A1;
            }
        """)
        learn_btn.clicked.connect(lambda: self.clicked.emit(self.concept_name))
        btn_row.addWidget(learn_btn)
        layout.addLayout(btn_row)

    def apply_style(self):
        if self.is_top:
            self.setStyleSheet("""
                QFrame {
                    background-color: #E3F2FD;
                    border: 2px solid #1565C0;
                    border-radius: 12px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                }
                QFrame:hover {
                    border: 1px solid #90CAF9;
                }
            """)

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
        icon_circle.setStyleSheet(f"background-color: {color}20; border-radius: 16px;")
        icon_layout = QVBoxLayout(icon_circle)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"color: {color}; font-size: 16px;")
        icon_layout.addWidget(icon_label)

        header = QHBoxLayout()
        header.addWidget(icon_circle)
        header.addWidget(QLabel(label))
        header.addStretch()
        layout.addLayout(header)

        value_widget = QLabel(str(value))
        value_widget.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
        layout.addWidget(value_widget)
        layout.addStretch()

        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 10px;
            }
        """)
