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
VIEW_PANORAMA = 7


class ViewManager(QObject):
    """Manages the view stack and routes cross-view signals.

    Views are plain QWidgets that know about MainWindow via `self._main`.
    They communicate upward through their own signals; this manager wires
    them to MainWindow slots.  This keeps the routing logic in one place
    instead of scattered across `_build_*` methods.
    """

    # Signals emitted upward to MainWindow
    navigate_requested = Signal(str)  # view_name

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
            "panorama": VIEW_PANORAMA,
        }

    def register_views(self, views: list):
        """Called by MainWindow after building all views."""
        self._views = views
