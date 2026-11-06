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
    QWidget,
)

from main import MainWindow
from expert_anything.ui.pyside_graph import KnowledgeGraphView
from expert_anything.ui.widgets._helpers import CollapsibleSection
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

    def test_eight_views(self):
        self.assertEqual(self.win.content_stack.count(), 8)

    def test_two_assets_loaded(self):
        self.assertGreaterEqual(len(self.win.assets), 4)

    def test_topbar_present(self):
        self.assertTrue(hasattr(self.win, "topbar"))
        self.assertTrue(self.win._topbar_asset.text())

    def test_stats_include_avg_mastery_and_unanchored(self):
        stats = self.win._compute_stats()
        self.assertIn("avg_mastery", stats)
        self.assertIn("unanchored", stats)
        self.assertGreaterEqual(stats["avg_mastery"], 0.0)
        self.assertLessEqual(stats["avg_mastery"], 1.0)
        self.assertGreaterEqual(stats["unanchored"], 0)
        self.assertLessEqual(stats["unanchored"], stats["total"])

    def test_view_switching(self):
        for idx in range(self.win.content_stack.count()):
            self.win.content_stack.setCurrentIndex(idx)
            self.win.repaint()
        self.win.content_stack.setCurrentIndex(1)

    def test_asset_switch_rebuilds(self):
        other = next(a for a in self.win.assets if a != self.win.current_asset_id)
        self.win.on_asset_select(other)
        self.assertEqual(self.win.current_asset_id, other)
        self.assertEqual(self.win.content_stack.count(), 8)
        # the cognitive map is the home view, so asset switch lands there
        self.assertEqual(self.win.content_stack.currentIndex(), 2)


