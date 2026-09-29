"""Shared helper functions for UI widgets.

Extracted from pyside_widgets.py so that widget submodules can import
these utilities without pulling in the entire monolith.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from expert_anything.core.i18n import t as _t

# --------------------------------------------------------------------------- #
# colour palette (consistent with pyside_graph / core.graph_viz)
# --------------------------------------------------------------------------- #
MASTERY_COLORS = {
    "mastered": "#4CAF50",
    "partial": "#FF9800",
    "weak": "#F44336",
    "unstudied": "#9E9E9E",
}


def _tag_label(tag: str) -> str:
    """Translated tag label -- looked up at render time so language switches
    take effect immediately (module-level _t() would freeze the first lang)."""
    # Dynamic tags with numeric suffix
    if tag.startswith("unblock:"):
        try:
            n = int(tag.split(":", 1)[1])
            return _t("tag_unblock_n", n=n)
        except (ValueError, IndexError):
            pass
    return {
        "weak": _t("legend_weak"),
        "anom": _t("legend_anomaly"),
        "foundation": _t("legend_unstudied"),
        "ready": _t("legend_mastered"),
        "blocked": _t("legend_learning"),
        "path": _t("legend_focus"),
        "stuck": _t("tag_stuck"),
        "high_leverage": _t("tag_high_leverage"),
        "prereq_shaky": _t("legend_weak"),
        "unblock_stuck": _t("tag_stuck"),
    }.get(tag, tag)


def mastery_level(m: float) -> str:
    if m >= 0.6:
        return "mastered"
    if m >= 0.3:
        return "partial"
    if m > 0:
        return "weak"
    return "unstudied"


def mastery_color(m: float) -> str:
    return MASTERY_COLORS[mastery_level(m)]


def tag_chip(text: str, color: str = "#1565C0") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background-color: {color}20; color: {color};"
        "padding: 2px 8px; border-radius: 4px; font-size: 12px;"
    )
    return lbl


def _sec_title(text: str, color: str = "#0c4a6e") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 14.5px; font-weight: bold; color: {color}; margin-top: 6px;"
    )
    return lbl
