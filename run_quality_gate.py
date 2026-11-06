"""Run the release quality gate (see expert_anything/core/quality_gate.py).

Standalone entry so the gate works regardless of how Python resolves
sys.path (same pattern as run_tests.py).  CI runs this right after the
quick suite; exits non-zero on any failed check.

Usage:  python run_quality_gate.py [domain_id ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from expert_anything.core.quality_gate import run_quality_gate  # noqa: E402

if __name__ == "__main__":
    gate = run_quality_gate(sys.argv[1:] or None)
    print(gate)
    print()
    print(gate.summary)
    sys.exit(0 if gate.passed else 1)
