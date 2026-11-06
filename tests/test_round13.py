# -*- coding: utf-8 -*-
"""Round 13 tests: recall evidence joins the learning trace, the teacher's
learner signals become visible, and mastery gains a per-channel breakdown.
"""
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

try:
    from PySide6.QtWidgets import QLabel, QPushButton
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


def _row(name: str, score: float, channel: str | None = None, review: bool = False):
    meta = {}
    if channel:
        meta["channel"] = channel
    if review:
        meta["review"] = True
    row = {
        "concept": name,
        "key": learner.normalize(name),
        "asset_id": "a-test",
        "score": score,
        "answer": "",
        "feedback": "",
        "at": "",
    }
    if meta:
        row["meta"] = meta
    return row


def _state(rows):
    return {"concepts": {}, "history": rows}


class TestRecallEvidence(unittest.TestCase):
    """``channel="recall"`` is mastery evidence, not teaching evidence."""

    def test_is_recall_record(self):
        self.assertTrue(
            learner.is_recall_record(_row("A", 0.5, learner.RECALL_CHANNEL))
        )
        self.assertFalse(learner.is_recall_record(_row("A", 0.5, "quiz")))
        self.assertFalse(learner.is_recall_record(_row("A", 0.5)))

    def test_recall_never_fires_stuck(self):
        state = _state(
            [_row("A", 0.2, learner.RECALL_CHANNEL) for _ in range(4)]
        )
        self.assertEqual(learner.stuck_concepts(state), [])
        state2 = _state([_row("A", 0.2, "answer") for _ in range(4)])
        self.assertTrue(
            any(s["name"] == "A" for s in learner.stuck_concepts(state2))
        )

    def test_recall_not_a_teaching_style(self):
        state = _state([_row("A", 0.9, learner.RECALL_CHANNEL)])
        self.assertNotIn("recall", learner.style_effectiveness(state))

    def test_mastery_prediction_ignores_recall(self):
        state = _state(
            [_row("A", 0.1, learner.RECALL_CHANNEL) for _ in range(3)]
        )
        self.assertEqual(learner.mastery_prediction(state, "A")["trend"], "unknown")

    def test_score_trail_marks_recall_rows(self):
        state = _state(
            [
                _row("A", 0.9, learner.RECALL_CHANNEL),
                _row("A", 0.5, "answer"),
            ]
        )
        trail = learner.score_trail(state, "A")
        self.assertEqual(len(trail), 2)
        self.assertFalse(trail[0]["recall"])  # older answer row
        self.assertTrue(trail[1]["recall"])  # newest recall row


class TestMasteryBreakdown(unittest.TestCase):
    """Per-channel projection of the learning trace."""

    def test_groups_by_channel_in_canonical_order(self):
        state = _state(
            [
                _row("A", 0.7, "quiz"),
                _row("A", 0.8, "quiz"),
                _row("A", 0.5, "practice"),
                _row("A", 0.6),  # legacy row → answer
                _row("A", 0.9, learner.RECALL_CHANNEL),
            ]
        )
        rows = learner.mastery_breakdown(state, "A")
        self.assertEqual(
            [r["channel"] for r in rows], ["answer", "quiz", "practice", "recall"]
        )
        quiz = next(r for r in rows if r["channel"] == "quiz")
        self.assertEqual(quiz["count"], 2)
        self.assertAlmostEqual(quiz["avg"], 0.75, places=2)
        self.assertAlmostEqual(quiz["last_score"], 0.7, places=2)

    def test_other_concepts_are_ignored(self):
        state = _state([_row("A", 0.4, "quiz"), _row("B", 0.9, "quiz")])
        rows = learner.mastery_breakdown(state, "A")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 1)

    def test_empty_history_is_silent(self):
        self.assertEqual(learner.mastery_breakdown(_state([]), "A"), [])


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound13UI(unittest.TestCase):
    def setUp(self):
        from tests.util import prepare_app

        prepare_app()

    def _concept(self):
        from expert_anything.core.models import Concept

        return Concept(
            id="c1",
            name="节点边际电价(LMP)",
            definition="节点边际电价是反映电力供需的边际价格",
            evidence=[
                "- 节点边际电价(LMP)：节点边际电价是反映电力供需的边际价格，由供需共同决定"
            ],
        )

    def test_feynman_record_writes_learning_trace(self):
        from expert_anything.ui.widgets.feynman import FeynmanDialog

        class _Asset:
            asset_id = "a-test"
            title = "电力现货市场"

        asset = _Asset()
        state = {"concepts": {}, "history": [], "assets": {}}
        dlg = FeynmanDialog(asset, self._concept(), state)
        dlg._editor.setPlainText(
            "节点边际电价(LMP)就是反映电力供需的边际价格，由供需共同决定"
        )
        dlg._on_check()
        btn = dlg.findChild(QPushButton, "recall_record_btn")
        self.assertIsNotNone(btn)
        btn.click()

        self.assertEqual(len(state["history"]), 1)
        row = state["history"][0]
        self.assertEqual(row["meta"]["channel"], learner.RECALL_CHANNEL)
        self.assertEqual(row["asset_id"], "a-test")
        self.assertGreater(row["score"], 0.9)
        rec = state["concepts"][learner.normalize("节点边际电价(LMP)")]
        self.assertGreater(rec["mastery"], 0.3)
        self.assertFalse(btn.isEnabled())
        dlg.deleteLater()

    def test_card_shows_breakdown_and_recall_status(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        self.assertIsNotNone(asset)
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        state = _state(
            [
                _row(concept.name, 0.8, "quiz"),
                _row(concept.name, 0.5, "answer"),
                _row(
                    concept.name,
                    0.4,
                    learner.RECALL_CHANNEL,
                ),
            ]
        )
        # the recall row needs a real answer for the deterministic gap recompute
        state["history"][0]["answer"] = "电价由供需决定"

        card = NodeDetailCard()
        card.set_concept(asset, concept.id, state, None)
        breakdown = card.findChild(QLabel, "mastery_breakdown_lbl")
        self.assertIsNotNone(breakdown, "card should explain where mastery came from")
        self.assertIn("自测", breakdown.text())
        recall_lbl = card.findChild(QLabel, "recall_status_lbl")
        self.assertIsNotNone(recall_lbl, "card should show last recall coverage")
        self.assertIn("复述", recall_lbl.text())
        self.assertIsNotNone(card.findChild(QPushButton, "recall_again_btn"))
        card.deleteLater()

    def test_card_shows_learner_signals_from_teacher(self):
        from expert_anything.core import teacher as teacher_mod
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        tm = teacher_mod.TeacherModel.from_dict(
            {
                "asset_id": "a20260908-002",
                "status": "done",
                "concept_notes": [
                    {
                        "concept_id": concept.id,
                        "name": concept.name,
                        "significance": "现货市场的核心定价机制",
                        "learner_signals": ["学习者追问:为什么节点电价会不同"],
                        "external_notes": ["补充：LMP 来源于最优潮流模型的对偶变量"],
                        "note": "系统综合理解",
                    }
                ],
            }
        )
        card = NodeDetailCard()
        card.set_concept(asset, concept.id, {"concepts": {}, "history": []}, tm)
        texts = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        self.assertIn("系统记住的你的困惑", texts)
        self.assertIn("为什么节点电价会不同", texts)
        self.assertIn("材料之外的补充", texts)
        self.assertIn("材料之外", texts)
        card.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
