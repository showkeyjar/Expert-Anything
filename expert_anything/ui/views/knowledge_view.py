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
    normalize,
    record_evaluation,
    topic_clusters,
)
from expert_anything.core.teacher import anomaly_concept_ids, TeacherModel
from expert_anything.core.i18n import t
from expert_anything.ui.widgets.shared import StatCard


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
        header = QFrame()
        header.setStyleSheet(
            "background-color: white; border-bottom: 2px solid #1565C0;"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 7, 20, 7)
        lay.setSpacing(10)
        t = QLabel(str(title))
        t.setStyleSheet("font-size: 18px; font-weight: bold; color: #1F2933;")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(str(subtitle))
            s.setStyleSheet("color: #6B7A90; font-size: 13.5px;")
            lay.addWidget(s)
        lay.addStretch()
        return header

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
            ("📚", self._main._t("stat_total"), stats["total"], "#1565C0"),
            ("✓", self._main._t("legend_mastered"), stats["mastered"], "#4CAF50"),
            ("↗", self._main._t("legend_learning"), stats["learning"], "#FF9800"),
            ("○", self._main._t("stat_unstudied"), stats["unstudied"], "#9E9E9E"),
            ("⚠", self._main._t("stat_anomaly"), stats["anomalies"], "#F44336"),
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
        filter_row.addWidget(self._concept_search, 1)

        self._mastery_filter = QComboBox()
        self._mastery_filter.addItems([
            self._main._t("filter_all"),
            self._main._t("filter_unstudied"),
            self._main._t("filter_weak"),
            self._main._t("filter_learning"),
            self._main._t("filter_mastered"),
        ])
        self._mastery_filter.setStyleSheet(
            "QComboBox { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 4px 8px; font-size: 14px; background-color: white; }"
        )
        self._mastery_filter.currentIndexChanged.connect(self._on_concept_filter)
        filter_row.addWidget(self._mastery_filter)
        dlayout.addLayout(filter_row)

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
                    dlayout.addWidget(pan_card)
            except Exception:
                pass

        # TOC and topic clusters
        if asset is not None:
            # TOC
            toc_card = QFrame()
            toc_card.setStyleSheet(
                "QFrame { background-color: white; border: 1px solid #E0E0E0;"
                "border-radius: 10px; }"
            )
            toc_lay = QVBoxLayout(toc_card)
            toc_lay.setContentsMargins(16, 12, 16, 12)
            toc_lay.setSpacing(6)

            toc_title = QLabel(self._main._t("toc_title"))
            toc_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #1F2933;"
            )
            toc_lay.addWidget(toc_title)

            toc_hint = QLabel(self._main._t("toc_hint"))
            toc_hint.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            toc_lay.addWidget(toc_hint)

            self._toc_tree = QTreeWidget()
            self._toc_tree.setHeaderHidden(True)
            self._toc_tree.setMaximumHeight(240)
            self._toc_tree.setStyleSheet(
                "QTreeWidget { background-color: #FAFAFA; border: 1px solid #E0E0E0;"
                "border-radius: 6px; font-size: 14.5px; }"
                "QTreeWidget::item { padding: 3px; }"
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

                top = QTreeWidgetItem([""])
                top.setData(0, 2, ("chapter", ch_title))
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
                    child = QTreeWidgetItem([f"  {c.name}  [{label}]"])
                    child.setData(0, 2, ("concept", c.id))
                    child.setData(0, 3, diff)
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
                top.setData(0, 2, ("chapter", ""))
                for c in unassigned[:20]:
                    diff = diff_map.get(c.name, "unknown")
                    bg, fg, label = diff_colors.get(diff, diff_colors["unknown"])
                    child = QTreeWidgetItem([f"  {c.name}  [{label}]"])
                    child.setData(0, 2, ("concept", c.id))
                    child.setData(0, 3, diff)
                    top.addChild(child)
                self._toc_tree.addTopLevelItem(top)
            if self._toc_tree.topLevelItemCount() == 0:
                self._toc_tree.addTopLevelItem(
                    QTreeWidgetItem([self._main._t("chapter_empty")])
                )
            self._toc_tree.itemClicked.connect(self._on_toc_clicked)
            toc_lay.addWidget(self._toc_tree)
            dlayout.addWidget(toc_card)

            # Topic clusters
            clusters = topic_clusters(asset)
            big = [c for c in clusters if c["size"] >= 2][:8]
            if big:
                topic_card = QFrame()
                topic_card.setStyleSheet(
                    "QFrame { background-color: white; border: 1px solid #E0E0E0;"
                    "border-radius: 10px; }"
                )
                tp_lay = QVBoxLayout(topic_card)
                tp_lay.setContentsMargins(16, 12, 16, 12)
                tp_lay.setSpacing(6)
                tp_title = QLabel(self._main._t("topics_title"))
                tp_title.setStyleSheet(
                    "font-size: 16px; font-weight: bold; color: #1F2933;"
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
                    tp_lay.addLayout(row)
                dlayout.addWidget(topic_card)

        # Adaptive path + graph
        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)

        section_title = QLabel(self._main._t("section_recommend"))
        section_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #1565C0; padding: 4px 0;"
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
            "font-size: 16px; font-weight: bold; color: #1565C0; padding: 4px 0;"
        )
        graph_layout.addWidget(graph_title)

        self._dash_graph = self._main._dash_graph_ref()
        self._dash_graph.setMinimumHeight(300)
        self._dash_graph.setStyleSheet(
            "QGraphicsView { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
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

        dlayout.addWidget(graph_container)
        dlayout.addStretch()
        return drawer

    def _on_toc_clicked(self, item):
        kind, payload = item.data(0, 2) or ("", "")
        if kind == "chapter":
            self.focus_graph.emit(payload)  # navigate to source, scroll to title
        elif kind == "concept":
            self.focus_graph.emit(payload)

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
                data = child.data(0, 2) or ("", "")
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
                # Mastery filter
                if filter_idx > 0:
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
        per-concept mastery record. Keeps the game meaningful without
        polluting the learning trajectory."""
        pass


# Avoid import cycle: methods are provided by MainWindow
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton
