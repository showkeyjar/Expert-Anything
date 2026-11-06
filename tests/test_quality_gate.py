"""Tests for the release quality gate.

Two layers are covered:

1. **Threshold logic** (``evaluate_scene`` / ``evaluate_learning``) against
   hand-built reports, so the pass/fail rules are pinned without depending on
   the heavy benchmark machinery.
2. **End-to-end gate** over the real toy assets — every bundled domain must
   pass both the decoder-quality and pedagogy checks on a clean checkout.
"""

import unittest
from types import SimpleNamespace

from expert_anything.core import quality_gate as qg


class _FakeAverages(dict):
    def __init__(self, curated, fallback):
        super().__init__(
            curated_structure_score=curated,
            fallback_structure_score=fallback,
            gain_structure=round(curated - fallback, 3),
        )


class TestSceneThresholds(unittest.TestCase):
    def test_curated_meets_fallback_passes(self):
        rep = SimpleNamespace(domain_id="x", averages=_FakeAverages(11.5, 9.55))
        ok, detail = qg.evaluate_scene(rep)
        self.assertTrue(ok)
        self.assertIn("Δ", detail)

    def test_curated_below_fallback_fails(self):
        rep = SimpleNamespace(domain_id="x", averages=_FakeAverages(9.0, 9.55))
        ok, detail = qg.evaluate_scene(rep)
        self.assertFalse(ok)


class TestLearningThresholds(unittest.TestCase):
    def _report(self, **kw):
        defaults = dict(
            asset_id="x", coverage=1.0, weak_first_rate=0.667,
            stuck_detected=True, stuck_rerouted=True, review_spaced_ok=True,
        )
        defaults.update(kw)
        return SimpleNamespace(**defaults)

    def test_all_good_passes(self):
        checks = qg.evaluate_learning(self._report())
        self.assertTrue(all(c["ok"] for c in checks))

    def test_low_coverage_fails(self):
        checks = qg.evaluate_learning(self._report(coverage=0.5))
        names = {c["name"]: c["ok"] for c in checks}
        self.assertFalse(names["learn:x:coverage>=0.8"])

    def test_stuck_not_detected_fails(self):
        checks = qg.evaluate_learning(self._report(stuck_detected=False))
        names = {c["name"]: c["ok"] for c in checks}
        self.assertFalse(names["learn:x:stuck_detected"])

    def test_stuck_not_rerouted_fails(self):
        checks = qg.evaluate_learning(self._report(stuck_rerouted=False))
        names = {c["name"]: c["ok"] for c in checks}
        self.assertFalse(names["learn:x:stuck_rerouted"])

    def test_review_not_spaced_fails(self):
        checks = qg.evaluate_learning(self._report(review_spaced_ok=False))
        names = {c["name"]: c["ok"] for c in checks}
        self.assertFalse(names["learn:x:review_spaced"])

    def test_weak_first_below_half_fails(self):
        checks = qg.evaluate_learning(self._report(weak_first_rate=0.3))
        names = {c["name"]: c["ok"] for c in checks}
        self.assertFalse(names["learn:x:weak_first>=0.5"])


class TestGateEndToEnd(unittest.TestCase):
    def test_default_domains_pass(self):
        gate = qg.run_quality_gate()
        self.assertTrue(gate.passed, msg=gate.summary)
        self.assertTrue(gate.checks)  # non-empty
        for c in gate.checks:
            self.assertTrue(c["ok"], msg=f"failed check: {c['name']} -> {c['detail']}")

    def test_report_str_and_exit_code(self):
        gate = qg.run_quality_gate()
        text = str(gate)
        self.assertIn("QUALITY GATE", text)
        self.assertIn("PASS" if gate.passed else "FAIL", text)


if __name__ == "__main__":
    unittest.main()
