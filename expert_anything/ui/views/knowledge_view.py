"""Knowledge model view: adaptive learning path + dashboard + quick deconstruction."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core.learner import (
    adaptive_path,
    concept_density,
    get_note,
    has_note,
    is_favorite,
    normalize,
    record_evaluation,
    topic_clusters,
)
from expert_anything.core.teacher import anomaly_concept_ids, TeacherModel
from expert_anything.core.i18n import t
from expert_anything.ui.widgets._helpers import CollapsibleSection
from expert_anything.ui import theme
from expert_anything.ui.widgets.shared import PageHeader, StatCard

# -- TOC item roles ---------------------------------------------------------
# PySide6 stores a *plain int* role 2 in the item's display slot, so writing
# the ("concept", id) payload there silently wiped every row caption and the
# chapter TOC rendered blank rows.  Payloads therefore live at Qt.UserRole and
# up, leaving DisplayRole for the caption the learner actually reads.
_ROLE_PAYLOAD = int(Qt.ItemDataRole.UserRole)  # ("concept", c.id) / ("chapter", title)
_ROLE_DIFF = _ROLE_PAYLOAD + 1  # difficulty bucket of the row
_ROLE_CAPTION = _ROLE_PAYLOAD + 2  # plain caption (note filter appends/restores)


def localize_method(method: str) -> str:
    """Translate an extraction method string to a human-readable label."""
    table = {
        "llm_extraction_chunked_v1": "method_llm_chunked",
        "llm_extraction_v1": "method_llm",
        "llm_failed_fallback_v1": "method_fallback",
        "deterministic_fallback_v1": "method_fallback",
    }
    return t(table.get(method, method))


class KnowledgeView(QWidget):
    """View 2 — Knowledge model (dashboard + adaptive path + TOC + clusters)."""

    # Signals to MainWindow
    open_concept_panel = Signal(str)  # concept_id
    teach_requested = Signal(str)  # concept_name
    topic_teach_requested = Signal(
        str, str, list, int
    )  # concept_name, topic_name, concept_names_queue, mastered_count
    focus_graph = Signal(str)  # concept_id
    jump_evidence = Signal(str, str)  # concept_id, evidence
    group_quiz_requested = Signal(list, str)  # concept_ids, group title
    glossary_requested = Signal()  # open the domain terminology table

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._build()

    def refresh(self):
        """Called by ViewManager when the current asset changes."""
        self._rebuild()

    def _rebuild(self):
        # Clear and rebuild.  Drop compatibility references to widgets owned by
        # the old subtree before deleteLater(), then publish the newly built
        # dashboard graph back to MainWindow.
        self._main._dash_graph = None
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._do_build()
        self._main._dash_graph = self._dash_graph

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._root_layout = layout
        self._do_build()

    def _do_build(self):
        self._root_layout.addWidget(
            self._view_header(
                self._main._t("nav_knowledge"),
                self._main._get_asset_subtitle(),
            )
        )

        # Fallback warning
        cur_asset = self._main.get_asset()
        if cur_asset is not None:
            mlow = (cur_asset.method or "").lower()
            if "fallback" in mlow or "failed" in mlow or "deterministic" in mlow:
                warn = QLabel(
                    self._main._t(
                        "dash_fallback_warn", method=localize_method(cur_asset.method)
                    )
                )
                # Never hide *why* the LLM path degraded: provenance carries the
                # explicit fallback reason (AGENTS.md #48 silent-degradation fix).
                provenance = getattr(cur_asset, "provenance", None) or {}
                reason = str(provenance.get("fallback_reason") or "").strip()
                if reason:
                    warn.setText(
                        warn.text() + "\n" + self._main._t("dash_fallback_reason", reason=reason)
                    )
                warn.setWordWrap(True)
                warn.setStyleSheet(
                    "background-color:#FFF4E5; color:#8A4B00; border:1px solid #FFD28A;"
                    "border-radius:8px; padding:10px 14px; font-size: 15px; margin:0 16px;"
                )
                self._root_layout.addWidget(warn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(20, 16, 20, 20)
        scroll_layout.setSpacing(16)

        scroll_layout.addWidget(self._build_browse_drawer())
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        self._root_layout.addWidget(scroll)

    def _view_header(self, title, subtitle=""):
        return PageHeader(title, subtitle)

    def _build_browse_drawer(self):
        drawer = QWidget()
        dlayout = QVBoxLayout(drawer)
        dlayout.setContentsMargins(0, 0, 0, 0)
        dlayout.setSpacing(16)

        # Stats
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)
        stats = self._main._compute_stats()
        for card in [
            ("📚", self._main._t("stat_total"), stats["total"], theme.ACCENT),
            (
                "✓",
                self._main._t("legend_mastered"),
                stats["mastered"],
                theme.SUCCESS,
            ),
            (
                "↗",
                self._main._t("legend_learning"),
                stats["learning"],
                theme.WARNING,
            ),
            (
                "○",
                self._main._t("stat_unstudied"),
                stats["unstudied"],
                theme.TEXT_FAINT,
            ),
            ("⚠", self._main._t("stat_anomaly"), stats["anomalies"], theme.DANGER),
            ("◔", self._main._t("stat_avg_mastery"), f"{stats['avg_mastery']:.0%}", "#7C3AED"),
            ("◌", self._main._t("stat_unanchored"), stats["unanchored"], "#607D8B"),
        ]:
            stats_layout.addWidget(StatCard(*card))
        stats_layout.addStretch()
        dlayout.addLayout(stats_layout)

        # Search + mastery filter bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._concept_search = QLineEdit()
        self._concept_search.setPlaceholderText(self._main._t("concept_search_ph"))
        self._concept_search.setStyleSheet(
            "QLineEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 5px 10px; font-size: 14px; background-color: white; }"
        )
        self._concept_search.textChanged.connect(self._on_concept_filter)
        self._install_search_completer()
        filter_row.addWidget(self._concept_search, 1)

        self._mastery_filter = QComboBox()
        self._mastery_filter.addItems([
            self._main._t("filter_all"),
            self._main._t("filter_unstudied"),
            self._main._t("filter_weak"),
            self._main._t("filter_learning"),
            self._main._t("filter_mastered"),
            self._main._t("filter_favorite"),
            self._main._t("filter_note"),
        ])
        self._mastery_filter.setStyleSheet(
            "QComboBox { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 4px 8px; font-size: 14px; background-color: white; }"
        )
        self._mastery_filter.currentIndexChanged.connect(self._on_concept_filter)
        filter_row.addWidget(self._mastery_filter)

        # Domain terminology table.  Shown only when the asset title maps to a
        # registered domain — otherwise there is no term to list and the button
        # would be a dead link (设计理念第 7 条：死链接零容忍).
        try:
            from expert_anything.core.domain_templates import detect_domain_from_title

            if detect_domain_from_title(getattr(self._main.get_asset(), "title", "")):
                gloss_btn = QPushButton(self._main._t("glossary_btn"))
                gloss_btn.setObjectName("glossary_btn")
                gloss_btn.setToolTip(self._main._t("glossary_btn_tip"))
                gloss_btn.setStyleSheet(
                    "QPushButton { background-color: white; color: #00695C;"
                    "border: 1px solid #B2DFDB; border-radius: 6px;"
                    "padding: 4px 10px; font-size: 13.5px; }"
                    "QPushButton:hover { background-color: #E0F2F1; }"
                )
                gloss_btn.clicked.connect(
                    lambda checked=False: self.glossary_requested.emit()
                )
                filter_row.addWidget(gloss_btn)
        except Exception:
            pass
        dlayout.addLayout(filter_row)

        # First screen keeps only the core three (stats, TOC, next-step path);
        # the quick-deconstruction panorama, topic clusters and the dashboard
        # graph live behind one 「更多」 fold — hidden, never removed, one
        # click away (AGENTS.md first-screen discipline).
        more_section = self._more_section = CollapsibleSection(
            self._main._t("more_section")
        )

        # Quick deconstruction: visual knowledge panorama
        asset = self._main.get_asset()
        if asset is not None and asset.concepts:
            try:
                from expert_anything.core import decoder
                from expert_anything.ui.widgets.teach_widgets import DecoderSceneCard

                scene = decoder.quick_deconstruction(asset)
                if scene and scene.get("nodes"):
                    pan_card = QFrame()
                    pan_card.setStyleSheet(
                        "QFrame { background-color: #FFF3E0; border: 1px solid #FFCC80;"
                        "border-radius: 10px; }"
                    )
                    pan_lay = QVBoxLayout(pan_card)
                    pan_lay.setContentsMargins(16, 12, 16, 12)
                    pan_lay.setSpacing(6)

                    pan_title = QLabel(self._main._t("quick_deconstruct_title"))
                    pan_title.setStyleSheet(
                        "font-size: 16px; font-weight: bold; color: #E65100;"
                    )
                    pan_lay.addWidget(pan_title)

                    pan_hint = QLabel(self._main._t("quick_deconstruct_hint"))
                    pan_hint.setWordWrap(True)
                    pan_hint.setStyleSheet("font-size: 13px; color: #8D6E63;")
                    pan_lay.addWidget(pan_hint)

                    # Relation semantic legend
                    from expert_anything.core.decoder import REL_SEMANTICS

                    legend_row = QHBoxLayout()
                    legend_row.setSpacing(8)
                    leg_title = QLabel(self._main._t("rel_legend_title"))
                    leg_title.setStyleSheet(
                        "font-size: 13px; font-weight: bold; color: #8D6E63;"
                    )
                    legend_row.addWidget(leg_title)
                    for sem_key, sem_info in REL_SEMANTICS.items():
                        color = sem_info["color"]
                        chip = QLabel(self._main._t("rel_" + sem_key))
                        chip.setStyleSheet(
                            f"font-size: 12.5px; color: white; background-color: {color};"
                            f"border-radius: 8px; padding: 2px 8px;"
                        )
                        legend_row.addWidget(chip)
                    legend_row.addStretch()
                    pan_lay.addLayout(legend_row)

                    dec_card = DecoderSceneCard(
                        scene,
                        concept=getattr(asset, "title", ""),
                        source_title=getattr(asset, "title", ""),
                    )
                    dec_card.game_scored.connect(
                        lambda score: self._on_panorama_game_scored(score)
                    )
                    pan_lay.addWidget(dec_card)

                    # Game → learning-loop handoff: after a sorting round, point
                    # the learner at the adaptive path's first concept instead
                    # of leaving them on a "watched it, done" dead end.
                    self._pan_feedback = QLabel()
                    self._pan_feedback.setWordWrap(True)
                    self._pan_feedback.hide()
                    pan_lay.addWidget(self._pan_feedback)

                    self._pan_learn_btn = QPushButton(self._main._t("start_teach"))
                    self._pan_learn_btn.setStyleSheet(
                        "QPushButton { background-color: #E65100; color: white; border: none;"
                        "border-radius: 6px; padding: 5px 14px; font-size: 13.5px;"
                        "font-weight: bold; }"
                        "QPushButton:hover { background-color: #BF360C; }"
                    )
                    self._pan_learn_btn.clicked.connect(self._on_pan_go_learn)
                    self._pan_learn_btn.hide()
                    pan_lay.addWidget(
                        self._pan_learn_btn, 0, Qt.AlignmentFlag.AlignRight
                    )
                    more_section.add(pan_card)
            except Exception:
                pass

        # TOC and topic clusters
        if asset is not None:
            # TOC
            toc_card = QFrame()
            toc_card.setStyleSheet(
                f"QFrame {{ background-color: {theme.SURFACE};"
                f" border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.RADIUS_LG}px; }}"
            )
            toc_lay = QVBoxLayout(toc_card)
            toc_lay.setContentsMargins(16, 12, 16, 12)
            toc_lay.setSpacing(6)

            toc_title = QLabel(self._main._t("toc_title"))
            toc_title.setStyleSheet(
                f"font-size: 15px; font-weight: 600; color: {theme.TEXT};"
            )
            toc_lay.addWidget(toc_title)

            toc_hint = QLabel(self._main._t("toc_hint"))
            toc_hint.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            toc_lay.addWidget(toc_hint)

            self._toc_tree = QTreeWidget()
            self._toc_tree.setHeaderHidden(True)
            self._toc_tree.setMaximumHeight(240)
            self._toc_tree.setStyleSheet(
                f"QTreeWidget {{ background-color: {theme.SURFACE_MUTED};"
                f" border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.RADIUS_MD}px; font-size: 13px; }}"
                "QTreeWidget::item { padding: 4px; }"
                f"QTreeWidget::item:selected {{ background-color: {theme.ACCENT_TINT};"
                f" color: {theme.ACCENT_HOVER}; }}"
            )
            by_ch = {}
            for c in asset.concepts:
                by_ch.setdefault(c.chapter or "", []).append(c)
            ordered = []
            seen = set()
            for ch in asset.chapters:
                if ch.title in by_ch and ch.title not in seen:
                    ordered.append(ch.title)
                    seen.add(ch.title)
            for k in by_ch:
                if k and k not in seen:
                    ordered.append(k)
                    seen.add(k)

            # Pre-compute mastery per chapter
            ch_mastery: dict[str, dict] = {}
            for ch_title in ordered:
                concepts = by_ch[ch_title]
                total = len(concepts)
                mastered = 0
                partial = 0
                weak = 0
                unstudied = 0
                avg_m = 0.0
                for c in concepts:
                    nk = normalize(c.name)
                    m = float(
                        self._main.learner.get("concepts", {})
                        .get(nk, {})
                        .get("mastery", 0.0)
                    )
                    avg_m += m
                    if m >= 0.6:
                        mastered += 1
                    elif m >= 0.3:
                        partial += 1
                    elif m > 0:
                        weak += 1
                    else:
                        unstudied += 1
                avg_m = avg_m / total if total > 0 else 0.0
                ch_mastery[ch_title] = {
                    "total": total,
                    "mastered": mastered,
                    "partial": partial,
                    "weak": weak,
                    "unstudied": unstudied,
                    "avg": avg_m,
                }

            for ch_title in ordered:
                mi = ch_mastery[ch_title]
                # Build custom widget for chapter row: name + progress + count
                ch_widget = QWidget()
                ch_layout = QHBoxLayout(ch_widget)
                ch_layout.setContentsMargins(4, 2, 8, 2)
                ch_layout.setSpacing(8)

                name_label = QLabel(ch_title)
                name_label.setStyleSheet(
                    "font-size: 14.5px; font-weight: 500; color: #1F2937;"
                )
                name_label.setMinimumWidth(120)
                name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                ch_layout.addWidget(name_label, 0)

                progress = QProgressBar()
                progress.setRange(0, 100)
                progress.setValue(int(mi["avg"] * 100))
                progress.setTextVisible(False)
                progress.setFixedHeight(8)
                progress.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                progress.setStyleSheet(
                    "QProgressBar { border: none; background-color: #E5E7EB;"
                    "border-radius: 4px; }"
                    "QProgressBar::chunk { border-radius: 4px;"
                    f"background-color: {self._progress_color(mi['avg'])}; }}"
                )
                ch_layout.addWidget(progress, 1)

                count_label = QLabel(f"{mi['mastered']}/{mi['total']}")
                count_label.setStyleSheet(
                    "font-size: 13px; color: #6B7280; min-width: 40px;"
                )
                count_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                count_label.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents
                )
                ch_layout.addWidget(count_label, 0)

                ch_quiz = QPushButton("📚")
                ch_quiz.setObjectName("chapter_quiz_btn")
                ch_quiz.setToolTip(self._main._t("group_quiz_hint"))
                ch_quiz.setFixedWidth(30)
                ch_quiz.setStyleSheet(
                    "QPushButton { background-color: white; color: #6A1B9A;"
                    "border: 1px solid #E1BEE7; border-radius: 6px;"
                    "padding: 1px 4px; font-size: 12.5px; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                ch_quiz.clicked.connect(
                    lambda checked, t=ch_title: self.group_quiz_requested.emit(
                        [c.id for c in by_ch.get(t, [])], t
                    )
                )
                ch_layout.addWidget(ch_quiz, 0)

                top = QTreeWidgetItem([""])
                top.setData(0, _ROLE_PAYLOAD, ("chapter", ch_title))
                self._toc_tree.addTopLevelItem(top)
                self._toc_tree.setItemWidget(top, 0, ch_widget)

                from expert_anything.core.learner import concept_difficulty

                diff_map = concept_difficulty(
                    self._main.learner, asset_id=self._main.current_asset_id
                )
                diff_colors = {
                    "easy": ("#E8F5E9", "#2E7D32", self._main._t("diff_easy")),
                    "medium": ("#FFF8E1", "#E65100", self._main._t("diff_medium")),
                    "hard": ("#FFEBEE", "#C62828", self._main._t("diff_hard")),
                    "unknown": ("#F5F5F5", "#9E9E9E", "?"),
                }
                for c in by_ch[ch_title][:25]:
                    diff = diff_map.get(c.name, "unknown")
                    bg, fg, label = diff_colors.get(diff, diff_colors["unknown"])
                    star = "★ " if is_favorite(self._main.learner, c.name) else ""
                    note_mark = "📝 " if has_note(self._main.learner, c.name) else ""
                    child = QTreeWidgetItem([f"  {star}{note_mark}{c.name}  [{label}]"])
                    child.setData(0, _ROLE_PAYLOAD, ("concept", c.id))
                    child.setData(0, _ROLE_DIFF, diff)
                    # Base caption kept so the note filter can append the note
                    # and restore the plain row when the filter is cleared.
                    child.setData(0, _ROLE_CAPTION, child.text(0))
                    child.setToolTip(0, self._main._t("toc_row_tip"))
                    top.addChild(child)
            unassigned = [c for k, lst in by_ch.items() if not k for c in lst]
            if unassigned:
                from expert_anything.core.learner import concept_difficulty

                diff_map = concept_difficulty(
                    self._main.learner, asset_id=self._main.current_asset_id
                )
                diff_colors = {
                    "easy": ("#E8F5E9", "#2E7D32", self._main._t("diff_easy")),
                    "medium": ("#FFF8E1", "#E65100", self._main._t("diff_medium")),
                    "hard": ("#FFEBEE", "#C62828", self._main._t("diff_hard")),
                    "unknown": ("#F5F5F5", "#9E9E9E", "?"),
                }
                top = QTreeWidgetItem([self._main._t("toc_other")])
                top.setData(0, _ROLE_PAYLOAD, ("chapter", ""))
                for c in unassigned[:20]:
                    diff = diff_map.get(c.name, "unknown")
                    bg, fg, label = diff_colors.get(diff, diff_colors["unknown"])
                    star = "★ " if is_favorite(self._main.learner, c.name) else ""
                    note_mark = "📝 " if has_note(self._main.learner, c.name) else ""
                    child = QTreeWidgetItem([f"  {star}{note_mark}{c.name}  [{label}]"])
                    child.setData(0, _ROLE_PAYLOAD, ("concept", c.id))
                    child.setData(0, _ROLE_DIFF, diff)
                    child.setData(0, _ROLE_CAPTION, child.text(0))
                    child.setToolTip(0, self._main._t("toc_row_tip"))
                    top.addChild(child)
                self._toc_tree.addTopLevelItem(top)
            if self._toc_tree.topLevelItemCount() == 0:
                self._toc_tree.addTopLevelItem(
                    QTreeWidgetItem([self._main._t("chapter_empty")])
                )
            self._toc_tree.itemClicked.connect(self._on_toc_clicked)
            self._toc_tree.itemDoubleClicked.connect(self._on_toc_double_clicked)
            toc_lay.addWidget(self._toc_tree)
            dlayout.addWidget(toc_card)

            # Topic clusters
            clusters = topic_clusters(asset)
            big = [c for c in clusters if c["size"] >= 2][:8]
            if big:
                topic_card = QFrame()
                topic_card.setStyleSheet(
                    f"QFrame {{ background-color: {theme.SURFACE};"
                    f" border: 1px solid {theme.BORDER};"
                    f" border-radius: {theme.RADIUS_LG}px; }}"
                )
                tp_lay = QVBoxLayout(topic_card)
                tp_lay.setContentsMargins(16, 12, 16, 12)
                tp_lay.setSpacing(6)
                tp_title = QLabel(self._main._t("topics_title"))
                tp_title.setStyleSheet(
                    f"font-size: 15px; font-weight: 600; color: {theme.TEXT};"
                )
                tp_lay.addWidget(tp_title)
                tp_hint = QLabel(self._main._t("topics_hint"))
                tp_hint.setWordWrap(True)
                tp_hint.setStyleSheet("font-size: 13px; color: #9E9E9E;")
                tp_lay.addWidget(tp_hint)

                for cl in big:
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    name_btn = QPushButton(
                        f"{cl['name']}  ·  {self._main._t('topic_size', n=cl['size'])}"
                    )
                    name_btn.setStyleSheet(
                        "QPushButton { font-size: 14.5px; font-weight: bold; color: #0c4a6e;"
                        "background-color: #E8F0F8; border: 1px solid #B0C4D8;"
                        "border-radius: 6px; padding: 4px 10px; text-align: left; }"
                        "QPushButton:hover { background-color: #D0E0F0; }"
                    )
                    name_btn.setToolTip(self._main._t("topic_focus_hint"))
                    name_btn.clicked.connect(
                        lambda checked, cid=cl["id"]: self._focus_topic(cid)
                    )
                    row.addWidget(name_btn)
                    for cid in cl["concept_ids"][:5]:
                        c = asset.concept_by_id(cid)
                        if c:
                            chip = QPushButton(c.name)
                            chip.setStyleSheet(
                                "QPushButton { background-color: #F3E5F5; color: #6A1B9A;"
                                "border: 1px solid #CE93D8; border-radius: 10px;"
                                "padding: 2px 8px; font-size: 12.5px; }"
                                "QPushButton:hover { background-color: #E1BEE7; }"
                            )
                            chip.clicked.connect(
                                lambda checked, cid=cid: self.focus_graph.emit(cid)
                            )
                            row.addWidget(chip)
                    row.addStretch()
                    learn_btn = QPushButton(self._main._t("learn_topic"))
                    learn_btn.setStyleSheet(
                        "QPushButton { background-color: white; color: #6A1B9A;"
                        "border: 1px solid #CE93D8; border-radius: 6px; padding: 3px 10px;"
                        "font-size: 13px; }"
                        "QPushButton:hover { background-color: #F3E5F5; }"
                    )
                    learn_btn.clicked.connect(
                        lambda checked, cid=cl["id"]: self._start_topic(cid)
                    )
                    row.addWidget(learn_btn)
                    quiz_btn = QPushButton(self._main._t("group_quiz_start"))
                    quiz_btn.setObjectName("topic_quiz_btn")
                    quiz_btn.setToolTip(self._main._t("group_quiz_hint"))
                    quiz_btn.setStyleSheet(
                        "QPushButton { background-color: white; color: #6A1B9A;"
                        "border: 1px solid #E1BEE7; border-radius: 6px;"
                        "padding: 3px 10px; font-size: 13px; }"
                        "QPushButton:hover { background-color: #F3E5F5; }"
                    )
                    quiz_btn.clicked.connect(
                        lambda checked, ids=list(cl["concept_ids"]), nm=cl["name"]: (
                            self.group_quiz_requested.emit(ids, nm)
                        )
                    )
                    row.addWidget(quiz_btn)
                    tp_lay.addLayout(row)
                more_section.add(topic_card)

        # Adaptive path + graph
        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)

        section_title = QLabel(self._main._t("section_recommend"))
        section_title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_HOVER};"
            " padding: 4px 0;"
        )
        cards_layout.addWidget(section_title)

        self._path_ladder = self._main._path_ladder_ref()
        self._path_ladder.concept_clicked.connect(self._on_path_card_click)
        if self._main.current_asset_id:
            path_items = self._main.get_adaptive_path(self._main.current_asset_id)
            entry = self._main.learner.get("assets", {}).get(
                self._main.current_asset_id, {}
            )
            completed = set(entry.get("completed", []))
            try:
                asset2 = self._main.get_asset()
                density = concept_density(asset2, self._main.learner)
                for it in path_items:
                    it["badge"] = density.get(it.get("cid", ""), {}).get("badge", "")
            except Exception:
                pass
            self._path_ladder.set_items(path_items, completed=completed)
        cards_layout.addWidget(self._path_ladder)
        cards_layout.addStretch()
        dlayout.addWidget(cards_container)

        # Dashboard graph.  Keep this reference on both the view and
        # MainWindow; graph_container becomes its Qt parent below.
        graph_container = QWidget()
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(8)

        graph_title = QLabel(self._main._t("section_graph"))
        graph_title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_HOVER};"
            " padding: 4px 0;"
        )
        graph_layout.addWidget(graph_title)

        self._dash_graph = self._main._dash_graph_ref()
        self._dash_graph.setMinimumHeight(300)
        self._dash_graph.setStyleSheet(
            f"QGraphicsView {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; }}"
        )
        graph_layout.addWidget(self._dash_graph)

        if self._main.current_asset_id:
            asset = self._main.get_asset()
            if asset is not None:
                mastery_map = {}
                for c in asset.concepts:
                    norm_name = normalize(c.name)
                    mastery_map[c.id] = (
                        self._main.learner.get("concepts", {})
                        .get(norm_name, {})
                        .get("mastery", 0.0)
                    )
                anomaly_ids = set()
                td = self._main.teacher_models.get(self._main.current_asset_id)
                if td:
                    try:
                        anomaly_ids = anomaly_concept_ids(
                            asset, TeacherModel.from_dict(td)
                        )
                    except Exception:
                        anomaly_ids = set()
                items = self._main.get_adaptive_path(self._main.current_asset_id)
                current_id = items[0].get("cid") if items else None
                self._dash_graph.set_asset(
                    asset,
                    mastery_map=mastery_map,
                    anomaly_ids=anomaly_ids,
                    current_id=current_id,
                )
                self._dash_graph.concept_clicked.connect(self._on_graph_click)
                # Keep dashboard navigation consistent with the full map:
                # single-click moves to the persistent map + inspector view,
                # rather than opening a separate modal dialog.
                self._dash_graph.node_single_clicked.connect(
                    self._on_dashboard_node_clicked
                )

        more_section.add(graph_container)
        if more_section.body_layout().count():
            dlayout.addWidget(more_section)
        dlayout.addStretch()
        return drawer

    def _on_toc_clicked(self, item):
        kind, payload = item.data(0, _ROLE_PAYLOAD) or ("", "")
        if kind == "chapter":
            self.focus_graph.emit(payload)  # navigate to source, scroll to title
        elif kind == "concept":
            self.focus_graph.emit(payload)

    def _on_toc_double_clicked(self, item, _column=0):
        """Double-click a concept row → open its evidence in the source text.

        The single click already opens the concept map, so the reader is never
        hijacked: the second click is an explicit "show me where this is said".
        """
        kind, payload = item.data(0, _ROLE_PAYLOAD) or ("", "")
        if kind == "concept" and payload:
            self.jump_evidence.emit(payload, "")

    def _install_search_completer(self):
        """Suggest concept names as the learner types — fast lookup beats
        remembering exact titles.  Rebuilt per _rebuild(), so it always
        reflects the current asset."""
        asset = self._main.get_asset()
        if asset is None or not asset.concepts:
            return
        from PySide6.QtWidgets import QCompleter

        names = [c.name for c in asset.concepts if c.name]
        if not names:
            return
        completer = QCompleter(names, self._concept_search)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._concept_search.setCompleter(completer)

    def _on_concept_filter(self):
        """Filter the TOC tree by search text and mastery level."""
        asset = self._main.get_asset()
        if asset is None or not hasattr(self, "_toc_tree"):
            return
        query = self._concept_search.text().strip().lower()
        filter_idx = self._mastery_filter.currentIndex()

        for i in range(self._toc_tree.topLevelItemCount()):
            ch_item = self._toc_tree.topLevelItem(i)
            ch_visible = False
            for j in range(ch_item.childCount()):
                child = ch_item.child(j)
                data = child.data(0, _ROLE_PAYLOAD) or ("", "")
                if data[0] != "concept":
                    child.setHidden(False)
                    continue
                cid = data[1]
                c = asset.concept_by_id(cid)
                if c is None:
                    child.setHidden(False)
                    continue
                # Text filter
                if query and query not in c.name.lower() and query not in (c.definition or "").lower():
                    child.setHidden(True)
                    continue
                # Favorites filter
                if filter_idx == 5:
                    if not is_favorite(self._main.learner, c.name):
                        child.setHidden(True)
                        continue
                # Notes filter — the learner's own words (generation effect)
                # only pay off if they can be read back; the row shows the
                # note inline instead of just a 📝 marker.
                elif filter_idx == 6:
                    if not has_note(self._main.learner, c.name):
                        child.setHidden(True)
                        continue
                # Mastery filter
                elif filter_idx > 0:
                    nk = normalize(c.name)
                    m = float(
                        self._main.learner.get("concepts", {})
                        .get(nk, {})
                        .get("mastery", 0.0)
                    )
                    if filter_idx == 1 and m > 0:  # unstudied
                        child.setHidden(True)
                        continue
                    elif filter_idx == 2 and not (0 < m < 0.3):  # weak
                        child.setHidden(True)
                        continue
                    elif filter_idx == 3 and not (0.3 <= m < 0.6):  # learning
                        child.setHidden(True)
                        continue
                    elif filter_idx == 4 and m < 0.6:  # mastered
                        child.setHidden(True)
                        continue
                child.setHidden(False)
                base = child.data(0, _ROLE_CAPTION)
                if base:
                    if filter_idx == 6:
                        note = " ".join(
                            (get_note(self._main.learner, c.name) or "").split()
                        )
                        if len(note) > 60:
                            note = note[:60] + "…"
                        child.setText(0, f"{base}  —  {note}")
                    else:
                        child.setText(0, base)
                ch_visible = True
            ch_item.setHidden(not ch_visible and bool(query or filter_idx > 0))

    @staticmethod
    def _progress_color(mastery: float) -> str:
        """Colour for a mastery progress bar — green → amber → red."""
        if mastery >= 0.6:
            return "#2E7D32"  # green — mastered
        elif mastery >= 0.3:
            return "#C8821E"  # amber — partial
        elif mastery > 0:
            return "#E67828"  # orange — weak
        else:
            return "#90A4AE"  # grey — unstudied

    def _start_topic(self, hub_cid):
        """Start learning a topic cluster as a sequential lesson pack.

        Finds the first unmastered concept in the cluster's ordered path
        and hands the full queue to the teach view so the learner sees
        progress through the topic (N of M completed).
        """
        asset = self._main.get_asset()
        if asset is None:
            return
        for cl in topic_clusters(asset):
            if cl["id"] == hub_cid:
                ordered = cl.get("ordered_ids", cl["concept_ids"])
                # Find first concept not yet mastered
                target = None
                mastered_n = 0
                for cid in ordered:
                    nm = (
                        normalize(asset.concept_by_id(cid).name)
                        if asset.concept_by_id(cid)
                        else ""
                    )
                    m = float(
                        self._main.learner.get("concepts", {})
                        .get(nm, {})
                        .get("mastery", 0.0)
                    )
                    if m >= 0.6:
                        mastered_n += 1
                    elif target is None:
                        target = asset.concept_by_id(cid)
                if target is None and ordered:
                    target = asset.concept_by_id(ordered[0])
                    mastered_n = 0
                if target is not None:
                    # Emit with topic context so teach view can show progress
                    self.topic_teach_requested.emit(
                        target.name,
                        cl["name"],
                        [
                            asset.concept_by_id(c).name
                            for c in ordered
                            if asset.concept_by_id(c)
                        ],
                        mastered_n,
                    )
                return

    def _focus_topic(self, hub_cid):
        """Focus the dashboard graph on the hub concept of a topic cluster,
        so the learner can see that cluster's neighbourhood at a glance."""
        self.focus_graph.emit(hub_cid)

    def _on_path_card_click(self, concept_name):
        self.teach_requested.emit(concept_name)

    def _on_graph_click(self, concept_name):
        self.teach_requested.emit(concept_name)

    def _on_dashboard_node_clicked(self, concept_id: str) -> None:
        """Enter the unified map + inspector workspace for this concept."""
        self.focus_graph.emit(concept_id)

    def _on_panorama_game_scored(self, score: float):
        """Panorama sorting game score — lightweight overview check, not a
        per-concept mastery record.  But "watched it, done" is a dead end:
        hand the learner to the adaptive path's first concept either way."""
        label = getattr(self, "_pan_feedback", None)
        btn = getattr(self, "_pan_learn_btn", None)
        if label is None or btn is None:
            return
        # 反馈与「去学下一个」按钮住在折叠区里：确认区必须先展开，否则用户
        # 玩完排序游戏只看到一张静止卡片，反馈被藏起来了。
        sec = getattr(self, "_more_section", None)
        if sec is not None:
            sec.set_expanded(True)
        try:
            pct = round(float(score) * 100)
        except (TypeError, ValueError):
            return
        if pct >= 100:
            label.setText(self._main._t("pan_feedback_full"))
            label.setStyleSheet(
                "font-size: 13px; color: #2E7D32; font-weight: bold;"
            )
        else:
            label.setText(self._main._t("pan_feedback_partial", score=pct))
            label.setStyleSheet("font-size: 13px; color: #E65100;")
        next_name = self._first_path_name()
        if next_name:
            self._pan_next_name = next_name
            btn.setText(f"{self._main._t('start_teach')}：{next_name}")
            btn.setVisible(True)
        else:
            self._pan_next_name = ""
            btn.setVisible(False)
        label.setVisible(True)

    def _first_path_name(self) -> str:
        """First concept of the adaptive path — the coach's top pick."""
        try:
            items = self._main.get_adaptive_path(self._main.current_asset_id)
            for it in items or []:
                name = (it or {}).get("name") or ""
                if name:
                    return name
        except Exception:
            pass
        return ""

    def _on_pan_go_learn(self):
        name = getattr(self, "_pan_next_name", "")
        if name:
            self.teach_requested.emit(name)


# Avoid import cycle: methods are provided by MainWindow
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton
