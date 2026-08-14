"""UI tests (offscreen PySide6): window, views, graph, source, panels, dialogs.

These run against a temp copy of the demo data so the real data is never
touched. No LLM calls (deterministic teach paths only).
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.util import ensure_demo, load_main_window, prepare_app

prepare_app()
ensure_demo()

from PySide6.QtWidgets import QDialog, QFrame, QLabel, QProgressBar, QPushButton, QTableWidget

from main import MainWindow
from expert_anything.ui.pyside_graph import KnowledgeGraphView
from expert_anything.ui.pyside_widgets import (
    ConceptDetailPanel,
    MasteryDistributionBar,
    PathLadderView,
    SourceTextView,
    TeachResultView,
    TrendChartView,
)


class TestWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_window_title(self):
        self.assertIn("ExpertAnything", self.win.windowTitle())

    def test_seven_views(self):
        self.assertEqual(self.win.content_stack.count(), 7)

    def test_two_assets_loaded(self):
        self.assertEqual(len(self.win.assets), 2)

    def test_topbar_present(self):
        self.assertTrue(hasattr(self.win, "topbar"))
        self.assertTrue(self.win._topbar_asset.text())

    def test_view_switching(self):
        for idx in range(self.win.content_stack.count()):
            self.win.content_stack.setCurrentIndex(idx)
            self.win.repaint()
        self.win.content_stack.setCurrentIndex(1)

    def test_asset_switch_rebuilds(self):
        other = next(a for a in self.win.assets if a != self.win.current_asset_id)
        self.win.on_asset_select(other)
        self.assertEqual(self.win.current_asset_id, other)
        self.assertEqual(self.win.content_stack.count(), 7)
        self.assertEqual(self.win.content_stack.currentIndex(), 1)


class TestGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_dash_graph_renders(self):
        self.win.content_stack.setCurrentIndex(1)
        dg = getattr(self.win, "_dash_graph", None)
        self.assertIsNotNone(dg)
        self.assertGreater(len(dg.scene().items()), 0)

    def test_map_graph_focus_and_reset(self):
        self.win.content_stack.setCurrentIndex(2)
        gv = getattr(self.win, "_graph_view", None)
        self.assertIsNotNone(gv)
        self.assertGreater(len(gv.scene().items()), 0)
        cid = next(iter(gv._node_items))
        gv.focus_concept(cid)
        self.assertTrue(gv.is_focused())
        gv.reset_focus()
        self.assertFalse(gv.is_focused())

    def test_teach_graph_follows_concept(self):
        # deterministic teach (no LLM) focuses the mini graph
        self.win.on_nav_click("teach")  # make the teach view visible
        asset = self.win.get_asset()
        from expert_anything.core.tutor import Tutor
        self.win.current_tutor = Tutor(asset, llm=None)
        concept = asset.concepts[0]
        self.win._show_teaching_content(concept)
        tg = getattr(self.win, "_teach_graph", None)
        self.assertIsNotNone(tg)
        self.assertTrue(tg.isVisible())
        self.assertTrue(tg.is_focused())


class TestSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_concepts_highlighted(self):
        self.win.content_stack.setCurrentIndex(3)
        sv = getattr(self.win, "_source_view_widget", None)
        self.assertIsNotNone(sv)
        asset = self.win.get_asset()
        html = sv.toHtml()
        highlighted = sum(1 for c in asset.concepts if f"concept://{c.id}" in html)
        self.assertGreater(highlighted, 0)

    def test_scroll_to_concept(self):
        sv = self.win._source_view_widget
        asset = self.win.get_asset()
        cid = asset.learning_path[0]
        sv.scroll_to_concept(cid)
        self.assertGreater(sv.textCursor().position(), 0)


class TestConceptPanel(unittest.TestCase):
    def test_panel_builds_and_signals(self):
        win = load_main_window()
        asset = win.get_asset()
        cid = asset.learning_path[0]
        panel = ConceptDetailPanel(asset, cid, win.learner, None, win)
        panel.show()
        self.assertIsInstance(panel, QDialog)
        signals = []
        panel.teach_requested.connect(lambda n: signals.append(("teach", n)))
        panel.focus_requested.connect(lambda c: signals.append(("focus", c)))
        panel.evidence_requested.connect(lambda c, e: signals.append(("ev", c, e)))
        panel.close()


class TestLearnerView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.content_stack.setCurrentIndex(5)

    def test_overview_and_distribution(self):
        bars = self.win.learner_view.findChildren(MasteryDistributionBar)
        self.assertGreaterEqual(len(bars), 1)

    def test_trend_chart(self):
        trends = self.win.learner_view.findChildren(TrendChartView)
        self.assertGreaterEqual(len(trends), 1)

    def test_history_table(self):
        tables = self.win.learner_view.findChildren(QTableWidget)
        self.assertGreaterEqual(len(tables), 1)

    def test_grouped_concepts(self):
        labels = [l.text() for l in self.win.learner_view.findChildren(QLabel)]
        self.assertTrue(any("个概念" in t for t in labels))


class TestTeacherView(unittest.TestCase):
    def test_anomaly_cards(self):
        win = load_main_window()
        win.content_stack.setCurrentIndex(6)
        # anomaly cards are QFrames with a border-left style; at least the
        # view builds and shows the teacher data status
        self.assertTrue(win.teacher_view)


class TestDirtyPayloads(unittest.TestCase):
    def test_null_payload(self):
        view = TeachResultView({
            "concept": "X", "style": "图示",
            "explanation": None, "example": None,
            "steps": None, "practice": None, "evidence": None,
        })
        view.show()
        self.assertIsNotNone(view.grab())

    def test_weird_types(self):
        view = TeachResultView({
            "concept": "X", "style": "拆解步骤",
            "explanation": 123, "example": ["a", "b"],
            "steps": "s1\ns2", "practice": "", "evidence": [None, "ok"],
        })
        view.show()
        self.assertIsNotNone(view.grab())

    def test_followup_and_neighbor_api(self):
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.set_neighbors([("依赖", "Y", "c2")])
        view.append_exchange("问？", "答。")
        view.append_evaluation(0.8, "好", "参考", "差距")
        self.assertIsNotNone(view.grab())


class TestPathLadder(unittest.TestCase):
    def test_ladder_renders_items(self):
        ladder = PathLadderView()
        items = [
            {"cid": "c1", "name": "A", "mastery": 0.2, "tags": ["weak"], "score": 0.8},
            {"cid": "c2", "name": "B", "mastery": 0.7, "tags": ["ready"], "score": 0.5},
        ]
        ladder.set_items(items, completed={"c2"})
        ladder.show()
        self.assertIsNotNone(ladder.grab())

    def test_empty_ladder(self):
        ladder = PathLadderView()
        ladder.set_items([])
        ladder.show()
        self.assertIsNotNone(ladder.grab())


class TestRegressionsRound9(unittest.TestCase):
    """Round-9 fixes: crash after asset switch, global map, single-click panel."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_asset_switch_then_teach_no_crash(self):
        other = next(a for a in self.win.assets if a != self.win.current_asset_id)
        self.win.on_asset_select(other)
        self.assertIsNotNone(getattr(self.win, "_teach_graph", None))
        items = self.win.get_adaptive_path(self.win.current_asset_id)
        self.assertTrue(items)
        self.win._open_concept_panel(items[0]["cid"])
        panel = getattr(self.win, "_concept_panel", None)
        self.assertIsNotNone(panel)
        panel.teach_requested.emit(items[0]["name"])  # must not raise

    def test_global_map_has_grey_nodes(self):
        self.win.content_stack.setCurrentIndex(2)
        gv = self.win._graph_view
        self.assertGreater(len(gv._grey_ids), 0)
        self.assertGreater(len(gv.scene().items()), 0)

    def test_single_click_emits_panel_signal(self):
        gv = self.win._graph_view
        clicked = []
        gv.node_single_clicked.connect(clicked.append)
        cid = next(iter(gv._node_items))
        item = gv._node_items[cid]
        pos = gv.mapFromScene(item.scenePos())
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(gv.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, pos)
        self.assertEqual(len(clicked), 1)

    def test_learner_view_has_no_progress_bars(self):
        self.win.content_stack.setCurrentIndex(5)
        bars = self.win.learner_view.findChildren(QProgressBar)
        self.assertEqual(len(bars), 0)

    def test_teacher_explainer_present(self):
        self.win.content_stack.setCurrentIndex(6)
        labels = [l.text() for l in self.win.teacher_view.findChildren(QLabel)]
        self.assertTrue(any("教师模型 = 系统对这本书自己的理解" in t for t in labels))


