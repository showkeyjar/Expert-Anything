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
    source_requested = Signal(str)  # concept id -> reader at grounded evidence
    evidence_jump_requested = Signal(str, str)  # concept id, evidence text
    neighbor_clicked = Signal(str)  # concept id (roam)
    compare_requested = Signal(str, str)  # concept_a_id, concept_b_id
    quick_quiz_requested = Signal(str)  # concept id (quick self-test)

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
        t.setStyleSheet("color: #9E9E9E; font-size: 14.5px; padding: 30px 0;")
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
        name.setStyleSheet("font-size: 17px; font-weight: bold; color: #0c3d5f;")
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
            "padding: 2px 10px; border-radius: 9px; font-size: 13px; font-weight: bold;"
        )
        head.addWidget(m_lbl, 0)
        self._layout.addLayout(head)

        # definition
        if concept.definition or concept.summary:
            d = QLabel((concept.definition or concept.summary)[:140])
            d.setWordWrap(True)
            d.setStyleSheet("font-size: 14.5px; color: #37474F;")
            self._layout.addWidget(d)

        # mini scene preview — a quick visual deconstruction of the concept
        # and its nearest neighbours. Gives the learner an immediate visual
        # anchor before they read the text details.
        try:
            from expert_anything.core import decoder

            # Unified entry point (domain scene when available, generic
            # fallback otherwise) so the detail panel matches the lesson view.
            scene = decoder.scene_for_concept(asset, concept)
            if scene and scene.get("nodes"):
                svg_data = decoder.render_svg(scene)
                if svg_data:
                    try:
                        from PySide6.QtSvgWidgets import QSvgWidget
                        from PySide6.QtCore import QByteArray

                        svg_widget = QSvgWidget()
                        svg_widget.load(QByteArray(svg_data.encode("utf-8")))
                        svg_widget.setMinimumHeight(130)
                        svg_widget.setMaximumHeight(160)
                        svg_widget.setStyleSheet(
                            "background-color: #FAFAFA; border: 1px solid #E8E8E8;"
                            "border-radius: 8px;"
                        )
                        self._layout.addWidget(svg_widget)
                    except Exception:
                        pass  # QtSvg not available — silently skip the preview
        except Exception:
            pass  # scene generation failed — silently skip

        # relations (roam) — colored by semantic type so the learner reads
        # structural meaning (causes / part-of / prerequisite / contrast / …)
        # at a glance instead of seeing a uniform "everything is connected" list.
        rels = []
        for r in asset.relations:
            if r.source == concept.id:
                other = asset.concept_by_id(r.target)
                if other:
                    rels.append(
                        (
                            r.label or _t("edge_related"),
                            other.name,
                            other.id,
                            getattr(r, "type", ""),
                        )
                    )
            elif r.target == concept.id:
                other = asset.concept_by_id(r.source)
                if other:
                    rels.append(
                        (
                            r.label or _t("edge_related"),
                            other.name,
                            other.id,
                            getattr(r, "type", ""),
                        )
                    )
        if rels:
            from expert_anything.core.decoder import classify_relation, REL_SEMANTICS

            self._layout.addWidget(_sec_title(_t("detail_relations"), "#0284C7"))
            for label, other_name, other_id, rtype in rels[:6]:
                sem = classify_relation(label, rtype)
                sem_info = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])
                color = sem_info["color"]
                sem_label = _t("rel_" + sem)
                btn = QPushButton(f"{sem_label} · {label} → {other_name}")
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {color}18; color: {color};"
                    f"border: 1px solid {color}55; border-radius: 6px; padding: 4px 10px;"
                    "font-size: 13.5px; text-align: left; }"
                    f"QPushButton:hover {{ background-color: {color}33; }}"
                )
                btn.clicked.connect(
                    lambda checked, cid=other_id: self.neighbor_clicked.emit(cid)
                )
                self._layout.addWidget(btn)

        # peers & next level — the reader's "position sense": clicking a node
        # must show what stands alongside it and where it leads, never a dead end
        self._append_peers(asset, concept_id, learner_state)
        self._append_next_level(asset, concept_id, learner_state)

        # difficulty badge — auto-labelled from evaluation history
        self._append_difficulty(asset, concept_id, learner_state)

        # path position — show where this concept sits in the learning path
        self._append_path_position(asset, concept_id)

        # action path — practice-oriented sequence after this concept
        self._append_action_path(asset, concept_id, learner_state)

        # evidence — every entry carries a page/line badge when the concept
        # has a stamped SourceLocation; clicking the badge jumps the reader
        # to that exact passage (same provenance chain as the lesson view).
        if concept.evidence:
            self._layout.addWidget(_sec_title(_t("detail_evidence"), "#2E7D32"))
            for e in concept.evidence[:3]:
                row = QHBoxLayout()
                row.setSpacing(6)
                e_lbl = QLabel(e[:160] + ("…" if len(e) > 160 else ""))
                e_lbl.setWordWrap(True)
                e_lbl.setStyleSheet(
                    "font-size: 13.5px; color: #546E7A; background-color:"
                    " #F0F8F0; border-radius: 6px; padding: 8px;"
                )
                row.addWidget(e_lbl, 1)
                loc = concept.location_for_evidence(e)
                if loc is not None and (loc.page or loc.line):
                    if loc.page:
                        badge_txt = _t("loc_page_and_line").format(
                            page=loc.page, line=loc.line
                        )
                    else:
                        badge_txt = _t("loc_line_only").format(line=loc.line)
                    badge = QPushButton(badge_txt)
                    badge.setCursor(Qt.CursorShape.PointingHandCursor)
                    badge.setToolTip(_t("evidence_jump_tip"))
                    badge.setStyleSheet(
                        "QPushButton { background-color: #DCEDC8; color: #33691E;"
                        "border: 1px solid #AED581; border-radius: 9px;"
                        "padding: 1px 8px; font-size: 11.5px; }"
                        "QPushButton:hover { background-color: #AED581; }"
                    )
                    badge.clicked.connect(
                        lambda checked, ev=e, cid=concept.id: (
                            self.evidence_jump_requested.emit(cid, ev)
                        )
                    )
                    row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
                self._layout.addLayout(row)

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
                        lbl.setStyleSheet("font-size: 13.5px; color: #5E35B1;")
                        self._layout.addWidget(lbl)

        # actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        teach_btn = QPushButton(_t("panel_teach"))
        teach_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 12px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        teach_btn.clicked.connect(lambda: self.teach_requested.emit(concept.name))
        btn_row.addWidget(teach_btn)

        # Quick self-test: 30-second check without leaving the map
        quiz_btn = QPushButton(_t("detail_quick_quiz"))
        quiz_btn.setStyleSheet(
            "QPushButton { background-color: #FFF8E1; color: #E65100;"
            "border: 1px solid #FFCC80; border-radius: 6px; padding: 6px 10px;"
            "font-size: 13.5px; font-weight: 600; }"
            "QPushButton:hover { background-color: #FFECB3; }"
        )
        quiz_btn.setToolTip(_t("detail_quick_quiz_tip"))
        quiz_btn.clicked.connect(lambda: self.quick_quiz_requested.emit(concept_id))
        btn_row.addWidget(quiz_btn)

        full_btn = QPushButton(_t("detail_full"))
        full_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #0284C7;"
            "border: 1px solid #BAE6FD; border-radius: 6px; padding: 6px 12px;"
            "font-size: 14px; }"
            "QPushButton:hover { background-color: #E1F0FA; }"
        )
        full_btn.clicked.connect(lambda: self.full_detail_requested.emit(concept_id))
        btn_row.addWidget(full_btn)

        source_btn = QPushButton(_t("btn_source"))
        source_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #2E7D32;"
            "border: 1px solid #A5D6A7; border-radius: 6px; padding: 6px 10px;"
            "font-size: 14px; }"
            "QPushButton:hover { background-color: #E8F5E9; }"
        )
        source_btn.setToolTip(_t("read_source"))
        source_btn.clicked.connect(lambda: self.source_requested.emit(concept_id))
        btn_row.addWidget(source_btn)

        # compare — only meaningful when a peer / next-level candidate exists
        if self._compare_target(asset, concept_id):
            cmp_btn = QPushButton(_t("detail_compare"))
            cmp_btn.setStyleSheet(
                "QPushButton { background-color: white; color: #00695C;"
                "border: 1px solid #80CBC4; border-radius: 6px; padding: 6px 12px;"
                "font-size: 14px; }"
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
            "font-size: 13.5px; text-align: left; }"
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
            "border-radius: 6px; padding: 4px 0; font-size: 13px; font-weight: bold; }"
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
            empty.setStyleSheet("font-size: 13px; color: #BDBDBD;")
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
            empty.setStyleSheet("font-size: 13px; color: #BDBDBD;")
            self._layout.addWidget(empty)
            return
        for n in nxt:
            arrow = "→" if n["dir"] == "out" else ("←" if n["dir"] == "in" else "→")
            sem_label = n.get("sem_label", "")
            sem_color = n.get("sem_color", "#00695C")
            if n["label"] and sem_label:
                label = f"{arrow} [{sem_label}] {n['label']}　{n['name']}"
            elif n["label"]:
                label = f"{arrow} {n['label']}　{n['name']}"
            else:
                label = f"{arrow} {n['name']}"
            self._layout.addWidget(self._pill(label, n["id"], n["name"], sem_color))

    def _append_difficulty(self, asset, concept_id: str, learner_state: dict) -> None:
        """Show an auto-computed difficulty badge and mastery prediction."""
        from expert_anything.core.learner import concept_difficulty, mastery_prediction

        diff_map = concept_difficulty(
            learner_state, asset_id=asset.asset_id if asset else None
        )
        c = asset.concept_by_id(concept_id) if asset else None
        if not c:
            return
        diff = diff_map.get(c.name, "unknown")
        diff_styles = {
            "easy": ("#E8F5E9", "#2E7D32", _t("diff_easy"), _t("diff_easy_tip")),
            "medium": ("#FFF8E1", "#E65100", _t("diff_medium"), _t("diff_medium_tip")),
            "hard": ("#FFEBEE", "#C62828", _t("diff_hard"), _t("diff_hard_tip")),
            "unknown": ("#F5F5F5", "#9E9E9E", "?", _t("diff_unknown_tip")),
        }
        bg, fg, label, tip = diff_styles.get(diff, diff_styles["unknown"])
        badge = QLabel(f" {_t('diff_label')}: {label} ")
        badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {fg};"
            "border-radius: 10px; padding: 2px 10px; font-size: 13px; font-weight: bold;"
        )
        badge.setToolTip(tip)
        self._layout.addWidget(badge)

        # Mastery prediction — linear trend forecast
        from expert_anything.core.learner import normalize as _norm

        pred = mastery_prediction(learner_state, c.name)
        self._layout.addWidget(_sec_title(_t("pred_title"), "#5E35B1"))

        current_mastery = float(
            learner_state.get("concepts", {}).get(_norm(c.name), {}).get("mastery", 0.0)
        )

        if pred["trend"] == "unknown" and current_mastery == 0:
            info = QLabel(_t("pred_no_data"))
            info.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            info.setWordWrap(True)
            self._layout.addWidget(info)
        elif current_mastery >= 0.6:
            info = QLabel(_t("pred_already_mastered"))
            info.setStyleSheet("font-size: 13.5px; color: #2E7D32; font-weight: 600;")
            self._layout.addWidget(info)
        else:
            trend_key = "trend_" + pred["trend"]
            trend_label = _t(trend_key)
            pred_pct = f"{pred['predicted_mastery']:.0%}"

            if pred["will_achieve"]:
                verdict = _t("pred_will_achieve")
                verdict_color = "#2E7D32"
                verdict_bg = "#E8F5E9"
            else:
                verdict = _t("pred_wont_achieve")
                verdict_color = "#C62828"
                verdict_bg = "#FFEBEE"

            verdict_lbl = QLabel(verdict)
            verdict_lbl.setStyleSheet(
                f"background-color: {verdict_bg}; color: {verdict_color};"
                "border-radius: 6px; padding: 4px 8px; font-size: 13px; font-weight: 600;"
            )
            verdict_lbl.setWordWrap(True)
            self._layout.addWidget(verdict_lbl)

            detail_parts = [f"{_t('pred_predicted')}: {pred_pct}", trend_label]
            if pred["sessions_needed"] > 0:
                detail_parts.append(
                    _t("pred_sessions_needed", n=pred["sessions_needed"])
                )
            detail = QLabel("  ·  ".join(detail_parts))
            detail.setStyleSheet("font-size: 13px; color: #616161;")
            detail.setWordWrap(True)
            self._layout.addWidget(detail)

    def _append_path_position(self, asset, concept_id: str) -> None:
        """Show where this concept sits in the learning path.

        Displays a compact "step N of M" badge with the previous and next
        concepts in the curated path, so the learner always knows their
        position in the overall knowledge sequence.
        """
        path = getattr(asset, "learning_path", None) or []
        if concept_id not in path:
            return
        idx = path.index(concept_id)
        total = len(path)
        self._layout.addWidget(_sec_title(_t("detail_path_pos"), "#1565C0"))

        # Position badge
        pos_widget = QWidget()
        pos_lay = QHBoxLayout(pos_widget)
        pos_lay.setContentsMargins(0, 0, 0, 0)
        pos_lay.setSpacing(6)

        badge = QLabel(f"{idx + 1} / {total}")
        badge.setStyleSheet(
            "background-color: #1565C0; color: white;"
            "border-radius: 10px; padding: 3px 12px; font-size: 14px; font-weight: bold;"
        )
        pos_lay.addWidget(badge)
        pos_lay.addStretch()
        self._layout.addWidget(pos_widget)

        # Previous concept in path
        if idx > 0:
            prev = asset.concept_by_id(path[idx - 1])
            if prev:
                prev_btn = QPushButton(f"← {prev.name}")
                prev_btn.setStyleSheet(
                    "QPushButton { background-color: #E3F2FD; color: #1565C0;"
                    "border: 1px solid #90CAF9; border-radius: 6px; padding: 4px 10px;"
                    "font-size: 13px; text-align: left; }"
                    "QPushButton:hover { background-color: #BBDEFB; }"
                )
                prev_btn.clicked.connect(
                    lambda checked, c=path[idx - 1]: self.neighbor_clicked.emit(c)
                )
                self._layout.addWidget(prev_btn)

        # Next concept in path
        if idx + 1 < total:
            nxt = asset.concept_by_id(path[idx + 1])
            if nxt:
                nxt_btn = QPushButton(f"{nxt.name} →")
                nxt_btn.setStyleSheet(
                    "QPushButton { background-color: #E8F5E9; color: #2E7D32;"
                    "border: 1px solid #A5D6A7; border-radius: 6px; padding: 4px 10px;"
                    "font-size: 13px; text-align: right; }"
                    "QPushButton:hover { background-color: #C8E6C9; }"
                )
                nxt_btn.clicked.connect(
                    lambda checked, c=path[idx + 1]: self.neighbor_clicked.emit(c)
                )
                self._layout.addWidget(nxt_btn)

    def _append_action_path(self, asset, concept_id: str, learner_state: dict) -> None:
        """Practice-oriented "how to use it" sequence after this concept.

        The learning path answers "what to learn next"; this section answers
        "in what order to *apply* it". When weak successors (mastery < 0.6)
        exist the focus variant is shown (⚠ + mastery %) so the learner
        drills the shaky spots first; otherwise the plain successor run is
        listed. Path-end concepts render nothing — no fake action path.
        """
        path = getattr(asset, "learning_path", None) or []
        if concept_id not in path:
            return
        idx = path.index(concept_id)
        successors = []
        for cid in path[idx + 1 : idx + 6]:
            c = asset.concept_by_id(cid)
            if c:
                successors.append(c)
        if not successors:
            return

        from expert_anything.core.learner import normalize as _norm

        def _mastery(c) -> float:
            rec = (
                learner_state.get("concepts", {}).get(_norm(c.name), {})
            )
            try:
                return float(rec.get("mastery", 0.0))
            except (TypeError, ValueError):
                return 0.0

        weak = [c for c in successors if _mastery(c) < 0.6]
        if weak:
            self._layout.addWidget(_sec_title(_t("action_path_focus"), "#E65100"))
            for c in weak:
                self._layout.addWidget(
                    self._pill(f"⚠ {c.name} {_mastery(c):.0%}", c.id, c.name, "#E65100")
                )
        else:
            self._layout.addWidget(_sec_title(_t("action_path"), "#00897B"))
            for i, c in enumerate(successors, 1):
                self._layout.addWidget(self._pill(f"{i}. {c.name}", c.id, c.name, "#00897B"))
