"""Concept map view: interactive force-directed knowledge graph."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core.learner import normalize
from expert_anything.core.search import search_assets
from expert_anything.core.teacher import anomaly_concept_ids, TeacherModel


class ConceptMapView(QWidget):
    """View 3 — Interactive concept network graph."""

    # Signals to MainWindow
    teach_requested = Signal(str)  # concept_name
    open_concept_panel = Signal(str)  # concept_id
    focus_graph = Signal(str)  # concept_id
    navigate_source = Signal(str)  # concept_id -> scroll to evidence
    evidence_jump_requested = Signal(str, str)  # concept id, evidence text
    quick_quiz_requested = Signal(str)  # concept_id

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._graph_view = None
        self._map_detail = None
        self._scope_combo = None
        self._search_box = None
        self._drill_path_label = None
        self._legend = None
        self._global_asset = None
        self._active_sem_filters: set[str] = set()
        self._sem_filter_buttons: dict[str, QPushButton] = {}
        self._build()

    def refresh(self):
        self._refresh_map()

    def focus_and_show(self, concept_id: str) -> None:
        """Show one concept in the unified map + inspector workspace.

        Cross-view navigation (TOC, dashboard graph, search) should land in
        the same persistent interaction surface instead of opening a modal
        dialog.  The map focuses the node and the inspector shows its grounded
        content in the same frame.
        """
        if not self._graph_view or not self._global_asset:
            return
        if self._global_asset.concept_by_id(concept_id) is None:
            return
        self._graph_view.focus_concept(concept_id)
        self._update_drill_controls()
        self._refresh_detail(concept_id)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(
            self._view_header(
                self._main._t("nav_map"),
                self._main._t("map_subtitle"),
            )
        )

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        if (
            self._main.current_asset_id
            and self._main.current_asset_id in self._main.assets
        ):
            content_layout.addWidget(self._build_toolbar())
            splitter = QSplitter()
            self._graph_view = self._main._graph_view_ref()
            self._graph_view.concept_clicked.connect(self._on_graph_click)
            self._graph_view.node_single_clicked.connect(self._on_node_clicked)
            self._graph_view.edge_clicked.connect(self._on_edge_click)
            self._map_detail = self._main._map_detail_ref()
            self._map_detail.teach_requested.connect(
                lambda n: self.teach_requested.emit(n)
            )
            self._map_detail.full_detail_requested.connect(
                lambda cid: self.open_concept_panel.emit(cid)
            )
            self._map_detail.source_requested.connect(
                lambda cid: self.navigate_source.emit(cid)
            )
            self._map_detail.evidence_jump_requested.connect(
                lambda cn, ev: self.evidence_jump_requested.emit(cn, ev)
            )
            self._map_detail.compare_requested.connect(
                lambda a, b: self._main._open_compare(a, b)
            )
            self._map_detail.quick_quiz_requested.connect(
                lambda cid: self.quick_quiz_requested.emit(cid)
            )
            # The detail card is also a navigation surface.  Without this
            # connection its peer/next-level buttons emitted a signal that no
            # view consumed, so the map looked clickable but never advanced.
            self._map_detail.neighbor_clicked.connect(self._on_detail_neighbor)
            splitter.addWidget(self._graph_view)
            # A concept can have evidence, peers, path position and teacher
            # notes.  Keep all of that available in a scrollable inspector
            # instead of letting the lower half disappear below the splitter.
            detail_scroll = QScrollArea()
            detail_scroll.setWidgetResizable(True)
            detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
            detail_scroll.setMinimumWidth(292)
            detail_scroll.setWidget(self._map_detail)
            splitter.addWidget(detail_scroll)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 0)
            content_layout.addWidget(splitter, 1)

            self._legend = self._build_legend()
            content_layout.addWidget(self._legend)

            self._refresh_map()
        else:
            content_layout.addWidget(self._build_empty_guide())

        layout.addWidget(content)

    def _build_empty_guide(self) -> QWidget:
        """First-run empty state: explain what the map will show and guide the
        newcomer to the import page instead of leaving a bare placeholder."""
        wrap = QWidget()
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 60, 0, 40)
        outer.setSpacing(0)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F7FAFF; border: 1px solid #D6E4F5;"
            "border-radius: 10px; }"
        )
        card.setMaximumWidth(560)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(14)

        title = QLabel(self._main._t("map_empty_title"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #174A7E;")
        lay.addWidget(title)

        desc = QLabel(self._main._t("map_empty_desc"))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #5F6B7A; font-size: 15px;")
        lay.addWidget(desc)

        cta = QPushButton(self._main._t("map_empty_cta"))
        cta.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 10px 22px; font-size: 15.5px;"
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        cta.clicked.connect(lambda: self._main.on_nav_click("import"))
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(cta)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        return wrap

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

    def _build_toolbar(self):
        toolbar_widget = QWidget()
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(self._main._t("search_placeholder"))
        self._search_box.setStyleSheet(
            "QLineEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 5px 10px; font-size: 14.5px; background-color: white; }"
        )
        self._search_box.returnPressed.connect(self._on_search)
        toolbar.addWidget(self._search_box, 1)

        for label, tooltip, callback in [
            (
                "−",
                self._main._t("zoom_out_tip"),
                lambda: self._graph_view.zoom_out() if self._graph_view else None,
            ),
            (
                self._main._t("zoom_fit"),
                self._main._t("zoom_fit"),
                lambda: self._graph_view.fit_content() if self._graph_view else None,
            ),
            (
                "＋",
                self._main._t("zoom_in_tip"),
                lambda: self._graph_view.zoom_in() if self._graph_view else None,
            ),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px;"
                "padding: 5px 10px; font-size: 14.5px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)

        for label, tooltip, callback in [
            (
                self._main._t("reset_map"),
                self._main._t("reset_map"),
                lambda: self._graph_view.reset_focus() if self._graph_view else None,
            ),
            (
                self._main._t("map_back"),
                self._main._t("map_back_tip"),
                lambda: self._graph_view.drill_up() if self._graph_view else None,
            ),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px;"
                "padding: 5px 12px; font-size: 14.5px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)

        self._drill_path_label = QLabel(self._main._t("drill_hint"))
        self._drill_path_label.setStyleSheet(
            "QLabel { color: #546E7A; font-size: 14px; padding: 4px 8px; }"
        )
        toolbar.addWidget(self._drill_path_label, 1)

        # Semantic filter chips
        from expert_anything.core.decoder import REL_SEMANTICS

        sem_types = [
            ("prereq", self._main._t("rel_prereq")),
            ("causes", self._main._t("rel_causes")),
            ("contrast", self._main._t("rel_contrast")),
            ("part_of", self._main._t("rel_part_of")),
            ("is_a", self._main._t("rel_is_a")),
        ]
        for sem_key, sem_label in sem_types:
            color = REL_SEMANTICS[sem_key]["color"]
            btn = QPushButton(sem_label)
            btn.setCheckable(True)
            btn.setToolTip(self._main._t("sem_filter_tip", type=sem_label))
            btn.setStyleSheet(
                f"QPushButton {{ background-color: #F5F7FA; color: #455A64;"
                f"border: 1px solid #CFD8DC; border-radius: 12px;"
                f"padding: 3px 10px; font-size: 13px; }}"
                f"QPushButton:hover {{ background-color: #ECEFF1; }}"
                f"QPushButton:checked {{ background-color: {color}; color: white;"
                f"border: 1px solid {color}; }}"
            )
            btn.clicked.connect(
                lambda checked, s=sem_key: self._on_sem_filter_toggle(s, checked)
            )
            self._sem_filter_buttons[sem_key] = btn
            toolbar.addWidget(btn)

        # Skeleton mode toggle
        self._skeleton_btn = QPushButton(self._main._t("skeleton_view"))
        self._skeleton_btn.setCheckable(True)
        self._skeleton_btn.setToolTip(self._main._t("skeleton_view_tip"))
        self._skeleton_btn.setStyleSheet(
            "QPushButton { background-color: #FFF8E1; color: #E65100;"
            "border: 1px solid #FFE082; border-radius: 6px;"
            "padding: 5px 12px; font-size: 14.5px; font-weight: 500; }"
            "QPushButton:hover { background-color: #FFECB3; }"
            "QPushButton:checked { background-color: #FF8F00; color: white;"
            "border: 1px solid #FF8F00; }"
        )
        self._skeleton_btn.clicked.connect(self._on_toggle_skeleton)
        toolbar.addWidget(self._skeleton_btn)

        # Density heatmap toggle
        self._density_btn = QPushButton(self._main._t("density_view"))
        self._density_btn.setCheckable(True)
        self._density_btn.setToolTip(self._main._t("density_view_tip"))
        self._density_btn.setStyleSheet(
            "QPushButton { background-color: #E8EAF6; color: #283593;"
            "border: 1px solid #9FA8DA; border-radius: 6px;"
            "padding: 5px 12px; font-size: 14.5px; font-weight: 500; }"
            "QPushButton:hover { background-color: #C5CAE9; }"
            "QPushButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            "stop:0 #1565C0, stop:0.5 #FFA000, stop:1 #C62828);"
            "color: white; border: 1px solid #7B1FA2; }"
        )
        self._density_btn.clicked.connect(self._on_toggle_density)
        toolbar.addWidget(self._density_btn)

        # Mastery heatmap toggle
        self._mheat_btn = QPushButton(self._main._t("mastery_heat_view"))
        self._mheat_btn.setCheckable(True)
        self._mheat_btn.setToolTip(self._main._t("mastery_heat_tip"))
        self._mheat_btn.setStyleSheet(
            "QPushButton { background-color: #F1F8E9; color: #2E7D32;"
            "border: 1px solid #A5D6A7; border-radius: 6px;"
            "padding: 5px 12px; font-size: 14.5px; font-weight: 500; }"
            "QPushButton:hover { background-color: #DCEDC8; }"
            "QPushButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            "stop:0 #C62828, stop:0.4 #FFA000, stop:1 #2E7D32);"
            "color: white; border: 1px solid #2E7D32; }"
        )
        self._mheat_btn.clicked.connect(self._on_toggle_mastery_heat)
        toolbar.addWidget(self._mheat_btn)

        self._scope_combo = QComboBox()
        self._scope_combo.addItems(
            [
                self._main._t("scope_all"),
                self._main._t("scope_current"),
            ]
        )
        self._scope_combo.setStyleSheet(
            "QComboBox { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 4px 8px; font-size: 14.5px; background-color: white; }"
        )
        self._scope_combo.currentIndexChanged.connect(self._on_scope_change)
        toolbar.addWidget(self._scope_combo)

        # Export PNG button
        export_btn = QPushButton(self._main._t("export_png"))
        export_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #1565C0;"
            "border: 1px solid #BBDEFB; border-radius: 6px;"
            "padding: 5px 12px; font-size: 14.5px; }"
            "QPushButton:hover { background-color: #E3F2FD; }"
        )
        export_btn.setToolTip(self._main._t("export_png_tip"))
        export_btn.clicked.connect(self._on_export_png)
        toolbar.addWidget(export_btn)

        # Dependency chain button
        self._chain_btn = QPushButton(self._main._t("dep_chain"))
        self._chain_btn.setCheckable(True)
        self._chain_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #00695C;"
            "border: 1px solid #80CBC4; border-radius: 6px;"
            "padding: 5px 12px; font-size: 14.5px; }"
            "QPushButton:hover { background-color: #E0F2F1; }"
            "QPushButton:checked { background-color: #00695C; color: white; }"
        )
        self._chain_btn.setToolTip(self._main._t("dep_chain_tip"))
        self._chain_btn.clicked.connect(self._on_chain_toggle)
        toolbar.addWidget(self._chain_btn)

        return toolbar_widget

    def _build_legend(self):
        from expert_anything.ui.widgets.map_widgets import MapLegend

        legend = MapLegend()
        return legend

    def _on_chain_toggle(self):
        """Toggle dependency chain highlight mode."""
        if self._chain_btn.isChecked():
            # Highlight chain for currently focused concept
            focus_id = self._graph_view._focus_id if self._graph_view else None
            if focus_id:
                self._graph_view.highlight_dependency_chain(focus_id)
        else:
            self._graph_view.highlight_dependency_chain(None)

    def _on_toggle_mastery_heat(self):
        """Toggle mastery heatmap mode."""
        if not self._graph_view:
            return
        active = self._graph_view.toggle_mastery_heatmap()
        self._mheat_btn.setChecked(active)
        if active and self._density_btn:
            self._density_btn.setChecked(False)

    def _on_export_png(self):
        """Export the current knowledge graph as a PNG image."""
        if not self._graph_view:
            return
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        asset = self._main.get_asset()
        default_name = (
            f"knowledge_map_{asset.asset_id[:12]}.png" if asset else "knowledge_map.png"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self._main._t("export_png_dialog"),
            default_name,
            "PNG Images (*.png)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".png"):
            file_path += ".png"
        ok = self._graph_view.export_png(file_path)
        if ok:
            QMessageBox.information(
                self,
                self._main._t("export_success"),
                self._main._t("export_saved_to", path=file_path),
            )
        else:
            QMessageBox.warning(
                self,
                self._main._t("export_failed"),
                self._main._t("export_failed_msg"),
            )

    def _refresh_map(self):
        if not hasattr(self, "_graph_view") or not self._main.current_asset_id:
            return
        scope_all = self._scope_combo.currentIndex() == 0
        if scope_all:
            asset, grey_ids = self._main._build_global_asset()
        else:
            asset = self._main.get_asset()
            grey_ids = set()
        self._global_asset = asset

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
                tm = TeacherModel.from_dict(td)
                anomaly_ids = anomaly_concept_ids(asset, tm)
            except Exception:
                anomaly_ids = set()

        items = self._main.get_adaptive_path(self._main.current_asset_id)
        current_id = items[0].get("cid") if items else None
        path_ids = [item.get("cid") for item in items[:6] if item.get("cid")]

        self._graph_view.set_asset(
            asset,
            mastery_map=mastery_map,
            anomaly_ids=anomaly_ids,
            current_id=current_id,
            grey_ids=grey_ids,
            path_ids=path_ids,
        )
        # Large books start in the readable backbone view; the button remains
        # the explicit escape hatch to the full network.
        if hasattr(self, "_skeleton_btn") and self._skeleton_btn:
            enabled = bool(getattr(self._graph_view, "_skeleton_mode", False))
            self._skeleton_btn.setChecked(enabled)
            self._skeleton_btn.setText(
                self._main._t("skeleton_exit" if enabled else "skeleton_view")
            )
        self._update_drill_controls()

    def _on_search(self):
        kw = self._search_box.text().strip().lower()
        if not kw or not self._graph_view:
            return

        # First: search within current asset's graph (existing behavior)
        for cid, name, _role in self._graph_view._nodes:
            if kw in name.lower():
                self._graph_view.focus_concept(cid)
                return

        # Second: search across ALL loaded assets by concept name
        results = []
        for asset_id, asset in self._main.assets.items():
            for c in getattr(asset, "concepts", []) or []:
                if kw in c.name.lower():
                    results.append((asset_id, asset, c))

        if not results:
            # No concept-name match: fall back to full-text search across
            # definitions / evidence / source anchors (P1-2).
            hits = search_assets(self._main.assets.values(), kw, limit=40)
            if hits:
                self._show_fulltext_results(hits, kw)
                return
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                self._main._t("search_title"),
                self._main._t("not_found_in_map", kw=self._search_box.text().strip()),
            )
            return

        if len(results) == 1:
            # Single result: switch asset and focus
            asset_id, asset, c = results[0]
            if asset_id != self._main.current_asset_id:
                self._main.on_asset_select(asset_id)
            self._graph_view.focus_concept(c.id)
            return

        # Multiple results: show a popup list
        self._show_name_results(results, kw)

    def _show_name_results(self, results, kw: str):
        """Popup listing concepts whose *name* contains the keyword."""
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QPushButton,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(self._main._t("search_results_title"))
        dlg.setMinimumWidth(400)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)
        hint = QLabel(self._main._t("search_results_hint", n=len(results), kw=kw))
        hint.setStyleSheet("color: #546E7A; font-size: 14px;")
        lay.addWidget(hint)

        lst = QListWidget()
        for asset_id, asset, c in results:
            asset_name = getattr(asset, "title", asset_id)
            item_text = f"{c.name}  ({asset_name})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole + 1, asset_id)
            item.setData(Qt.UserRole + 2, c.id)
            lst.addItem(item)
        lst.itemDoubleClicked.connect(self._on_search_result_activated)
        lay.addWidget(lst)

        open_btn = QPushButton(self._main._t("search_open"))
        open_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        open_btn.clicked.connect(
            lambda: self._on_search_result_activated(lst.currentItem())
        )
        lay.addWidget(open_btn)

        dlg.exec()

    def _show_fulltext_results(self, hits, kw: str):
        """Popup listing full-text matches (name missed): field + snippet + anchor."""
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QVBoxLayout,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QPushButton,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(self._main._t("search_fulltext_title"))
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)

        hint = QLabel(self._main._t("search_fulltext_hint", n=len(hits), kw=kw))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #546E7A; font-size: 13.5px;")
        lay.addWidget(hint)

        field_keys = {
            "name": "search_field_name",
            "alias": "search_field_alias",
            "definition": "search_field_definition",
            "summary": "search_field_summary",
            "evidence": "search_field_evidence",
            "source": "search_field_source",
        }
        lst = QListWidget()
        for h in hits:
            fk = field_keys.get(h.field, "search_field_source")
            field_label = self._main._t(fk)
            asset_name = h.asset_title or h.asset_id
            anchor = ""
            if h.page:
                anchor = f" · p.{h.page}"
            elif h.chapter:
                anchor = f" · {h.chapter}"
            head = f"{h.concept_name}  [{field_label}]  ({asset_name}{anchor})"
            item = QListWidgetItem(f"{head}\n    {h.snippet}")
            item.setToolTip(h.snippet)
            item.setData(Qt.UserRole + 1, h.asset_id)
            item.setData(Qt.UserRole + 2, h.concept_id)
            lst.addItem(item)
        lst.itemDoubleClicked.connect(self._on_search_result_activated)
        lay.addWidget(lst)

        btn = QPushButton(self._main._t("search_open"))
        btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        btn.clicked.connect(lambda: self._on_search_result_activated(lst.currentItem()))
        lay.addWidget(btn)

        dlg.exec()

    def _on_search_result_activated(self, item):
        """Open a search result: switch asset if needed, then focus concept."""
        if item is None:
            return
        asset_id = item.data(Qt.UserRole + 1)
        cid = item.data(Qt.UserRole + 2)
        if asset_id and asset_id != self._main.current_asset_id:
            self._main.on_asset_select(asset_id)
        if cid and self._graph_view:
            self._graph_view.focus_concept(cid)

    def _on_scope_change(self, _idx):
        self._refresh_map()

    def _on_sem_filter_toggle(self, sem_key: str, checked: bool) -> None:
        """Toggle a semantic relation type filter on/off."""
        if checked:
            self._active_sem_filters.add(sem_key)
        else:
            self._active_sem_filters.discard(sem_key)
        if self._graph_view:
            self._graph_view.set_semantic_filter(self._active_sem_filters)

    def _on_toggle_skeleton(self) -> None:
        """Toggle core skeleton view on/off."""
        if not self._graph_view:
            return
        enabled = self._graph_view.toggle_skeleton_mode()
        if hasattr(self, "_skeleton_btn") and self._skeleton_btn:
            self._skeleton_btn.setChecked(enabled)
            self._skeleton_btn.setText(
                self._main._t("skeleton_exit" if enabled else "skeleton_view")
            )

    def _on_toggle_density(self) -> None:
        """Toggle knowledge-density heatmap on/off."""
        if not self._graph_view:
            return
        enabled = self._graph_view.toggle_density_mode()
        if hasattr(self, "_density_btn") and self._density_btn:
            self._density_btn.setChecked(enabled)
        if enabled and hasattr(self, "_mheat_btn") and self._mheat_btn:
            self._mheat_btn.setChecked(False)

    def _on_graph_click(self, concept_name):
        self.teach_requested.emit(concept_name)

    def _on_detail_neighbor(self, concept_id: str) -> None:
        """Navigate from an inspector item to the next concept.

        This deliberately refreshes both panes: the graph recentres on the
        selected neighbour and the inspector replaces its content with that
        neighbour's definition/evidence/children.
        """
        if not self._graph_view or not self._global_asset:
            return
        if self._global_asset.concept_by_id(concept_id) is None:
            return
        self.focus_and_show(concept_id)

    def _on_node_clicked(self, concept_id: str):
        if not self._graph_view:
            return
        was_focused = self._graph_view._focus_id == concept_id
        if was_focused:
            self._graph_view.drill_down(concept_id)
        else:
            self._graph_view.focus_concept(concept_id)
        self._update_drill_controls()
        # If chain mode is active, update chain highlight for newly focused concept
        if hasattr(self, "_chain_btn") and self._chain_btn.isChecked():
            self._graph_view.highlight_dependency_chain(concept_id)
        if str(concept_id).startswith("ext:"):
            self._explain_external(concept_id)
            return
        self._refresh_detail(concept_id)

    def _on_edge_click(self, src_id: str, tgt_id: str, rel_label: str):
        """When an edge is clicked, teach the source concept (which has the relation)."""
        asset = self._global_asset or self._main.get_asset()
        if asset is None:
            return
        src_c = asset.concept_by_id(src_id)
        tgt_c = asset.concept_by_id(tgt_id)
        if not src_c:
            return
        # Teach the source concept — the relation provides context
        from PySide6.QtWidgets import QMessageBox
        from expert_anything.core.decoder import classify_relation

        sem = classify_relation(rel_label, "")
        sem_name = (
            self._main._t("rel_" + sem)
            if sem
            in {
                "prereq",
                "causes",
                "is_a",
                "part_of",
                "contrast",
                "related",
            }
            else self._main._t("rel_default")
        )
        tgt_name = tgt_c.name if tgt_c else tgt_id
        msg = self._main._t(
            "edge_teach_msg", rel=sem_name, src=src_c.name, tgt=tgt_name
        )
        reply = QMessageBox.question(
            self,
            self._main._t("edge_teach_title"),
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.teach_requested.emit(src_c.name)

    def _explain_external(self, concept_id: str):
        asset = self._global_asset
        if asset is None:
            return
        c = asset.concept_by_id(concept_id)
        if c is None:
            return
        if self._main.llm_client is None:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                self._main._t("hint"),
                self._main._t("external_no_llm", name=c.name),
            )
            return
        try:
            from expert_anything.core.llm import Message

            anchor_name = ""
            for r in asset.relations:
                if r.target == concept_id:
                    a = asset.concept_by_id(r.source)
                    if a:
                        anchor_name = a.name
                        break
            lang_hint = ""
            if self._main._get_lang() == "en":
                lang_hint = "Answer in English. "
            elif self._main._get_lang() == "ja":
                lang_hint = "日本語で回答してください。"

            prompt = (
                f"概念「{c.name}」来自外部知识（不在本书中），"
                f"它与书中的「{anchor_name or '当前概念'}」相关。"
                f"请用 3-5 句话解释这个概念是什么、为什么与「{anchor_name}」相关，"
                f"并用一个技术人员容易理解的类比帮助建立直觉。"
                f" {lang_hint}"
            )
            ans = self._main.llm_client.chat(
                [Message("user", prompt)],
                temperature=0.3,
                max_tokens=400,
            )
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                f"{self._main._t('external_title')}「{c.name}」",
                ans,
            )
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(self, self._main._t("hint"), str(e))

    def _refresh_detail(self, concept_id: str):
        if self._map_detail is None or self._global_asset is None:
            return
        teacher = None
        td = self._main.teacher_models.get(self._main.current_asset_id)
        if td:
            try:
                teacher = TeacherModel.from_dict(td)
            except Exception:
                teacher = None
        self._map_detail.set_concept(
            self._global_asset,
            concept_id,
            self._main.learner,
            teacher,
        )

    def _update_drill_controls(self):
        if not hasattr(self, "_drill_path_label") or not self._graph_view:
            return
        path = self._graph_view.drill_path()
        asset = self._global_asset
        names = []
        for cid in path:
            c = asset.concept_by_id(cid) if asset else None
            names.append((c.name if c else cid))
        self._drill_path_label.setText(
            self._main._t("drill_current_prefix")
            + (" > ".join(names) if names else self._main._t("drill_all"))
            + self._main._t("drill_continue")
        )
