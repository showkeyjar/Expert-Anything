"""Teacher model view: anomaly board, concept notes, recheck."""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)
from expert_anything.core.teacher import TeacherModel, build_teacher_model, kind_label
from expert_anything.ui.widgets._helpers import CollapsibleSection
from expert_anything.ui import theme
from expert_anything.ui.widgets.shared import PageHeader


def _match_anomaly_concept(asset, anomaly: dict):
    """Resolve the concept an anomaly card is about.

    Same name-in-text rule as ``teacher.anomaly_concept_ids`` (description /
    location carry the concept name).  Longest name wins so short sibling
    names cannot steal the match; no match returns None and the card stays
    read-only — never invent a target from a weak guess.
    """
    text = f"{anomaly.get('description', '')} {anomaly.get('location', '') or ''}"
    hits = [c for c in getattr(asset, "concepts", []) if c.name and c.name in text]
    return max(hits, key=lambda c: len(c.name)) if hits else None


class TeacherWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, asset, llm_client):
        super().__init__()
        self.asset = asset
        self.llm_client = llm_client

    def run(self):
        try:
            teacher = build_teacher_model(
                self.asset,
                llm=self.llm_client,
                on_progress=lambda stage, current, total, msg: None,
            )
            self.finished.emit(teacher)
        except Exception as e:
            self.error.emit(str(e))


