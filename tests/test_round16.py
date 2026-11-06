# -*- coding: utf-8 -*-
"""Round 16 tests: answer / follow-up wiring, graph evidence jump, TOC
double-click evidence, and dead-signal cleanup."""
import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo  # noqa: E402

ensure_demo()

from expert_anything.core.i18n import t as _t  # noqa: E402

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QPushButton, QTreeWidgetItem
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound16UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.app = load_main_window()

    def setUp(self):
        # Every test wants the reader/teach wiring in a known state.
        self.app.on_nav_click("knowledge")

    def _patch(self, obj, name, value):
        """Temporarily replace an attribute and restore it after the test.

        Instance-level handlers are real wiring other tests depend on — a
        leftover lambda would make the next case look broken for the wrong
        reason.
        """
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def _flush(self):
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    # -- candidate 1: the answer → evaluation → mastery loop is reachable -----
    def test_teach_submit_button_reaches_evaluate(self):
        tv = self.app._teach_view
        asset = self.app.get_asset()
        concept = asset.concepts[0]
        tv._display_result(
            {
                "concept": concept.name,
                "explanation": "讲解",
                "practice": "请举一个例子说明。",
            }
        )
        QApplication.processEvents()
        self._flush()

        view = tv._teach_view_widget
        self.assertIsNotNone(view.answer_input, "practice lesson exposes an answer box")

        got = []
        self._patch(tv, "on_submit_answer", lambda answer: got.append(answer))

        btns = [b for b in view.findChildren(QPushButton) if b.text() == _t("submit_answer")]
        self.assertTrue(btns, "the answer card must have a submit button")
        view.answer_input.setPlainText("我的答案")
        btns[0].click()
        QApplication.processEvents()
        self.assertEqual(got, ["我的答案"], "submit must forward the typed answer")

        # a blank answer is not a submission
        view.answer_input.setPlainText("   ")
        btns[0].click()
        QApplication.processEvents()
        self.assertEqual(got, ["我的答案"], "empty answers must be ignored")

    def test_teach_followup_reaches_handler(self):
        tv = self.app._teach_view
        asset = self.app.get_asset()
        concept = asset.concepts[0]
        tv._display_result(
            {"concept": concept.name, "explanation": "讲解"}
        )
        QApplication.processEvents()
        self._flush()

        view = tv._teach_view_widget
        self.assertIsNotNone(view._followup_input, "follow-up box is always built")

        got = []
        self._patch(tv, "on_followup", lambda question: got.append(question))

        ask = [b for b in view.findChildren(QPushButton) if b.text() == _t("ask")]
        self.assertTrue(ask, "the follow-up card must have an ask button")
        view._followup_input.setPlainText("为什么这样？")
        ask[0].click()
        QApplication.processEvents()
        self.assertEqual(got, ["为什么这样？"], "ask must forward the question")

        # blank questions are ignored
        view._followup_input.setPlainText("")
        ask[0].click()
        QApplication.processEvents()
        self.assertEqual(got, ["为什么这样？"])

    # -- candidate 2: graph context-menu evidence jump ------------------------
    def test_graph_evidence_signal_is_dedicated_and_wired(self):
        from expert_anything.ui.pyside_graph import KnowledgeGraphView

        # The single-click channel must not be reused for the menu action.
        self.assertFalse(
            hasattr(KnowledgeGraphView, "concept_drilldown"),
            "the multiplexed drill-down signal must be gone",
        )
        self.assertTrue(hasattr(KnowledgeGraphView, "evidence_requested"))

        gv = self.app._graph_view_ref()
        asset = self.app.get_asset()
        cid = asset.concepts[0].id

        got = []
        self._patch(
            self.app, "_on_teach_evidence_jump", lambda ref, ev="": got.append((ref, ev))
        )
        gv.evidence_requested.emit(cid)
        QApplication.processEvents()
        self.assertEqual(got, [(cid, "")], "menu signal must reach the evidence jump")

    # -- candidate 3: TOC double-click opens the live evidence ---------------
    def test_toc_double_click_lands_in_live_reader(self):
        from expert_anything.ui.views.knowledge_view import _ROLE_PAYLOAD

        kv = self.app._knowledge_view
        asset = self.app.get_asset()
        cid = asset.learning_path[0] if asset.learning_path else asset.concepts[0].id

        item = QTreeWidgetItem()
        item.setData(0, _ROLE_PAYLOAD, ("concept", cid))
        kv._on_toc_double_clicked(item)
        QApplication.processEvents()

        live = self.app.source_view._source_widget
        self.assertIsNotNone(live)
        self.assertIs(
            self.app._source_view_widget,
            live,
            "cached reader ref must follow the view refresh (no stale widget)",
        )
        self.assertGreater(
            live.textCursor().position(), 0, "the jump must land in the live reader"
        )

    def test_toc_double_click_ignores_chapter_rows(self):
        from expert_anything.ui.views.knowledge_view import _ROLE_PAYLOAD

        kv = self.app._knowledge_view
        got = []
        self._patch(
            self.app, "_on_jump_to_evidence", lambda cid, ev="": got.append((cid, ev))
        )

        item = QTreeWidgetItem()
        item.setData(0, _ROLE_PAYLOAD, ("chapter", "第一章"))
        kv._on_toc_double_clicked(item)
        QApplication.processEvents()
        self.assertEqual(got, [], "only concept rows jump to evidence")

    # -- candidate 3: dead signals removed, real behaviour kept ---------------
    def test_dead_signals_removed(self):
        from expert_anything.ui.views.teacher_view import TeacherView
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        self.assertFalse(hasattr(TeacherView, "teacher_rebuilt"))
        self.assertFalse(hasattr(NodeDetailCard, "favorite_toggled"))

    def test_favorite_star_still_persists(self):
        from unittest.mock import patch

        from expert_anything.core.learner import is_favorite
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        state = {
            "profile": {},
            "concepts": {},
            "assets": {},
            "history": [],
            "favorites": [],
        }
        card = NodeDetailCard()
        card.set_concept(asset, concept.id, state, None)
        try:
            star = card.findChild(QPushButton, "fav_star_btn")
            self.assertIsNotNone(star)
            self.assertFalse(is_favorite(state, concept.name))
            with patch("expert_anything.core.learner.save"):  # no disk write
                star.click()
            self.assertTrue(is_favorite(state, concept.name), "star must persist")
            self.assertEqual(star.text(), "★")
        finally:
            card.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
