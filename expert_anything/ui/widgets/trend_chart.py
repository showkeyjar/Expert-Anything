from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor as _QColor, QFont as _QFont, QPainter as _QPainter, QPen as _QPen
from PySide6.QtWidgets import QWidget

from expert_anything.core.i18n import t as _t


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
        """items: [{"label": short concept name, "score": 0..1, "time": str}] in time order."""
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
        bar_centers: list[tuple[int, float]] = []  # (x_center, score) for trend line
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
            bar_centers.append((int(x + bar_w / 2), score))

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

        # trend line — connects bar tops to visualise improvement direction
        if len(bar_centers) >= 2:
            painter.setPen(_QPen(_QColor("#1565C0"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            points = []
            for cx, sc in bar_centers:
                py = margin_t + plot_h * (1 - sc)
                points.append((cx, int(py)))
            for j in range(len(points) - 1):
                painter.drawLine(points[j][0], points[j][1],
                                 points[j + 1][0], points[j + 1][1])
            # dots at each data point
            for cx, py in points:
                painter.setBrush(_QColor("#1565C0"))
                painter.setPen(_QPen(_QColor("#0D47A1"), 1))
                painter.drawEllipse(cx - 3, py - 3, 6, 6)

            # trend arrow: up / down / flat based on last 3 items
            recent = bar_centers[-3:] if len(bar_centers) >= 3 else bar_centers
            if len(recent) >= 2:
                delta = recent[-1][1] - recent[0][1]
                if delta > 0.1:
                    arrow_text = "↗"
                    arrow_color = _QColor("#2E7D32")
                elif delta < -0.1:
                    arrow_text = "↘"
                    arrow_color = _QColor("#C62828")
                else:
                    arrow_text = "→"
                    arrow_color = _QColor("#757575")
                painter.setPen(arrow_color)
                big = _QFont()
                big.setPointSize(12)
                big.setBold(True)
                painter.setFont(big)
                painter.drawText(w - margin_r - 30, margin_t + 16, arrow_text)

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
