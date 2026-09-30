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

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
)

from main import MainWindow
from expert_anything.ui.pyside_graph import KnowledgeGraphView
from expert_anything.ui.widgets import (
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
        # the cognitive map is the home view, so asset switch lands there
        self.assertEqual(self.win.content_stack.currentIndex(), 2)


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

    def test_unanchored_concept_mark(self):
        """Concepts without source locations get a hollow-ring corner mark
        plus a tooltip hint; anchored concepts carry neither."""
        from PySide6.QtWidgets import QGraphicsEllipseItem
        from expert_anything.core.i18n import t as _t

        gv = self.win._graph_view
        asset = self.win.get_asset()
        target = asset.concepts[0]
        target.locations = []  # simulate a template-enriched concept
        gv.set_asset(asset)
        item = gv._node_items.get(target.id)
        self.assertIsNotNone(item)
        self.assertIn(_t("unanchored_tip"), item.toolTip())
        corner_marks = [
            it for it in gv.scene().items()
            if isinstance(it, QGraphicsEllipseItem)
        ]
        self.assertTrue(corner_marks, "no hollow-ring mark rendered")
        target_top_left = item.mapRectToScene(item.boundingRect()).topLeft()
        mark_pos = [
            m.scenePos() for m in corner_marks
            if (m.scenePos() - target_top_left).manhattanLength() < 30
        ]
        self.assertTrue(mark_pos, "mark not placed at the node corner")

        # an anchored concept must NOT carry the tooltip hint
        anchored = next(
            (c for c in asset.concepts if c.locations), None
        )
        if anchored is not None:
            self.assertNotIn(
                _t("unanchored_tip"), gv._node_items[anchored.id].toolTip()
            )

    def test_evidence_margin_marks(self):
        """Lines serving as grounded evidence carry a reverse anchor mark
        (evidence://<cid>) that hops back to the concept when clicked."""
        from PySide6.QtCore import QUrl
        from expert_anything.core.extraction import _stamp_locations

        sv = self.win._source_view_widget
        asset = self.win.get_asset()
        _stamp_locations(asset)  # idempotent on already-stamped assets
        sv.set_asset(asset, self.win.learner or {})
        html = sv.toHtml()
        anchored = [
            c
            for c in asset.concepts
            if any(
                c.location_for_evidence(ev) is not None for ev in c.evidence or []
            )
        ]
        self.assertTrue(anchored, "demo asset has no anchored evidence")
        with_mark = [c for c in anchored if f"evidence://{c.id}" in html]
        self.assertEqual(
            len(with_mark), len(anchored), "missing evidence:// margin mark"
        )

        # clicking the mark emits the concept hop (same signal as name anchors)
        fired = []
        sv.concept_anchor_clicked.connect(lambda cid: fired.append(cid))
        target = anchored[0]
        sv._on_anchor(QUrl(f"evidence://{target.id}"))
        self.assertEqual(fired, [target.id])


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


class TestDueGainTags(unittest.TestCase):
    """The review queue must explain WHY a concept is due (gain-weak /
    gain-stretched scheduling tags), not just THAT it is due."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_gain_weak_tag_shown_on_due_card(self):
        from datetime import datetime, timedelta, timezone
        from expert_anything.core.learner import normalize, record_evaluation

        win = self.win
        asset = win.get_asset()
        state = win.learner
        state["history"] = []
        state["concepts"] = {}
        concept = asset.concepts[0]
        record_evaluation(state, concept.name, asset.asset_id, 0.9, "a", "f")
        record_evaluation(state, concept.name, asset.asset_id, 0.4, "a", "f",
                          meta={"channel": "answer", "review": True})
        now = datetime.now(timezone.utc)
        state["concepts"][normalize(concept.name)]["updated_at"] = (
            now - timedelta(days=1, seconds=10)
        ).isoformat()
        win.learner_view.refresh()
        from PySide6.QtWidgets import QLabel

        texts = [l.text() for l in win.learner_view.findChildren(QLabel)]
        self.assertTrue(
            any("间隔缩短" in t or "shorter interval" in t for t in texts),
            f"gain-weak scheduling tag not found on due card",
        )


class TestReviewIneffectiveAnomaly(unittest.TestCase):
    """Negative review gain must sink a learner_gap anomaly into the
    teacher model — the review loop feeds teaching priority, it does not
    stop at a red label on the learner page (AGENTS.md §2/§6)."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_answer_channel_review_negative_writes_anomaly(self):
        from expert_anything.core.learner import record_evaluation

        win = self.win
        asset = win.get_asset()
        state = win.learner
        state["history"] = []
        state["concepts"] = {}
        concept = asset.concepts[0]
        # first-time learning reached 0.9; a review drops to 0.4
        record_evaluation(state, concept.name, asset.asset_id, 0.9, "a", "f")
        record_evaluation(state, concept.name, asset.asset_id, 0.4, "a", "f",
                          meta={"channel": "answer", "review": True})
        win.teach_view._review_mode = True
        try:
            win.teach_view._check_review_gain_for(concept, asset)
        finally:
            win.teach_view._review_mode = False
        from expert_anything.core.teacher import TeacherModel

        td = win.teacher_models.get(asset.asset_id) or {}
        teacher = TeacherModel.from_dict(td)
        gaps = [a for a in teacher.anomalies
                if a.kind == "learner_gap" and "复习" in a.description]
        self.assertTrue(gaps, "negative review gain must produce a learner_gap anomaly")
        win.teacher_models[asset.asset_id] = {}  # reset for other tests


class TestReviewGainCard(unittest.TestCase):
    """The learner view must surface review consolidation gain (§5 anchor)."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_review_gain_card_renders_with_data(self):
        from expert_anything.core.learner import record_evaluation

        state = self.win.learner
        state["history"] = []
        state["concepts"] = {}
        record_evaluation(state, "两级市场架构", "a", 0.4, "a", "f")
        record_evaluation(state, "两级市场架构", "a", 0.9, "a", "f",
                          meta={"review": True})
        self.win.learner_view.refresh()
        # find the gain label inside the learner view
        from PySide6.QtWidgets import QLabel
        labels = self.win.learner_view.findChildren(QLabel)
        texts = [l.text() for l in labels]
        self.assertTrue(any("复习巩固增益" in t or "Review Consolidation" in t
                            for t in texts))
        self.assertTrue(any("两级市场架构" in t for t in texts))

    def test_review_gain_card_empty_hint(self):
        state = self.win.learner
        state["history"] = []
        state["concepts"] = {}
        self.win.learner_view.refresh()
        from PySide6.QtWidgets import QLabel
        texts = [l.text() for l in self.win.learner_view.findChildren(QLabel)]
        self.assertTrue(any("复习后的得分变化" in t or "Score changes after" in t
                            for t in texts))


class TestReviewSessionVary(unittest.TestCase):
    """Review entries must teach with vary=1 (AGENTS.md §6 间隔效应).

    The review toggle exists but the entry points used to bypass it:
    _on_review_all_request started a topic pack without review=True and
    review-queue cards emitted plain teach_requested. These tests pin the
    wiring, not the UI pixels.
    """

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def _teach_view(self):
        self.win.content_stack.setCurrentWidget(self.win.teach_view)
        return self.win.teach_view

    def test_review_all_pack_sets_review_mode(self):
        tv = self._teach_view()
        tv._review_toggle.setChecked(False)
        self.win._on_review_all_request(["总量控制", "碳排放配额"])
        self.assertTrue(tv._topic_review)
        self.assertTrue(tv._review_mode)
        self.assertTrue(tv._review_toggle.isChecked())

    def test_topic_pack_unchecked_by_default(self):
        tv = self._teach_view()
        tv._review_toggle.setChecked(False)
        self.win._on_topic_teach_request(
            "总量控制", "主题", ["总量控制", "碳排放配额"], 0)
        self.assertFalse(tv._topic_review)

    def test_review_pack_flag_resets_after_queue_end(self):
        tv = self._teach_view()
        self.win._on_review_all_request(["总量控制", "碳排放配额"])
        tv._teach_concept_now = "碳排放配额"  # simulate last lesson shown
        tv._on_topic_next()  # queue exhausted -> reset branch
        self.assertFalse(tv._topic_review)
        self.assertFalse(tv._review_mode)

    def test_review_card_emits_review_signal(self):
        from expert_anything.ui.views.learner_view import LearnerView
        self.assertIn("review_requested", LearnerView.__dict__)

    def test_review_one_flows_to_start_teach(self):
        tv = self._teach_view()
        calls = []
        tv.start_teach_by_name = lambda n, review=False: calls.append((n, review))
        self.win._on_review_one_request("总量控制")
        self.assertEqual(calls, [("总量控制", True)])

    def test_quiz_meta_records_review_flag(self):
        """Quiz launched inside a review lesson records review=True in the
        learning trace; a standalone quick-quiz stays False (no lesson
        context must not inherit a stale flag)."""
        tv = self._teach_view()
        name = "两级市场架构"  # first concept of the demo (current) asset
        # lesson quiz: review semantics present
        tv._teach_concept_now = name
        tv._teach_vary = 1
        tv._on_quiz_requested()
        self.assertTrue(tv._quiz_vary)
        # standalone quick quiz: semantics reset
        tv.start_quick_quiz_by_name(name)
        self.assertFalse(tv._quiz_vary)
        # meta actually lands in the trace
        tv._quiz_vary = True
        learner_state = self.win.learner
        n_before = len(learner_state.get("history", []))
        tv._on_quiz_result(0.8)
        hist = learner_state.get("history", [])
        self.assertEqual(len(hist), n_before + 1)
        self.assertTrue(hist[0]["meta"]["review"])

    def test_answer_meta_records_review_flag(self):
        tv = self._teach_view()
        name = "两级市场架构"
        tv._review_mode = True
        tv._teach_vary = 1
        tv._teach_lesson = {"concept": name, "style": "example"}
        tv._teach_concept_now = name
        learner_state = self.win.learner
        tv._eval_answer_text = "测试作答"
        # call the answer-recording path with a fake graded result
        tv._on_answer_eval_done({"score": 0.9, "feedback": "ok", "judges": 1})
        hist = learner_state.get("history", [])
        self.assertTrue(hist[0]["meta"]["review"])
        self.assertEqual(hist[0]["meta"]["channel"], "answer")


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

    def test_anchor_rate_displayed(self):
        """Teacher view surfaces source-provenance coverage and lists the
        unanchored (template-enriched / unlocatable) concepts."""
        from PySide6.QtWidgets import QLabel
        from expert_anything.core.extraction import _stamp_locations
        from expert_anything.core.i18n import t as _t

        win = load_main_window()
        win.content_stack.setCurrentIndex(6)

        def anchor_labels():
            return [
                l for l in win.teacher_view.findChildren(QLabel)
                if _t("teacher_anchor_rate", pct="", n=0, total=0)[:6] in l.text()
                or "证据锚定率" in l.text() or "Evidence anchored" in l.text()
                or "証拠アンカー率" in l.text()
            ]

        asset = win.get_asset()
        self.assertIsNotNone(asset)
        # demo assets regenerate with verbatim evidence -> fully anchored
        self.assertTrue(
            all(c.locations for c in asset.concepts),
            "demo concepts should be stamped (regen_all guarantees verbatim)",
        )
        rate_labels = anchor_labels()
        self.assertEqual(len(rate_labels), 1)
        self.assertIn("100%", rate_labels[0].text())
        self.assertNotIn("无锚点", rate_labels[0].text())

        # simulate a template-enriched (unanchored) concept
        target = asset.concepts[0]
        target.locations = []
        win.teacher_view.refresh()
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        # deleteLater() posts a DeferredDelete event that plain
        # processEvents() swallows — flush it or the stale label lingers
        # in the object tree and findChildren() counts it twice.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        rate_labels = anchor_labels()
        self.assertEqual(len(rate_labels), 1)
        self.assertNotIn("100%", rate_labels[0].text())
        missing = [
            l for l in win.teacher_view.findChildren(QLabel)
            if target.name in l.text()
        ]
        self.assertTrue(missing, "unanchored concept name not listed")

        # restore for other tests sharing the window/asset
        _stamp_locations(asset)


class TestDirtyPayloads(unittest.TestCase):
    def test_null_payload(self):
        view = TeachResultView(
            {
                "concept": "X",
                "style": "图示",
                "explanation": None,
                "example": None,
                "steps": None,
                "practice": None,
                "evidence": None,
            }
        )
        view.show()
        self.assertIsNotNone(view.grab())

    def test_weird_types(self):
        view = TeachResultView(
            {
                "concept": "X",
                "style": "拆解步骤",
                "explanation": 123,
                "example": ["a", "b"],
                "steps": "s1\ns2",
                "practice": "",
                "evidence": [None, "ok"],
            }
        )
        view.show()
        self.assertIsNotNone(view.grab())

    def test_followup_and_neighbor_api(self):
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.set_neighbors([("依赖", "Y", "c2")])
        view.append_exchange("问？", "答。")
        view.append_evaluation(0.8, "好", "参考", "差距")
        self.assertIsNotNone(view.grab())

    def test_unanchored_warning_rendered(self):
        """The teach result shows the no-anchor caveat when the taught
        concept (resolved through the parent teach view → asset) carries no
        SourceLocation, and stays silent otherwise."""
        from PySide6.QtWidgets import QLabel
        from expert_anything.core.i18n import t as _t

        win = load_main_window()
        asset = win.get_asset()
        # demo assets are fully anchored (regen_all stamps them) — the
        # warning must NOT render for anchored concepts
        anchored = asset.concepts[0]
        self.assertTrue(anchored.locations)

        plain = TeachResultView(
            {"concept": anchored.name, "style": "example", "explanation": "e"},
            parent=win.teach_view,
        )
        plain.show()
        warn_texts = [
            l.text()
            for l in plain.findChildren(QLabel)
            if _t("teach_unanchored_warn") in l.text()
        ]
        self.assertEqual(warn_texts, [])

        # strip anchors -> warning renders
        anchored.locations = []
        warned = TeachResultView(
            {"concept": anchored.name, "style": "example", "explanation": "e"},
            parent=win.teach_view,
        )
        warned.show()
        hits = [
            l.text()
            for l in warned.findChildren(QLabel)
            if _t("teach_unanchored_warn") in l.text()
        ]
        self.assertEqual(len(hits), 1)

        from expert_anything.core.extraction import _stamp_locations

        _stamp_locations(asset)


class TestHarnessSuggestionUI(unittest.TestCase):
    """AutoHarness stuck-loop UI: suggestion card + one-click adopt."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_suggestion_card_renders_and_emits(self):
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        candidate = {
            "name": "evolved-1",
            "tools": ["teach", "scene", "quiz"],
            "policy": {"style": "图示"},
        }
        received = []
        view.harness_adopt_requested.connect(received.append)
        view.append_harness_suggestion("建议", "摘要", candidate)
        self.assertIsNotNone(view.grab())
        # find the adopt button and click it -> signal carries the candidate
        from PySide6.QtWidgets import QPushButton
        from expert_anything.core.i18n import t as _t

        buttons = [
            b for b in view.findChildren(QPushButton) if b.text() == _t("harness_adopt")
        ]
        self.assertEqual(len(buttons), 1)
        buttons[0].click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["name"], "evolved-1")

    def test_stuck_signal_shows_evolution_card(self):
        """Full §12 wiring: stuck signal → evolve_joint → card in the teach
        result view → adopt click → persist + re-teach. The card must appear
        exactly once for the same (concept, reason, candidate) signature."""
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        win._teach_concept_now = concept.name
        # render a lesson result view so the suggestion card has a host and
        # its adopt/transfer signals get wired (as in _display_result)
        win._teach_view._display_result(
            {"concept": concept.name, "style": "例子"}
        )
        view = win._teach_view._teach_view_widget

        fake = {
            "evolved": True,
            "source": "joint",
            "reason": "stuck",
            "focused": {
                "name": concept.name,
                "stuck": True,
                "regression": False,
                "attempts": 3,
                "avg": 0.2,
            },
            "diagnosis": [],
            "candidates": [
                {
                    "name": "evolved-stuck",
                    "mode": "fast",
                    "tools": ["teach", "quiz"],
                    "policy": {"style": "图示"},
                    "loop": {"max_steps": 4},
                    "evaluation": {"metric": "learning_gain", "threshold": 0.6},
                    "meta": {"budget_cost": 50, "sandbox": "local"},
                }
            ],
        }
        with mock.patch.object(main_module._ah, "evolve_joint", return_value=fake):
            win._offer_harness_evolution(concept.name, {"attempts": 3, "avg": 0.2})
            # repeated weak evaluation of the same concept: no duplicate card
            win._offer_harness_evolution(concept.name, {"attempts": 4, "avg": 0.1})

        from PySide6.QtWidgets import QPushButton
        from expert_anything.core.i18n import t as _t

        buttons = [
            b
            for b in view.findChildren(QPushButton)
            if b.text() == _t("harness_adopt")
        ]
        self.assertEqual(len(buttons), 1)  # deduped to a single card
        self.assertIsNotNone(view.grab())

        before = dict(win._harness_specs)
        try:
            with (
                mock.patch.object(main_module._ah, "save_harness_state"),
                mock.patch.object(main_module._ah, "record_harness_evolution"),
                mock.patch.object(main_module.QMessageBox, "information"),
                mock.patch.object(win, "_show_teaching_content") as teach_mock,
            ):
                buttons[0].click()  # adopt → full chain via harness_adopted
            teach_mock.assert_called_once()
            kw = teach_mock.call_args.kwargs
            self.assertEqual(kw.get("style"), "图示")
            self.assertEqual(kw.get("vary"), 1)
            self.assertEqual(
                win._harness_specs.get(asset.asset_id, {}).get("name"),
                "evolved-stuck",
            )
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_offer_shown = set()

    def test_transfer_card_via_stuck(self):
        """Stuck → migration candidate → light-blue card → adopt chain.
        _find_transfer_candidates is mocked: its differential evaluation has
        core-layer tests; here we verify the wiring (card render, session
        dedup, evaluation skip, one-click migrate re-teach)."""
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        others = [aid for aid in win.assets if aid != asset.asset_id]
        if not others:
            self.skipTest("no second asset loaded")
        src_aid = others[0]
        concept = asset.concepts[0]
        win._teach_concept_now = concept.name
        win._teach_view._display_result(
            {"concept": concept.name, "style": "例子"}
        )
        view = win._teach_view._teach_view_widget

        spec = {
            "name": "migr-1",
            "mode": "fast",
            "tools": ["teach", "quiz"],
            "policy": {"style": "图示"},
            "loop": {"max_steps": 4},
            "evaluation": {"metric": "learning_gain", "threshold": 0.6},
            "meta": {"budget_cost": 50, "sandbox": "local"},
        }
        payload = {
            "source_asset_id": src_aid,
            "source_title": "Source Book",
            "spec": spec,
            "evaluation": {"comparison": {"diff": 0.12}, "cost_diff": 4},
            "gain": 0.12,
        }
        before = dict(win._harness_specs)
        try:
            with mock.patch.object(
                win,
                "_find_transfer_candidates",
                return_value=[payload],
            ) as find_mock:
                win._harness_specs[src_aid] = spec
                win._offer_harness_transfer_cards()
                win._offer_harness_transfer_cards()  # dedup: no 2nd card
            self.assertEqual(find_mock.call_count, 1)  # 2nd call skipped eval

            from PySide6.QtWidgets import QPushButton
            from expert_anything.core.i18n import t as _t

            buttons = [
                b
                for b in view.findChildren(QPushButton)
                if b.text() == _t("harness_transfer_adopt")
            ]
            self.assertEqual(len(buttons), 1)
            self.assertIsNotNone(view.grab())

            with (
                mock.patch.object(
                    main_module._ah,
                    "adopt_harness_for_asset",
                    return_value=(True, {}),
                ) as adopt_mock,
                mock.patch.object(main_module.QMessageBox, "information"),
                mock.patch.object(win, "_show_teaching_content") as teach_mock,
            ):
                buttons[0].click()
            adopt_mock.assert_called_once()
            teach_mock.assert_called_once()
            kw = teach_mock.call_args.kwargs
            self.assertEqual(kw.get("style"), "图示")
            self.assertEqual(kw.get("vary"), 1)
            self.assertEqual(
                win._harness_specs.get(asset.asset_id, {}).get("name"), "migr-1"
            )
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._transfer_offer_shown = set()

    def test_evidence_badges_in_lesson(self):
        """演进 #1: lesson evidence entries carry a page/line badge sourced
        from Concept.locations and emit (concept, evidence) on click."""
        from PySide6.QtWidgets import QPushButton
        from expert_anything.core.i18n import t as _t
        from expert_anything.core.extraction import _stamp_locations
        from expert_anything.core.models import SourceLocation

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = next(
            (c for c in asset.concepts if c.evidence), asset.concepts[0]
        )
        if not concept.evidence:
            self.skipTest("no evidence in demo asset")
        # ensure anchors exist (idempotent on already-stamped assets)
        _stamp_locations(asset)

        win._teach_view._display_result(
            {
                "concept": concept.name,
                "explanation": "demo",
                "evidence": list(concept.evidence[:2]),
            }
        )
        view = win._teach_view._teach_view_widget
        badges = [
            b for b in view.findChildren(QPushButton)
            if b.text().startswith(("第", "p.", "line", "ページ"))
        ]
        self.assertTrue(badges, "no location badge rendered")

        # clicking emits the jump signal with the evidence text
        fired = []
        win._teach_view.evidence_jump_requested.connect(
            lambda cid, ev: fired.append((cid, ev))
        )
        badges[0].click()
        self.assertTrue(fired)
        cid, ev = fired[0]
        self.assertEqual(cid, concept.id)
        self.assertTrue(any(ev == e or ev in e for e in concept.evidence))

    def test_graph_card_evidence_badges_and_cross_asset_jump(self):
        """Graph detail card: evidence rows carry location badges emitting
        (concept_id, evidence); a global-scope id with an asset prefix makes
        main resolve the right asset, switch to it and jump without error."""
        from PySide6.QtWidgets import QPushButton
        from expert_anything.core.extraction import _stamp_locations

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = next(
            (c for c in asset.concepts if c.evidence), asset.concepts[0]
        )
        if not concept.evidence:
            self.skipTest("no evidence in demo asset")
        _stamp_locations(asset)

        card = win._map_detail_ref() if hasattr(win, "_map_detail_ref") else None
        if card is None:
            self.skipTest("map detail card not built")
        card.set_concept(asset, concept.id, {"concepts": {}}, None)
        badges = [
            b
            for b in card.findChildren(QPushButton)
            if b.text().startswith(("第", "p.", "line", "ページ"))
        ]
        self.assertTrue(badges, "card rendered no location badge")

        fired = []
        card.evidence_jump_requested.connect(
            lambda cid, ev: fired.append((cid, ev))
        )
        badges[0].click()
        self.assertTrue(fired)
        self.assertEqual(fired[0][0], concept.id)
        self.assertTrue(fired[0][1])

        # cross-asset: forge a global id for the *other* demo asset and let
        # main resolve + switch + jump end-to-end (must not raise).
        others = [aid for aid in win.assets if aid != asset.asset_id]
        if not others:
            self.skipTest("single-asset demo")
        target = asset.concepts[0]
        win._on_teach_evidence_jump(
            f"{others[0]}:{target.id}", target.evidence[0]
        )
        self.assertEqual(win.current_asset_id, others[0])

    def test_quick_quiz_by_name_builds_view(self):
        """Regression: quick-quiz from the concept card used to construct
        TeachResultView with removed kwargs (TypeError on first click)."""
        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        # force the is-None branch that used to blow up
        old = win._teach_view._teach_view_widget
        win._teach_view._teach_view_widget = None
        try:
            win._teach_view.start_quick_quiz_by_name(concept.name)
            self.assertIsNotNone(win._teach_view._teach_view_widget)
        finally:
            if win._teach_view._teach_view_widget is not None:
                win._teach_view._teach_view_widget.deleteLater()
            win._teach_view._teach_view_widget = old

    def test_location_for_evidence_matching(self):
        """Concept.location_for_evidence: prefix match on snippet, longest
        char_start wins on duplicates, None when unmatched."""
        from expert_anything.core.models import Concept, SourceLocation

        c = Concept(id="c1", name="节点电价", evidence=["ev-one text", "ev-two text"])
        c.locations = [
            SourceLocation(
                char_start=10, char_end=21, snippet="ev-one text",
                line=2, page=1,
            ),
            SourceLocation(
                char_start=400, char_end=411, snippet="ev-two text",
                line=30, page=5,
            ),
        ]
        loc = c.location_for_evidence("ev-two text")
        self.assertIsNotNone(loc)
        self.assertEqual((loc.page, loc.line), (5, 30))
        # truncated caller-side rendering still matches
        loc2 = c.location_for_evidence("ev-one tex" + "…")
        self.assertIsNotNone(loc2)
        self.assertEqual(loc2.snippet, "ev-one text")
        self.assertIsNone(c.location_for_evidence("nowhere"))
        self.assertIsNone(c.location_for_evidence(""))

    def test_doubt_strip_in_lesson(self):
        """§2 walk-ahead: the teach result view shows this concept's doubts,
        or the asset-wide open count when the concept is clean; nothing at
        all when the whole asset is resolved."""
        from expert_anything.core.teacher import Anomaly, TeacherModel
        from expert_anything.core.i18n import t as _t
        from PySide6.QtWidgets import QLabel

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        name = concept.name
        tm = TeacherModel(asset_id=asset.asset_id)
        tm.anomalies.append(Anomaly(
            id="d1", kind="contradiction",
            description=f"{name} 的定义前后矛盾", severity="high"))
        before = dict(win.teacher_models)
        try:
            win.teacher_models[asset.asset_id] = tm.to_dict()
            win._teach_view._display_result(
                {"concept": name, "style": "例子"}
            )
            view = win._teach_view._teach_view_widget
            texts = [l.text() for l in view.findChildren(QLabel)]
            self.assertIn(_t("doubt_section"), texts)
            matched = [x for x in texts if "矛盾" in x and name in x]
            self.assertTrue(matched, texts)

            # clean concept + open anomalies elsewhere → doubt_none line
            tm2 = TeacherModel(asset_id=asset.asset_id)
            tm2.anomalies.append(Anomaly(
                id="d2", kind="undefined_term",
                description="别的概念术语未定义"))
            win.teacher_models[asset.asset_id] = tm2.to_dict()
            win._teach_view._display_result(
                {"concept": name, "style": "例子"}
            )
            texts = [l.text() for l in
                     win._teach_view._teach_view_widget.findChildren(QLabel)]
            self.assertIn(
                _t("doubt_none", n=1), texts
            )

            # fully resolved asset → no strip at all
            win.teacher_models.pop(asset.asset_id, None)
            win._teach_view._display_result(
                {"concept": name, "style": "例子"}
            )
            texts = [l.text() for l in
                     win._teach_view._teach_view_widget.findChildren(QLabel)]
            self.assertNotIn(_t("doubt_section"), texts)
        finally:
            win.teacher_models.clear()
            win.teacher_models.update(before)

    def test_adopt_persists_and_retaches(self):
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        win._teach_concept_now = concept.name
        candidate = {
            "name": "evolved-x",
            "mode": "fast",
            "tools": ["teach", "quiz"],
            "policy": {"style": "图示", "guard_ids": ["budget_ok"]},
            "loop": {"max_steps": 4},
            "evaluation": {"metric": "learning_gain", "threshold": 0.6},
            "meta": {"budget_cost": 50, "sandbox": "local"},
        }
        before = dict(win._harness_specs)
        hist_before = getattr(win, "_harness_history", [])
        try:
            with (
                mock.patch.object(main_module._ah, "save_harness_state") as save_mock,
                mock.patch.object(
                    main_module._ah, "record_harness_evolution"
                ) as rec_mock,
                mock.patch.object(main_module.QMessageBox, "information") as info_mock,
                mock.patch.object(win, "_show_teaching_content") as teach_mock,
            ):
                win._on_adopt_harness(candidate)
            save_mock.assert_called_once()
            rec_mock.assert_called_once()  # 审计链：采纳必须落一条演化事件
            info_mock.assert_called_once()
            teach_mock.assert_called_once()
            kw = teach_mock.call_args.kwargs
            self.assertEqual(kw.get("vary"), 1)  # fresh-angle re-teach
            self.assertEqual(kw.get("style"), "图示")  # candidate style applied
            self.assertEqual(
                win._harness_specs.get(asset.asset_id, {}).get("name"), "evolved-x"
            )
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_history = hist_before

    def test_history_block_renders_and_dedups(self):
        # 演化历史块：渲染 reason 本地化 + old -> new；同视图重复调用去重
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        events = [
            {
                "ts": "2026-08-18T13:55:00",
                "reason": "stuck",
                "old": "o1",
                "new": "n1",
                "spec_name": "h1",
            },
            {
                "ts": "2026-08-18T14:00:00",
                "reason": "manual",
                "old": "n1",
                "new": "n2",
                "spec_name": "h2",
            },
        ]
        view.append_harness_history(events[:1])
        view.append_harness_history(events)  # 第二次只渲染新增事件
        view.append_harness_history(events)  # 第三次无新增 → 不渲染
        self.assertEqual(view._harness_shown_count, 2)  # 去重计数正确
        self.assertIsNotNone(view.grab())
        from PySide6.QtWidgets import QLabel
        from expert_anything.core.i18n import t as _t

        texts = " ".join(l.text() for l in view.findChildren(QLabel))
        self.assertIn(_t("harness_history"), texts)
        self.assertIn(_t("harness_reason_stuck"), texts)
        self.assertIn(_t("harness_reason_manual"), texts)
        self.assertIn("o1", texts)
        self.assertIn("→", texts)

    def test_history_empty_is_noop(self):
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        view.append_harness_history([])
        self.assertEqual(getattr(view, "_harness_shown_count", 0), 0)
        self.assertIsNotNone(view.grab())

    def test_regression_card_renders_and_emits_source(self):
        # 回归演化卡：独立按钮文案 + emit 时携带 _source="regression"
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        candidate = {
            "name": "trim-guard",
            "tools": ["teach", "quiz"],
            "policy": {"style": "图示"},
        }
        received = []
        view.harness_adopt_requested.connect(received.append)
        view.append_harness_suggestion(
            "回归建议", "回归正文", candidate, source="regression"
        )
        self.assertIsNotNone(view.grab())
        from PySide6.QtWidgets import QPushButton
        from expert_anything.core.i18n import t as _t

        buttons = [
            b
            for b in view.findChildren(QPushButton)
            if b.text() == _t("harness_adopt_regress")
        ]
        self.assertEqual(len(buttons), 1)  # 回归卡用专属按钮文案
        amber = [
            b for b in view.findChildren(QPushButton) if b.text() == _t("harness_adopt")
        ]
        self.assertEqual(len(amber), 0)
        buttons[0].click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["_source"], "regression")
        self.assertEqual(received[0]["name"], "trim-guard")

    def test_adopt_regression_persists_clean_and_logs_reason(self):
        # 回归卡采纳：_source 剥离后持久化（不污染 HarnessSpec），
        # 审计链 reason="regression"（区别于 stuck 卡的 manual）
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        win._teach_concept_now = concept.name
        candidate = {
            "_source": "regression",
            "name": "trim-guard",
            "mode": "fast",
            "tools": ["teach", "quiz"],
            "policy": {"style": "图示", "guard_ids": ["no_definition_copy"]},
            "loop": {"max_steps": 4},
            "evaluation": {"metric": "learning_gain", "threshold": 0.6},
            "meta": {"budget_cost": 50, "sandbox": "local"},
        }
        before = dict(win._harness_specs)
        hist_before = getattr(win, "_harness_history", [])
        try:
            with (
                mock.patch.object(main_module._ah, "save_harness_state") as save_mock,
                mock.patch.object(
                    main_module._ah, "record_harness_evolution"
                ) as rec_mock,
                mock.patch.object(main_module.QMessageBox, "information") as info_mock,
                mock.patch.object(win, "_show_teaching_content") as teach_mock,
            ):
                win._on_adopt_harness(candidate)
            rec_mock.assert_called_once()
            ev = rec_mock.call_args.args[1]
            self.assertEqual(ev["reason"], "regression")  # 审计链标注回归来源
            # 持久化 spec 不含 _source 内部标记
            saved = save_mock.call_args.args[1][asset.asset_id]
            self.assertNotIn("_source", saved)
            self.assertEqual(saved["name"], "trim-guard")
            teach_mock.assert_called_once()
            kw = teach_mock.call_args.kwargs
            self.assertEqual(kw.get("vary"), 1)
            self.assertEqual(kw.get("style"), "图示")
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_history = hist_before

    def test_joint_card_renders_and_emits(self):
        # 联合演化卡（青色）：专属按钮文案 + emit 携带 _source="joint" 与
        # _joint_reason 触发家族串（供审计链记录，不污染 HarnessSpec）
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        candidate = {
            "name": "joint-plan",
            "tools": ["teach", "quiz"],
            "policy": {"style": "图示"},
        }
        received = []
        view.harness_adopt_requested.connect(received.append)
        view.append_harness_suggestion(
            "联合建议",
            "联合正文",
            candidate,
            source="joint",
            extra={"_joint_reason": "stuck+regression"},
        )
        self.assertIsNotNone(view.grab())
        from PySide6.QtWidgets import QPushButton
        from expert_anything.core.i18n import t as _t

        buttons = [
            b
            for b in view.findChildren(QPushButton)
            if b.text() == _t("harness_adopt_joint")
        ]
        self.assertEqual(len(buttons), 1)  # 联合卡用专属按钮文案
        amber = [
            b for b in view.findChildren(QPushButton) if b.text() == _t("harness_adopt")
        ]
        self.assertEqual(len(amber), 0)
        buttons[0].click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["_source"], "joint")
        self.assertEqual(received[0]["_joint_reason"], "stuck+regression")
        self.assertEqual(received[0]["name"], "joint-plan")

    def test_adopt_joint_persists_clean_and_logs_reason(self):
        # 联合卡采纳：_source/_joint_reason 剥离后持久化，审计链记录
        # 触发家族串（stuck+regression+sessions），历史块可拆分本地化
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        win._teach_concept_now = concept.name
        candidate = {
            "_source": "joint",
            "_joint_reason": "stuck+regression+sessions",
            "name": "joint-plan",
            "mode": "fast",
            "tools": ["teach", "quiz"],
            "policy": {"style": "图示", "guard_ids": ["no_definition_copy"]},
            "loop": {"max_steps": 4},
            "evaluation": {"metric": "learning_gain", "threshold": 0.6},
            "meta": {"budget_cost": 50, "sandbox": "local"},
        }
        before = dict(win._harness_specs)
        hist_before = getattr(win, "_harness_history", [])
        try:
            with (
                mock.patch.object(main_module._ah, "save_harness_state") as save_mock,
                mock.patch.object(
                    main_module._ah, "record_harness_evolution"
                ) as rec_mock,
                mock.patch.object(main_module.QMessageBox, "information") as info_mock,
                mock.patch.object(win, "_show_teaching_content") as teach_mock,
            ):
                win._on_adopt_harness(candidate)
            rec_mock.assert_called_once()
            ev = rec_mock.call_args.args[1]
            self.assertEqual(ev["reason"], "stuck+regression+sessions")
            saved = save_mock.call_args.args[1][asset.asset_id]
            self.assertNotIn("_source", saved)
            self.assertNotIn("_joint_reason", saved)
            self.assertEqual(saved["name"], "joint-plan")
            teach_mock.assert_called_once()
            kw = teach_mock.call_args.kwargs
            self.assertEqual(kw.get("vary"), 1)
            self.assertEqual(kw.get("style"), "图示")
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_history = hist_before

    def test_history_compound_reason_localized(self):
        # 联合演化的 reason 是触发家族串：历史块按 "+" 拆分后逐个本地化，
        # 保证审计链可读（stuck+regression+sessions → 三语标签拼接）
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        events = [
            {
                "ts": "2026-08-18T14:05:00",
                "reason": "stuck+regression+sessions",
                "old": "o1",
                "new": "n1",
                "spec_name": "h1",
            }
        ]
        view.append_harness_history(events)
        self.assertEqual(view._harness_shown_count, 1)
        self.assertIsNotNone(view.grab())
        from PySide6.QtWidgets import QLabel
        from expert_anything.core.i18n import t as _t

        texts = " ".join(l.text() for l in view.findChildren(QLabel))
        expect = "+".join(
            [
                _t("harness_reason_stuck"),
                _t("harness_reason_regression"),
                _t("harness_reason_sessions"),
            ]
        )
        self.assertIn(expect, texts)
        self.assertIn("o1", texts)


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

    def test_single_click_defers_scene_rebuild_and_emits_once(self):
        gv = self.win._graph_view
        from PySide6.QtWidgets import QApplication

        QApplication.instance().processEvents()
        clicked = []
        gv.node_single_clicked.connect(clicked.append)
        cid = next(iter(gv._node_items))
        item = gv._node_items[cid]
        # Simulate the state established by mousePressEvent, then invoke the
        # real release handler.  This isolates the regression from headless
        # viewport transforms while still proving release-time deferral.
        gv._drag_cid = cid
        gv._dragged = False
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        pos = gv.viewport().rect().center()
        QTest.mouseRelease(
            gv.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            pos,
        )
        # Scene-changing click work must not run inside mouseReleaseEvent.
        self.assertEqual(clicked, [])
        QTest.qWait(20)
        self.assertEqual(clicked, [cid])

    def test_learner_view_has_no_progress_bars(self):
        self.win.content_stack.setCurrentIndex(5)
        bars = self.win.learner_view.findChildren(QProgressBar)
        self.assertEqual(len(bars), 0)

    def test_teacher_explainer_present(self):
        self.win.content_stack.setCurrentIndex(6)
        labels = [l.text() for l in self.win.teacher_view.findChildren(QLabel)]
        self.assertTrue(any("教师模型 = 系统对这本书自己的理解" in t for t in labels))

    def test_click_node_after_fresh_set_asset_survives_lifecycle(self):
        """Import new asset → _node_items rebuilt → click node → signal fires, no crash."""
        import time
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from expert_anything.core.models import (
            Chapter,
            Concept,
            KnowledgeAsset,
            Relation,
            SourceLocation,
        )

        c_root = Concept(
            id="root",
            name="根",
            evidence=[{"text": "root evidence", "page": 1}],
            locations=[SourceLocation(chapter="ch1", snippet="root text")],
        )
        c_mid = Concept(
            id="mid",
            name="中",
            evidence=[{"text": "mid evidence", "page": 1}],
            locations=[SourceLocation(chapter="ch1", snippet="mid text")],
        )
        c_leaf = Concept(
            id="leaf",
            name="叶",
            evidence=[{"text": "leaf evidence", "page": 1}],
            locations=[SourceLocation(chapter="ch1", snippet="leaf text")],
        )
        chapter = Chapter(id="ch1", title="第一章")
        asset = KnowledgeAsset(
            asset_id="test-lifecycle",
            type="book",
            title="生命周期回归",
            source_name="test",
            created_at=time.time(),
            chapters=[chapter],
            concepts=[c_root, c_mid, c_leaf],
            relations=[
                Relation(id="r1", source="root", target="mid"),
                Relation(id="r2", source="mid", target="leaf"),
            ],
            learning_path=[],
        )

        gv = KnowledgeGraphView()
        gv.show()
        QApplication.instance().processEvents()
        gv.set_asset(asset)
        QApplication.instance().processEvents()

        self.assertGreater(
            len(gv._node_items),
            0,
            "_node_items should be rebuilt after set_asset",
        )

        cid = next(iter(gv._node_items))
        clicked: list = []
        gv.node_single_clicked.connect(clicked.append)

        gv._drag_cid = cid
        gv._dragged = False
        pos = gv.viewport().rect().center()
        QTest.mouseRelease(
            gv.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            pos,
        )
        self.assertEqual(clicked, [])
        QTest.qWait(20)
        self.assertEqual(clicked, [cid])


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
        moved = sum(
            1
            for c in pos0
            if (self.gv._node_items[c].pos() - pos0[c]).manhattanLength() > 1
        )
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
        labels = [
            l.text() for l in self.win.content_stack.widget(4).findChildren(QLabel)
        ]
        self.assertTrue(any("选择概念 · 学习 · 答题 · 追问" in t for t in labels))


