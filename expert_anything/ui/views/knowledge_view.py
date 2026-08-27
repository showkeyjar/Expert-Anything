"""Knowledge model view: adaptive learning path + dashboard."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from expert_anything.core.learner import (
    adaptive_path, concept_density, normalize, topic_clusters,
)
from expert_anything.core.teacher import anomaly_concept_ids, TeacherModel
from expert_anything.ui.widgets.shared import StatCard


def localize_method(method: str) -> str:
    """Translate an extraction method string to a human-readable label."""
    table = {
        "llm_extraction_chunked_v1": "LLM 多分块并行抽取",
        "llm_extraction_v1": "LLM 抽取",
        "llm_failed_fallback_v1": "确定性降级",
        "deterministic_fallback_v1": "确定性降级",
    }
    return table.get(method, method)


class KnowledgeView(QWidget):
    """View 2 — Knowledge model (dashboard + adaptive path + TOC + clusters)."""

    # Signals to MainWindow
    open_concept_panel = Signal(str)    # concept_id
    teach_requested = Signal(str)       # concept_name
    focus_graph = Signal(str)            # concept_id
    jump_evidence = Signal(str, str)     # concept_id, evidence

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
        self._root_layout.addWidget(self._view_header(
            self._main._t("nav_knowledge"),
            self._main._get_asset_subtitle(),
        ))

        # Fallback warning
        cur_asset = self._main.get_asset()
        if cur_asset is not None:
            mlow = (cur_asset.method or "").lower()
            if "fallback" in mlow or "failed" in mlow or "deterministic" in mlow:
                warn = QLabel(
                    self._main._t("dash_fallback_warn",
                                   method=localize_method(cur_asset.method))
                )
                warn.setWordWrap(True)
                warn.setStyleSheet(
                    "background-color:#FFF4E5; color:#8A4B00; border:1px solid #FFD28A;"
                    "border-radius:8px; padding:10px 14px; font-size:13px; margin:0 16px;"
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
        header.setStyleSheet("background-color: white; border-bottom: 2px solid #1565C0;")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 7, 20, 7)
        lay.setSpacing(10)
        t = QLabel(str(title))
        t.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2933;")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(str(subtitle))
            s.setStyleSheet("color: #6B7A90; font-size: 11.5px;")
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
            ("📚", self._main._t("stat_total"), stats['total'], "#1565C0"),
            ("✓", self._main._t("legend_mastered"), stats['mastered'], "#4CAF50"),
            ("↗", self._main._t("legend_learning"), stats['learning'], "#FF9800"),
            ("○", self._main._t("stat_unstudied"), stats['unstudied'], "#9E9E9E"),
            ("⚠", self._main._t("stat_anomaly"), stats['anomalies'], "#F44336"),
        ]:
            stats_layout.addWidget(StatCard(*card))
        stats_layout.addStretch()
        dlayout.addLayout(stats_layout)

        asset = self._main.get_asset()
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
            toc_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2933;")
            toc_lay.addWidget(toc_title)

            toc_hint = QLabel(self._main._t("toc_hint"))
            toc_hint.setStyleSheet("font-size: 11px; color: #9E9E9E;")
            toc_lay.addWidget(toc_hint)

            self._toc_tree = QTreeWidget()
            self._toc_tree.setHeaderHidden(True)
            self._toc_tree.setMaximumHeight(240)
            self._toc_tree.setStyleSheet(
                "QTreeWidget { background-color: #FAFAFA; border: 1px solid #E0E0E0;"
                "border-radius: 6px; font-size: 12.5px; }"
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
            for ch_title in ordered:
                top = QTreeWidgetItem([ch_title])
                top.setData(0, 2, ("chapter", ch_title))
                for c in by_ch[ch_title][:25]:
                    child = QTreeWidgetItem([f"  {c.name}"])
                    child.setData(0, 2, ("concept", c.id))
                    top.addChild(child)
                self._toc_tree.addTopLevelItem(top)
            unassigned = [c for k, lst in by_ch.items() if not k for c in lst]
            if unassigned:
                top = QTreeWidgetItem([self._main._t("toc_other")])
                top.setData(0, 2, ("chapter", ""))
                for c in unassigned[:20]:
                    child = QTreeWidgetItem([f"  {c.name}"])
                    child.setData(0, 2, ("concept", c.id))
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
                    "font-size: 14px; font-weight: bold; color: #1F2933;"
                )
                tp_lay.addWidget(tp_title)
                tp_hint = QLabel(self._main._t("topics_hint"))
                tp_hint.setWordWrap(True)
                tp_hint.setStyleSheet("font-size: 11px; color: #9E9E9E;")
                tp_lay.addWidget(tp_hint)

                for cl in big:
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    name_lbl = QLabel(
                        f"{cl['name']}  ·  "
                        f"{self._main._t('topic_size', n=cl['size'])}"
                    )
                    name_lbl.setStyleSheet(
                        "font-size: 12.5px; font-weight: bold; color: #0c4a6e;"
                        "background-color: #E8F0F8; border-radius: 6px; padding: 4px 10px;"
                    )
                    row.addWidget(name_lbl)
                    for cid in cl["concept_ids"][:5]:
                        c = asset.concept_by_id(cid)
                        if c:
                            chip = QLabel(c.name)
                            chip.setStyleSheet(
                                "background-color: #F3E5F5; color: #6A1B9A;"
                                "border-radius: 10px; padding: 2px 8px; font-size: 10.5px;"
                            )
                            row.addWidget(chip)
                    row.addStretch()
                    learn_btn = QPushButton(self._main._t("learn_topic"))
                    learn_btn.setStyleSheet(
                        "QPushButton { background-color: white; color: #6A1B9A;"
                        "border: 1px solid #CE93D8; border-radius: 6px; padding: 3px 10px;"
                        "font-size: 11px; }"
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
            "font-size: 14px; font-weight: bold; color: #1565C0; padding: 4px 0;"
        )
        cards_layout.addWidget(section_title)

        self._path_ladder = self._main._path_ladder_ref()
        self._path_ladder.concept_clicked.connect(self._on_path_card_click)
        if self._main.current_asset_id:
            path_items = self._main.get_adaptive_path(self._main.current_asset_id)
            entry = self._main.learner.get('assets', {}).get(
                self._main.current_asset_id, {}
            )
            completed = set(entry.get('completed', []))
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
            "font-size: 14px; font-weight: bold; color: #1565C0; padding: 4px 0;"
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
                        self._main.learner.get('concepts', {})
                        .get(norm_name, {})
                        .get('mastery', 0.0)
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
                current_id = items[0].get('cid') if items else None
                self._dash_graph.set_asset(
                    asset, mastery_map=mastery_map,
                    anomaly_ids=anomaly_ids, current_id=current_id,
                )
                self._dash_graph.concept_clicked.connect(self._on_graph_click)

        dlayout.addWidget(graph_container)
        dlayout.addStretch()
        return drawer

    def _on_toc_clicked(self, item):
        kind, payload = item.data(0, 2) or ("", "")
        if kind == "chapter":
            self.focus_graph.emit(payload)  # navigate to source, scroll to title
        elif kind == "concept":
            self.open_concept_panel.emit(payload)

    def _start_topic(self, hub_cid):
        asset = self._main.get_asset()
        if asset is None:
            return
        for cl in topic_clusters(asset):
            if cl["id"] == hub_cid:
                order = [c for c in asset.learning_path if c in cl["concept_ids"]]
                order += [c for c in cl["concept_ids"] if c not in order]
                target = None
                for cid in order:
                    completed = set(
                        self._main.learner.get("assets", {})
                        .get(self._main.current_asset_id, {})
                        .get("completed", [])
                    )
                    if cid not in completed:
                        target = asset.concept_by_id(cid)
                        break
                if target is None and order:
                    target = asset.concept_by_id(order[0])
                if target is not None:
                    self.teach_requested.emit(target.name)
                return

    def _on_path_card_click(self, concept_name):
        self.teach_requested.emit(concept_name)

    def _on_graph_click(self, concept_name):
        self.teach_requested.emit(concept_name)


# Avoid import cycle: methods are provided by MainWindow
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton
