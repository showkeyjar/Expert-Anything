# -*- coding: utf-8 -*-
"""Round 12 tests: feynman recall check, terminology tooltips, and the
renewable / distributed-energy demo assets.
"""
import json
import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo

ensure_demo()

from expert_anything.core import feynman  # noqa: E402
from expert_anything.core.models import Concept  # noqa: E402

try:
    from PySide6.QtWidgets import QPushButton, QLabel
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


class TestFeynmanCoverage(unittest.TestCase):
    """Deterministic explain-it-back coverage (no LLM)."""

    def _concept(self):
        return Concept(
            id="c1",
            name="节点边际电价(LMP)",
            definition="节点边际电价是反映电力供需的边际价格",
            evidence=[
                "- 节点边际电价(LMP)：节点边际电价是反映电力供需的边际价格，由供需共同决定"
            ],
        )

    def test_full_restatement_covers_all_points(self):
        res = feynman.coverage(
            "节点边际电价(LMP)就是反映电力供需的边际价格，它由供需共同决定",
            self._concept(),
            "electricity_trading",
        )
        self.assertEqual(res["coverage"], 1.0)
        self.assertEqual(res["missed_points"], [])
        self.assertTrue(res["self_mentioned"])
        self.assertEqual(res["self_name"], "节点边际电价(LMP)")

    def test_empty_text_covers_nothing(self):
        res = feynman.coverage("不知道", self._concept(), "electricity_trading")
        self.assertEqual(res["coverage"], 0.0)
        self.assertEqual(res["missed_points"], self._concept().evidence)
        self.assertFalse(res["self_mentioned"])

    def test_no_domain_still_uses_evidence(self):
        res = feynman.coverage(
            "节点边际电价是反映电力供需的边际价格",
            self._concept(),
            "",
        )
        self.assertGreaterEqual(res["coverage"], 0.4)
        self.assertEqual(res["self_name"], "节点边际电价(LMP)")

    def test_related_terms_surface(self):
        from expert_anything.core import terminology

        terms = terminology.iter_terms("electricity_trading")
        self.assertGreaterEqual(len(terms), 2, "template needs at least two terms")
        other = terms[1]
        concept = self._concept()
        concept.definition += f"，与{other.name}密切相关"
        res = feynman.coverage(
            "节点边际电价由供需共同决定",
            concept,
            "electricity_trading",
        )
        missed = [t["name"] for t in res["missed_terms"]]
        self.assertIn(other.name, missed)


class TestDemoAssetsRound12(unittest.TestCase):
    """Renewable and distributed-energy demo assets exist and are wired."""

    def test_renewable_and_der_assets_present(self):
        demo = PROJECT / "data" / "_demo" / "assets"
        for stem in ("a20260908-004", "a20260908-005"):
            self.assertTrue((demo / f"{stem}.json").exists())
            self.assertTrue((demo / f"teacher_{stem}.json").exists())

    def test_learner_covers_all_four_assets(self):
        learner = json.loads(
            (PROJECT / "data" / "_demo" / "learner.json").read_text(encoding="utf-8")
        )
        for stem in ("a20260908-002", "a20260908-003", "a20260908-004", "a20260908-005"):
            self.assertIn(stem, learner.get("assets", {}))


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound12UI(unittest.TestCase):
    """UI wiring for the recall button and the terminology card section."""

    def setUp(self):
        from tests.util import load_main_window

        self.main = load_main_window()

    def tearDown(self):
        self.main.deleteLater()

    def test_source_view_has_recall_button(self):
        self.main.on_nav_click("source")
        btn = self.main.findChild(QPushButton, "reader_recall_btn")
        self.assertIsNotNone(btn, "reading view should expose a recall button")

    def test_node_detail_renders_terminology_section(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        self.assertIsNotNone(asset)
        card = NodeDetailCard()
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        card.set_concept(asset, concept.id, self.main.learner, None)
        labels = card.findChildren(QLabel)
        found = any(lbl.text() == "领域术语" for lbl in labels)
        self.assertTrue(
            found, "concept card should render the domain terminology section"
        )

    def test_pyside_widgets_highlight_includes_tooltip(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.pyside_widgets import SourceTextView

        asset = load_asset("a20260908-002")
        self.assertIsNotNone(asset)
        view = SourceTextView()
        view.set_asset(asset, self.main.learner)
        html = view._body_html(
            asset.source_text.split("\n"),
            view._compiled_concepts(),
            view._evidence_marks(),
        )
        self.assertIn("title=", html, "registered concept should carry a tooltip")
        self.assertIn("节点边际电价", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
