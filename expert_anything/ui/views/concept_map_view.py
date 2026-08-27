"""Concept map view: interactive force-directed knowledge graph."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)
from expert_anything.core.learner import normalize
from expert_anything.core.teacher import anomaly_concept_ids, TeacherModel


class ConceptMapView(QWidget):
    """View 3 — Interactive concept network graph."""

    # Signals to MainWindow
    teach_requested = Signal(str)   # concept_name
    open_concept_panel = Signal(str)  # concept_id
    focus_graph = Signal(str)         # concept_id
    navigate_source = Signal(str)     # concept_id -> scroll to evidence

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
        self._build()

    def refresh(self):
        self._refresh_map()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._view_header(
            self._main._t("nav_map"),
            self._main._t("map_subtitle"),
        ))

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        if self._main.current_asset_id and self._main.current_asset_id in self._main.assets:
            content_layout.addWidget(self._build_toolbar())
            splitter = QSplitter()
            self._graph_view = self._main._graph_view_ref()
            self._graph_view.concept_clicked.connect(self._on_graph_click)
            self._graph_view.node_single_clicked.connect(self._on_node_clicked)
            self._map_detail = self._main._map_detail_ref()
            self._map_detail.teach_requested.connect(
                lambda n: self.teach_requested.emit(n)
            )
            self._map_detail.full_detail_requested.connect(
                lambda cid: self.open_concept_panel.emit(cid)
            )
            self._map_detail.compare_requested.connect(
                lambda a, b: self._main._open_compare(a, b)
            )
            splitter.addWidget(self._graph_view)
            splitter.addWidget(self._map_detail)
            splitter.setStretchFactor(0, 1)
            splitter.setStretchFactor(1, 0)
            content_layout.addWidget(splitter, 1)

            self._legend = self._build_legend()
            content_layout.addWidget(self._legend)

            self._refresh_map()
        else:
            placeholder = QLabel(self._main._t("no_asset_placeholder"))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #757575; font-size: 14px; margin: 40px;")
            content_layout.addWidget(placeholder)

        layout.addWidget(content)

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

    def _build_toolbar(self):
        toolbar_widget = QWidget()
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(self._main._t("search_placeholder"))
        self._search_box.setStyleSheet(
            "QLineEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 5px 10px; font-size: 12.5px; background-color: white; }"
        )
        self._search_box.returnPressed.connect(self._on_search)
        toolbar.addWidget(self._search_box, 1)

        for label, tooltip, callback in [
            ("−", self._main._t("zoom_out_tip"),
             lambda: self._graph_view.zoom_out() if self._graph_view else None),
            (self._main._t("zoom_fit"), self._main._t("zoom_fit"),
             lambda: self._graph_view.fit_content() if self._graph_view else None),
            ("＋", self._main._t("zoom_in_tip"),
             lambda: self._graph_view.zoom_in() if self._graph_view else None),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px;"
                "padding: 5px 10px; font-size: 12.5px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)

        for label, tooltip, callback in [
            (self._main._t("reset_map"), self._main._t("reset_map"),
             lambda: self._graph_view.reset_focus() if self._graph_view else None),
            (self._main._t("map_back"), self._main._t("map_back_tip"),
             lambda: self._graph_view.drill_up() if self._graph_view else None),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px;"
                "padding: 5px 12px; font-size: 12.5px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)

        self._drill_path_label = QLabel(self._main._t("drill_hint"))
        self._drill_path_label.setStyleSheet(
            "QLabel { color: #546E7A; font-size: 12px; padding: 4px 8px; }"
        )
        toolbar.addWidget(self._drill_path_label, 1)

        self._scope_combo = QComboBox()
        self._scope_combo.addItems([
            self._main._t("scope_all"),
            self._main._t("scope_current"),
        ])
        self._scope_combo.setStyleSheet(
            "QComboBox { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 4px 8px; font-size: 12.5px; background-color: white; }"
        )
        self._scope_combo.currentIndexChanged.connect(self._on_scope_change)
        toolbar.addWidget(self._scope_combo)

        return toolbar_widget

    def _build_legend(self):
        from expert_anything.ui.widgets.map_widgets import MapLegend
        legend = MapLegend()
        return legend

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
                self._main.learner.get('concepts', {})
                .get(norm_name, {})
                .get('mastery', 0.0)
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
        current_id = items[0].get('cid') if items else None

        self._graph_view.set_asset(
            asset, mastery_map=mastery_map,
            anomaly_ids=anomaly_ids, current_id=current_id,
            grey_ids=grey_ids,
        )
        self._update_drill_controls()

    def _on_search(self):
        kw = self._search_box.text().strip().lower()
        if not kw or not self._graph_view:
            return
        for cid, name, _role in self._graph_view._nodes:
            if kw in name.lower():
                self._graph_view.focus_concept(cid)
                return
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, self._main._t("not_found_in_map").split("「")[0],
            self._main._t("not_found_in_map", kw=self._search_box.text().strip()),
        )

    def _on_scope_change(self, _idx):
        self._refresh_map()

    def _on_graph_click(self, concept_name):
        self.teach_requested.emit(concept_name)

    def _on_node_clicked(self, concept_id: str):
        if not self._graph_view:
            return
        was_focused = self._graph_view._focus_id == concept_id
        if was_focused:
            self._graph_view.drill_down(concept_id)
        else:
            self._graph_view.focus_concept(concept_id)
        self._update_drill_controls()
        if str(concept_id).startswith("ext:"):
            self._explain_external(concept_id)
            return
        self._refresh_detail(concept_id)

    def _explain_external(self, concept_id: str):
        asset = self._global_asset
        if asset is None:
            return
        c = asset.concept_by_id(concept_id)
        if c is None:
            return
        if self._main.llm_client is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, self._main._t("hint"),
                                    self._main._t("external_no_llm", name=c.name))
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
                [Message("user", prompt)], temperature=0.3, max_tokens=400,
            )
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, f"{self._main._t('external_title')}「{c.name}」", ans,
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
            self._global_asset, concept_id, self._main.learner, teacher,
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
