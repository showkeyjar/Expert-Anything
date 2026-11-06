"""Learning-loop effectiveness benchmark: does the pedagogy engine actually teach?

``scene_benchmark`` proves the *decoder* (L1→L3 render) produces richer scenes
than the fallback.  But Expert-Anything's whole reason to exist is the
**teaching loop** — coach recommends → learner attempts → mastery is recorded →
spaced review resurfaces decaying material → stuck concepts trigger a strategy
change.  Until this module, that loop had *internal analytics* (learner.py /
coach.py) but **no validation signal** that running it produces learning.

This module closes that gap offline and deterministically:

* a ``SimulatedLearner`` drives the *real* ``coach.recommend`` →
  ``learner.record_evaluation`` → ``coach.record_coach_feedback`` loop, with a
  *deterministic* ability model (no randomness, no LLM, no network);
* three scenarios exercise the claims the analytics make:
    - **normal**: driven by the coach, does mastery coverage converge?
    - **stuck**: repeated failure on one concept — is it flagged & re-routed?
    - **review**: mastered material — does spacing schedule it back *after*
      the right interval (not too early, not never)?
* a ``LearningReport`` aggregates objective metrics with a plain-text ``__str__``.

The benchmark is pure-stdlib, deterministic, and fully offline — it is the
"learning telemetry" the project was missing, just self-administered instead of
collected from real users (which would need a deployment the sandbox can't run).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from expert_anything.core import coach, learner
from expert_anything.core.coach import recommend
from expert_anything.core.config import WEAKNESS_THRESHOLD as W
from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.scene_benchmark import build_toy_asset

# W = WEAKNESS_THRESHOLD (0.6) — mastery >= W counts as "learned"


def _utc(y: int, m: int, d: int, hh: int = 0) -> datetime:
    return datetime(y, m, d, hh, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Deterministic simulated learner
# --------------------------------------------------------------------------- #
class SimulatedLearner:
    """Drive the real teaching loop with a deterministic ability model.

    Ability model (no randomness, so the benchmark is reproducible):
      * a concept whose prerequisites are not yet mastered (< W) yields a low
        score (0.15) — you cannot learn B before you can learn A;
      * otherwise the score rises with the number of *attempts* on that concept
        (0.5, 0.75, 1.0, ...) — repeated study consolidates, as designed.

    The loop follows ``coach.recommend`` exactly as the UI would: it teaches the
    concept the coach names (a ``prereq`` redirect means shore up the
    prerequisite first), tags the attempt ``review`` when the coach says so, and
    records acceptance via ``record_coach_feedback``.
    """

    def __init__(self, asset: KnowledgeAsset):
        self.asset = asset
        self.state: dict = {"concepts": {}, "assets": {}, "history": []}
        learner.register_asset(self.state, asset)
        # prereq map: concept_id -> [prerequisite concept_ids]
        from expert_anything.core.decoder import classify_relation

        self._prereqs: dict[str, list[str]] = {c.id: [] for c in asset.concepts}
        for r in asset.relations or []:
            if classify_relation(r.label or "", r.type or "") in ("prereq", "causes"):
                if r.target in self._prereqs and r.source in self._prereqs:
                    self._prereqs[r.target].append(r.source)
        self._attempts: dict[str, int] = {}  # normalized key -> count
        self._force_fail: set[str] = set()   # concepts that always score 0.1
        self.trace: list[dict] = []

    def _mastery(self, concept_id: str) -> float:
        c = self.asset.concept_by_id(concept_id)
        if c is None:
            return 0.0
        return float(self.state["concepts"].get(learner.normalize(c.name), {}).get("mastery", 0.0))

    def _attempt(self, concept_id: str) -> float:
        if concept_id in self._force_fail:
            return 0.1
        if any(self._mastery(p) < W for p in self._prereqs.get(concept_id, [])):
            return 0.15  # foundation missing -> cannot consolidate
        idx = self._attempts.get(concept_id, 0)
        return min(1.0, 0.5 + 0.25 * idx)

    def _step(self) -> bool:
        """One coaching→attempt→record cycle. Returns False if nothing to coach."""
        rec = recommend(self.asset, self.state)
        cid = rec.get("concept_id") or ""
        if not cid:
            # explore / import: fall back to the top adaptive-path item
            items = learner.adaptive_path(self.asset, self.state, limit=8)
            cid = items[0]["cid"] if items else ""
        if not cid:
            return False
        c = self.asset.concept_by_id(cid)
        if c is None:
            return False
        score = self._attempt(cid)
        is_review = coach.is_review(rec)
        learner.record_evaluation(
            self.state, c.name, self.asset.asset_id, score, "answer", "feedback",
            meta={"style": "default", "channel": "quiz" if is_review else "answer",
                  "review": is_review},
        )
        coach.record_coach_feedback(self.state, rec, "start")
        self._attempts[cid] = self._attempts.get(cid, 0) + 1
        self.trace.append({
            "step": len(self.trace),
            "concept_id": cid,
            "concept_name": c.name,
            "kind": rec.get("kind", ""),
            "score": round(score, 2),
            "mastery_before": round(self._mastery(cid), 2),
        })
        return True

    def run(self, max_sessions: int) -> None:
        for _ in range(max_sessions):
            if not self._step():
                break


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@dataclass
class LearningReport:
    asset_id: str
    n_concepts: int
    sessions: int
    coverage: float = 0.0           # fraction of concepts reaching mastery >= W
    mean_mastery: float = 0.0       # mean mastery across all concepts
    mastery_gain: float = 0.0       # mean mastery delta from 0 (== mean_mastery)
    weak_first_rate: float = 0.0   # fraction of coach picks targeting an unlearned concept
    trend: str = ""                # learning_efficiency trend: improving|stable|declining
    stuck_detected: bool = False   # stuck scenario: repeated failure was flagged
    stuck_rerouted: bool = False   # stuck scenario: adaptive_path tagged it 'stuck'
    review_spaced_ok: bool = False # review scenario: due only after the interval, never before
    summary: str = ""

    def __str__(self) -> str:
        return _format_report(self)


def _coverage(state: dict) -> tuple[float, float]:
    recs = state.get("concepts", {}).values()
    n = len(recs)
    if n == 0:
        return 0.0, 0.0
    mastered = sum(1 for r in recs if float(r.get("mastery", 0.0)) >= W)
    mean_m = sum(float(r.get("mastery", 0.0)) for r in recs) / n
    return mastered / n, round(mean_m, 3)


def _weak_first_rate(trace: list[dict]) -> float:
    """Fraction of coaching picks that named a not-yet-mastered concept.

    A healthy coach leads the learner to what they *don't* know, not to what
    they already do.  Review picks (kind == 'review') are excluded — by
    definition they resurface *mastered* material that is decaying, so counting
    them as "not weak" would unfairly penalise correct spacing behaviour.
    """
    picks = [t for t in trace if t["kind"] != "review"]
    if not picks:
        return 0.0
    weak = sum(1 for t in picks if t["mastery_before"] < W)
    return round(weak / len(picks), 3)


def scenario_normal(asset: KnowledgeAsset) -> dict:
    sim = SimulatedLearner(asset)
    sim.run(max_sessions=len(asset.concepts) * 5 + 10)
    coverage, mean_m = _coverage(sim.state)
    eff = learner.learning_efficiency(sim.state)
    return {
        "n_concepts": len(asset.concepts),
        "sessions": len(sim.trace),
        "coverage": round(coverage, 3),
        "mean_mastery": mean_m,
        "mastery_gain": mean_m,
        "weak_first_rate": _weak_first_rate(sim.trace),
        "trend": eff.get("trend", ""),
    }


def scenario_stuck(asset: KnowledgeAsset, stuck_id: str | None = None) -> dict:
    """Repeated failure on one concept must be detected and re-routed."""
    sim = SimulatedLearner(asset)
    if stuck_id is None:
        # pick a leaf concept (one that is not a prerequisite for anything)
        targets = {r.target for r in asset.relations or []}
        leaf = next((c.id for c in asset.concepts if c.id not in targets), asset.concepts[0].id)
        stuck_id = leaf
    sim._force_fail.add(stuck_id)
    c = sim.asset.concept_by_id(stuck_id)
    name = c.name if c else stuck_id
    for _ in range(5):
        learner.record_evaluation(
            sim.state, name, asset.asset_id, 0.1, "answer", "wrong",
            meta={"style": "default", "channel": "answer", "review": False},
        )
    stuck = learner.stuck_concepts(sim.state, attempts=3)
    stuck_keys = {s["key"] for s in stuck}
    path = learner.adaptive_path(asset, sim.state, limit=20)
    rerouted = any(
        learner.normalize(item["name"]) == learner.normalize(name)
        and "stuck" in item.get("tags", [])
        for item in path
    )
    return {
        "stuck_id": stuck_id,
        "stuck_detected": learner.normalize(name) in stuck_keys,
        "stuck_rerouted": rerouted,
    }


def scenario_review(asset: KnowledgeAsset, review_id: str | None = None) -> dict:
    """Mastered material must resurface only after its spacing interval.

    We teach one concept to mastery, pin its ``updated_at`` to a fixed clock,
    then fast-forward that clock (via ``due_for_review(now=...)``) and assert the
    concept is NOT due one day later but IS due well past its interval.
    """
    sim = SimulatedLearner(asset)
    if review_id is None:
        review_id = asset.concepts[0].id
    c = sim.asset.concept_by_id(review_id)
    name = c.name if c else review_id
    # teach to mastery deterministically (no prereqs assumed for concept[0])
    for _ in range(4):
        learner.record_evaluation(
            sim.state, name, asset.asset_id, 0.85, "answer", "good",
            meta={"style": "default", "channel": "answer", "review": False},
        )
    key = learner.normalize(name)
    t0 = _utc(2026, 1, 1, 12)
    sim.state["concepts"][key]["updated_at"] = t0.isoformat()

    due_early = learner.due_for_review(sim.state, asset=asset, now=t0 + timedelta(days=1))
    due_late = learner.due_for_review(sim.state, asset=asset, now=t0 + timedelta(days=30))
    early_ids = {d.get("id") for d in due_early}
    late_ids = {d.get("id") for d in due_late}
    spaced_ok = (review_id not in early_ids) and (review_id in late_ids)
    return {
        "review_id": review_id,
        "mastery": sim.state["concepts"][key]["mastery"],
        "review_spaced_ok": spaced_ok,
        "interval_days": next((d.get("interval") for d in due_late if d.get("id") == review_id), None),
    }


def run_learning_benchmark(domain_id: str = "electricity_trading") -> LearningReport:
    asset = build_toy_asset(domain_id)
    normal = scenario_normal(asset)
    stuck = scenario_stuck(asset)
    review = scenario_review(asset)
    report = LearningReport(
        asset_id=domain_id,
        n_concepts=normal["n_concepts"],
        sessions=normal["sessions"],
        coverage=normal["coverage"],
        mean_mastery=normal["mean_mastery"],
        mastery_gain=normal["mastery_gain"],
        weak_first_rate=normal["weak_first_rate"],
        trend=normal["trend"],
        stuck_detected=stuck["stuck_detected"],
        stuck_rerouted=stuck["stuck_rerouted"],
        review_spaced_ok=review["review_spaced_ok"],
    )
    report.summary = _summarize(report, review)
    return report


def run_learning_benchmarks(domain_ids: Iterable[str] | None = None) -> list[LearningReport]:
    if domain_ids is None:
        from expert_anything.core.domain_templates import DOMAIN_TEMPLATES
        domain_ids = list(DOMAIN_TEMPLATES)
    return [run_learning_benchmark(d) for d in domain_ids]


def _summarize(r: LearningReport, review: dict) -> str:
    return (
        f"{r.asset_id}: {r.n_concepts} concepts / {r.sessions} sessions | "
        f"coverage {r.coverage} | mean-mastery {r.mean_mastery} | "
        f"weak-first {r.weak_first_rate} | trend {r.trend} | "
        f"stuck {('✓' if r.stuck_detected else '✗')}→{'✓' if r.stuck_rerouted else '✗'} | "
        f"review-spacing {('✓' if r.review_spaced_ok else '✗')}"
        f"(interval={review.get('interval_days')}d)"
    )


def _format_report(r: LearningReport) -> str:
    lines = [
        f"=== learning benchmark: {r.asset_id} ===",
        r.summary,
        "",
        f"{'metric':<18}{'value':>10}",
        f"{'concepts':<18}{r.n_concepts:>10}",
        f"{'sessions':<18}{r.sessions:>10}",
        f"{'coverage':<18}{r.coverage:>10}",
        f"{'mean_mastery':<18}{r.mean_mastery:>10}",
        f"{'weak_first_rate':<18}{r.weak_first_rate:>10}",
        f"{'trend':<18}{r.trend:>10}",
        f"{'stuck_detected':<18}{'YES' if r.stuck_detected else 'NO':>10}",
        f"{'stuck_rerouted':<18}{'YES' if r.stuck_rerouted else 'NO':>10}",
        f"{'review_spaced_ok':<18}{'YES' if r.review_spaced_ok else 'NO':>10}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    requested = sys.argv[1:] or None
    reports = run_learning_benchmarks(requested)
    for rep in reports:
        print(rep)
    print("--- summary ---")
    for rep in reports:
        print(rep.summary)
