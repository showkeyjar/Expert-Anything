from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.i18n import t as _t
from expert_anything.ui.widgets._helpers import mastery_color, _sec_title


class NodeDetailCard(QFrame):
    """Right-hand detail card that follows the clicked node.

    Clicking a node in the living graph updates this card: definition,
    mastery, relation neighbours (clickable to roam), first evidence and
    teacher-note highlights. '开始教学' starts a lesson, '完整详情' opens
    the full ConceptDetailPanel.
    """

    teach_requested = Signal(str)  # concept name
    full_detail_requested = Signal(str)  # concept id
    neighbor_clicked = Signal(str)  # concept id (roam)
    compare_requested = Signal(str, str)  # concept_a_id, concept_b_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(270)
        self.setMaximumWidth(320)
        self.setStyleSheet(
            "NodeDetailCard { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 10px; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)
        self._empty()

    # -- state ---------------------------------------------------------------
    def _empty(self) -> None:
        self._clear()
        t = QLabel(_t("detail_click_hint"))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("color: #9E9E9E; font-size: 12.5px; padding: 30px 0;")
        self._layout.addWidget(t)
        self._layout.addStretch()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    @staticmethod
    def _clear_layout(lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                NodeDetailCard._clear_layout(item.layout())

    # -- content --------------------------------------------------------------
    def set_concept(
        self, asset, concept_id: str, learner_state: dict, teacher=None
    ) -> None:
        """Fill the card for one concept (asset is the global map asset)."""
        self._clear()
        concept = asset.concept_by_id(concept_id)
        if concept is None:
            self._empty()
            return

        # header: name + mastery
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(concept.name)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 15px; font-weight: bold; color: #0c3d5f;")
        head.addWidget(name, 1)
        key = next(
            (
                k
                for k, v in learner_state.get("concepts", {}).items()
                if v.get("name") == concept.name
            ),
            None,
        )
        rec = learner_state.get("concepts", {}).get(key or "", {})
        mastery = float(rec.get("mastery", 0.0))
        m_lbl = QLabel(f"{mastery:.0%}")
        m_lbl.setStyleSheet(
            f"background-color: {mastery_color(mastery)}; color: white;"
            "padding: 2px 10px; border-radius: 9px; font-size: 11px; font-weight: bold;"
        )
        head.addWidget(m_lbl, 0)
        self._layout.addLayout(head)

        # definition
        if concept.definition or concept.summary:
            d = QLabel((concept.definition or concept.summary)[:140])
            d.setWordWrap(True)
            d.setStyleSheet("font-size: 12.5px; color: #37474F;")
            self._layout.addWidget(d)

        # relations (roam)
        rels = []
        for r in asset.relations:
            if r.source == concept.id:
                other = asset.concept_by_id(r.target)
                if other:
                    rels.append((r.label or _t("edge_related"), other.name, other.id))
            elif r.target == concept.id:
                other = asset.concept_by_id(r.source)
                if other:
                    rels.append((r.label or _t("edge_related"), other.name, other.id))
        if rels:
            self._layout.addWidget(_sec_title(_t("detail_relations"), "#0284C7"))
            for label, other_name, other_id in rels[:6]:
                btn = QPushButton(f"{label} → {other_name}")
                btn.setStyleSheet(
                    "QPushButton { background-color: #E1F0FA; color: #0369A1;"
                    "border: 1px solid #BAE6FD; border-radius: 6px; padding: 4px 10px;"
                    "font-size: 11.5px; text-align: left; }"
                    "QPushButton:hover { background-color: #BAE6FD; }"
                )
                btn.clicked.connect(
                    lambda checked, cid=other_id: self.neighbor_clicked.emit(cid)
                )
                self._layout.addWidget(btn)

        # peers & next level — the reader's "position sense": clicking a node
        # must show what stands alongside it and where it leads, never a dead end
        self._append_peers(asset, concept_id, learner_state)
        self._append_next_level(asset, concept_id, learner_state)

        # first evidence
        if concept.evidence:
            self._layout.addWidget(_sec_title(_t("detail_evidence"), "#2E7D32"))
            ev = QLabel(
                concept.evidence[0][:160]
                + ("…" if len(concept.evidence[0]) > 160 else "")
            )
            ev.setWordWrap(True)
            ev.setStyleSheet(
                "font-size: 11.5px; color: #546E7A; background-color: #F0F8F0;"
                "border-radius: 6px; padding: 8px;"
            )
            self._layout.addWidget(ev)

        # teacher notes
        if teacher is not None:
            note = teacher.concept_note_by_id(concept_id)
            if note is not None:
                bits = []
                if note.significance:
                    bits.append(_t("detail_why", s=note.significance[:80]))
                if note.misconceptions:
                    bits.append(_t("detail_miscon", s=note.misconceptions[0][:60]))
                if bits:
                    self._layout.addWidget(_sec_title(_t("detail_teacher"), "#7C3AED"))
                    for b in bits:
                        lbl = QLabel(b)
                        lbl.setWordWrap(True)
                        lbl.setStyleSheet("font-size: 11.5px; color: #5E35B1;")
                        self._layout.addWidget(lbl)

        # actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        teach_btn = QPushButton(_t("panel_teach"))
        teach_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(lambda: self.teach_requested.emit(concept.name))
        btn_row.addWidget(teach_btn)
        full_btn = QPushButton(_t("detail_full"))
        full_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7;"
            "border: 1px solid #BAE6FD; border-radius: 6px; padding: 6px 12px;"
            "font-size: 12px; }"
            "QPushButton:hover { background-color: #E1F0FA; }"
        )
        full_btn.clicked.connect(lambda: self.full_detail_requested.emit(concept_id))
        btn_row.addWidget(full_btn)

        # compare — only meaningful when a peer / next-level candidate exists
        if self._compare_target(asset, concept_id):
            cmp_btn = QPushButton(_t("detail_compare"))
            cmp_btn.setStyleSheet(
                "QPushButton { background-color: white; color: #00695C;"
                "border: 1px solid #80CBC4; border-radius: 6px; padding: 6px 12px;"
                "font-size: 12px; }"
                "QPushButton:hover { background-color: #E0F2F1; }"
            )
            cmp_btn.clicked.connect(
                lambda: self.compare_requested.emit(
                    concept_id, self._compare_target(asset, concept_id)[0]
                )
            )
            btn_row.addWidget(cmp_btn)

        btn_row.addStretch()
        self._layout.addLayout(btn_row)
        self._layout.addStretch()

    # -- peers / next level ----------------------------------------------------
    @staticmethod
    def _compare_target(asset, concept_id: str) -> list[str]:
        try:
            from expert_anything.core.map_context import siblings, next_level

            cands = siblings(asset, concept_id, max_n=1) + next_level(
                asset, concept_id, max_n=1
            )
            return [c["id"] for c in cands][:1]
        except Exception:
            return []

    def _pill(self, text: str, cid: str, name: str, color: str) -> QWidget:
        """A roam pill + a small teach button: a peer / next-level point can be
        *studied* in one click, not just roamed to (cognitive-map → lesson)."""
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        roam = QPushButton(text)
        roam.setObjectName("pill_roam_btn")
        roam.setStyleSheet(
            f"QPushButton {{ background-color: {color}18; color: {color};"
            f"border: 1px solid {color}55; border-radius: 6px; padding: 4px 10px;"
            "font-size: 11.5px; text-align: left; }"
            f"QPushButton:hover {{ background-color: {color}33; }}"
        )
        roam.setToolTip(_t("detail_pill_roam"))
        roam.clicked.connect(lambda checked=False, c=cid: self.neighbor_clicked.emit(c))
        h.addWidget(roam, 1)
        teach = QPushButton("▶")
        teach.setObjectName("pill_teach_btn")
        teach.setFixedWidth(30)
        teach.setToolTip(_t("detail_pill_teach"))
        teach.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: white; border: none;"
            "border-radius: 6px; padding: 4px 0; font-size: 11px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: {color}BB; }}"
        )
        teach.clicked.connect(
            lambda checked=False, n=name: self.teach_requested.emit(n)
        )
        h.addWidget(teach, 0)
        return wrap

    def _append_peers(self, asset, concept_id: str, learner_state: dict) -> None:
        try:
            from expert_anything.core.map_context import siblings

            peers = siblings(asset, concept_id, max_n=5, learner_state=learner_state)
        except Exception:
            peers = []
        self._layout.addWidget(_sec_title(_t("detail_siblings"), "#6D4C41"))
        if not peers:
            empty = QLabel(_t("detail_peers_empty"))
            empty.setStyleSheet("font-size: 11px; color: #BDBDBD;")
            self._layout.addWidget(empty)
            return
        for p in peers:
            self._layout.addWidget(self._pill(p["name"], p["id"], p["name"], "#6D4C41"))

    def _append_next_level(self, asset, concept_id: str, learner_state: dict) -> None:
        try:
            from expert_anything.core.map_context import next_level

            nxt = next_level(asset, concept_id, max_n=6, learner_state=learner_state)
        except Exception:
            nxt = []
        self._layout.addWidget(_sec_title(_t("detail_next_level"), "#00695C"))
        if not nxt:
            empty = QLabel(_t("detail_next_empty"))
            empty.setStyleSheet("font-size: 11px; color: #BDBDBD;")
            self._layout.addWidget(empty)
            return
        for n in nxt:
            arrow = "→" if n["dir"] == "out" else ("←" if n["dir"] == "in" else "→")
            label = (
                f"{arrow} {n['label']}　{n['name']}"
                if n["label"]
                else f"{arrow} {n['name']}"
            )
            self._layout.addWidget(self._pill(label, n["id"], n["name"], "#00695C"))
