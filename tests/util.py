"""Shared test utilities for the ExpertAnything test suite.

- ``ensure_demo()``: point EXPERTANYTHING_DATA_DIR at a temp copy of the
  demo data (regenerating a minimal deterministic demo if missing).
- ``prepare_app()``: create a QApplication + patched dialogs for UI tests.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEMO = PROJECT / "data" / "_demo"

_TMP_DATA: Path | None = None


def ensure_demo() -> Path:
    """Return a temp dir with a copy of the demo data (never mutates real data)."""
    global _TMP_DATA
    if _TMP_DATA is not None:
        return _TMP_DATA
    _TMP_DATA = Path(tempfile.mkdtemp(prefix="ea_tests_")) / "d"
    if DEMO.exists():
        shutil.copytree(DEMO, _TMP_DATA, dirs_exist_ok=True)
    else:
        _regenerate_minimal(_TMP_DATA)
    os.environ["EXPERTANYTHING_DATA_DIR"] = str(_TMP_DATA)
    # reload config so modules imported earlier in this process pick up the
    # temp data dir (unittest discover shares one process across modules)
    import importlib
    import expert_anything.core.config as _cfg
    importlib.reload(_cfg)
    return _TMP_DATA


def _regenerate_minimal(target: Path) -> None:
    """Deterministic fallback demo (no LLM) so tests always run."""
    sys.path.insert(0, str(PROJECT))
    target.mkdir(parents=True, exist_ok=True)
    from expert_anything.core import storage
    from expert_anything.core.extraction import extract_knowledge

    samples = {
        "a630c18fb": (
            "# Pure Mathematics\n\n## Inquiry\nInquiry is the process of asking questions "
            "and testing ideas through practice.\n\n## Strategy\nStrategy is the plan of "
            "attacking a problem step by step.\n\n## Content\nContent is what a mathematical "
            "theory studies.\n\nconsumer of mathematics uses tools without questioning.\n"
            "producer of mathematics creates new mathematics.\npure mathematics is the study "
            "of abstract structures.\n",
            "pure-math.md",
        ),
        "ac586ee94": (
            "# Design Agent Memory\n\n## Memory\nMemory lets an Agent keep key information "
            "across turns.\n\n## 短期记忆\n短期记忆保存在当前会话内。\n\n## 长期记忆\n长期记忆"
            "写入外部存储，跨会话复用。\n\nMemory is part of Context Engineering.\n",
            "agent-memory.md",
        ),
    }
    for aid, (text, fname) in samples.items():
        asset = extract_knowledge(text, fname, llm=None)
        asset.asset_id = aid
        storage.save_asset(asset)
    state = {
        "profile": {"goal": "理解纯数学", "baseline": "novice", "style": "example"},
        "concepts": {},
        "assets": {},
        "history": [],
    }
    (target / "learner.json").write_text(
        __import__("json").dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def prepare_app():
    """Create QApplication (offscreen) with non-blocking dialogs; return app."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    for name in ("information", "warning", "critical"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    return app


def load_main_window():
    """Import main and build a MainWindow against the demo data."""
    ensure_demo()
    sys.path.insert(0, str(PROJECT))
    prepare_app()
    from main import MainWindow

    return MainWindow()
