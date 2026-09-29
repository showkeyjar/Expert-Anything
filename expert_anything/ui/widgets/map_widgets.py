from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from expert_anything.core.i18n import t as _t


class MapLegend(QFrame):
    """A horizontal row of visual chips explaining the cognitive map.

    Two rows:
    - Node chips: mastery levels + special node states.
    - Edge chips: 6 semantic relation types with their matching colors, so the
      learner can read structural meaning (causes / part-of / prerequisite / …)
      at a glance instead of guessing what each line color means.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        # Row 1 — node mastery chips
        node_row = QHBoxLayout()
        node_row.setContentsMargins(0, 0, 0, 0)
        node_row.setSpacing(14)
        node_row.addWidget(self._chip("#E1E4E8", "#78909C", solid=1, text=_t("legend_unstudied")))
        node_row.addWidget(self._chip("#FDEBCE", "#78909C", solid=1, text=_t("legend_partial")))
        node_row.addWidget(self._chip("#C5E6C6", "#78909C", solid=1, text=_t("legend_mastered")))
        node_row.addWidget(self._chip("#E1E4E8", "#E67828", solid=1, dashed=True, text=_t("legend_frontier")))
        node_row.addWidget(self._chip("#E1E4E8", "#E67828", solid=3, text=_t("legend_anomaly")))
        node_row.addWidget(self._chip("#E1E4E8", "#0284C7", solid=3, text=_t("legend_current")))
        node_row.addStretch()
        outer.addLayout(node_row)

        # Row 2 — edge relation type chips
        edge_row = QHBoxLayout()
        edge_row.setContentsMargins(0, 0, 0, 0)
        edge_row.setSpacing(12)
        from expert_anything.core.decoder import REL_SEMANTICS
        edge_title = QLabel(_t("legend_edges_title"))
        edge_title.setStyleSheet("font-size: 11px; color: #90A4AE; font-weight: bold;")
        edge_row.addWidget(edge_title)
        for sem_key in ("is_a", "part_of", "causes", "prereq", "contrast", "related"):
            sem_info = REL_SEMANTICS.get(sem_key, {})
            color = sem_info.get("color", "#78909C")
            edge_row.addWidget(self._edge_chip(color, _t("rel_" + sem_key)))
        edge_row.addStretch()
        outer.addLayout(edge_row)

        self.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
            "QLabel { font-size: 12px; color: #455A64; }"
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

    def _edge_chip(self, color: str, text: str) -> QWidget:
        """A small colored line segment + label for one relation type."""
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(4)
        line = QFrame()
        line.setFixedSize(20, 3)
        line.setStyleSheet(
            f"QFrame {{ background-color: {color}; border: none; border-radius: 1px; }}"
        )
        wrap.addWidget(line)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
        wrap.addWidget(lbl)
        host = QWidget()
        host.setLayout(wrap)
        host.setStyleSheet("background: transparent; border: none;")
        return host


# --------------------------------------------------------------------------- #
# NodeDetailCard — in-graph detail sidebar (changes per clicked node)
# --------------------------------------------------------------------------- #
