# -*- coding: utf-8 -*-
"""Round 18 tests: glossary source-coverage badges, dead-code cleanup,
and evidence-backed anomaly resolution."""
import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo  # noqa: E402

ensure_demo()

from expert_anything.core.learner import normalize  # noqa: E402
from expert_anything.core.models import Concept, KnowledgeAsset  # noqa: E402
from expert_anything.core.teacher import (  # noqa: E402
    GAP_RESOLVE_MASTERY,
    Anomaly,
    TeacherModel,
    anomaly_concept_ids,
    concept_anomalies,
    resolve_satisfied_anomalies,
)

try:
    from PySide6.QtWidgets import QLabel
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


def _asset(locations=None) -> KnowledgeAsset:
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
                name="节点电价",
                definition="反映供需的边际价格",
                evidence=["节点电价是本文的核心概念。"],
                locations=locations or [],
            )
        ],
        relations=[],
        learning_path=["c1"],
        method="test",
        source_length=0,
    )


def _anomaly(kind, name="节点电价", status="open") -> Anomaly:
    return Anomaly(
        id=f"an-{kind}",
        kind=kind,
        description=f"异常涉及概念 {name}",
        location=name,
        severity="medium",
        status=status,
        source="internal",
    )


class TestResolveSatisfiedAnomalies(unittest.TestCase):
    """Evidence-backed resolution: closed gaps must stop crying wolf."""

    def test_learner_gap_resolves_at_threshold(self):
        asset = _asset()
        tm = TeacherModel(
            "a1", "done", "test", "", [],
            [_anomaly("learner_gap", status="surfaced_to_student")],
        )
        state = {"concepts": {normalize("节点电价"): {"mastery": GAP_RESOLVE_MASTERY}}}
        n = resolve_satisfied_anomalies(asset, tm, state)
        self.assertEqual(n, 1)
        self.assertEqual(tm.anomalies[0].status, "resolved")
        self.assertEqual(
            anomaly_concept_ids(asset, tm),
            set(),
            "resolved anomaly must leave the actionable set",
        )
        self.assertEqual(concept_anomalies(asset.concepts[0], tm), [])

    def test_learner_gap_stays_below_threshold(self):
        asset = _asset()
        tm = TeacherModel("a1", "done", "test", "", [], [_anomaly("learner_gap")])
        state = {"concepts": {normalize("节点电价"): {"mastery": GAP_RESOLVE_MASTERY - 0.01}}}
        n = resolve_satisfied_anomalies(asset, tm, state)
        self.assertEqual(n, 0)
        self.assertEqual(tm.anomalies[0].status, "open")
        self.assertEqual(anomaly_concept_ids(asset, tm), {"c1"})

    def test_unanchored_resolves_once_locations_exist(self):
        asset = _asset(locations=["anchor"])
        tm = TeacherModel("a1", "done", "test", "", [], [_anomaly("unanchored_source")])
        self.assertEqual(resolve_satisfied_anomalies(asset, tm, {}), 1)
        self.assertEqual(tm.anomalies[0].status, "resolved")

    def test_unanchored_stays_without_locations(self):
        asset = _asset()
        tm = TeacherModel("a1", "done", "test", "", [], [_anomaly("unanchored_source")])
        self.assertEqual(resolve_satisfied_anomalies(asset, tm, {}), 0)
        self.assertEqual(tm.anomalies[0].status, "open")

    def test_material_doubts_never_auto_resolve(self):
        """contradiction & friends describe the material, not the learner —
        mastery must never talk the system out of them."""
        asset = _asset()
        tm = TeacherModel("a1", "done", "test", "", [], [_anomaly("contradiction")])
        state = {"concepts": {normalize("节点电价"): {"mastery": 1.0}}}
        self.assertEqual(resolve_satisfied_anomalies(asset, tm, state), 0)
        self.assertEqual(tm.anomalies[0].status, "open")

    def test_idempotent_and_none_safe(self):
        asset = _asset()
        tm = TeacherModel("a1", "done", "test", "", [], [_anomaly("learner_gap")])
        state = {"concepts": {normalize("节点电价"): {"mastery": 0.9}}}
        self.assertEqual(resolve_satisfied_anomalies(asset, tm, state), 1)
        self.assertEqual(
            resolve_satisfied_anomalies(asset, tm, state),
            0,
            "already-resolved rows must not double-count",
        )
        self.assertEqual(resolve_satisfied_anomalies(None, tm, state), 0)
        self.assertEqual(resolve_satisfied_anomalies(asset, None, state), 0)
        self.assertEqual(resolve_satisfied_anomalies(asset, tm, "garbage"), 0)


