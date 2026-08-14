"""ExpertAnything test runner — one command, layered report.

Usage:
    python run_tests.py          # full suite (LLM tests run if key configured)
    python run_tests.py --quick  # skip LLM tests (fast, ~10s)
    python run_tests.py --llm    # LLM tests only

Layers:
  core  – parsers / extraction / models / learner / tutor / teacher / storage
  data  – demo-data integrity (real data/_demo, read-only)
  ui    – offscreen PySide6 window/widget tests
  llm   – real LLM tests (skipped without EXPERTANYTHING_LLM_API_KEY)
"""
import argparse
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LAYERS = {
    "core": ["tests.test_core"],
    "data": ["tests.test_demo_data"],
    "ui": ["tests.test_ui"],
    "llm": ["tests.test_llm"],
}


def main() -> int:
    ap = argparse.ArgumentParser(description="ExpertAnything test runner")
    ap.add_argument("--quick", action="store_true", help="skip LLM tests")
    ap.add_argument("--llm", action="store_true", help="run LLM tests only")
    ap.add_argument("--layer", choices=list(LAYERS), help="run one layer only")
    ap.add_argument("-v", action="store_true", help="verbose")
    args = ap.parse_args()

    if args.layer:
        modules = LAYERS[args.layer]
        label = args.layer
    elif args.llm:
        modules = LAYERS["llm"]
        label = "llm"
    else:
        modules = []
        for layer, mods in LAYERS.items():
            if layer == "llm" and args.quick:
                continue
            modules.extend(mods)
        label = "quick" if args.quick else "full"

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for mod in modules:
        try:
            suite.addTests(loader.loadTestsFromName(mod))
        except Exception as exc:  # pragma: no cover
            print(f"!! cannot load {mod}: {exc}")
            return 2

    print(f"== ExpertAnything tests [{label}] ==")
    runner = unittest.TextTestRunner(verbosity=2 if args.v else 1)
    result = runner.run(suite)
    print(f"\n== {result.testsRun} tests, "
          f"{len(result.failures)} failures, {len(result.errors)} errors ==")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
