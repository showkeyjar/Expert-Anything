"""ExpertAnything test runner — one command, layered report.

Usage:
    python run_tests.py          # full suite (LLM tests run if key configured)
    python run_tests.py --quick  # core+data+ui+runner, 796 tests, ~5 min (UI layer dominates)
    python run_tests.py --llm    # LLM tests only

Layers:
  core  – parsers / extraction / models / learner / tutor / teacher / storage
  data  – demo-data integrity (real data/_demo, read-only)
  ui    – offscreen PySide6 window/widget tests
  llm   – real LLM tests (skipped without EXPERTANYTHING_LLM_API_KEY)
"""

import argparse
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LAYERS = {
    "core": [
        "tests.test_core",
        "tests.test_report",
        "tests.test_checks",
        "tests.test_decoder",
        "tests.test_auto_harness",
        "tests.test_map_context",
        "tests.test_prompt_templates",
        "tests.test_domain_templates",
        "tests.test_domain_prompts",
        "tests.test_terminology",
        "tests.test_search",
        "tests.test_knowledge_index",
        "tests.test_domain_renewable",
        "tests.test_domain_distributed_energy",
        "tests.test_scene_benchmark",
        "tests.test_learning_benchmark",
        "tests.test_quality_gate",
        "tests.test_i18n_integrity",
        "tests.test_llm_endpoint",
        "tests.test_round12",
        "tests.test_round13",
        "tests.test_round14",
        "tests.test_round15",
        "tests.test_round16",
        "tests.test_round17",
        "tests.test_round18",
        "tests.test_round19",
        "tests.test_round20",
    ],
    "data": ["tests.test_demo_data"],
    "ui": ["tests.test_ui"],
    "llm": ["tests.test_llm"],
}

# Optional layers must not make the whole runner unusable in a minimal
# environment.  Keep the mapping explicit so adding a new layer remains safe.
# The LLM client itself uses urllib/json from the standard library; its tests
# only need the project's configured endpoint when they make live calls.
LAYER_DEPENDENCIES = {"ui": "PySide6"}


def layer_dependency_available(layer: str) -> bool:
    dependency = LAYER_DEPENDENCIES.get(layer)
    return dependency is None or importlib.util.find_spec(dependency) is not None


def main() -> int:
    ap = argparse.ArgumentParser(description="ExpertAnything test runner")
    ap.add_argument("--quick", action="store_true", help="skip LLM tests")
    ap.add_argument("--llm", action="store_true", help="run LLM tests only")
    ap.add_argument("--layer", choices=list(LAYERS), help="run one layer only")
    ap.add_argument("-v", action="store_true", help="verbose")
    args = ap.parse_args()

    if args.layer:
        selected_layers = [args.layer]
        label = args.layer
    elif args.llm:
        selected_layers = ["llm"]
        label = "llm"
    else:
        selected_layers = [
            layer for layer in LAYERS if not (layer == "llm" and args.quick)
        ]
        label = "quick" if args.quick else "full"

    modules = []
    for layer in selected_layers:
        if not layer_dependency_available(layer):
            print(f"-- skip {layer}: optional dependency unavailable")
            continue
        modules.extend(LAYERS[layer])

    # Keep the runner's own regression tests in the repository test suite.
    if "tests.test_runner" not in modules:
        modules.append("tests.test_runner")

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
    print(
        f"\n== {result.testsRun} tests, "
        f"{len(result.failures)} failures, {len(result.errors)} errors =="
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
