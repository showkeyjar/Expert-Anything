"""Teacher model view: anomaly board, concept notes, recheck."""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)
from expert_anything.core.teacher import TeacherModel, build_teacher_model


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
    teacher_built = Signal(object)    # TeacherModel
    teacher_rebuilt = Signal(object)  # TeacherModel

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
            "QFrame { background-color: #FFF8E1; border: 1px solid #FFE0B2;"
            "border-radius: 8px; }"
        )
        ex_lay = QVBoxLayout(explain)
        ex_lay.setContentsMargins(12, 10, 12, 10)
        ex_lay.setSpacing(4)
        ex_t = QLabel(self._main._t("teacher_explain_title"))
        ex_t.setStyleSheet("font-size: 14.5px; font-weight: bold; color: #B45309;")
        ex_lay.addWidget(ex_t)
        ex_b = QLabel(self._main._t("teacher_explain_body"))
        ex_b.setWordWrap(True)
        ex_b.setStyleSheet("font-size: 14px; color: #5D4037;")
        ex_lay.addWidget(ex_b)
        content_layout.addWidget(explain)

        if self._main.current_asset_id in self._main.teacher_models:
            self._build_existing(content_layout)
        else:
            self._build_empty(content_layout)

        self._root_layout.addWidget(content)

    def _view_header(self, title, subtitle=""):
        header = QFrame()
        header.setStyleSheet("background-color: white; border-bottom: 2px solid #1565C0;")
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
        lay.addStretch()
        return header

    def _build_existing(self, layout):
        from PySide6.QtWidgets import QMessageBox
        teacher_data = self._main.teacher_models[self._main.current_asset_id]
        status = teacher_data.get('status', 'unknown')
        status_labels = {"done": "done", "fallback": "fallback", "failed": "failed"}
        slbl = QLabel(self._main._t("teacher_status_" + status_labels.get(status, "done")))
        slbl.setStyleSheet(
            f"font-size: 16px; font-weight: bold; "
            f"color: {'#2E7D32' if status == 'done' else '#FF9800' if status == 'fallback' else '#F44336'};"
        )
        layout.addWidget(slbl)

        method = teacher_data.get('method', '')
        if method:
            lbl = QLabel(self._main._t("teacher_method", m=method))
            lbl.setStyleSheet("font-size: 14px; color: #666;")
            layout.addWidget(lbl)

        synthesized = teacher_data.get('synthesized_at', '')
        if synthesized:
            lbl = QLabel(self._main._t("teacher_time", t=synthesized[:19]))
            lbl.setStyleSheet("font-size: 14px; color: #666;")
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
            color = "#2E7D32" if rate >= 0.8 else "#E65100" if rate >= 0.5 else "#C62828"
            rate_lbl.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {color};")
            layout.addWidget(rate_lbl)
            missing = [c.name for c in asset.concepts if not c.locations]
            if missing and rate < 1.0:
                shown = "、".join(missing[:5]) + ("…" if len(missing) > 5 else "")
                miss_lbl = QLabel(self._main._t("teacher_unanchored_list", names=shown))
                miss_lbl.setWordWrap(True)
                miss_lbl.setStyleSheet("font-size: 13px; color: #90A4AE;")
                layout.addWidget(miss_lbl)

        btn_layout = QHBoxLayout()
        recheck_btn = QPushButton(self._main._t("recheck"))
        recheck_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 15px; }
            QPushButton:hover { background-color: #F57C00; }
        """)
        recheck_btn.clicked.connect(self._on_recheck)
        btn_layout.addWidget(recheck_btn)

        if not self._main.llm_client:
            hint = QLabel(self._main._t("recheck_needs_llm"))
            hint.setStyleSheet("color: #999; font-size: 14px;")
            btn_layout.addWidget(hint)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Anomalies
        anomalies = teacher_data.get('anomalies', [])
        if anomalies:
            albl = QLabel(self._main._t("anomaly_label", n=len(anomalies)))
            albl.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #E65100; margin-top: 12px;"
            )
            layout.addWidget(albl)

            kind_labels = {
                "contradiction": self._main._t("kind_contradiction"),
                "undefined_term": self._main._t("kind_undefined_term"),
                "logical_gap": self._main._t("kind_logical_gap"),
                "surprising_claim": self._main._t("kind_surprising_claim"),
                "learner_gap": self._main._t("kind_learner_gap"),
                "needs_llm": self._main._t("kind_needs_llm"),
            }
            sev_colors = {
                "high": "#C62828", "medium": "#E65100",
                "low": "#616161", "info": "#0277BD",
            }
            sev_bgs = {
                "high": "#FFEBEE", "medium": "#FFF3E0",
                "low": "#F5F5F5", "info": "#E1F5FE",
            }

            for a in anomalies:
                kind = a.get('kind', '?')
                desc = a.get('description', '')
                sev = a.get('severity', 'medium')
                loc = a.get('location', '')
                sev_color = sev_colors.get(sev, "#616161")
                sev_bg = sev_bgs.get(sev, "#F5F5F5")

                acard = QFrame()
                acard.setStyleSheet(
                    f"QFrame {{ background-color: {sev_bg};"
                    f"border-left: 4px solid {sev_color}; border-radius: 6px; }}"
                )
                a_lay = QVBoxLayout(acard)
                a_lay.setContentsMargins(12, 8, 12, 8)
                a_lay.setSpacing(4)

                head = QHBoxLayout()
                head.setSpacing(8)
                badge = QLabel(f"{kind_labels.get(kind, kind)} · {sev}")
                badge.setStyleSheet(
                    f"background-color: {sev_color}; color: white;"
                    "padding: 2px 10px; border-radius: 8px;"
                    "font-size: 12px; font-weight: bold;"
                )
                head.addWidget(badge)
                if loc:
                    loc_lbl = QLabel(self._main._t("anomaly_loc", loc=loc[:40]))
                    loc_lbl.setStyleSheet("color: #757575; font-size: 12.5px;")
                    head.addWidget(loc_lbl)
                head.addStretch()
                a_lay.addLayout(head)

                desc_lbl = QLabel(desc)
                desc_lbl.setWordWrap(True)
                desc_lbl.setStyleSheet("font-size: 14.5px; color: #37474F;")
                a_lay.addWidget(desc_lbl)
                layout.addWidget(acard)

        # Concept notes
        notes = teacher_data.get('concept_notes', [])
        if notes:
            nlbl = QLabel(self._main._t("notes_label", n=len(notes)))
            nlbl.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #666; margin-top: 12px;"
            )
            layout.addWidget(nlbl)

            nhint = QLabel(self._main._t("notes_hint", n=len(notes)))
            nhint.setStyleSheet("font-size: 13.5px; color: #8D6E63;")
            layout.addWidget(nhint)

            notes_list = QListWidget()
            notes_list.setStyleSheet("""
                QListWidget { background-color: white; border: 1px solid #E0E0E0;
                              border-radius: 6px; font-size: 14.5px; }
                QListWidget::item { padding: 7px 10px;
                                    border-bottom: 1px solid #F0F0F0; }
                QListWidget::item:hover { background-color: #FFF8E1; }
            """)
            for note in notes:
                name = note.get('name', '?')
                sign = note.get('significance', '')
                miscon = note.get('misconceptions', [])
                parts = [name]
                if sign:
                    parts.append(sign[:46] + ("…" if len(sign) > 46 else ""))
                if miscon:
                    parts.append(self._main._t("detail_miscon", s=miscon[0][:24]))
                item = QListWidgetItem("　".join(parts))
                item.setData(2, note.get('concept_id', ''))
                notes_list.addItem(item)
            notes_list.itemClicked.connect(self._on_note_clicked)
            layout.addWidget(notes_list)

    def _build_empty(self, layout):
        placeholder = QLabel(self._main._t("teacher_empty"))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #757575; font-size: 16px; margin: 40px;")
        layout.addWidget(placeholder)

        build_btn = QPushButton(self._main._t("teacher_build_now"))
        build_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border: none;
                          border-radius: 6px; padding: 10px 20px; font-size: 15px; }
            QPushButton:hover { background-color: #388E3C; }
        """)
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
        self.teacher_rebuilt.emit(teacher)
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
        cid = item.data(2)
        if cid:
            self.open_concept_panel.emit(cid)
