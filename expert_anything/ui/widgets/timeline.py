"""Learning trajectory timeline — a Gantt-style visual of concept learning over time.

Each row is a concept; horizontal bars show when the concept was studied (each
dot = one evaluation, colored by score). This lets the learner see their
learning journey at a glance: when they started, what they revisited, and
where the gaps are.
"""

from __future__ import annotations

from datetime import datetime, timezone
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor as _QColor, QFont as _QFont, QPainter as _QPainter, QPen as _QPen
from PySide6.QtWidgets import QWidget

from expert_anything.core.i18n import t as _t


class LearningTimeline(QWidget):
    """Gantt-style timeline: rows = concepts, x-axis = days, dots = evaluations.

    Colors: green ≥0.6, amber ≥0.3, red <0.3. Concepts are ordered by first
    evaluation date so the learning journey reads top-to-bottom.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._min_height = 200
        self.setMinimumHeight(self._min_height)

    def set_data(self, history: list[dict]) -> None:
        """Build timeline data from learner history.

        history: [{"concept": str, "score": float, "at": ISO str, ...}]
        """
        if not history:
            self._items = []
            self.update()
            return

        # Parse timestamps and group by concept
        concept_events: dict[str, list[dict]] = {}
        all_dates: list[datetime] = []

        for h in history:
            name = h.get("concept", "?")
            score = float(h.get("score", 0.0))
            ts_str = h.get("at", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            all_dates.append(ts)
            concept_events.setdefault(name, []).append({
                "ts": ts,
                "score": score,
            })

        if not all_dates:
            self._items = []
            self.update()
            return

        # Sort concepts by first evaluation date
        for name in concept_events:
            concept_events[name].sort(key=lambda e: e["ts"])
        sorted_concepts = sorted(
            concept_events.items(),
            key=lambda kv: kv[1][0]["ts"]
        )

        self._items = [
            {"concept": name, "events": events}
            for name, events in sorted_concepts
        ]
        self._date_min = min(all_dates)
        self._date_max = max(all_dates)
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _t("timeline_empty"))
            return

        margin_l, margin_r, margin_t, margin_b = 120, 20, 20, 30
        plot_w = w - margin_l - margin_r
        plot_h = h - margin_t - margin_b
        n_concepts = len(self._items)
        row_h = plot_h / max(1, n_concepts)

        # Date range
        total_days = max(1, (self._date_max - self._date_min).days + 1)

        # Draw date gridlines (every ~7 days or every day if <14 days)
        painter.setPen(_QPen(_QColor("#F0F0F0"), 1))
        step = 7 if total_days > 14 else 1
        for d in range(0, total_days, step):
            x = margin_l + (d / total_days) * plot_w
            painter.drawLine(int(x), margin_t, int(x), margin_t + plot_h)
            if d % max(step, 7) == 0 and d < total_days:
                label_date = self._date_min.replace(hour=0, minute=0, second=0)
                from datetime import timedelta
                label_date = label_date + timedelta(days=d)
                painter.setPen(_QColor("#BDBDBD"))
                font = _QFont()
                font.setPointSize(8)
                painter.setFont(font)
                painter.drawText(
                    int(x - 15), margin_t + plot_h + 15, 50, 14,
                    Qt.AlignmentFlag.AlignLeft,
                    label_date.strftime("%m/%d"),
                )
                painter.setPen(_QPen(_QColor("#F0F0F0"), 1))

        # Draw rows
        for i, item in enumerate(self._items):
            y = margin_t + i * row_h + row_h / 2

            # Concept name (left margin)
            name = item["concept"]
            if len(name) > 16:
                name = name[:15] + "…"
            painter.setPen(_QColor("#455A64"))
            font = _QFont()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(
                4, int(y - row_h * 0.35), margin_l - 8, int(row_h * 0.7),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                name,
            )

            # Row separator
            painter.setPen(_QPen(_QColor("#F5F5F5"), 1))
            painter.drawLine(
                margin_l, int(margin_t + (i + 1) * row_h),
                margin_l + plot_w, int(margin_t + (i + 1) * row_h)
            )

            # Evaluation dots
            for ev in item["events"]:
                day_offset = (ev["ts"] - self._date_min).total_seconds() / 86400
                x = margin_l + (day_offset / total_days) * plot_w
                score = ev["score"]
                if score >= 0.6:
                    color = _QColor("#2E7D32")
                elif score >= 0.3:
                    color = _QColor("#F57C00")
                else:
                    color = _QColor("#C62828")
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                radius = 5 + score * 3
                painter.drawEllipse(int(x - radius), int(y - radius), int(radius * 2), int(radius * 2))
