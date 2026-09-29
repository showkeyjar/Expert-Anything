"""
ExpertAnything main entry point.

All top-level window logic lives here. View construction is delegated to the
`ui.views` package so that each view is a standalone module. The ViewManager
wires cross-view signals without them having to know about each other.

File layout after refactoring:
  expert_anything/core/      — knowledge engine (LLM-free logic)
  expert_anything/ui/
      __init__.py
      pyside_graph.py         — KnowledgeGraphView (QGraphicsView)
      pyside_widgets.py       — reusable widgets (ConceptDetailPanel, etc.)
      widgets/                — new modular widgets
          shared.py            — KnowledgeCard, StatCard
          teach_widgets.py     — TeachResultView, answer/practice/quiz widgets
          source_widgets.py    — SourceTextView
          map_widgets.py       — NodeDetailCard, MapLegend
          trend_chart.py       — TrendChartView, MasteryDistributionBar
      views/                  — one file per view
          import_view.py
          knowledge_view.py
          concept_map_view.py
          source_view.py
          teach_view.py
          learner_view.py
          teacher_view.py
      view_manager.py         — content stack orchestration + signal routing
  main.py                    — MainWindow, state, entry point
  app.py                     — thin bootstrap
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QLibraryInfo,
    QLocale,
    QObject,
    QTranslator,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core import config
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.i18n import (
    LANGS,
    get_lang,
    set_lang,
    save_lang,
    t as _t,
)
from expert_anything.core.learner import (
    adaptive_path,
    due_for_review,
    normalize,
    record_evaluation,
    register_asset,
    topic_clusters,
    concept_density,
    stuck_concepts,
)
from expert_anything.core.llm import LLMClient, LLMNotConfigured
from expert_anything.core.models import (
    Concept,
    KnowledgeAsset,
    Relation,
    SourceLocation,
    Chapter,
)
from expert_anything.core.report_html import build_html_report, localize_method
from expert_anything.core.storage import (
    delete_asset,
    load_learner,
    save_learner,
    save_teacher,
    load_teacher,
)
from expert_anything.core.teacher import (
    TeacherModel,
    anomaly_concept_ids,
    incorporate_comparison,
    incorporate_stuck_signal,
    record_learner_question,
    build_teacher_model,
)
from expert_anything.core import auto_harness as _ah
from expert_anything.ui.pyside_graph import KnowledgeGraphView
from expert_anything.ui.widgets import (
    ConceptDetailPanel,
    ConceptCompareDialog,
    PathLadderView,
    SourceTextView,
    NodeDetailCard,
    MapLegend,
    TrendChartView,
)
from expert_anything.ui.views import (
    ImportView,
    KnowledgeView,
    ConceptMapView,
    SourceView,
    TeachView,
    LearnerView,
    TeacherView,
)
from expert_anything.ui.view_manager import ViewManager


# ---------------------------------------------------------------------------
# Global exception hook
# ---------------------------------------------------------------------------


def _install_excepthook():
    """Write uncaught exceptions to error.log and show a message box."""
    log_path = Path(__file__).parent / "error.log"
    _orig = sys.excepthook

    def hook(typ, value, tb):
        tb_text = "".join(traceback.format_exception(typ, value, tb))
        try:
            log_path.write_text(tb_text, encoding="utf-8")
        except Exception:
            pass
        _orig(typ, value, tb)
        QMessageBox.critical(
            None,
            _t("fatal_error"),
            _t("fatal_error_body", msg=f"{value}\n\n{tb_text[-600:]}"),
        )

    sys.excepthook = hook


# ---------------------------------------------------------------------------
# Progress signal (used by workers and UI)
# ---------------------------------------------------------------------------


class ProgressSignal(QObject):
    valueChanged = Signal(int)
    textChanged = Signal(str)


progress_signal = ProgressSignal()


# ---------------------------------------------------------------------------
# Shared worker references (cleared on _rebuild_all_views)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    # ---- constructor --------------------------------------------------------

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ExpertAnything")
        self.setMinimumSize(1100, 760)
        self.resize(1200, 800)

        # Application state
        self.assets: dict = {}  # asset_id -> metadata dict
        # Parsed assets and the merged map are immutable between imports or
        # asset switches. Rebuilding 500+ Concept/Relation objects on every
        # navigation click made the cognitive map feel like it was hanging.
        self._asset_object_cache: dict[str, tuple[dict, KnowledgeAsset]] = {}
        self._global_asset_cache: tuple[tuple, KnowledgeAsset, set] | None = None
        self.teacher_models: dict = {}  # asset_id -> TeacherModel.to_dict()
        self.learner = {}  # learner state dict
        self.current_asset_id: str | None = None
        self.llm_client: LLMClient | None = None

        # Per-view widget refs that need clearing on rebuild
        self._concept_panel: ConceptDetailPanel | None = None
        self._teach_graph: KnowledgeGraphView | None = None
        self._dash_graph: KnowledgeGraphView | None = None
        self._graph_view: KnowledgeGraphView | None = None
        self._source_view_widget: SourceTextView | None = None
        self._map_detail: NodeDetailCard | None = None
        self._path_ladder: PathLadderView | None = None
        self._teach_answer_input: QWidget | None = None

        # AutoHarness state
        self._harness_specs: dict = {}
        self._harness_history: list = []

        # View manager
        self._view_manager: ViewManager | None = None

        self.load_data()
        self.init_llm()
        self.setup_ui()

    # ---- LLM ----------------------------------------------------------------

    def init_llm(self):
        if config.has_llm():
            try:
                self.llm_client = LLMClient.from_config(
                    config.LLM_API_KEY,
                    config.LLM_BASE_URL,
                    config.LLM_MODEL,
                )
            except LLMNotConfigured:
                self.llm_client = None

    # ---- data loading --------------------------------------------------------

    def load_data(self):
        assets_dir = config.DATA_DIR / "assets"
        if assets_dir.exists():
            for fpath in sorted(assets_dir.glob("*.json")):
                if fpath.name.startswith("teacher_"):
                    continue
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                    aid = data.get("asset_id", fpath.stem)
                    self.assets[aid] = data
                except Exception:
                    pass

        # Teacher models
        if assets_dir.exists():
            for fpath in sorted(assets_dir.glob("teacher_*.json")):
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                    aid = data.get("asset_id", fpath.stem.replace("teacher_", ""))
                    self.teacher_models[aid] = data
                except Exception:
                    pass

        # Learner
        learner_path = config.LEARNER_FILE
        if learner_path.exists():
            try:
                self.learner = load_learner()
            except Exception:
                self.learner = {
                    "profile": {},
                    "assets": {},
                    "concepts": {},
                    "history": [],
                }

        # AutoHarness
        harness_state = config.DATA_DIR / "harness_state.json"
        self._harness_specs = _ah.load_harness_state(harness_state)
        self._harness_history = _ah.load_harness_history(
            config.DATA_DIR / "harness_history.json"
        )

        if self.assets and not self.current_asset_id:
            self.current_asset_id = next(iter(self.assets))

    # ---- UI setup ------------------------------------------------------------

    def _get_asset_subtitle(self) -> str:
        """Return a concise summary for the currently selected asset."""
        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            title = data.get("title", self.current_asset_id)
            method = data.get("method", "llm_extraction_chunked_v1")
            concepts = len(data.get("concepts", []))
            return _t("dash_subtitle", title=title, concepts=concepts, method=method)
        return _t("dash_loading")

    def setup_ui(self):
        # Language
        lang = get_lang()
        app = QApplication.instance()
        if app is not None:
            app.setStyle(QStyleFactory.create("Fusion"))
        self.setFont(QFont("Segoe UI", 11))

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self._sidebar = self._build_sidebar()
        root.addWidget(self._sidebar)

        # Main area: topbar + content stack (7 pages)
        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self._topbar = self._build_topbar()
        self.topbar = self._topbar
        main_layout.addWidget(self._topbar)
        self.content_stack = QStackedWidget()
        main_layout.addWidget(self.content_stack, 1)
        root.addWidget(main_area, 1)

        # Build all 7 views
        self._build_import_view()
        self._build_knowledge_view()
        self._build_concept_map_view()
        self._build_source_view()
        self._build_teach_view()
        self._build_learner_view()
        self._build_teacher_view()
        # View constructors may trigger nested Qt layout ownership changes;
        # publish the final live graph after the complete view tree exists.
        self._dash_graph = self._knowledge_view._dash_graph

        # Add views to content stack
        for v in [
            self._import_view,
            self._knowledge_view,
            self._concept_map_view,
            self._source_view,
            self._teach_view,
            self._learner_view,
            self._teacher_view,
        ]:
            self.content_stack.addWidget(v)

        # Wire ViewManager signals
        self._view_manager = ViewManager(self.content_stack)
        self._view_manager.register_views(
            [
                self._import_view,
                self._knowledge_view,
                self._concept_map_view,
                self._source_view,
                self._teach_view,
                self._learner_view,
                self._teacher_view,
            ]
        )
        self._view_manager.navigate_requested.connect(self.on_nav_click)
        self._view_manager.refresh_requested.connect(self._refresh_all_views)

        # First-run users need an actionable entry point.  The map remains the
        # home view once an asset exists, but an empty map is not a useful
        # starting screen.
        self.on_nav_click("concept_map" if self.assets else "import")
        self._update_topbar()

    # ---- topbar ----------------------------------------------------------------

    def _build_topbar(self):
        bar = QWidget()
        bar.setStyleSheet("background-color: white; border-bottom: 2px solid #E0E0E0;")
        bar.setFixedHeight(48)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(12)

        self._topbar_title = QLabel()
        self._topbar_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #1F2933;"
        )
        lay.addWidget(self._topbar_title)

        self._topbar_progress = QLabel()
        self._topbar_progress.setStyleSheet("color: #6B7A90; font-size: 13.5px;")
        lay.addWidget(self._topbar_progress)

        lay.addStretch()

        # Language switcher
        self._lang_combo = QComboBox()
        for _code, _name in LANGS.items():
            self._lang_combo.addItem(_name, _code)
        _lang_idx = self._lang_combo.findData(get_lang())
        if _lang_idx >= 0:
            self._lang_combo.setCurrentIndex(_lang_idx)
        self._lang_combo.setStyleSheet(
            "QComboBox { border: 1px solid #E0E0E0; border-radius: 4px;"
            "padding: 3px 8px; font-size: 13.5px; background-color: white; }"
        )
        self._lang_combo.currentIndexChanged.connect(self._apply_language)
        lay.addWidget(QLabel(_t("lang") + ": "))
        lay.addWidget(self._lang_combo)

        # Shortcut buttons
        for label, view in [
            ("📖 " + _t("btn_teach"), "teach"),
            ("🗺️ " + _t("btn_map"), "concept_map"),
            ("📄 " + _t("btn_source"), "source"),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "QPushButton { background-color: transparent; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px;"
                "padding: 5px 12px; font-size: 14px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            btn.clicked.connect(lambda checked, v=view: self.on_nav_click(v))
            lay.addWidget(btn)

        return bar

    def _update_topbar(self):
        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            title = (
                data.get("title") or data.get("source_name") or self.current_asset_id
            )
            stats = self._compute_stats()
            self._topbar_title.setText(f"📚 {title}")
            self._topbar_progress.setText(
                _t(
                    "topbar_progress",
                    m=stats["mastered"],
                    t=stats["total"],
                    l=stats["learning"],
                    r=len(due_for_review(self.learner, asset=self.get_asset())),
                )
            )
        else:
            self._topbar_title.setText(_t("app_name"))
            self._topbar_progress.setText("")

    # ---- sidebar ----------------------------------------------------------------

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background-color: #1A237E;")
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Logo area
        logo = QWidget()
        logo.setStyleSheet("background-color: #0D1B4C; padding: 18px 0 12px;")
        logo_lay = QVBoxLayout(logo)
        logo_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lay.setSpacing(2)
        icon_lbl = QLabel("🧠")
        icon_lbl.setStyleSheet("font-size: 30px; text-align: center;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lay.addWidget(icon_lbl)
        name_lbl = QLabel("ExpertAnything")
        name_lbl.setStyleSheet(
            "color: white; font-size: 15px; font-weight: bold; text-align: center;"
        )
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lay.addWidget(name_lbl)
        lay.addWidget(logo)

        # Primary nav
        nav = QWidget()
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(8, 12, 8, 0)
        nav_lay.setSpacing(4)
        self._nav_buttons: dict[str, QPushButton] = {}
        for icon, label, view in [
            ("🗺️", "nav_map", "concept_map"),
            ("📖", "nav_teach", "teach"),
            ("📥", "nav_import", "import"),
        ]:
            btn = QPushButton(f"{icon}  {self._t(label)}")
            btn.setStyleSheet(
                "QPushButton { background-color: transparent; color: white;"
                "text-align: left; padding: 10px 14px; border: none;"
                "border-radius: 6px; font-size: 15px; }"
                "QPushButton:hover { background-color: #3949AB; }"
                "QPushButton:checked { background-color: #3949AB;"
                "border-left: 3px solid #80D8FF; padding-left: 11px; }"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, v=view: self.on_nav_click(v))
            self._nav_buttons[view] = btn
            nav_lay.addWidget(btn)
        lay.addWidget(nav)

        # Divider
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet("background-color: #3949AB; margin: 8px 16px;")
        lay.addWidget(div)

        # Secondary nav
        sec = QWidget()
        sec_lay = QVBoxLayout(sec)
        sec_lay.setContentsMargins(8, 0, 8, 0)
        sec_lay.setSpacing(4)
        for icon, label, view in [
            ("📊", "nav_knowledge", "knowledge"),
            ("📄", "nav_source", "source"),
            ("🧠", "nav_learner", "learner"),
            ("👨‍🏫", "nav_teacher", "teacher"),
        ]:
            btn = QPushButton(f"{icon}  {self._t(label)}")
            btn.setStyleSheet(
                "QPushButton { background-color: transparent; color: #9FA8DA;"
                "text-align: left; padding: 8px 14px; border: none;"
                "border-radius: 6px; font-size: 14.5px; }"
                "QPushButton:hover { background-color: #283593; color: white; }"
                "QPushButton:checked { background-color: #283593; color: white;"
                "border-left: 3px solid #80D8FF; padding-left: 11px; }"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, v=view: self.on_nav_click(v))
            self._nav_buttons[view] = btn
            sec_lay.addWidget(btn)
        lay.addWidget(sec)

        # Asset list
        self._asset_list_widget = QWidget()
        al_lay = QVBoxLayout(self._asset_list_widget)
        al_lay.setContentsMargins(8, 12, 8, 8)
        al_lay.setSpacing(4)
        al_title = QLabel(_t("nav_assets"))
        al_title.setStyleSheet("color: #7986CB; font-size: 12.5px; font-weight: bold;")
        al_lay.addWidget(al_title)
        self._asset_list_layout = al_lay
        self._asset_buttons: dict = {}
        lay.addWidget(self._asset_list_widget, 1)
        self._refresh_asset_list()

        return sidebar

    # ---- view building ---------------------------------------------------------

    def _build_import_view(self):
        view = ImportView(self)
        view.asset_extracted.connect(self._on_asset_extracted)
        view.teacher_built.connect(self._on_teacher_built)
        view.navigate_requested.connect(self.on_nav_click)
        self._import_view = view
        self.import_view = view

    def _build_knowledge_view(self):
        view = KnowledgeView(self)
        view.teach_requested.connect(self._on_teach_request)
        view.topic_teach_requested.connect(self._on_topic_teach_request)
        view.open_concept_panel.connect(self._on_open_concept_panel)
        view.focus_graph.connect(self._on_focus_graph)
        self._knowledge_view = view
        self.knowledge_view = view
        # Compatibility attribute used by tests and external callers.
        self._dash_graph = view._dash_graph

    def _build_concept_map_view(self):
        view = ConceptMapView(self)
        view.teach_requested.connect(self._on_teach_request)
        view.open_concept_panel.connect(self._on_open_concept_panel)
        view.navigate_source.connect(self._on_jump_to_evidence)
        view.quick_quiz_requested.connect(self._on_quick_quiz_request)
        self._concept_map_view = view
        self.concept_map_view = view

    def _build_source_view(self):
        view = SourceView(self)
        view.open_concept_panel.connect(self._on_open_concept_panel)
        view.teach_requested.connect(self._on_teach_request)
        self._source_view = view
        self.source_view = view
        self._source_view_widget = view._source_widget

    def _build_teach_view(self):
        view = TeachView(self)
        view.teach_started.connect(self._on_teach_started)
        view.stuck_detected.connect(self._on_stuck_detected)
        view.followup_done.connect(self._on_followup_done)
        view.harness_adopted.connect(self._on_adopt_harness)
        view.harness_transferred.connect(self._on_transfer_harness)
        view.evaluate_recorded.connect(self._on_evaluate_recorded)
        self._teach_view = view
        self.teach_view = view
        self._teach_graph = view._graph

    def _build_learner_view(self):
        view = LearnerView(self)
        view.teach_requested.connect(self._on_teach_request)
        view.review_all_requested.connect(self._on_review_all_request)
        view.export_report.connect(self._on_export_report)
        view.export_html.connect(self._on_export_html)
        self._learner_view = view
        self.learner_view = view

    def _build_teacher_view(self):
        view = TeacherView(self)
        view.open_concept_panel.connect(self._on_open_concept_panel)
        self._teacher_view = view
        self.teacher_view = view

    # ---- knowledge graph helpers -----------------------------------------------

    def _teach_graph_ref(self) -> KnowledgeGraphView:
        if self._teach_graph is None:
            self._teach_graph = KnowledgeGraphView()
            self._teach_graph.concept_clicked.connect(self._on_graph_teach_click)
            self._teach_graph.node_single_clicked.connect(self._on_graph_node_clicked)
        return self._teach_graph

    def _dash_graph_ref(self) -> KnowledgeGraphView:
        # The dashboard graph belongs to KnowledgeView.  A rebuilt view must
        # always receive a fresh QObject; retaining the old C++ wrapper after
        # deleteLater() leaves MainWindow pointing at an invalid object.
        graph = KnowledgeGraphView()
        graph.concept_clicked.connect(self._on_graph_teach_click)
        graph.node_single_clicked.connect(self._on_graph_node_clicked)
        return graph

    def _graph_view_ref(self) -> KnowledgeGraphView:
        if self._graph_view is None:
            self._graph_view = KnowledgeGraphView()
            self._graph_view.concept_clicked.connect(self._on_graph_teach_click)
            self._graph_view.node_single_clicked.connect(self._on_graph_node_clicked)
        return self._graph_view

    def _path_ladder_ref(self) -> PathLadderView:
        if self._path_ladder is None:
            self._path_ladder = PathLadderView()
            self._path_ladder.concept_clicked.connect(self._on_graph_teach_click)
        return self._path_ladder

    def _map_detail_ref(self) -> NodeDetailCard:
        if self._map_detail is None:
            self._map_detail = NodeDetailCard()
        return self._map_detail

    # ---- navigation & view switching -------------------------------------------

    VIEW_MAP = {
        "import": 0,
        "knowledge": 1,
        "concept_map": 2,
        "source": 3,
        "teach": 4,
        "learner": 5,
        "teacher": 6,
    }

    def on_nav_click(self, view_name: str):
        idx = self.VIEW_MAP.get(view_name)
        if idx is not None:
            self.content_stack.setCurrentIndex(idx)
            for name, button in getattr(self, "_nav_buttons", {}).items():
                button.setChecked(name == view_name)
            # A view can be hidden while learning state changes.  Refresh on
            # entry so path completion, mastery colours and review counts are
            # never stale when the learner returns to that page.
            view = self.content_stack.widget(idx)
            if view is not None and hasattr(view, "refresh"):
                view.refresh()

    def _on_teach_request(self, concept_name: str):
        self.on_nav_click("teach")
        # Highlight teaching context on the knowledge graph so the learner
        # sees "where am I, what leads here, what comes next" at a glance.
        asset = self.get_asset()
        if asset:
            c = asset.concept_by_name(concept_name)
            if c:
                gv = self._graph_view_ref()
                gv.set_teaching_context(c.id)
        if hasattr(self, "_teach_view"):
            self._teach_view.start_teach_by_name(concept_name)

    def _on_quick_quiz_request(self, concept_id: str):
        """Launch a quick self-test quiz for a concept from the map detail card.

        Switches to the teach view and starts a quiz directly — 30-second
        check without a full lesson, lowering the friction of self-testing.
        """
        asset = self.get_asset()
        if asset is None:
            return
        c = asset.concept_by_id(concept_id)
        if c is None:
            return
        self.on_nav_click("teach")
        # Highlight teaching context on the graph
        gv = self._graph_view_ref()
        gv.set_teaching_context(concept_id)
        # Delegate to teach view: start a quick quiz
        if hasattr(self, "_teach_view"):
            self._teach_view.start_quick_quiz_by_name(c.name)

    def _on_topic_teach_request(
        self, concept_name: str, topic_name: str,
        queue_names: list, mastered_count: int,
    ):
        """Start teaching a concept as part of a topic learning pack.

        The teach view shows a topic progress banner (e.g. "3 / 8 完成")
        so the learner has a sense of progress through the topic cluster.
        """
        self.on_nav_click("teach")
        # Highlight teaching context on the graph
        asset = self.get_asset()
        if asset:
            c = asset.concept_by_name(concept_name)
            if c:
                gv = self._graph_view_ref()
                gv.set_teaching_context(c.id)
        if hasattr(self, "_teach_view"):
            self._teach_view.start_topic_teach(
                concept_name, topic_name, queue_names, mastered_count
            )

    def _on_review_all_request(self, concept_names: list):
        """Start a continuous review session for all due concepts.

        Hands the queue to the teach view's topic mechanism (reused as a
        generic sequential lesson pack) with a "review" label so the
        learner sees a progress banner while reviewing.
        """
        if not concept_names:
            return
        self.on_nav_click("teach")
        if hasattr(self, "_teach_view"):
            self._teach_view.start_topic_teach(
                concept_names[0],
                self._t("review_session_title"),
                concept_names,
                0,
            )

    # ---- delegation to extracted views (compatibility shim) -------------------
    # These methods delegate to the view classes that were extracted from
    # MainWindow.  They exist so that tests and external callers that reference
    # MainWindow directly continue to work during the transition period.

    @property
    def _topbar_asset(self):
        """Alias for _topbar_title (tests expect _topbar_asset)."""
        return self._topbar_title

    def _show_teaching_content(self, concept, vary=0, style=None):
        """Delegate to TeachView."""
        self._teach_view._show_teaching_content(concept, vary=vary, style=style)

    def _display_teach_result(self, result):
        """Delegate to TeachView._display_result."""
        self._teach_view._display_result(result)

    @property
    def _teach_concept_now(self):
        """Delegate to TeachView's current concept."""
        return getattr(self._teach_view, "_teach_concept_now", "")

    @_teach_concept_now.setter
    def _teach_concept_now(self, value):
        self._teach_view._teach_concept_now = value

    def _start_topic(self, hub_cid):
        """Delegate to KnowledgeView._start_topic."""
        self._knowledge_view._start_topic(hub_cid)

    def _find_transfer_candidates(self, asset):
        """Find harnesses worth migrating from *other* assets onto this one."""
        out: list[dict] = []
        if asset is None:
            return out
        for src_aid, spec in self._harness_specs.items():
            if src_aid == asset.asset_id:
                continue
            src_data = self.assets.get(src_aid)
            if not src_data:
                continue
            src_asset = self.get_asset(src_aid)
            if src_asset is None:
                continue
            ev = _ah.evaluate_transfer(
                spec,
                src_asset,
                asset,
                learner_state=self.learner,
                local_spec=self._harness_specs.get(asset.asset_id),
            )
            if ev.get("recommendation") == "migrate":
                diff = (ev.get("comparison") or {}).get("diff") or 0.0
                out.append(
                    {
                        "source_asset_id": src_aid,
                        "source_title": src_data.get("title", src_aid),
                        "spec": spec,
                        "evaluation": ev,
                        "gain": round(float(diff), 4),
                    }
                )
        out.sort(key=lambda x: x["gain"], reverse=True)
        return out

    # ---- concept panel ---------------------------------------------------------

    def _on_open_concept_panel(self, concept_id: str):
        """Open the concept detail panel for a concept id."""
        self._open_concept_panel(concept_id)

    def _open_concept_panel(self, concept_id: str):
        asset = self.get_asset()
        if asset is None:
            return
        if self._concept_panel is not None:
            try:
                self._concept_panel.close()
            except Exception:
                pass
        teacher = None
        td = self.teacher_models.get(self.current_asset_id)
        if td:
            try:
                teacher = TeacherModel.from_dict(td)
            except Exception:
                teacher = None
        panel = ConceptDetailPanel(
            asset,
            concept_id,
            self.learner,
            teacher,
            self,
        )
        panel.teach_requested.connect(self._on_teach_request)
        panel.focus_requested.connect(self._on_focus_graph)
        panel.evidence_requested.connect(self._on_jump_to_evidence)
        panel.incorporate_requested.connect(self._on_incorporate_comparison)
        panel.show()
        self._concept_panel = panel

    def _on_focus_graph(self, concept_id: str):
        self.on_nav_click("concept_map")
        if hasattr(self, "_concept_map_view"):
            # All concept entry points converge on the same persistent
            # map+inspector workspace. Avoid opening a modal panel here: the
            # selected node and its grounded details stay visible together.
            self._concept_map_view.focus_and_show(concept_id)

    def _on_jump_to_evidence(self, concept_id: str, evidence: str = ""):
        self.on_nav_click("source")
        if self._source_view_widget:
            self._source_view_widget.scroll_to_concept(concept_id)

    def _on_graph_teach_click(self, concept_name: str):
        self._on_teach_request(concept_name)

    def _on_graph_node_clicked(self, concept_id: str):
        pass

    def _on_incorporate_comparison(self, a_id: str, b_id: str):
        asset = self.get_asset()
        if asset is None:
            return
        teacher = None
        td = self.teacher_models.get(self.current_asset_id)
        if td:
            try:
                teacher = TeacherModel.from_dict(td)
            except Exception:
                teacher = None
        teacher = incorporate_comparison(
            asset,
            teacher,
            a_id,
            b_id,
            self.learner,
        )
        save_teacher(self.current_asset_id, teacher)
        self.teacher_models[self.current_asset_id] = teacher.to_dict()

    # ---- teaching flow ---------------------------------------------------------

    def _on_teach_started(self, concept_name: str):
        self._refresh_all_views()

    def _on_stuck_detected(self, concept_name: str, stuck_info: object):
        self._refresh_all_views()
        self._offer_harness_evolution(concept_name, stuck_info)
        self._offer_harness_transfer_cards()

    def _offer_harness_transfer_cards(self):
        """Stuck signal → cross-asset migration candidates → light-blue cards.

        Reuses _find_transfer_candidates (eligibility gate → differential
        OFF/ON evaluation → migrate/no_change verdict). Only "migrate"
        verdicts become cards, at most 2 per run per (target, source, spec)
        signature — the differential evaluation itself is a local
        deterministic simulation (no LLM), so running it on stuck is cheap.
        """
        try:
            asset = self.get_asset()
            if asset is None:
                return
            shown = getattr(self, "_transfer_offer_shown", None)
            if shown is None:
                shown = self._transfer_offer_shown = set()
            # skip the evaluation entirely when every source spec was
            # already offered (and dismissed) this session
            fresh = [
                aid
                for aid, spec in self._harness_specs.items()
                if aid != asset.asset_id
                and self.assets.get(aid)
                and (asset.asset_id, aid, spec.get("name", "")) not in shown
            ]
            if not fresh:
                return
            w = getattr(self._teach_view, "_teach_view_widget", None)
            if w is None or not hasattr(w, "append_transfer_suggestion"):
                return
            for cand in self._find_transfer_candidates(asset)[:2]:
                ev = cand.get("evaluation") or {}
                diff = (ev.get("comparison") or {}).get("diff")
                gain = cand.get("gain") if diff is not None else ev.get(
                    "coverage_diff", 0.0
                )
                sig = (
                    asset.asset_id,
                    cand.get("source_asset_id", ""),
                    (cand.get("spec") or {}).get("name", ""),
                )
                if sig in shown:
                    continue
                shown.add(sig)
                body = _t(
                    "harness_transfer_body",
                    source=cand.get("source_title", ""),
                    name=(cand.get("spec") or {}).get("name", "?"),
                    gain=f"{float(gain):+.2f}",
                    cost=ev.get("cost_diff", 0),
                )
                w.append_transfer_suggestion(_t("harness_transfer_title"), body, cand)
        except Exception:
            pass

    def _offer_harness_evolution(self, concept_name: str, stuck_info=None):
        """Stuck signal → joint evolution → suggestion card in the teach view.

        Closes the AGENTS.md §12 loop: evolve_joint produces the candidate
        (all signal layers fused, check_harness-admitted), the result view
        renders it as an amber/purple/cyan card, one click re-teaches.
        Session-level dedup: the same (asset, concept, reason, candidate)
        is only offered once per run — repeated weak evaluations must not
        spam identical cards.
        """
        try:
            asset = self.get_asset()
            if asset is None or not concept_name:
                return
            spec = self._harness_specs.get(asset.asset_id) or _ah.fallback_harness()
            reports = _ah.load_session_reports(
                config.DATA_DIR / "harness_state.json"
            )
            res = _ah.evolve_joint(
                spec, self.learner, reports=reports, concept_name=concept_name
            )
            if not res.get("evolved"):
                return
            cands = res.get("candidates") or []
            if not cands:
                return
            cand = cands[0]
            reason = res.get("reason", "stuck")
            focused = res.get("focused") or {}
            concept = focused.get("name") or concept_name
            fallback_attempts = 3
            if isinstance(stuck_info, dict):
                fallback_attempts = stuck_info.get("attempts", 3)
            attempts = focused.get("attempts") or fallback_attempts
            sig = (asset.asset_id, concept, reason, cand.get("name", ""))
            if getattr(self, "_harness_offer_shown", None) is None:
                self._harness_offer_shown = set()
            if sig in self._harness_offer_shown:
                return
            self._harness_offer_shown.add(sig)

            summary = _ah.harness_summary(cand)
            if reason == "regression":
                src = "regression"
                title = _t("harness_regress_title")
                body = _t(
                    "harness_regress_body",
                    concept=concept,
                    before=f"{focused.get('before_avg', 0):.2f}",
                    after=f"{focused.get('after_avg', 0):.2f}",
                    attempts=attempts,
                )
                extra = None
            elif reason in ("stuck", "sessions"):
                src = "stuck"
                title = _t("harness_suggest_title")
                body = _t(
                    "harness_suggest_body",
                    concept=concept,
                    attempts=attempts,
                    summary=summary,
                )
                extra = None
            else:
                src = "joint"
                title = _t("harness_joint_title")
                body = _t(
                    "harness_joint_body",
                    concept=concept,
                    reason=reason,
                    summary=summary,
                    diag="；".join(res.get("diagnosis", [])),
                )
                extra = {"_joint_reason": reason}
            w = getattr(self._teach_view, "_teach_view_widget", None)
            if w is not None and hasattr(w, "append_harness_suggestion"):
                w.append_harness_suggestion(title, body, cand, source=src, extra=extra)
        except Exception:
            pass

    def _on_followup_done(self, question: str, answer: str):
        pass

    def _on_adopt_harness(self, candidate):
        """Adopt an AutoHarness evolution candidate: persist + re-teach."""
        try:
            asset = self.get_asset()
            if asset is None:
                return
            src = ""
            joint_reason = ""
            if isinstance(candidate, dict):
                src = candidate.pop("_source", "")
                joint_reason = candidate.pop("_joint_reason", "")
            spec = candidate
            old_spec = self._harness_specs.get(asset.asset_id)
            self._harness_specs[asset.asset_id] = spec
            _ah.save_harness_state(
                config.DATA_DIR / "harness_state.json", self._harness_specs
            )
            concept_now = getattr(self, "_teach_concept_now", "")
            if src == "regression":
                reason = "regression"
            elif src == "joint":
                reason = joint_reason or "joint"
            elif src == "stuck":
                reason = "stuck"
            else:
                reason = "manual"
            self._harness_history = _ah.record_harness_evolution(
                config.DATA_DIR / "harness_state.json",
                _ah.evolution_event(
                    reason,
                    old_spec,
                    spec,
                    asset_id=asset.asset_id,
                    concept=concept_now,
                ),
            )
            QMessageBox.information(
                self,
                _t("harness_suggest_title"),
                _t("harness_adopted", name=spec.get("name", "?"), concept=concept_now),
            )
            style = spec.get("policy", {}).get("style")
            concept = asset.concept_by_name(concept_now) if concept_now else None
            if concept is not None and style:
                self._show_teaching_content(concept, vary=1, style=style)
        except Exception as exc:
            QMessageBox.warning(self, _t("hint"), str(exc))

    def _on_transfer_harness(self, payload):
        """Adopt a harness migrated from another asset."""
        try:
            asset = self.get_asset()
            if asset is None:
                return
            spec = payload.get("spec") or {}
            source_id = payload.get("source_asset_id", "")
            concept_now = getattr(self, "_teach_concept_now", "")
            path = config.DATA_DIR / "harness_state.json"
            ok, _event = _ah.adopt_harness_for_asset(
                path,
                asset.asset_id,
                spec,
                source_asset_id=source_id,
                concept=concept_now,
            )
            if not ok:
                QMessageBox.warning(self, _t("hint"), _t("harness_none"))
                return
            self._harness_specs[asset.asset_id] = spec
            self._harness_history = _ah.load_harness_history(path)
            source_title = payload.get("source_title", source_id)
            QMessageBox.information(
                self,
                _t("harness_transfer_title"),
                _t(
                    "harness_transfer_adopted",
                    name=spec.get("name", "?"),
                    source=source_title,
                    concept=concept_now,
                ),
            )
            style = spec.get("policy", {}).get("style")
            concept = asset.concept_by_name(concept_now) if concept_now else None
            if concept is not None and style:
                self._show_teaching_content(concept, vary=1, style=style)
        except Exception as exc:
            QMessageBox.warning(self, _t("hint"), str(exc))

    def _on_evaluate_recorded(self):
        self.save_learner_state()
        self._refresh_all_views()

    # ---- asset management ------------------------------------------------------

    def _on_asset_extracted(self, asset):
        pass  # ImportView handles everything

    def _on_teacher_built(self, teacher):
        pass  # ImportView handles everything

    def on_asset_select(self, asset_id: str):
        self.current_asset_id = asset_id
        self._refresh_asset_list()
        self._rebuild_all_views()
        self.on_nav_click("concept_map")

    def _refresh_asset_list(self):
        if not hasattr(self, "_asset_buttons"):
            return
        while self._asset_list_layout.count():
            item = self._asset_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._asset_buttons = {}
        for aid, data in self.assets.items():
            title = data.get("title") or data.get("source_name") or aid
            count = len(data.get("concepts", []))
            btn = QPushButton(
                f"📚 {title[:22]}{'...' if len(title) > 22 else ''}  · {count}"
            )
            btn.setToolTip(_t("asset_tooltip", title=title, count=count))
            btn.setStyleSheet(
                "QPushButton { background-color: transparent; color: #BBDEFB;"
                "text-align: left; padding: 8px 12px; border: none;"
                "border-radius: 4px; font-size: 14px; }"
                "QPushButton:hover { background-color: #283593; }"
                "QPushButton:checked { background-color: #3949AB; }"
            )
            btn.setCheckable(True)
            btn.setChecked(aid == self.current_asset_id)
            btn.clicked.connect(lambda checked, a=aid: self.on_asset_select(a))
            self._asset_buttons[aid] = btn
            self._asset_list_layout.addWidget(btn)

    def _rebuild_all_views(self):
        """Clear and rebuild every data-dependent view.

        Fully rebuilds all 7 views (like the original code) so that graph
        widgets, concept panels, and other lazy-created references are
        fresh after an asset switch or language change.
        """
        # Remember which view was visible
        prev_idx = (
            self.content_stack.currentIndex() if hasattr(self, "content_stack") else 2
        )

        # Clear stale widget refs BEFORE rebuilding so no handler can touch
        # a deleted object
        for attr in [
            "_concept_panel",
            "_teach_answer_input",
            "_teach_graph",
            "_dash_graph",
            "_graph_view",
            "_source_view_widget",
            "_map_detail",
            "_path_ladder",
        ]:
            setattr(self, attr, None)

        # Remove the old widget tree before constructing replacements.  Some
        # extracted views own QObjects also exposed through MainWindow
        # compatibility attributes; building first could re-parent a new shared
        # widget into an old view that is about to be deleted.
        while self.content_stack.count():
            w = self.content_stack.widget(0)
            self.content_stack.removeWidget(w)
            w.deleteLater()

        # Build fresh views
        self._build_import_view()
        self._build_knowledge_view()
        self._build_concept_map_view()
        self._build_source_view()
        self._build_teach_view()
        self._build_learner_view()
        self._build_teacher_view()
        # View constructors may trigger nested Qt layout ownership changes;
        # publish the final live graph after the complete view tree exists.
        self._dash_graph = self._knowledge_view._dash_graph

        for v in [
            self._import_view,
            self._knowledge_view,
            self._concept_map_view,
            self._source_view,
            self._teach_view,
            self._learner_view,
            self._teacher_view,
        ]:
            self.content_stack.addWidget(v)

        # Re-register views with ViewManager
        if self._view_manager:
            self._view_manager.register_views(
                [
                    self._import_view,
                    self._knowledge_view,
                    self._concept_map_view,
                    self._source_view,
                    self._teach_view,
                    self._learner_view,
                    self._teacher_view,
                ]
            )

        # Restore visible view
        self.content_stack.setCurrentIndex(
            min(prev_idx, self.content_stack.count() - 1)
        )

        self._update_topbar()
        self._refresh_asset_list()
        self._update_lang_combo()

    # ---- language --------------------------------------------------------------

    def _t(self, key, **kw) -> str:
        return _t(key, **kw)

    def _get_lang(self) -> str:
        return get_lang()

    def _update_lang_combo(self):
        if hasattr(self, "_lang_combo"):
            self._lang_combo.blockSignals(True)
            idx = self._lang_combo.findData(get_lang())
            if idx >= 0:
                self._lang_combo.setCurrentIndex(idx)
            self._lang_combo.blockSignals(False)

    def _apply_language(self, _idx: int = 0):
        code = self._lang_combo.currentData()
        if not code or code == get_lang():
            return
        set_lang(code)
        save_lang()

        # Rebuild topbar
        new_bar = self._build_topbar()
        old_bar = self._topbar
        old_bar.parent().layout().replaceWidget(old_bar, new_bar)
        old_bar.deleteLater()
        self._topbar = new_bar
        self.topbar = new_bar

        # Rebuild sidebar
        new_sb = self._build_sidebar()
        old_sb = self._sidebar
        old_sb.parent().layout().replaceWidget(old_sb, new_sb)
        old_sb.deleteLater()
        self._sidebar = new_sb

        # Rebuild all views
        self._rebuild_all_views()

    # ---- report export ---------------------------------------------------------

    def _on_export_report(self):
        text = build_html_report(self.assets, self.learner, localized=False)
        path = config.DATA_DIR / "report.txt"
        path.write_text(text, encoding="utf-8")
        QMessageBox.information(
            self,
            self._t("done"),
            self._t("report_saved", path=str(path)),
        )

    def _on_export_html(self):
        # Pass all assets so the report shows the full cross-asset table
        html = build_html_report(self.assets, self.learner, lang=self._get_lang())
        path = config.DATA_DIR / "report.html"
        path.write_text(html, encoding="utf-8")
        QMessageBox.information(
            self,
            self._t("done"),
            self._t("report_saved", path=str(path)),
        )

    # ---- helpers ----------------------------------------------------------------

    def get_asset(self, asset_id: str | None = None) -> KnowledgeAsset | None:
        aid = asset_id or self.current_asset_id
        if not aid or aid not in self.assets:
            return None
        data = self.assets[aid]
        try:
            return self._dict_to_asset(aid, data)
        except Exception:
            return None

    def _dict_to_asset(self, aid: str, data: dict) -> KnowledgeAsset:
        cached = self._asset_object_cache.get(aid)
        if cached is not None and cached[0] is data:
            return cached[1]
        chapters = [Chapter.from_dict(c) for c in data.get("chapters", [])]
        concepts = [Concept.from_dict(c) for c in data.get("concepts", [])]
        relations = [Relation.from_dict(r) for r in data.get("relations", [])]
        asset = KnowledgeAsset(
            asset_id=aid,
            type=data.get("type", "article"),
            title=data.get("title", ""),
            source_name=data.get("source_name", ""),
            created_at=data.get("created_at", ""),
            source_text=data.get("source_text", ""),
            chapters=chapters,
            concepts=concepts,
            relations=relations,
            learning_path=data.get("learning_path", []),
            method=data.get("method", "unknown"),
            source_length=0,
        )
        self._asset_object_cache[aid] = (data, asset)
        return asset

    def get_adaptive_path(self, asset_id: str):
        asset = self.get_asset(asset_id)
        if asset is None:
            return []
        return adaptive_path(asset, self.learner)

    def _compute_stats(self) -> dict:
        mastered = learning = unstudied = 0
        anomaly_count = 0
        for c in self.get_asset().concepts if self.get_asset() else []:
            norm = normalize(c.name)
            m = self.learner.get("concepts", {}).get(norm, {}).get("mastery", 0.0)
            if m >= 0.6:
                mastered += 1
            elif m > 0:
                learning += 1
            else:
                unstudied += 1
        td = self.teacher_models.get(self.current_asset_id or "", {})
        anomaly_count = len(td.get("anomalies", []))
        total = mastered + learning + unstudied
        return dict(
            total=total,
            mastered=mastered,
            learning=learning,
            unstudied=unstudied,
            anomalies=anomaly_count,
        )

    def _next_concept(self):
        """Return (next Concept to learn, mastery)."""
        asset = self.get_asset()
        if asset is None:
            return None, 0.0
        entry = self.learner.get("assets", {}).get(self.current_asset_id, {})
        completed = set(entry.get("completed", []))
        path = self.get_adaptive_path(self.current_asset_id)
        for item in path:
            cid = item.get("cid")
            if cid and cid not in completed:
                c = asset.concept_by_id(cid)
                if c is not None:
                    m = (
                        self.learner.get("concepts", {})
                        .get(normalize(c.name), {})
                        .get("mastery", 0.0)
                    )
                    return c, m
        return None, 0.0

    def save_learner_state(self):
        save_learner(self.learner)

    def _refresh_all_views(self):
        self._update_topbar()
        idx = self.content_stack.currentIndex()
        if idx == 1 and hasattr(self, "_knowledge_view"):  # knowledge
            self._knowledge_view.refresh()
        elif idx == 2 and hasattr(self, "_concept_map_view"):  # concept map
            self._concept_map_view.refresh()
        elif idx == 3 and hasattr(self, "_source_view"):  # source
            self._source_view.refresh()
        elif idx == 4 and hasattr(
            self, "_teach_view"
        ):  # teach: rebuild style combo i18n
            self._teach_view.refresh()
        elif idx == 5 and hasattr(self, "_learner_view"):  # learner
            self._learner_view.refresh()

    # ---- global concept graph --------------------------------------------------

    def _build_global_asset(self) -> tuple[KnowledgeAsset, set]:
        """Merge all assets into one for the all-knowledge graph."""
        cache_key = (
            tuple((aid, id(data)) for aid, data in self.assets.items()),
            self.current_asset_id,
            id(self.teacher_models.get(self.current_asset_id or "")),
        )
        if self._global_asset_cache is not None:
            old_key, cached_asset, cached_grey = self._global_asset_cache
            if old_key == cache_key:
                return cached_asset, cached_grey

        all_concepts = []
        all_relations = []
        all_chapters = []
        next_offset = 0
        grey_ids = set()

        for aid, data in self.assets.items():
            try:
                asset = self._dict_to_asset(aid, data)
            except Exception:
                continue
            prefix = f"{aid}:" if len(self.assets) > 1 else ""
            seen_ids = set()
            for c in asset.concepts:
                cid = f"{prefix}{c.id}"
                all_concepts.append(
                    Concept(
                        id=cid,
                        name=c.name,
                        definition=c.definition,
                        summary=c.summary,
                        evidence=c.evidence,
                        chapter=c.chapter,
                        locations=c.locations,
                    )
                )
                seen_ids.add(c.id)
                if aid != self.current_asset_id:
                    grey_ids.add(cid)
            for r in asset.relations:
                if r.source in seen_ids and r.target in seen_ids:
                    all_relations.append(
                        Relation(
                            id=str(uuid.uuid4()),
                            source=f"{prefix}{r.source}",
                            target=f"{prefix}{r.target}",
                            label=r.label,
                            type=r.type,
                            evidence=r.evidence,
                        )
                    )

        # Shared-concept edges between same-normalized names
        norm_map: dict = {}
        for c in all_concepts:
            k = normalize(c.name)
            norm_map.setdefault(k, []).append(c.id)
        for ids in norm_map.values():
            if len(ids) > 1:
                for aid_ in ids:
                    for bid in ids:
                        if aid_ < bid:
                            all_relations.append(
                                Relation(
                                    id=str(uuid.uuid4()),
                                    source=aid_,
                                    target=bid,
                                    label=self._t("edge_shared"),
                                    type="shared_concept",
                                    evidence="",
                                )
                            )

        # Teacher external concepts
        td = self.teacher_models.get(self.current_asset_id or "", {})
        for note in td.get("concept_notes", []):
            for ext in note.get("external_concepts", []):
                ext_id = f"ext:{ext}"
                if not any(c.id == ext_id for c in all_concepts):
                    all_concepts.append(
                        Concept(
                            id=ext_id,
                            name=ext,
                            definition="",
                            summary="",
                            evidence="",
                            chapter="",
                            locations=[],
                        )
                    )
                    grey_ids.add(ext_id)
                    an = all_concepts[-1]
                    for cn in all_concepts:
                        if normalize(cn.name) == normalize(ext):
                            all_relations.append(
                                Relation(
                                    id=str(uuid.uuid4()),
                                    source=cn.id,
                                    target=ext_id,
                                    label=self._t("edge_external"),
                                    type="external",
                                    evidence="",
                                )
                            )

        # Teacher notes add prerequisite edges
        td2 = self.teacher_models.get(self.current_asset_id or "", {})
        for note in td2.get("concept_notes", []):
            cid = note.get("concept_id", "")
            for prereq in note.get("prerequisites", []):
                for c in all_concepts:
                    if normalize(c.name) == normalize(prereq):
                        all_relations.append(
                            Relation(
                                id=str(uuid.uuid4()),
                                source=c.id,
                                target=cid,
                                label=self._t("edge_prereq"),
                                type="prerequisite",
                                evidence="",
                            )
                        )
                        break
            for conn in note.get("connections", []):
                for c in all_concepts:
                    if normalize(c.name) == normalize(conn):
                        all_relations.append(
                            Relation(
                                id=str(uuid.uuid4()),
                                source=cid,
                                target=c.id,
                                label=self._t("edge_related"),
                                type="related",
                                evidence="",
                            )
                        )
                        break

        title = self._t("global_graph_title")
        global_asset = KnowledgeAsset(
            asset_id="global",
            type="global",
            title=title,
            source_name=title,
            created_at="",
            source_text="",
            chapters=all_chapters,
            concepts=all_concepts,
            relations=all_relations,
            learning_path=[],
            method="global_graph",
            source_length=0,
        )
        self._global_asset_cache = (cache_key, global_asset, grey_ids)
        return global_asset, grey_ids

    # ---- compare dialog -------------------------------------------------------

    def _open_compare(self, a_id: str, b_id: str):
        asset = self.get_asset()
        if asset is None:
            return
        teacher = None
        td = self.teacher_models.get(self.current_asset_id)
        if td:
            try:
                teacher = TeacherModel.from_dict(td)
            except Exception:
                teacher = None
        dlg = ConceptCompareDialog(asset, a_id, b_id, self.learner, teacher, self)
        dlg.teach_requested.connect(self._on_teach_request)
        dlg.incorporate_comparison.connect(self._on_incorporate_comparison)
        dlg.show()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("ExpertAnything")

    # Locale
    locale = QLocale.system().name()
    qt_trans = QTranslator()
    if qt_trans.load(
        f"qtbase_{locale}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(qt_trans)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