class TestDeadCodeCleanup(unittest.TestCase):
    """Round 18 deletions stay deleted and the live graph import is intact."""

    def test_raster_pipeline_gone(self):
        from expert_anything.core import graph_viz

        for name in (
            "concept_map_png",
            "_render",
            "_arrowhead",
            "_font",
            "_wrap",
            "_mastery_fill",
            "_node_border",
            "FONT_PATHS",
        ):
            self.assertFalse(hasattr(graph_viz, name), f"dead raster API: {name}")

    def test_prompt_aliases_gone(self):
        from expert_anything.core import prompt_registry

        self.assertFalse(hasattr(prompt_registry, "get_system_prompt"))
        self.assertFalse(hasattr(prompt_registry, "get_user_prompt"))
        self.assertTrue(callable(prompt_registry.get_prompt))

    def test_llm_cache_stats_gone(self):
        from expert_anything.core import llm

        self.assertFalse(hasattr(llm, "llm_cache_stats"))
        self.assertFalse(hasattr(llm, "_llm_cache_stats"))

    @unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
    def test_live_graph_import_intact(self):
        from expert_anything.ui.pyside_graph import KnowledgeGraphView  # noqa: F401


@unittest.skipUnless(HAS_QT, "Qt tests need PySide6")
class TestRound18UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.app = load_main_window()

    # -- candidate 1: glossary source coverage ---------------------------------
    def _domain_asset(self):
        from expert_anything.core.domain_templates import detect_domain_from_title

        for aid in sorted(self.app.assets):
            if detect_domain_from_title(self.app.assets[aid].get("title", "")):
                return self.app.get_asset(aid)
        return None

    def test_glossary_occurrence_badges(self):
        from expert_anything.core.i18n import t as _t
        from expert_anything.ui.widgets.glossary import GlossaryDialog

        asset = self._domain_asset()
        self.assertIsNotNone(asset, "demo data must include a domain asset")
        dlg = GlossaryDialog(asset)
        summary = dlg.findChild(QLabel, "glossary_occ_summary")
        self.assertIsNotNone(summary, "occurrence summary must render")
        self.assertIn("/", summary.text())
        chips = dlg.findChildren(QLabel, "glossary_occ_chip")
        self.assertTrue(chips, "every row must carry an occurrence chip")
        self.assertTrue(all(c.toolTip() for c in chips))
        yes = _t("glossary_occ_yes")
        self.assertTrue(
            any(c.text() == yes for c in chips),
            "a real textbook must mention at least one registered term",
        )

    def test_glossary_no_domain_keeps_old_look(self):
        from expert_anything.ui.widgets.glossary import GlossaryDialog

        asset = KnowledgeAsset(
            asset_id="x",
            type="article",
            title="未登记领域读物",
            source_name="",
            created_at="",
            source_text="一些正文。",
            chapters=[],
            concepts=[],
            relations=[],
            learning_path=[],
            method="test",
            source_length=0,
        )
        dlg = GlossaryDialog(asset)
        self.assertIsNone(dlg.findChild(QLabel, "glossary_occ_summary"))
        self.assertFalse(dlg.findChildren(QLabel, "glossary_occ_chip"))

    # -- candidate 3: post-evaluation sync resolves satisfied anomalies ---------
    def test_teach_view_sync_resolves_gap(self):
        import copy
        from unittest.mock import patch

        from expert_anything.core.teacher import TeacherModel

        app = self.app
        aid = sorted(app.assets)[0]
        asset = app.get_asset(aid)
        concept = asset.concepts[0]

        tm = TeacherModel(
            aid, "done", "test", "", [],
            [
                Anomaly(
                    id="an-gap",
                    kind="learner_gap",
                    description=f"复习增益为负：{concept.name}",
                    location=concept.name,
                    severity="medium",
                    status="surfaced_to_student",
                    source="internal",
                )
            ],
        )
        snapshot_tm = copy.deepcopy(app.teacher_models)
        learner_concepts = app.learner.setdefault("concepts", {})
        old_rec = copy.deepcopy(learner_concepts.get(normalize(concept.name)))
        learner_concepts[normalize(concept.name)] = {
            "name": concept.name,
            "mastery": 0.9,
        }

        def _restore():
            app.teacher_models = snapshot_tm
            if old_rec is None:
                learner_concepts.pop(normalize(concept.name), None)
            else:
                learner_concepts[normalize(concept.name)] = old_rec

        self.addCleanup(_restore)

        app.teacher_models[aid] = tm.to_dict()
        with patch(
            "expert_anything.ui.views.teach_view.save_teacher"
        ) as mock_save:
            app._teach_view._check_review_gain_for(concept, asset)

        stored = app.teacher_models[aid]["anomalies"]
        gap = next(a for a in stored if a["id"] == "an-gap")
        self.assertEqual(
            gap["status"],
            "resolved",
            "post-evaluation sync must resolve a gap the learner has closed",
        )
        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
