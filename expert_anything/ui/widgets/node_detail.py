from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.i18n import t as _t
from expert_anything.core.learner import (
    get_lesson_snapshot,
    get_note,
    normalize,
    save as save_learner,
    score_trail,
    set_note,
)
from expert_anything.ui import theme
from expert_anything.ui.widgets._helpers import (
    CollapsibleSection,
    mastery_color,
    open_feynman_check,
    tag_chip,
    _sec_title,
)

# Channel labels for the mastery breakdown.  Keys appear here as literals so
# the i18n integrity guard sees them as real references (no dynamic family).
_CHANNEL_KEYS = {
    "answer": "breakdown_answer",
    "quiz": "breakdown_quiz",
    "practice": "breakdown_practice",
    "flashcard": "breakdown_flashcard",
    "recall": "breakdown_recall",
    "harness": "breakdown_harness",
}


# Plain-language reading of each semantic relation, used by the edge card.
# Keys stay literal so the i18n integrity guard sees real references.
_REL_GLOSS_KEYS = {
    "prereq": "rel_gloss_prereq",
    "causes": "rel_gloss_causes",
    "part_of": "rel_gloss_part_of",
    "is_a": "rel_gloss_is_a",
    "contrast": "rel_gloss_contrast",
    "related": "rel_gloss_related",
}


def _channel_label(channel: str) -> str:
    key = _CHANNEL_KEYS.get(channel)
    return _t(key) if key else channel


