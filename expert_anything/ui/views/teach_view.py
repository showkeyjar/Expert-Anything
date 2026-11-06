"""Teaching view: lesson generation, answer evaluation, quiz, practice."""

from __future__ import annotations

from PySide6.QtCore import QThread, Qt, Signal
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
    mark_completed,
    normalize,
    record_evaluation,
    record_taught_concept,
    recent_taught_concepts,
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
from expert_anything.ui import theme


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


class EvaluateWorker(QThread):
    """Evaluate a learner's answer / practice submission off the UI thread.

    evaluate() and evaluate_practice() call the LLM (up to the client timeout,
    60s by default). Running them synchronously froze the whole window right
    at the moment the learner submitted their answer 鈥?the worst possible
    place to stall the learning loop.
    """

    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        tutor,
        concept,
        answer: str,
        practice: bool = False,
        task: str = "",
    ):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
        self.answer = answer
        self.practice = practice
        self.task = task

    def run(self):
        try:
            if self.practice:
                result = self.tutor.evaluate_practice(
                    self.concept, self.task, self.answer
                )
            else:
                result = self.tutor.evaluate(self.concept, self.answer)
            self.finished.emit(result or {})
        except Exception as e:
            self.error.emit(str(e))


class TeachView(QWidget):
    """View 5 鈥?Teaching session."""

    # Signalled back to MainWindow
    teach_started = Signal(str)  # concept_name (for stuck detection)
    stuck_detected = Signal(str, object)  # concept_name, stuck_info
    followup_done = Signal(str, str)  # question, answer
    evidence_jump_requested = Signal(str, str)  # concept id, evidence text
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
        self._eval_worker = None  # EvaluateWorker for answer/practice grading
        self._tutor = None
        self._teach_lesson = None
        self._teach_concept_now = ""
        self._teach_vary = 0
        self._teach_answer_input = None
        self._teach_view_widget = None
        self._practice_concept = None  # concept for practice evaluation
        self._practice_task = ""  # task text shown when practice was generated
        self._eval_answer_text = ""  # answer being graded by EvaluateWorker
        self._quiz_concept = None  # concept for quiz recording
        # Vary semantics snapshot at quiz launch: True when the quiz belongs
        # to a review lesson. A standalone quick-quiz (map card) has no
        # lesson context, so it must not inherit a stale review flag.
        self._quiz_vary = False
        self._review_mode = False
        self._followup_history = []
        self._retired: list = []  # workers parked mid-flight (retire-and-replace)
        # Topic learning session: a sequential pack of concepts from one cluster
        self._topic_name: str | None = None
        self._topic_queue: list[str] = []
        self._topic_mastered: int = 0
        # Review packs (queue from due_for_review) teach every lesson with
        # vary=1; regular topic packs never set this.
        self._topic_review: bool = False
        self._topic_banner = None
        self._recent_host = None
        self._recent_layout = None
        # External callers/tests can submit an already-scored quiz through the
        # view-level compatibility signal.  Connect once per TeachView lifetime,
        # not once per rendered result card.
        self.quiz_result.connect(self._on_quiz_result)
        self._build()

    # Style index 鈫?canonical code mapping (stable, not i18n-dependent)
    _CODE_TO_IDX = {None: 0, "example": 1, "diagram": 2, "steps": 3}
    _IDX_TO_CODE = {v: k for k, v in _CODE_TO_IDX.items()}

    def _retire(self, worker) -> None:
        """Retire-and-replace for QThread workers.

        Re-assigning ``self._x_worker`` while the old thread is still running
        drops the last Python reference 鈫?Qt fatal "QThread: Destroyed while
        thread is still running". Instead: disconnect the stale worker's
        signals (its late result must not clobber the newer one) and park it
        in a retirement list until it finishes naturally.
        """
        if worker is None:
            return
        for sig in (worker.finished, worker.error):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._retired = [w for w in self._retired if w.isRunning()]
        self._retired.append(worker)

    def refresh(self):
        self._rebuild_concept_list()
        self._rebuild_style_combo()
        self._rebuild_recent_bar()

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
        if code is None:  # "no preference" 鈫?leave profile untouched
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

    def _rebuild_recent_bar(self) -> None:
        """Render recently-taught concepts of THIS asset as quick-jump pills."""
        host = getattr(self, "_recent_host", None)
        layout = getattr(self, "_recent_layout", None)
        if host is None or layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        asset = self._main.get_asset()
        if asset is None:
            host.setVisible(False)
            return
        asset_names = {c.name for c in asset.concepts}
        recent = [
            n for n in recent_taught_concepts(self._main.learner, limit=5)
            if n in asset_names
        ]
        if not recent:
            host.setVisible(False)
            return

        title = QLabel(self._main._t("recent_taught_title"))
        title.setStyleSheet("font-size: 12px; color: #78909C; font-weight: bold;")
        layout.addWidget(title)
        for name in recent:
            pill = QPushButton(name)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.setStyleSheet(
                "QPushButton { background-color: #F1F5F9; color: #334155;"
                "border: 1px solid #CBD5E1; border-radius: 12px;"
                "padding: 4px 12px; font-size: 12.5px; text-align: left; }"
                "QPushButton:hover { background-color: #E2E8F0;"
                "border-color: #1565C0; color: #1565C0; }"
            )
            pill.clicked.connect(
                lambda _checked=False, n=name: self.start_teach_by_name(n)
            )
            layout.addWidget(pill)
        host.setVisible(True)

    def _on_recommend_next(self):
        """Pick the best next concept using adaptive_path scoring and teach it.

        Uses the same adaptive_path algorithm that powers the learner view's
        study queue 鈥?mastery deficit, anomaly links, stuck concepts,
        foundational leverage, and prerequisite readiness 鈥?to pick the
        single best concept to study right now. Shows a reason tooltip so
        the learner understands *why* this concept was recommended.
        """
        asset = self._main.get_asset()
        if asset is None:
            return
        from expert_anything.core.learner import adaptive_path
        from expert_anything.core.teacher import anomaly_concept_ids
        from expert_anything.core.i18n import t as _t

        # Gather anomaly IDs for this asset's teacher model
        anomaly_ids: set = set()
        tm = self._main._teacher_models.get(asset.asset_id)
        if tm:
            anomaly_ids = set(anomaly_concept_ids(tm))

        items = adaptive_path(asset, self._main.learner, anomaly_ids, limit=1)
        if not items:
            # All mastered 鈥?suggest reviewing the weakest
            from expert_anything.core.learner import due_for_review
            due = due_for_review(self._main.learner, asset=asset)
            if due:
                name = due[0]["name"]
                idx = self._concept_list.findText(name)
                if idx >= 0:
                    self._concept_list.setCurrentIndex(idx)
                self._on_start_teach()
                return
            return

        rec = items[0]
        name = rec["name"]
        tags = rec.get("tags", [])
        idx = self._concept_list.findText(name)
        if idx >= 0:
            self._concept_list.setCurrentIndex(idx)

        # Build a human-readable reason
        reasons = []
        tag_map = {
            "anom": _t("rec_reason_anom"),
            "stuck": _t("rec_reason_stuck"),
            "weak": _t("rec_reason_weak"),
            "high_leverage": _t("rec_reason_leverage"),
            "ready": _t("rec_reason_ready"),
            "prereq_shaky": _t("rec_reason_prereq"),
            "unblock_stuck": _t("rec_reason_unblock_stuck"),
            "foundation": _t("rec_reason_foundation"),
        }
        for t in tags:
            if t in tag_map and tag_map[t] not in reasons:
                reasons.append(tag_map[t])
        reason_str = " 路 ".join(reasons[:3]) if reasons else _t("rec_reason_default")

        # Show a brief toast-like message in the result label
        if hasattr(self, "_result_label") and self._result_label:
            self._result_label.setText(
                _t("rec_toast", name=name, reason=reason_str)
            )

        self._on_start_teach()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Slim header
        from expert_anything.ui.widgets.shared import PageHeader

        layout.addWidget(
            PageHeader(self._main._t("nav_teach"), self._main._t("teach_hint"))
        )

        splitter = QSplitter()
        # Left panel: concept selector
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(20, 18, 12, 18)
        left_layout.setSpacing(8)

        concept_label = QLabel(self._main._t("swap_concept"))
        concept_label.setStyleSheet(
            f"font-size: 12.5px; font-weight: 600; color: {theme.TEXT_MUTED};"
        )
        left_layout.addWidget(concept_label)

        self._concept_list = QComboBox()
        self._rebuild_concept_list()
        left_layout.addWidget(self._concept_list)

        # Recently-taught quick-jump bar — learners bounce between 3-5
        # concepts while building a mental model; this removes the
        # dropdown hunt when going back to a concept just taught.
        self._recent_host = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_host)
        self._recent_layout.setContentsMargins(0, 10, 0, 0)
        self._recent_layout.setSpacing(5)
        left_layout.addWidget(self._recent_host)
        self._rebuild_recent_bar()

        # Smart recommendation button 鈥?picks the best next concept
        self._recommend_btn = QPushButton(self._main._t("recommend_next"))
        self._recommend_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recommend_btn.setStyleSheet(theme.secondary_button_style())
        self._recommend_btn.setToolTip(self._main._t("recommend_tip"))
        self._recommend_btn.clicked.connect(self._on_recommend_next)
        left_layout.addWidget(self._recommend_btn)

        style_label = QLabel(self._main._t("style_label"))
        style_label.setStyleSheet(
            f"font-size: 12.5px; font-weight: 600; color: {theme.TEXT_MUTED};"
            " margin-top: 10px;"
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
        left_layout.addWidget(self._style_combo)

        # Review mode toggle
        self._review_toggle = QPushButton(self._main._t("review_mode"))
        self._review_toggle.setCheckable(True)
        self._review_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._review_toggle.setStyleSheet(
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_MUTED}; border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; padding: 7px 12px;"
            " font-size: 12.5px; text-align: left; }"
            f"QPushButton:hover {{ background-color: {theme.SURFACE_HOVER}; }}"
            f"QPushButton:checked {{ background-color: {theme.ACCENT_TINT};"
            f" border-color: {theme.ACCENT_SOFT}; color: {theme.ACCENT_HOVER}; }}"
        )
        self._review_toggle.clicked.connect(self._on_review_toggle)
        left_layout.addWidget(self._review_toggle)

        start_btn = QPushButton(self._main._t("start_teach"))
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.setStyleSheet(theme.primary_button_style())
        start_btn.clicked.connect(self._on_start_teach)
        left_layout.addWidget(start_btn)
        left_layout.addStretch()
        splitter.addWidget(left)

        # Right panel: content
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 16, 16, 16)

        self._result_label = QLabel(self._main._t("lesson_ready"))
        self._result_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 13px;"
        )
        right_layout.addWidget(self._result_label)

        self._graph = self._main._teach_graph_ref()
        self._graph.setMinimumHeight(140)
        self._graph.setMaximumHeight(170)
        self._graph.setStyleSheet(
            f"QGraphicsView {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; }}"
        )
        self._graph.setVisible(False)
        right_layout.addWidget(self._graph)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        right_layout.addWidget(self._progress)

        # Topic learning progress banner (hidden by default)
        self._topic_banner = QFrame()
        self._topic_banner.setVisible(False)
        self._topic_banner.setStyleSheet(
            f"QFrame {{ background-color: {theme.ACCENT_TINT};"
            f" border: 1px solid {theme.ACCENT_SOFT};"
            f" border-radius: {theme.RADIUS_MD}px; }}"
        )
        tb_lay = QHBoxLayout(self._topic_banner)
        tb_lay.setContentsMargins(12, 8, 12, 8)
        tb_lay.setSpacing(8)
        self._topic_banner_label = QLabel("")
        self._topic_banner_label.setStyleSheet(
            f"font-size: 13px; color: {theme.ACCENT_HOVER}; font-weight: 600;"
        )
        tb_lay.addWidget(self._topic_banner_label)
        self._topic_next_btn = QPushButton("")
        self._topic_next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._topic_next_btn.setStyleSheet(
            theme.primary_button_style(compact=True)
        )
        self._topic_next_btn.setVisible(False)
        self._topic_next_btn.clicked.connect(self._on_topic_next)
        tb_lay.addWidget(self._topic_next_btn)
        right_layout.addWidget(self._topic_banner)

        self._result_area = QScrollArea()
        self._result_area.setWidgetResizable(True)
        self._result_area.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_LG}px;"
            f" background-color: {theme.SURFACE}; }}"
        )
        # An empty bordered pane reads as "unfinished software"; show a calm
        # placeholder until a concept is picked.  It is replaced by the lesson
        # view through the normal _display_result path.
        empty = QWidget()
        empty_lay = QVBoxLayout(empty)
        empty_lay.setContentsMargins(24, 24, 24, 24)
        empty_lay.addStretch()
        empty_title = QLabel(self._main._t("lesson_ready"))
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setStyleSheet(
            f"font-size: 17px; font-weight: 600; color: {theme.TEXT};"
        )
        empty_lay.addWidget(empty_title)
        empty_hint = QLabel(self._main._t("teach_hint"))
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setStyleSheet(
            f"font-size: 12.5px; color: {theme.TEXT_FAINT}; margin-top: 6px;"
        )
        empty_lay.addWidget(empty_hint)
        empty_lay.addStretch()
        self._result_area.setWidget(empty)
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
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)

        # Canonical style codes (example/diagram/steps) are used internally
        # by the Tutor regardless of UI language.
        _idx_to_code = {0: None, 1: "example", 2: "diagram", 3: "steps"}
        explicit_style = _idx_to_code.get(self._style_combo.currentIndex())

        vary = 1 if self._review_mode else 0
        self._show_teaching_content(concept, vary=vary, style=explicit_style)

    def _show_teaching_content(self, concept, vary=0, style=None):
        # Remember every lesson actually started (even when no evaluation
        # follows) so the recently-taught bar can jump back in one tap.
        record_taught_concept(self._main.learner, concept.name)
        self._main.save_learner_state()
        self._rebuild_recent_bar()

        if not self._tutor:
            asset = self._main.get_asset()
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)

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
        self._retire(self._teach_worker)
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

    def _attach_doubt_strip(self, view, concept):
        """Render the teacher-model doubt strip into a lesson result view.

        Walk-ahead principle (AGENTS.md §2): the teach page must surface the
        system's open doubts about *this* concept, or point at the asset-wide
        open count when this concept is clean. Fully resolved → no strip.
        """
        try:
            asset = self._main.get_asset()
            if asset is None or concept is None:
                return
            if not hasattr(view, "append_doubt_strip"):
                return
            tm = None
            td = getattr(self._main, "teacher_models", {}).get(asset.asset_id)
            if td:
                from expert_anything.core.teacher import (
                    TeacherModel,
                    concept_anomalies,
                )

                tm = TeacherModel.from_dict(td)
            anoms = concept_anomalies(concept, tm) if tm else []
            open_count = len(tm.open_anomalies()) if tm else 0
            view.append_doubt_strip(anoms, open_count)
        except Exception:
            pass

    def _attach_misconceptions(self, view, concept) -> None:
        """Render the teacher model's common misconceptions for this concept.

        Walk-ahead principle (AGENTS.md §2): surface known pitfalls so the
        learner can self-check before the quiz. Silent on failure.
        """
        try:
            asset = self._main.get_asset()
            if asset is None or concept is None:
                return
            if not hasattr(view, "append_misconceptions"):
                return
            td = getattr(self._main, "teacher_models", {}).get(asset.asset_id)
            if not td:
                return
            from expert_anything.core.teacher import TeacherModel

            tm = TeacherModel.from_dict(td)
            note = tm.concept_note_by_id(concept.id)
            if note and note.misconceptions:
                view.append_misconceptions(note.misconceptions)
        except Exception:
            pass

    def _display_result(self, result):
        old = self._result_area.takeWidget()
        if old is not None:
            old.deleteLater()

        from expert_anything.ui.widgets.teach_widgets import TeachResultView

        view = TeachResultView(result, self)
        self._teach_view_widget = view
        self._teach_concept_now = result.get("concept", "")
        self._teach_lesson = result
        # Persist a bounded snapshot of this lesson so the learner can re-read
        # the explanation later without another LLM call (zero-cost review;
        # detail card "重看讲解" reads it).
        try:
            from expert_anything.core.learner import save_lesson_snapshot

            if save_lesson_snapshot(
                self._main.learner,
                result.get("concept", ""),
                self._main.current_asset_id or "",
                result.get("style", ""),
                result.get("explanation", ""),
                result.get("steps", []),
            ):
                self._main.save_learner_state()
        except Exception:
            pass  # snapshot is an enhancement, never blocks the lesson
        # Teacher-model doubt strip (AGENTS.md §2 walk-ahead)
        _asset0 = self._main.get_asset()
        _concept0 = (
            _asset0.concept_by_name(result.get("concept", ""))
            if _asset0 is not None
            else None
        )
        if _concept0 is not None:
            self._attach_doubt_strip(view, _concept0)
            self._attach_misconceptions(view, _concept0)
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
                                    getattr(r, "type", ""),
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
                                    getattr(r, "type", ""),
                                )
                            )
                    if len(neighbors) >= 6:
                        break
                view.set_neighbors(neighbors)

        # Wire practice / quiz / quiz_result / neighbor_clicked signals
        view.practice_requested.connect(self._on_practice_requested)
        view.practice_submit.connect(self._on_practice_submit)
        view.quiz_requested.connect(self._on_quiz_requested)
        view.quiz_result.connect(self._on_quiz_result)
        view.neighbor_clicked.connect(self._on_neighbor_clicked)
        view.next_requested.connect(self._on_next_requested)
        view.retry_requested.connect(self._on_retry_requested)
        view.vary_requested.connect(self._on_vary_requested)
        # Answer submission and follow-up questions live inside the result
        # view, so their widgets are only reachable from here.  Without these
        # two connections the answer box and the question box were painted
        # buttons that did nothing (the whole answer → evaluation → mastery
        # loop was unreachable from the UI).
        view.submit_requested.connect(
            lambda v=view: self._on_submit_requested(v)
        )
        view.followup_requested.connect(self.on_followup)
        # Evidence badge click -> jump the reader to that exact passage
        # (AGENTS.md 长期演进 #1: source-anchored answers).
        view.evidence_jump_requested.connect(self._on_evidence_jump)

        self._result_area.setWidget(view)
        self._progress.setVisible(False)
        self._result_label.setText("")

        # Refresh topic progress banner when a new lesson loads
        self._update_topic_banner()

    def _active_concept(self):
        """Return the currently taught concept, if it is still available."""
        asset = self._main.get_asset()
        if asset is None:
            return None
        return asset.concept_by_name(self._teach_concept_now or "")

    def _on_next_requested(self):
        """Continue with the adaptive recommendation after feedback."""
        self._on_recommend_next()

    def _on_retry_requested(self):
        """Repeat the current concept using the selected teaching style."""
        concept = self._active_concept()
        if concept is not None:
            style = self._IDX_TO_CODE.get(self._style_combo.currentIndex(), None)
            self._show_teaching_content(concept, vary=0, style=style)

    def _on_vary_requested(self):
        """Re-teach the current concept from a different angle."""
        concept = self._active_concept()
        if concept is not None:
            style = self._IDX_TO_CODE.get(self._style_combo.currentIndex(), None)
            self._show_teaching_content(concept, vary=1, style=style)

    def _on_submit_requested(self, view):
        """提交答案 — the answer box belongs to ``view``, so read it there.

        Reading through the live view (instead of a cached widget pointer)
        avoids touching a QTextEdit that ``setWidget`` already deleted.
        """
        box = getattr(view, "answer_input", None)
        if box is None:
            return
        try:
            answer = (box.toPlainText() or "").strip()
        except RuntimeError:  # underlying C++ object already deleted
            return
        if answer:
            self.on_submit_answer(answer)

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
            if self._eval_busy():
                return
            self._eval_answer_text = answer
            self._progress.setVisible(True)
            self._progress.setValue(50)
            self._eval_worker = EvaluateWorker(self._tutor, concept, answer)
            self._eval_worker.finished.connect(self._on_answer_eval_done)
            self._eval_worker.error.connect(
                lambda e: self._on_worker_error("evaluate", e)
            )
            self._eval_worker.start()

    def _eval_busy(self) -> bool:
        return self._eval_worker is not None and self._eval_worker.isRunning()

    def _on_answer_eval_done(self, result: dict):
        self._eval_worker = None
        self._progress.setVisible(False)
        result = result or {}
        score = result.get("score", 0)
        feedback = result.get("feedback", "")
        concept_name = self._teach_concept_now
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = None
        for c in asset.concepts:
            if normalize(c.name) == normalize(concept_name):
                concept = c
                break
        if concept is None:
            return

        lesson = self._teach_lesson or {}
        new_mastery = record_evaluation(
            self._main.learner,
            concept.name,
            asset.asset_id,
            score,
            self._eval_answer_text,
            feedback,
            meta={
                "channel": "answer",
                "style": lesson.get("style", ""),
                "vary": self._teach_vary,
                "review": bool(self._review_mode),
                "rotated_style": bool(lesson.get("rotated_style")),
                "judges": result.get("judges", 1),
            },
        )
        self._main.save_learner_state()
        if score >= 0.6:
            mark_completed(self._main.learner, asset.asset_id, concept.id)
            self._main.save_learner_state()
        self.evaluate_recorded.emit()

        # Stuck detection — feeds teacher model priority, keeps learning loop alive.
        # AutoHarness evolution removed from the main teaching flow: it was
        # polluting the lesson card with meta-optimization suggestions instead
        # of letting the learner focus on the concept.
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
        except Exception:
            pass

        # Review-effectiveness check: a review that scores below the
        # learner's own first-time baseline means the review strategy is
        # not landing — surface it to the teacher model (re-teach with a
        # rotated style) instead of scheduling more of the same review.
        if self._review_mode:
            self._check_review_gain_for(concept, asset)

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
    # Practice (P2 hands-on闂幆)
    # ------------------------------------------------------------------
    def _on_practice_requested(self):
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_name(self._teach_concept_now or "")
        if concept is None:
            return
        if not self._tutor:
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)
        self._practice_concept = concept
        self._retire(self._practice_worker)
        self._practice_worker = PracticeWorker(self._tutor, concept)
        self._practice_worker.finished.connect(self._on_practice_done)
        self._practice_worker.error.connect(
            lambda e: self._on_worker_error("practice", e)
        )
        self._practice_worker.start()

    def _on_practice_done(self, task: dict):
        self._practice_worker = None
        # Keep the task text for the evaluation prompt (evaluate_practice
        # grades against the task, not just the concept).
        self._practice_task = (task or {}).get("task", "") if task else ""
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
        if self._eval_busy():
            return
        concept = self._practice_concept
        task_text = getattr(self, "_practice_task", "")
        self._eval_answer_text = answer
        self._progress.setVisible(True)
        self._progress.setValue(50)
        self._eval_worker = EvaluateWorker(
            self._tutor, concept, answer, practice=True, task=task_text
        )
        self._eval_worker.finished.connect(self._on_practice_eval_done)
        self._eval_worker.error.connect(lambda e: self._on_worker_error("practice", e))
        self._eval_worker.start()

    def _on_practice_eval_done(self, result: dict):
        self._eval_worker = None
        self._progress.setVisible(False)
        concept = self._practice_concept
        asset = self._main.get_asset()
        if concept is None or asset is None:
            return
        result = result or {}
        score = float(result.get("score", 0.0))
        feedback = result.get("feedback", "")
        if self._teach_view_widget:
            self._teach_view_widget.show_practice_result(result)
        record_evaluation(
            self._main.learner,
            concept.name,
            asset.asset_id,
            score,
            self._eval_answer_text,
            feedback,
            meta={
                "channel": "practice",
                "style": (self._teach_lesson or {}).get("style", ""),
                "vary": self._teach_vary,
                "review": bool(self._review_mode),
            },
        )
        if score >= 0.6:
            mark_completed(self._main.learner, asset.asset_id, concept.id)
        self._main.save_learner_state()
        self.evaluate_recorded.emit()
        self._check_harness_for(concept, asset, "practice", score)
        if self._review_mode:
            self._check_review_gain_for(concept, asset)

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
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)
        self._quiz_concept = concept
        # Quiz belongs to the current lesson: snapshot its vary semantics
        # so the recorded meta says whether this was a review quiz.
        self._quiz_vary = bool(self._teach_vary)
        self._retire(self._quiz_worker)
        self._quiz_worker = QuizWorker(self._tutor, concept)
        self._quiz_worker.finished.connect(self._on_quiz_done)
        self._quiz_worker.error.connect(lambda e: self._on_worker_error("quiz", e))
        self._quiz_worker.start()

    def start_topic_teach(
        self, concept_name: str, topic_name: str,
        queue_names: list, mastered_count: int, review: bool = False,
    ):
        """Start teaching a concept as part of a topic learning pack.

        Shows a progress banner above the lesson so the learner can see
        "X of Y done" for the topic. After mastering a concept, auto-advances
        to the next one in the queue 鈥?the learner just keeps going.
        """
        self._topic_name = topic_name
        self._topic_queue = list(queue_names) if queue_names else []
        self._topic_mastered = mastered_count
        # Review pack: every lesson teaches with vary=1 (fresh angle) per
        # AGENTS.md §6; the flag survives queue advances via _on_topic_next.
        self._topic_review = review
        self._review_mode = review
        self._review_toggle.setChecked(review)
        self._update_topic_banner()
        # Start the lesson normally
        idx = self._concept_list.findText(concept_name)
        if idx >= 0:
            self._concept_list.setCurrentIndex(idx)
        self._on_start_teach()

    def _update_topic_banner(self):
        """Update the topic progress banner text and visibility."""
        if not self._topic_name or not self._topic_queue:
            if self._topic_banner:
                self._topic_banner.setVisible(False)
            return
        total = len(self._topic_queue)
        current_idx = -1
        for i, name in enumerate(self._topic_queue):
            if name == self._teach_concept_now:
                current_idx = i
                break
        # Count how many are mastered (those before current + any already mastered)
        done = self._topic_mastered
        pct = int((done / total) * 100) if total > 0 else 0
        if self._topic_banner and self._topic_banner_label:
            self._topic_banner_label.setText(
                self._t(
                    "topic_progress",
                    topic=self._topic_name,
                    done=done,
                    total=total,
                    pct=pct,
                )
            )
            self._topic_banner.setVisible(True)
            # Show "next" button if there's a next concept in the queue
            has_next = current_idx >= 0 and current_idx + 1 < total
            if self._topic_next_btn:
                if has_next:
                    next_name = self._topic_queue[current_idx + 1]
                    self._topic_next_btn.setText(
                        self._t("topic_next", name=next_name)
                    )
                    self._topic_next_btn.setVisible(True)
                else:
                    self._topic_next_btn.setVisible(False)

    def _on_topic_next(self):
        """Advance to the next concept in the topic queue."""
        if not self._topic_queue:
            return
        current_idx = -1
        for i, name in enumerate(self._topic_queue):
            if name == self._teach_concept_now:
                current_idx = i
                break
        if current_idx >= 0 and current_idx + 1 < len(self._topic_queue):
            next_name = self._topic_queue[current_idx + 1]
            idx = self._concept_list.findText(next_name)
            if idx >= 0:
                self._concept_list.setCurrentIndex(idx)
            # Pack semantics win: a review pack keeps vary=1 across the
            # whole queue, a regular pack teaches at vary=0 even if a
            # previous review session left the toggle checked.
            self._review_mode = self._topic_review
            self._review_toggle.setChecked(self._topic_review)
            self._on_start_teach()
        elif self._topic_review:
            # Review pack finished: restore the default teaching mode so
            # the next manual lesson is not silently varied.
            self._topic_review = False
            self._review_mode = False
            self._review_toggle.setChecked(False)

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
        meta = {
            "channel": "quiz",
            "style": (self._teach_lesson or {}).get("style", ""),
            "vary": self._teach_vary,
            "review": bool(self._quiz_vary),
        }
        # The question / my answer / the right answer ride along in the trace:
        # later the concept card can show "what exactly did I miss?" instead of
        # a bare score.  Data comes from the view that rendered the quiz.
        last = getattr(self._teach_view_widget, "_quiz_last", None)
        if isinstance(last, dict) and last.get("question"):
            meta.update(
                {
                    "quiz_kind": last.get("kind", ""),
                    "quiz_question": last.get("question", ""),
                    "quiz_given": last.get("given", ""),
                    "quiz_expected": last.get("expected", ""),
                }
            )
        record_evaluation(
            self._main.learner,
            concept.name,
            asset.asset_id,
            score,
            "",
            "quick self-test",
            meta=meta,
        )
        if score >= 0.6:
            mark_completed(self._main.learner, asset.asset_id, concept.id)
        self._main.save_learner_state()
        self.evaluate_recorded.emit()
        self._check_harness_for(concept, asset, "quiz", score)
        if self._quiz_vary:
            self._check_review_gain_for(concept, asset)

    def _on_neighbor_clicked(self, concept_name: str):
        """Learner clicked a related-concept chip in the teach card 鈥?start
        teaching that concept so the knowledge network is navigable from
        the lesson itself (map navigation 鈫?learning, not just graph 鈫?learning)."""
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_name(concept_name)
        if concept is None:
            return
        # Update the dropdown to reflect the new concept
        idx = self._concept_list.findText(concept.name)
        if idx >= 0:
            self._concept_list.setCurrentIndex(idx)
        if not self._tutor:
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)
        _idx_to_code = {0: None, 1: "example", 2: "diagram", 3: "steps"}
        explicit_style = _idx_to_code.get(self._style_combo.currentIndex())
        self._show_teaching_content(concept, vary=0, style=explicit_style)

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
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)
        lesson = self._teach_lesson
        self._retire(self._followup_worker)
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
    # Stuck detection for practice / quiz channels
    # (AutoHarness evolution removed 鈥?was polluting teaching flow with
    #  meta-optimization suggestions. Stuck detection remains because it
    #  feeds the teacher model's priority system.)
    # ------------------------------------------------------------------
    def _check_harness_for(self, concept, asset, channel, score):
        """Run stuck detection after practice/quiz eval."""
        if concept is None:
            return
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

    def _check_review_gain_for(self, concept, asset):
        """Post-evaluation teacher sync (all three channels land here):

        1. If the concept's review average fell at least 0.1 below its
           first-time baseline, sink a learner_gap anomaly into the teacher
           model so the anomaly-prioritized path re-teaches it (rotated
           style) instead of scheduling more identical reviews.
        2. Resolve anomalies whose fix is now evidenced (mastery back above
           threshold / evidence anchored) so a closed gap stops crying wolf
           in doubt strips and the coach (AGENTS.md §34)."""
        if concept is None:
            return
        from expert_anything.core.teacher import (
            incorporate_review_gain_signal,
            resolve_satisfied_anomalies,
        )

        try:
            teacher = None
            td = self._main.teacher_models.get(asset.asset_id)
            if td:
                teacher = TeacherModel.from_dict(td)
            teacher = incorporate_review_gain_signal(
                asset, teacher, concept.id, self._main.learner
            )
            resolve_satisfied_anomalies(asset, teacher, self._main.learner)
            save_teacher(asset.asset_id, teacher)
            self._main.teacher_models[asset.asset_id] = teacher.to_dict()
        except Exception:
            pass

    def start_teach_by_name(self, concept_name: str, review: bool = False):
        self._review_mode = review
        self._review_toggle.setChecked(review)
        idx = self._concept_list.findText(concept_name)
        if idx >= 0:
            self._concept_list.setCurrentIndex(idx)
        self._on_start_teach()

    def _on_evidence_jump(self, concept_id: str, evidence: str):
        """Evidence badge clicked in the lesson — hand the exact evidence
        text to the reader jump (falls back to concept-level scroll)."""
        self.evidence_jump_requested.emit(concept_id, evidence)

    def start_quick_quiz_by_name(self, concept_name: str):
        """Launch a quick self-test quiz directly (no lesson first).

        Used when the user taps "蹇€熻嚜娴? from the concept detail card on
        the map 鈥?lowers the friction of checking mastery without sitting
        through a full teaching session.
        """
        asset = self._main.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_name(concept_name)
        if concept is None:
            return
        # Select the concept in the dropdown
        idx = self._concept_list.findText(concept_name)
        if idx >= 0:
            self._concept_list.setCurrentIndex(idx)
        self._teach_concept_now = concept_name
        if not self._tutor:
            from expert_anything.core.tutor import Tutor
            self._tutor = Tutor(asset, llm=self._main.llm_client, learner_state=self._main.learner)
        # Build a minimal result view so the quiz has somewhere to render.
        # TeachResultView takes (result_dict, parent) and communicates via
        # signals — the old kwargs-style call here raised TypeError on the
        # first quick-quiz from the concept card.
        if self._teach_view_widget is None:
            from expert_anything.ui.widgets.teach_widgets import TeachResultView

            self._teach_view_widget = TeachResultView(
                {"concept": concept.name, "explanation": ""}, self
            )
            view = self._teach_view_widget
            view.quiz_requested.connect(self._on_quiz_requested)
            view.quiz_result.connect(self._on_quiz_result)
            view.practice_requested.connect(self._on_practice_requested)
            view.practice_submit.connect(self._on_practice_submit)
            view.neighbor_clicked.connect(self._on_neighbor_clicked)
            view.next_requested.connect(self._on_next_requested)
            view.retry_requested.connect(self._on_retry_requested)
            view.vary_requested.connect(self._on_vary_requested)
            view.submit_requested.connect(
                lambda v=view: self._on_submit_requested(v)
            )
            view.followup_requested.connect(self.on_followup)
            self._result_area.setWidget(view)
        self._quiz_concept = concept
        # Standalone quick-quiz from the map card: no lesson context, so
        # never inherit a stale review flag from a previous lesson.
        self._quiz_vary = False
        self._retire(self._quiz_worker)
        self._quiz_worker = QuizWorker(self._tutor, concept)
        self._quiz_worker.finished.connect(self._on_quiz_done)
        self._quiz_worker.error.connect(lambda e: self._on_worker_error("quiz", e))
        self._quiz_worker.start()

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