class TeacherView(QWidget):
    """View 7 — Teacher model: system's understanding, anomalies, notes."""

    # Signals
    open_concept_panel = Signal(str)  # concept_id
    teach_requested = Signal(str)     # concept name — start a lesson
    teacher_built = Signal(object)    # TeacherModel

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._worker = None
        self._build()

    def refresh(self):
        self._rebuild()

    def _rebuild(self):
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._do_build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._root_layout = layout
        self._do_build()

    def _do_build(self):
        self._root_layout.addWidget(self._view_header(
            self._main._t("nav_teacher"),
            self._main._t("teacher_subtitle"),
        ))

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        # What is this?
        explain = QFrame()
        explain.setStyleSheet(
            f"QFrame {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_LG}px; }}"
        )
        ex_lay = QVBoxLayout(explain)
        ex_lay.setContentsMargins(14, 12, 14, 12)
        ex_lay.setSpacing(4)
        ex_t = QLabel(self._main._t("teacher_explain_title"))
        ex_t.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {theme.TEXT};"
        )
        ex_lay.addWidget(ex_t)
        ex_b = QLabel(self._main._t("teacher_explain_body"))
        ex_b.setWordWrap(True)
        ex_b.setStyleSheet(f"font-size: 13px; color: {theme.TEXT_MUTED};")
        ex_lay.addWidget(ex_b)
        content_layout.addWidget(explain)

        if self._main.current_asset_id in self._main.teacher_models:
            self._build_existing(content_layout)
        else:
            self._build_empty(content_layout)

        content_layout.addStretch(1)
        self._root_layout.addWidget(content)

    def _view_header(self, title, subtitle=""):
        return PageHeader(title, subtitle)

    def _build_existing(self, layout):
        from PySide6.QtWidgets import QMessageBox
        teacher_data = self._main.teacher_models[self._main.current_asset_id]
        status = teacher_data.get('status', 'unknown')
        status_labels = {"done": "done", "fallback": "fallback", "failed": "failed"}
        slbl = QLabel(self._main._t("teacher_status_" + status_labels.get(status, "done")))
        slbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; "
            f"color: {theme.SUCCESS if status == 'done' else theme.WARNING if status == 'fallback' else theme.DANGER};"
        )
        layout.addWidget(slbl)

        method = teacher_data.get('method', '')
        if method:
            lbl = QLabel(self._main._t("teacher_method", m=method))
            lbl.setStyleSheet(
                f"font-size: 12.5px; color: {theme.TEXT_MUTED};"
            )
            layout.addWidget(lbl)

        synthesized = teacher_data.get('synthesized_at', '')
        if synthesized:
            lbl = QLabel(self._main._t("teacher_time", t=synthesized[:19]))
            lbl.setStyleSheet(f"font-size: 12.5px; color: {theme.TEXT_MUTED};")
            layout.addWidget(lbl)

        # Source-provenance coverage: how many concepts carry a grounded
        # anchor (rest are template-enriched / unlocatable — marked ◌ in graph)
        asset = self._main.get_asset()
        if asset is not None and asset.concepts:
            anchored = [c for c in asset.concepts if c.locations]
            rate = len(anchored) / len(asset.concepts)
            pct = f"{rate:.0%}"
            rate_lbl = QLabel(
                self._main._t(
                    "teacher_anchor_rate",
                    pct=pct, n=len(anchored), total=len(asset.concepts),
                )
            )
            color = (
                theme.SUCCESS
                if rate >= 0.8
                else theme.WARNING
                if rate >= 0.5
                else theme.DANGER
            )
            rate_lbl.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {color};")
            layout.addWidget(rate_lbl)
            missing = [c.name for c in asset.concepts if not c.locations]
            if missing and rate < 1.0:
                shown = "、".join(missing[:5]) + ("…" if len(missing) > 5 else "")
                miss_lbl = QLabel(self._main._t("teacher_unanchored_list", names=shown))
                miss_lbl.setWordWrap(True)
                miss_lbl.setStyleSheet(
                    f"font-size: 12px; color: {theme.TEXT_FAINT};"
                )
                layout.addWidget(miss_lbl)

        btn_layout = QHBoxLayout()
        recheck_btn = QPushButton(self._main._t("recheck"))
        recheck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        recheck_btn.setStyleSheet(theme.secondary_button_style())
        recheck_btn.clicked.connect(self._on_recheck)
        btn_layout.addWidget(recheck_btn)

        if not self._main.llm_client:
            hint = QLabel(self._main._t("recheck_needs_llm"))
            hint.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: 12px;"
            )
            btn_layout.addWidget(hint)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Anomalies — split by lifecycle status: open ones stay actionable
        # cards; resolved ones move to a separate "teaching worked" section so
        # the learner sees the gap actually closed instead of crying wolf
        # forever (round-19: resolve_satisfied_anomalies marks them, the board
        # must show the difference).
        all_anomalies = teacher_data.get('anomalies', [])
        anomalies = [
            a for a in all_anomalies if a.get('status', 'open') != 'resolved'
        ]
        resolved_anomalies = [
            a for a in all_anomalies if a.get('status') == 'resolved'
        ]
        if anomalies:
            albl = QLabel(self._main._t("anomaly_label", n=len(anomalies)))
            albl.setStyleSheet(
                f"font-size: 14px; font-weight: 600; color: {theme.WARNING};"
                " margin-top: 12px;"
            )
            layout.addWidget(albl)

            sev_colors = {
                "high": theme.DANGER, "medium": theme.WARNING,
                "low": theme.TEXT_MUTED, "info": theme.ACCENT,
            }
            sev_bgs = {
                "high": theme.DANGER_TINT, "medium": theme.WARNING_TINT,
                "low": theme.SURFACE_MUTED, "info": theme.ACCENT_TINT,
            }

            for a in anomalies:
                kind = a.get('kind', '?')
                desc = a.get('description', '')
                sev = a.get('severity', 'medium')
                loc = a.get('location', '')
                sev_color = sev_colors.get(sev, theme.TEXT_MUTED)
                sev_bg = sev_bgs.get(sev, theme.SURFACE_MUTED)

                acard = QFrame()
                acard.setStyleSheet(
                    f"QFrame {{ background-color: {theme.SURFACE};"
                    f" border: 1px solid {theme.BORDER};"
                    f" border-radius: {theme.RADIUS_LG}px; }}"
                )
                a_lay = QVBoxLayout(acard)
                a_lay.setContentsMargins(12, 8, 12, 8)
                a_lay.setSpacing(4)

                head = QHBoxLayout()
                head.setSpacing(8)
                badge = QLabel(f"{kind_label(kind)} · {sev}")
                badge.setStyleSheet(
                    f"background-color: {sev_bg}; color: {sev_color};"
                    " padding: 2px 9px; border-radius: 6px;"
                    " font-size: 11.5px; font-weight: 600;"
                )
                head.addWidget(badge)
                if loc:
                    loc_lbl = QLabel(self._main._t("anomaly_loc", loc=loc[:40]))
                    loc_lbl.setStyleSheet(
                        f"color: {theme.TEXT_FAINT}; font-size: 11.5px;"
                    )
                    head.addWidget(loc_lbl)
                head.addStretch()
                a_lay.addLayout(head)

                desc_lbl = QLabel(desc)
                desc_lbl.setWordWrap(True)
                desc_lbl.setStyleSheet(
                    f"font-size: 13px; color: {theme.TEXT};"
                )
                a_lay.addWidget(desc_lbl)

                # Anomalies are the highest-priority teaching signal
                # (anomaly_prioritized_path), yet the board used to be
                # read-only: the learner saw "contradiction / undefined" and
                # could not act.  Same name-matching rule as
                # teacher.anomaly_concept_ids; unmatched stays read-only
                # (never invent a target).
                target = _match_anomaly_concept(asset, a)
                if target is not None:
                    acts = QHBoxLayout()
                    acts.setSpacing(8)
                    view_btn = QPushButton(
                        self._main._t("anomaly_view_concept")
                    )
                    view_btn.setObjectName("anomaly_view_btn")
                    view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    view_btn.setStyleSheet(theme.secondary_button_style())
                    view_btn.clicked.connect(
                        lambda checked, cid=target.id: self.open_concept_panel.emit(cid)
                    )
                    acts.addWidget(view_btn)
                    teach_btn = QPushButton(self._main._t("anomaly_teach"))
                    teach_btn.setObjectName("anomaly_teach_btn")
                    teach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    teach_btn.setStyleSheet(theme.primary_button_style(compact=True))
                    teach_btn.clicked.connect(
                        lambda checked, n=target.name: self.teach_requested.emit(n)
                    )
                    acts.addWidget(teach_btn)
                    acts.addStretch()
                    a_lay.addLayout(acts)

                layout.addWidget(acard)

        # Resolved anomalies and concept notes are secondary reading: they
        # move behind one 「更多」 fold so the first screen keeps only the
        # status block and the *open* (actionable) anomalies.  Hidden, never
        # removed — one click away.
        more_section = self._more_section = CollapsibleSection(
            self._main._t("more_section")
        )

        # Resolved anomalies: the gap closed — show it as evidence that
        # teaching worked, greyed out and read-only (nothing left to act on).
        # The reason is derived from the kind, the same deterministic rule
        # resolve_satisfied_anomalies uses to close them.
        if resolved_anomalies:
            rlbl = QLabel(
                self._main._t("teacher_resolved_label", n=len(resolved_anomalies))
            )
            rlbl.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #757575; margin-top: 12px;"
            )
            more_section.add(rlbl)

            reason_keys = {
                "learner_gap": "teacher_resolved_reason_mastery",
                "unanchored_source": "teacher_resolved_reason_anchor",
            }
            for a in resolved_anomalies:
                kind = a.get('kind', '?')
                rcard = QFrame()
                rcard.setStyleSheet(
                    f"QFrame {{ background-color: {theme.SURFACE_MUTED};"
                    f" border: 1px solid {theme.BORDER};"
                    f" border-radius: {theme.RADIUS_MD}px; }}"
                )
                r_lay = QVBoxLayout(rcard)
                r_lay.setContentsMargins(12, 8, 12, 8)
                r_lay.setSpacing(4)

                rhead = QHBoxLayout()
                rhead.setSpacing(8)
                rbadge = QLabel(
                    f"{kind_label(kind)} · {self._main._t('teacher_resolved_badge')}"
                )
                rbadge.setStyleSheet(
                    f"background-color: {theme.SURFACE};"
                    f" color: {theme.TEXT_MUTED}; border: 1px solid {theme.BORDER};"
                    " padding: 2px 9px; border-radius: 6px;"
                    " font-size: 11.5px; font-weight: 600;"
                )
                rhead.addWidget(rbadge)
                reason = QLabel(
                    self._main._t(
                        reason_keys.get(kind, "teacher_resolved_reason_generic")
                    )
                )
                reason.setStyleSheet(
                    f"color: {theme.SUCCESS}; font-size: 12px;"
                )
                rhead.addWidget(reason)
                rhead.addStretch()
                r_lay.addLayout(rhead)

                rdesc = QLabel(a.get('description', ''))
                rdesc.setWordWrap(True)
                rdesc.setStyleSheet(
                    f"font-size: 12.5px; color: {theme.TEXT_FAINT};"
                )
                r_lay.addWidget(rdesc)
                more_section.add(rcard)

        # Concept notes
        notes = teacher_data.get('concept_notes', [])
        if notes:
            nlbl = QLabel(self._main._t("notes_label", n=len(notes)))
            nlbl.setStyleSheet(
                f"font-size: 14px; font-weight: 600; color: {theme.TEXT};"
                " margin-top: 12px;"
            )
            more_section.add(nlbl)

            nhint = QLabel(self._main._t("notes_hint", n=len(notes)))
            nhint.setStyleSheet(
                f"font-size: 12.5px; color: {theme.TEXT_MUTED};"
            )
            more_section.add(nhint)

            notes_list = QListWidget()
            notes_list.setStyleSheet(
                f"QListWidget {{ background-color: {theme.SURFACE};"
                f" border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.RADIUS_MD}px; font-size: 13px; }}"
                f"QListWidget::item {{ padding: 7px 10px;"
                f" border-bottom: 1px solid {theme.DIVIDER}; }}"
                f"QListWidget::item:hover {{ background-color: {theme.ACCENT_TINT}; }}"
            )
            for note in notes:
                name = note.get('name', '?')
                sign = note.get('significance', '')
                miscon = note.get('misconceptions', [])
                signals = note.get('learner_signals') or []
                parts = [name]
                if sign:
                    parts.append(sign[:46] + ("…" if len(sign) > 46 else ""))
                if miscon:
                    parts.append(self._main._t("detail_miscon", s=miscon[0][:24]))
                if signals:
                    # What the system has learned FROM this learner — the
                    # teacher model's learner envelope, finally visible here.
                    parts.append(self._main._t("notes_signal_n", n=len(signals)))
                item = QListWidgetItem("　".join(parts))
                # Payload MUST live in UserRole: int role 2 is DisplayRole and
                # blanked the whole row once already (AGENTS.md #7).
                item.setData(Qt.ItemDataRole.UserRole, note.get('concept_id', ''))
                notes_list.addItem(item)
            notes_list.itemClicked.connect(self._on_note_clicked)
            more_section.add(notes_list)

        if more_section.body_layout().count():
            layout.addWidget(more_section)

    def _build_empty(self, layout):
        placeholder = QLabel(self._main._t("teacher_empty"))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 15px; margin: 40px;"
        )
        layout.addWidget(placeholder)

        build_btn = QPushButton(self._main._t("teacher_build_now"))
        build_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        build_btn.setStyleSheet(theme.primary_button_style())
        build_btn.clicked.connect(self._on_build_now)
        layout.addWidget(build_btn)

    def _on_recheck(self):
        from PySide6.QtWidgets import QMessageBox
        if not self._main.llm_client:
            QMessageBox.warning(self, self._main._t("hint"),
                               self._main._t("recheck_needs_llm"))
            return
        asset = self._main.get_asset()
        if not asset:
            return
        QMessageBox.information(self, self._main._t("hint"),
                                 self._main._t("rechecking"))
        self._worker = TeacherWorker(asset, self._main.llm_client)
        self._worker.finished.connect(self._on_recheck_finished)
        self._worker.error.connect(
            lambda e: QMessageBox.critical(self, self._main._t("error"),
                                           self._main._t("recheck_failed", e=e))
        )
        self._worker.start()

    def _on_recheck_finished(self, teacher):
        from PySide6.QtWidgets import QMessageBox
        self._main.teacher_models[teacher.asset_id] = teacher.to_dict()
        QMessageBox.information(
            self, self._main._t("done"),
            self._main._t("recheck_done", n=len(teacher.anomalies))
        )
        # The rebuilt model is already in main.teacher_models; every view reads
        # it from there on entry, so no cross-view notification is needed.
        self._rebuild()

    def _on_build_now(self):
        from PySide6.QtWidgets import QMessageBox
        if not self._main.llm_client:
            QMessageBox.warning(self, self._main._t("hint"),
                               self._main._t("build_needs_llm"))
            return
        asset = self._main.get_asset()
        if not asset:
            return
        QMessageBox.information(self, self._main._t("hint"),
                                self._main._t("building_teacher"))
        self._worker = TeacherWorker(asset, self._main.llm_client)
        self._worker.finished.connect(self._on_build_finished)
        self._worker.error.connect(
            lambda e: QMessageBox.critical(self, self._main._t("error"),
                                           self._main._t("build_failed", e=e))
        )
        self._worker.start()

    def _on_build_finished(self, teacher):
        from PySide6.QtWidgets import QMessageBox
        self._main.teacher_models[teacher.asset_id] = teacher.to_dict()
        QMessageBox.information(
            self, self._main._t("done"),
            self._main._t("build_done", n=len(teacher.anomalies))
        )
        self.teacher_built.emit(teacher)
        self._rebuild()

    def _on_note_clicked(self, item):
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid:
            self.open_concept_panel.emit(cid)