def _quiz_choice_label(value: str) -> str:
    """Render a stored true/false answer code in the active UI language.

    Quiz traces keep language-neutral codes ("true"/"false", option numbers)
    so a language switch never rewrites history; the display maps them to the
    same labels the quiz buttons used.
    """
    v = str(value or "").strip().lower()
    if v == "true":
        return _t("quiz_true")
    if v == "false":
        return _t("quiz_false")
    return str(value or "").strip()


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
        self._relation: dict | None = None
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
                # deleteLater is deferred until the event loop turns; hiding
                # first prevents the old content flashing over the new card.
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    @staticmethod
    def _clear_layout(lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                NodeDetailCard._clear_layout(item.layout())

    # -- content --------------------------------------------------------------
    def set_concept(
        self, asset, concept_id: str, learner_state: dict, teacher=None
    ) -> None:
        """Fill the card for one concept (asset is the global map asset)."""
        self._clear()
        self._relation = None
        self._learner_state = learner_state  # kept for the favorite toggle
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

        # Bookmark star — the learner marks ideas worth returning to; the
        # Knowledge view can then filter the TOC down to starred concepts.
        from expert_anything.core.learner import is_favorite

        fav = is_favorite(learner_state, concept.name)
        star_btn = QPushButton("★" if fav else "☆")
        star_btn.setObjectName("fav_star_btn")
        star_btn.setToolTip(_t("fav_toggle_tip"))
        star_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #F59E0B;"
            "border: 1px solid #FCD34D; border-radius: 9px;"
            "padding: 1px 7px; font-size: 15px; }"
            "QPushButton:hover { background-color: #FFFBEB; }"
        )
        star_btn.clicked.connect(
            lambda checked=False, n=concept.name, s=star_btn: self._on_toggle_favorite(n, s)
        )
        head.addWidget(star_btn, 0)
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
            from expert_anything.ui.widgets._helpers import _HAS_SVG, SvgScenePreview

            # Unified entry point (domain scene when available, generic
            # fallback otherwise) so the detail panel matches the lesson view.
            scene = decoder.scene_for_concept(asset, concept)
            if _HAS_SVG and scene and scene.get("nodes"):
                svg_data = decoder.render_svg(scene)
                if svg_data:
                    try:
                        svg_widget = SvgScenePreview()
                        svg_widget.load_svg(svg_data, zoom_title=concept.name)
                        svg_widget.setMinimumHeight(150)
                        svg_widget.setStyleSheet(
                            "background-color: #FAFAFA; border: 1px solid #E8E8E8;"
                            "border-radius: 8px;"
                        )
                        self._layout.addWidget(svg_widget)
                    except Exception:
                        pass  # QtSvg not available — silently skip the preview
        except Exception:
            pass  # scene generation failed — silently skip

        # ===== 折叠区 1：关系与认知位置 =====
        sec_structure = CollapsibleSection(_t("detail_fold_structure"))
        saved = self._layout
        self._layout = sec_structure.body_layout()

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

        # path position — show where this concept sits in the learning path
        self._append_path_position(asset, concept_id)

        # prerequisite context — show the full prereq chain so the learner
        # knows what to review before diving in
        self._append_prereq_context(asset, concept_id, learner_state)

        # unlocks — the mirror image of the prereq chain: what becomes
        # learnable once this concept is solid ("why must I learn this?")
        self._append_unlocks(asset, concept_id, learner_state)

        # action path — practice-oriented sequence after this concept
        self._append_action_path(asset, concept_id, learner_state)

        self._layout = saved
        self._layout.addWidget(sec_structure)

        # ===== 折叠区 2：学习进展 =====
        sec_progress = CollapsibleSection(_t("detail_fold_progress"))
        saved = self._layout
        self._layout = sec_progress.body_layout()

        # difficulty badge — auto-labelled from evaluation history
        self._append_difficulty(asset, concept_id, learner_state)

        # score trail — recent evaluation scores for THIS concept (am I
        # actually improving here, or stuck at the same level?)
        self._append_score_trail(concept, learner_state)

        # latest self-test miss — what was asked, what I answered, what was
        # actually right (a bare 20% tells the learner nothing to fix)
        self._append_quiz_miss(concept, learner_state)

        # mastery breakdown — where did this mastery % come from?
        # (per-channel counts / averages, deterministic projection)
        self._append_mastery_breakdown(concept, learner_state)

        # recall status — latest Feynman self-explanation coverage, with the
        # deterministic gap ("you left out N points") and a one-click retry
        self._append_recall_status(asset, concept, learner_state)

        self._layout = saved
        self._layout.addWidget(sec_progress)

        # ===== 折叠区 3：参考资料 =====
        sec_ref = CollapsibleSection(_t("detail_fold_reference"))
        saved = self._layout
        self._layout = sec_ref.body_layout()

        # domain terminology — the official registered term for this concept
        # (canonical name / aliases / definition / key points) plus related
        # terms, so clicking a node also surfaces its domain vocabulary.
        self._append_terminology(asset, concept)

        # personal note — own-words understanding (generation effect) and
        # lesson replay — re-read the last explanation at zero LLM cost
        self._append_note(concept, learner_state)
        self._append_lesson_replay(concept, learner_state)

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

        # teacher notes — the system's own understanding of this concept, and
        # (crucially) what it has LEARNED FROM THE LEARNER: low-score answer
        # snippets, follow-up questions, comparison findings.  Learner signals
        # were being written by teacher.py but never shown anywhere in the
        # desktop UI, so the "system remembers your confusion" loop was invisible.
        if teacher is not None:
            note = teacher.concept_note_by_id(concept_id)
            if note is not None and (
                note.significance
                or note.misconceptions
                or note.note
                or note.learner_signals
                or note.external_notes
            ):
                self._layout.addWidget(_sec_title(_t("detail_teacher"), "#7C3AED"))
                if note.significance:
                    self._teacher_line(_t("detail_why", s=note.significance[:80]))
                if note.misconceptions:
                    self._teacher_line(_t("detail_miscon", s=note.misconceptions[0][:60]))
                if note.note:
                    self._teacher_line(_t("detail_system_note", s=note.note[:120]))
                signals = [s for s in note.learner_signals if s]
                if signals:
                    self._layout.addWidget(
                        _sec_title(_t("learner_signals_title"), "#C2185B")
                    )
                    for sig in signals[-3:]:
                        self._teacher_line("• " + str(sig)[:90], "#AD1457")
                externals = [s for s in note.external_notes if s]
                if externals:
                    self._layout.addWidget(
                        _sec_title(
                            _t("external_notes_title"), "#455A64"
                        )
                    )
                    tag = QLabel(_t("external_source_tag"))
                    tag.setStyleSheet(
                        "background-color: #ECEFF1; color: #546E7A;"
                        "padding: 1px 6px; border-radius: 4px; font-size: 11px;"
                    )
                    self._layout.addWidget(tag)
                    for ext in externals[-2:]:
                        self._teacher_line(str(ext)[:90], "#546E7A")

        self._layout = saved
        self._layout.addWidget(sec_ref)

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

    def set_relation(
        self, asset, source_id: str, target_id: str,
        label: str = "", rtype: str = "",
    ) -> None:
        """Explain one graph edge: semantics, direction and source evidence.

        An edge click used to open a "start teaching?" box, which threw away the
        one thing the learner needs — why the line exists. This card states the
        relation type, reads it as a sentence, and shows the verbatim source
        span with its line (or says honestly that the edge is inferred).
        """
        self._clear()
        self._relation = None
        src = asset.concept_by_id(source_id)
        tgt = asset.concept_by_id(target_id)
        if src is None or tgt is None:
            self._empty()
            return

        from expert_anything.core.decoder import classify_relation, rel_semantic_color

        relation = None
        for r in asset.relations or []:
            if r.source != source_id or r.target != target_id:
                continue
            if (label or "") == (getattr(r, "label", "") or ""):
                relation = r
                break
            if relation is None:
                relation = r

        sem = classify_relation(
            label or (getattr(relation, "label", "") or ""),
            rtype or (getattr(relation, "type", "") or ""),
        )
        evidence = (getattr(relation, "evidence", "") or "").strip()
        self._relation = {
            "source": source_id,
            "target": target_id,
            "label": label or "",
            "type": sem,
            "evidence": evidence,
        }

        head = QLabel(f"{src.name} → {tgt.name}")
        head.setWordWrap(True)
        head.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: 600;"
        )
        self._layout.addWidget(head)

        chip = tag_chip(
            _t("rel_" + sem),
            rel_semantic_color(
                label or (getattr(relation, "label", "") or ""),
                rtype or (getattr(relation, "type", "") or ""),
            ),
        )
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.addWidget(chip)
        chip_row.addStretch()
        self._layout.addLayout(chip_row)

        gloss_key = _REL_GLOSS_KEYS.get(sem)
        if gloss_key:
            gloss = QLabel(_t(gloss_key, a=src.name, b=tgt.name))
            gloss.setWordWrap(True)
            gloss.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 12.5px;"
            )
            self._layout.addWidget(gloss)

        self._layout.addWidget(_sec_title(_t("rel_edge_title")))
        if evidence:
            source_text = getattr(asset, "source_text", "") or ""
            at = source_text.find(evidence)
            loc = getattr(relation, "location", None) if relation is not None else None
            # A persisted SourceLocation is the authoritative anchor (it carries
            # line/offset recorded at generation time); searching source_text is
            # only the fallback for assets written before relation anchors existed.
            anchored = loc is not None or at >= 0
            if not anchored:
                # Template/demo relations carry a note rather than a verbatim
                # span; label it as such instead of passing it off as the source.
                note = QLabel(_t("rel_edge_model_note"))
                note.setStyleSheet(
                    f"color: {theme.TEXT_FAINT}; font-size: 11.5px;"
                )
                self._layout.addWidget(note)
            quote = QLabel(f"「{evidence}」")
            quote.setWordWrap(True)
            quote.setStyleSheet(
                f"background-color: {theme.SURFACE_MUTED};"
                f" border: 1px solid {theme.DIVIDER};"
                f" border-radius: {theme.RADIUS_MD}px; padding: 8px;"
                f" color: {theme.TEXT}; font-size: 12.5px;"
            )
            self._layout.addWidget(quote)
            if anchored:
                if loc is not None and loc.line > 0:
                    line = loc.line
                else:
                    line = source_text.count("\n", 0, at) + 1
                place = QLabel(_t("rel_edge_line", line=line))
                place.setStyleSheet(
                    f"color: {theme.TEXT_FAINT}; font-size: 11.5px;"
                )
                self._layout.addWidget(place)
                jump = QPushButton(_t("rel_edge_jump"))
                jump.setStyleSheet(theme.secondary_button_style())
                jump.clicked.connect(
                    lambda: self.evidence_jump_requested.emit(source_id, evidence)
                )
                self._layout.addWidget(jump)
            else:
                why = QLabel(_t("rel_edge_no_evidence"))
                why.setWordWrap(True)
                why.setStyleSheet(
                    f"color: {theme.WARNING}; font-size: 12px;"
                )
                self._layout.addWidget(why)
        else:
            reason = _t("rel_edge_path_only") if relation is None else _t(
                "rel_edge_no_evidence"
            )
            why = QLabel(reason)
            why.setWordWrap(True)
            why.setStyleSheet(f"color: {theme.WARNING}; font-size: 12.5px;")
            self._layout.addWidget(why)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        teach_src = QPushButton(_t("rel_edge_teach", name=src.name))
        teach_src.setStyleSheet(theme.primary_button_style(compact=True))
        teach_src.clicked.connect(lambda: self.teach_requested.emit(src.name))
        actions.addWidget(teach_src, 1)
        teach_tgt = QPushButton(_t("rel_edge_teach", name=tgt.name))
        teach_tgt.setStyleSheet(theme.secondary_button_style())
        teach_tgt.clicked.connect(lambda: self.teach_requested.emit(tgt.name))
        actions.addWidget(teach_tgt, 1)
        self._layout.addLayout(actions)
        self._layout.addStretch()

    # -- favorites --------------------------------------------------------------
    def _on_toggle_favorite(self, concept_name: str, star_btn) -> None:
        """Flip the bookmark and persist immediately (same local-first pattern
        as reading positions); the star icon reflects the new state at once."""
        from expert_anything.core.learner import save as save_learner, toggle_favorite

        # The card needs the live learner state — grab it from the last
        # set_concept call via the sender's parent chain is fragile, so we
        # keep a reference instead.
        state = getattr(self, "_learner_state", None)
        if state is None:
            return
        fav = toggle_favorite(state, concept_name)
        save_learner(state)
        star_btn.setText("★" if fav else "☆")

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

        # Structural complexity — graph centrality based score
        from expert_anything.core.learner import structural_complexity

        sc_map = structural_complexity(asset) if asset else {}
        sc = sc_map.get(concept_id, 0.0)
        if sc >= 0.6:
            sc_bg, sc_fg, sc_label = "#E3F2FD", "#0D47A1", _t("struct_complex_high")
        elif sc >= 0.3:
            sc_bg, sc_fg, sc_label = "#F3E5F5", "#6A1B9A", _t("struct_complex_med")
        else:
            sc_bg, sc_fg, sc_label = "#F5F5F5", "#616161", _t("struct_complex_low")
        sc_badge = QLabel(f" {_t('struct_complexity')}: {sc_label} ({sc:.0%}) ")
        sc_badge.setStyleSheet(
            f"background-color: {sc_bg}; color: {sc_fg};"
            f"border: 1px solid {sc_fg}55; border-radius: 10px;"
            "padding: 2px 10px; font-size: 13px;"
        )
        sc_badge.setToolTip(_t("struct_complexity_tip"))
        self._layout.addWidget(sc_badge)

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

    def _append_prereq_context(self, asset, concept_id: str, learner_state: dict) -> None:
        """Show the prerequisite chain with mastery status.

        Lists each prerequisite concept (root → target) with a mastery
        indicator so the learner can spot shaky foundations before
        attempting the current concept. Weak prereqs get a warning badge
        and a one-click teach entry.
        """
        from expert_anything.core.learner import dependency_chain, normalize as _norm

        chain = dependency_chain(asset, concept_id)
        # Exclude the concept itself (depth 0)
        prereqs = [item for item in chain if item["id"] != concept_id]
        if not prereqs:
            return

        self._layout.addWidget(_sec_title(_t("prereq_context_title"), "#7B1FA2"))

        # Check if any prereq is weak
        has_weak = False
        for item in prereqs:
            c = asset.concept_by_id(item["id"])
            if not c:
                continue
            nk = _norm(c.name)
            mastery = float(learner_state.get("concepts", {}).get(nk, {}).get("mastery", 0.0))
            if mastery < 0.3:
                has_weak = True
                break

        if has_weak:
            warn = QLabel(_t("prereq_context_warn"))
            warn.setStyleSheet(
                "background-color: #FFF3E0; color: #E65100; border-radius: 6px;"
                "padding: 4px 8px; font-size: 11px; font-weight: 600;"
            )
            warn.setWordWrap(True)
            self._layout.addWidget(warn)

        for item in prereqs:
            c = asset.concept_by_id(item["id"])
            if not c:
                continue
            nk = _norm(c.name)
            mastery = float(learner_state.get("concepts", {}).get(nk, {}).get("mastery", 0.0))

            depth_indent = "  " * item["depth"]
            if mastery >= 0.6:
                m_color = "#2E7D32"
                m_bg = "#E8F5E9"
                m_icon = "✓"
            elif mastery >= 0.3:
                m_color = "#F57C00"
                m_bg = "#FFF3E0"
                m_icon = "◐"
            else:
                m_color = "#C62828"
                m_bg = "#FFEBEE"
                m_icon = "⚠"

            pill = QPushButton(f"{depth_indent}{m_icon} {c.name}  {mastery:.0%}")
            pill.setStyleSheet(
                f"QPushButton {{ background-color: {m_bg}; color: {m_color};"
                f"border: 1px solid {m_color}55; border-radius: 6px; padding: 4px 10px;"
                "font-size: 13px; text-align: left; }"
                f"QPushButton:hover {{ background-color: {m_color}22; }}"
            )
            pill.clicked.connect(
                lambda checked, cid=item["id"]: self.neighbor_clicked.emit(cid)
            )
            self._layout.addWidget(pill)

    def _append_unlocks(self, asset, concept_id: str, learner_state: dict) -> None:
        """Show what this concept unlocks (reverse prerequisite/causal edges).

        The prerequisite section answers "what must I know first?"; this one
        answers "why bother?" — the downstream concepts that take this one as
        a prerequisite (or causal upstream).  Pure relation reverse lookup:
        only edges the source text actually states are listed, and each pill
        shows its current mastery so the learner sees what is still blocked.
        """
        try:
            from expert_anything.core.decoder import REL_SEMANTICS, classify_relation
            from expert_anything.core.learner import normalize as _norm
        except Exception:
            return

        unlocks = []
        seen: set[str] = set()
        for r in getattr(asset, "relations", None) or []:
            if r.source != concept_id:
                continue
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            if sem not in ("prereq", "causes"):
                continue
            other = asset.concept_by_id(r.target)
            if other is None or other.id in seen:
                continue
            seen.add(other.id)
            unlocks.append((other, r.label or "", sem))
        if not unlocks:
            return

        self._layout.addWidget(_sec_title(_t("unlock_title"), "#0D47A1"))
        intro = QLabel(_t("unlock_intro", n=len(unlocks)))
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 13px; color: #546E7A;")
        self._layout.addWidget(intro)

        for other, label, sem in unlocks[:6]:
            try:
                mastery = float(
                    learner_state.get("concepts", {})
                    .get(_norm(other.name), {})
                    .get("mastery", 0.0)
                )
            except (TypeError, ValueError):
                mastery = 0.0
            sem_label = _t("rel_" + sem)
            if label:
                text = f"[{sem_label}] {label} → {other.name}  {mastery:.0%}"
            else:
                text = f"[{sem_label}] → {other.name}  {mastery:.0%}"
            color = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])["color"]
            self._layout.addWidget(self._pill(text, other.id, other.name, color))

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

    # -- domain terminology ---------------------------------------------------
    def _append_terminology(self, asset, concept) -> None:
        """Registered domain term for this concept (deterministic, no LLM).

        Sourced exclusively from the domain template via ``core.terminology``:
        an unregistered concept says so instead of guessing (source
        constraint), and the whole section is skipped when the asset has no
        detectable domain.  Related terms come from the template's
        ``prerequisites``/``connections`` IDs, resolved to names.
        """
        from expert_anything.core.domain_templates import detect_domain_from_title
        from expert_anything.core import terminology

        domain = detect_domain_from_title(getattr(asset, "title", "")) or ""
        if not domain:
            return
        term = terminology.get_term(concept.name, domain)

        self._layout.addWidget(_sec_title(_t("detail_terminology"), "#6A1B9A"))
        if term is None:
            none_lbl = QLabel(_t("terminology_none"))
            none_lbl.setWordWrap(True)
            none_lbl.setStyleSheet("font-size: 13px; color: #9575CD;")
            self._layout.addWidget(none_lbl)
            return

        if term.aliases:
            alias_lbl = QLabel(" · ".join(term.aliases))
            alias_lbl.setWordWrap(True)
            alias_lbl.setStyleSheet(
                "font-size: 12.5px; color: #00695C; background-color: #E0F2F1;"
                "border-radius: 6px; padding: 2px 8px;"
            )
            self._layout.addWidget(alias_lbl)
        if term.definition:
            d = QLabel(term.definition)
            d.setWordWrap(True)
            d.setStyleSheet("font-size: 13.5px; color: #455A64;")
            self._layout.addWidget(d)
        points = [p for p in term.key_points if p]
        if points:
            p_lbl = QLabel(" · ".join(points[:2]))
            p_lbl.setWordWrap(True)
            p_lbl.setStyleSheet("font-size: 12.5px; color: #8D6E63;")
            self._layout.addWidget(p_lbl)

        related: list[str] = []
        seen: set[str] = set()
        for tid in list(term.prerequisites):
            rel = terminology.term_by_id(tid, domain)
            if rel is None or rel.name in seen:
                continue
            seen.add(rel.name)
            related.append(rel.name)
            if len(related) >= 3:
                break
        if related:
            rel_lbl = QLabel(f"{_t('terminology_related')}: {' · '.join(related)}")
            rel_lbl.setWordWrap(True)
            rel_lbl.setStyleSheet("font-size: 12.5px; color: #6A1B9A;")
            self._layout.addWidget(rel_lbl)

    # -- score trail -----------------------------------------------------------
    def _append_score_trail(self, concept, learner_state: dict) -> None:
        """Recent evaluation scores for this concept, oldest → newest.

        Mastery % alone hides direction; the trail shows whether the learner
        is climbing or circling. Review-channel scores get a ↺ suffix so the
        interval-effect entries read differently from first-pass learning.
        Silence (no render) when fewer than two records exist.
        """
        trail = score_trail(learner_state, concept.name)
        if not trail:
            return
        parts = []
        for item in trail:
            s = f"{item['score']:.0%}"
            if item["review"]:
                s += "↺"
            parts.append(s)
        lbl = QLabel(
            _t("score_trail", n=len(trail), scores=" → ".join(parts))
        )
        lbl.setObjectName("score_trail_lbl")
        lbl.setWordWrap(True)
        lbl.setToolTip(_t("score_trail_tip"))
        lbl.setStyleSheet(
            "font-size: 13px; color: #546E7A; background-color: #F5F5F5;"
            "border-radius: 6px; padding: 4px 8px;"
        )
        self._layout.addWidget(lbl)

    # -- latest self-test miss ---------------------------------------------------
    def _append_quiz_miss(self, concept, learner_state: dict) -> None:
        """Show the last self-test's question / my answer / the right answer.

        A score alone ("20%") tells the learner *that* they missed, never
        *what* they missed.  Only trace-carrying quiz records from the quick
        self-test render here; a passed latest quiz hides the section (the
        miss is resolved, no need to keep rubbing it in).  Pure projection of
        history — deterministic, no LLM.
        """
        key = normalize(concept.name)
        row = None
        for h in learner_state.get("history", []):
            if (h.get("key") or normalize(h.get("concept", ""))) != key:
                continue
            meta = h.get("meta") or {}
            if meta.get("channel") != "quiz":
                continue
            if not meta.get("quiz_question"):
                continue  # decoder-game / older quizzes carry no trace
            row = h
            break
        if row is None:
            return
        if float(row.get("score", 0.0)) >= 0.6:
            return
        meta = row["meta"]
        question = str(meta.get("quiz_question", "") or "").strip()
        if not question:
            return
        self._layout.addWidget(_sec_title(_t("quiz_miss_title"), "#6A1B9A"))
        q_lbl = QLabel(_t("quiz_miss_question", q=question[:120]))
        q_lbl.setObjectName("quiz_miss_lbl")
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet("font-size: 13px; color: #37474F;")
        self._layout.addWidget(q_lbl)
        for key_name, tpl in (
            ("quiz_given", "quiz_miss_yours"),
            ("quiz_expected", "quiz_miss_expected"),
        ):
            value = _quiz_choice_label(meta.get(key_name, ""))
            if not value:
                continue
            lbl = QLabel(_t(tpl, s=value))
            lbl.setObjectName("quiz_miss_lbl")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                "font-size: 12.5px; color: #6A1B9A; background-color: #F3E5F5;"
                "border-radius: 6px; padding: 3px 8px;"
            )
            self._layout.addWidget(lbl)

    # -- mastery makeup ---------------------------------------------------------
    def _append_mastery_breakdown(self, concept, learner_state: dict) -> None:
        """Show WHERE the mastery % came from (per-channel evidence).

        A bare 62% hides its provenance: three quiz rounds, one practice task,
        a flashcard sweep and a self-explanation.  The breakdown is a pure
        projection of the history trace — no LLM, no new inference.
        """
        from expert_anything.core.learner import mastery_breakdown

        rows = mastery_breakdown(learner_state, concept.name)
        if not rows:
            return
        self._layout.addWidget(_sec_title(_t("mastery_breakdown"), "#00695C"))
        chips = " · ".join(
            f"{_channel_label(r['channel'])} {r['count']}× {r['avg']:.0%}"
            for r in rows
        )
        lbl = QLabel(chips)
        lbl.setObjectName("mastery_breakdown_lbl")
        lbl.setWordWrap(True)
        lbl.setToolTip(_t("mastery_breakdown_tip"))
        lbl.setStyleSheet(
            "font-size: 12.5px; color: #00695C; background-color: #E0F2F1;"
            "border-radius: 6px; padding: 4px 8px;"
        )
        self._layout.addWidget(lbl)

    def _teacher_line(self, text: str, color: str = "#5E35B1") -> None:
        """One wrapped teacher-note line (significance / signal / source)."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size: 13px; color: {color};")
        self._layout.addWidget(lbl)

    # -- active recall status ---------------------------------------------------
    def _append_recall_status(self, asset, concept, learner_state: dict) -> None:
        """Latest self-explanation coverage + the deterministic gap + retry.

        Active recall is the strongest comprehension check; once recorded it
        becomes mastery evidence (``channel="recall"``), so the card must show
        it alongside the other channels — and let the learner try again.
        """
        from expert_anything.core import feynman
        from expert_anything.core.domain_templates import detect_domain_from_title
        from expert_anything.core.learner import (
            RECALL_CHANNEL,
            normalize,
            recall_trend,
        )

        key = normalize(concept.name)
        row = next(
            (
                h
                for h in learner_state.get("history", [])
                if (h.get("key") or normalize(h.get("concept", ""))) == key
                and (h.get("meta") or {}).get("channel") == RECALL_CHANNEL
            ),
            None,
        )
        if row is None:
            return
        domain = detect_domain_from_title(getattr(asset, "title", "")) or ""
        result = feynman.coverage(str(row.get("answer", "")), concept, domain)
        pct = int(round(float(row.get("score", 0.0)) * 100))
        missed = len([p for p in (result.get("missed_points") or []) if p])
        self._layout.addWidget(_sec_title(_t("recall_title"), "#2E7D32"))
        lbl = QLabel(_t("recall_status", pct=pct, missed=missed))
        lbl.setObjectName("recall_status_lbl")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "font-size: 12.5px; color: #2E7D32; background-color: #E8F5E9;"
            "border-radius: 6px; padding: 4px 8px;"
        )
        self._layout.addWidget(lbl)

        # Coverage trend — "am I actually getting better at explaining it?"
        # Block bars are plain text (no extra widget); stagnation gets an
        # explicit retry strategy instead of silently repeating the same gap.
        trend = recall_trend(learner_state, concept.name)
        if len(trend) >= 2:
            bars = "".join(
                "▁▂▃▄▅▆▇█"[min(7, int(round(float(v) * 7)))] for v in trend
            )
            trend_lbl = QLabel(_t("recall_trend", s=bars, n=len(trend)))
            trend_lbl.setObjectName("recall_trend_lbl")
            trend_lbl.setToolTip(_t("recall_trend_tip"))
            trend_lbl.setStyleSheet("font-size: 13px; color: #2E7D32;")
            self._layout.addWidget(trend_lbl)
            if len(trend) >= 3 and max(trend[-3:]) - trend[-3] < 0.05:
                stagnant = QLabel(_t("recall_stagnant"))
                stagnant.setObjectName("recall_stagnant_lbl")
                stagnant.setWordWrap(True)
                stagnant.setStyleSheet(
                    "font-size: 12.5px; color: #BF360C;"
                    "background-color: #FBE9E7; border-radius: 6px;"
                    "padding: 4px 8px;"
                )
                self._layout.addWidget(stagnant)

        again = QPushButton(_t("recall_again"))
        again.setObjectName("recall_again_btn")
        again.setStyleSheet(
            "QPushButton { background-color: white; color: #2E7D32;"
            "border: 1px solid #A5D6A7; border-radius: 6px; padding: 4px 10px;"
            "font-size: 12.5px; }"
            "QPushButton:hover { background-color: #E8F5E9; }"
        )
        again.clicked.connect(
            lambda checked=False, a=asset, c=concept, s=learner_state: (
                open_feynman_check(self, s, a, c)
            )
        )
        self._layout.addWidget(again)

    # -- personal note ----------------------------------------------------------
    def _append_note(self, concept, learner_state: dict) -> None:
        """Own-words note block — writing an explanation in your own words is
        the cheapest strong comprehension check (generation effect)."""
        note = get_note(learner_state, concept.name)
        self._layout.addWidget(_sec_title(_t("note_title"), "#B45309"))
        if note:
            text = note[:160] + ("…" if len(note) > 160 else "")
            style = (
                "font-size: 13.5px; color: #37474F; background-color: #FFF8E1;"
                "border-radius: 6px; padding: 8px;"
            )
            tip = note[:300]
        else:
            text = _t("note_empty")
            style = "font-size: 13px; color: #9E9E9E; font-style: italic;"
            tip = _t("note_hint")
        lbl = QLabel(text)
        lbl.setObjectName("note_body_lbl")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(style)
        lbl.setToolTip(tip)
        self._layout.addWidget(lbl)

        edit_btn = QPushButton(_t("note_edit"))
        edit_btn.setObjectName("note_edit_btn")
        edit_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #B45309;"
            "border: 1px solid #FCD34D; border-radius: 6px; padding: 4px 10px;"
            "font-size: 13px; }"
            "QPushButton:hover { background-color: #FFFBEB; }"
        )
        edit_btn.clicked.connect(
            lambda checked=False, n=concept.name: self._on_edit_note(n)
        )
        self._layout.addWidget(edit_btn)

    def _on_edit_note(self, concept_name: str) -> None:
        """Modal own-words editor; persists immediately on save."""
        state = getattr(self, "_learner_state", None)
        if state is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(_t("note_dialog_title", name=concept_name))
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        hint = QLabel(_t("note_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 13px; color: #6B7A90;")
        lay.addWidget(hint)
        editor = QPlainTextEdit(get_note(state, concept_name))
        editor.setObjectName("note_editor")
        editor.setMinimumHeight(160)
        editor.setStyleSheet("font-size: 14px;")
        lay.addWidget(editor)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_note_text(concept_name, editor.toPlainText())

    def _save_note_text(self, concept_name: str, text: str) -> None:
        """Write path factored out for tests: persist + refresh the label."""
        state = getattr(self, "_learner_state", None)
        if state is None:
            return
        set_note(state, concept_name, text)
        save_learner(state)
        lbl = self.findChild(QLabel, "note_body_lbl")
        note = get_note(state, concept_name)
        if lbl is not None:
            if note:
                lbl.setText(note[:160] + ("…" if len(note) > 160 else ""))
                lbl.setStyleSheet(
                    "font-size: 13.5px; color: #37474F; background-color: #FFF8E1;"
                    "border-radius: 6px; padding: 8px;"
                )
            else:
                lbl.setText(_t("note_empty"))
                lbl.setStyleSheet(
                    "font-size: 13px; color: #9E9E9E; font-style: italic;"
                )

    # -- lesson replay ----------------------------------------------------------
    def _append_lesson_replay(self, concept, learner_state: dict) -> None:
        """Zero-cost review: re-read the last saved lesson for this concept."""
        snap = get_lesson_snapshot(learner_state, concept.name)
        if not snap:
            return
        self._layout.addWidget(_sec_title(_t("replay_section"), "#1565C0"))
        style_code = str(snap.get("style", "") or "")
        style_name = (
            _t("style_" + style_code) if style_code in ("example", "diagram", "steps")
            else _t("style_example")
        )
        meta = QLabel(
            _t("replay_meta", date=str(snap.get("at", ""))[:10], style=style_name)
        )
        meta.setObjectName("replay_meta_lbl")
        meta.setStyleSheet("font-size: 12.5px; color: #6B7A90;")
        self._layout.addWidget(meta)
        btn = QPushButton(_t("replay_btn"))
        btn.setObjectName("replay_btn")
        btn.setStyleSheet(
            "QPushButton { background-color: #E3F2FD; color: #1565C0;"
            "border: 1px solid #90CAF9; border-radius: 6px; padding: 5px 12px;"
            "font-size: 13.5px; font-weight: 600; }"
            "QPushButton:hover { background-color: #BBDEFB; }"
        )
        btn.clicked.connect(
            lambda checked=False, n=concept.name: self._on_replay_lesson(n)
        )
        self._layout.addWidget(btn)

    def _on_replay_lesson(self, concept_name: str) -> None:
        state = getattr(self, "_learner_state", None)
        snap = get_lesson_snapshot(state, concept_name) if state is not None else None
        if not snap:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(
            _t("replay_dialog_title", name=snap.get("name", concept_name))
        )
        dlg.setMinimumSize(520, 420)
        outer = QVBoxLayout(dlg)
        style_code = str(snap.get("style", "") or "")
        style_name = (
            _t("style_" + style_code) if style_code in ("example", "diagram", "steps")
            else _t("style_example")
        )
        meta = QLabel(
            _t("replay_meta", date=str(snap.get("at", ""))[:10], style=style_name)
        )
        meta.setStyleSheet("font-size: 13px; color: #6B7A90;")
        outer.addWidget(meta)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(8)
        expl = QLabel(str(snap.get("explanation", "")))
        expl.setObjectName("replay_explanation")
        expl.setWordWrap(True)
        expl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        expl.setStyleSheet("font-size: 14.5px; color: #1F2933;")
        v.addWidget(expl)
        steps = snap.get("steps") or []
        if steps:
            v.addWidget(_sec_title(_t("replay_steps"), "#2E7D32"))
            for i, s in enumerate(steps, 1):
                step_lbl = QLabel(f"{i}. {s}")
                step_lbl.setWordWrap(True)
                step_lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                step_lbl.setStyleSheet(
                    "font-size: 14px; color: #37474F; padding-left: 6px;"
                )
                v.addWidget(step_lbl)
        v.addStretch()
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.clicked.connect(lambda *_a: dlg.close())
        outer.addWidget(btns)
        dlg.exec()
