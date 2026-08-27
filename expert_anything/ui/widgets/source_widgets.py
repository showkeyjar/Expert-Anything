"""SourceTextView re-export.

SourceTextView has not yet been extracted from pyside_widgets.py.
This module provides a stable import path for views that only need
SourceTextView without pulling in the entire widget collection.
"""

from __future__ import annotations

from expert_anything.ui.pyside_widgets import (
    SourceTextView,
    ConceptDetailPanel,
    ConceptCompareDialog,
    PathLadderView,
)

__all__ = [
    "SourceTextView",
    "ConceptDetailPanel",
    "ConceptCompareDialog",
    "PathLadderView",
]