class TestPanorama(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_collect_aggregates_across_materials(self):
        self.win.on_nav_click("panorama")
        pv = self.win._panorama_view
        data = pv._collect()
        self.assertGreaterEqual(data["n_assets"], 2)
        self.assertGreater(data["union"], 0)
        self.assertEqual(len(data["materials"]), data["n_assets"])
        self.assertIsInstance(data["unknowns"], list)
        self.assertIsInstance(data["unanchored"], list)
        self.assertIsInstance(data["weak"], list)
        # unknowns are severity-sorted (high first)
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        sevs = [order.get(a["sev"], 9) for a in data["unknowns"]]
        self.assertEqual(sevs, sorted(sevs))

    def test_asset_switch_stays_on_panorama(self):
        self.win.on_nav_click("panorama")
        other = next(a for a in self.win.assets if a != self.win.current_asset_id)
        self.win._on_panorama_asset_switch(other)
        self.assertEqual(self.win.current_asset_id, other)
        # panorama must NOT navigate away after drilling into a material
        self.assertEqual(self.win.content_stack.currentIndex(), 7)

    def test_concept_jump_opens_detail_panel(self):
        asset = self.win.get_asset()
        concept = asset.concepts[0]
        self.win._on_panorama_concept_jump(self.win.current_asset_id, concept.name)
        self.assertIsNotNone(self.win._concept_panel)
        try:
            self.win._concept_panel.close()
        except Exception:
            pass
        self.win._concept_panel = None

    def test_unknown_concept_jump_falls_back_to_learner(self):
        self.win.on_nav_click("panorama")
        self.win._on_panorama_concept_jump("", "不存在的概念XYZ")
        self.assertEqual(self.win.content_stack.currentIndex(), 5)


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

    def test_edges_draw_direction_markers_by_semantics(self):
        self.win.content_stack.setCurrentIndex(2)
        gv = getattr(self.win, "_graph_view", None)
        asset = self.win.get_asset()
        self.assertIsNotNone(gv)
        gv.toggle_skeleton_mode(False)
        gv.set_asset(asset)
        gv.reset_focus()
        gv._update_edges()
        heads = getattr(gv, "_edge_heads", {})
        self.assertTrue(heads, "every rendered edge needs a direction marker")
        from expert_anything.core.decoder import classify_relation

        for key, head in heads.items():
            sem = classify_relation(key[2] or "", gv._edge_type_map.get(key, ""))
            if sem == "contrast":
                self.assertFalse(head.isVisible())  # undirected by design
            else:
                self.assertTrue(head.isVisible())
                self.assertGreater(head.polygon().count(), 2)

    def test_edge_click_opens_relation_evidence_card(self):
        self.win.content_stack.setCurrentIndex(2)
        asset = self.win.get_asset()
        self.assertGreaterEqual(len(asset.relations), 1)
        rel = asset.relations[0]
        view = self.win._concept_map_view
        view._on_edge_click(rel.source, rel.target, rel.label)
        card = self.win._map_detail_ref()
        self.assertIsNotNone(card._relation)
        self.assertEqual(card._relation["evidence"], rel.evidence)
        from expert_anything.core.decoder import classify_relation

        self.assertEqual(
            card._relation["type"], classify_relation(rel.label, rel.type)
        )

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

    def test_mastery_filter_isolates_bands(self):
        self.win.content_stack.setCurrentIndex(2)
        gv = getattr(self.win, "_graph_view", None)
        asset = self.win.get_asset()
        ids = [c.id for c in asset.concepts]
        self.assertGreaterEqual(len(ids), 3, "demo asset needs 3+ concepts")
        mastered_id, weak_id = ids[0], ids[1]
        gv.toggle_skeleton_mode(False)  # skeleton subset would skew the counts
        gv.set_asset(asset, mastery_map={mastered_id: 0.8, weak_id: 0.4})
        gv.reset_focus()
        try:
            gv.set_mastery_filter("mastered")
            self.assertEqual(set(gv._node_items), {mastered_id})
            gv.set_mastery_filter("weak")
            self.assertEqual(set(gv._node_items), {weak_id})
            gv.set_mastery_filter("unstudied")
            shown = set(gv._node_items)
            self.assertNotIn(mastered_id, shown)
            self.assertNotIn(weak_id, shown)
            self.assertGreaterEqual(len(shown), 1)
            # an active band filter must NOT strip a focused ego-network
            gv.focus_concept(mastered_id)
            self.assertIn(mastered_id, gv._node_items)
        finally:
            gv.set_mastery_filter("all")
            gv.reset_focus()

    def test_path_playback_walks_full_path(self):
        self.win.content_stack.setCurrentIndex(2)
        gv = getattr(self.win, "_graph_view", None)
        asset = self.win.get_asset()
        self.assertIsNotNone(gv)
        gv.toggle_skeleton_mode(False)
        gv.set_asset(asset)
        gv.reset_focus()
        if not gv.path_playback_available():
            self.skipTest("demo asset has no curated learning path")
        full = [cid for cid in asset.learning_path if asset.concept_by_id(cid)]
        try:
            self.assertTrue(gv.set_path_playback(True))
            # playback badges the FULL curated path, not the adaptive top-6
            self.assertEqual(set(gv._path_rank), set(full))
            # off-path nodes are faded so the trail stands out
            for cid, item in gv._node_items.items():
                if cid not in gv._path_rank:
                    self.assertAlmostEqual(item.opacity(), 0.35)
            # stepping walks the path with a cursor ring on the current node
            first = gv.path_step(1)
            self.assertIsNotNone(first)
            cid, pos_i, total = first
            self.assertEqual(pos_i, 1)
            visible_path = [c for c in full if c in gv._node_items]
            self.assertEqual(total, len(visible_path))
            self.assertEqual(cid, visible_path[0])
            self.assertIsNotNone(gv._path_cursor_item)
            if len(visible_path) > 1:
                nxt = gv.path_step(1)
                self.assertIsNotNone(nxt)
                self.assertNotEqual(nxt[0], cid)
                # stepping back returns to the first node
                back = gv.path_step(-1)
                self.assertEqual(back[0], visible_path[0])
                # backward from the first wraps to the last
                wrap = gv.path_step(-1)
                self.assertEqual(wrap[0], visible_path[-1])
                # forward from the last wraps back to the first
                self.assertEqual(gv.path_step(1)[0], visible_path[0])
        finally:
            # leaving playback restores the adaptive top-6 badge set
            self.assertFalse(gv.set_path_playback(False))
            self.assertEqual(set(gv._path_rank), set(gv._path_ids_adaptive))
            gv.reset_focus()

    def test_detail_card_favorite_star_persists(self):
        from expert_anything.core.learner import is_favorite

        self.win.content_stack.setCurrentIndex(2)
        card = self.win._map_detail_ref()
        asset = self.win.get_asset()
        concept = asset.concepts[0]
        learner = self.win.learner
        saved = list(learner.get("favorites", []))
        try:
            card.set_concept(asset, concept.id, learner)
            star = card.findChild(QPushButton, "fav_star_btn")
            self.assertIsNotNone(star, "detail card must expose a bookmark star")
            was = is_favorite(learner, concept.name)
            self.assertEqual(star.text(), "★" if was else "☆")
            star.click()
            self.assertEqual(is_favorite(learner, concept.name), not was)
            self.assertEqual(star.text(), "☆" if was else "★")
        finally:
            learner["favorites"] = saved

    def test_detail_card_note_save_updates_state_and_label(self):
        from expert_anything.core.learner import get_note

        self.win.content_stack.setCurrentIndex(2)
        card = self.win._map_detail_ref()
        asset = self.win.get_asset()
        concept = asset.concepts[0]
        learner = self.win.learner
        saved = dict(learner.get("notes", {}))
        try:
            card.set_concept(asset, concept.id, learner)
            # _clear() uses deleteLater() — flush or findChild sees dead widgets
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication

            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            edit_btn = card.findChild(QPushButton, "note_edit_btn")
            body = card.findChild(QLabel, "note_body_lbl")
            self.assertIsNotNone(edit_btn, "detail card must expose a note edit button")
            self.assertIsNotNone(body, "detail card must expose a note body label")
            # save via the factored write path (dialog exec is not testable)
            card._save_note_text(concept.name, "用自己的话：节点电价由边际机组决定")
            self.assertEqual(
                get_note(learner, concept.name), "用自己的话：节点电价由边际机组决定"
            )
            self.assertIn("用自己的话", body.text())
            # clearing deletes the note and resets the label to the empty hint
            card._save_note_text(concept.name, "")
            self.assertEqual(get_note(learner, concept.name), "")
        finally:
            learner["notes"] = saved

    def test_detail_card_replay_button_appears_with_snapshot(self):
        from expert_anything.core.learner import (
            get_lesson_snapshot,
            normalize,
            save_lesson_snapshot,
        )

        self.win.content_stack.setCurrentIndex(2)
        card = self.win._map_detail_ref()
        asset = self.win.get_asset()
        concept = asset.concepts[0]
        learner = self.win.learner
        saved = dict(learner.get("lesson_snapshots", {}))
        try:
            # no snapshot -> no replay button
            learner.setdefault("lesson_snapshots", {}).pop(normalize(concept.name), None)
            card.set_concept(asset, concept.id, learner)
            # _clear() uses deleteLater() — flush or findChild sees dead widgets
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication

            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertIsNone(card.findChild(QPushButton, "replay_btn"))

            save_lesson_snapshot(
                learner, concept.name, asset.asset_id, "example",
                "这是上次的讲解内容。", ["第一步", "第二步"],
            )
            card.set_concept(asset, concept.id, learner)
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            btn = card.findChild(QPushButton, "replay_btn")
            self.assertIsNotNone(btn, "replay button must appear once a snapshot exists")
            self.assertIsNotNone(get_lesson_snapshot(learner, concept.name))
        finally:
            learner["lesson_snapshots"] = saved

    def test_detail_card_score_trail_renders(self):
        from expert_anything.core.learner import normalize, score_trail

        self.win.content_stack.setCurrentIndex(2)
        card = self.win._map_detail_ref()
        asset = self.win.get_asset()
        concept = asset.concepts[0]
        learner = self.win.learner
        saved_hist = list(learner.get("history", []))
        try:
            key = normalize(concept.name)
            learner["history"] = [
                {"concept": concept.name, "key": key, "score": 0.8, "meta": {"review": True}},
                {"concept": concept.name, "key": key, "score": 0.5, "meta": {}},
            ]
            card.set_concept(asset, concept.id, learner)
            # _clear() uses deleteLater() — flush or findChild sees dead widgets
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication

            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            lbl = card.findChild(QLabel, "score_trail_lbl")
            self.assertIsNotNone(lbl, "score trail label must render when >=2 records")
            self.assertIn("50%", lbl.text())
            self.assertIn("80%", lbl.text())
            self.assertIn("↺", lbl.text())
            self.assertEqual(
                [t["score"] for t in score_trail(learner, concept.name)], [0.5, 0.8]
            )
            # fewer than two records -> silent
            learner["history"] = [
                {"concept": concept.name, "key": key, "score": 0.5, "meta": {}}
            ]
            card.set_concept(asset, concept.id, learner)
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertIsNone(card.findChild(QLabel, "score_trail_lbl"))
        finally:
            learner["history"] = saved_hist


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

    def test_reading_position_restored_after_reload(self):
        """The source reader resumes at the saved scroll offset after a
        view rebuild (jump to a lesson and come back -> no lost position)."""
        from PySide6.QtWidgets import QApplication
        from expert_anything.core.learner import save_reading_position

        self.win.show()  # scrollbar range needs a laid-out, visible widget
        self.win.content_stack.setCurrentIndex(3)
        QApplication.processEvents()
        sv = self.win._source_view_widget
        asset = self.win.get_asset()
        learner = self.win.learner
        target = sv.verticalScrollBar().maximum()
        self.assertGreater(target, 0, "demo source should be scrollable")
        save_reading_position(learner, asset.asset_id, target)
        try:
            sv.set_asset(asset, learner)  # re-render schedules a restore
            QApplication.processEvents()  # run the queued restore callback
            self.assertEqual(sv.verticalScrollBar().value(), target)
        finally:
            save_reading_position(learner, asset.asset_id, 0)

    def test_unanchored_concept_mark(self):
        """Concepts without source locations get a hollow-ring corner mark
        plus a tooltip hint; anchored concepts carry neither."""
        from PySide6.QtWidgets import QGraphicsEllipseItem
        from expert_anything.core.i18n import t as _t

        gv = self.win._graph_view
        asset = self.win.get_asset()
        target = asset.concepts[0]
        target.locations = []  # simulate a template-enriched concept
        # Skeleton mode persists from the global panorama (60 concepts) and its
        # backbone subset need not contain every anchored concept. Disable it so
        # this assertion is about the corner mark, not about skeleton selection.
        gv.toggle_skeleton_mode(False)
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


class TestMasteryPredictionCard(unittest.TestCase):
    """The forecast card must appear, order falling-trend concepts first
    (they need the intervention), and stay out of the review channel's
    forgetting dips."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_prediction_card_shows_falling_first(self):
        win = self.win
        state = win.learner
        # newest-first teaching history: F falling (0.9->0.4),
        # R rising (0.3->0.6)
        state["history"] = [
            {"concept": "F", "score": 0.4},
            {"concept": "F", "score": 0.9},
            {"concept": "R", "score": 0.6},
            {"concept": "R", "score": 0.3},
        ]
        state["concepts"] = {
            "f": {"key": "f", "name": "F", "mastery": 0.4, "sources": ["a1"]},
            "r": {"key": "r", "name": "R", "mastery": 0.6, "sources": ["a1"]},
        }
        win.learner_view.refresh()
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton

        # processEvents alone does not flush DeferredDelete without a
        # running event loop — force it so findChildren sees live widgets
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        labels = [l.text() for l in win.learner_view.findChildren(QLabel)]
        self.assertTrue(
            any("掌握预测" in t or "Mastery Forecast" in t for t in labels),
            f"forecast card title not found: {sorted(set(labels))[:15]}",
        )
        trend_rows = [t for t in labels if "趋势" in t or "trend" in t.lower()]
        self.assertGreaterEqual(len(trend_rows), 2, "trend rows missing")
        # falling badge must render before rising badge (intervention
        # first) — search INSIDE the forecast card frame so other sections
        # cannot pollute the ordering assertion
        title_lbl = next(
            (l for l in win.learner_view.findChildren(QLabel)
             if "掌握预测" in l.text() or "Mastery Forecast" in l.text()),
            None,
        )
        self.assertIsNotNone(title_lbl, "forecast title not found")
        card_labels = [
            l.text() for l in title_lbl.parent().findChildren(QLabel)
        ]
        pos = {
            "down": next(
                (i for i, t in enumerate(card_labels)
                 if t.startswith("\u2193")), -1,
            ),
            "up": next(
                (i for i, t in enumerate(card_labels)
                 if t.startswith("\u2191")), -1,
            ),
        }
        self.assertGreaterEqual(pos["down"], 0, "falling tag missing")
        self.assertGreater(pos["up"], -1, "rising tag missing")
        self.assertLess(pos["down"], pos["up"], "falling must sort first")
        # actionable: each forecast row carries a study button
        go_btns = [
            b for b in win.learner_view.findChildren(QPushButton)
            if "继续学" in b.text() or b.text() == "Study"
        ]
        self.assertGreaterEqual(len(go_btns), 2, "study buttons missing")

    def test_prediction_card_ignores_review_dips(self):
        win = self.win
        state = win.learner
        # teaching rising + review dip must NOT flip the trend to falling
        state["history"] = [
            {"concept": "F", "score": 0.2,
             "meta": {"channel": "answer", "review": True}},
            {"concept": "F", "score": 0.6},
            {"concept": "F", "score": 0.3},
        ]
        state["concepts"] = {
            "f": {"key": "f", "name": "F", "mastery": 0.5, "sources": ["a1"]},
        }
        win.learner_view.refresh()
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication, QLabel

        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        labels = [l.text() for l in win.learner_view.findChildren(QLabel)]
        self.assertFalse(
            any("下滑" in t or "falling" in t for t in labels),
            "review dip incorrectly reported as falling trend",
        )


class TestStyleReviewBucketTag(unittest.TestCase):
    """The style-effectiveness card must surface the retention bucket —
    teaching avg and review retention answer different questions and
    conflating them (or hiding one) breaks the card's purpose."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_review_bucket_tag_shown_in_style_card(self):
        win = self.win
        state = win.learner
        state["history"] = [
            {"concept": "LMP", "score": 0.5, "meta": {"style": "analogy"}},
            {"concept": "LMP", "score": 0.9, "meta": {"style": "analogy", "review": True}},
        ]
        state["concepts"] = {}
        win.learner_view.refresh()
        from PySide6.QtWidgets import QLabel

        texts = [l.text() for l in win.learner_view.findChildren(QLabel)]
        self.assertTrue(
            any("复习巩固" in t or "review retention" in t for t in texts),
            "retention bucket tag not found in style card",
        )
        # teaching avg must stay 0.5, not diluted by the review score
        self.assertTrue(
            any(t.strip() == "50%" for t in texts),
            f"teaching avg diluted: {sorted(set(texts))[:20]}",
        )


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

    def test_recent_taught_bar_lists_asset_concepts_only(self):
        tv = self._teach_view()
        asset = self.win.get_asset()
        learner = self.win.learner
        saved = learner.get("recent_taught")
        try:
            learner["recent_taught"] = [
                asset.concepts[0].name,
                "完全不属于本资产的外星概念",  # must be filtered out
                asset.concepts[1].name,
            ]
            tv._rebuild_recent_bar()
            self.assertFalse(tv._recent_host.isHidden())
            # Old pills are deleteLater()'d — flush before findChildren or it
            # counts pills from every previous rebuild (DeferredDelete rule).
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            pills = tv._recent_host.findChildren(QPushButton)
            self.assertEqual(
                [p.text() for p in pills],
                [asset.concepts[0].name, asset.concepts[1].name],
            )
        finally:
            if saved is None:
                learner.pop("recent_taught", None)
            else:
                learner["recent_taught"] = saved
            tv._rebuild_recent_bar()

    def test_recent_taught_bar_hidden_when_nothing_matches(self):
        tv = self._teach_view()
        learner = self.win.learner
        saved = learner.get("recent_taught")
        try:
            learner["recent_taught"] = ["无关概念甲", "无关概念乙"]
            tv._rebuild_recent_bar()
            self.assertTrue(tv._recent_host.isHidden())
        finally:
            if saved is None:
                learner.pop("recent_taught", None)
            else:
                learner["recent_taught"] = saved
            tv._rebuild_recent_bar()

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


class TestLessonResultUI(unittest.TestCase):
    """Lesson result view: evidence badges, doubt strip, silent harness adapt."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

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

    def test_stuck_adapts_silently_and_dedupes(self):
        """Stuck → the system adapts teaching silently: no evolution card,
        no dialog. The evolved HarnessSpec is persisted with its audit event
        and the live explanation style switches — that is the only signal the
        learner sees. The same (concept, reason, candidate) adapts once."""
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        concept = asset.concepts[0]
        fake = {
            "evolved": True,
            "reason": "stuck",
            "focused": {"name": concept.name, "attempts": 3, "avg": 0.2},
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
        before = dict(win._harness_specs)
        hist_before = getattr(win, "_harness_history", [])
        try:
            with (
                mock.patch.object(main_module._ah, "evolve_joint", return_value=fake),
                mock.patch.object(main_module._ah, "save_harness_state") as save_mock,
                mock.patch.object(
                    main_module._ah, "record_harness_evolution"
                ) as rec_mock,
                mock.patch.object(
                    main_module.QMessageBox, "information"
                ) as info_mock,
            ):
                win._on_stuck_detected(concept.name, {"attempts": 3, "avg": 0.2})
                win._on_stuck_detected(concept.name, {"attempts": 4, "avg": 0.1})
            save_mock.assert_called_once()
            rec_mock.assert_called_once()  # dedup: one audit event, not two
            ev = rec_mock.call_args.args[1]
            self.assertEqual(ev["reason"], "stuck")
            info_mock.assert_not_called()  # no popup — internal mechanism hidden
            self.assertEqual(
                win._harness_specs.get(asset.asset_id, {}).get("name"),
                "evolved-stuck",
            )
            # the only learner-visible effect: live explanation style nudge
            combo = win._teach_view._style_combo
            self.assertEqual(combo.currentIndex(), win._teach_view._CODE_TO_IDX["diagram"])
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_history = hist_before
            win._harness_offer_shown = set()

    def test_transfer_adopted_silently_without_local_evolution(self):
        """No local candidate → the strategy proven on another asset is
        adopted silently (persist + audit + style nudge), still no card."""
        import main as main_module
        from unittest import mock

        win = self.win
        asset = win.get_asset()
        if asset is None or not asset.concepts:
            self.skipTest("no asset loaded")
        others = [aid for aid in win.assets if aid != asset.asset_id]
        if not others:
            self.skipTest("no second asset loaded")
        concept = asset.concepts[0]
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
            "source_asset_id": others[0],
            "source_title": "Source Book",
            "spec": spec,
            "evaluation": {"comparison": {"diff": 0.12}, "cost_diff": 4},
            "gain": 0.12,
        }
        before = dict(win._harness_specs)
        hist_before = getattr(win, "_harness_history", [])
        try:
            win._harness_specs[others[0]] = spec  # source asset must carry a spec
            with (
                mock.patch.object(
                    main_module._ah, "evolve_joint", return_value={"evolved": False}
                ),
                mock.patch.object(
                    win, "_find_transfer_candidates", return_value=[payload]
                ) as find_mock,
                mock.patch.object(
                    main_module._ah,
                    "adopt_harness_for_asset",
                    return_value=(True, {}),
                ) as adopt_mock,
                mock.patch.object(
                    main_module._ah, "load_harness_history", return_value=[]
                ),
            ):
                win._on_stuck_detected(concept.name, {"attempts": 3, "avg": 0.2})
                win._on_stuck_detected(concept.name, {"attempts": 4, "avg": 0.1})
            find_mock.assert_called_once()  # dedup: second run skips the search
            adopt_mock.assert_called_once()
            kw = adopt_mock.call_args.kwargs
            self.assertEqual(kw.get("source_asset_id"), others[0])
            self.assertEqual(kw.get("concept"), concept.name)
            self.assertEqual(
                win._harness_specs.get(asset.asset_id, {}).get("name"), "migr-1"
            )
            combo = win._teach_view._style_combo
            self.assertEqual(combo.currentIndex(), win._teach_view._CODE_TO_IDX["diagram"])
        finally:
            win._harness_specs.clear()
            win._harness_specs.update(before)
            win._harness_history = hist_before
            win._harness_offer_shown = set()
            win._transfer_offer_shown = set()


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
    """Cross-asset harness migration: differential evaluation + silent adopt."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

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
            self.assertIn("智能分析", labels)
            self.assertIn("仍可导入", labels)

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
        # 小白文案：报"补充了几个概念的专业释义"，不再报覆盖率/命中数
        self.assertIn("3", summary)
        self.assertIn("专业释义", summary)

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
        # language-agnostic: the localized reason sentence must be embedded
        self.assertIn(
            _tstr("domain_template_reason_degraded_low_coverage"), text
        )



class TestFlashcardReviewWiring(unittest.TestCase):
    """Flashcard self-rating must persist as *review* evidence.

    Regression guard: ``_open_flashcards`` called ``record_evaluation`` without
    importing it, so every self-rating raised NameError and the learner's
    review outcome was silently discarded.  The ratings must also carry
    ``meta={"channel": "flashcard", "review": True}``: rated as *forgetting*
    they must NOT be counted by the teaching-channel aggregators, otherwise a
    normal spaced-review lapse would fire stuck detection / style rotation on
    data that only says "the learner forgot" (AGENTS.md 6 + 12).
    """

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def _seed_due(self, state):
        """Give the active asset a fully-due population with a shaky history.

        Each concept already has two low *teaching* attempts, so a third low
        score would ordinarily tip it into ``stuck_concepts`` — which is what
        makes the review-channel separation observable rather than vacuous.
        """
        import datetime as _dt

        from expert_anything.core.learner import due_for_review, normalize

        asset = self.win.get_asset()
        old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=9)).isoformat()
        state["concepts"] = {}
        state["history"] = []
        for c in asset.concepts[:3]:
            key = normalize(c.name)
            state["concepts"][key] = {
                "name": c.name, "mastery": 0.5, "sources": [asset.asset_id],
                "last_feedback": "", "updated_at": old,
            }
            for _ in range(2):
                state["history"].append({
                    "concept": c.name, "key": key, "asset_id": asset.asset_id,
                    "score": 0.1, "answer": "", "feedback": "", "at": old,
                    "meta": {"channel": "answer", "review": False},
                })
        return due_for_review(state, asset=asset)

    def _run_flashcards(self, due, score):
        """Drive the real dialog path; self-rate every card at *score*."""
        from unittest import mock

        from expert_anything.ui.widgets import flashcard as flashcard_mod

        def fake_exec(dlg):
            for item in dlg._concepts:
                dlg._rate(item["name"], score)
            return 1

        with mock.patch.object(flashcard_mod.FlashCardDialog, "exec", fake_exec):
            self.win.learner_view._open_flashcards(due)

    def test_self_rating_persists_with_review_semantics(self):
        from expert_anything.core.learner import review_gain, stuck_concepts

        state = self.win.learner
        due = self._seed_due(state)
        self.assertTrue(due, "no due concepts to review")

        before = len(state["history"])
        self._run_flashcards(due, 0.1)  # learner forgot every card

        added = len(state["history"]) - before
        self.assertEqual(
            added, len(due),
            "every self-rating must append one evaluation row "
            "(the NameError bug dropped them all)",
        )
        row = state["history"][0]
        self.assertEqual(row["meta"].get("channel"), "flashcard")
        self.assertTrue(row["meta"].get("review"), "flashcard ratings are review evidence")

        # retention channel sees it ...
        self.assertGreater(
            len(review_gain(state)["concepts"]), 0,
            "flashcard ratings must feed the review-gain (retention) analytics",
        )
        # ... teaching channel must not: three low *review* attempts are
        # forgetting, not a failed teaching strategy.
        self.assertEqual(
            [s["name"] for s in stuck_concepts(state)], [],
            "low review scores must not trigger stuck detection "
            "(would wrongly rotate teaching style / evolve the harness)",
        )

    def test_stuck_detection_would_fire_without_review_flag(self):
        """Sanity-check the guard above: the same low scores DO trip stuck
        detection when they are recorded as first-time teaching, which is why
        the review flag matters."""
        from expert_anything.core.learner import record_evaluation, stuck_concepts

        state = {"concepts": {}, "history": []}
        for _ in range(3):
            record_evaluation(state, "总量控制", "a1", 0.1, "", "f",
                              meta={"channel": "answer", "review": False})
        self.assertEqual(
            len(stuck_concepts(state)), 1,
            "control case: teaching-channel failures must still be detected",
        )

    def test_flashcard_entry_point_present(self):
        """The button lives inside the due-for-review card, so the queue must
        be non-empty for it to exist at all."""
        from PySide6.QtWidgets import QPushButton

        state = self.win.learner
        due = self._seed_due(state)
        self.assertTrue(due, "no due concepts to review")
        # rebuild in place so the actions tab re-reads the seeded queue; flush
        # DeferredDelete first or stale widgets stay in the object tree and get
        # counted twice (tests/test_ui.py house rule)
        self.win.learner_view.refresh()
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        texts = [b.text() for b in self.win.learner_view.findChildren(QPushButton)]
        self.assertTrue(
            any("闪卡" in t or "Flashcard" in t or "フラッシュカード" in t for t in texts),
            f"flashcard button missing; buttons={texts}",
        )


class TestMisconceptionCardRendering(unittest.TestCase):
    """The teacher model's common misconceptions must reach the lesson page.

    Regression guard: ``_attach_misconceptions`` looked up ``TeacherModel.notes``
    (the real field is ``concept_notes``, read via ``concept_note_by_id``), and
    the surrounding ``except Exception: pass`` turned that AttributeError into a
    silent no-op — the walk-ahead card never appeared for any asset.
    """

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def _show_lesson(self, concept):
        self.win._teach_concept_now = concept.name
        self.win._display_teach_result({
            "concept": concept.name, "style": "例子", "explanation": "x",
            "example": "", "steps": [], "practice": "", "evidence": [],
        })
        return self.win._teach_view._teach_view_widget

    def _with_teacher(self, data):
        return _teacher_override(self.win, self.win.get_asset().asset_id, data)

    def test_misconceptions_render_on_lesson_result(self):
        import copy

        from PySide6.QtWidgets import QLabel

        from expert_anything.core.i18n import t as _tstr

        concept = self.win.get_asset().concepts[0]
        td = copy.deepcopy(
            self.win.teacher_models.get(self.win.get_asset().asset_id) or {}
        )
        notes = td.setdefault("concept_notes", [])
        note = next((n for n in notes if n.get("concept_id") == concept.id), None)
        if note is None:
            note = {"concept_id": concept.id, "name": concept.name}
            notes.append(note)
        note["misconceptions"] = ["误解甲：把配额当作免费赠予"]

        with self._with_teacher(td):
            view = self._show_lesson(concept)
            joined = "\n".join(l.text() for l in view.findChildren(QLabel))

        self.assertIn(_tstr("misconception_section"), joined)
        self.assertIn(_tstr("misconception_hint"), joined)
        self.assertIn("误解甲：把配额当作免费赠予", joined)

    def test_no_card_when_teacher_has_no_misconceptions(self):
        from PySide6.QtWidgets import QLabel

        from expert_anything.core.i18n import t as _tstr

        concept = self.win.get_asset().concepts[0]
        cleaned = dict(self.win.teacher_models.get(self.win.get_asset().asset_id) or {})
        cleaned["concept_notes"] = [
            {k: v for k, v in n.items() if k != "misconceptions"}
            for n in cleaned.get("concept_notes", [])
        ]
        with self._with_teacher(cleaned):
            view = self._show_lesson(concept)
            joined = "\n".join(l.text() for l in view.findChildren(QLabel))

        self.assertNotIn(
            _tstr("misconception_section"), joined,
            "no misconceptions -> the warning card must stay absent",
        )


