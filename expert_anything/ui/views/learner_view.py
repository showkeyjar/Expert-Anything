"""Learner model view: overview, review queue, history, export."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core.learner import due_for_review, normalize
from expert_anything.ui.widgets.shared import KnowledgeCard, StatCard
from expert_anything.ui.widgets.trend_chart import (
    TrendChartView,
    MasteryDistributionBar,
)


class LearnerView(QWidget):
    """View 6 — Learning progress overview, review queue, history, export."""

    # Signals
    teach_requested = Signal(str)  # concept_name
    export_report = Signal()  # text
    export_html = Signal()  # html

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._build()

    def refresh(self):
        pass

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(
            self._view_header(
                self._main._t("nav_learner"),
                self._main._t(
                    "learner_subtitle", n=len(self._main.learner.get("concepts", {}))
                ),
            )
        )

        # Stat cards
        stats = self._main._compute_stats()
        due = due_for_review(self._main.learner)
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)
        stat_row.addWidget(
            StatCard("✓", self._main._t("stat_mastered"), stats["mastered"], "#2E7D32")
        )
        stat_row.addWidget(
            StatCard("◐", self._main._t("stat_learning"), stats["learning"], "#B45309")
        )
        stat_row.addWidget(
            StatCard("⏰", self._main._t("stat_due"), len(due), "#C62828")
        )
        stat_row.addWidget(
            StatCard(
                "🧠",
                self._main._t("stat_cross"),
                len(self._main.learner.get("concepts", {})),
                "#0284C7",
            )
        )
        stat_row.addStretch()
        layout.addLayout(stat_row)

        # Overview narrative
        concepts_all = self._main.learner.get("concepts", {})
        total_c = len(concepts_all)
        mastered_c = sum(
            1 for v in concepts_all.values() if float(v.get("mastery", 0)) >= 0.6
        )
        learning_c = sum(
            1 for v in concepts_all.values() if 0.3 <= float(v.get("mastery", 0)) < 0.6
        )
        weak_c = sum(
            1 for v in concepts_all.values() if 0 < float(v.get("mastery", 0)) < 0.3
        )
        unstudied_c = sum(
            1 for v in concepts_all.values() if float(v.get("mastery", 0)) == 0
        )
        avg_c = (
            (sum(float(v.get("mastery", 0)) for v in concepts_all.values()) / total_c)
            if total_c
            else 0
        )

        weak_names = sorted(
            (
                v.get("name", k)
                for k, v in concepts_all.items()
                if 0 < float(v.get("mastery", 0)) < 0.6
            ),
            key=lambda n: float(
                next(
                    (
                        v.get("mastery", 0)
                        for k2, v in concepts_all.items()
                        if v.get("name") == n
                    ),
                    0,
                )
            ),
        )[:3]

        parts = []
        parts.append(
            self._main._t(
                "overview_summary",
                total=total_c,
                m=mastered_c,
                pct=(mastered_c / total_c) if total_c else 0.0,
                avg=avg_c,
            )
        )
        if due:
            parts.append(
                self._main._t("overview_due", n=len(due), first=due[0]["name"])
            )
        if weak_names:
            parts.append(self._main._t("overview_weak", names="、".join(weak_names)))
        elif total_c and mastered_c == total_c:
            parts.append(self._main._t("overview_all"))

        overview = QFrame()
        overview.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 10px; }"
        )
        ov_lay = QVBoxLayout(overview)
        ov_lay.setContentsMargins(16, 12, 16, 12)
        ov_lay.setSpacing(6)

        ov_title = QLabel(self._main._t("overview_title"))
        ov_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2933;")
        ov_lay.addWidget(ov_title)

        sum_lbl = QLabel(" ".join(parts))
        sum_lbl.setWordWrap(True)
        sum_lbl.setStyleSheet("font-size: 13px; color: #37474F;")
        ov_lay.addWidget(sum_lbl)

        dist = MasteryDistributionBar(
            {
                "mastered": mastered_c,
                "learning": learning_c,
                "weak": weak_c,
                "unstudied": unstudied_c,
            }
        )
        ov_lay.addWidget(dist)

        leg_row = QHBoxLayout()
        leg_row.setSpacing(6)
        for color, text in [
            ("#4CAF50", f"{self._main._t('legend_mastered')} {mastered_c}"),
            ("#FF9800", f"{self._main._t('legend_learning')} {learning_c}"),
            ("#F44336", f"{self._main._t('legend_weak')} {weak_c}"),
            ("#BDBDBD", f"{self._main._t('legend_unstudied')} {unstudied_c}"),
        ]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")
            t = QLabel(text)
            t.setStyleSheet("color: #757575; font-size: 11px;")
            leg_row.addWidget(dot)
            leg_row.addWidget(t)
        leg_row.addStretch()
        ov_lay.addLayout(leg_row)
        layout.addWidget(overview)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 4px; }
            QTabBar::tab { background: white; padding: 8px 16px; margin-right: 2px; }
            QTabBar::tab:selected { background: #E8F5E9; color: #2E7D32; }
        """)
        tabs.addTab(self._build_concepts_tab(), self._main._t("tab_concepts"))
        tabs.addTab(self._build_history_tab(), self._main._t("tab_history"))
        layout.addWidget(tabs)

    def _view_header(self, title, subtitle=""):
        header = QFrame()
        header.setStyleSheet(
            "background-color: white; border-bottom: 2px solid #1565C0;"
        )
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

    def _build_concepts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(8)

        due = due_for_review(self._main.learner)
        if due:
            due_title = QLabel(self._main._t("due_title", n=len(due)))
            due_title.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #C62828; padding: 4px 0;"
            )
            layout.addWidget(due_title)
            for d in due:
                card = KnowledgeCard(
                    concept_name=d["name"],
                    mastery=d["mastery"],
                    tags=[self._main._t("due_days", d=d["days_since"])],
                )
                card.clicked.connect(
                    lambda e, n=d["name"]: self.teach_requested.emit(n)
                )
                layout.addWidget(card)
            due_hint = QLabel(self._main._t("due_hint"))
            due_hint.setStyleSheet("font-size: 11px; color: #9E9E9E;")
            layout.addWidget(due_hint)

        section_title = QLabel(self._main._t("all_concepts"))
        section_title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #2E7D32; padding: 4px 0;"
        )
        layout.addWidget(section_title)

        groups = {}
        for key, rec in self._main.learner.get("concepts", {}).items():
            srcs = rec.get("sources", [])
            gid = srcs[0] if srcs else "?"
            groups.setdefault(gid, []).append(rec)

        for gid, items in groups.items():
            g_title = (
                self._main.assets.get(gid, {}).get(
                    "title", self._main._t("group_unknown")
                )
                if gid != "?"
                else self._main._t("group_other")
            )
            g_label = QLabel(self._main._t("group_fmt", title=g_title, n=len(items)))
            g_label.setStyleSheet(
                "font-size: 12.5px; font-weight: bold; color: #0c4a6e;"
                "background-color: #E8F0F8; border-radius: 4px; padding: 4px 8px; margin-top: 6px;"
            )
            layout.addWidget(g_label)

            for concept in sorted(items, key=lambda x: x.get("mastery", 0)):
                name = concept.get("name", concept.get("key", "?"))
                mastery = concept.get("mastery", 0)
                sources = concept.get("sources", [])
                tags = []
                if mastery < 0.3:
                    tags.append(self._main._t("legend_weak"))
                if len(sources) > 1:
                    tags.append(self._main._t("tag_cross"))
                card = KnowledgeCard(concept_name=name, mastery=mastery, tags=tags)
                card.clicked.connect(lambda e, n=name: self.teach_requested.emit(n))
                layout.addWidget(card)

        layout.addStretch()
        return widget

    def _build_history_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 20)

        history_title = QLabel(self._main._t("history_title"))
        history_title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #2E7D32; padding: 4px 0;"
        )
        layout.addWidget(history_title)

        trend = TrendChartView()
        hist_series = self._main.learner.get("history", [])
        trend_items = [
            {"label": h.get("concept", "?"), "score": float(h.get("score", 0))}
            for h in reversed(hist_series[-12:])
        ]
        trend.set_data(trend_items)
        trend.setStyleSheet(
            "background-color: white; border: 1px solid #E0E0E0; border-radius: 8px;"
        )
        layout.addWidget(trend)

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(
            [
                self._main._t("history_col_time"),
                self._main._t("history_col_concept"),
                self._main._t("history_col_score"),
                self._main._t("history_col_feedback"),
            ]
        )
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setStyleSheet("""
            QTableWidget { background-color: white; border: 1px solid #E0E0E0;
                           border-radius: 8px; font-size: 12px; }
            QTableWidget::item { padding: 6px; border-bottom: 1px solid #F0F0F0; }
            QHeaderView::section { background-color: #E8F5E9; color: #2E7D32;
                                   border: none; padding: 6px; font-weight: bold; }
        """)
        history = self._main.learner.get("history", [])
        table.setRowCount(len(history))
        for row, h in enumerate(history):
            at = h.get("at", "")[:19]
            score = float(h.get("score", 0))
            concept = h.get("concept", "?")
            feedback = h.get("feedback", "")[:80]

            at_item = QTableWidgetItem(at)
            con_item = QTableWidgetItem(concept)
            score_item = QTableWidgetItem(f"{score:.2f}")
            if score >= 0.6:
                score_item.setForeground(QColor("#2E7D32"))
            elif score >= 0.3:
                score_item.setForeground(QColor("#B45309"))
            else:
                score_item.setForeground(QColor("#C62828"))
            fb_item = QTableWidgetItem(feedback)
            table.setItem(row, 0, at_item)
            table.setItem(row, 1, con_item)
            table.setItem(row, 2, score_item)
            table.setItem(row, 3, fb_item)
        table.setColumnWidth(0, 170)
        table.setColumnWidth(1, 190)
        table.setColumnWidth(2, 60)
        if not history:
            table.setRowCount(1)
            empty = QTableWidgetItem(self._main._t("history_empty"))
            table.setSpan(0, 0, 1, 4)
            table.setItem(0, 0, empty)
        layout.addWidget(table)

        # Export buttons
        export_btn = QPushButton(self._main._t("export_report"))
        export_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 13px; }
            QPushButton:hover { background-color: #388E3C; }
        """)
        export_btn.clicked.connect(lambda: self.export_report.emit())
        layout.addWidget(export_btn)

        export_html_btn = QPushButton(self._main._t("export_html"))
        export_html_btn.setStyleSheet("""
            QPushButton { background-color: #1565C0; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 13px; }
            QPushButton:hover { background-color: #0D47A1; }
        """)
        export_html_btn.clicked.connect(lambda: self.export_html.emit())
        layout.addWidget(export_html_btn)
        layout.addStretch()
        return widget


from PySide6.QtCore import Signal
