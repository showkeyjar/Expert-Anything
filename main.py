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
    unregister_asset,
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
from expert_anything.ui import theme
from expert_anything.ui.pyside_graph import KnowledgeGraphView
from expert_anything.ui.widgets import (
    ConceptDetailPanel,
    ConceptCompareDialog,
    PathLadderView,
    SourceTextView,
    NodeDetailCard,
    MapLegend,
    TrendChartView,
    GuideBar,
    GroupQuizDialog,
    GlossaryDialog,
)
from expert_anything.ui.views import (
    ImportView,
    KnowledgeView,
    ConceptMapView,
    SourceView,
    TeachView,
    LearnerView,
    TeacherView,
    PanoramaView,
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
    # HarnessSpec policy styles (Chinese, auto_harness STYLE_CYCLE) → style
    # combo codes (TeachView._CODE_TO_IDX).
    _HARNESS_STYLE_CODES = {
        "例子": "example",
        "图示": "diagram",
        "拆解步骤": "steps",
    }

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
                    max_concurrency=config.LLM_MAX_CONCURRENCY,
                    timeout=config.LLM_TIMEOUT,
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

        # Heal stale anomaly statuses once per startup (AGENTS.md §34): a gap
        # the learner has since closed must not keep crying wolf in doubt
        # strips / teaching order.  Resolves only evidence-backed kinds and
        # persists only when something actually changed.
        try:
            from expert_anything.core.teacher import (
                TeacherModel,
                resolve_satisfied_anomalies,
            )

            for aid, tdata in list(self.teacher_models.items()):
                if not tdata or aid not in self.assets:
                    continue
                try:
                    asset = self.get_asset(aid)
                    if asset is None:
                        continue
                    tm = TeacherModel.from_dict(tdata)
                    if resolve_satisfied_anomalies(asset, tm, self.learner):
                        save_teacher(aid, tm)
                        self.teacher_models[aid] = tm.to_dict()
                except Exception:
                    continue
        except Exception:
            pass

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
        theme.apply_theme(app)

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self._sidebar = self._build_sidebar()
        root.addWidget(self._sidebar)

        # Main area: topbar + content stack (8 pages)
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

        # Build all 8 views
        self._build_import_view()
        self._build_knowledge_view()
        self._build_concept_map_view()
        self._build_source_view()
        self._build_teach_view()
        self._build_learner_view()
        self._build_teacher_view()
        self._build_panorama_view()
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
            self._panorama_view,
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
                self._panorama_view,
            ]
        )
        self._view_manager.navigate_requested.connect(self.on_nav_click)

        # First-run users need an actionable entry point.  The map remains the
        # home view once an asset exists, but an empty map is not a useful
        # starting screen.
        self.on_nav_click("concept_map" if self.assets else "import")
        self._update_topbar()

    # ---- topbar ----------------------------------------------------------------

    def _build_topbar(self):
        """Topbar = the original asset/progress row + the proactive guide bar.

        The second row is the coach's permanent voice (AGENTS.md §49): it lives
        outside the content stack so the主张 stays visible in every view.
        """
        bar = QWidget()
        bar.setStyleSheet(f"background-color: {theme.SURFACE};")

        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row = QWidget()
        row.setStyleSheet(
            f"background-color: {theme.SURFACE};"
            f" border-bottom: 1px solid {theme.DIVIDER};"
        )
        row.setFixedHeight(theme.TOPBAR_HEIGHT)
        outer.addWidget(row)

        self._guide_bar = GuideBar()
        self._guide_bar.start_requested.connect(self._on_guide_start)
        self._guide_bar.swap_requested.connect(
            lambda rec: self._on_guide_dismissed(rec, "swap")
        )
        self._guide_bar.dismiss_requested.connect(
            lambda rec: self._on_guide_dismissed(rec, "dismiss")
        )
        outer.addWidget(self._guide_bar)

        lay = QHBoxLayout(row)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(12)

        self._topbar_title = QLabel()
        self._topbar_title.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {theme.TEXT};"
        )
        lay.addWidget(self._topbar_title)

        self._topbar_progress = QLabel()
        self._topbar_progress.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12.5px;"
        )
        # Numbers here are "统计 chip" — they must lead somewhere (设计理念第 20
        # 条).  Rich text lets each segment be its own link without extra widgets.
        self._topbar_progress.setTextFormat(Qt.TextFormat.RichText)
        self._topbar_progress.setOpenExternalLinks(False)
        self._topbar_progress.linkActivated.connect(self._on_topbar_drill)
        lay.addWidget(self._topbar_progress)

        lay.addStretch()

        # Language switcher
        self._lang_combo = QComboBox()
        for _code, _name in LANGS.items():
            self._lang_combo.addItem(_name, _code)
        _lang_idx = self._lang_combo.findData(get_lang())
        if _lang_idx >= 0:
            self._lang_combo.setCurrentIndex(_lang_idx)
        self._lang_combo.setFixedWidth(112)
        self._lang_combo.setStyleSheet(
            f"QComboBox {{ border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; padding: 3px 8px;"
            " font-size: 12.5px; background-color: transparent; }"
            f"QComboBox:hover {{ border-color: {theme.BORDER_STRONG}; }}"
        )
        self._lang_combo.currentIndexChanged.connect(self._apply_language)
        lang_lbl = QLabel(_t("lang"))
        lang_lbl.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11.5px;"
        )
        lay.addWidget(lang_lbl)
        lay.addWidget(self._lang_combo)

        # Navigation lives in the sidebar only.  The topbar used to duplicate
        # three of those entries as "shortcut" buttons, which gave every screen
        # three competing entry points for the same action — the main reason
        # the shell read as crowded.

        return bar

    # ---- proactive guidance (AGENTS.md §49) --------------------------------

    def _refresh_guide_bar(self):
        """Recompute the single next主张 and show it in the guide bar.

        Reads the same signals the rest of the app trusts (adaptive_path /
        due_for_review / stuck / anomalies) via ``core.coach``; never raises
        into the UI — a coaching failure hides the strip.
        """
        bar = getattr(self, "_guide_bar", None)
        if bar is None:
            return
        try:
            from expert_anything.core.coach import recommend

            asset = self.get_asset()
            teacher = self.teacher_models.get(self.current_asset_id or "")
            rec = recommend(asset, self.learner, teacher)
            bar.set_recommendation(rec)
        except Exception:
            bar.set_recommendation(None)

    def _on_guide_start(self, rec: dict):
        """Accept the coach's主张: open teaching at exactly that concept.

        Review-shaped主张 route through the review entry point so the lesson is
        re-taught from a different angle instead of repeating the first lesson
        (AGENTS.md §6 — never double-open a course).
        """
        if not isinstance(rec, dict):
            return
        try:
            from expert_anything.core.coach import record_coach_feedback

            record_coach_feedback(self.learner, rec, "start")
            self.save_learner_state()
        except Exception:
            pass
        name = rec.get("concept_name") or ""
        if not name:
            # Asset-level主张 (no concept to teach): land the learner where the
            # next step lives rather than silently doing nothing.  "import" has
            # nothing to teach yet → the import view; "explore" means everything
            # is mastered → the concept map, where roaming is the point.
            self.on_nav_click(
                "concept_map" if rec.get("kind") == "explore" else "import"
            )
            return
        from expert_anything.core.coach import is_review

        if is_review(rec):
            self._on_review_one_request(name)
        else:
            self._on_teach_request(name)

    def _on_guide_dismissed(self, rec: dict, action: str = "dismiss"):
        """Record that the learner passed on a claim (``swap`` / ``dismiss``).

        This is what turns the guide bar from a broadcaster into a listener:
        repeated dismissals of one kind demote it (``coach.coach_fatigue``),
        while accepting a kind resets its run.  Persisting is best-effort — a
        feedback failure must never interrupt teaching.
        """
        try:
            from expert_anything.core.coach import record_coach_feedback

            record_coach_feedback(self.learner, rec, action)
            self.save_learner_state()
        except Exception:
            pass
        self._refresh_guide_bar()

    def _update_topbar(self):
        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            title = (
                data.get("title") or data.get("source_name") or self.current_asset_id
            )
            stats = self._compute_stats()
            self._topbar_title.setText(title)
            self._topbar_progress.setText(
                self._topbar_progress_html(
                    m=int(stats["mastered"]),
                    t=int(stats["total"]),
                    l=int(stats["learning"]),
                    r=len(due_for_review(self.learner, asset=self.get_asset())),
                )
            )
        else:
            self._topbar_title.setText(_t("app_name"))
            self._topbar_progress.setText("")
        # keep the coach strip in step with learner state (cheap, deterministic)
        self._refresh_guide_bar()

    # Sentinel used to mark the numeric slots of the progress template so they
    # can be swapped for links.  It never occurs in translation text.
    _DRILL_SENTINEL = "\x01"

    def _topbar_progress_html(self, m: int, t: int, l: int, r: int) -> str:
        """Progress line with clickable segments (设计理念第 20 条).

        已掌握 / 学习中 → 知识模型页并套用对应掌握度过滤；待复习 → 学习页复习队列。
        The i18n template stays untouched: sentinels mark the slots and are
        swapped for anchors, so a reordered or differently-spaced translation
        still links correctly (and never leaks a control character).
        """
        S = self._DRILL_SENTINEL

        def link(href: str, text, tip: str) -> str:
            return (
                f'<a href="{href}" title="{tip}" '
                f'style="color:{theme.ACCENT}; text-decoration:none;">{text}</a>'
            )

        mastered_tip = _t("filter_mastered")
        raw = _t(
            "topbar_progress",
            m=f"{S}M{S}",
            t=f"{S}T{S}",
            l=f"{S}L{S}",
            r=f"{S}R{S}",
        )
        # Preferred: keep "m/t" as one link; fall back to per-number links only
        # if a translation separates the pair.
        raw = raw.replace(
            f"{S}M{S}/{S}T{S}", link("drill:mastered", f"{m}/{t}", mastered_tip)
        )
        return (
            raw.replace(f"{S}M{S}", link("drill:mastered", m, mastered_tip))
            .replace(f"{S}T{S}", link("drill:mastered", t, mastered_tip))
            .replace(f"{S}L{S}", link("drill:learning", l, _t("filter_learning")))
            .replace(f"{S}R{S}", link("drill:due", r, _t("due_title", n=r)))
        )

    def _on_topbar_drill(self, href: str):
        """Topbar progress link → the list it summarises."""
        if href == "drill:due":
            self.on_nav_click("learner")
            return
        self.on_nav_click("knowledge")  # refresh() rebuilds the filter combo
        kv = getattr(self, "_knowledge_view", None)
        combo = getattr(kv, "_mastery_filter", None) if kv is not None else None
        if combo is not None:
            combo.setCurrentIndex(4 if href == "drill:mastered" else 3)

    # ---- sidebar ----------------------------------------------------------------

    @staticmethod
    def _nav_label(text: str) -> str:
        """Drop the decorative leading emoji from i18n nav labels.

        Emoji made sense in a prototype, but a light text-only rail is calmer
        and gives every language the same rhythm.  The i18n source keeps the
        emoji (it is also used for tooltips and tests).
        """
        head, sep, tail = str(text).partition(" ")
        if sep and tail and not head[:1].isalnum():
            return tail
        return str(text)

    def _build_sidebar(self):
        from expert_anything.ui.widgets._helpers import CollapsibleSection

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        sidebar.setStyleSheet(
            f"#sidebar {{ background-color: {theme.SURFACE};"
            f" border-right: 1px solid {theme.BORDER}; }}"
        )
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Brand: small accent tile + wordmark (the old 90px navy block with a
        # brain emoji consumed a fifth of the sidebar before any navigation).
        brand = QWidget()
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(18, 18, 18, 14)
        brand_lay.setSpacing(10)
        tile = QLabel("EA")
        tile.setFixedSize(30, 30)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setStyleSheet(
            f"background-color: {theme.ACCENT}; color: {theme.TEXT_ON_ACCENT};"
            f" border-radius: {theme.RADIUS_MD}px;"
            " font-size: 12.5px; font-weight: 700;"
        )
        brand_lay.addWidget(tile)
        name_lbl = QLabel("ExpertAnything")
        name_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: 700;"
        )
        brand_lay.addWidget(name_lbl)
        brand_lay.addStretch()
        lay.addWidget(brand)

        # Primary nav (小白核心路径：4 个入口)
        nav_style = (
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_MUTED}; text-align: left;"
            " padding: 9px 10px; border: none;"
            f" border-radius: {theme.RADIUS_MD}px; font-size: 13.5px; }}"
            f"QPushButton:hover {{ background-color: {theme.SURFACE_HOVER};"
            f" color: {theme.TEXT}; }}"
            f"QPushButton:checked {{ background-color: {theme.ACCENT_TINT};"
            f" color: {theme.ACCENT_HOVER}; font-weight: 600; }}"
        )
        nav = QWidget()
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(10, 2, 10, 0)
        nav_lay.setSpacing(2)
        self._nav_buttons: dict[str, QPushButton] = {}
        for label, view in [
            ("nav_map", "concept_map"),
            ("nav_teach", "teach"),
            ("nav_import", "import"),
            ("nav_source", "source"),
        ]:
            btn = QPushButton(self._nav_label(self._t(label)))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(nav_style)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, v=view: self.on_nav_click(v))
            self._nav_buttons[view] = btn
            nav_lay.addWidget(btn)
        lay.addWidget(nav)

        # Hairline divider
        div_wrap = QWidget()
        div_lay = QVBoxLayout(div_wrap)
        div_lay.setContentsMargins(16, 10, 16, 10)
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {theme.DIVIDER};")
        div_lay.addWidget(div)
        lay.addWidget(div_wrap)

        # 进阶功能（默认折叠，小白不需要在首屏看到教师模型等高级入口）
        adv_section = CollapsibleSection(_t("nav_advanced"))
        adv_section._toggle.setStyleSheet(
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_MUTED}; border: none; text-align: left;"
            " padding: 6px 10px; font-size: 12.5px; font-weight: 600; }"
            f"QPushButton:hover {{ color: {theme.ACCENT}; }}"
        )
        body_lay = adv_section.body_layout()
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(2)
        adv_style = (
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_MUTED}; text-align: left;"
            " padding: 7px 10px; border: none;"
            f" border-radius: {theme.RADIUS_MD}px; font-size: 12.5px; }}"
            f"QPushButton:hover {{ background-color: {theme.SURFACE_HOVER};"
            f" color: {theme.TEXT}; }}"
            f"QPushButton:checked {{ background-color: {theme.ACCENT_TINT};"
            f" color: {theme.ACCENT_HOVER}; font-weight: 600; }}"
        )
        for label, view in [
            ("nav_knowledge", "knowledge"),
            ("nav_learner", "learner"),
            ("nav_teacher", "teacher"),
            ("nav_panorama", "panorama"),
        ]:
            btn = QPushButton(self._nav_label(self._t(label)))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(adv_style)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, v=view: self.on_nav_click(v))
            self._nav_buttons[view] = btn
            body_lay.addWidget(btn)
        adv_host = QWidget()
        adv_host_lay = QVBoxLayout(adv_host)
        adv_host_lay.setContentsMargins(10, 0, 10, 0)
        adv_host_lay.addWidget(adv_section)
        lay.addWidget(adv_host)

        # Asset list
        self._asset_list_widget = QWidget()
        al_lay = QVBoxLayout(self._asset_list_widget)
        al_lay.setContentsMargins(10, 10, 10, 8)
        al_lay.setSpacing(2)
        al_title = QLabel(_t("nav_assets"))
        al_title.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11.5px; font-weight: 600;"
        )
        al_lay.addWidget(al_title)
        # Keep the heading outside the dynamic list: _refresh_asset_list clears
        # this layout on every switch and used to delete the heading with it.
        self._asset_list_layout = QVBoxLayout()
        self._asset_list_layout.setContentsMargins(0, 0, 0, 0)
        self._asset_list_layout.setSpacing(2)
        al_lay.addLayout(self._asset_list_layout, 1)
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
        view.group_quiz_requested.connect(self._on_group_quiz_request)
        view.glossary_requested.connect(self._on_open_glossary)
        # Double-clicking a concept row opens its evidence in the source text
        # (the TOC's single click already navigates to the map).
        view.jump_evidence.connect(self._on_jump_to_evidence)
        self._knowledge_view = view
        self.knowledge_view = view
        # Compatibility attribute used by tests and external callers.
        self._dash_graph = view._dash_graph

    def _build_concept_map_view(self):
        view = ConceptMapView(self)
        view.teach_requested.connect(self._on_teach_request)
        view.open_concept_panel.connect(self._on_open_concept_panel)
        view.navigate_source.connect(self._on_jump_to_evidence)
        view.evidence_jump_requested.connect(self._on_teach_evidence_jump)
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
        view.evidence_jump_requested.connect(self._on_teach_evidence_jump)
        view.evaluate_recorded.connect(self._on_evaluate_recorded)
        self._teach_view = view
        self.teach_view = view
        self._teach_graph = view._graph

    def _build_learner_view(self):
        view = LearnerView(self)
        view.teach_requested.connect(self._on_teach_request)
        view.review_requested.connect(self._on_review_one_request)
        view.review_all_requested.connect(self._on_review_all_request)
        view.export_report.connect(self._on_export_report)
        view.export_html.connect(self._on_export_html)
        self._learner_view = view
        self.learner_view = view

    def _build_teacher_view(self):
        view = TeacherView(self)
        view.open_concept_panel.connect(self._on_open_concept_panel)
        view.teach_requested.connect(self._on_teach_request)
        self._teacher_view = view
        self.teacher_view = view

    def _build_panorama_view(self):
        view = PanoramaView(self)
        view.asset_switch_requested.connect(self._on_panorama_asset_switch)
        view.concept_jump_requested.connect(self._on_panorama_concept_jump)
        # A statistic chip that counts concepts/relations must be able to
        # take the learner to the graph that shows them.
        view.view_switch_requested.connect(self.on_nav_click)
        self._panorama_view = view
        self.panorama_view = view

    # ---- knowledge graph helpers -----------------------------------------------

    def _teach_graph_ref(self) -> KnowledgeGraphView:
        if self._teach_graph is None:
            self._teach_graph = KnowledgeGraphView()
            self._wire_graph(self._teach_graph)
        return self._teach_graph

    def _wire_graph(self, graph: KnowledgeGraphView) -> None:
        """Connect the shared graph interaction signals (one place, so a new
        graph surface can never ship with a clickable-but-dead menu item)."""
        graph.concept_clicked.connect(self._on_graph_teach_click)
        graph.node_single_clicked.connect(self._on_graph_node_clicked)
        graph.evidence_requested.connect(self._on_graph_evidence_click)

    def _on_graph_evidence_click(self, concept_id: str):
        """Right-click ▸ 查看证据 — jump the reader to this concept's passage."""
        self._on_teach_evidence_jump(concept_id, "")

    def _dash_graph_ref(self) -> KnowledgeGraphView:
        # The dashboard graph belongs to KnowledgeView.  A rebuilt view must
        # always receive a fresh QObject; retaining the old C++ wrapper after
        # deleteLater() leaves MainWindow pointing at an invalid object.
        graph = KnowledgeGraphView()
        self._wire_graph(graph)
        return graph

    def _graph_view_ref(self) -> KnowledgeGraphView:
        if self._graph_view is None:
            self._graph_view = KnowledgeGraphView()
            self._wire_graph(self._graph_view)
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
        "panorama": 7,
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

    def _on_group_quiz_request(self, concept_ids: list, title: str):
        """Chapter / topic comprehensive quiz: mixed questions over a group.

        A single-concept self-test checks recall; this checks the structure of
        the whole group (chapter or topic cluster). Each answer is scored and
        recorded through the existing quiz channel, and the group is summarised
        at the end — then the views refresh so mastery colours catch up.
        """
        asset = self.get_asset()
        if asset is None or not concept_ids:
            return
        dialog = GroupQuizDialog(self, asset, list(concept_ids), title, self)
        dialog.exec()
        self._refresh_all_views()

    def _on_open_glossary(self):
        """Domain terminology table: 缩写 ↔ 全称 ↔ 释义, deterministic.

        Every row comes from the asset's registered domain template, so no
        invented term can appear.  Terms that map onto a concept of the current
        asset get a ▶ jump into the concept panel (地图游走通向学习).
        """
        asset = self.get_asset()
        if asset is None:
            return
        self._glossary_dialog = GlossaryDialog(asset, self)
        self._glossary_dialog.concept_jump_requested.connect(self._on_glossary_jump)
        self._glossary_dialog.exec()
        self._glossary_dialog = None

    def _on_glossary_jump(self, concept_id: str):
        """Term → concept: close the modal table first (it owns a modal event
        loop), then land on the map with the concept's detail panel open."""
        dialog = getattr(self, "_glossary_dialog", None)
        if dialog is not None:
            dialog.accept()
        self.on_nav_click("concept_map")
        self._open_concept_panel(concept_id)

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
        learner sees a progress banner while reviewing. review=True keeps
        vary=1 (fresh angle) on every lesson in the pack — AGENTS.md §6.
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
                review=True,
            )

    def _on_review_one_request(self, concept_name: str):
        """Teach one due concept as a review lesson (vary=1, fresh angle).

        From a review-queue card click: the learner asked for review, not
        a first-time lesson, so the angle must differ from what they
        already sat through.
        """
        self.on_nav_click("teach")
        asset = self.get_asset()
        if asset:
            c = asset.concept_by_name(concept_name)
            if c:
                gv = self._graph_view_ref()
                gv.set_teaching_context(c.id)
        if hasattr(self, "_teach_view"):
            self._teach_view.start_teach_by_name(concept_name, review=True)

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

    # ---- project panorama ------------------------------------------------------

    def _switch_asset_quiet(self, asset_id: str):
        """Switch the active asset without forcing a navigation away.

        Used by the panorama page, which aggregates across materials and must
        stay put while the learner drills into a specific one.
        """
        if asset_id not in self.assets or asset_id == self.current_asset_id:
            return
        self.current_asset_id = asset_id
        self._refresh_asset_list()
        self._rebuild_all_views()
        self._update_topbar()

    def _on_panorama_asset_switch(self, asset_id: str):
        self._switch_asset_quiet(asset_id)

    def _on_panorama_concept_jump(self, asset_id: str, concept_name: str):
        self._switch_asset_quiet(asset_id)
        asset = self.get_asset()
        if asset is not None and concept_name:
            c = asset.concept_by_name(concept_name)
            if c is not None:
                self._open_concept_panel(c.id)
                return
        # Concept lives in a material that is not active / not loaded as a
        # concept — fall back to the learner model where mastery is visible.
        self.on_nav_click("learner")

    def _on_jump_to_evidence(self, concept_id: str, evidence: str = ""):
        self.on_nav_click("source")
        # ``on_nav_click`` refreshes the reader (fresh mastery colours and
        # anchors), which replaces ``SourceView._source_widget``; re-bind to
        # the live widget — the cached one was just deleteLater'd, so scrolling
        # it would silently do nothing (a dead link in all but appearance).
        view = getattr(self, "_source_view", None)
        widget = getattr(view, "_source_widget", None) if view is not None else None
        self._source_view_widget = widget
        if widget is not None:
            widget.scroll_to_concept(concept_id, evidence or None)

    def _on_teach_evidence_jump(self, concept_ref: str, evidence: str = ""):
        """Evidence badge clicked — resolve the concept (global graph ids
        carry an ``asset_id:`` prefix; lesson ids are current-asset local)
        and jump the reader to that exact evidence passage. A cross-asset
        badge first switches the active asset so the reader shows the
        right source text."""
        aid = None
        cid = concept_ref or ""
        if ":" in cid:
            maybe_aid, _, rest = cid.partition(":")
            if maybe_aid in self.assets:
                aid, cid = maybe_aid, rest
        asset = self.get_asset(aid) if aid else self.get_asset()
        if asset is None:
            return
        concept = asset.concept_by_id(cid)
        if concept is None:
            # legacy callers may still pass a concept name (current asset)
            concept = asset.concept_by_name(concept_ref or "")
            if concept is None:
                return
        if aid and aid != self.current_asset_id:
            # switch first so the source view renders this asset's text
            self.current_asset_id = aid
            self._refresh_asset_list()
            self._rebuild_all_views()
        self._on_jump_to_evidence(concept.id, evidence)

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
        self._adapt_teaching_silently(concept_name)

    def _adapt_teaching_silently(self, concept_name: str):
        """Stuck signal → silently improve the teaching strategy.

        AutoHarness is an internal mechanism: the learner never sees evolution
        cards, guard trimming or cross-asset migration. The same deterministic
        pipeline still runs — ``evolve_joint`` (all signal layers) or a
        strategy that wins on another asset — and the adopted HarnessSpec is
        persisted with its audit event. The one visible effect is the live
        explanation style switching, so the next "换个讲法" lands differently.
        """
        try:
            asset = self.get_asset()
            if asset is None or not concept_name:
                return
            if getattr(self, "_harness_offer_shown", None) is None:
                self._harness_offer_shown = set()
            spec = self._harness_specs.get(asset.asset_id) or _ah.fallback_harness()
            reports = _ah.load_session_reports(
                config.DATA_DIR / "harness_state.json"
            )
            res = _ah.evolve_joint(
                spec, self.learner, reports=reports, concept_name=concept_name
            )
            cand = (res.get("candidates") or [None])[0] if res.get("evolved") else None
            reason = res.get("reason", "stuck")
            if cand is not None:
                sig = (asset.asset_id, concept_name, reason, cand.get("name", ""))
                if sig in self._harness_offer_shown:
                    return
                self._harness_offer_shown.add(sig)
                self._apply_harness_silently(cand, reason, concept_name)
                return
            self._adopt_transfer_silently(asset, concept_name)
        except Exception:
            pass

    def _adopt_transfer_silently(self, asset, concept_name: str):
        """No local candidate → adopt the strategy that wins on another asset."""
        shown = getattr(self, "_transfer_offer_shown", None)
        if shown is None:
            shown = self._transfer_offer_shown = set()
        # skip the differential evaluation entirely when every source asset
        # was already offered (and adopted) this session
        fresh_sources = [
            aid
            for aid in self._harness_specs
            if aid != asset.asset_id
            and not any(
                sig[0] == asset.asset_id and sig[1] == aid for sig in shown
            )
        ]
        if not fresh_sources:
            return
        listed = self._find_transfer_candidates(asset)[:1]
        if not listed:
            return
        cand = listed[0]
        spec = cand.get("spec") or {}
        sig = (asset.asset_id, cand.get("source_asset_id", ""), spec.get("name", ""))
        if sig in shown:
            return
        shown.add(sig)
        path = config.DATA_DIR / "harness_state.json"
        ok, _event = _ah.adopt_harness_for_asset(
            path,
            asset.asset_id,
            spec,
            source_asset_id=cand.get("source_asset_id", ""),
            concept=concept_name,
        )
        if not ok:
            return
        self._harness_specs[asset.asset_id] = spec
        self._harness_history = _ah.load_harness_history(path)
        self._nudge_style(spec)

    def _apply_harness_silently(self, spec: dict, reason: str, concept_name: str):
        """Persist an evolved spec + audit event, then nudge the live style."""
        asset = self.get_asset()
        if asset is None:
            return
        path = config.DATA_DIR / "harness_state.json"
        old_spec = self._harness_specs.get(asset.asset_id)
        self._harness_specs[asset.asset_id] = spec
        _ah.save_harness_state(path, self._harness_specs)
        self._harness_history = _ah.record_harness_evolution(
            path,
            _ah.evolution_event(
                reason,
                old_spec,
                spec,
                asset_id=asset.asset_id,
                concept=concept_name,
            ),
        )
        self._nudge_style(spec)

    def _nudge_style(self, spec: dict):
        """Switch the live explanation style to the adopted strategy's style."""
        tv = getattr(self, "_teach_view", None)
        combo = getattr(tv, "_style_combo", None)
        if combo is None:
            return
        code = self._HARNESS_STYLE_CODES.get(
            (spec.get("policy") or {}).get("style", ""), None
        )
        if code is None:
            return
        idx = tv._CODE_TO_IDX.get(code, 0)
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_followup_done(self, question: str, answer: str):
        pass

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
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(2)
            btn = QPushButton(
                f"{title[:22]}{'...' if len(title) > 22 else ''}  · {count}"
            )
            btn.setToolTip(_t("asset_tooltip", title=title, count=count))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent;"
                f" color: {theme.TEXT_MUTED}; text-align: left;"
                " padding: 7px 10px; border: none;"
                f" border-radius: {theme.RADIUS_MD}px; font-size: 12.5px; }}"
                f"QPushButton:hover {{ background-color: {theme.SURFACE_HOVER};"
                f" color: {theme.TEXT}; }}"
                f"QPushButton:checked {{ background-color: {theme.ACCENT_TINT};"
                f" color: {theme.ACCENT_HOVER}; }}"
            )
            btn.setCheckable(True)
            btn.setChecked(aid == self.current_asset_id)
            btn.clicked.connect(lambda checked, a=aid: self.on_asset_select(a))
            row_lay.addWidget(btn, 1)
            del_btn = QPushButton("×")
            del_btn.setObjectName(f"asset_delete_{aid}")
            del_btn.setToolTip(_t("asset_delete_tip", title=title))
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setFixedWidth(26)
            del_btn.setFixedHeight(24)
            del_btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent;"
                f" color: {theme.TEXT_FAINT}; border: none;"
                f" border-radius: {theme.RADIUS_SM}px; font-size: 12.5px; }}"
                f"QPushButton:hover {{ background-color: {theme.DANGER};"
                f" color: {theme.TEXT_ON_ACCENT}; }}"
            )
            del_btn.clicked.connect(
                lambda checked, a=aid: self._on_delete_asset(a)
            )
            row_lay.addWidget(del_btn)
            self._asset_buttons[aid] = btn
            self._asset_list_layout.addWidget(row)
        # Extra space belongs below the list, not between rows.
        self._asset_list_layout.addStretch(1)

    def _on_delete_asset(self, asset_id: str):
        """Delete an asset with its teacher model and learner traces.

        The knowledge index rebuilds itself from the remaining assets via its
        signature check, so no explicit index maintenance is needed here.
        """
        data = self.assets.get(asset_id)
        if data is None:
            return
        title = data.get("title") or data.get("source_name") or asset_id
        answer = QMessageBox.question(
            self,
            _t("asset_delete_title"),
            _t("asset_delete_confirm", title=title),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_asset(asset_id)
        self.assets.pop(asset_id, None)
        self.teacher_models.pop(asset_id, None)
        unregister_asset(self.learner, asset_id)
        self.save_learner_state()
        if self.current_asset_id == asset_id:
            self.current_asset_id = next(iter(self.assets), None)
        self._rebuild_all_views()

    def _rebuild_all_views(self):
        """Clear and rebuild every data-dependent view.

        Fully rebuilds all 8 views (like the original code) so that graph
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
        self._build_panorama_view()
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
            self._panorama_view,
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
                    self._panorama_view,
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
        mastery_vals: list[float] = []
        unanchored = 0
        for c in self.get_asset().concepts if self.get_asset() else []:
            norm = normalize(c.name)
            m = self.learner.get("concepts", {}).get(norm, {}).get("mastery", 0.0)
            mastery_vals.append(m)
            if not (getattr(c, "locations", None) or []):
                unanchored += 1
            if m >= 0.6:
                mastered += 1
            elif m > 0:
                learning += 1
            else:
                unstudied += 1
        td = self.teacher_models.get(self.current_asset_id or "", {})
        anomaly_count = len(td.get("anomalies", []))
        total = mastered + learning + unstudied
        avg_mastery = sum(mastery_vals) / len(mastery_vals) if mastery_vals else 0.0
        return dict(
            total=total,
            mastered=mastered,
            learning=learning,
            unstudied=unstudied,
            anomalies=anomaly_count,
            avg_mastery=avg_mastery,
            unanchored=unanchored,
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
        elif idx == 7 and hasattr(self, "_panorama_view"):  # panorama
            self._panorama_view.refresh()

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
        # Carry the current asset's curated path into the merged graph (ids
        # prefixed) so path playback works in the all-assets scope too.
        cur_prefix = f"{self.current_asset_id}:" if len(self.assets) > 1 else ""
        cur_path: list[str] = []
        cur_data = self.assets.get(self.current_asset_id or "", {})
        for cid in cur_data.get("learning_path", []) or []:
            pid = f"{cur_prefix}{cid}"
            if any(c.id == pid for c in all_concepts):
                cur_path.append(pid)

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
            learning_path=cur_path,
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
