# -*- coding: utf-8 -*-
"""Round 17 tests: asset deletion entry, dead-signal cleanup, unified
localized anomaly-kind labels."""
import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo  # noqa: E402

ensure_demo()

from expert_anything.core.i18n import get_lang, set_lang  # noqa: E402
from expert_anything.core.teacher import kind_label  # noqa: E402

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


class TestKindLabel(unittest.TestCase):
    """One i18n-aware mapping for every anomaly-kind surface."""

    def setUp(self):
        self._lang = get_lang()
        self.addCleanup(set_lang, self._lang)

    def test_follows_ui_language(self):
        set_lang("zh-CN")
        self.assertEqual(kind_label("contradiction"), "矛盾")
        set_lang("en")
        self.assertEqual(kind_label("contradiction"), "Contradiction")
        set_lang("ja")
        self.assertEqual(kind_label("contradiction"), "矛盾")

    def test_unknown_kind_falls_back_to_code(self):
        set_lang("en")
        self.assertEqual(
            kind_label("brand_new_kind"),
            "brand_new_kind",
            "an unmapped kind must stay readable as its own code",
        )

    def test_all_known_kinds_have_labels(self):
        for kind in (
            "contradiction",
            "undefined_term",
            "logical_gap",
            "surprising_claim",
            "learner_gap",
            "needs_llm",
            "unanchored_source",
        ):
            self.assertNotEqual(kind_label(kind), kind, f"missing label: {kind}")


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound17UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.app = load_main_window()

    def _flush(self):
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _answer_delete_dialog(self, button):
        old = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: button)
        self.addCleanup(setattr, QMessageBox, "question", old)

    # -- candidate 2: dead signals removed ------------------------------------
    def test_dead_signals_removed(self):
        from expert_anything.ui.pyside_graph import KnowledgeGraphView
        from expert_anything.ui.view_manager import ViewManager
        from expert_anything.ui.views.import_view import ImportView
        from expert_anything.ui.widgets.group_quiz import GroupQuizDialog

        self.assertFalse(hasattr(ImportView, "asset_selected"))
        self.assertFalse(hasattr(GroupQuizDialog, "completed"))
        self.assertFalse(hasattr(KnowledgeGraphView, "view_changed"))
        for name in (
            "concept_panel_requested",
            "focus_graph_requested",
            "refresh_requested",
        ):
            self.assertFalse(hasattr(ViewManager, name), f"dead signal: {name}")

    # -- candidate 1: asset deletion -------------------------------------------
    def test_delete_button_present_per_asset(self):
        self.app._refresh_asset_list()
        self._flush()
        for aid in self.app.assets:
            btn = self.app.findChild(QPushButton, f"asset_delete_{aid}")
            self.assertIsNotNone(btn, f"delete button missing for {aid}")
            self.assertTrue(btn.toolTip(), "delete button needs a tooltip")

    def test_delete_asset_full_cleanup(self):
        import copy
        from unittest.mock import patch

        app = self.app
        aid = sorted(app.assets)[-1]
        title = app.assets[aid].get("title") or aid
        other = sorted(app.assets)[0]
        app.current_asset_id = aid

        # seed learner traces for the deleted asset
        app.learner.setdefault("assets", {})[aid] = {"learning_path": ["x"]}
        app.learner.setdefault("concepts", {})["tmp::c"] = {
            "sources": [aid],
            "mastery": 0.5,
        }

        snapshot = (
            copy.deepcopy(app.assets),
            copy.deepcopy(app.teacher_models),
            copy.deepcopy(app.learner),
            app.current_asset_id,
        )

        def _restore():
            app.assets, app.teacher_models, app.learner, app.current_asset_id = (
                snapshot[0],
                snapshot[1],
                snapshot[2],
                snapshot[3],
            )
            app._rebuild_all_views()

        self.addCleanup(_restore)

        self._answer_delete_dialog(QMessageBox.StandardButton.Yes)
        deleted = []
        with patch("main.delete_asset", lambda a: deleted.append(a)):
            app._on_delete_asset(aid)

        self.assertEqual(deleted, [aid], "storage.delete_asset must be called")
        self.assertNotIn(aid, app.assets)
        self.assertNotIn(aid, app.teacher_models)
        self.assertNotIn(aid, app.learner.get("assets", {}))
        self.assertNotIn(
            "tmp::c",
            app.learner.get("concepts", {}),
            "concepts whose only source was deleted must be purged",
        )
        self.assertEqual(
            app.current_asset_id,
            other,
            "deleting the current asset must move selection to a survivor",
        )

    def test_delete_cancel_keeps_everything(self):
        app = self.app
        aid = sorted(app.assets)[0]
        before_assets = set(app.assets)
        # prepare_app() answers "No" by default; make that explicit here.
        self._answer_delete_dialog(QMessageBox.StandardButton.No)
        app._on_delete_asset(aid)
        self.assertIn(aid, app.assets, "a cancelled delete must change nothing")
        self.assertEqual(set(app.assets), before_assets)

    def test_delete_unknown_asset_is_noop(self):
        app = self.app
        before = set(app.assets)
        app._on_delete_asset("no-such-asset")
        self.assertEqual(set(app.assets), before)

    # -- candidate 3: views render through the unified label -------------------
    def test_teacher_view_uses_unified_kind_label(self):
        from PySide6.QtWidgets import QLabel

        from expert_anything.core.i18n import t as _t

        app = self.app
        app.on_nav_click("teacher")
        QApplication.processEvents()
        self._flush()
        # demo teacher anomalies are needs_llm: the badge must carry the
        # localized unified label, not a hardcoded string.
        texts = [w.text() for w in app._teacher_view.findChildren(QLabel)]
        expected = _t("kind_needs_llm")
        self.assertTrue(
            any(expected in txt for txt in texts),
            f"teacher view must show '{expected}'; got {texts[:8]}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
