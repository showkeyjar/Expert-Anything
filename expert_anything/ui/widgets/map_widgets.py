from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from expert_anything.core.i18n import t as _t


class MapLegend(QFrame):
    """A horizontal row of visual chips explaining the cognitive map.

    Two rows:
    - Node chips: mastery levels + special node states.  The row rebuilds via
      :meth:`set_mode` when the graph switches heatmap modes — a legend that
      keeps describing grey/amber/green while every node is painted red→green
      heat is actively lying to the learner.
    - Edge chips: 6 semantic relation types with their matching colors, so the
      learner can read structural meaning (causes / part-of / prerequisite / …)
      at a glance instead of guessing what each line color means.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        # Row 1 — node chips (rebuilt on mode change)
        self._node_host = QWidget()
        self._node_row = QHBoxLayout(self._node_host)
        self._node_row.setContentsMargins(0, 0, 0, 0)
        self._node_row.setSpacing(14)
        outer.addWidget(self._node_host)
        self.set_mode()

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

        # Direction key: colour says *what* the relation is, the marker says
        # *which way* it points. Without this line the arrows are guesswork.
        direction = QLabel(_t("legend_direction"))
        direction.setStyleSheet("font-size: 11px; color: #90A4AE;")
        outer.addWidget(direction)

        self.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
            "QLabel { font-size: 12px; color: #455A64; }"
        )

    # -- mode adaptation ------------------------------------------------------ #

    def set_mode(
        self,
        mastery_heat: bool = False,
        density: bool = False,
        hop2: bool = False,
    ) -> None:
        """Rebuild the node chip row for the graph's current display mode.

        ``mastery_heat`` / ``density`` replace the three static mastery chips
        with a gradient scale (they repaint every node fill); ``hop2`` adds a
        chip for the dimmed second-ring nodes.
        """
        row = self._node_row
        self._clear_row(row)
        if mastery_heat:
            row.addWidget(
                self._gradient_chip(
                    "qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                    "stop:0 #C62828, stop:0.5 #FFA000, stop:1 #2E7D32)",
                    f"{_t('legend_heat_low')} → {_t('legend_heat_high')}",
                )
            )
        elif density:
            row.addWidget(
                self._gradient_chip(
                    "qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                    "stop:0 #1A237E, stop:0.5 #FFD54F, stop:1 #C62828)",
                    f"{_t('legend_density_low')} → {_t('legend_density_high')}",
                )
            )
        else:
            row.addWidget(self._chip("#E1E4E8", "#78909C", solid=1, text=_t("legend_unstudied")))
            row.addWidget(self._chip("#FDEBCE", "#78909C", solid=1, text=_t("legend_partial")))
            row.addWidget(self._chip("#C5E6C6", "#78909C", solid=1, text=_t("legend_mastered")))
        # Special states survive every fill mode (border semantics, §3 orthogonal)
        row.addWidget(self._chip("#E1E4E8", "#E67828", solid=1, dashed=True, text=_t("legend_frontier")))
        row.addWidget(self._chip("#E1E4E8", "#E67828", solid=3, text=_t("legend_anomaly")))
        row.addWidget(self._chip("#E1E4E8", "#0284C7", solid=3, text=_t("legend_current")))
        row.addWidget(self._chip("#FFFFFF", "#90A4AE", solid=1, dashed=True, text="◌ " + _t("legend_unanchored")))
        if hop2:
            row.addWidget(self._chip("#EDF0F3", "#B0BEC5", solid=1, text=_t("legend_hop2_node")))
        row.addStretch()

    @staticmethod
    def _clear_row(row: QHBoxLayout) -> None:
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # -- chip builders --------------------------------------------------------- #

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

    def _gradient_chip(self, gradient: str, text: str) -> QWidget:
        """A small horizontal gradient bar + label — for heatmap scale rows."""
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(5)
        box = QFrame()
        box.setFixedSize(48, 12)
        box.setStyleSheet(
            f"QFrame {{ background: {gradient}; border: 1px solid #90A4AE;"
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
