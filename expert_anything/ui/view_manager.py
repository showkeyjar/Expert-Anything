"""ViewManager: orchestrates the content stack and provides shared services."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QStackedWidget

# View index constants (mirrored by MainWindow.on_nav_click)
VIEW_IMPORT = 0
VIEW_KNOWLEDGE = 1
VIEW_MAP = 2
VIEW_SOURCE = 3
VIEW_TEACH = 4
VIEW_LEARNER = 5
VIEW_TEACHER = 6


class ViewManager(QObject):
    """Manages the view stack and routes cross-view signals.

    Views are plain QWidgets that know about MainWindow via `self._main`.
    They communicate upward through their own signals; this manager wires
    them to MainWindow slots.  This keeps the routing logic in one place
    instead of scattered across `_build_*` methods.
    """

    # Signals emitted upward to MainWindow
    navigate_requested = Signal(str)  # view_name
    teach_requested = Signal(str)     # concept_name
    concept_panel_requested = Signal(str)  # concept_id
    focus_graph_requested = Signal(str)    # concept_id
    refresh_requested = Signal()       # refresh all data views

    def __init__(self, content_stack: QStackedWidget):
        super().__init__()
        self._stack = content_stack
        self._views: list = []  # [ImportView, KnowledgeView, ...]

        # Register view index for navigation by name
        self._view_index = {
            "import": VIEW_IMPORT,
            "knowledge": VIEW_KNOWLEDGE,
            "concept_map": VIEW_MAP,
            "source": VIEW_SOURCE,
            "teach": VIEW_TEACH,
            "learner": VIEW_LEARNER,
            "teacher": VIEW_TEACHER,
        }

    def register_views(self, views: list):
        """Called by MainWindow after building all views."""
        self._views = views

    def set_current(self, name: str):
        idx = self._view_index.get(name)
        if idx is not None and idx < self._stack.count():
            self._stack.setCurrentIndex(idx)

    def current_index(self) -> int:
        return self._stack.currentIndex()

    def current_name(self) -> str:
        """Reverse-lookup the current view name."""
        for name, idx in self._view_index.items():
            if idx == self.current_index():
                return name
        return ""

    def refresh_current(self):
        """Ask the current view to rebuild (e.g. after language change)."""
        idx = self.current_index()
        if idx < len(self._views) and hasattr(self._views[idx], "refresh"):
            self._views[idx].refresh()

    def navigate_to(self, name: str):
        """Public navigation entry point (called from views)."""
        self.navigate_requested.emit(name)