class _teacher_override:
    """Temporarily swap one asset's teacher model on the main window."""

    def __init__(self, win, asset_id, data):
        self._win = win
        self._aid = asset_id
        self._new = data

    def __enter__(self):
        self._had = self._aid in self._win.teacher_models
        self._old = self._win.teacher_models.get(self._aid)
        self._win.teacher_models[self._aid] = self._new
        return self._win

    def __exit__(self, *exc):
        if self._had:
            self._win.teacher_models[self._aid] = self._old
        else:
            self._win.teacher_models.pop(self._aid, None)
        return False



class TestGuideBar(unittest.TestCase):
    """The coach's permanent voice: one主张, one reason, one action."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def setUp(self):
        # every test starts from a clean bar
        self.win._guide_bar.set_recommendation(None)

    def _rec(self, **kw):
        rec = {
            "kind": "focus",
            "concept_id": "",
            "concept_name": "总量控制",
            "why_key": "coach_why_focus_unlock",
            "why_args": {"n": 6},
            "urgency": 1.3,
            "alternatives": [],
        }
        rec.update(kw)
        return rec

    def test_bar_renders_claim_and_reason(self):
        from expert_anything.core.i18n import t as _tstr

        bar = self.win._guide_bar
        bar.set_recommendation(self._rec())

        self.assertTrue(bar.isVisible(), "an actionable主张 must show the bar")
        text = self._bar_text()
        self.assertIn("总量控制", text)
        # the reason is the whole point: it says WHY, not just WHAT
        self.assertIn(_tstr("coach_why_focus_unlock", n=6), text)
        self.assertIn(_tstr("coach_now"), text)

    def _bar_text(self) -> str:
        from PySide6.QtWidgets import QLabel

        return "\n".join(
            l.text() for l in self.win._guide_bar.findChildren(QLabel) if l.text()
        )

    def test_bar_hidden_without_actionable_claim(self):
        bar = self.win._guide_bar
        bar.set_recommendation(None)
        self.assertFalse(bar.isVisible())
        # an unknown-kind主张 without a concept is not actionable
        bar.set_recommendation(self._rec(concept_name="", kind="focus"))
        self.assertFalse(bar.isVisible())

    def test_import_claim_is_allowed_without_concept(self):
        bar = self.win._guide_bar
        bar.set_recommendation(
            self._rec(kind="import", concept_name="", why_key="coach_why_import")
        )
        self.assertTrue(
            bar.isVisible(),
            "first-run must still be led somewhere (import), not left silent",
        )

    def test_review_claim_starts_review_lesson(self):
        """review主张 must reach the review entry point (vary=1), not a new lesson."""
        calls = []
        original = self.win._on_review_one_request
        self.win._on_review_one_request = lambda name: calls.append(("review", name))
        try:
            self.win._on_guide_start(
                self._rec(kind="review", concept_name="碳排放配额", why_key="coach_why_review")
            )
        finally:
            self.win._on_review_one_request = original
        self.assertEqual(calls, [("review", "碳排放配额")])

    def test_non_review_claim_starts_normal_lesson(self):
        calls = []
        original = self.win._on_teach_request
        self.win._on_teach_request = lambda name: calls.append(("teach", name))
        try:
            self.win._on_guide_start(self._rec(kind="focus", concept_name="总量控制"))
        finally:
            self.win._on_teach_request = original
        self.assertEqual(calls, [("teach", "总量控制")])

    def test_import_claim_navigates_to_import_view(self):
        self.win._on_guide_start(
            self._rec(kind="import", concept_name="", why_key="coach_why_import")
        )
        self.assertEqual(self.win.content_stack.currentIndex(), 0)

    def test_swap_advances_to_alternative(self):
        bar = self.win._guide_bar
        alt = self._rec(concept_name="碳排放配额", why_key="coach_why_weak")
        bar.set_recommendation(self._rec(alternatives=[alt]))
        self.assertIn("总量控制", self._bar_text())

        bar._emit_swap()
        self.assertIn(
            "碳排放配额", self._bar_text(),
            "换一个 must surface the runner-up主张",
        )

    def test_swap_button_hidden_without_alternatives(self):
        bar = self.win._guide_bar
        bar.set_recommendation(self._rec(alternatives=[]))
        self.assertFalse(bar._swap_btn.isVisible())
        bar.set_recommendation(self._rec(alternatives=[self._rec(concept_name="另一个")]))
        self.assertTrue(bar._swap_btn.isVisible())

    def test_refresh_uses_real_coach_and_never_raises(self):
        """The live path must produce a real主张 from the demo asset."""
        self.win._refresh_guide_bar()
        rec = self.win._guide_bar.current()
        self.assertIsNotNone(rec, "demo data must yield a主张")
        # bind to the module contract instead of a copied literal: a new kind
        # must not require editing every test that enumerates them.
        from expert_anything.core.coach import KIND_ORDER

        self.assertIn(rec["kind"], KIND_ORDER)

    def test_guide_bar_lives_outside_content_stack(self):
        """It must stay visible in every view, so it cannot be a stacked page."""
        bar = self.win._guide_bar
        for idx in range(self.win.content_stack.count()):
            self.assertIsNot(self.win.content_stack.widget(idx), bar)
        # and it is part of the topbar container
        self.assertTrue(self.win.topbar.isAncestorOf(bar))



class TestAnalysisFold(unittest.TestCase):
    """Analysis cards sit behind a disclosure; the mainline leads the page."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def setUp(self):
        # the fold needs learner history to have analytical content at all
        from expert_anything.core.learner import record_evaluation

        state = self.win.learner
        state["history"] = []
        state["concepts"] = {}
        asset = self.win.get_asset()
        for c in asset.concepts[:4]:
            record_evaluation(
                state, c.name, asset.asset_id, 0.4, "a", "f",
                meta={"channel": "answer", "review": False},
            )
            record_evaluation(
                state, c.name, asset.asset_id, 0.85, "a", "f",
                meta={"channel": "answer", "review": True},
            )
        self.win.content_stack.setCurrentWidget(self.win.learner_view)
        self.win.learner_view.refresh()

    def test_fold_starts_collapsed_and_holds_the_analytics(self):
        lv = self.win.learner_view
        self.assertTrue(hasattr(lv, "_analysis_toggle"), "fold toggle missing")
        self.assertFalse(
            lv._analysis_body.isVisible(),
            "analysis must be collapsed by default so the mainline leads",
        )
        self.assertGreater(
            lv._analysis_body.layout().count(), 0,
            "the fold must actually contain the analytical cards",
        )

    def test_expanding_reveals_analytics(self):
        lv = self.win.learner_view
        lv._analysis_toggle.setChecked(True)
        self.assertTrue(
            lv._analysis_body.isVisible(),
            "expanding the disclosure must reveal the cards",
        )
        lv._analysis_toggle.setChecked(False)
        self.assertFalse(lv._analysis_body.isVisible())

    def test_fold_toggle_is_labelled_and_localised(self):
        from expert_anything.core.i18n import t as _tstr

        lv = self.win.learner_view
        label = lv._analysis_toggle.text()
        self.assertIn(_tstr("coach_more"), label)
        self.assertTrue(label.strip().startswith(("▸", "▾")))


