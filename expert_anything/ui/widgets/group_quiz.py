"""Chapter / topic comprehensive quiz: mixed questions across a concept group.

A quick self-test checks one concept's recall; this flow checks the structure
the learner just walked through — several concepts of one chapter or topic
cluster, one mixed question each (true/false or ordering), every answer scored
locally and recorded through the existing quiz channel (``learner.record_evaluation``
with ``channel="quiz"``), then summarised as group mastery.

The LLM (when configured) only writes the questions (reusing the existing
``Tutor.generate_quiz`` admission path); scoring, recording and the summary are
deterministic code.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.i18n import t as _t
from expert_anything.core.learner import mark_completed, record_evaluation
from expert_anything.core.tutor import Tutor

GROUP_QUIZ_MAX = 5  # questions per group: bounded so a group quiz stays a quiz


class GroupQuizWorker(QThread):
    """Generate one quiz per concept, alternating type for coverage."""

    ready = Signal(list)  # [{"concept": name, "concept_id": id, "quiz": dict}]
    error = Signal(str)

    def __init__(self, tutor, concepts, limit: int = GROUP_QUIZ_MAX):
        super().__init__()
        self._tutor = tutor
        self._concepts = list(concepts)[:limit]

    def run(self):
        try:
            out = []
            for i, c in enumerate(self._concepts):
                quiz = self._tutor.generate_quiz(
                    c, qtype=("true_false" if i % 2 == 0 else "ordering")
                )
                if quiz:
                    out.append(
                        {"concept": c.name, "concept_id": c.id, "quiz": quiz}
                    )
            self.ready.emit(out)
        except Exception as exc:  # generation failure must not break the flow
            self.error.emit(str(exc))


class GroupQuizDialog(QDialog):
    """Walk a concept group: one question each, then a group mastery summary."""

    def __init__(self, main, asset, concept_ids, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("group_quiz_title", name=title))
        self.setMinimumWidth(560)
        self.setMinimumHeight(440)
        self._main = main
        self._asset = asset
        self._items: list[dict] = []
        self._idx = -1
        self._scores: list[tuple[str, float]] = []
        self._quiz = None
        self._answer: list[int] = []
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)
        head = QLabel(_t("group_quiz_title", name=title))
        head.setStyleSheet("font-size: 16px; font-weight: bold; color: #6A1B9A;")
        root.addWidget(head)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size: 13px; color: #7B5A9E;")
        root.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._area = QWidget()
        self._area_lay = QVBoxLayout(self._area)
        self._area_lay.setContentsMargins(0, 0, 0, 0)
        self._area_lay.setSpacing(8)
        self._area_lay.addStretch()
        self._scroll.setWidget(self._area)
        root.addWidget(self._scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton(_t("flashcard_close"))
        close_btn.setObjectName("group_quiz_close_btn")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        concepts = [asset.concept_by_id(cid) for cid in concept_ids]
        concepts = [c for c in concepts if c is not None]
        if not concepts:
            self._status.setText(_t("group_quiz_no_concepts"))
            return
        tutor = Tutor(
            asset,
            llm=getattr(main, "llm_client", None),
            learner_state=getattr(main, "learner", None),
        )
        self._status.setText(
            _t("group_quiz_generating", n=min(len(concepts), GROUP_QUIZ_MAX))
        )
        self._worker = GroupQuizWorker(tutor, concepts)
        self._worker.ready.connect(self._on_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # -- question flow --------------------------------------------------------
    def _insert(self, widget) -> None:
        self._area_lay.insertWidget(self._area_lay.count() - 1, widget)

    def _clear_area(self) -> None:
        while self._area_lay.count() > 1:  # keep the trailing stretch
            item = self._area_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _on_error(self, _msg: str) -> None:
        self._status.setText(_t("group_quiz_failed"))

    def _on_ready(self, items: list) -> None:
        if not items:
            self._status.setText(_t("group_quiz_failed"))
            return
        self._items = items
        self._next_question()

    def _next_question(self) -> None:
        self._idx += 1
        if self._idx >= len(self._items):
            self._show_summary()
            return
        item = self._items[self._idx]
        self._quiz = item["quiz"]
        self._answer = []
        self._status.setText(
            _t(
                "group_quiz_progress",
                i=self._idx + 1,
                n=len(self._items),
                name=item["concept"],
            )
        )
        self._clear_area()

        quiz = self._quiz
        qtype = quiz.get("type")
        card = QFrame()
        card.setObjectName("group_quiz_card")
        card.setStyleSheet(
            "QFrame#group_quiz_card { background-color: #F3E5F5;"
            "border: 2px solid #AB47BC; border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        badge = QLabel(
            _t("quiz_true_false") if qtype == "true_false" else _t("quiz_ordering")
        )
        badge.setStyleSheet(
            "background-color: #AB47BC; color: white; padding: 2px 10px;"
            "border-radius: 8px; font-size: 12px; font-weight: bold;"
        )
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        q = QLabel(quiz.get("question", ""))
        q.setWordWrap(True)
        q.setStyleSheet("font-size: 15px; color: #37474F; font-weight: bold;")
        lay.addWidget(q)

        if qtype == "true_false":
            row = QHBoxLayout()
            row.setSpacing(8)
            for val, label in [(True, _t("quiz_true")), (False, _t("quiz_false"))]:
                b = QPushButton(label)
                b.setStyleSheet(
                    "QPushButton { background-color: white; color: #6A1B9A;"
                    "border: 1px solid #CE93D8; border-radius: 6px;"
                    "padding: 6px 18px; font-size: 14.5px; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                b.clicked.connect(lambda checked, v=val: self._check(v))
                row.addWidget(b)
            row.addStretch()
            lay.addLayout(row)
        else:
            self._order_label = QLabel("")
            self._order_label.setObjectName("group_quiz_order_lbl")
            self._order_label.setStyleSheet("font-size: 14px; color: #6A1B9A;")
            lay.addWidget(self._order_label)
            for i, opt in enumerate(quiz.get("options", [])):
                b = QPushButton(f"{i + 1}. {opt}")
                b.setStyleSheet(
                    "QPushButton { background-color: white; color: #37474F;"
                    "border: 1px solid #E1BEE7; border-radius: 6px;"
                    "padding: 5px 10px; font-size: 14px; text-align: left; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                b.clicked.connect(lambda checked, idx=i: self._pick_order(idx))
                lay.addWidget(b)
            check = QPushButton(_t("quiz_check"))
            check.setStyleSheet(
                "QPushButton { background-color: #6A1B9A; color: white;"
                "border: none; border-radius: 6px; padding: 5px 14px;"
                "font-size: 14px; }"
            )
            check.clicked.connect(lambda: self._check(list(self._answer)))
            lay.addWidget(check, 0, Qt.AlignmentFlag.AlignRight)
        self._insert(card)

    def _pick_order(self, idx: int) -> None:
        if idx not in self._answer:
            self._answer.append(idx)
        self._order_label.setText(
            " → ".join(str(i + 1) for i in self._answer)
        )

    def _score_answer(self, answer) -> float:
        quiz = self._quiz or {}
        if quiz.get("type") == "true_false":
            return 1.0 if bool(answer) == bool(quiz.get("correct")) else 0.2
        correct = quiz.get("correct_order", [])
        if not correct or len(answer) != len(correct):
            return 0.0
        hits = sum(1 for a, c in zip(answer, correct) if a == c)
        return round(hits / len(correct), 2)

    def _check(self, answer) -> None:
        """Score locally, record into mastery, then offer the next question."""
        if self._quiz is None or not (0 <= self._idx < len(self._items)):
            return
        score = self._score_answer(answer)
        item = self._items[self._idx]
        name = item["concept"]
        self._scores.append((name, score))
        self._record(name, score)

        result = QFrame()
        result.setObjectName("group_quiz_result")
        ok = score >= 0.6
        result.setStyleSheet(
            "QFrame#group_quiz_result {"
            f"background-color: {'#E8F5E9' if ok else '#FFEBEE'};"
            f"border-left: 4px solid {'#2E7D32' if ok else '#C62828'};"
            "border-radius: 6px; }"
        )
        rl = QVBoxLayout(result)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(4)
        verdict = _t("quiz_correct") if ok else _t("quiz_wrong")
        v = QLabel(f"{name} · {verdict}  ({score:.0%})")
        v.setStyleSheet(
            f"color: {'#2E7D32' if ok else '#C62828'};"
            "font-size: 14.5px; font-weight: bold;"
        )
        rl.addWidget(v)
        quiz = self._quiz
        if quiz.get("type") == "ordering" and quiz.get("correct_order"):
            right = " → ".join(str(i + 1) for i in quiz["correct_order"])
            rl.addWidget(QLabel(f"{_t('quiz_correct_order')}: {right}"))
        if quiz.get("explanation"):
            e = QLabel(quiz["explanation"])
            e.setWordWrap(True)
            e.setStyleSheet("font-size: 14px; color: #37474F;")
            rl.addWidget(e)
        self._insert(result)

        nxt = QPushButton(_t("group_quiz_next"))
        nxt.setObjectName("group_quiz_next_btn")
        nxt.setStyleSheet(
            "QPushButton { background-color: #6A1B9A; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 14px;"
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #4A148C; }"
        )
        nxt.clicked.connect(self._next_question)
        self._insert(nxt)

    def _record(self, concept_name: str, score: float) -> None:
        """Record the group-quiz answer through the existing quiz channel."""
        learner = getattr(self._main, "learner", None)
        if learner is None:
            return
        asset_id = getattr(self._main, "current_asset_id", "") or ""
        record_evaluation(
            learner,
            concept_name,
            asset_id,
            float(score),
            "",
            "group quiz",
            meta={
                "channel": "quiz",
                "style": "",
                "vary": False,
                "review": False,
            },
        )
        if score >= 0.6:
            concept = self._asset.concept_by_name(concept_name)
            if concept is not None:
                mark_completed(learner, asset_id, concept.id)
        self._main.save_learner_state()

    def _show_summary(self) -> None:
        """Group mastery summary: per-concept scores + weak-concept pointer."""
        self._clear_area()
        total = len(self._scores)
        avg = (sum(s for _, s in self._scores) / total) if total else 0.0
        self._status.setText(_t("group_quiz_summary_title"))

        card = QFrame()
        card.setObjectName("group_quiz_summary")
        card.setStyleSheet(
            "QFrame#group_quiz_summary { background-color: white;"
            "border: 1px solid #E0E0E0; border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        avg_lbl = QLabel(_t("group_quiz_summary_avg", avg=f"{avg:.0%}", n=total))
        avg_lbl.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #6A1B9A;"
        )
        lay.addWidget(avg_lbl)
        for name, score in self._scores:
            row = QLabel(f"{'✓' if score >= 0.6 else '✗'} {name}  {score:.0%}")
            row.setStyleSheet(
                f"font-size: 14px; color: {'#2E7D32' if score >= 0.6 else '#C62828'};"
            )
            lay.addWidget(row)
        hint = QLabel(_t("group_quiz_summary_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 13px; color: #6B7A90;")
        lay.addWidget(hint)
        self._insert(card)