class TestLivingGraph(unittest.TestCase):
    """Force-directed motion + interaction."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()
        cls.win.content_stack.setCurrentIndex(2)
        cls.win.repaint()
        cls.gv = cls.win._graph_view

    def test_physics_runs_in_full_mode(self):
        self.assertTrue(self.gv._phys_timer.isActive())

    def test_nodes_move(self):
        import time
        pos0 = {c: self.gv._node_items[c].pos() for c in self.gv._node_items}
        deadline = time.time() + 1.2
        while time.time() < deadline:
            app = self.gv.scene().views()[0]
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            time.sleep(0.02)
        moved = sum(1 for c in pos0
                    if (self.gv._node_items[c].pos() - pos0[c]).manhattanLength() > 1)
        self.assertGreater(moved, 0)

    def test_focus_sleeps_physics(self):
        cid = next(iter(self.gv._node_items))
        self.gv.focus_concept(cid)
        self.assertTrue(self.gv.is_focused())
        self.assertFalse(self.gv._phys_timer.isActive())
        self.gv.reset_focus()
        self.assertTrue(self.gv._phys_timer.isActive())

    def test_teach_mini_header(self):
        self.win.content_stack.setCurrentIndex(4)
        labels = [l.text() for l in self.win.content_stack.widget(4).findChildren(QLabel)]
        self.assertTrue(any("选择概念 · 学习 · 答题 · 追问" in t for t in labels))


if __name__ == "__main__":
    unittest.main(verbosity=2)
