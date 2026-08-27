"""Teaching view: lesson generation, answer evaluation, quiz, practice."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core.learner import (
    normalize,
    record_evaluation,
    set_profile,
    stuck_concepts,
)
from expert_anything.core.teacher import (
    TeacherModel,
    incorporate_stuck_signal,
    record_learner_question,
)
from expert_anything.core.storage import save_teacher
from expert_anything.core.tutor import Tutor
from expert_anything.core import config, auto_harness as _ah


class TeachWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, tutor, concept, vary=0, style=None):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
        self.vary = vary
        self.style = style

    def run(self):
        try:
            result = self.tutor.teach(self.concept, vary=self.vary, style=self.style)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class FollowUpWorker(QThread):
    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, tutor, concept, question, lesson, history):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
        self.question = question
        self.lesson = lesson
        self.history = history

    def run(self):
        try:
            answer = self.tutor.follow_up(
                self.concept,
                self.question,
                lesson=self.lesson,
                history=self.history,
            )
            self.finished.emit(self.question, answer)
        except Exception as e:
            self.error.emit(str(e))


class PracticeWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, tutor, concept):
        super().__init__()
        self.tutor = tutor
        self.concept = concept

    def run(self):
        try:
            task = self.tutor.generate_practice(self.concept)
            self.finished.emit(task or {})
        except Exception as e:
            self.error.emit(str(e))


class QuizWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, tutor, concept, qtype=""):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
        self.qtype = qtype

    def run(self):
        try:
            quiz = self.tutor.generate_quiz(self.concept, qtype=self.qtype)
            self.finished.emit(quiz or {})
        except Exception as e:
            self.error.emit(str(e))


class TeachView(QWidget):
    """View 5 — Teaching session."""

    # Signalled back to MainWindow
    teach_started = Signal(str)  # concept_name (for stuck detection)
    stuck_detected = Signal(str, object)  # concept_name, stuck_info
    followup_done = Signal(str, str)  # question, answer
    harness_adopted = Signal(object)  # candidate spec
    harness_transferred = Signal(object)  # payload
    evaluate_recorded = Signal()  # refresh topbar
    quiz_result = Signal(float)  # quiz score (delegated from TeachResultView)

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._concept_list = None
        self._style_combo = None
        self._graph = None
        self._progress = None
        self._result_area = None
        self._teach_worker = None
        self._followup_worker = None
        self._practice_worker = None
        self._quiz_worker = None
        self._tutor = None
        self._teach_lesson = None
        self._teach_concept_now = ""
        self._teach_vary = 0
        self._teach_answer_input = None
        self._teach_view_widget = None
        self._practice_concept = None  # concept for practice evaluation
        self._quiz_concept = None  # concept for quiz recording
        self._review_mode = False
        self._followup_history = []
        # External callers/tests can submit an already-scored quiz through the
        # view-level compatibility signal.  Connect once per TeachView lifetime,
        # not once per rendered result card.
        self.quiz_result.connect(self._on_quiz_result)
        self._build()

    # Style index ↔ canonical code mapping (stable, not i18n-dependent)
    _CODE_TO_IDX = {None: 0, "example": 1, "diagram": 2, "steps": 3}
    _IDX_TO_CODE = {v: k for k, v in _CODE_TO_IDX.items()}

    def refresh(self):
        self._rebuild_concept_list()
        self._rebuild_style_combo()

    def _restore_style_combo(self):
        """Restore style combo to learner profile preference."""
        if self._style_combo is None:
            return
        saved = self._main.learner.get("profile", {}).get("style")
        idx = self._CODE_TO_IDX.get(saved, 0)
        self._style_combo.setCurrentIndex(idx)

    def _rebuild_style_combo(self):
        """Rebuild style combo items when language changes."""
        if self._style_combo is None:
            return
        self._style_combo.currentIndexChanged.disconnect()
        self._style_combo.clear()
        self._style_combo.addItems(
            [
                self._main._t("style_example"),
                self._main._t("style_diagram"),
                self._main._t("style_steps"),
            ]
        )
        self._style_combo.currentIndexChanged.connect(self._on_style_changed)
        self._restore_style_combo()

    def _on_style_changed(self, idx: int):
        """Save style preference to learner profile."""
        code = self._IDX_TO_CODE.get(idx)
        if code is None:  # "no preference" → leave profile untouched
            return
        prof = self._main.learner.setdefault("profile", {})
        prof["style"] = code
        self._main.save_learner_state()

    def _rebuild_concept_list(self):
        self._concept_list.clear()
        if (
            self._main.current_asset_id
            and self._main.current_asset_id in self._main.assets
        ):
            data = self._main.assets[self._main.current_asset_id]
            names = [c.get("name", "?") for c in data.get("concepts", [])]
            self._concept_list.addItems(names)
            next_c, _ = self._main._next_concept()
            if next_c is not None and next_c.name in names:
                self._concept_list.setCurrentText(next_c.name)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Slim header
        header = QFrame()
        header.setStyleSheet(
            "background-color: white; border-bottom: 1px solid #E0E0E0;"
        )
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 5, 20, 5)
        h_lay.setSpacing(10)
        h_t = QLabel(self._main._t("nav_teach"))
        h_t.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2933;")
        h_lay.addWidget(h_t)
        h_s = QLabel(self._main._t("teach_hint"))
        h_s.setStyleSheet("color: #9E9E9E; font-size: 11px;")
        h_lay.addWidget(h_s)
        h_lay.addStretch()
        layout.addWidget(header)

        splitter = QSplitter()
        # Left panel: concept selector
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 8, 16)

        concept_label = QLabel(self._main._t("swap_concept"))
        concept_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        left_layout.addWidget(concept_label)

        self._concept_list = QComboBox()
        self._concept_list.setStyleSheet("""
            QComboBox { padding: 6px; border: 1px solid #E0E0E0;
                        border-radius: 4px; font-size: 12px; background-color: white; }
        """)
        self._rebuild_concept_list()
        left_layout.addWidget(self._concept_list)

        style_label = QLabel(self._main._t("style_label"))
        style_label.setStyleSheet(
            "font-size: 12px; font-weight: bold; margin-top: 12px;"
        )
        left_layout.addWidget(style_label)

        self._style_combo = QComboBox()
        self._style_combo.addItems(
            [
                self._main._t("style_example"),
                self._main._t("style_diagram"),
                self._main._t("style_steps"),
            ]
        )
        self._style_combo.currentIndexChanged.connect(self._on_style_changed)
        self._style_combo.setStyleSheet("""
            QComboBox { padding: 6px; border: 1px solid #E0E0E0;
                        border-radius: 4px; font-size: 12px; }
        """)
        left_layout.addWidget(self._style_combo)

        # Review mode toggle
        self._review_toggle = QPushButton(self._main._t("review_mode"))
        self._review_toggle.setCheckable(True)
        self._review_toggle.setStyleSheet("""
            QPushButton { background-color: white; color: #6A1B9A;
                          border: 1px solid #CE93D8; border-radius: 6px;
                          padding: 6px 12px; font-size: 11px; }
            QPushButton:checked { background-color: #F3E5F5; }
        """)
        self._review_toggle.clicked.connect(self._on_review_toggle)
        left_layout.addWidget(self._review_toggle)

        start_btn = QPushButton(self._main._t("start_teach"))
        start_btn.setStyleSheet("""
            QPushButton { background-color: #1565C0; color: white; border: none;
                          border-radius: 6px; padding: 10px 20px; font-size: 13px; }
            QPushButton:hover { background-color: #0D47A1; }
        """)
        start_btn.clicked.connect(self._on_start_teach)
        left_layout.addWidget(start_btn)
        left_layout.addStretch()
        splitter.addWidget(left)

        # Right panel: content
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 16, 16, 16)

        self._result_label = QLabel(self._main._t("lesson_ready"))
        self._result_label.setStyleSheet("color: #757575; font-size: 13px;")
        right_layout.addWidget(self._result_label)

        self._graph = self._main._teach_graph_ref()
        self._graph.setMinimumHeight(140)
        self._graph.setMaximumHeight(170)
        self._graph.setStyleSheet(
            "QGraphicsView { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        self._graph.setVisible(False)
        right_layout.addWidget(self._graph)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        right_layout.addWidget(self._progress)

        self._result_area = QScrollArea()
        self._result_area.setWidgetResizable(True)
        self._result_area.setStyleSheet("""
            QScrollArea { border: 1px solid #E0E0E0; border-radius: 8px;
                          background-color: white; }
        """)
        right_layout.addWidget(self._result_area, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([230, 760])
        layout.addWidget(splitter, 1)

    def _on_review_toggle(self):
        self._review_mode = self._review_toggle.isChecked()

    def _on_start_teach(self):
        concept_name = self._concept_list.currentText()
        if not concept_name:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self, self._main._t("hint"), self._main._t("pick_concept_first")
            )
            return

        asset = self._main.get_asset()
        if not asset:
            return

        concept = None
        for c in asset.concepts:
            if normalize(c.name) == normalize(concept_name):
                concept = c
                break

        if not concept:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                self._main._t("hint"),
                self._main._t("concept_not_found", name=concept_name),
            )
            return

        if self._main.current_asset_id:
            self._tutor = Tutor(asset, llm=self._main.llm_client)

        # Canonical style codes (example/diagram/steps) are used internally
        # by the Tutor regardless of UI language.
        _idx_to_code = {0: None, 1: "example", 2: "diagram", 3: "steps"}
        explicit_style = _idx_to_code.get(self._style_combo.currentIndex())

        vary = 1 if self._review_mode else 0
        self._show_teaching_content(concept, vary=vary, style=explicit_style)

    def _show_teaching_content(self, concept, vary=0, style=None):
        if not self._tutor:
            asset = self._main.get_asset()
            self._tutor = Tutor(asset, llm=self._main.llm_client)

        self._progress.setVisible(True)
        self._progress.setValue(30)
        self._result_label.setText(self._main._t("generating_lesson"))
        self._result_label.repaint()

        # Mini graph
        try:
            asset = self._main.get_asset()
            if asset is not None:
                mastery_map = {}
                for c in asset.concepts:
                    norm_name = normalize(c.name)
                    mastery_map[c.id] = (
                        self._main.learner.get("concepts", {})
                        .get(norm_name, {})
                        .get("mastery", 0.0)
                    )
                anomaly_ids = set()
                td = self._main.teacher_models.get(self._main.current_asset_id)
                if td:
                    try:
                        from expert_anything.core.teacher import (
                            anomaly_concept_ids,
                            TeacherModel,
                        )

                        anomaly_ids = anomaly_concept_ids(
                            asset, TeacherModel.from_dict(td)
                        )
                    except Exception:
                        anomaly_ids = set()
                self._graph.set_asset(
                    asset,
                    mastery_map=mastery_map,
                    anomaly_ids=anomaly_ids,
                    current_id=concept.id,
                )
                self._graph.focus_concept(concept.id)
                self._graph.setVisible(True)
        except Exception:
            self._graph.setVisible(False)

        self._teach_vary = vary
        self._teach_worker = TeachWorker(self._tutor, concept, vary=vary, style=style)
        self._teach_worker.finished.connect(self._on_teach_finished)
        self._teach_worker.error.connect(self._on_teach_error)
        self._teach_worker.start()

    def _on_teach_finished(self, result):
        self._progress.setValue(100)
        self._display_result(result)

    def _on_teach_error(self, error_msg):
        from PySide6.QtWidgets import QMessageBox

        self._progress.setVisible(False)
        QMessageBox.critical(
            self, self._main._t("error"), self._main._t("teach_error", msg=error_msg)
        )

    def _display_result(self, result):
        old = self._result_area.takeWidget()
        if old is not None:
            old.deleteLater()

        from expert_anything.ui.widgets.teach_widgets import TeachResultView

        view = TeachResultView(result, self)
        self._teach_view_widget = view
        self._teach_concept_now = result.get("concept", "")
        self._teach_lesson = result
        self._teach_result_label = self._main._t("generating_lesson")
        if view.answer_input is not None:
            self._teach_answer_input = view.answer_input

        # Graph neighbours
        asset = self._main.get_asset()
        if asset is not None:
            concept = asset.concept_by_name(result.get("concept", ""))
            if concept is not None:
                seen, neighbors = set(), []
                for r in asset.relations:
                    if r.source == concept.id:
                        other = asset.concept_by_id(r.target)
                        if other and other.id not in seen:
                            seen.add(other.id)
                            neighbors.append(
                                (
                                    r.label or self._main._t("edge_related"),
                                    other.name,
                                    other.id,
                                )
                            )
                    elif r.target == concept.id:
                        other = asset.concept_by_id(r.source)
                        if other and other.id not in seen:
                            seen.add(other.id)
                            neighbors.append(
                                (
                                    r.label or self._main._t("edge_related"),
                                    other.name,
                                    other.id,
                                )
                            )
                    if len(neighbors) >= 6:
                        break
                view.set_neighbors(neighbors)

        # Wire practice / quiz / quiz_result signals
        view.practice_requested.connect(self._on_practice_requested)
        view.practice_submit.connect(self._on_practice_submit)
        view.quiz_requested.connect(self._on_quiz_requested)
        view.quiz_result.connect(self._on_quiz_result)

        self._result_area.setWidget(view)
        self._progress.setVisible(False)
        self._result_label.setText("")

    def on_submit_answer(self, answer: str):
        concept_name = self._teach_concept_now
        asset = self._main.get_asset()
        if not concept_name or asset is None:
            return

        concept = None
        for c in asset.concepts:
            if normalize(c.name) == normalize(concept_name):
                concept = c
                break
        if not concept:
            return

        if self._tutor:
            result = self._tutor.evaluate(concept, answer)
            score = result.get("score", 0)
            feedback = result.get("feedback", "")
            lesson = self._teach_lesson or {}
            new_mastery = record_evaluation(
                self._main.learner,
                concept.name,
                asset.asset_id,
                score,
                answer,
                feedback,
                meta={
                    "channel": "answer",
                    "style": lesson.get("style", ""),
                    "vary": self._teach_vary,
                    "rotated_style": bool(lesson.get("rotated_style")),
                    "judges": result.get("judges", 1),
                },
            )
            self._main.save_learner_state()
            self.evaluate_recorded.emit()

            # Stuck detection + AutoHarness
            try:
                key = normalize(concept.name)
                hit = next(
                    (s for s in stuck_concepts(self._main.learner) if s["key"] == key),
                    None,
                )
                if hit is not None:
                    teacher = None
                    td = self._main.teacher_models.get(asset.asset_id)
                    if td:
                        teacher = TeacherModel.from_dict(td)
                    teacher = incorporate_stuck_signal(
                        asset,
                        teacher,
                        concept.id,
                        hit["attempts"],
                        hit["avg"],
                    )
                    save_teacher(asset.asset_id, teacher)
                    self._main.teacher_models[asset.asset_id] = teacher.to_dict()
                    self.stuck_detected.emit(concept.name, hit)

                    # AutoHarness evolve
                    try:
                        spec = self._main._harness_specs.get(
                            asset.asset_id
                        ) or _ah.fallback_harness(concept.name)
                        sess = _ah.load_session_reports(
                            config.DATA_DIR / "harness_state.json"
                        )
                        jt = _ah.evolve_joint(
                            spec,
                            self._main.learner,
                            reports=sess,
                            concept_name=concept.name,
                        )
                        jc = jt.get("candidates", [])
                        if jt.get("evolved") and jc:
                            diag = "\n".join(jt.get("diagnosis", []))
                            if self._teach_view_widget:
                                self._teach_view_widget.append_harness_suggestion(
                                    self._main._t("harness_joint_title"),
                                    self._main._t(
                                        "harness_joint_body",
                                        concept=concept.name,
                                        reason=jt["reason"],
                                        summary=_ah.harness_summary(jc[0]),
                                        diag=diag[:180],
                                    ),
                                    jc[0],
                                    source="joint",
                                    extra={"_joint_reason": jt["reason"]},
                                )
                                self._teach_view_widget.append_harness_history(
                                    self._main._harness_history
                                )
                    except Exception:
                        pass
            except Exception:
                pass

            # Display evaluation
            if self._teach_view_widget:
                self._teach_view_widget.append_evaluation(
                    score,
                    feedback,
                    result.get("reference", ""),
                    result.get("gap", ""),
                )
        self.teach_started.emit(concept_name)

    # ------------------------------------------------------------------
    # Practice (P2 hands-on闭环)
    # ------------------------------------------------------------------
    def _on_practice_requested(self):
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_name(self._teach_concept_now or "")
        if concept is None:
            return
        if not self._tutor:
            self._tutor = Tutor(asset, llm=self._main.llm_client)
        self._practice_concept = concept
        self._practice_worker = PracticeWorker(self._tutor, concept)
        self._practice_worker.finished.connect(self._on_practice_done)
        self._practice_worker.error.connect(
            lambda e: self._on_worker_error("practice", e)
        )
        self._practice_worker.start()

    def _on_practice_done(self, task: dict):
        self._practice_worker = None
        if not self._teach_view_widget:
            return
        self._teach_view_widget.show_practice(task if task else None)

    # ------------------------------------------------------------------
    # Practice evaluation (record into mastery)
    # ------------------------------------------------------------------
    def _on_practice_submit(self, answer: str):
        if not self._practice_concept:
            return
        asset = self._main.get_asset()
        if asset is None or not self._tutor:
            return
        concept = self._practice_concept
        result = self._tutor.evaluate_practice(concept, answer)
        score = float(result.get("score", 0.0))
        feedback = result.get("feedback", "")
        if self._teach_view_widget:
            self._teach_view_widget.show_practice_result(result)
        record_evaluation(
            self._main.learner,
            concept.name,
            asset.asset_id,
            score,
            answer,
            feedback,
            meta={"channel": "practice"},
        )
        self._main.save_learner_state()
        self.evaluate_recorded.emit()
        self._check_harness_for(concept, asset, "practice", score)

    # ------------------------------------------------------------------
    # Quick-quiz (P1 quick self-test)
    # ------------------------------------------------------------------
    def _on_quiz_requested(self):
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_name(self._teach_concept_now or "")
        if concept is None:
            return
        if not self._tutor:
            self._tutor = Tutor(asset, llm=self._main.llm_client)
        self._quiz_concept = concept
        self._quiz_worker = QuizWorker(self._tutor, concept)
        self._quiz_worker.finished.connect(self._on_quiz_done)
        self._quiz_worker.error.connect(lambda e: self._on_worker_error("quiz", e))
        self._quiz_worker.start()

    def _on_quiz_done(self, quiz: dict):
        self._quiz_worker = None
        if not self._teach_view_widget:
            return
        self._teach_view_widget.show_quiz(quiz if quiz else None)

    def _on_quiz_result(self, score: float):
        """Record a locally scored quiz against the active teaching concept."""
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = self._quiz_concept
        if concept is None and self._teach_concept_now:
            concept = asset.concept_by_name(self._teach_concept_now)
        if concept is None:
            return
        self._quiz_concept = concept
        record_evaluation(
            self._main.learner,
            concept.name,
            asset.asset_id,
            score,
            "",
            "quick self-test",
            meta={"channel": "quiz"},
        )
        self._main.save_learner_state()
        self.evaluate_recorded.emit()
        self._check_harness_for(concept, asset, "quiz", score)

    def _on_worker_error(self, kind: str, msg: str):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self, self._main._t("error"), self._main._t(f"{kind}_failed", msg=msg)
        )

    def on_followup(self, question: str):
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_name(self._teach_concept_now or "")
        if concept is None:
            return
        if not self._tutor:
            self._tutor = Tutor(asset, llm=self._main.llm_client)
        lesson = self._teach_lesson
        self._followup_worker = FollowUpWorker(
            self._tutor,
            concept,
            question,
            lesson,
            self._followup_history,
        )
        self._followup_worker.finished.connect(self._on_followup_done)
        self._followup_worker.error.connect(
            lambda msg: (
                self._teach_view_widget.append_exchange(
                    question, self._main._t("followup_failed", msg=msg)
                )
                if self._teach_view_widget
                else None
            )
        )
        self._followup_worker.start()

    def _on_followup_done(self, question: str, answer: str):
        if self._teach_view_widget:
            self._teach_view_widget.append_exchange(question, answer)
        self._followup_history.append((question, answer))
        self._followup_history = self._followup_history[-4:]

        # Sink question into teacher model
        try:
            asset = self._main.get_asset()
            if asset is not None:
                concept = asset.concept_by_name(self._teach_concept_now or "")
                if concept is not None:
                    teacher = None
                    td = self._main.teacher_models.get(self._main.current_asset_id)
                    if td:
                        teacher = TeacherModel.from_dict(td)
                    teacher = record_learner_question(
                        asset,
                        teacher,
                        concept.id,
                        question,
                    )
                    save_teacher(self._main.current_asset_id, teacher)
                    self._main.teacher_models[self._main.current_asset_id] = (
                        teacher.to_dict()
                    )
        except Exception:
            pass
        self.followup_done.emit(question, answer)

    # ------------------------------------------------------------------
    # AutoHarness evolution for practice / quiz channels
    # ------------------------------------------------------------------
    def _check_harness_for(self, concept, asset, channel, score):
        """Run stuck detection + AutoHarness evolution after practice/quiz eval."""
        if concept is None:
            return
        # Stuck detection
        try:
            key = normalize(concept.name)
            hit = next(
                (s for s in stuck_concepts(self._main.learner) if s["key"] == key), None
            )
            if hit is not None:
                teacher = None
                td = self._main.teacher_models.get(asset.asset_id)
                if td:
                    from expert_anything.core.teacher import TeacherModel

                    teacher = TeacherModel.from_dict(td)
                teacher = incorporate_stuck_signal(
                    asset,
                    teacher,
                    concept.id,
                    hit["attempts"],
                    hit["avg"],
                )
                save_teacher(asset.asset_id, teacher)
                self._main.teacher_models[asset.asset_id] = teacher.to_dict()
                self.stuck_detected.emit(concept.name, hit)
        except Exception:
            pass
        # AutoHarness evolve
        try:
            spec = self._main._harness_specs.get(
                asset.asset_id
            ) or _ah.fallback_harness(concept.name)
            sess = _ah.load_session_reports(config.DATA_DIR / "harness_state.json")
            jt = _ah.evolve_joint(
                spec, self._main.learner, reports=sess, concept_name=concept.name
            )
            jc = jt.get("candidates", [])
            if jt.get("evolved") and jc:
                diag = "\n".join(jt.get("diagnosis", []))
                if self._teach_view_widget:
                    self._teach_view_widget.append_harness_suggestion(
                        self._main._t("harness_joint_title"),
                        self._main._t(
                            "harness_joint_body",
                            concept=concept.name,
                            reason=jt["reason"],
                            summary=_ah.harness_summary(jc[0]),
                            diag=diag[:180],
                        ),
                        jc[0],
                        source="joint",
                        extra={"_joint_reason": jt["reason"]},
                    )
                    self._teach_view_widget.append_harness_history(
                        self._main._harness_history
                    )
        except Exception:
            pass

    def on_adopt_harness(self, candidate):
        self.harness_adopted.emit(candidate)

    def on_transfer_harness(self, payload):
        self.harness_transferred.emit(payload)

    def start_teach_by_name(self, concept_name: str, review: bool = False):
        self._review_mode = review
        self._review_toggle.setChecked(review)
        idx = self._concept_list.findText(concept_name)
        if idx >= 0:
            self._concept_list.setCurrentIndex(idx)
        self._on_start_teach()

    def _t(self, key, **kw):
        return self._main._t(key, **kw)

    # ------------------------------------------------------------------
    # Delegates to TeachResultView (so tests and external callers can use
    # TeachView directly without reaching into _teach_view_widget)
    # ------------------------------------------------------------------
    def show_quiz(self, quiz):
        if self._teach_view_widget:
            self._teach_view_widget.show_quiz(quiz)

    def show_practice(self, task):
        if self._teach_view_widget:
            self._teach_view_widget.show_practice(task)

    def show_practice_result(self, result):
        if self._teach_view_widget:
            self._teach_view_widget.show_practice_result(result)
