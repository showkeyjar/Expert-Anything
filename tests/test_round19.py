# -*- coding: utf-8 -*-
"""Round 19 tests: dead-public cleanup round 2, resolved-anomaly visibility
on the teacher board, and the coach explore edge state (guide bar + routing)."""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo  # noqa: E402

ensure_demo()

from expert_anything.core.learner import normalize  # noqa: E402
from expert_anything.core.models import Concept, KnowledgeAsset  # noqa: E402

try:
    from PySide6.QtWidgets import QLabel, QPushButton
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


def _asset(mastery_name="节点电价") -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_id="a1",
        type="article",
        title="测试教材",
        source_name="",
        created_at="",
        source_text="节点电价是本文的核心概念。",
        chapters=[],
        concepts=[
            Concept(
                id="c1",
                name=mastery_name,
                definition="反映供需的边际价格",
                evidence=["节点电价是本文的核心概念。"],
                locations=[],
            )
        ],
        relations=[],
        learning_path=["c1"],
        method="test",
        source_length=0,
    )


class TestDeadPublicsGone(unittest.TestCase):
    """Round 19 deletions stay deleted; the live neighbours stay intact."""

    def test_llm_cache_clear_gone(self):
        from expert_anything.core import llm

        self.assertFalse(hasattr(llm, "clear_llm_cache"))

    def test_parsers_base64_gone(self):
        from expert_anything.core import parsers

        self.assertFalse(hasattr(parsers, "extract_from_base64"))
        self.assertTrue(callable(parsers.extract_from_bytes))

    def test_learner_goal_accessor_gone(self):
        from expert_anything.core import learner

        self.assertFalse(hasattr(learner, "get_study_goal"))
        self.assertTrue(callable(learner.set_study_goal))
        self.assertTrue(callable(learner.study_goal_progress))

    def test_i18n_dead_helpers_gone(self):
        from expert_anything.core import i18n

        self.assertFalse(hasattr(i18n, "init_lang"))
        self.assertFalse(hasattr(i18n, "translate_option"))
        for live in ("t", "get_lang", "set_lang", "save_lang"):
            self.assertTrue(callable(getattr(i18n, live)), live)

    def test_domain_template_chapter_lookup_gone(self):
        from expert_anything.core.domain_templates import DomainTemplate

        self.assertFalse(hasattr(DomainTemplate, "get_chapter_by_id"))
        self.assertTrue(hasattr(DomainTemplate, "get_concept_by_id"))

    @unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
    def test_view_manager_dead_surface_gone(self):
        from expert_anything.ui.view_manager import ViewManager

        for name in (
            "set_current",
            "current_name",
            "current_index",
            "refresh_current",
            "navigate_to",
            "teach_requested",
        ):
            self.assertFalse(hasattr(ViewManager, name), f"dead API: {name}")
        self.assertTrue(hasattr(ViewManager, "register_views"))
        self.assertTrue(hasattr(ViewManager, "navigate_requested"))

    @unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
    def test_widget_dead_methods_gone(self):
        # trend_chart lives inside ui.widgets — importing it first lets the
        # package __init__ finish before pyside_widgets pulls _helpers
        # (otherwise the two modules deadlock in a circular import).
        from expert_anything.ui.widgets.trend_chart import MasteryDistributionBar
        from expert_anything.ui.pyside_widgets import SourceTextView

        self.assertFalse(hasattr(SourceTextView, "scroll_to_text"))
        self.assertFalse(hasattr(MasteryDistributionBar, "set_counts"))


