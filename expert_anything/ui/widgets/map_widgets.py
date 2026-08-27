from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from expert_anything.core.i18n import t as _t


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
