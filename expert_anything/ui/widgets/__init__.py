"""
UI widgets package.

Classes that have been extracted to dedicated submodules are re-exported
from those submodules.  Classes still living in pyside_widgets.py are
re-exported from there until they are extracted.

Public API is stable regardless of where a class physically lives.
"""

from __future__ import annotations

# -- helpers (single source of truth) ---------------------------------------
from expert_anything.ui.widgets._helpers import (
    MASTERY_COLORS,
    _tag_label,
    mastery_color,
    mastery_level,
    tag_chip,
    _sec_title,
)

# -- extracted classes (from submodules) ------------------------------------
from expert_anything.ui.widgets.teach_widgets import (
    DecoderSceneCard,
    TeachResultView,
)
from expert_anything.ui.widgets.trend_chart import (
    TrendChartView,
    MasteryDistributionBar,
)
from expert_anything.ui.widgets.map_widgets import MapLegend
from expert_anything.ui.widgets.node_detail import NodeDetailCard
from expert_anything.ui.widgets.shared import KnowledgeCard, StatCard

# -- classes still in pyside_widgets (not yet extracted) --------------------
from expert_anything.ui.pyside_widgets import (
    SourceTextView,
    ConceptDetailPanel,
    ConceptCompareDialog,
    PathLadderView,
)

__all__ = [
    # helpers
    "MASTERY_COLORS",
    "_tag_label",
    "mastery_color",
    "mastery_level",
    "tag_chip",
    "_sec_title",
    # extracted classes
    "DecoderSceneCard",
    "TeachResultView",
    "TrendChartView",
    "MasteryDistributionBar",
    "MapLegend",
    "NodeDetailCard",
    "KnowledgeCard",
    "StatCard",
    # classes still in pyside_widgets
    "SourceTextView",
    "ConceptDetailPanel",
    "ConceptCompareDialog",
    "PathLadderView",
]
