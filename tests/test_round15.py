# -*- coding: utf-8 -*-
"""Round 15 tests: full error book, own-answer replay, quiz-miss trace,
reader note summary."""
import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo

ensure_demo()

from expert_anything.core import learner  # noqa: E402
from expert_anything.core.i18n import t as _t  # noqa: E402

try:
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


def _history_row(concept: str, score: float, answer: str = "", **meta):
    row = {
        "concept": concept,
        "key": learner.normalize(concept),
        "asset_id": "a-test",
        "score": score,
        "answer": answer,
        "feedback": "",
        "at": "",
    }
    if meta:
        row["meta"] = meta
    return row


class TestQuizAnswerCode(unittest.TestCase):
    def test_true_false_codes_are_language_neutral(self):
        from expert_anything.ui.widgets.teach_widgets import TeachResultView

        self.assertEqual(TeachResultView._quiz_answer_code("true_false", True), "true")
        self.assertEqual(
            TeachResultView._quiz_answer_code("true_false", False), "false"
        )

    def test_ordering_codes_use_one_based_numbers(self):
        from expert_anything.ui.widgets.teach_widgets import TeachResultView

        self.assertEqual(
            TeachResultView._quiz_answer_code("ordering", [2, 0, 1]),
            "3 → 1 → 2",
        )


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound15UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.app = load_main_window()

    def _flush_deletes(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _weak_rows(self, n: int):
        return [
            {
                "concept": f"薄弱概念{i}",
                "score": 0.2,
                "answer": f"我的答案{i}",
                "feedback": "需要重学",
            }
            for i in range(n)
        ]

    def test_error_book_shows_five_then_all(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QApplication

        rows = self._weak_rows(8)
        with patch(
            "expert_anything.core.learner.weak_history", return_value=rows
        ):
            self.app.on_nav_click("learner")
            QApplication.processEvents()
        self._flush_deletes()
        entries = self.app.learner_view.findChildren(QWidget, "error_book_entry")
        self.assertEqual(len(entries), 8)
        visible = [w for w in entries if not w.isHidden()]
        self.assertEqual(len(visible), 5, "error book defaults to five entries")

        btns = self.app.learner_view.findChildren(
            QPushButton, "error_book_show_all_btn"
        )
        self.assertTrue(btns, "eight weak entries must offer 'show all'")
        btns[0].click()
        QApplication.processEvents()
        visible = [w for w in entries if not w.isHidden()]
        self.assertEqual(len(visible), 8, "show all must reveal every entry")

        btns[0].click()
        QApplication.processEvents()
        visible = [w for w in entries if not w.isHidden()]
        self.assertEqual(len(visible), 5, "toggle collapses back to five")

    def test_my_answers_card_replays_own_words(self):
        from PySide6.QtWidgets import QApplication

        old_history = self.app.learner.get("history")
        self.app.learner["history"] = [
            _history_row(
                "节点边际电价(LMP)",
                0.72,
                "电价由供需与边际成本共同决定",
                channel="practice",
            )
        ]
        try:
            self.app.learner_view.refresh()
            QApplication.processEvents()
            self._flush_deletes()
            card = self.app.learner_view.findChild(QWidget, "my_answers_card")
            self.assertIsNotNone(card, "own answers need an aggregate replay card")
            labels = self.app.learner_view.findChildren(QLabel, "my_answers_lbl")
            self.assertTrue(labels)
            self.assertIn("边际成本", labels[0].text())
            channels = [
                lbl.text() for lbl in card.findChildren(QLabel)
            ]
            self.assertIn(_t("breakdown_practice"), channels)
        finally:
            self.app.learner["history"] = old_history
            self.app.learner_view.refresh()

    def test_concept_card_shows_quiz_miss_comparison(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        state = {
            "concepts": {},
            "history": [
                _history_row(
                    concept.name,
                    0.2,
                    "",
                    channel="quiz",
                    quiz_kind="true_false",
                    quiz_question="节点边际电价反映的是供需平衡吗？",
                    quiz_given="false",
                    quiz_expected="true",
                )
            ],
        }
        card = NodeDetailCard()
        card.set_concept(asset, concept.id, state, None)
        labels = card.findChildren(QLabel, "quiz_miss_lbl")
        texts = " | ".join(lbl.text() for lbl in labels)
        self.assertIn("题目", texts)
        self.assertIn("供需平衡", texts)
        self.assertIn(_t("quiz_false"), texts)
        self.assertIn(_t("quiz_true"), texts)
        card.deleteLater()

    def test_concept_card_hides_passed_quiz(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        state = {
            "concepts": {},
            "history": [
                _history_row(
                    concept.name,
                    1.0,
                    "",
                    channel="quiz",
                    quiz_kind="true_false",
                    quiz_question="节点边际电价反映的是供需平衡吗？",
                    quiz_given="true",
                    quiz_expected="true",
                )
            ],
        }
        card = NodeDetailCard()
        card.set_concept(asset, concept.id, state, None)
        self.assertEqual(card.findChildren(QLabel, "quiz_miss_lbl"), [])
        card.deleteLater()

    def test_reader_shows_note_summary_and_expands(self):
        from PySide6.QtWidgets import QApplication

        asset = self.app.get_asset()
        self.assertIsNotNone(asset)
        concept = asset.concepts[0]
        long_note = "我的理解：" + "这是一段用于验证展开按钮的长笔记。" * 6
        old_note = learner.get_note(self.app.learner, concept.name)
        learner.set_note(self.app.learner, concept.name, long_note)
        try:
            self.app.on_nav_click("source")
            self.app.source_view.refresh()
            QApplication.processEvents()
            self._flush_deletes()
            combo = self.app.source_view._concept_combo
            self.assertIsNotNone(combo)
            idx = combo.findText(concept.name)
            self.assertGreaterEqual(idx, 0)
            combo.setCurrentIndex(idx)
            QApplication.processEvents()

            summary = self.app.source_view._reader_note_summary
            self.assertIsNotNone(summary)
            box = self.app.source_view._reader_note_box
            self.assertIsNotNone(box)
            self.assertFalse(box.isHidden(), "a note must surface while reading")
            self.assertIn("我的理解", summary.text())
            more = self.app.source_view._reader_note_more
            self.assertIsNotNone(more)
            self.assertFalse(more.isHidden(), "long notes need an expand toggle")
            more.click()
            QApplication.processEvents()
            self.assertIn(long_note[-10:], summary.text())
        finally:
            learner.set_note(self.app.learner, concept.name, old_note)

    def test_reader_hides_summary_without_note(self):
        from PySide6.QtWidgets import QApplication

        asset = self.app.get_asset()
        concept = asset.concepts[0]
        old_note = learner.get_note(self.app.learner, concept.name)
        learner.set_note(self.app.learner, concept.name, "")
        try:
            self.app.on_nav_click("source")
            self.app.source_view.refresh()
            QApplication.processEvents()
            self._flush_deletes()
            combo = self.app.source_view._concept_combo
            idx = combo.findText(concept.name)
            combo.setCurrentIndex(idx)
            QApplication.processEvents()
            box = self.app.source_view._reader_note_box
            self.assertIsNotNone(box)
            self.assertTrue(box.isHidden(), "no note → no summary strip")
        finally:
            learner.set_note(self.app.learner, concept.name, old_note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
