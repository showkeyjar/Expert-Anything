"""UI views extracted from main.py.

Each view is a standalone QWidget that receives a MainWindow reference
(`self._main`) to access shared state. Communication goes upward through
signals; MainWindow wires them to slots.
"""
from __future__ import annotations

from expert_anything.ui.views.import_view import ImportView
from expert_anything.ui.views.knowledge_view import KnowledgeView
from expert_anything.ui.views.concept_map_view import ConceptMapView
from expert_anything.ui.views.source_view import SourceView
from expert_anything.ui.views.teach_view import TeachView
from expert_anything.ui.views.learner_view import LearnerView
from expert_anything.ui.views.teacher_view import TeacherView
from expert_anything.ui.views.panorama_view import PanoramaView

__all__ = [
    "ImportView", "KnowledgeView", "ConceptMapView",
    "SourceView", "TeachView", "LearnerView", "TeacherView", "PanoramaView",
]
