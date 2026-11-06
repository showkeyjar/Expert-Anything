"""Release quality gate.

Aggregates the two offline benchmarks (:mod:`scene_benchmark` and
:mod:`learning_benchmark`) into a single pass/fail gate that CI can enforce
before shipping.  The gate is *deterministic and offline* — it reuses the
toy assets baked into :mod:`domain_templates`, so it never needs the network or
an LLM, and therefore proves two things on every commit:

1. **Decoder quality** — every curated domain decoder still produces scenes
   whose structure score is at least as good as the generic fallback.  This
   catches regressions where a template edit silently degrades output.
2. **Pedagogy validity** — the teaching loop actually teaches: coverage
   converges, weak concepts are coached first, stuck concepts are detected and
   re-routed, and spaced review fires only after its interval.

Run it with ``python -m expert_anything.core.quality_gate``; it exits non-zero
on any failed check so a CI step can block the release.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from expert_anything.core import scene_benchmark as _sb
from expert_anything.core import learning_benchmark as _lb
from expert_anything.core.domain_templates import DOMAIN_TEMPLATES

# --- Hard thresholds --------------------------------------------------------
# Curated decoders must not regress below the generic fallback on structure,
# and the pedagogy loop must demonstrably teach.
SCENE_MIN_STRUCTURE_GAIN = 0.0     # curated_structure_score >= fallback_structure_score
LEARNING_MIN_COVERAGE = 0.8        # >= 80% of concepts mastered after the loop
LEARNING_MIN_WEAK_FIRST = 0.5      # coach leads to unmastered concepts > 50% of picks


@dataclass
class QualityGateReport:
    domain_ids: list[str]
    scene_reports: list = field(default_factory=list)
    learning_reports: list = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)  # {"name", "ok", "detail"}
    passed: bool = True
    summary: str = ""

    def __str__(self) -> str:
        return _format(self)


def _chk(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def evaluate_scene(report) -> tuple[bool, str]:
    """Return (ok, detail) for one scene BenchmarkReport."""
    a = report.averages
    gain = float(a.get("gain_structure", 0.0))
    ok = gain >= SCENE_MIN_STRUCTURE_GAIN
    detail = (
        f"curated {a['curated_structure_score']} vs fallback "
        f"{a['fallback_structure_score']} (Δ{gain:+.3f})"
    )
    return ok, detail


def evaluate_learning(report) -> list[dict]:
    """Return the list of (name, ok, detail) checks for one LearningReport."""
    out = [
        _chk(
            f"learn:{report.asset_id}:coverage>={LEARNING_MIN_COVERAGE}",
            float(report.coverage) >= LEARNING_MIN_COVERAGE,
            f"coverage={report.coverage}",
        ),
        _chk(
            f"learn:{report.asset_id}:weak_first>={LEARNING_MIN_WEAK_FIRST}",
            float(report.weak_first_rate) >= LEARNING_MIN_WEAK_FIRST,
            f"weak_first={report.weak_first_rate}",
        ),
        _chk(
            f"learn:{report.asset_id}:stuck_detected",
            bool(report.stuck_detected),
            "stuck detected" if report.stuck_detected else "NOT detected",
        ),
        _chk(
            f"learn:{report.asset_id}:stuck_rerouted",
            bool(report.stuck_rerouted),
            "rerouted" if report.stuck_rerouted else "NOT rerouted",
        ),
        _chk(
            f"learn:{report.asset_id}:review_spaced",
            bool(report.review_spaced_ok),
            "spaced ok" if report.review_spaced_ok else "NOT spaced",
        ),
    ]
    return out


def run_quality_gate(domain_ids: list[str] | None = None) -> QualityGateReport:
    """Run both benchmarks across ``domain_ids`` and evaluate the gate.

    Returns a :class:`QualityGateReport` with ``passed`` True only if every
    check passes.
    """
    if domain_ids is None:
        domain_ids = list(DOMAIN_TEMPLATES)

    scene_reports = _sb.run_scene_benchmark(domain_ids)
    learning_reports = _lb.run_learning_benchmarks(domain_ids)

    checks: list[dict] = []
    for r in scene_reports:
        ok, detail = evaluate_scene(r)
        checks.append(_chk(f"scene:{r.domain_id}:structure_gain>={SCENE_MIN_STRUCTURE_GAIN}", ok, detail))
    for r in learning_reports:
        checks.extend(evaluate_learning(r))

    passed = all(c["ok"] for c in checks)
    rep = QualityGateReport(
        domain_ids=list(domain_ids),
        scene_reports=scene_reports,
        learning_reports=learning_reports,
        checks=checks,
        passed=passed,
    )
    rep.summary = _summarize(rep)
    return rep


def _summarize(rep: QualityGateReport) -> str:
    n_pass = sum(1 for c in rep.checks if c["ok"])
    n_fail = len(rep.checks) - n_pass
    status = "PASS" if rep.passed else "FAIL"
    return (
        f"QUALITY GATE: {status} "
        f"({n_pass}/{len(rep.checks)} checks; {n_fail} failed) | "
        f"domains={','.join(rep.domain_ids)}"
    )


def _format(rep: QualityGateReport) -> str:
    lines = [
        "=== quality gate ===",
        rep.summary,
        "",
        f"{'check':<56}{'result':>7}",
    ]
    for c in rep.checks:
        mark = "PASS" if c["ok"] else "FAIL"
        lines.append(f"{c['name']:<56}{mark:>7}")
        if not c["ok"]:
            lines.append(f"{'':<4}-> {c['detail']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    requested = sys.argv[1:] or None
    gate = run_quality_gate(requested)
    print(gate)
    print()
    print(gate.summary)
    sys.exit(0 if gate.passed else 1)