class TestCoachExploreEdge(unittest.TestCase):
    """All-mastered fallback: the coach lowers its voice, never disappears."""

    def test_select_empty_candidates_yields_explore(self):
        from expert_anything.core.coach import _select

        rec = _select([], {})
        self.assertEqual(rec.get("kind"), "explore")
        self.assertEqual(rec.get("why_key"), "coach_why_explore")
        self.assertFalse(rec.get("concept_name"))

    def test_recommend_all_mastered_falls_back_to_explore(self):
        from expert_anything.core.coach import recommend

        asset = _asset()
        state = {
            "concepts": {
                normalize("节点电价"): {"name": "节点电价", "mastery": 1.0}
            }
        }
        rec = recommend(asset, state, None)
        self.assertEqual(
            rec.get("kind"),
            "explore",
            f"nothing left to teach must yield explore, got {rec.get('kind')}",
        )


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound19UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.app = load_main_window()

    def _flush(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    # -- candidate 3: guide bar renders the explore claim ----------------------
    def test_guide_bar_shows_explore_and_import(self):
        from expert_anything.ui.widgets.guide_bar import GuideBar

        bar = GuideBar()
        self.addCleanup(bar.deleteLater)

        bar.set_recommendation({"kind": "explore", "why_key": "coach_why_explore"})
        self.assertFalse(bar.isHidden(), "explore claim must be visible")
        self.assertEqual(bar.current().get("kind"), "explore")

        bar.set_recommendation({"kind": "import", "why_key": "coach_why_import"})
        self.assertFalse(bar.isHidden(), "import claim must stay visible")

        bar.set_recommendation({"kind": "review"})  # nameless non-asset kind
        self.assertTrue(bar.isHidden(), "nameless concept-kind must stay hidden")

    # -- candidate 3: start routes by kind -------------------------------------
    def test_guide_start_routes_by_kind(self):
        app = self.app
        learner_snapshot = copy.deepcopy(app.learner)
        prev_index = app.content_stack.currentIndex()

        def _restore():
            app.learner = learner_snapshot
            app.content_stack.setCurrentIndex(prev_index)

        self.addCleanup(_restore)

        with patch.object(app, "save_learner_state"):
            app._on_guide_start({"kind": "explore", "why_key": "coach_why_explore"})
            self.assertEqual(
                app.content_stack.currentIndex(),
                2,  # VIEW_MAP
                "explore must land on the concept map, not the import view",
            )
            app._on_guide_start({"kind": "import", "why_key": "coach_why_import"})
            self.assertEqual(app.content_stack.currentIndex(), 0)  # VIEW_IMPORT

    # -- candidate 2: resolved anomalies render as a separate section ----------
    def test_teacher_board_splits_resolved(self):
        from expert_anything.core.i18n import t as _t

        app = self.app
        aid = app.current_asset_id
        self.assertIsNotNone(aid, "demo window must have a current asset")
        asset = app.get_asset()
        concept = asset.concepts[0]

        snapshot = copy.deepcopy(app.teacher_models)
        self.addCleanup(setattr, app, "teacher_models", snapshot)
        self.addCleanup(app.teacher_view.refresh)

        app.teacher_models[aid] = {
            "status": "done",
            "method": "test",
            "synthesized_at": "",
            "concept_notes": [],
            "anomalies": [
                {
                    "id": "o1",
                    "kind": "contradiction",
                    "description": f"材料自相矛盾，涉及 {concept.name}",
                    "location": concept.name,
                    "severity": "high",
                    "status": "open",
                    "source": "internal",
                },
                {
                    "id": "r1",
                    "kind": "learner_gap",
                    "description": f"掌握薄弱：{concept.name}",
                    "location": concept.name,
                    "severity": "medium",
                    "status": "resolved",
                    "source": "internal",
                },
                {
                    "id": "r2",
                    "kind": "unanchored_source",
                    "description": f"无原文锚点：{concept.name}",
                    "location": concept.name,
                    "severity": "low",
                    "status": "resolved",
                    "source": "internal",
                },
            ],
        }
        app.teacher_view.refresh()
        self._flush()

        teach_btns = app.teacher_view.findChildren(QPushButton, "anomaly_teach_btn")
        self.assertEqual(
            len(teach_btns), 1, "only the open anomaly keeps an action button"
        )

        texts = [l.text() for l in app.teacher_view.findChildren(QLabel)]
        joined = "\n".join(texts)
        self.assertIn(_t("teacher_resolved_label", n=2), joined)
        self.assertTrue(
            any(_t("teacher_resolved_badge") in s for s in texts),
            "resolved cards must carry the resolved badge",
        )
        self.assertIn(_t("teacher_resolved_reason_mastery"), joined)
        self.assertIn(_t("teacher_resolved_reason_anchor"), joined)

    def test_teacher_board_without_resolved_hides_section(self):
        from expert_anything.core.i18n import t as _t

        app = self.app
        aid = app.current_asset_id
        asset = app.get_asset()
        concept = asset.concepts[0]

        snapshot = copy.deepcopy(app.teacher_models)
        self.addCleanup(setattr, app, "teacher_models", snapshot)
        self.addCleanup(app.teacher_view.refresh)

        app.teacher_models[aid] = {
            "status": "done",
            "method": "test",
            "synthesized_at": "",
            "concept_notes": [],
            "anomalies": [
                {
                    "id": "o1",
                    "kind": "contradiction",
                    "description": f"材料自相矛盾，涉及 {concept.name}",
                    "location": concept.name,
                    "severity": "high",
                    "status": "open",
                    "source": "internal",
                }
            ],
        }
        app.teacher_view.refresh()
        self._flush()

        texts = [l.text() for l in app.teacher_view.findChildren(QLabel)]
        self.assertNotIn(_t("teacher_resolved_badge"), texts)
        self.assertFalse(
            any(s.startswith(_t("teacher_resolved_label", n=1)[:6]) for s in texts),
            "no resolved section when nothing is resolved",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