class TestGuideBarSwapLabel(unittest.TestCase):
    """The swap button used to render blank (unreferenced i18n key)."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def test_swap_button_has_localised_text(self):
        from expert_anything.core.i18n import t as _tstr

        bar = self.win._guide_bar
        bar.set_recommendation({
            "kind": "focus", "concept_id": "", "concept_name": "总量控制",
            "why_key": "coach_why_focus", "why_args": {}, "urgency": 1.0,
            "alternatives": [{
                "kind": "focus", "concept_id": "", "concept_name": "碳排放配额",
                "why_key": "coach_why_focus", "why_args": {}, "urgency": 0.9,
                "alternatives": [],
            }],
        })
        self.assertEqual(
            bar._swap_btn.text(), _tstr("coach_swap"),
            "an unlabelled button is invisible affordance — it must be localised",
        )



class TestGuideBarFeedback(unittest.TestCase):
    """Declining advice must be possible, recorded, and visibly acted upon."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def setUp(self):
        """A review-due learner state so the bar leads with a review claim."""
        import datetime as _dt

        from expert_anything.core.learner import normalize

        asset = self.win.get_asset()
        old = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=9)
        ).isoformat()
        state = self.win.learner
        state["concepts"] = {}
        state["history"] = []
        state["coach"] = {"events": []}
        for c in asset.concepts:
            state["concepts"][normalize(c.name)] = {
                "name": c.name, "mastery": 0.2, "sources": [asset.asset_id],
                "last_feedback": "", "updated_at": old,
            }
        self.win._refresh_guide_bar()

    def test_skip_button_exists_and_is_localised(self):
        from expert_anything.core.i18n import t as _tstr

        bar = self.win._guide_bar
        self.assertTrue(hasattr(bar, "_dismiss_btn"), "skip affordance missing")
        self.assertEqual(
            bar._dismiss_btn.text(), _tstr("coach_dismiss"),
            "declining must be a labelled, discoverable action",
        )

    def test_dismiss_is_persisted_to_the_feedback_log(self):
        bar = self.win._guide_bar
        self.assertEqual(bar.current()["kind"], "review", "precondition")

        bar._emit_dismiss()

        events = self.win.learner.get("coach", {}).get("events", [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "dismiss")
        self.assertEqual(events[0]["kind"], "review")

    def test_repeated_dismissal_changes_what_the_coach_leads_with(self):
        from expert_anything.core.coach import FATIGUE_THRESHOLD, coach_fatigue

        bar = self.win._guide_bar
        self.assertEqual(bar.current()["kind"], "review", "precondition")

        for _ in range(FATIGUE_THRESHOLD):
            bar._emit_dismiss()

        self.assertEqual(coach_fatigue(self.win.learner), {"review": FATIGUE_THRESHOLD})
        self.assertNotEqual(
            bar.current()["kind"], "review",
            "the bar must re-render with a different kind, not the same advice",
        )
        self.assertEqual(bar.current()["fatigue_note"]["kind"], "review")

    def test_accepting_records_start_and_clears_fatigue(self):
        from expert_anything.core.coach import (
            FATIGUE_THRESHOLD,
            coach_fatigue,
        )

        bar = self.win._guide_bar
        for _ in range(FATIGUE_THRESHOLD):
            bar._emit_dismiss()
        self.assertTrue(coach_fatigue(self.win.learner))

        # accept whatever is on offer now
        rec = bar.current()
        calls = []
        original = self.win._on_teach_request
        self.win._on_teach_request = lambda n: calls.append(n)
        try:
            self.win._on_guide_start(rec)
        finally:
            self.win._on_teach_request = original

        events = self.win.learner["coach"]["events"]
        self.assertEqual(events[0]["action"], "start")
        self.assertTrue(calls, "accepting must actually start a lesson")

    def test_swap_records_the_declined_claim_not_the_new_one(self):
        """The log must record what was rejected, not where we moved to."""
        bar = self.win._guide_bar
        rec = bar.current()
        self.assertTrue(rec.get("alternatives"), "need a runner-up to swap to")
        rejected_kind = rec["kind"]
        next_kind = rec["alternatives"][0]["kind"]

        bar._emit_swap()

        events = self.win.learner["coach"]["events"]
        self.assertEqual(events[0]["action"], "swap")
        self.assertEqual(
            events[0]["kind"], rejected_kind,
            "recording the destination instead of the rejection would invert "
            "the signal and demote the advice the learner actually accepted",
        )
        if next_kind != rejected_kind:
            # and the bar did move on
            self.assertEqual(bar.current()["kind"], next_kind)

    def test_feedback_failure_does_not_break_the_shell(self):
        """A corrupt learner state must degrade quietly, never raise."""
        bar = self.win._guide_bar
        self.win.learner["coach"] = "corrupt"
        try:
            bar._emit_dismiss()
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"dismiss must not raise on corrupt state: {exc!r}")


