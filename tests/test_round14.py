# -*- coding: utf-8 -*-
"""Round 14 tests: anomaly board actions, error book answers, recall trends."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

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


def _recall(name: str, score: float):
    return {
        "concept": name,
        "key": learner.normalize(name),
        "asset_id": "a-test",
        "score": score,
        "answer": "",
        "feedback": "",
        "at": "",
        "meta": {"channel": learner.RECALL_CHANNEL},
    }


class TestRecallTrendCore(unittest.TestCase):
    def test_orders_old_to_new(self):
        state = {"concepts": {}, "history": [_recall("A", 0.8), _recall("A", 0.4)]}
        self.assertEqual(learner.recall_trend(state, "A"), [0.4, 0.8])

    def test_ignores_other_concepts_and_limit(self):
        state = {
            "concepts": {},
            "history": [
                _recall("A", 0.9),
                _recall("B", 0.2),
                _recall("A", 0.5),
                _recall("A", 0.3),
            ],
        }
        self.assertEqual(learner.recall_trend(state, "A", limit=2), [0.5, 0.9])

    def test_empty_history_is_silent(self):
        self.assertEqual(learner.recall_trend({"history": []}, "A"), [])


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound14UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.app = load_main_window()

    def test_anomaly_matching_prefers_longest_name(self):
        from expert_anything.ui.views.teacher_view import _match_anomaly_concept

        asset = SimpleNamespace(
            concepts=[
                SimpleNamespace(id="c1", name="电价"),
                SimpleNamespace(id="c2", name="节点边际电价"),
                SimpleNamespace(id="c3", name="负荷预测"),
            ]
        )
        hit = _match_anomaly_concept(
            asset, {"description": "「节点边际电价」缺少定义", "location": ""}
        )
        self.assertEqual(hit.id, "c2")
        self.assertIsNone(
            _match_anomaly_concept(asset, {"description": "无关描述", "location": ""})
        )

    def test_teacher_anomaly_board_offers_actions(self):
        from PySide6.QtWidgets import QApplication

        # demo teacher models only carry the needs_llm anomaly (no concept to
        # act on), so inject a concept-bound anomaly and rebuild the board
        aid = self.app.current_asset_id
        data = dict(self.app.teacher_models.get(aid) or {})
        data["anomalies"] = [
            {
                "kind": "contradiction",
                "severity": "high",
                "description": "「节点边际电价(LMP)」与文中的定义相互矛盾",
                "location": "第 1 章",
            }
        ]
        self.app.teacher_models[aid] = data
        self.app.teacher_view.refresh()
        QApplication.processEvents()
        btns = self.app.teacher_view.findChildren(QPushButton, "anomaly_view_btn")
        self.assertTrue(
            btns, "anomaly cards must offer 'view concept' — they are actionable"
        )
        teach_btns = self.app.teacher_view.findChildren(
            QPushButton, "anomaly_teach_btn"
        )
        self.assertTrue(teach_btns, "anomaly cards must offer 'learn it'")
        self.assertTrue(hasattr(self.app.teacher_view, "teach_requested"))

    def test_error_book_shows_learner_answer(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QApplication

        rows = [
            {
                "concept": "节点边际电价(LMP)",
                "score": 0.3,
                "answer": "我觉得电价就是政府定的价格",
                "feedback": "缺少供需与边际成本",
            }
        ]
        with patch(
            "expert_anything.core.learner.weak_history",
            return_value=rows,
        ):
            self.app.on_nav_click("learner")
            QApplication.processEvents()
        labels = self.app.learner_view.findChildren(
            QLabel, "error_book_answer_lbl"
        )
        self.assertTrue(labels, "error book must show what the learner actually wrote")
        self.assertIn("政府定的价格", labels[0].text())

    def test_card_shows_recall_trend_and_stagnation(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        state = {
            "concepts": {},
            "history": [
                _recall(concept.name, 0.45),
                _recall(concept.name, 0.44),
                _recall(concept.name, 0.46),
            ],
        }
        card = NodeDetailCard()
        card.set_concept(asset, concept.id, state, None)
        trend = card.findChild(QLabel, "recall_trend_lbl")
        self.assertIsNotNone(trend, "card should plot recall coverage over time")
        self.assertIn("复述趋势", trend.text())
        self.assertIsNotNone(
            card.findChild(QLabel, "recall_stagnant_lbl"),
            "flat coverage across three recalls must trigger a strategy hint",
        )
        card.deleteLater()

    def test_card_single_recall_has_no_trend(self):
        from expert_anything.core.storage import load_asset
        from expert_anything.ui.widgets.node_detail import NodeDetailCard

        asset = load_asset("a20260908-002")
        concept = next(c for c in asset.concepts if c.name == "节点边际电价(LMP)")
        state = {"concepts": {}, "history": [_recall(concept.name, 0.4)]}
        card = NodeDetailCard()
        card.set_concept(asset, concept.id, state, None)
        self.assertIsNone(card.findChild(QLabel, "recall_trend_lbl"))
        self.assertIsNotNone(card.findChild(QLabel, "recall_status_lbl"))
        card.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