class TestI18n(unittest.TestCase):
    """Language switching rebuilds the UI and translates texts."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def _nav_texts(self):
        from PySide6.QtWidgets import QPushButton

        return [b.text() for b in self.win._sidebar.findChildren(QPushButton)]

    def test_default_chinese(self):
        self.assertTrue(any("教学会话" in t for t in self._nav_texts()))

    def test_switch_to_english(self):
        from expert_anything.core import i18n

        self.win._lang_combo.setCurrentIndex(self.win._lang_combo.findData("en"))
        texts = self._nav_texts()
        self.assertTrue(any("Tutor" in t for t in texts))
        self.assertIn("Mastered", self.win._topbar_progress.text())
        # restore (re-fetch: the combo is rebuilt on every switch)
        self.win._lang_combo.setCurrentIndex(self.win._lang_combo.findData("zh-CN"))

    def test_switch_to_japanese(self):
        from expert_anything.core import i18n

        self.win._lang_combo.setCurrentIndex(self.win._lang_combo.findData("ja"))
        texts = self._nav_texts()
        self.assertTrue(any("学習セッション" in t for t in texts))
        # restore
        self.win._lang_combo.setCurrentIndex(self.win._lang_combo.findData("zh-CN"))


class TestLearningFeatures(unittest.TestCase):
    """Quiz, practice and topic-cluster UI features."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_topic_cards_in_knowledge_view(self):
        from PySide6.QtWidgets import QPushButton

        self.win.content_stack.setCurrentIndex(1)
        btns = [
            b.text() for b in self.win.content_stack.widget(1).findChildren(QPushButton)
        ]
        self.assertTrue(any("学习主题" in t or "Learn topic" in t for t in btns))

    def test_start_topic_opens_teach(self):
        from expert_anything.core.learner import topic_clusters

        asset = self.win.get_asset()
        clusters = topic_clusters(asset)
        big = [c for c in clusters if c["size"] >= 2]
        self.assertTrue(big)
        self.win._start_topic(big[0]["id"])
        self.assertEqual(self.win.content_stack.currentIndex(), 4)

    def test_quiz_card_and_recording(self):
        from expert_anything.core.tutor import Tutor

        asset = self.win.get_asset()
        tutor = Tutor(asset, llm=None)
        # deterministic path: quiz generation requires LLM -> skip generation,
        # but scoring logic and UI card must work
        quiz = {
            "type": "true_false",
            "question": "1+1=2?",
            "correct": True,
            "explanation": "arithmetic",
        }
        self.win._teach_concept_now = asset.concepts[0].name
        self.win.on_nav_click("teach")
        self.win._display_teach_result(
            {
                "concept": asset.concepts[0].name,
                "style": "例子",
                "explanation": "x",
                "example": "",
                "steps": [],
                "practice": "",
                "evidence": [],
            }
        )
        tv = self.win._teach_view
        tv.show_quiz(quiz)
        before = len(self.win.learner.get("history", []))
        tv.quiz_result.emit(1.0)
        self.assertEqual(len(self.win.learner.get("history", [])), before + 1)

    def test_practice_card_renders(self):
        task = {"task": "证明 1+1=2", "hint": "用皮亚诺公理", "reference": ["定义后继"]}
        self.win.on_nav_click("teach")
        self.win._display_teach_result(
            {
                "concept": "x",
                "style": "例子",
                "explanation": "x",
                "example": "",
                "steps": [],
                "practice": "",
                "evidence": [],
            }
        )
        tv = self.win._teach_view
        tv.show_practice(task)
        tv.show_practice_result({"score": 0.8, "feedback": "好", "reference": "要点"})
        self.assertIsNotNone(tv.grab())


class TestTransferSuggestionUI(unittest.TestCase):
    """Cross-asset harness migration UI: suggestion card + one-click adopt."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_transfer_card_renders_and_emits(self):
        view = TeachResultView({"concept": "X", "style": "例子"})
        view.show()
        payload = {
            "source_asset_id": "src",
            "source_title": "源书",
            "spec": {
                "name": "migrated-1",
                "tools": ["teach", "quiz"],
                "policy": {"style": "图示"},
            },
            "evaluation": {
                "spec_name": "migrated-1",
                "cost_diff": 6,
                "comparison": {"diff": 0.46},
            },
            "gain": 0.46,
        }
        received = []
        view.harness_transfer_requested.connect(received.append)
        view.append_transfer_suggestion("迁移建议", "正文", payload)
        self.assertIsNotNone(view.grab())
        from expert_anything.core.i18n import t as _t

        buttons = [
            b
            for b in view.findChildren(QPushButton)
            if b.text() == _t("harness_transfer_adopt")
        ]
        self.assertEqual(len(buttons), 1)
        buttons[0].click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["source_asset_id"], "src")
        self.assertEqual(received[0]["spec"]["name"], "migrated-1")
        self.assertEqual(received[0]["gain"], 0.46)

    def test_transfer_adopt_persists_and_retaches(self):
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        win._teach_concept_now = concept.name
        payload = {
            "source_asset_id": "src-a",
            "source_title": "源书",
            "spec": {
                "name": "migrated-x",
                "mode": "fast",
                "tools": ["teach", "quiz"],
                "policy": {"style": "图示", "guard_ids": ["budget_ok"]},
                "loop": {"max_steps": 4},
                "evaluation": {"metric": "learning_gain", "threshold": 0.6},
                "meta": {"budget_cost": 50, "sandbox": "local"},
            },
            "evaluation": {"spec_name": "migrated-x"},
            "gain": 0.4,
        }
        before = dict(win._harness_specs)
        hist_before = getattr(win, "_harness_history", [])
        fake_event = {
            "reason": "transfer",
            "ts": "2026-08-18T14:00:00",
            "old": "o",
            "new": "n",
            "spec_name": "migrated-x",
        }
        try:
            with (
                mock.patch.object(
                    main_module._ah,
                    "adopt_harness_for_asset",
                    return_value=(True, fake_event),
                ) as adopt_mock,
                mock.patch.object(
                    main_module._ah,
                    "load_harness_history",
                    return_value=hist_before + [fake_event],
                ) as load_mock,
                mock.patch.object(main_module.QMessageBox, "information") as info_mock,
                mock.patch.object(win, "_show_teaching_content") as teach_mock,
            ):
                win._on_transfer_harness(payload)
            adopt_mock.assert_called_once()
            args, kw = adopt_mock.call_args
            self.assertEqual(
                str(args[0]), str(main_module.config.DATA_DIR / "harness_state.json")
            )
            self.assertEqual(args[1], asset.asset_id)  # target = current asset
            self.assertEqual(kw.get("source_asset_id"), "src-a")
            self.assertEqual(kw.get("concept"), concept.name)
            load_mock.assert_called_once()
            info_mock.assert_called_once()
            teach_mock.assert_called_once()
            kw2 = teach_mock.call_args.kwargs
            self.assertEqual(kw2.get("vary"), 1)  # fresh-angle re-teach
            self.assertEqual(kw2.get("style"), "图示")  # migrated style applied
            self.assertEqual(
                win._harness_specs.get(asset.asset_id, {}).get("name"), "migrated-x"
            )
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_history = hist_before

    def test_find_transfer_candidates_filters_and_sorts(self):
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None:
            self.skipTest("no asset loaded")
        specs = {"mig1": {"name": "h1"}, "mig2": {"name": "h2"}, "keep": {"name": "h3"}}
        for aid in specs:
            if aid not in win.assets:
                win.assets[aid] = dict(win.assets[asset.asset_id])

        def fake_eval(spec, src_asset, target_asset, **kw):
            ev = {
                "comparison": {"diff": 0.3},
                "spec_name": spec["name"],
                "cost_diff": 2,
                "recommendation": "migrate",
            }
            if src_asset.asset_id == "keep":
                ev.update(
                    {"recommendation": "keep_local", "comparison": {"diff": -0.2}}
                )
            if src_asset.asset_id == "mig2":
                ev["comparison"] = {"diff": 0.6}
            return ev

        specs_before = dict(win._harness_specs)
        try:
            for aid, spec in specs.items():
                win._harness_specs[aid] = spec
            with mock.patch.object(
                main_module._ah, "evaluate_transfer", side_effect=fake_eval
            ):
                out = win._find_transfer_candidates(asset)
            # 只保留 migrate，按差分收益降序；keep_local/无 harness 被过滤
            self.assertEqual([c["source_asset_id"] for c in out], ["mig2", "mig1"])
            self.assertEqual(
                [c["evaluation"]["recommendation"] for c in out], ["migrate", "migrate"]
            )
            self.assertEqual(out[0]["gain"], 0.6)
            self.assertEqual(out[1]["gain"], 0.3)
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(specs_before)
            for aid in specs:
                win.assets.pop(aid, None)

    def test_find_transfer_candidates_real_differential(self):
        """Real evaluate_transfer (no mock): a harness with an extra practice
        slot (adopted on the source asset) raises the scoring coverage on the
        target asset within budget, so it surfaces as a migrate candidate."""
        win = self.win
        asset = win.get_asset()
        if asset is None or len(win.assets) < 2:
            self.skipTest("need >=2 assets")
        src_aid = next(a for a in win.assets if a != asset.asset_id)
        # 源 harness：多一个计分槽位 practice（覆盖度 2 vs 本地 fallback 的 1），
        # 预算充足 → 覆盖度差分 +1 且成本可接受 → migrate
        fast = {
            "name": "fast-transfer",
            "mode": "fast",
            "tools": ["teach", "scene", "quiz", "practice"],
            "policy": {
                "teach_styles": ["图示"],
                "guard_ids": ["no_definition_copy", "budget_ok"],
                "retry": 1,
                "fallback": "deterministic",
            },
            "loop": {"max_steps": 4},
            "evaluation": {"metric": "learning_gain", "threshold": 0.6},
            "meta": {
                "budget_cost": 200,
                "sandbox": "local",
                "lang": "zh-CN",
                "note": "x",
            },
        }
        specs_before = dict(win._harness_specs)
        try:
            win._harness_specs[src_aid] = fast
            out = win._find_transfer_candidates(asset)
            self.assertTrue(out, "coverage gain should justify migration")
            self.assertEqual(out[0]["source_asset_id"], src_aid)
            self.assertEqual(out[0]["evaluation"]["recommendation"], "migrate")
            self.assertGreater(out[0]["evaluation"]["coverage_diff"], 0)
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(specs_before)


class TestMapContextUI(unittest.TestCase):
    """Cognitive-map information gain: peers / next level on the detail card,
    and the two-concept comparison dialog (no dead-end clicks)."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def _asset_and_concept(self):
        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        cid = asset.learning_path[0] if asset.learning_path else asset.concepts[0].id
        return asset, cid

    def test_card_renders_peers_and_next(self):
        from expert_anything.ui.widgets import NodeDetailCard
        from expert_anything.core.map_context import siblings, next_level

        asset, cid = self._asset_and_concept()
        card = NodeDetailCard()
        card.set_concept(asset, cid, self.win.learner)
        texts = [b.text() for b in card.findChildren(QPushButton)]
        peers = siblings(asset, cid, max_n=5)
        nxt = next_level(asset, cid, max_n=6)
        for p in peers[:3]:
            self.assertTrue(
                any(p["name"] in t for t in texts),
                f"peer {p['name']} missing from card",
            )
        for n in nxt[:3]:
            self.assertTrue(
                any(n["name"] in t for t in texts),
                f"next-level {n['name']} missing from card",
            )
        card.close()

    def test_card_action_path_variants(self):
        """action_path*: weak successors → focus variant (⚠ + mastery %),
        all-mastered → plain numbered run, path-end concept → no section."""
        from expert_anything.ui.widgets import NodeDetailCard
        from expert_anything.core.i18n import t as _t
        from expert_anything.core.learner import normalize as _norm

        asset, cid = self._asset_and_concept()
        path = asset.learning_path or [c.id for c in asset.concepts]
        if len(path) < 2 or cid not in path:
            self.skipTest("no successor in demo path")
        succ = asset.concept_by_id(path[path.index(cid) + 1])

        def _section_titles(card):
            return [l.text() for l in card.findChildren(QLabel)]

        # weak successor (no learner record → mastery 0) → focus variant
        empty_state = {"concepts": {}}
        card = NodeDetailCard()
        card.set_concept(asset, cid, empty_state)
        self.assertIn(_t("action_path_focus"), _section_titles(card))
        btns = [b.text() for b in card.findChildren(QPushButton)]
        self.assertTrue(
            any(succ.name in t and "⚠" in t for t in btns), btns
        )
        card.close()

        # all successors mastered → plain numbered run
        strong_state = {
            "concepts": {
                _norm(c.name): {"name": c.name, "mastery": 0.9}
                for c in asset.concepts
            }
        }
        card = NodeDetailCard()
        card.set_concept(asset, cid, strong_state)
        titles = _section_titles(card)
        self.assertIn(_t("action_path"), titles)
        self.assertNotIn(_t("action_path_focus"), titles)
        btns = [b.text() for b in card.findChildren(QPushButton)]
        self.assertTrue(any(t.startswith("1. ") for t in btns), btns)
        card.close()

        # path-end concept → no action path section at all
        last = asset.concept_by_id(path[-1])
        card = NodeDetailCard()
        card.set_concept(asset, path[-1], empty_state)
        titles = _section_titles(card)
        self.assertNotIn(_t("action_path"), titles)
        self.assertNotIn(_t("action_path_focus"), titles)
        card.close()

    def test_card_compare_emits(self):
        from expert_anything.ui.widgets import NodeDetailCard
        from expert_anything.core.i18n import t as _t

        asset, cid = self._asset_and_concept()
        card = NodeDetailCard()
        card.set_concept(asset, cid, self.win.learner)
        emitted = []
        card.compare_requested.connect(lambda a, b: emitted.append((a, b)))
        btn = next(
            (
                b
                for b in card.findChildren(QPushButton)
                if b.text() == _t("detail_compare")
            ),
            None,
        )
        if btn is None:
            card.close()
            self.skipTest("no compare target for this concept")
        btn.click()
        self.assertEqual(len(emitted), 1)
        a, b = emitted[0]
        self.assertEqual(a, cid)
        self.assertNotEqual(a, b)
        card.close()

    def test_compare_dialog_builds_and_switches(self):
        from expert_anything.ui.widgets import ConceptCompareDialog

        asset, cid = self._asset_and_concept()
        other = next((c.id for c in asset.concepts if c.id != cid), None)
        if other is None:
            self.skipTest("need >=2 concepts")
        dlg = ConceptCompareDialog(asset, cid, other, self.win.learner, None)
        dlg.show()
        self.assertGreaterEqual(len(dlg._cand_ids), 1)
        self.assertTrue(
            any(
                l.text().startswith("•") or "相似度" in l.text()
                for l in dlg.findChildren(QLabel)
            )
        )
        # switch the comparison target -> body rebuilds, id_b changes
        if len(dlg._cand_ids) > 1:
            idx = 1 if dlg._b_combo.currentIndex() == 0 else 0
            dlg._b_combo.setCurrentIndex(idx)
            dlg._on_switch()
            self.assertEqual(dlg._id_b, dlg._cand_ids[idx])
        dlg.close()

    def test_panel_has_compare_button(self):
        asset, cid = self._asset_and_concept()
        panel = ConceptDetailPanel(asset, cid, self.win.learner, None)
        panel.show()
        from expert_anything.core.i18n import t as _t

        btns = [b.text() for b in panel.findChildren(QPushButton)]
        self.assertTrue(any(_t("detail_compare_with") in b for b in btns))
        panel.close()

    def test_card_pill_teach_emits(self):
        """A peer/next-level pill carries a one-click teach button."""
        from expert_anything.ui.widgets import NodeDetailCard
        from expert_anything.core.map_context import siblings, next_level

        asset, cid = self._asset_and_concept()
        card = NodeDetailCard()
        card.set_concept(asset, cid, self.win.learner)
        emitted = []
        card.teach_requested.connect(lambda n: emitted.append(n))
        teach_btns = [
            b
            for b in card.findChildren(QPushButton)
            if b.objectName() == "pill_teach_btn"
        ]
        cands = siblings(asset, cid, max_n=5) + next_level(asset, cid, max_n=6)
        card.close()
        if not teach_btns or not cands:
            self.skipTest("no peer/next-level pill for this concept")
        teach_btns[0].click()
        self.assertEqual(len(emitted), 1)
        self.assertIn(emitted[0], {c["name"] for c in cands})

    def test_panel_double_click_teaches(self):
        """Double-clicking a peer/next-level row starts a lesson on it."""
        from expert_anything.core.map_context import siblings, next_level
        from PySide6.QtWidgets import QListWidget
        from PySide6.QtCore import Qt

        asset, cid = self._asset_and_concept()
        panel = ConceptDetailPanel(asset, cid, self.win.learner, None)
        panel.show()
        emitted = []
        panel.teach_requested.connect(lambda n: emitted.append(n))
        cands = siblings(asset, cid, max_n=6) + next_level(asset, cid, max_n=8)
        if not cands:
            panel.close()
            self.skipTest("no candidates")
        target = None
        item = None
        for w in panel.findChildren(QListWidget):
            for i in range(w.count()):
                it = w.item(i)
                if it and (it.data(Qt.ItemDataRole.UserRole) or "") == cands[0]["id"]:
                    target, item = w, it
                    break
            if target:
                break
        if target is None:
            panel.close()
            self.skipTest("candidate not rendered as a list row")
        # NOTE: emitting itemDoubleClicked after accept() is unreliable (the
        # dialog starts closing), so exercise the handler directly — it is the
        # exact code path a double-click runs.
        panel._on_neighbor_activated(item)
        panel.close()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0], cands[0]["name"])

    def test_compare_dialog_incorporate_button(self):
        """Sinking a comparison emits (a, b) and confirms on the button."""
        from expert_anything.ui.widgets import ConceptCompareDialog
        from expert_anything.core.i18n import t as _t

        asset, cid = self._asset_and_concept()
        other = next((c.id for c in asset.concepts if c.id != cid), None)
        if other is None:
            self.skipTest("need >=2 concepts")
        dlg = ConceptCompareDialog(asset, cid, other, self.win.learner, None)
        dlg.show()
        emitted = []
        dlg.incorporate_requested.connect(lambda a, b: emitted.append((a, b)))
        btn = next(
            (
                b
                for b in dlg.findChildren(QPushButton)
                if b.text() == _t("compare_incorporate")
            ),
            None,
        )
        self.assertIsNotNone(btn, "incorporate button missing")
        btn.click()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0], (cid, other))
        self.assertFalse(btn.isEnabled())
        self.assertEqual(btn.text(), _t("compare_incorporated"))
        dlg.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestImportExperience(unittest.TestCase):
    """First-run import flow: clear state, duplicate-submit guard and recovery."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def setUp(self):
        self.view = self.win.content_stack.widget(0)
        self.view._extract_worker = None
        self.view._teacher_worker = None
        self.view._import_progress.setValue(0)
        self.view._import_paste.setPlainText("一段可用于分析的学习材料。")
        self.view._update_ready()

    def test_import_view_explains_first_run_path_and_llm_effect(self):
        labels = " ".join(label.text() for label in self.view.findChildren(QLabel))
        self.assertIn("导入", labels)
        self.assertIn("知识", labels)
        if self.win.llm_client is None:
            self.assertIn("确定性", labels)
            self.assertIn("配置", labels)

    def test_busy_state_blocks_duplicate_submission(self):
        from unittest import mock

        worker = mock.Mock()
        worker.isRunning.return_value = True
        self.view._extract_worker = worker
        with mock.patch("expert_anything.ui.views.import_view.ExtractWorker") as ctor:
            self.view._on_generate()
        ctor.assert_not_called()
        self.assertFalse(self.view._analysis_btn.isEnabled())

    def test_failure_keeps_inline_error_and_exposes_retry(self):
        from unittest import mock

        with mock.patch("PySide6.QtWidgets.QMessageBox.critical"):
            self.view._on_extraction_error("认证失败")
        self.assertIn("认证失败", self.view._import_status_label.text())
        self.assertTrue(self.view._analysis_btn.isEnabled())
        self.assertIn("重试", self.view._analysis_btn.text())

    def test_pipeline_reports_distinct_stages(self):
        from unittest import mock

        asset = self.win.get_asset()
        with mock.patch("expert_anything.ui.views.import_view.register_asset"), \
             mock.patch("expert_anything.ui.views.import_view.TeacherWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = False
            self.view._on_extraction_finished(asset)
        self.assertGreaterEqual(self.view._import_progress.value(), 80)
        self.assertIn("教师", self.view._import_status_label.text())

    # -- domain template integration ------------------------------------- #

    def _asset_titled(self, needle):
        for aid in self.win.assets:
            asset = self.win.get_asset(aid)
            if asset is not None and needle in (asset.title or ""):
                return asset
        return None

    def test_template_offer_reports_domain_and_coverage(self):
        asset = self._asset_titled("电力")
        if asset is None:
            self.skipTest("demo data has no electricity asset")
        offer = self.view._template_offer(asset)
        self.assertIsNotNone(offer)
        self.assertEqual(offer["domain_id"], "electricity_trading")
        self.assertGreater(offer["matched_count"], 0)
        self.assertLessEqual(offer["coverage"], 1.0)

    def test_template_offer_is_none_without_domain_signal(self):
        class _Plain:
            title = "纯数学笔记"
            concepts: list = []
            learning_path: list = []

        self.assertIsNone(self.view._template_offer(_Plain()))

    def test_declined_template_leaves_pipeline_untouched(self):
        from unittest import mock

        asset = self._asset_titled("电力")
        if asset is None:
            self.skipTest("demo data has no electricity asset")
        before = list(asset.learning_path or [])
        with mock.patch(
            "expert_anything.ui.views.import_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ), mock.patch(
            "expert_anything.ui.views.import_view.apply_domain_template"
        ) as apply_fn:
            self.view._offer_domain_template(asset)
        apply_fn.assert_not_called()
        self.assertEqual(list(asset.learning_path or []), before)

    def test_confirmed_template_applies_and_reports_stats(self):
        from unittest import mock

        from expert_anything.core.domain_templates import TemplateApplicationResult

        asset = self._asset_titled("电力")
        if asset is None:
            self.skipTest("demo data has no electricity asset")
        result = TemplateApplicationResult(
            domain_id="electricity_trading",
            template_name="中国电力市场交易体系",
            applied=True,
            reason="ok",
            template_concept_count=20,
            matched_count=10,
            coverage=0.5,
            enriched_count=3,
            learning_path_applied=True,
            learning_path=["c001"],
        )
        with mock.patch(
            "expert_anything.ui.views.import_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), mock.patch(
            "expert_anything.ui.views.import_view.apply_domain_template",
            return_value=result,
        ) as apply_fn, mock.patch(
            "expert_anything.ui.views.import_view.QMessageBox.information"
        ) as info:
            self.view._offer_domain_template(asset)
        apply_fn.assert_called_once_with(asset, "electricity_trading")
        info.assert_called_once()
        summary = info.call_args[0][2]
        self.assertIn("中国电力市场交易体系", summary)
        self.assertIn("50%", summary)

    def test_failed_apply_warns_and_keeps_import_alive(self):
        from unittest import mock

        asset = self._asset_titled("电力")
        if asset is None:
            self.skipTest("demo data has no electricity asset")
        with mock.patch(
            "expert_anything.ui.views.import_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ), mock.patch(
            "expert_anything.ui.views.import_view.apply_domain_template",
            side_effect=RuntimeError("boom"),
        ), mock.patch(
            "expert_anything.ui.views.import_view.QMessageBox.warning"
        ) as warn:
            self.view._offer_domain_template(asset)  # must not raise
        warn.assert_called_once()

    def test_degraded_result_surfaces_reason(self):
        from expert_anything.core.domain_templates import TemplateApplicationResult
        from expert_anything.core.i18n import t as _tstr

        degraded = TemplateApplicationResult(
            domain_id="electricity_trading",
            template_name="中国电力市场交易体系",
            applied=True,
            reason="degraded_low_coverage",
            template_concept_count=20,
            matched_count=6,
            coverage=0.3,
        )
        text = self.view._template_result_text(degraded)
        self.assertIn("30%", text)
        # language-agnostic: the localized reason sentence must be embedded
        self.assertIn(
            _tstr("domain_template_reason_degraded_low_coverage"), text
        )
