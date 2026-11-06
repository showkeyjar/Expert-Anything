"""Concept map view: interactive force-directed knowledge graph."""

from __future__ import annotations

from pathlib import Path

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
from expert_anything.core.knowledge_index import indexed_search
from expert_anything.core.teacher import anomaly_concept_ids, TeacherModel
from expert_anything.ui import theme
from expert_anything.ui.widgets.shared import PageHeader


def _toggle_style() -> str:
    """One look for every toolbar toggle (the old ones each picked their own
    candy colour and gradient, which is what made the toolbar feel busy)."""
    return (
        f"QPushButton {{ background-color: {theme.SURFACE};"
        f" color: {theme.TEXT_MUTED}; border: 1px solid {theme.BORDER};"
        f" border-radius: {theme.RADIUS_MD}px; padding: 5px 12px;"
        " font-size: 13px; }"
        f"QPushButton:hover {{ background-color: {theme.SURFACE_HOVER};"
        f" color: {theme.TEXT}; }}"
        f"QPushButton:checked {{ background-color: {theme.ACCENT_TINT};"
        f" border-color: {theme.ACCENT_SOFT}; color: {theme.ACCENT_HOVER};"
        " font-weight: 600; }"
    )


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
        self._breadcrumb_host = None
        self._legend = None
        self._global_asset = None
        self._active_sem_filters: set[str] = set()
        self._sem_filter_buttons: dict[str, QPushButton] = {}
        self._build()

    # 标记文件路径：首次看到引导后就不再弹
    _ONBOARDING_MARKER = Path("data/.cm_onboarding_seen")

    def refresh(self):
        self._refresh_map()
        # 首次进入认知地图时给小白一个 3 步引导层
        if (
            self._graph_view is not None
            and self._global_asset is not None
            and self._global_asset.concepts
            and not self._ONBOARDING_MARKER.exists()
        ):
            self._show_onboarding()
            try:
                self._ONBOARDING_MARKER.parent.mkdir(parents=True, exist_ok=True)
                self._ONBOARDING_MARKER.touch()
            except OSError:
                pass  # 允许只读环境

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
        self._content_layout = content_layout

        if (
            self._main.current_asset_id
            and self._main.current_asset_id in self._main.assets
        ):
            content_layout.addWidget(self._build_toolbar())
            self._more_row = self._build_more_row()
            content_layout.addWidget(self._more_row)
            splitter = QSplitter()
            self._graph_view = self._main._graph_view_ref()
            # The main map is the drill-down surface: double-click enters a
            # concept's subgraph (breadcrumb on top), right-click still offers
            # teaching.  Embedded mini-graphs keep double-click-to-teach.
            self._graph_view.enable_drill_down()
            self._graph_view.node_drilled.connect(self._on_node_drilled)
            self._graph_view.concept_clicked.connect(self._on_graph_click)
            self._graph_view.node_single_clicked.connect(self._on_node_clicked)
            self._graph_view.edge_clicked.connect(self._on_edge_click)
            # The graph widget survives view rebuilds — reflect its current
            # mastery band in the freshly-created combo without re-rendering.
            self._sync_mastery_filter_combo()
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
        cta.setCursor(Qt.CursorShape.PointingHandCursor)
        cta.setStyleSheet(theme.primary_button_style())
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
        return PageHeader(title, subtitle)

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

        # 缩放组合：三个按钮紧挨，视觉上合成一个工具组
        zoom_group = QWidget()
        zoom_lay = QHBoxLayout(zoom_group)
        zoom_lay.setContentsMargins(0, 0, 0, 0)
        zoom_lay.setSpacing(0)
        zoom_style_normal = (
            f"QPushButton {{ background-color: {theme.SURFACE};"
            f" color: {theme.ACCENT}; border: 1px solid {theme.BORDER};"
            " padding: 5px 10px; font-size: 13px;"
            "border-top-left-radius:6px; border-bottom-left-radius:6px;"
            "border-top-right-radius:0px; border-bottom-right-radius:0px; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_TINT}; }}"
        )
        zoom_style_mid = (
            f"QPushButton {{ background-color: {theme.SURFACE};"
            f" color: {theme.ACCENT}; border-top: 1px solid {theme.BORDER};"
            f" border-bottom: 1px solid {theme.BORDER};"
            " padding: 5px 10px; font-size: 13px; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_TINT}; }}"
        )
        zoom_style_end = (
            f"QPushButton {{ background-color: {theme.SURFACE};"
            f" color: {theme.ACCENT}; border: 1px solid {theme.BORDER};"
            " border-top-left-radius:0px; border-bottom-left-radius:0px;"
            " border-top-right-radius:6px; border-bottom-right-radius:6px;"
            " padding: 5px 10px; font-size: 13px; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_TINT}; }}"
        )

        btn_out = QPushButton("−")
        btn_out.setToolTip(self._main._t("zoom_out_tip"))
        btn_out.setStyleSheet(zoom_style_normal)
        btn_out.clicked.connect(lambda: self._graph_view.zoom_out() if self._graph_view else None)
        zoom_lay.addWidget(btn_out)

        btn_fit = QPushButton(self._main._t("zoom_fit"))
        btn_fit.setToolTip(self._main._t("zoom_fit"))
        btn_fit.setStyleSheet(zoom_style_mid)
        btn_fit.clicked.connect(lambda: self._graph_view.fit_content() if self._graph_view else None)
        zoom_lay.addWidget(btn_fit)

        btn_in = QPushButton("＋")
        btn_in.setToolTip(self._main._t("zoom_in_tip"))
        btn_in.setStyleSheet(zoom_style_end)
        btn_in.clicked.connect(lambda: self._graph_view.zoom_in() if self._graph_view else None)
        zoom_lay.addWidget(btn_in)
        toolbar.addWidget(zoom_group)

        # 显式下钻入口：选中节点时出现「展开子图」按钮
        # （等同于双击手势的显式入口，避免"双击"成为隐藏功能）
        self._drill_btn = QPushButton(self._main._t("drill_btn_label"))
        self._drill_btn.setToolTip(self._main._t("drill_btn_tip"))
        self._drill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drill_btn.setStyleSheet(theme.primary_button_style(compact=True))
        self._drill_btn.clicked.connect(self._on_explicit_drill)
        self._drill_btn.setVisible(False)
        toolbar.addWidget(self._drill_btn)

        # Breadcrumb bar: 全部知识 › A › B — every segment is a one-click jump
        # back up the drill trail (下钻必须可回退).
        self._breadcrumb_host = QWidget()
        crumb_lay = QHBoxLayout(self._breadcrumb_host)
        crumb_lay.setContentsMargins(0, 0, 0, 0)
        crumb_lay.setSpacing(2)
        toolbar.addWidget(self._breadcrumb_host, 1)

        # 「更多工具」: reset/back/范围切换/热力图/过滤/导出等进阶功能
        self._more_btn = QPushButton("▸ " + self._main._t("more_tools"))
        self._more_btn.setToolTip(self._main._t("more_tools_hint"))
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_MUTED}; border: none; padding: 5px 6px;"
            " font-size: 12.5px; font-weight: 600; }"
            f"QPushButton:hover {{ color: {theme.ACCENT}; }}"
        )
        self._more_btn.clicked.connect(self._on_toggle_more_tools)
        toolbar.addWidget(self._more_btn)

        return toolbar_widget

    def _build_more_row(self):
        """Secondary toolbar row (reset/back/范围切换/语义过滤/热力图/导出…).
        Hidden by default; toggled by the 「更多工具」 button."""
        row_widget = QWidget()
        row_widget.setVisible(False)
        toolbar = QHBoxLayout(row_widget)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        # reset_map / map_back — 进阶状态维护操作，小白不需要在首行看到
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
                "QPushButton { background-color: white; color: #455A64;"
                "border: 1px solid #CFD8DC; border-radius: 6px;"
                "padding: 4px 10px; font-size: 13.5px; }"
                "QPushButton:hover { background-color: #ECEFF1; }"
            )
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)

        # 范围切换（全部资产 / 仅当前资产）——跨资产场景是进阶用法
        self._scope_combo = QComboBox()
        self._scope_combo.addItems(
            [
                self._main._t("scope_all"),
                self._main._t("scope_current"),
            ]
        )
        self._scope_combo.setStyleSheet(
            "QComboBox { border: 1px solid #CFD8DC; border-radius: 6px;"
            "padding: 3px 7px; font-size: 13.5px; background-color: white; }"
        )
        self._scope_combo.currentIndexChanged.connect(self._on_scope_change)
        toolbar.addWidget(self._scope_combo)

        # 分隔线（小竖线，视觉上把"导航状态"和"过滤/视图模式"区分开）
        sep = QLabel("│")
        sep.setStyleSheet("color: #CFD8DC; font-size: 14px; padding: 0 2px;")
        toolbar.addWidget(sep)

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
        self._density_btn.setStyleSheet(_toggle_style())
        self._density_btn.clicked.connect(self._on_toggle_density)
        toolbar.addWidget(self._density_btn)

        # Mastery heatmap toggle
        self._mheat_btn = QPushButton(self._main._t("mastery_heat_view"))
        self._mheat_btn.setCheckable(True)
        self._mheat_btn.setToolTip(self._main._t("mastery_heat_tip"))
        self._mheat_btn.setStyleSheet(_toggle_style())
        self._mheat_btn.clicked.connect(self._on_toggle_mastery_heat)
        toolbar.addWidget(self._mheat_btn)

        # 2-hop breadth exploration toggle
        self._hop2_btn = QPushButton(self._main._t("hop2_view"))
        self._hop2_btn.setCheckable(True)
        self._hop2_btn.setToolTip(self._main._t("hop2_tip"))
        self._hop2_btn.setStyleSheet(_toggle_style())
        self._hop2_btn.clicked.connect(self._on_toggle_hop2)
        toolbar.addWidget(self._hop2_btn)

        # Mastery band filter — isolate "what's left to learn" (full network
        # only; focus mode keeps the ego-network intact).
        self._mastery_filter_combo = QComboBox()
        for band, label_key in (
            ("all", "filter_all"),
            ("unstudied", "filter_unstudied"),
            ("weak", "filter_weak"),
            ("mastered", "filter_mastered"),
        ):
            self._mastery_filter_combo.addItem(self._main._t(label_key), band)
        self._mastery_filter_combo.setToolTip(
            self._main._t("map_mastery_filter_tip")
        )
        self._mastery_filter_combo.setStyleSheet(
            f"QComboBox {{ border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; padding: 4px 8px;"
            f" font-size: 13px; background-color: {theme.SURFACE}; }}"
        )
        self._mastery_filter_combo.currentIndexChanged.connect(
            self._on_mastery_filter_change
        )
        toolbar.addWidget(self._mastery_filter_combo)

        # Learning-path playback: walk the curated path step by step, with the
        # map highlighting the full sequence and the detail card following.
        self._path_mode_btn = QPushButton(self._main._t("map_path_mode"))
        self._path_mode_btn.setCheckable(True)
        self._path_mode_btn.setToolTip(self._main._t("map_path_mode_tip"))
        self._path_mode_btn.setStyleSheet(_toggle_style())
        self._path_mode_btn.clicked.connect(self._on_toggle_path_mode)
        toolbar.addWidget(self._path_mode_btn)

        step_style = (
            f"QPushButton {{ background-color: {theme.SURFACE};"
            f" color: {theme.ACCENT}; border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px;"
            " padding: 5px 10px; font-size: 13px; font-weight: 600; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_TINT}; }}"
        )
        self._path_prev_btn = QPushButton("◀")
        self._path_prev_btn.setToolTip(self._main._t("map_path_prev_tip"))
        self._path_prev_btn.setStyleSheet(step_style)
        self._path_prev_btn.clicked.connect(lambda: self._on_path_step(-1))
        toolbar.addWidget(self._path_prev_btn)

        self._path_next_btn = QPushButton("▶")
        self._path_next_btn.setToolTip(self._main._t("map_path_next_tip"))
        self._path_next_btn.setStyleSheet(step_style)
        self._path_next_btn.clicked.connect(lambda: self._on_path_step(1))
        toolbar.addWidget(self._path_next_btn)

        self._path_pos_label = QLabel("")
        self._path_pos_label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_MUTED}; font-size: 12.5px;"
            " padding: 0 4px; }"
        )
        toolbar.addWidget(self._path_pos_label)
        for w in (self._path_prev_btn, self._path_next_btn, self._path_pos_label):
            w.setVisible(False)

        # Export PNG button
        export_btn = QPushButton(self._main._t("export_png"))
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setStyleSheet(theme.secondary_button_style())
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

        toolbar.addStretch()
        return row_widget

    def _on_toggle_more_tools(self) -> None:
        """Show/hide the secondary toolbar row (「更多工具」)."""
        row = getattr(self, "_more_row", None)
        if row is None:
            return
        on = not row.isVisible()
        row.setVisible(on)
        self._more_btn.setText(
            ("▾ " if on else "▸ ") + self._main._t("more_tools")
        )

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
        self._sync_legend()

    def _on_toggle_hop2(self):
        """Toggle 2-hop breadth exploration mode."""
        if not self._graph_view:
            return
        active = self._graph_view.toggle_hop2_mode()
        self._hop2_btn.setChecked(active)
        self._sync_legend()

    def _sync_legend(self):
        """Keep the legend truthful: it must describe the *current* node
        fill semantics, which heatmap/hop2 modes repaint."""
        if self._legend is None or not self._graph_view:
            return
        self._legend.set_mode(
            mastery_heat=getattr(self._graph_view, "_mastery_heat_mode", False),
            density=getattr(self._graph_view, "_density_mode", False),
            hop2=getattr(self._graph_view, "_hop2_mode", False),
        )

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
        # The graph widget survives view rebuilds — reflect its playback state
        # in the freshly-created toolbar controls.
        if hasattr(self, "_path_mode_btn") and self._path_mode_btn:
            avail = self._graph_view.path_playback_available()
            self._path_mode_btn.setEnabled(avail)
            on = bool(getattr(self._graph_view, "_path_playback", False)) and avail
            self._path_mode_btn.setChecked(on)
            for w in (self._path_prev_btn, self._path_next_btn, self._path_pos_label):
                w.setVisible(on)
            if not on:
                self._path_pos_label.setText("")
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
            # definitions / evidence / source anchors (P1-2). Uses the persistent
            # index so repeated searches over a large corpus stay fast.
            hits = indexed_search(self._main.assets, kw, limit=40)
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
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(theme.primary_button_style(compact=True))
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
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(theme.primary_button_style(compact=True))
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

    def _on_mastery_filter_change(self, _idx: int) -> None:
        """Isolate the full network to one mastery band."""
        if not self._graph_view:
            return
        band = self._mastery_filter_combo.currentData() or "all"
        self._graph_view.set_mastery_filter(str(band))

    def _on_toggle_path_mode(self) -> None:
        """Toggle learning-path playback on the graph."""
        if not self._graph_view:
            return
        enabled = self._graph_view.set_path_playback(self._path_mode_btn.isChecked())
        self._path_mode_btn.setChecked(enabled)
        for w in (self._path_prev_btn, self._path_next_btn, self._path_pos_label):
            w.setVisible(enabled)
        if enabled:
            # Land on the first path node immediately so the mode switch has
            # a visible effect (cursor ring + detail card follow).
            self._on_path_step(1)
        else:
            self._path_pos_label.setText("")

    def _on_path_step(self, delta: int) -> None:
        """Advance the playback cursor; the detail card walks along."""
        if not self._graph_view:
            return
        result = self._graph_view.path_step(delta)
        if not result:
            self._path_pos_label.setText("")
            return
        cid, pos_i, total = result
        asset = self._global_asset
        c = asset.concept_by_id(cid) if asset else None
        self._path_pos_label.setText(
            self._main._t("map_path_pos", i=pos_i, n=total, name=c.name if c else cid)
        )
        self._refresh_detail(cid)

    def _sync_mastery_filter_combo(self) -> None:
        """Reflect the persistent graph view's band in a freshly-built combo."""
        combo = getattr(self, "_mastery_filter_combo", None)
        if combo is None or self._graph_view is None:
            return
        band = getattr(self._graph_view, "_mastery_filter", "all")
        idx = combo.findData(band)
        if idx >= 0:
            combo.setCurrentIndex(idx)

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
        self._sync_legend()

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
        # Single click = look (focus + detail).  Entering a concept's subgraph
        # is the double-click gesture — mixing the two on one button is what
        # made the old map feel like it had no real drill-down.
        if self._graph_view._focus_id != concept_id:
            self._graph_view.focus_concept(concept_id)
        self._update_drill_controls()
        # If chain mode is active, update chain highlight for newly focused concept
        if hasattr(self, "_chain_btn") and self._chain_btn.isChecked():
            self._graph_view.highlight_dependency_chain(concept_id)
        if str(concept_id).startswith("ext:"):
            self._explain_external(concept_id)
            return
        self._refresh_detail(concept_id)

    def _on_node_drilled(self, concept_id: str) -> None:
        """Double-click drill: the graph already re-rendered the subgraph;
        refresh the breadcrumb trail and the inspector to match."""
        self._update_drill_controls()
        if str(concept_id).startswith("ext:"):
            return
        self._refresh_detail(concept_id)

    def _on_breadcrumb(self, level: int) -> None:
        """Breadcrumb jump: 0 = full map, k = the k-th drilled concept."""
        if not self._graph_view:
            return
        self._graph_view.drill_to(level)
        self._update_drill_controls()
        focus = self._graph_view._focus_id
        if focus:
            self._refresh_detail(focus)

    def _on_edge_click(self, src_id: str, tgt_id: str, rel_label: str):
        """Explain the line the learner just clicked (semantics + evidence)."""
        asset = self._global_asset or self._main.get_asset()
        if asset is None or self._map_detail is None:
            return
        if not asset.concept_by_id(src_id) or not asset.concept_by_id(tgt_id):
            # Global-map ids carry an asset prefix; a local-scope edge may use
            # bare ids instead, so fall back to the current asset.
            asset = self._main.get_asset()
            if asset is None:
                return
            if not asset.concept_by_id(src_id) or not asset.concept_by_id(tgt_id):
                return
        rtype = ""
        if self._graph_view is not None:
            rtype = self._graph_view._edge_type_map.get(
                (src_id, tgt_id, rel_label), ""
            )
        self._map_detail.set_relation(asset, src_id, tgt_id, rel_label, rtype)

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
        """Rebuild the breadcrumb bar from the graph's current drill trail.

        Every crumb is a button — a trail you cannot click back up is just a
        label, and the old static label is exactly what made drilling feel
        one-way.  Also updates the explicit drill-in button and the always-
        visible affordance capsule that tells the newcomer drilling exists.
        """
        host = getattr(self, "_breadcrumb_host", None)
        if host is None or not self._graph_view:
            return
        lay = host.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        path = self._graph_view.drill_path()
        asset = self._global_asset
        in_drill = bool(path)

        # — 面包屑 —
        def _seg(text: str, level: int, current: bool) -> QPushButton:
            b = QPushButton(text)
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            weight = "bold" if current else "normal"
            color = theme.ACCENT_HOVER if current else theme.ACCENT
            b.setStyleSheet(
                f"QPushButton {{ color: {color}; font-size: 13.5px;"
                f"font-weight: {weight}; border: none; padding: 3px 5px;"
                f"border-radius: 4px; background: transparent; }}"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            b.clicked.connect(lambda _=False, lv=level: self._on_breadcrumb(lv))
            return b

        lay.addWidget(_seg(self._main._t("drill_all"), 0, current=not path))
        for i, cid in enumerate(path):
            sep = QLabel("›")
            sep.setStyleSheet("color: #90A4AE; font-size: 13.5px;")
            lay.addWidget(sep)
            c = asset.concept_by_id(cid) if asset else None
            name = c.name if c else cid
            if len(name) > 12:
                name = name[:12] + "…"
            lay.addWidget(_seg(name, i + 1, current=i == len(path) - 1))
        lay.addStretch()

        # — 显式「展开子图」按钮 —
        # 下钻模式下不再显示（用户已经在子图里了，双击继续深入即可）；
        # 未选中节点时也不显示（没有对象可钻）；有焦点节点才出现
        drill_btn = getattr(self, "_drill_btn", None)
        if drill_btn is not None:
            focus_id = getattr(self._graph_view, "_focus_id", None)
            visible = (not in_drill) and bool(focus_id)
            drill_btn.setVisible(visible)

    def _on_explicit_drill(self) -> None:
        """工具栏「展开子图」按钮：显式入口，等效双击当前焦点节点。"""
        if not self._graph_view:
            return
        focus_id = getattr(self._graph_view, "_focus_id", None)
        if not focus_id:
            return
        self._graph_view.drill_down(focus_id)
        self._update_drill_controls()
        self._refresh_detail(focus_id)

    def _show_onboarding(self) -> None:
        """首次进入认知地图时，在工具栏下方显示一条可关闭的 3 步提示条。

        刻意不用模态遮罩：小白的核心诉求是「快速看懂」，遮挡式引导既打断
        视线又难关闭；一条不挡操作的提示条既补充 discoverability，也随时可收起。
        """
        bar = QWidget()
        bar.setObjectName("cm_onboarding_bar")
        bar.setStyleSheet(
            "QWidget#cm_onboarding_bar { background-color: #E3F2FD;"
            "border: 1px solid #90CAF9; border-radius: 8px; }"
        )
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(14, 10, 10, 10)
        bar_lay.setSpacing(18)
        for text in (
            self._main._t("cm_onboard_step1"),
            self._main._t("cm_onboard_step2"),
            self._main._t("cm_onboard_step3"),
        ):
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 13px; color: #0D47A1;")
            bar_lay.addWidget(lbl)
        bar_lay.addStretch()

        dismiss = QPushButton("✕")
        dismiss.setFixedSize(22, 22)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setToolTip(self._main._t("cm_onboard_dismiss"))
        dismiss.setStyleSheet(
            "QPushButton { background-color: transparent; color: #1565C0;"
            "border: none; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { color: #0D47A1; }"
        )
        dismiss.clicked.connect(bar.deleteLater)
        bar_lay.addWidget(dismiss)

        self._content_layout.insertWidget(1, bar)
