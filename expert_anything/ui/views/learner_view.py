"""Learner model view: overview, review queue, history, export."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
    review_requested = Signal(str)  # concept_name, taught with vary=1
    review_all_requested = Signal(list)  # list of concept names to review
    export_report = Signal()  # text
    export_html = Signal()  # html

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._build()

    def refresh(self):
        # Evaluation updates learner.json while this view is often hidden.
        # Rebuild in place so switching back never shows stale mastery,
        # review, plan, or history information.
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
                self._main._t("nav_learner"),
                self._main._t(
                    "learner_subtitle", n=len(self._main.learner.get("concepts", {}))
                ),
            )
        )

        # Stat cards
        stats = self._main._compute_stats()
        due = due_for_review(self._main.learner, asset=self._main.get_asset())
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
        ov_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2933;")
        ov_lay.addWidget(ov_title)

        sum_lbl = QLabel(" ".join(parts))
        sum_lbl.setWordWrap(True)
        sum_lbl.setStyleSheet("font-size: 15px; color: #37474F;")
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
            dot.setStyleSheet(f"color: {color}; font-size: 12px;")
            t = QLabel(text)
            t.setStyleSheet("color: #757575; font-size: 13px;")
            leg_row.addWidget(dot)
            leg_row.addWidget(t)
        leg_row.addStretch()
        ov_lay.addLayout(leg_row)
        layout.addWidget(overview)

        # Study goal tracker
        from expert_anything.core.learner import study_goal_progress, set_study_goal

        goal_prog = study_goal_progress(self._main.learner)
        if goal_prog.get("active"):
            g_frame = QFrame()
            g_frame.setStyleSheet(
                "QFrame { background-color: #FFF3E0; border: 1px solid #FFCC80;"
                "border-radius: 10px; }"
            )
            g_lay = QVBoxLayout(g_frame)
            g_lay.setContentsMargins(16, 12, 16, 12)
            g_lay.setSpacing(6)

            g_header = QHBoxLayout()
            g_title = QLabel(self._main._t("goal_title"))
            g_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #E65100;")
            g_header.addWidget(g_title)

            if goal_prog["completed"]:
                status = QLabel(self._main._t("goal_completed"))
                status.setStyleSheet(
                    "background-color: #4CAF50; color: white; border-radius: 10px;"
                    "padding: 2px 10px; font-size: 13px; font-weight: bold;"
                )
            elif goal_prog["expired"]:
                status = QLabel(self._main._t("goal_expired"))
                status.setStyleSheet(
                    "background-color: #F44336; color: white; border-radius: 10px;"
                    "padding: 2px 10px; font-size: 13px; font-weight: bold;"
                )
            elif goal_prog["on_track"]:
                status = QLabel(self._main._t("goal_on_track"))
                status.setStyleSheet(
                    "background-color: #2E7D32; color: white; border-radius: 10px;"
                    "padding: 2px 10px; font-size: 13px; font-weight: bold;"
                )
            else:
                status = QLabel(self._main._t("goal_behind"))
                status.setStyleSheet(
                    "background-color: #E65100; color: white; border-radius: 10px;"
                    "padding: 2px 10px; font-size: 13px; font-weight: bold;"
                )
            g_header.addWidget(status)
            g_header.addStretch()
            g_lay.addLayout(g_header)

            # Progress bar
            progress_pct = min(100, int(goal_prog["progress"] * 100))
            bar_frame = QFrame()
            bar_frame.setFixedHeight(24)
            bar_frame.setStyleSheet(
                "QFrame { background-color: #FFE0B2; border-radius: 10px; }"
            )
            bar_lay = QHBoxLayout(bar_frame)
            bar_lay.setContentsMargins(0, 0, 0, 0)
            fill = QFrame()
            fill.setFixedWidth(int(bar_frame.width() * goal_prog["progress"]))
            fill.setStyleSheet("background-color: #FF9800; border-radius: 10px;")
            bar_text = QLabel(f"{goal_prog['delta']} / {goal_prog['target']}")
            bar_text.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #BF360C;"
            )
            bar_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g_lay.addWidget(bar_frame)
            g_lay.addWidget(bar_text)

            # Days left
            days_label = QLabel(
                self._main._t("goal_days_left", n=goal_prog["days_left"])
            )
            days_label.setStyleSheet("font-size: 13px; color: #BF360C;")
            g_lay.addWidget(days_label)
            layout.addWidget(g_frame)
        else:
            # Set goal button
            set_goal_btn = QPushButton(self._main._t("goal_set"))
            set_goal_btn.setStyleSheet(
                "QPushButton { background-color: #FFF3E0; color: #E65100;"
                "border: 1px solid #FFCC80; border-radius: 8px;"
                "padding: 8px 16px; font-size: 15px; font-weight: bold; }"
                "QPushButton:hover { background-color: #FFE0B2; }"
            )
            set_goal_btn.clicked.connect(lambda: self._on_set_goal())
            layout.addWidget(set_goal_btn)

        # Learning efficiency dashboard
        from expert_anything.core.learner import learning_efficiency

        eff = learning_efficiency(self._main.learner)
        if eff["total_sessions"] > 0:
            eff_frame = QFrame()
            eff_frame.setStyleSheet(
                "QFrame { background-color: #E3F2FD; border: 1px solid #90CAF9;"
                "border-radius: 10px; }"
            )
            eff_lay = QVBoxLayout(eff_frame)
            eff_lay.setContentsMargins(16, 12, 16, 12)
            eff_lay.setSpacing(8)

            eff_title = QLabel(self._main._t("efficiency_title"))
            eff_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #0D47A1;"
            )
            eff_lay.addWidget(eff_title)

            # Metric cards row
            metrics_row = QHBoxLayout()
            metrics_row.setSpacing(12)

            trend_icon = {
                "improving": "📈",
                "stable": "➡️",
                "declining": "📉",
                "unknown": "❓",
            }
            trend_color = {
                "improving": "#2E7D32",
                "stable": "#1565C0",
                "declining": "#C62828",
                "unknown": "#9E9E9E",
            }
            trend_key = {
                "improving": "eff_trend_up",
                "stable": "eff_trend_stable",
                "declining": "eff_trend_down",
                "unknown": "eff_trend_unknown",
            }

            metrics = [
                (self._main._t("eff_sessions"), str(eff["total_sessions"]), "#1565C0"),
                (
                    self._main._t("eff_concepts"),
                    str(eff["total_concepts_studied"]),
                    "#2E7D32",
                ),
                (self._main._t("eff_avg_score"), f"{eff['avg_score']:.0%}", "#7B1FA2"),
                (self._main._t("eff_roi"), f"{eff['efficiency']:.2f}", "#E65100"),
                (
                    self._main._t(trend_key[eff["trend"]]),
                    f"{trend_icon[eff['trend']]} {eff['recent_avg']:.0%}→{eff['early_avg']:.0%}",
                    trend_color[eff["trend"]],
                ),
            ]
            for label, value, color in metrics:
                card = QFrame()
                card.setStyleSheet(
                    f"QFrame {{ background-color: white; border: 1px solid {color}33;"
                    "border-radius: 8px; }}"
                )
                card_lay = QVBoxLayout(card)
                card_lay.setContentsMargins(8, 6, 8, 6)
                card_lay.setSpacing(2)
                val_lbl = QLabel(value)
                val_lbl.setStyleSheet(
                    f"font-size: 18px; font-weight: bold; color: {color};"
                )
                val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                card_lay.addWidget(val_lbl)
                lbl = QLabel(label)
                lbl.setStyleSheet("font-size: 11px; color: #78909C;")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                card_lay.addWidget(lbl)
                metrics_row.addWidget(card)

            metrics_row.addStretch()
            eff_lay.addLayout(metrics_row)
            layout.addWidget(eff_frame)

        # Milestones / achievements
        milestones = self._compute_milestones(
            total_c, mastered_c, weak_c, unstudied_c, avg_c, due
        )
        if milestones:
            ms_frame = QFrame()
            ms_frame.setStyleSheet(
                "QFrame { background-color: white; border: 1px solid #E0E0E0;"
                "border-radius: 10px; }"
            )
            ms_lay = QVBoxLayout(ms_frame)
            ms_lay.setContentsMargins(16, 12, 16, 12)
            ms_lay.setSpacing(8)

            ms_title = QLabel(self._main._t("milestones_title"))
            ms_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #1F2933;"
            )
            ms_lay.addWidget(ms_title)

            ms_row = QHBoxLayout()
            ms_row.setSpacing(10)
            for m in milestones:
                badge = QLabel(m["icon"])
                badge.setFixedSize(44, 44)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setStyleSheet(
                    f"font-size: 26px; background-color: {m['bg']};"
                    f"border: 2px solid {m['color']}; border-radius: 22px;"
                )
                badge.setToolTip(m["label"])
                ms_row.addWidget(badge)

                label = QLabel(m["label"])
                label.setStyleSheet(
                    f"font-size: 12.5px; color: {m['color']}; font-weight: 500;"
                    "max-width: 60px;"
                )
                label.setWordWrap(True)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ms_row.addWidget(label)

            ms_row.addStretch()
            ms_lay.addLayout(ms_row)
            layout.addWidget(ms_frame)

        # Style effectiveness — which teaching style works best for this learner
        from expert_anything.core.learner import style_effectiveness

        style_data = style_effectiveness(self._main.learner)
        if style_data:
            se_frame = QFrame()
            se_frame.setStyleSheet(
                "QFrame { background-color: #E0F2F1; border: 1px solid #80CBC4;"
                "border-radius: 10px; }"
            )
            se_lay = QVBoxLayout(se_frame)
            se_lay.setContentsMargins(16, 12, 16, 12)
            se_lay.setSpacing(8)

            se_title = QLabel(self._main._t("style_effect_title"))
            se_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #00695C;"
            )
            se_lay.addWidget(se_title)

            # Sort styles by avg score descending
            sorted_styles = sorted(style_data.items(), key=lambda x: -x[1]["avg"])
            best_style = sorted_styles[0][0] if sorted_styles else ""

            for style_name, data in sorted_styles:
                row = QHBoxLayout()
                row.setSpacing(10)
                s_label = QLabel(style_name)
                s_label.setStyleSheet(
                    "font-size: 14px; color: #37474F; font-weight: 500;"
                )
                row.addWidget(s_label)

                # Score bar
                avg = data["avg"]
                if avg >= 0.6:
                    bar_color = "#4CAF50"
                elif avg >= 0.3:
                    bar_color = "#FF9800"
                else:
                    bar_color = "#F44336"
                bar = QLabel(f"{avg:.0%}")
                bar.setStyleSheet(
                    f"background-color: {bar_color}; color: white; border-radius: 8px;"
                    "padding: 2px 8px; font-size: 13px; font-weight: bold;"
                )
                row.addWidget(bar)

                count = QLabel(self._main._t("style_count", n=data["count"]))
                count.setStyleSheet("font-size: 13px; color: #78909C;")
                row.addWidget(count)
                # Retention bucket (kept separate from the teaching avg by
                # style_effectiveness): shows whether material taught in
                # this style actually stuck across reviews.
                rv = data.get("review")
                if rv and rv.get("count"):
                    rtag = QLabel(
                        self._main._t(
                            "style_review_bucket",
                            n=rv["count"],
                            avg=f"{rv['avg']:.0%}",
                        )
                    )
                    rtag.setStyleSheet(
                        "font-size: 12px; color: #00897B;"
                        "background-color: rgba(0,137,123,0.08);"
                        "border-radius: 8px; padding: 2px 8px;"
                    )
                    row.addWidget(rtag)
                row.addStretch()

                if style_name == best_style and data["count"] >= 2:
                    best_tag = QLabel(self._main._t("style_best"))
                    best_tag.setStyleSheet(
                        "background-color: #00695C; color: white; border-radius: 10px;"
                        "padding: 2px 8px; font-size: 12px; font-weight: bold;"
                    )
                    row.addWidget(best_tag)

                se_lay.addLayout(row)

            if best_style:
                insight = QLabel(self._main._t("style_insight", style=best_style))
                insight.setStyleSheet(
                    "font-size: 13px; color: #00695C; padding: 4px 0;"
                )
                insight.setWordWrap(True)
                se_lay.addWidget(insight)

            layout.addWidget(se_frame)

        # Review consolidation gain — did vary=1 reviews actually help?
        # Visible Learning-Gain anchor (AGENTS.md §5): the review queue is
        # not done until its effect is measurable on this page.
        from expert_anything.core.learner import review_gain

        rg = review_gain(self._main.learner)
        if rg["review_count"] > 0:
            rg_frame = QFrame()
            rg_frame.setStyleSheet(
                "QFrame { background-color: #E8F5E9; border: 1px solid #A5D6A7;"
                "border-radius: 10px; }"
            )
            rg_lay = QVBoxLayout(rg_frame)
            rg_lay.setContentsMargins(16, 12, 16, 12)
            rg_lay.setSpacing(8)

            rg_title = QLabel(self._main._t("review_gain_title"))
            rg_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #2E7D32;"
            )
            rg_lay.addWidget(rg_title)

            if rg["measurable"] > 0:
                avg = QLabel(
                    self._main._t(
                        "review_gain_avg", gain=rg["avg_gain"], n=rg["measurable"]
                    )
                )
                avg_color = "#2E7D32" if rg["avg_gain"] >= 0 else "#C62828"
                avg.setStyleSheet(
                    f"font-size: 14px; font-weight: 600; color: {avg_color};"
                )
                rg_lay.addWidget(avg)
                for r in rg["concepts"][:5]:
                    gain_color = "#2E7D32" if r["gain"] >= 0 else "#C62828"
                    row = QLabel(
                        self._main._t(
                            "review_gain_row",
                            concept=r["concept"],
                            baseline=r["baseline"],
                            review=r["review_avg"],
                            n=r["n"],
                        )
                    )
                    row.setStyleSheet(
                        f"font-size: 13px; color: {gain_color};"
                    )
                    rg_lay.addWidget(row)
            else:
                nb = QLabel(self._main._t("review_gain_no_baseline"))
                nb.setStyleSheet("font-size: 13px; color: #546E7A;")
                nb.setWordWrap(True)
                rg_lay.addWidget(nb)

            layout.addWidget(rg_frame)
        else:
            # No review records yet: show an educational hint instead of
            # hiding the section (the metric must be discoverable).
            empty = QLabel(self._main._t("review_gain_empty"))
            empty.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            empty.setWordWrap(True)
            layout.addWidget(empty)

        # Mastery forecast — per-concept trend from teaching-channel
        # history only (review dips excluded, see mastery_prediction).
        # Rows are actionable: every concept links back into the teaching
        # loop, falling-trend concepts first (they need the intervention).
        from expert_anything.core.learner import mastery_prediction

        preds = []
        for rec in self._main.learner.get("concepts", {}).values():
            name = rec.get("name") or rec.get("key")
            if not name:
                continue
            p = mastery_prediction(self._main.learner, name)
            if p.get("trend") != "unknown":
                preds.append((name, p))
        # falling first (intervention), then rising (momentum)
        order = {"falling": 0, "rising": 1, "flat": 2}
        preds.sort(key=lambda x: order.get(x[1]["trend"], 3))
        if preds:
            pf_frame = QFrame()
            pf_frame.setStyleSheet(
                "QFrame { background-color: #F3E5F5; border: 1px solid #CE93D8;"
                "border-radius: 10px; }"
            )
            pf_lay = QVBoxLayout(pf_frame)
            pf_lay.setContentsMargins(16, 12, 16, 12)
            pf_lay.setSpacing(8)

            pf_title = QLabel(self._main._t("prediction_title"))
            pf_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #6A1B9A;"
            )
            pf_lay.addWidget(pf_title)

            # literal keys (not f-string composed) so the i18n scanner
            # can see them used
            trend_meta = {
                "rising": ("#2E7D32", "#E8F5E9", "↑",
                           self._main._t("prediction_rising")),
                "falling": ("#C62828", "#FFEBEE", "↓",
                            self._main._t("prediction_falling")),
                "flat": ("#546E7A", "#ECEFF1", "→",
                         self._main._t("prediction_flat")),
            }
            for name, p in preds[:5]:
                trend = p["trend"]
                fg, bg, arrow, trend_text = trend_meta.get(
                    trend, trend_meta["flat"]
                )
                row = QHBoxLayout()
                row.setSpacing(8)

                t_lbl = QLabel(f"{arrow} {trend_text}")
                t_lbl.setStyleSheet(
                    f"background-color: {bg}; color: {fg}; border-radius: 8px;"
                    "padding: 2px 8px; font-size: 12px; font-weight: bold;"
                )
                row.addWidget(t_lbl)

                n_lbl = QLabel(name)
                n_lbl.setStyleSheet(
                    "font-size: 14px; color: #37474F; font-weight: 500;"
                )
                row.addWidget(n_lbl)

                v = f"{p['predicted_mastery']:.0%}"
                if p.get("sessions_needed", -1) > 0:
                    detail = self._main._t(
                        "prediction_row", v=v, n=p["sessions_needed"]
                    )
                elif p.get("sessions_needed") == 0 or p.get("will_achieve"):
                    detail = self._main._t("prediction_achieved", v=v)
                else:
                    detail = self._main._t("prediction_no_est", v=v)
                d_lbl = QLabel(detail)
                d_lbl.setStyleSheet("font-size: 12px; color: #78909C;")
                row.addWidget(d_lbl, 1)

                go_btn = QPushButton(self._main._t("prediction_go"))
                go_btn.setStyleSheet(
                    "QPushButton { background-color: #6A1B9A; color: white;"
                    "border: none; border-radius: 6px; padding: 3px 10px;"
                    "font-size: 12px; }"
                    "QPushButton:hover { background-color: #4A148C; }"
                )
                go_btn.clicked.connect(
                    lambda checked, n=name: self.teach_requested.emit(n)
                )
                row.addWidget(go_btn)
                pf_lay.addLayout(row)

            layout.addWidget(pf_frame)

        # Knowledge blind spots — high-risk unlearned prerequisites
        asset = self._main.get_asset()
        if asset is not None:
            from expert_anything.core.learner import knowledge_blind_spots

            spots = knowledge_blind_spots(asset, self._main.learner)
            if spots:
                bs_frame = QFrame()
                bs_frame.setStyleSheet(
                    "QFrame { background-color: #FFEBEE; border: 1px solid #EF9A9A;"
                    "border-radius: 10px; }"
                )
                bs_lay = QVBoxLayout(bs_frame)
                bs_lay.setContentsMargins(16, 12, 16, 12)
                bs_lay.setSpacing(6)

                bs_title = QLabel(self._main._t("blind_spot_title"))
                bs_title.setStyleSheet(
                    "font-size: 16px; font-weight: bold; color: #C62828;"
                )
                bs_lay.addWidget(bs_title)

                bs_hint = QLabel(self._main._t("blind_spot_hint"))
                bs_hint.setStyleSheet("font-size: 13px; color: #B71C1C;")
                bs_hint.setWordWrap(True)
                bs_lay.addWidget(bs_hint)

                for sp in spots[:5]:
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    # Risk indicator
                    risk = sp["risk"]
                    if risk >= 3:
                        risk_color = "#C62828"
                        risk_bg = "#FFCDD2"
                    elif risk >= 1.5:
                        risk_color = "#E65100"
                        risk_bg = "#FFE0B2"
                    else:
                        risk_color = "#F57F17"
                        risk_bg = "#FFF9C4"
                    risk_lbl = QLabel(f"⚠ {risk:.1f}")
                    risk_lbl.setStyleSheet(
                        f"background-color: {risk_bg}; color: {risk_color};"
                        "border-radius: 8px; padding: 2px 8px; font-size: 13px; font-weight: bold;"
                    )
                    row.addWidget(risk_lbl)

                    name = QLabel(sp["name"])
                    name.setStyleSheet(
                        "font-size: 14px; color: #37474F; font-weight: 500;"
                    )
                    row.addWidget(name)

                    deps_text = "→ " + ", ".join(sp["dependents"][:3])
                    if len(sp["dependents"]) > 3:
                        deps_text += "..."
                    deps = QLabel(deps_text)
                    deps.setStyleSheet("font-size: 12px; color: #78909C;")
                    row.addWidget(deps, 1)

                    fix_btn = QPushButton(self._main._t("blind_spot_fix"))
                    fix_btn.setStyleSheet(
                        "QPushButton { background-color: #C62828; color: white; border: none;"
                        "border-radius: 6px; padding: 3px 10px; font-size: 12px; }"
                        "QPushButton:hover { background-color: #B71C1C; }"
                    )
                    fix_btn.clicked.connect(
                        lambda checked, n=sp["name"]: self.teach_requested.emit(n)
                    )
                    row.addWidget(fix_btn)
                    bs_lay.addLayout(row)

                layout.addWidget(bs_frame)

        # Study plan — time-boxed plan for today
        if asset is not None:
            from expert_anything.core.learner import generate_study_plan

            plan = generate_study_plan(asset, self._main.learner, minutes=30)
            if plan:
                sp_frame = QFrame()
                sp_frame.setStyleSheet(
                    "QFrame { background-color: #EDE7F6; border: 1px solid #B39DDB;"
                    "border-radius: 10px; }"
                )
                sp_lay = QVBoxLayout(sp_frame)
                sp_lay.setContentsMargins(16, 12, 16, 12)
                sp_lay.setSpacing(6)

                sp_header = QHBoxLayout()
                sp_title = QLabel(self._main._t("plan_title"))
                sp_title.setStyleSheet(
                    "font-size: 16px; font-weight: bold; color: #4527A0;"
                )
                sp_header.addWidget(sp_title)
                total_min = sum(p["est_minutes"] for p in plan)
                sp_time = QLabel(
                    self._main._t("plan_total_time", n=total_min, count=len(plan))
                )
                sp_time.setStyleSheet(
                    "background-color: #7B1FA2; color: white; border-radius: 10px;"
                    "padding: 2px 10px; font-size: 13px; font-weight: bold;"
                )
                sp_header.addWidget(sp_time)
                sp_header.addStretch()
                sp_lay.addLayout(sp_header)

                type_styles = {
                    "review": ("#E3F2FD", "#1565C0", "🔄"),
                    "new": ("#E8F5E9", "#2E7D32", "📚"),
                    "blind_spot": ("#FFEBEE", "#C62828", "⚠️"),
                }
                for i, p in enumerate(plan, 1):
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    bg, fg, icon = type_styles.get(p["type"], type_styles["new"])
                    step_lbl = QLabel(f"{i}. {icon} {p['name']}")
                    step_lbl.setStyleSheet(
                        f"font-size: 14px; color: {fg}; font-weight: 500;"
                    )
                    row.addWidget(step_lbl)
                    row.addStretch()
                    reason = QLabel(p["reason"])
                    reason.setStyleSheet("font-size: 12px; color: #78909C;")
                    row.addWidget(reason)
                    est = QLabel(f"{p['est_minutes']}min")
                    est.setStyleSheet(
                        f"background-color: {bg}; color: {fg}; border-radius: 6px;"
                        "padding: 1px 8px; font-size: 12px; font-weight: bold;"
                    )
                    row.addWidget(est)
                    go_btn = QPushButton(self._main._t("plan_start"))
                    go_btn.setStyleSheet(
                        "QPushButton { background-color: #4527A0; color: white; border: none;"
                        "border-radius: 6px; padding: 3px 10px; font-size: 12px; }"
                        "QPushButton:hover { background-color: #311B92; }"
                    )
                    go_btn.clicked.connect(
                        lambda checked, n=p["name"]: self.teach_requested.emit(n)
                    )
                    row.addWidget(go_btn)
                    sp_lay.addLayout(row)

                layout.addWidget(sp_frame)

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

    def _on_set_goal(self):
        """Open a dialog to set a study goal."""
        from PySide6.QtWidgets import QDialog, QSpinBox, QFormLayout, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle(self._main._t("goal_dialog_title"))
        dlg.setModal(True)
        form = QFormLayout(dlg)

        target_spin = QSpinBox()
        target_spin.setRange(1, 200)
        target_spin.setValue(10)
        form.addRow(self._main._t("goal_target_label"), target_spin)

        days_spin = QSpinBox()
        days_spin.setRange(1, 90)
        days_spin.setValue(7)
        form.addRow(self._main._t("goal_days_label"), days_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            from expert_anything.core.learner import set_study_goal

            set_study_goal(self._main.learner, target_spin.value(), days_spin.value())
            self.refresh()

    def _compute_milestones(
        self,
        total: int,
        mastered: int,
        weak: int,
        unstudied: int,
        avg: float,
        due: list,
    ) -> list:
        """Compute achievement badges based on learning progress.

        Milestones give the learner a sense of accomplishment and momentum —
        each badge represents a concrete step toward expertise.
        """
        ms = []

        # First concept mastered
        if mastered >= 1:
            ms.append(
                {
                    "icon": "🌱",
                    "label": self._main._t("ms_first_mastered"),
                    "color": "#2E7D32",
                    "bg": "#E8F5E9",
                }
            )

        # 10 concepts mastered
        if mastered >= 10:
            ms.append(
                {
                    "icon": "🌿",
                    "label": self._main._t("ms_ten_mastered"),
                    "color": "#2E7D32",
                    "bg": "#E8F5E9",
                }
            )

        # 50 concepts mastered
        if mastered >= 50:
            ms.append(
                {
                    "icon": "🌳",
                    "label": self._main._t("ms_fifty_mastered"),
                    "color": "#1B5E20",
                    "bg": "#C8E6C9",
                }
            )

        # All concepts mastered (perfect)
        if total > 0 and mastered == total:
            ms.append(
                {
                    "icon": "🏆",
                    "label": self._main._t("ms_all_mastered"),
                    "color": "#FF6F00",
                    "bg": "#FFF8E1",
                }
            )

        # 50%+ average mastery
        if avg >= 0.5 and total > 0:
            ms.append(
                {
                    "icon": "⭐",
                    "label": self._main._t("ms_half_avg"),
                    "color": "#1565C0",
                    "bg": "#E3F2FD",
                }
            )

        # 80%+ average mastery
        if avg >= 0.8 and total > 0:
            ms.append(
                {
                    "icon": "🎯",
                    "label": self._main._t("ms_high_avg"),
                    "color": "#0D47A1",
                    "bg": "#BBDEFB",
                }
            )

        # Kept up with reviews (no overdue)
        if due is not None and len(due) == 0 and mastered > 0:
            ms.append(
                {
                    "icon": "✅",
                    "label": self._main._t("ms_uptodate"),
                    "color": "#2E7D32",
                    "bg": "#E8F5E9",
                }
            )

        # Active learner (has some unstudied + some mastered = still going)
        if mastered > 0 and unstudied > 0:
            ms.append(
                {
                    "icon": "📖",
                    "label": self._main._t("ms_active"),
                    "color": "#7B1FA2",
                    "bg": "#F3E5F5",
                }
            )

        # Overcame weakness (had weak concepts but mastered > weak now)
        if mastered > 0 and mastered > weak and weak > 0:
            ms.append(
                {
                    "icon": "💪",
                    "label": self._main._t("ms_overcame"),
                    "color": "#E65100",
                    "bg": "#FFF3E0",
                }
            )

        return ms

    def _domain_profile_line(self):
        """Deterministic domain profile (Phase 4) for the header.

        A pure view over ``detect_user_profile``: nothing is inferred here,
        and an ``unknown`` judgement still shows the reason why. Every string
        goes through i18n — no hard-coded prose.
        """
        from expert_anything.core.learner import (
            detect_user_profile,
            profile_reason_text,
        )

        try:
            profile = detect_user_profile(self._main.learner)
        except Exception:
            return ""
        if not profile:
            return ""
        level = str(profile.get("level", "") or "")
        level_text = self._main._t("profile_level_" + level) if level else ""
        if not level_text or level_text == "profile_level_" + level:
            level_text = level
        domain = str(profile.get("template_name", "") or profile.get("domain_id", ""))
        reason = profile_reason_text(profile, self._main._t)
        if reason:
            return self._main._t(
                "profile_domain_item", domain=domain, level=level_text, reason=reason
            )
        return self._main._t(
            "profile_domain_item_short", domain=domain, level=level_text
        )

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
        domain_line = self._domain_profile_line()
        if domain_line:
            d = QLabel(domain_line)
            d.setStyleSheet("color: #1565C0; font-size: 13.5px; font-weight: bold;")
            lay.addWidget(d)
        lay.addStretch()
        return header

    def _build_concepts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(8)

        due = due_for_review(self._main.learner, asset=self._main.get_asset())
        if due:
            # Urgency summary bar
            overdue_n = sum(1 for d in due if d.get("urgency_tier") == "overdue")
            due_n = sum(1 for d in due if d.get("urgency_tier") == "due")
            soon_n = sum(1 for d in due if d.get("urgency_tier") == "soon")

            due_title = QLabel(self._main._t("due_title", n=len(due)))
            due_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #C62828; padding: 4px 0;"
            )
            layout.addWidget(due_title)

            # Urgency legend / summary chips
            summary_row = QHBoxLayout()
            summary_row.setSpacing(8)
            for tier, label_key, color in [
                ("overdue", "due_tier_overdue", "#C62828"),
                ("due", "due_tier_due", "#EF6C00"),
                ("soon", "due_tier_soon", "#2E7D32"),
            ]:
                count = {"overdue": overdue_n, "due": due_n, "soon": soon_n}[tier]
                chip = QLabel(f"● {self._main._t(label_key)}: {count}")
                chip.setStyleSheet(
                    f"color: {color}; font-size: 13.5px; font-weight: 600;"
                    f"background-color: {color}15; border-radius: 10px;"
                    f"padding: 2px 10px;"
                )
                summary_row.addWidget(chip)
            summary_row.addStretch()
            layout.addLayout(summary_row)

            # Quick review all button — start a continuous review session
            review_all_btn = QPushButton(self._main._t("review_all_btn", n=len(due)))
            review_all_btn.setStyleSheet(
                "QPushButton { background-color: #C62828; color: white;"
                "border: none; border-radius: 8px; padding: 8px 16px;"
                "font-size: 15px; font-weight: bold; }"
                "QPushButton:hover { background-color: #B71C1C; }"
            )
            review_all_btn.setToolTip(self._main._t("review_all_tip"))
            review_all_btn.clicked.connect(
                lambda: self.review_all_requested.emit([d["name"] for d in due])
            )
            layout.addWidget(review_all_btn)

            for d in due:
                tags = [self._main._t("due_days", d=d["days_since"])]
                if d.get("prereq_weak"):
                    tags.append(self._main._t("due_prereq_weak"))
                if d.get("gain_weak"):
                    # review-ineffective: consolidation failed, interval
                    # shortened — the learner should see WHY it came back
                    tags.append(self._main._t("due_gain_weak"))
                if d.get("gain_stretched"):
                    tags.append(self._main._t("due_gain_stretched"))
                if d.get("unanchored"):
                    # source-provenance tag: no passage to re-read, the
                    # review loop is the only consolidation channel
                    tags.append("◌ " + self._main._t("due_unanchored"))
                # Urgency tag with tier colour
                tier = d.get("urgency_tier", "due")
                tier_colors = {
                    "overdue": "#C62828",
                    "due": "#EF6C00",
                    "soon": "#2E7D32",
                }
                tier_labels = {
                    "overdue": self._main._t("due_tier_overdue"),
                    "due": self._main._t("due_tier_due"),
                    "soon": self._main._t("due_tier_soon"),
                }
                tier_color = tier_colors.get(tier, "#EF6C00")
                tags.append(tier_labels.get(tier, tier))

                card = KnowledgeCard(
                    concept_name=d["name"],
                    mastery=d["mastery"],
                    tags=tags,
                    urgency=tier_color,
                )
                card.clicked.connect(
                    lambda e, n=d["name"]: self.review_requested.emit(n)
                )
                layout.addWidget(card)
            due_hint = QLabel(self._main._t("due_hint"))
            due_hint.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            layout.addWidget(due_hint)

        section_title = QLabel(self._main._t("all_concepts"))
        section_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #2E7D32; padding: 4px 0;"
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
                "font-size: 14.5px; font-weight: bold; color: #0c4a6e;"
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
            "font-size: 16px; font-weight: bold; color: #2E7D32; padding: 4px 0;"
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

        # Error book — low-score evaluations that need targeted review
        from expert_anything.core.learner import weak_history

        weak_entries = weak_history(
            self._main.learner,
            asset_id=self._main.current_asset_id,
        )
        if weak_entries:
            eb_frame = QFrame()
            eb_frame.setStyleSheet(
                "QFrame { background-color: #FFF8E1; border: 1px solid #FFD54F;"
                "border-radius: 8px; }"
            )
            eb_lay = QVBoxLayout(eb_frame)
            eb_lay.setContentsMargins(12, 10, 12, 10)
            eb_lay.setSpacing(6)

            eb_header = QHBoxLayout()
            eb_title = QLabel(self._main._t("error_book_title"))
            eb_title.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #E65100;"
            )
            eb_header.addWidget(eb_title)
            eb_count = QLabel(self._main._t("error_book_count", n=len(weak_entries)))
            eb_count.setStyleSheet(
                "background-color: #FF6F00; color: white; border-radius: 10px;"
                "padding: 2px 10px; font-size: 13px; font-weight: bold;"
            )
            eb_header.addWidget(eb_count)
            eb_header.addStretch()
            eb_lay.addLayout(eb_header)

            for we in weak_entries[:5]:
                row = QHBoxLayout()
                row.setSpacing(8)
                w_concept = QLabel(we.get("concept", "?"))
                w_concept.setStyleSheet(
                    "font-size: 14px; color: #37474F; font-weight: 500;"
                )
                row.addWidget(w_concept)
                w_score = QLabel(f"{float(we.get('score', 0)):.0%}")
                w_score.setStyleSheet(
                    "background-color: #F44336; color: white; border-radius: 8px;"
                    "padding: 1px 8px; font-size: 12px; font-weight: bold;"
                )
                row.addWidget(w_score)
                w_fb = QLabel(str(we.get("feedback", ""))[:60])
                w_fb.setStyleSheet("font-size: 13px; color: #546E7A;")
                w_fb.setWordWrap(True)
                row.addWidget(w_fb, 1)
                # Retry button
                w_retry = QPushButton(self._main._t("error_book_retry"))
                w_retry.setStyleSheet(
                    "QPushButton { background-color: #E65100; color: white; border: none;"
                    "border-radius: 6px; padding: 3px 10px; font-size: 12px; }"
                    "QPushButton:hover { background-color: #BF360C; }"
                )
                w_retry.clicked.connect(
                    lambda checked, n=we.get("concept", ""): self.teach_requested.emit(
                        n
                    )
                )
                row.addWidget(w_retry)
                eb_lay.addLayout(row)

            eb_lay2 = QHBoxLayout()
            eb_lay2.addStretch()
            review_all_weak = QPushButton(self._main._t("error_book_review_all"))
            review_all_weak.setStyleSheet(
                "QPushButton { background-color: #E65100; color: white; border: none;"
                "border-radius: 6px; padding: 6px 14px; font-size: 14px; font-weight: bold; }"
                "QPushButton:hover { background-color: #BF360C; }"
            )
            review_all_weak.clicked.connect(
                lambda: self.review_all_requested.emit(
                    [we["concept"] for we in weak_entries]
                )
            )
            eb_lay2.addWidget(review_all_weak)
            eb_lay.addLayout(eb_lay2)

            layout.addWidget(eb_frame)

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
                           border-radius: 8px; font-size: 14px; }
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
                          border-radius: 6px; padding: 8px 16px; font-size: 15px; }
            QPushButton:hover { background-color: #388E3C; }
        """)
        export_btn.clicked.connect(lambda: self.export_report.emit())
        layout.addWidget(export_btn)

        export_html_btn = QPushButton(self._main._t("export_html"))
        export_html_btn.setStyleSheet("""
            QPushButton { background-color: #1565C0; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 15px; }
            QPushButton:hover { background-color: #0D47A1; }
        """)
        export_html_btn.clicked.connect(lambda: self.export_html.emit())
        layout.addWidget(export_html_btn)
        layout.addStretch()
        return widget


from PySide6.QtCore import Signal