class TestMapLegendModes(unittest.TestCase):
    """The legend must describe the node fill semantics actually on screen —
    a legend that keeps saying grey/amber/green while every node is painted
    red→green heat is actively lying to the learner."""

    @classmethod
    def setUpClass(cls):
        prepare_app()
        from expert_anything.ui.widgets.map_widgets import MapLegend

        cls.legend = MapLegend()

    @classmethod
    def tearDownClass(cls):
        cls.legend.deleteLater()

    def _texts(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication, QLabel

        # set_mode() deleteLater()s replaced chips; flush DeferredDelete or
        # findChildren() still counts the stale ones (AGENTS.md UI trap).
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return [l.text() for l in self.legend.findChildren(QLabel) if l.text()]

    def test_default_row_describes_mastery_fills(self):
        from expert_anything.core.i18n import t

        texts = self._texts()
        self.assertIn(t("legend_unstudied"), texts)
        self.assertNotIn(t("legend_hop2_node"), texts)

    def test_mastery_heat_swaps_mastery_chips_for_scale(self):
        from expert_anything.core.i18n import t

        self.legend.set_mode(mastery_heat=True)
        texts = self._texts()
        self.assertNotIn(t("legend_unstudied"), texts)
        self.assertIn(f"{t('legend_heat_low')} → {t('legend_heat_high')}", texts)
        # border semantics (anomaly / unanchored) survive every fill mode
        self.assertTrue(any(t("legend_unanchored") in x for x in texts))

    def test_density_swaps_for_value_scale(self):
        from expert_anything.core.i18n import t

        self.legend.set_mode(density=True)
        self.assertIn(
            f"{t('legend_density_low')} → {t('legend_density_high')}", self._texts()
        )

    def test_hop2_appends_and_drops_second_ring_chip(self):
        from expert_anything.core.i18n import t

        self.legend.set_mode(hop2=True)
        self.assertIn(t("legend_hop2_node"), self._texts())
        self.legend.set_mode()
        self.assertNotIn(t("legend_hop2_node"), self._texts())


class TestGlossaryPanel(unittest.TestCase):
    """术语对照表：领域术语总表。

    core.terminology.glossary/stats 与 terminology_count/source_note 三语键
    早已就绪却无 UI（本轮接上），术语只来自已注册的领域模板。
    """

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def _buttons(self):
        from PySide6.QtWidgets import QPushButton

        view = self.win._knowledge_view
        return [b for b in view.findChildren(QPushButton)
                if b.objectName() == "glossary_btn"]

    def test_button_present_for_domain_asset(self):
        self.win.on_nav_click("knowledge")
        self.assertTrue(self._buttons(), "domain asset must expose 🔤 术语表")

    def test_button_emits_glossary_request(self):
        self.win.on_nav_click("knowledge")
        btns = self._buttons()
        self.assertTrue(btns)
        btn = btns[0]
        got = {"opened": False}
        # The button is wired to main's real handler (opens a modal dialog).
        # Detach it so the test never blocks in the dialog's event loop.
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        btn.clicked.connect(lambda checked=False: got.__setitem__("opened", True))
        try:
            btn.click()
            self.assertTrue(got["opened"])
        finally:
            btn.clicked.disconnect()

    def test_dialog_rows_grouped_and_jumpable(self):
        from PySide6.QtWidgets import QPushButton

        from expert_anything.ui.widgets.glossary import GlossaryDialog

        asset = self.win.get_asset()
        dlg = GlossaryDialog(asset)
        rows = [r for rows in dlg._groups.values() for r in rows]
        self.assertTrue(rows, "domain asset must yield glossary rows")
        jumps = [b for b in dlg.findChildren(QPushButton) if b.text() == "▶"]
        self.assertTrue(jumps, "demo terms map onto concepts → ▶ jump expected")
        got = {}
        dlg.concept_jump_requested.connect(lambda cid: got.__setitem__("cid", cid))
        jumps[0].click()
        self.assertTrue(got.get("cid"))
        dlg.deleteLater()

    def test_empty_glossary_for_undetected_domain(self):
        from expert_anything.core.models import KnowledgeAsset
        from expert_anything.ui.widgets.glossary import GlossaryDialog

        plain = KnowledgeAsset(
            asset_id="x",
            type="txt",
            title="A story about nothing",
            source_name="nothing.txt",
            created_at="2026-01-01T00:00:00",
        )
        dlg = GlossaryDialog(plain)
        self.assertEqual(dlg._groups, {})
        dlg.deleteLater()


class TestTopbarDrilldown(unittest.TestCase):
    """统计 chip 必须下钻（设计理念第 20 条）——topbar 进度数字点了要去到对应列表。"""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_progress_line_renders_links(self):
        text = self.win._topbar_progress.text()
        self.assertIn("drill:mastered", text)
        self.assertIn("drill:learning", text)
        self.assertIn("drill:due", text)
        # no control-character sentinel may leak into the rendered label
        self.assertNotIn("\x01", text)

    def test_drill_mastered_lands_on_filtered_knowledge(self):
        try:
            self.win._on_topbar_drill("drill:mastered")
            self.assertEqual(self.win.content_stack.currentIndex(), 1)
            combo = self.win._knowledge_view._mastery_filter
            self.assertEqual(combo.currentIndex(), 4)
        finally:
            self.win._knowledge_view._mastery_filter.setCurrentIndex(0)

    def test_drill_due_opens_learner(self):
        self.win._on_topbar_drill("drill:due")
        self.assertEqual(self.win.content_stack.currentIndex(), 5)


class TestKnowledgePanoramaFeedback(unittest.TestCase):
    """Sorting the panorama must hand the learner onward, not dead-end."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()

    def _view(self):
        from expert_anything.ui.views.knowledge_view import KnowledgeView

        v = KnowledgeView(self.win)
        self.addCleanup(v.deleteLater)
        return v

    def test_feedback_appears_and_carries_next_concept(self):
        from expert_anything.core.i18n import t

        view = self._view()
        self.assertFalse(view._pan_feedback.isVisibleTo(view))

        view._on_panorama_game_scored(1.0)
        self.assertTrue(view._pan_feedback.isVisibleTo(view))
        self.assertIn(t("pan_feedback_full"), view._pan_feedback.text())
        if view._pan_next_name:
            self.assertTrue(view._pan_learn_btn.isVisibleTo(view))
            self.assertIn(view._pan_next_name, view._pan_learn_btn.text())
        else:
            self.assertFalse(view._pan_learn_btn.isVisibleTo(view))

    def test_partial_score_reports_percentage(self):
        view = self._view()
        view._on_panorama_game_scored(0.4)
        self.assertIn("40", view._pan_feedback.text())

    def test_go_learn_emits_teach_request(self):
        view = self._view()
        seen = []
        view.teach_requested.connect(seen.append)
        view._pan_next_name = "总量控制"
        view._on_pan_go_learn()
        self.assertEqual(seen, ["总量控制"])
        view._pan_next_name = ""
        view._on_pan_go_learn()
        self.assertEqual(seen, ["总量控制"], "no name → no emit")


class TestLearningSiteCapture(unittest.TestCase):
    """Capture at the learning site: ★/📝 in the lesson and reader (F1),
    focused reading (F2), chapter/topic group quiz (F3)."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    # -- F1: notes / favourites where the learning happens --------------------
    def test_teach_result_offers_note_and_favorite(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from expert_anything.core.i18n import t as _t
        from expert_anything.core.learner import (
            get_note,
            is_favorite,
            save as save_learner,
            set_note,
        )

        asset = self.win.get_asset()
        c = asset.concepts[0]
        old_note = get_note(self.win.learner, c.name)
        old_fav = is_favorite(self.win.learner, c.name)
        self.win.on_nav_click("teach")
        set_note(self.win.learner, c.name, "我的理解")
        save_learner(self.win.learner)
        try:
            self.win._display_teach_result(
                {
                    "concept": c.name,
                    "style": "例子",
                    "explanation": "x",
                    "example": "",
                    "steps": [],
                    "practice": "",
                    "evidence": [],
                }
            )
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            view = self.win._teach_view._teach_view_widget
            star = view.findChild(QPushButton, "teach_fav_btn")
            note = view.findChild(QPushButton, "teach_note_btn")
            self.assertIsNotNone(star)
            self.assertIsNotNone(note)
            self.assertEqual(note.text(), _t("note_edit_has"))
            # the star toggles the bookmark straight into learner state
            star.click()
            self.assertNotEqual(is_favorite(self.win.learner, c.name), old_fav)
        finally:
            set_note(self.win.learner, c.name, old_note)
            if is_favorite(self.win.learner, c.name) != old_fav:
                from expert_anything.core.learner import toggle_favorite

                toggle_favorite(self.win.learner, c.name)
            save_learner(self.win.learner)

    def test_reader_toolbar_note_and_favorite(self):
        from PySide6.QtWidgets import QApplication, QComboBox
        from expert_anything.core.learner import (
            is_favorite,
            save as save_learner,
            toggle_favorite,
        )

        self.win.content_stack.setCurrentIndex(3)
        QApplication.processEvents()
        view = self.win._source_view
        combo = view.findChild(QComboBox, "reader_concept_combo")
        star = view.findChild(QPushButton, "reader_fav_btn")
        note = view.findChild(QPushButton, "reader_note_btn")
        focus = view.findChild(QPushButton, "reader_focus_btn")
        for w in (combo, star, note, focus):
            self.assertIsNotNone(w)
        self.assertFalse(star.isEnabled(), "nothing picked yet → disabled")
        combo.setCurrentIndex(1)
        name = combo.currentText()
        self.assertTrue(star.isEnabled())
        before = is_favorite(self.win.learner, name)
        star.click()
        self.assertNotEqual(is_favorite(self.win.learner, name), before)
        # the 🔍 button drives the reader into focused reading and back
        from expert_anything.core.i18n import t as _t

        focus.click()
        QApplication.processEvents()
        self.assertIn(_t("focus_exit_btn"), view._source_widget.toPlainText())
        focus.click()
        QApplication.processEvents()
        self.assertNotIn(_t("focus_exit_btn"), view._source_widget.toPlainText())
        # restore the demo state so later tests see the original bookmark set
        if is_favorite(self.win.learner, name) != before:
            toggle_favorite(self.win.learner, name)
        save_learner(self.win.learner)

    # -- F2: focused reading (deterministic projection) -----------------------
    def test_focus_reading_projects_matching_lines(self):
        from PySide6.QtWidgets import QApplication
        from expert_anything.core.i18n import t as _t

        self.win.content_stack.setCurrentIndex(3)
        QApplication.processEvents()
        sv = self.win._source_view_widget
        asset = self.win.get_asset()
        text = (asset.source_text or "").lower()
        target = next(
            (c for c in asset.concepts if len(c.name) >= 2 and c.name.lower() in text),
            None,
        )
        self.assertIsNotNone(target, "demo source should mention a concept verbatim")
        full_len = len(sv.toPlainText())
        sv.set_focus_concept(target.id)
        QApplication.processEvents()
        plain = sv.toPlainText()
        self.assertIn(target.name, plain)
        self.assertIn(_t("focus_exit_btn"), plain)  # card rendered
        self.assertLess(len(plain), full_len, "projection drops unrelated lines")
        # leaving focus restores the full text
        sv.set_focus_concept(None)
        QApplication.processEvents()
        self.assertNotIn(_t("focus_exit_btn"), sv.toPlainText())

    def test_focus_reading_falls_back_when_never_mentioned(self):
        from PySide6.QtWidgets import QApplication
        from expert_anything.core.i18n import t as _t

        self.win.content_stack.setCurrentIndex(3)
        QApplication.processEvents()
        sv = self.win._source_view_widget
        asset = self.win.get_asset()
        c = asset.concepts[-1]
        old_name, old_ev = c.name, list(c.evidence or [])
        c.name, c.evidence = "ZZZ不存在于原文ZZZ", []
        try:
            sv.set_focus_concept(c.id)
            QApplication.processEvents()
            self.assertIn(_t("focus_no_match"), sv.toPlainText())
        finally:
            c.name, c.evidence = old_name, old_ev
            sv.set_focus_concept(None)

    # -- F3: chapter / topic group quiz --------------------------------------
    def test_group_quiz_entry_buttons(self):
        self.win.content_stack.setCurrentIndex(1)
        kv = self.win._knowledge_view
        topic_btns = [
            b for b in kv.findChildren(QPushButton) if b.objectName() == "topic_quiz_btn"
        ]
        chapter_btns = [
            b
            for b in kv._toc_tree.findChildren(QPushButton)
            if b.objectName() == "chapter_quiz_btn"
        ]
        self.assertTrue(topic_btns, "topic cards need a group-quiz entry")
        self.assertTrue(chapter_btns, "chapter rows need a group-quiz entry")
        # Detach main's real handler first: in the app it opens a modal dialog,
        # which would block a headless test. Re-attach in the finally block.
        try:
            kv.group_quiz_requested.disconnect(self.win._on_group_quiz_request)
        except (RuntimeError, TypeError):
            pass
        seen = []
        kv.group_quiz_requested.connect(lambda ids, nm: seen.append((ids, nm)))
        try:
            topic_btns[0].click()
        finally:
            kv.group_quiz_requested.connect(self.win._on_group_quiz_request)
        self.assertTrue(seen and seen[0][0] and seen[0][1])

    def test_group_quiz_scores_and_records_per_concept(self):
        import copy
        import types

        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from expert_anything.core.i18n import t as _t
        from expert_anything.ui.widgets.group_quiz import GroupQuizDialog

        asset = self.win.get_asset()
        ids = [c.id for c in asset.concepts[:2]]
        state = copy.deepcopy(self.win.learner)
        state["history"] = []
        fake = types.SimpleNamespace(
            learner=state,
            current_asset_id=asset.asset_id,
            llm_client=None,  # deterministic fallback quizzes
            save_learner_state=lambda: None,
        )
        dlg = GroupQuizDialog(fake, asset, ids, "综合", None)
        self.addCleanup(dlg.deleteLater)
        self.assertIsNotNone(dlg._worker)
        dlg._worker.wait(15000)
        QApplication.processEvents()
        self.assertEqual(len(dlg._items), len(ids))

        for i in range(len(dlg._items)):
            quiz = dlg._quiz  # already rendered by _on_ready / _next_question
            self.assertIsNotNone(quiz)
            if quiz.get("type") == "true_false":
                dlg._check(quiz.get("correct"))
            else:
                dlg._check(list(quiz.get("correct_order", [])))
            if i + 1 < len(dlg._items):
                dlg._next_question()
        dlg._next_question()  # past the last item → summary

        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(len(dlg._scores), len(ids))
        self.assertTrue(all(s >= 0.6 for _n, s in dlg._scores))
        self.assertEqual(dlg._status.text(), _t("group_quiz_summary_title"))
        self.assertIsNotNone(dlg.findChild(QFrame, "group_quiz_summary"))
        # every answer was recorded through the existing quiz channel
        self.assertEqual(len(state["history"]), len(ids))
        for rec in state["history"]:
            self.assertEqual((rec.get("meta") or {}).get("channel"), "quiz")


class TestRound10Drilldowns(unittest.TestCase):
    """Round 10 — dead ends removed: panorama statistic chips drill down
    (C1), the concept card shows what it unlocks (C2), and notes written at
    the learning site can be read back through the TOC filter (C3)."""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    # -- C1: scale chips are clickable -----------------------------------------
    def test_scale_chips_drill_down(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from expert_anything.ui.views.panorama_view import _ScaleChip

        self.win.on_nav_click("panorama")
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        pv = self.win._panorama_view
        chips = pv.findChildren(_ScaleChip)
        self.assertEqual(len(chips), 5)
        for chip in chips:
            self.assertTrue(chip.toolTip(), "a clickable chip must say what it does")

        seen = []
        pv.view_switch_requested.connect(seen.append)
        chips[1].click()  # concepts (unique)
        chips[2].click()  # relations
        self.assertEqual(seen, ["concept_map", "concept_map"])
        # the scroll-to-card chips must not raise (they move the viewport)
        chips[0].click()
        chips[4].click()

    def test_shared_concepts_list_matches_count(self):
        self.win.on_nav_click("panorama")
        pv = self.win._panorama_view
        data = pv._collect()
        self.assertEqual(data["shared"], len(data["shared_list"]))
        for it in data["shared_list"]:
            self.assertGreaterEqual(len(it["assets"]), 2)

        seen = []
        pv.concept_jump_requested.connect(lambda a, n: seen.append((a, n)))

        class _Dlg:
            def __init__(self):
                self.accepted = False

            def accept(self):
                self.accepted = True

        name = data["shared_list"][0]["name"] if data["shared_list"] else "X"
        dlg = _Dlg()
        pv._jump_and_close(dlg, "asset-1", name)
        self.assertTrue(dlg.accepted, "drilling into a shared concept closes its list")
        self.assertEqual(seen, [("asset-1", name)])

    # -- C2: what does this concept unlock -------------------------------------
    def test_card_shows_unlocks(self):
        from PySide6.QtWidgets import QLabel, QPushButton
        from expert_anything.ui.widgets import NodeDetailCard
        from expert_anything.core.decoder import classify_relation
        from expert_anything.core.i18n import t as _t

        asset = self.win.get_asset()
        src, expect = None, None
        for r in asset.relations or []:
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            if sem not in ("prereq", "causes"):
                continue
            a, b = asset.concept_by_id(r.source), asset.concept_by_id(r.target)
            if a is not None and b is not None and r.source != r.target:
                src, expect = a.id, b.name
                break
        if src is None:
            self.skipTest("demo asset has no prereq/causes edge")

        card = NodeDetailCard()
        card.set_concept(asset, src, self.win.learner)
        texts = [b.text() for b in card.findChildren(QPushButton)]
        self.assertTrue(
            any(expect in txt for txt in texts),
            f"unlocked concept {expect} missing from the card",
        )
        labels = [lbl.text() for lbl in card.findChildren(QLabel)]
        self.assertTrue(any(_t("unlock_title") in lbl for lbl in labels))
        # the intro counts exactly the concepts this one unlocks
        targets: list[str] = []
        for r in asset.relations or []:
            if r.source != src:
                continue
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            if sem in ("prereq", "causes") and r.target not in targets and asset.concept_by_id(r.target):
                targets.append(r.target)
        self.assertTrue(
            any(_t("unlock_intro", n=len(targets)) in lbl for lbl in labels)
        )
        card.close()

    # -- C3: notes are readable again -------------------------------------------
    def test_toc_rows_keep_their_caption(self):
        """Regression: a plain int role 2 payload lands in the display slot in
        PySide6, which wiped every row caption and left the chapter TOC blank."""
        from PySide6.QtWidgets import QApplication
        from expert_anything.ui.views.knowledge_view import (
            KnowledgeView,
            _ROLE_PAYLOAD,
        )

        view = KnowledgeView(self.win)
        self.addCleanup(view.deleteLater)
        QApplication.processEvents()
        tree = view._toc_tree
        asset = self.win.get_asset()
        rows = []
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for j in range(top.childCount()):
                ch = top.child(j)
                payload = ch.data(0, _ROLE_PAYLOAD)
                if payload and payload[0] == "concept":
                    rows.append((ch.text(0), payload[1]))
        self.assertTrue(rows, "the chapter TOC must list concept rows")
        for caption, cid in rows:
            self.assertTrue(caption.strip(), "TOC row rendered blank (role clash)")
            self.assertIn("]", caption)
            self.assertIsNotNone(asset.concept_by_id(cid))

    def test_toc_note_filter_shows_note_inline(self):
        from PySide6.QtWidgets import QApplication
        from expert_anything.ui.views.knowledge_view import KnowledgeView
        from expert_anything.core.i18n import t as _t
        from expert_anything.core.learner import (
            get_note,
            save as save_learner,
            set_note,
        )

        asset = self.win.get_asset()
        c = asset.concepts[0]
        old = get_note(self.win.learner, c.name)
        set_note(self.win.learner, c.name, "费曼：用自己的话讲一遍才算真懂")
        save_learner(self.win.learner)
        try:
            view = KnowledgeView(self.win)
            self.addCleanup(view.deleteLater)
            QApplication.processEvents()
            idx = view._mastery_filter.findText(_t("filter_note"))
            self.assertGreaterEqual(idx, 0, "the note filter must exist")
            view._mastery_filter.setCurrentIndex(idx)

            tree = view._toc_tree
            noted, visible = None, []
            for i in range(tree.topLevelItemCount()):
                top = tree.topLevelItem(i)
                for j in range(top.childCount()):
                    ch = top.child(j)
                    if ch.isHidden():
                        continue
                    visible.append(ch.text(0))
                    noted = ch
            self.assertEqual(len(visible), 1, "only the noted concept may remain")
            self.assertIn("费曼", noted.text(0))
            self.assertIn("📝", noted.text(0))

            # clearing the filter restores the plain caption (no leftovers)
            view._mastery_filter.setCurrentIndex(0)
            self.assertNotIn("费曼", noted.text(0))
        finally:
            set_note(self.win.learner, c.name, old)
            save_learner(self.win.learner)


class TestRound21BeginnerSimplify(unittest.TestCase):
    """Round 21 — 小白视角减负：侧边栏只留 4 个核心入口、地图工具栏首行
    收敛到 6 个控件以内、详情卡首屏折叠、首次进入地图给一条可关闭提示。"""

    @classmethod
    def setUpClass(cls):
        cls.win = load_main_window()
        cls.win.show()

    def test_sidebar_pins_only_four_core_entries(self):
        core = ["concept_map", "teach", "import", "source"]
        for view in core:
            self.assertTrue(
                self.win._nav_buttons[view].isVisible(),
                f"core entry {view} must stay on the first screen",
            )
        # 进阶入口（教师模型等）默认折叠在「进阶功能」里
        for view in ("teacher", "panorama", "learner", "knowledge"):
            self.assertFalse(
                self.win._nav_buttons[view].isVisible(),
                f"advanced entry {view} must be folded away by default",
            )

    def test_nav_labels_do_not_double_up_emoji(self):
        # i18n 文案本身自带 emoji，代码再拼一个就会出现「📊 🌳 ...」
        for view, btn in self.win._nav_buttons.items():
            self.assertNotIn(
                "  ",
                btn.text(),
                f"nav button {view} renders a doubled icon:{btn.text()!r}",
            )

    def test_map_first_row_stays_compact(self):
        self.win.on_nav_click("concept_map")
        view = self.win._concept_map_view
        toolbar_widget = view._content_layout.itemAt(0).widget()
        self.assertIsNotNone(toolbar_widget)
        count = toolbar_widget.layout().count()
        self.assertLessEqual(
            count, 6, f"first toolbar row must stay <=6 controls, got {count}"
        )
        # 范围切换等进阶控件已收进「更多工具」
        self.assertFalse(view._more_row.isVisible())
        self.assertIn(view._scope_combo, view._more_row.findChildren(QWidget))

    def test_onboarding_bar_is_shown_at_most_once(self):
        view = self.win._concept_map_view
        view.refresh()
        view.refresh()
        bars = view.findChildren(QWidget, "cm_onboarding_bar")
        self.assertLessEqual(
            len(bars), 1, "refresh must never stack duplicate onboarding bars"
        )

    def test_detail_card_first_screen_is_folded(self):
        view = self.win._concept_map_view
        asset = view._global_asset
        self.assertIsNotNone(asset)
        card = view._map_detail
        card.set_concept(asset, asset.concepts[0].id, self.win.learner, None)
        sections = card.findChildren(CollapsibleSection)
        self.assertGreaterEqual(
            len(sections), 3, "secondary detail blocks must live behind folds"
        )
        for sec in sections:
            self.assertFalse(
                sec.is_expanded(), "folds start collapsed to keep the first screen quiet"
            )
        # 折叠只是收起，不是删除：内容仍在折叠体里
        self.assertGreater(
            sum(sec.body_layout().count() for sec in sections),
            0,
            "collapsed sections must still carry their content",
        )

