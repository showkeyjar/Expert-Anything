"""Tests for the learning-loop effectiveness benchmark.

Validates the three claims the pedagogy analytics make:
  - the coach-driven loop actually raises mastery coverage;
  - repeated failure on a concept is flagged AND re-routed (stuck);
  - spaced review resurfaces mastered material only after its interval.
"""
import unittest
from datetime import datetime, timedelta, timezone

from expert_anything.core import learner
from expert_anything.core.domain_templates import DOMAIN_TEMPLATES
from expert_anything.core.learning_benchmark import (
    LearningReport,
    SimulatedLearner,
    run_learning_benchmark,
    run_learning_benchmarks,
    scenario_normal,
    scenario_review,
    scenario_stuck,
)
from expert_anything.core.scene_benchmark import build_toy_asset


def _make_state() -> dict:
    return {"concepts": {}, "assets": {}, "history": []}


class TestScenarioNormal(unittest.TestCase):
    def test_coverage_converges(self):
        asset = build_toy_asset("electricity_trading")
        r = scenario_normal(asset)
        self.assertGreater(r["coverage"], 0.8, "coach loop should master most concepts")
        self.assertGreater(r["mastery_gain"], 0.3, "loop must raise mean mastery from 0")
        # NOTE: r["trend"] is a per-attempt *score* slope, not mastery growth, so
        # it is intentionally NOT gated here (a spaced-review tail can lower the
        # recent score average even when every concept was mastered).

    def test_weak_first_prioritization(self):
        asset = build_toy_asset("electricity_trading")
        r = scenario_normal(asset)
        # The coach must lead the learner to what they don't yet know for the
        # majority of (non-review) picks.  Review picks resurface mastered
        # material by design and are excluded from this ratio.
        self.assertGreater(r["weak_first_rate"], 0.5)


class TestScenarioStuck(unittest.TestCase):
    def test_detected_and_rerouted(self):
        asset = build_toy_asset("electricity_trading")
        r = scenario_stuck(asset)
        self.assertTrue(r["stuck_detected"], "repeated failure must be flagged stuck")
        self.assertTrue(r["stuck_rerouted"], "stuck concept must surface in adaptive_path")

    def test_adaptive_path_tags_stuck(self):
        asset = build_toy_asset("electricity_trading")
        targets = {rr.target for rr in asset.relations or []}
        leaf = next((c.id for c in asset.concepts if c.id not in targets), asset.concepts[0].id)
        sim = SimulatedLearner(asset)
        sim._force_fail.add(leaf)
        name = asset.concept_by_id(leaf).name
        for _ in range(5):
            learner.record_evaluation(
                sim.state, name, asset.asset_id, 0.1, "a", "w",
                meta={"style": "default", "channel": "answer", "review": False},
            )
        stuck = learner.stuck_concepts(sim.state, attempts=3)
        self.assertTrue(any(s["key"] == learner.normalize(name) for s in stuck))


class TestScenarioReview(unittest.TestCase):
    def test_spacing_respects_interval(self):
        asset = build_toy_asset("electricity_trading")
        r = scenario_review(asset)
        self.assertTrue(r["review_spaced_ok"], "due only after the interval, never before")
        self.assertGreater(r["interval_days"], 5)

    def test_due_for_review_now_param(self):
        # The injected `now` makes the spacing algorithm testable deterministically.
        t0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        state = _make_state()
        state["concepts"]["weak"] = {
            "name": "weak", "mastery": 0.3, "updated_at": t0.isoformat(), "sources": [], "last_feedback": "",
        }
        state["concepts"]["strong"] = {
            "name": "strong", "mastery": 0.9,
            "updated_at": (t0 - timedelta(days=10)).isoformat(), "sources": [], "last_feedback": "",
        }
        asset = build_toy_asset("electricity_trading")
        # No `asset=` here on purpose: due_for_review skips any concept not in
        # the asset graph (learner.py:1472), which would drop our hand-built
        # "strong"/"weak" rows.  We only want to verify the `now` injection.
        due = learner.due_for_review(state, now=t0)
        due_keys = {d.get("key") for d in due}
        # strong was last touched 10 days ago (interval ~5.7d) -> due; weak touched today -> not
        self.assertIn("strong", due_keys)
        self.assertNotIn("weak", due_keys)


class TestReport(unittest.TestCase):
    def test_run_returns_report_with_fields(self):
        rep = run_learning_benchmark("electricity_trading")
        self.assertIsInstance(rep, LearningReport)
        self.assertGreater(rep.n_concepts, 0)
        self.assertGreaterEqual(rep.coverage, 0.0)
        self.assertIn(rep.trend, ("improving", "stable", "declining", "unknown"))
        self.assertTrue(rep.summary)

    def test_report_str_has_sections(self):
        rep = run_learning_benchmark("carbon_trading")
        text = str(rep)
        self.assertIn("carbon_trading", text)
        self.assertIn("coverage", text)
        self.assertIn("weak_first_rate", text)

    def test_all_domains(self):
        reports = run_learning_benchmarks()
        self.assertEqual(len(reports), len(DOMAIN_TEMPLATES))
        for r in reports:
            self.assertIsInstance(r, LearningReport)


if __name__ == "__main__":
    unittest.main(verbosity=2)
