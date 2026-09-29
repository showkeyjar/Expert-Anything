from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor as _QColor,
    QDesktopServices,
    QFont as _QFont,
    QPainter as _QPainter,
    QPen as _QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core.i18n import t as _t
from expert_anything.ui.widgets._helpers import mastery_color, tag_chip, _sec_title


class DecoderSceneCard(QWidget):
    """Knowledge decoding card: SceneSpec → step-animated SVG + sort game.

    The spec is produced by Tutor (LLM SceneSpec with code admission, or the
    deterministic relation-graph fallback) and rendered here by pure code —
    the step player (QtSvg), an in-app ordering mini-game whose score re-enters
    the mastery loop via ``game_scored``, and a richer self-contained HTML
    (animation + game) that opens in the browser.
    """

    game_scored = Signal(float)

    def __init__(
        self,
        scene: dict,
        concept: str = "",
        source_title: str = "",
        definition: str = "",
        evidence: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._scene = scene
        self._concept = concept
        self._source_title = source_title
        self._definition = definition
        self._evidence = evidence or []
        self._frames: list[dict] = []
        self._idx = 0
        self._picked: list[int] = []
        self._build()

    # --- shell ---------------------------------------------------------------
    def _build(self) -> None:
        from expert_anything.core import decoder

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #FFF3E0; border: 1px solid #FFCC80;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        root.addWidget(card)

        head = QHBoxLayout()
        t = QLabel(_t("decoder_card_title"))
        t.setStyleSheet("font-size: 14px; font-weight: bold; color: #E65100;")
        head.addWidget(t)
        head.addStretch()
        open_btn = QPushButton(_t("decoder_open_html"))
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(
            "font-size: 14px; color: #E65100; border: 1px solid #FFCC80;"
            "border-radius: 6px; padding: 2px 10px; background: white;"
        )
        open_btn.clicked.connect(self._open_html)
        head.addWidget(open_btn)
        lay.addLayout(head)

        # --- step player -----------------------------------------------------
        self._frames = decoder.render_step_svgs(self._scene)
        self._dot_btns: list[QPushButton] = []
        self._svg_host: QWidget | None = None
        self._fade: QGraphicsOpacityEffect | None = None
        self._fade_anim = None
        try:
            from PySide6.QtSvgWidgets import QSvgWidget

            self._svg_widget = QSvgWidget()
            self._svg_widget.setMinimumHeight(240)
            self._svg_widget.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                " stop:0 #FBFDFF, stop:1 #F0F5FA);"
                "border: 1px solid #EDF2F8; border-radius: 10px;"
            )
            lay.addWidget(self._svg_widget)
            self._svg_host = self._svg_widget
            self._fade = QGraphicsOpacityEffect(self._svg_widget)
            self._svg_widget.setGraphicsEffect(self._fade)
        except Exception:
            self._svg_widget = None
            note = QLabel(_t("svg_unsupported"))
            note.setWordWrap(True)
            lay.addWidget(note)

        self._caption = QLabel("")
        self._caption.setWordWrap(True)
        self._caption.setStyleSheet("font-size: 15.5px; color: #123B66;")
        lay.addWidget(self._caption)

        # clickable step dots (jump to any step)
        dots = QHBoxLayout()
        dots.setSpacing(6)
        for k in range(len(self._frames)):
            d = QPushButton(str(k + 1))
            d.setFixedSize(24, 24)
            d.setCursor(Qt.CursorShape.PointingHandCursor)
            d.clicked.connect(lambda _=False, j=k: self._show(j))
            dots.addWidget(d)
            self._dot_btns.append(d)
        dots.addStretch()
        lay.addLayout(dots)

        from PySide6.QtCore import QTimer

        ctrl = QHBoxLayout()
        self._btn_back = QPushButton("◎ " + _t("decoder_overview_btn"))
        self._btn_start = QPushButton(_t("decoder_step_btn") + " ›")
        self._btn_prev = QPushButton(_t("decoder_prev"))
        self._btn_next = QPushButton(_t("decoder_next"))
        self._btn_play = QPushButton(_t("decoder_play"))
        for b in (
            self._btn_back,
            self._btn_start,
            self._btn_prev,
            self._btn_next,
            self._btn_play,
        ):
            b.setStyleSheet(
                "font-size: 14px; padding: 3px 12px; border: 1px solid #FFCC80;"
                "border-radius: 6px; background: white; color: #E65100;"
            )
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setStyleSheet(
            "font-size: 14px; padding: 3px 14px; border: none;"
            "border-radius: 6px; background: #E65100; color: white;"
            "font-weight: bold;"
        )
        ctrl.addWidget(self._btn_back)
        ctrl.addWidget(self._btn_start)
        ctrl.addWidget(self._btn_prev)
        ctrl.addWidget(self._btn_play)
        ctrl.addWidget(self._btn_next)
        ctrl.addStretch()
        lay.addLayout(ctrl)
        self._btn_back.clicked.connect(self._show_static)
        self._btn_start.clicked.connect(lambda: self._show(0))
        self._btn_prev.clicked.connect(lambda: self._show(self._idx - 1))
        self._btn_next.clicked.connect(lambda: self._show(self._idx + 1))
        self._timer = QTimer(self)
        self._timer.setInterval(2200)
        self._timer.timeout.connect(self._auto_advance)
        self._btn_play.clicked.connect(self._toggle_play)
        # L1 by default: static overview first — animation is opt-in
        self._show_static()

        # --- ordering mini-game (score re-enters the mastery loop) -----------
        game = self._scene.get("game")
        if isinstance(game, dict) and game.get("items"):
            gh = QLabel(_t("decoder_game_title"))
            gh.setStyleSheet("font-size: 14px; font-weight: bold; color: #BF360C;")
            lay.addWidget(gh)
            goal = QLabel(str(game.get("goal", "")))
            goal.setWordWrap(True)
            goal.setStyleSheet("font-size: 14px; color: #5D4037;")
            lay.addWidget(goal)

            grid = QGridLayout()
            grid.setSpacing(4)
            self._chip_btns: list[QPushButton] = []
            for i, item in enumerate(game["items"]):
                b = QPushButton(str(item))
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setCheckable(False)
                b.setStyleSheet(
                    "font-size: 14px; padding: 4px 10px; border-radius: 12px;"
                    "border: 1px solid #FFB74D; background: #FFF8E1; color: #5D4037;"
                    "text-align: center;"
                )
                b.clicked.connect(lambda _=False, k=i: self._pick(k))
                grid.addWidget(b, i // 3, i % 3)
                self._chip_btns.append(b)
            lay.addLayout(grid)

            hint = QLabel(_t("decoder_your_order"))
            hint.setStyleSheet("font-size: 13px; color: #8D6E63;")
            lay.addWidget(hint)
            self._picked_label = QLabel("—")
            self._picked_label.setWordWrap(True)
            self._picked_label.setStyleSheet(
                "font-size: 15px; color: #37474F; background: white;"
                "border-radius: 6px; padding: 4px;"
            )
            lay.addWidget(self._picked_label)

            gctrl = QHBoxLayout()
            self._btn_check = QPushButton(_t("decoder_game_check"))
            self._btn_check.setStyleSheet(
                "font-size: 14px; padding: 3px 12px; border-radius: 6px;"
                "background: #E65100; color: white;"
            )
            self._btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn_check.clicked.connect(self._check_game)
            retry = QPushButton(_t("decoder_game_retry"))
            retry.setStyleSheet(
                "font-size: 14px; padding: 3px 12px; border-radius: 6px;"
                "border: 1px solid #FFCC80; background: white; color: #E65100;"
            )
            retry.setCursor(Qt.CursorShape.PointingHandCursor)
            retry.clicked.connect(self._reset_game)
            reveal = QPushButton(_t("decoder_game_answer"))
            reveal.setStyleSheet(
                "font-size: 14px; padding: 3px 12px; border-radius: 6px;"
                "border: 1px solid #FFCC80; background: white; color: #E65100;"
            )
            reveal.setCursor(Qt.CursorShape.PointingHandCursor)
            reveal.clicked.connect(self._reveal_game)
            for b in (self._btn_check, retry, reveal):
                gctrl.addWidget(b)
            gctrl.addStretch()
            lay.addLayout(gctrl)
            self._verdict = QLabel("")
            self._verdict.setWordWrap(True)
            self._verdict.setStyleSheet("font-size: 14px;")
            lay.addWidget(self._verdict)

    # --- step player behaviour ----------------------------------------------
    def _set_step_ui(self, on: bool) -> None:
        """Toggle between L1 (overview) and L2 (step-by-step) chrome."""
        widgets = [
            self._btn_back,
            self._btn_prev,
            self._btn_play,
            self._btn_next,
            *self._dot_btns,
        ]
        for w in widgets:
            w.setVisible(on)
        self._btn_start.setVisible(not on)

    def _show_static(self) -> None:
        """L1 — static overview: full diagram, minimal cognitive cost.

        Nothing animates by default; the walkthrough is one explicit
        click away (progressive representation)."""
        from expert_anything.core import decoder

        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText(_t("decoder_play"))
        self._set_step_ui(False)
        self._load_frame(decoder.render_svg(self._scene))
        self._caption.setText(
            f"<span style='background-color:#1976D2; color:white;"
            f"border-radius:4px; padding:1px 8px; font-size: 13px;'>◎</span>"
            f"&nbsp; {html.escape(_t('decoder_overview_hint'))}"
        )

    def _show(self, i: int) -> None:
        if not self._frames:
            return
        self._set_step_ui(True)
        self._idx = max(0, min(i, len(self._frames) - 1))
        f = self._frames[self._idx]
        self._load_frame(f["svg"])
        self._caption.setText(
            f"<span style='background-color:#1976D2; color:white;"
            f"border-radius:4px; padding:1px 8px; font-size: 13px;'>"
            f"&nbsp;{self._idx + 1}/{len(self._frames)}&nbsp;</span>"
            f"&nbsp; {html.escape(f['caption'])}"
        )
        for k, d in enumerate(self._dot_btns):
            if k == self._idx:
                style = (
                    "background: #1976D2; color: white; border: none;font-weight: bold;"
                )
            elif k < self._idx:
                style = "background: #DCEBFB; color: #1565C0;border: 1px solid #64B5F6;"
            else:
                style = "background: white; color: #7B8FA3;border: 1px solid #C6D4E4;"
            d.setStyleSheet(style + "border-radius: 12px; font-size: 13px;")

    def _load_frame(self, svg: str) -> None:
        """Swap the frame SVG with a gentle fade-in (keeps steps feeling
        animated even though QtSvg ignores SMIL)."""
        if self._svg_widget is None:
            return
        data = svg.encode("utf-8")
        try:
            from PySide6.QtCore import QByteArray

            self._svg_widget.load(QByteArray(data))
        except Exception:
            self._svg_widget.load(data)
        if self._fade is not None:
            try:
                from PySide6.QtCore import QEasingCurve, QPropertyAnimation

                self._fade_anim = QPropertyAnimation(self._fade, b"opacity", self)
                self._fade_anim.setDuration(280)
                self._fade_anim.setStartValue(0.0)
                self._fade_anim.setEndValue(1.0)
                self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self._fade_anim.start()
            except Exception:
                self._fade.setOpacity(1.0)

    def _auto_advance(self) -> None:
        if self._idx >= len(self._frames) - 1:
            self._timer.stop()
            self._btn_play.setText(_t("decoder_play"))
            return
        self._show(self._idx + 1)

    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText(_t("decoder_play"))
        else:
            self._show(0)
            self._timer.start()
            self._btn_play.setText("⏸")

    # --- game behaviour -------------------------------------------------------
    def _pick(self, i: int) -> None:
        if i in self._picked:
            self._picked.remove(i)
        else:
            self._picked.append(i)
        items = self._scene["game"]["items"]
        txt = " → ".join(str(items[k]) for k in self._picked) if self._picked else "—"
        self._picked_label.setText(txt)
        for k, b in enumerate(self._chip_btns):
            b.setStyleSheet(
                (
                    "background: #E65100; color: white; border-color: #E65100;"
                    if k in self._picked
                    else "background: #FFF8E1; color: #5D4037; border-color: #FFB74D;"
                )
                + "font-size: 14px; padding: 4px 10px; border-radius: 12px;"
                "border: 1px solid; text-align: center;"
            )

    def _check_game(self) -> None:
        game = self._scene["game"]
        n = len(game["items"])
        if len(self._picked) != n:
            return
        answer = list(game.get("answer") or range(n))
        hits = sum(1 for a, c in zip(self._picked, answer) if a == c)
        score = round(hits / n, 2)
        ok = hits == n
        self._verdict.setText(
            _t("decoder_game_correct")
            if ok
            else f"{_t('decoder_game_wrong')}（{hits}/{n}）"
        )
        self._verdict.setStyleSheet(
            f"font-size: 14px; font-weight: {'bold' if ok else 'normal'};"
            f"color: {'#2E7D32' if ok else '#C62828'};"
        )
        self.game_scored.emit(score)

    def _reset_game(self) -> None:
        self._picked = []
        self._picked_label.setText("—")
        self._verdict.setText("")
        for k in range(len(self._chip_btns)):
            self._chip_btns[k].setStyleSheet(
                "font-size: 14px; padding: 4px 10px; border-radius: 12px;"
                "border: 1px solid #FFB74D; background: #FFF8E1; color: #5D4037;"
                "text-align: center;"
            )

    def _reveal_game(self) -> None:
        game = self._scene["game"]
        items = game["items"]
        answer = list(game.get("answer") or range(len(items)))
        self._verdict.setText(
            f"{_t('decoder_game_answer')}： "
            + " → ".join(str(items[k]) for k in answer)
        )
        self._verdict.setStyleSheet("font-size: 14px; color: #1565C0;")

    # --- browser demo ---------------------------------------------------------
    def _open_html(self) -> None:
        import os
        import tempfile

        from PySide6.QtGui import QDesktopServices
        from expert_anything.core import decoder

        safe = re.sub(r"[^\w\-]+", "_", self._concept or "scene")[:32]
        path = os.path.join(tempfile.gettempdir(), f"ea_decoder_{safe}.html")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    decoder.render_interactive_html(
                        self._scene,
                        self._concept,
                        self._source_title,
                        self._definition,
                        self._evidence,
                    )
                )
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            pass


class TeachResultView(QWidget):
    """Structured lesson view: explanation / example / steps / practice / evidence.

    Replaces the plain QTextEdit dump with colour-coded cards, a numbered
    step ladder and a dedicated practice area. ``submit_requested`` fires
    when the learner submits an answer (the answer box is exposed as
    ``answer_input``).
    """

    submit_requested = Signal()
    followup_requested = Signal(str)
    neighbor_clicked = Signal(str)  # concept name
    evidence_jump_requested = Signal(str, str)  # concept id, evidence text
    quiz_requested = Signal()  # user asked for a quick self-test
    quiz_result = Signal(float)  # scored quiz (record into mastery)
    practice_requested = Signal()  # user asked for a hands-on task
    practice_submit = Signal(str)  # answer submitted (score via quiz_result)
    next_requested = Signal()
    retry_requested = Signal()
    vary_requested = Signal()
    harness_adopt_requested = Signal(dict)  # learner adopts an evolved HarnessSpec
    harness_transfer_requested = Signal(
        dict
    )  # learner migrates a harness from another asset

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.answer_input: QWidget | None = None
        self._build(result)

    def _provenance_concept(self, concept_name: str):
        """Concept object for evidence→location lookup, or None.

        Walks up to the enclosing teach view (parent) and resolves the
        concept in the current asset; degrades silently when the parent
        chain or asset is unavailable so provenance badges simply don't
        render instead of breaking the lesson.
        """
        if not concept_name:
            return None
        p = self.parent()
        main = getattr(p, "_main", None) if p is not None else None
        asset = main.get_asset() if main is not None else None
        if asset is None:
            return None
        try:
            return asset.concept_by_name(concept_name)
        except Exception:
            return None

    def _card(
        self, title: str, body: str, bg: str, border: str, title_color: str
    ) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {title_color};")
        lay.addWidget(t)
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet("font-size: 15px; color: #37474F; line-height: 1.6;")
        lay.addWidget(b)
        return card

    def _build(self, result: dict) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # header: concept + style badge
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(result.get("concept", _t("stat_total")))
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1565C0;")
        head.addWidget(title)
        style = result.get("style", "")
        if style:
            # style is always canonical code (example/diagram/steps) internally
            head.addWidget(tag_chip(_t("style_" + style), "#0284C7"))
        # Phase 4 — deterministic difficulty hint from detect_user_profile
        # (foundation / standard / advanced / unknown); unknown renders too,
        # because "we cannot tell yet" is itself useful information.
        hint = str(result.get("difficulty_hint", "") or "")
        if hint:
            hint_text = _t("profile_hint_" + hint)
            if hint_text and hint_text != "profile_hint_" + hint:
                head.addWidget(tag_chip(hint_text, "#7B5A9E"))
        head.addStretch()
        root.addLayout(head)

        def _txt(v):
            return str(v).strip() if v is not None else ""

        def _lst(v):
            if isinstance(v, list):
                return [str(s) for s in v if str(s).strip()]
            if isinstance(v, str) and v.strip():
                return [s.strip() for s in v.splitlines() if s.strip()]
            return []

        # explanation
        explanation = _txt(result.get("explanation"))
        if explanation:
            root.addWidget(
                self._card(
                    _t("explanation"), explanation, "#E3F2FD", "#90CAF9", "#1565C0"
                )
            )

            # source-provenance caveat: this concept carries no located
            # evidence in the asset (template-enriched / unlocatable), so the
            # lesson is relation- and skeleton-based rather than verbatim.
            # The learner deserves to know before trusting the explanation.
            concept_obj = self._provenance_concept(result.get("concept", ""))
            if concept_obj is not None and not concept_obj.locations:
                warn = QFrame()
                warn.setStyleSheet(
                    "QFrame { background-color: #FFF3E0; border-left: 3px solid"
                    " #FB8C00; border-radius: 4px; }"
                )
                w_lay = QVBoxLayout(warn)
                w_lay.setContentsMargins(10, 6, 10, 6)
                w_lbl = QLabel(f"⚠ {_t('teach_unanchored_warn')}")
                w_lbl.setWordWrap(True)
                w_lbl.setStyleSheet(
                    "font-size: 13px; color: #E65100; line-height: 1.4;"
                )
                w_lay.addWidget(w_lbl)
                root.addWidget(warn)

            # source provenance — show which evidence the explanation is based on,
            # each entry badged with its page/line anchor (SourceLocation) and
            # clickable to jump the reader to that exact passage (AGENTS.md #1)
            evidence_list = [
                str(e) for e in (result.get("evidence") or []) if str(e).strip()
            ]
            if evidence_list:
                prov = QFrame()
                prov.setStyleSheet(
                    "QFrame { background-color: #F1F8E9; border-left: 3px solid #689F38;"
                    "border-radius: 4px; }"
                )
                prov_lay = QVBoxLayout(prov)
                prov_lay.setContentsMargins(10, 6, 10, 6)
                prov_lay.setSpacing(4)
                prov_title = QLabel(_t("source_provenance"))
                prov_title.setStyleSheet(
                    "font-size: 13px; font-weight: bold; color: #558B2F;"
                )
                prov_lay.addWidget(prov_title)
                for e in evidence_list[:2]:
                    row = QHBoxLayout()
                    row.setSpacing(6)
                    e_short = e if len(e) <= 120 else e[:117] + "…"
                    e_lbl = QLabel(f"📖 {e_short}")
                    e_lbl.setWordWrap(True)
                    e_lbl.setStyleSheet(
                        "font-size: 13px; color: #558B2F; line-height: 1.4;"
                    )
                    row.addWidget(e_lbl, 1)
                    loc = (
                        concept_obj.location_for_evidence(e)
                        if concept_obj is not None
                        else None
                    )
                    if loc is not None and (loc.page or loc.line):
                        if loc.page:
                            badge_txt = _t("loc_page_and_line").format(
                                page=loc.page, line=loc.line
                            )
                        else:
                            badge_txt = _t("loc_line_only").format(line=loc.line)
                        badge = QPushButton(badge_txt)
                        badge.setCursor(Qt.CursorShape.PointingHandCursor)
                        badge.setStyleSheet(
                            "QPushButton { background-color: #DCEDC8; color: #33691E;"
                            "border: 1px solid #AED581; border-radius: 9px;"
                            "padding: 1px 8px; font-size: 11.5px; }"
                            "QPushButton:hover { background-color: #AED581; }"
                        )
                        badge.clicked.connect(
                            lambda checked, ev=e, cid=(
                                concept_obj.id if concept_obj is not None else ""
                            ): self.evidence_jump_requested.emit(cid, ev)
                        )
                        row.addWidget(badge)
                    prov_lay.addLayout(row)
                root.addWidget(prov)

        # knowledge decoding card (SceneSpec → step animation + sort game)
        # Placed right after explanation so the learner sees the visual
        # deconstruction before reading examples and steps — visual-first.
        scene = result.get("scene")
        if isinstance(scene, dict) and scene.get("nodes"):
            dec_card = DecoderSceneCard(
                scene,
                _txt(result.get("concept")),
                definition=_txt(result.get("definition", "")),
                evidence=result.get("evidence") or [],
            )
            dec_card.game_scored.connect(self.quiz_result)
            root.addWidget(dec_card)

        # example
        example = _txt(result.get("example"))
        if example:
            root.addWidget(
                self._card(_t("example"), example, "#FFF8E1", "#FFE082", "#B45309")
            )

        # terminology (Phase 4 — registered domain glossary, template-sourced;
        # the block is produced by core.terminology via Tutor.enrich, so this
        # view never invents a term: an unregistered concept says so).
        terminology = result.get("terminology")
        if isinstance(terminology, dict):
            term_self = terminology.get("self")
            related_terms = terminology.get("related") or []
            lines: list[str] = []
            if isinstance(term_self, dict) and term_self.get("name"):
                lines.append(f"{_t('terminology_self')}: {term_self.get('name', '')}")
                aliases = [
                    str(a) for a in (term_self.get("aliases") or []) if str(a).strip()
                ]
                if aliases:
                    lines.append(f"{_t('terminology_alias')}: {' / '.join(aliases)}")
                definition = str(term_self.get("definition", "") or "").strip()
                if definition:
                    lines.append(f"{_t('terminology_definition')}: {definition}")
                points = [
                    str(p)
                    for p in (term_self.get("key_points") or [])
                    if str(p).strip()
                ]
                if points:
                    lines.append(f"{_t('terminology_key_points')}: {points[0]}")
            else:
                lines.append(_t("terminology_none"))
            for term in related_terms[:3]:
                if not isinstance(term, dict) or not term.get("name"):
                    continue
                matched = str(term.get("matched", "") or "")
                label = f"• {term['name']}"
                if matched and matched != term["name"]:
                    label += f" ({_t('terminology_matched', matched=matched)})"
                lines.append(label)
            root.addWidget(
                self._card(
                    _t("terminology"),
                    "\n".join(lines),
                    "#F3E5F5",
                    "#CE93D8",
                    "#6A1B9A",
                )
            )

        # analogy bridge (LLM compressed-knowledge layer)
        analogy = _txt(result.get("analogy"))
        if analogy:
            root.addWidget(
                self._card(
                    _t("analogy_title"), analogy, "#E0F2F1", "#80CBC4", "#00695C"
                )
            )

        # cross-book anchor (personalised link to a previously learned concept)
        cross = result.get("cross_link")
        if isinstance(cross, dict) and cross.get("name"):
            root.addWidget(
                self._card(
                    _t("crosslink_title").format(
                        name=cross.get("name", ""), asset=cross.get("asset", "") or ""
                    ),
                    cross.get("relation", ""),
                    "#E3F2FD",
                    "#90CAF9",
                    "#0D47A1",
                )
            )

        # connected (semantic relation summary — the "where it sits" block)
        connected = _txt(result.get("connected"))
        if connected:
            root.addWidget(
                self._card(
                    _t("connected_title"),
                    connected,
                    "#E8F0F8",
                    "#B0C4D8",
                    "#0c4a6e",
                )
            )

        # steps (numbered ladder)
        steps = _lst(result.get("steps"))
        if steps:
            steps_title = QLabel(_t("steps_title"))
            steps_title.setStyleSheet(
                "font-size: 14px; font-weight: bold; color: #37474F;"
            )
            root.addWidget(steps_title)
            for i, s in enumerate(steps, 1):
                row = QHBoxLayout()
                row.setSpacing(8)
                num = QLabel(str(i))
                num.setAlignment(Qt.AlignmentFlag.AlignCenter)
                num.setFixedSize(22, 22)
                num.setStyleSheet(
                    "background-color: #1565C0; color: white; border-radius: 11px;"
                    "font-size: 13px; font-weight: bold;"
                )
                row.addWidget(num, 0)
                txt = QLabel(str(s))
                txt.setWordWrap(True)
                txt.setStyleSheet("font-size: 15px; color: #37474F;")
                row.addWidget(txt, 1)
                root.addLayout(row)

        # practice
        practice = _txt(result.get("practice"))
        if practice:
            prac_card = QFrame()
            prac_card.setStyleSheet(
                "QFrame { background-color: #F1F8E9; border: 1px solid #AED581;"
                "border-radius: 8px; }"
            )
            prac_lay = QVBoxLayout(prac_card)
            prac_lay.setContentsMargins(12, 10, 12, 10)
            prac_lay.setSpacing(6)
            p_t = QLabel(_t("practice"))
            p_t.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E7D32;")
            prac_lay.addWidget(p_t)
            p_q = QLabel(practice)
            p_q.setWordWrap(True)
            p_q.setStyleSheet("font-size: 15px; color: #37474F;")
            prac_lay.addWidget(p_q)

            self.answer_input = QTextEdit()
            self.answer_input.setPlaceholderText(_t("answer_placeholder"))
            self.answer_input.setMinimumHeight(80)
            self.answer_input.setStyleSheet(
                "QTextEdit { border: 1px solid #C5E1A5; border-radius: 6px;"
                "padding: 8px; font-size: 15px; background-color: white; }"
            )
            prac_lay.addWidget(self.answer_input)

            submit_btn = QPushButton(_t("submit_answer"))
            submit_btn.setStyleSheet(
                "QPushButton { background-color: #4CAF50; color: white; border: none;"
                "border-radius: 6px; padding: 8px 18px; font-size: 15px; font-weight: bold; }"
                "QPushButton:hover { background-color: #388E3C; }"
            )
            submit_btn.clicked.connect(self.submit_requested)
            prac_lay.addWidget(submit_btn, 0, Qt.AlignmentFlag.AlignRight)
            root.addWidget(prac_card)

        # evidence
        evidence = [str(e) for e in (result.get("evidence") or []) if str(e).strip()]
        if evidence:
            root.addWidget(
                self._card(
                    _t("evidence_label"),
                    "\n".join(f"• {e}" for e in evidence[:3]),
                    "#E8EAF6",
                    "#C5CAE9",
                    "#3F51B5",
                )
            )

        root.addStretch()
        self._build_followup()
        self._build_quiz_area()
        self._build_practice_area()

    # -- evaluation feedback ---------------------------------------------------
    def append_evaluation(
        self, score: float, feedback: str, reference: str = "", gap: str = ""
    ) -> None:
        """Append an evaluation card (score + feedback + reference answer)."""
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F3E5F5; border: 1px solid #CE93D8;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # score row
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_sec_title(_t("eval_result"), "#6A1B9A"))
        score_lbl = QLabel(f"{score:.0%}")
        score_lbl.setStyleSheet(
            f"background-color: {mastery_color(score)}; color: white;"
            "padding: 3px 12px; border-radius: 9px; font-size: 15px; font-weight: bold;"
        )
        head.addWidget(score_lbl)
        head.addStretch()
        lay.addLayout(head)

        if feedback:
            fb = QLabel(feedback)
            fb.setWordWrap(True)
            fb.setStyleSheet("font-size: 15px; color: #37474F;")
            lay.addWidget(fb)

        if reference:
            ref_title = QLabel(_t("eval_reference"))
            ref_title.setStyleSheet(
                "font-size: 13.5px; font-weight: bold; color: #6A1B9A; margin-top: 2px;"
            )
            lay.addWidget(ref_title)
            ref = QLabel(reference)
            ref.setWordWrap(True)
            ref.setStyleSheet(
                "font-size: 14.5px; color: #37474F; background-color: #EDE7F6;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(ref)

        if gap:
            gap_title = QLabel(_t("eval_gap"))
            gap_title.setStyleSheet(
                "font-size: 13.5px; font-weight: bold; color: #C62828; margin-top: 2px;"
            )
            lay.addWidget(gap_title)
            gp = QLabel(gap)
            gp.setWordWrap(True)
            gp.setStyleSheet(
                "font-size: 14.5px; color: #B71C1C; background-color: #FFEBEE;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(gp)

        # Keep the learner moving after feedback.  These actions are explicit
        # and local to the result card, so the user does not need to return to
        # the concept selector after every answer.
        actions = QHBoxLayout()
        actions.setSpacing(8)
        next_btn = QPushButton(_t("learn_next"))
        next_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 12px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        next_btn.clicked.connect(self.next_requested.emit)
        actions.addWidget(next_btn)

        retry_btn = QPushButton(_t("learn_retry"))
        retry_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #6A1B9A;"
            "border: 1px solid #CE93D8; border-radius: 6px;"
            "padding: 6px 12px; font-size: 14px; }"
            "QPushButton:hover { background-color: #F3E5F5; }"
        )
        retry_btn.clicked.connect(self.retry_requested.emit)
        actions.addWidget(retry_btn)

        vary_btn = QPushButton(_t("learn_vary"))
        vary_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #00695C;"
            "border: 1px solid #80CBC4; border-radius: 6px;"
            "padding: 6px 12px; font-size: 14px; }"
            "QPushButton:hover { background-color: #E0F2F1; }"
        )
        vary_btn.clicked.connect(self.vary_requested.emit)
        actions.addWidget(vary_btn)
        actions.addStretch()
        lay.addLayout(actions)

        root.insertWidget(root.count() - 1, card)

    # -- AutoHarness evolution suggestion --------------------------------------
    def append_harness_suggestion(
        self,
        title: str,
        body: str,
        candidate: dict,
        source: str = "stuck",
        extra: dict | None = None,
    ) -> None:
        """Append an AutoHarness evolution suggestion card with an adopt button.

        The candidate (a normalized HarnessSpec) was produced by the stuck
        loop's ``evolve_for_stuck`` (source="stuck", amber card), by
        ``evolve_for_regression`` (source="regression", violet card — the
        regression signal points to a guard that may be backfiring, e.g.
        budget_ok throttling explanations), or by ``evolve_joint`` when
        multiple signal families fire together (source="joint", cyan card —
        the fusion decision with its diagnosis; ``extra`` carries metadata
        for the audit chain, e.g. {"_joint_reason": "stuck+regression"}).
        Adopting any of them fires ``harness_adopt_requested`` so the window
        can persist the spec and re-teach with its style.
        """
        if source == "joint":
            bg, border, title_c, text_c, btn_bg, btn_hover = (
                "#E0F7FA",
                "#4DD0E1",
                "#006064",
                "#00363D",
                "#00838F",
                "#006064",
            )
            btn_text = _t("harness_adopt_joint")
        elif source == "regression":
            bg, border, title_c, text_c, btn_bg, btn_hover = (
                "#F3E5F5",
                "#CE93D8",
                "#4A148C",
                "#311B3A",
                "#6A1B9A",
                "#4A148C",
            )
            btn_text = _t("harness_adopt_regress")
        else:
            bg, border, title_c, text_c, btn_bg, btn_hover = (
                "#FFF8E1",
                "#FFE082",
                "#E65100",
                "#4E342E",
                "#E65100",
                "#BF360C",
            )
            btn_text = _t("harness_adopt")
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        lay.addWidget(_sec_title(title, title_c))
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet(f"font-size: 14.5px; color: {text_c};")
        lay.addWidget(b)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn = QPushButton(btn_text)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {btn_bg}; color: white;"
            "border: none; border-radius: 6px; padding: 7px 16px;"
            "font-size: 14.5px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: {btn_hover}; }}"
        )
        btn.clicked.connect(
            lambda checked=False, c=candidate, s=source, x=extra or {}: (
                self.harness_adopt_requested.emit(dict(c, _source=s, **x))
            )
        )
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)

        root.insertWidget(root.count() - 1, card)

    def append_transfer_suggestion(self, title: str, body: str, payload: dict) -> None:
        """Append a cross-asset harness migration suggestion card.

        Unlike the amber evolution card (``append_harness_suggestion``), this
        light-blue card carries a *transfer payload* built by the window's
        ``_find_transfer_candidates``::

            {"source_asset_id", "source_title", "spec", "evaluation", "gain"}

        Adopting it fires ``harness_transfer_requested`` with the whole payload
        so the window can persist via ``adopt_harness_for_asset`` (audit trail
        reason="transfer") and re-teach with the migrated style.
        """
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E3F2FD; border: 1px solid #90CAF9;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        lay.addWidget(_sec_title(title, "#0D47A1"))
        b = QLabel(body)
        b.setWordWrap(True)
        b.setStyleSheet("font-size: 14.5px; color: #0D2B45;")
        lay.addWidget(b)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn = QPushButton(_t("harness_transfer_adopt"))
        btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 6px; padding: 7px 16px; font-size: 14.5px;"
            "font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        btn.clicked.connect(
            lambda checked=False, p=payload: self.harness_transfer_requested.emit(p)
        )
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)

        root.insertWidget(root.count() - 1, card)

    def append_doubt_strip(
        self, concept_anoms: list, open_count: int = 0
    ) -> bool:
        """Teacher-model "doubt" strip: what the system is unsure about.

        Renders only when there is something to say (matched anomalies for
        this concept, or open anomalies elsewhere in the asset) — a fully
        resolved asset shows nothing. Informational, not actionable: lighter
        than the amber evolution card.
        """
        concept_anoms = list(concept_anoms or [])
        if not concept_anoms and open_count <= 0:
            return False
        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #FFF8E1; border-left: 3px solid "
            "#F9A825; border-radius: 4px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        lay.addWidget(_sec_title(_t("doubt_section"), "#B45309"))

        if concept_anoms:
            for an in concept_anoms:
                # t() falls back to the raw key when missing: strip the
                # prefix so an unknown kind still reads as its own code
                kind_key = f"kind_{an.kind}"
                kind = _t(kind_key)
                if kind == kind_key:
                    kind = str(getattr(an, "kind", "") or "")
                desc = str(getattr(an, "description", "") or "")[:80]
                line = QLabel(_t("doubt_matched", kind=kind, desc=desc))
                line.setWordWrap(True)
                line.setStyleSheet("font-size: 13.5px; color: #6B4E0E;")
                lay.addWidget(line)
        else:
            line = QLabel(_t("doubt_none", n=open_count))
            line.setWordWrap(True)
            line.setStyleSheet("font-size: 13.5px; color: #6B4E0E;")
            lay.addWidget(line)

        root.insertWidget(root.count() - 1, card)
        return True

    def append_harness_history(self, events: list[dict], limit: int = 5) -> None:
        """Append an evolution history block (audit trail) to the teach area.

        Events come from ``auto_harness.load_harness_history`` (append-only
        audit chain). Only *new* events since the last call on this view are
        rendered (dedup by count), capped at ``limit``, so repeated calls
        (e.g. stuck branch + fresh teaching view) never duplicate lines.
        """
        if not events:
            return
        shown = getattr(self, "_harness_shown_count", 0)
        new_events = events[shown:]
        if not new_events:
            return
        self._harness_shown_count = len(events)

        root = self.layout()
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F5F5F5; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(_sec_title(_t("harness_history"), "#455A64"))

        _reason_labels = {
            "stuck": _t("harness_reason_stuck"),
            "manual": _t("harness_reason_manual"),
            "steady": _t("harness_reason_steady"),
            "transfer": _t("harness_reason_transfer"),
            "regression": _t("harness_reason_regression"),
            "joint": _t("harness_reason_joint"),
            "sessions": _t("harness_reason_sessions"),
        }

        def _fmt(reason: str) -> str:
            # 联合演化 reason 是触发家族串（如 stuck+regression+sessions），
            # 逐个家族本地化后拼接，保证审计链可读。
            if reason in _reason_labels:
                return _reason_labels[reason]
            return "+".join(_reason_labels.get(p, p) for p in str(reason).split("+"))

        for ev in new_events[-limit:]:
            ts = ev.get("ts", "")
            ts_show = ts[:16].replace("T", " ") if isinstance(ts, str) else ""
            reason = _fmt(ev.get("reason", ""))
            old = ev.get("old", "")
            new = ev.get("new", "")
            line = (
                f"{ts_show}  {reason}\n  {old}  →  {new}"
                if ts_show
                else f"{reason}\n  {old}  →  {new}"
            )
            b = QLabel(line)
            b.setWordWrap(True)
            b.setStyleSheet("font-size: 13.5px; color: #37474F;")
            lay.addWidget(b)

        root.insertWidget(root.count() - 1, card)

    # -- related concepts --------------------------------------------------------
    def set_neighbors(
        self, neighbors: list[tuple[str, str, str] | tuple[str, str, str, str]]
    ) -> None:
        """Show a mini knowledge graph centred on the current concept.

        The current concept sits in the middle, surrounded by its direct
        neighbours arranged radially. Edges are coloured by semantic type
        (prereq / causes / contrast / part-of / is_a / related) with arrow
        direction. Clickable chips below provide quick navigation.

        Each entry is ``(label, name, concept_id)`` or the richer
        ``(label, name, concept_id, relation_type)``; the short form is
        normalized here so both callers keep working.

        This gives the learner constant "you are here" context during the
        lesson — no need to switch back to the graph view.
        """
        if not neighbors:
            return
        # Normalize both the documented 3-tuple and the richer 4-tuple
        # (relation type) forms once, so the rest of the pipeline can rely
        # on a stable shape.
        normalized: list[tuple[str, str, str, str]] = []
        for n in neighbors:
            if len(n) == 4:
                label, name, cid, rtype = n
            else:
                label, name, cid = n
                rtype = ""
            normalized.append((label, name, cid, rtype))
        neighbors = normalized

        from expert_anything.core.decoder import classify_relation, REL_SEMANTICS

        root = self.layout()
        t = QLabel(_t("related_concepts"))
        t.setStyleSheet("font-size: 14px; font-weight: bold; color: #0c4a6e;")
        root.insertWidget(root.count() - 1, t)

        # Build the mini-graph SVG
        svg = self._build_minigraph_svg(neighbors)
        try:
            from PySide6.QtSvgWidgets import QSvgWidget

            graph_widget = QSvgWidget()
            graph_widget.load(bytes(svg, "utf-8"))
            graph_widget.setMinimumHeight(210)
            graph_widget.setStyleSheet(
                "QSvgWidget { background-color: #FAFBFC; border: 1px solid #E0E0E0;"
                "border-radius: 8px; }"
            )
            root.insertWidget(root.count() - 1, graph_widget)
        except ImportError:
            # Fallback: skip graph if QtSvg isn't available
            pass

        # Clickable chips below the graph for quick navigation
        chips_row = QWidget()
        chips_lay2 = QHBoxLayout(chips_row)
        chips_lay2.setContentsMargins(0, 8, 0, 0)
        chips_lay2.setSpacing(6)
        for label, name, _cid, rtype in neighbors[:6]:
            sem = classify_relation(label or "", rtype or "")
            sem_info = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])
            color = sem_info["color"]
            chip = QPushButton(name)
            chip.setToolTip(label or _t("related_concepts"))
            chip.setStyleSheet(
                f"QPushButton {{ background-color: {color}12; color: {color};"
                f"border: 1px solid {color}40; border-radius: 10px; padding: 3px 10px;"
                "font-size: 13px; }"
                f"QPushButton:hover {{ background-color: {color}25; }}"
            )
            chip.clicked.connect(lambda checked, n=name: self.neighbor_clicked.emit(n))
            chips_lay2.addWidget(chip)
        chips_lay2.addStretch()
        root.insertWidget(root.count() - 1, chips_row)

    def _build_minigraph_svg(self, neighbors: list) -> str:
        """Generate an SVG mini-graph: central concept + radial neighbours.

        Left side = prerequisites / sources (what you need first).
        Right side = dependents / targets (what this unlocks).
        Edges are coloured by semantic type with arrowheads showing direction.
        """
        from expert_anything.core.decoder import classify_relation, REL_SEMANTICS
        import math

        W, H = 540, 200
        cx, cy = W // 2, H // 2
        center_r = 38
        node_r = 28

        # Separate incoming (prerequisites / sources) and outgoing (dependents)
        incoming = []  # (name, sem, color) — concept depends on these
        outgoing = []  # (name, sem, color) — these depend on the concept
        for label, name, _cid, rtype in neighbors[:10]:
            sem = classify_relation(label or "", rtype or "")
            sem_info = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])
            color = sem_info["color"]
            if sem in ("prereq", "causes", "is_a", "part_of"):
                incoming.append((name, sem, color))
            else:
                outgoing.append((name, sem, color))

        # Balance both sides visually
        if not incoming and outgoing:
            half = max(1, len(outgoing) // 2)
            incoming = outgoing[:half]
            outgoing = outgoing[half:]
        elif not outgoing and incoming:
            half = max(1, len(incoming) // 2)
            outgoing = incoming[:half]
            incoming = incoming[half:]

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        ]

        # Arrow marker
        svg_parts.append("""
            <defs>
                <marker id="mg-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                        markerWidth="6" markerHeight="6" orient="auto">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#90A4AE"/>
                </marker>
            </defs>
        """)

        # Place nodes on left and right arcs
        def place_arc(items: list, side: str) -> list:
            n = len(items)
            if n == 0:
                return []
            result = []
            arc_r = 130
            total_angle = 100  # degrees
            start_angle = -total_angle / 2
            step = total_angle / max(n - 1, 1)
            for i, (name, sem, color) in enumerate(items):
                angle_deg = start_angle + i * step
                angle = angle_deg * math.pi / 180
                if side == "left":
                    x = cx - arc_r * math.cos(angle)
                else:
                    x = cx + arc_r * math.cos(angle)
                y = cy + arc_r * 0.7 * math.sin(angle)
                result.append((x, y, name, sem, color))
            return result

        left_nodes = place_arc(incoming, "left")
        right_nodes = place_arc(outgoing, "right")

        # Draw edges first (behind nodes)
        for nx, ny, _name, _sem, color in left_nodes:
            svg_parts.append(
                f'<line x1="{nx + node_r:.1f}" y1="{ny:.1f}" '
                f'x2="{cx - center_r:.1f}" y2="{cy:.1f}" '
                f'stroke="{color}" stroke-width="2" '
                f'stroke-linecap="round" marker-end="url(#mg-arrow)"/>'
            )

        for nx, ny, _name, _sem, color in right_nodes:
            svg_parts.append(
                f'<line x1="{cx + center_r:.1f}" y1="{cy:.1f}" '
                f'x2="{nx - node_r:.1f}" y2="{ny:.1f}" '
                f'stroke="{color}" stroke-width="2" '
                f'stroke-linecap="round" marker-end="url(#mg-arrow)"/>'
            )

        # Side labels
        if left_nodes:
            svg_parts.append(
                f'<text x="20" y="24" fill="#6B7280" font-size="10.5px" '
                f'font-family="Segoe UI, sans-serif">← {_t("minigraph_prereqs")}</text>'
            )
        if right_nodes:
            svg_parts.append(
                f'<text x="{W - 20}" y="24" fill="#6B7280" font-size="10.5px" '
                f'text-anchor="end" font-family="Segoe UI, sans-serif">'
                f"{_t('minigraph_nexts')} →</text>"
            )

        # Draw center concept (current lesson focus)
        svg_parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{center_r}" '
            f'fill="#1565C0" stroke="#0D47A1" stroke-width="3"/>'
        )
        svg_parts.append(
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" '
            f'fill="white" font-size="11" font-weight="bold" '
            f'font-family="Segoe UI, sans-serif">●</text>'
        )

        # Draw neighbour nodes
        for nx, ny, name, _sem, color in left_nodes + right_nodes:
            svg_parts.append(
                f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="{node_r}" '
                f'fill="white" stroke="{color}" stroke-width="2"/>'
            )
            max_chars = 7
            display_name = (
                name if len(name) <= max_chars else name[: max_chars - 1] + "…"
            )
            svg_parts.append(
                f'<text x="{nx:.1f}" y="{ny + 3}" text-anchor="middle" '
                f'fill="#374151" font-size="10px" font-weight="500" '
                f'font-family="Segoe UI, sans-serif">{display_name}</text>'
            )

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    # -- quick self-test ----------------------------------------------------------
    def _build_quiz_area(self) -> None:
        """Button that asks the tutor to generate a self-test."""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F3E5F5; border: 1px solid #CE93D8;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        t = QLabel(_t("quiz_title"))
        t.setStyleSheet("font-size: 14px; font-weight: bold; color: #6A1B9A;")
        lay.addWidget(t)
        hint = QLabel(_t("quiz_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 13.5px; color: #7B5A9E;")
        lay.addWidget(hint)
        self._quiz_btn = QPushButton(_t("quiz_start"))
        self._quiz_btn.setStyleSheet(
            "QPushButton { background-color: #6A1B9A; color: white; border: none;"
            "border-radius: 6px; padding: 6px 14px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #4A148C; }"
        )
        self._quiz_btn.clicked.connect(self.quiz_requested)
        lay.addWidget(self._quiz_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.layout().insertWidget(self.layout().count() - 1, card)

    def show_quiz(self, quiz: dict | None) -> None:
        """Render a generated quiz (or a hint when generation failed)."""
        if quiz is None:
            t = QLabel(_t("quiz_failed"))
            t.setStyleSheet("font-size: 14px; color: #9E9E9E; padding: 6px;")
            self.layout().insertWidget(self.layout().count() - 1, t)
            return
        qtype = quiz.get("type")
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F3E5F5; border: 2px solid #AB47BC;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        badge = QLabel(
            _t("quiz_true_false") if qtype == "true_false" else _t("quiz_ordering")
        )
        badge.setStyleSheet(
            "background-color: #AB47BC; color: white; padding: 2px 10px;"
            "border-radius: 8px; font-size: 12px; font-weight: bold;"
        )
        head.addWidget(badge)
        head.addStretch()
        lay.addLayout(head)

        q = QLabel(quiz.get("question", ""))
        q.setWordWrap(True)
        q.setStyleSheet("font-size: 15px; color: #37474F; font-weight: bold;")
        lay.addWidget(q)

        self._quiz_data = quiz
        self._quiz_answer: list[int] = []

        if qtype == "true_false":
            row = QHBoxLayout()
            row.setSpacing(8)
            for val, label in [(True, _t("quiz_true")), (False, _t("quiz_false"))]:
                b = QPushButton(label)
                b.setStyleSheet(
                    "QPushButton { background-color: white; color: #6A1B9A;"
                    "border: 1px solid #CE93D8; border-radius: 6px; padding: 6px 18px;"
                    "font-size: 14.5px; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                b.clicked.connect(lambda checked, v=val: self._check_quiz(v))
                row.addWidget(b)
            row.addStretch()
            lay.addLayout(row)
        else:
            self._quiz_order_label = QLabel("")
            self._quiz_order_label.setStyleSheet("font-size: 14px; color: #6A1B9A;")
            lay.addWidget(self._quiz_order_label)
            for i, opt in enumerate(quiz.get("options", [])):
                b = QPushButton(f"{i + 1}. {opt}")
                b.setStyleSheet(
                    "QPushButton { background-color: white; color: #37474F;"
                    "border: 1px solid #E1BEE7; border-radius: 6px; padding: 5px 10px;"
                    "font-size: 14px; text-align: left; }"
                    "QPushButton:hover { background-color: #F3E5F5; }"
                )
                b.clicked.connect(lambda checked, idx=i: self._pick_order(idx))
                lay.addWidget(b)
            check = QPushButton(_t("quiz_check"))
            check.setStyleSheet(
                "QPushButton { background-color: #6A1B9A; color: white; border: none;"
                "border-radius: 6px; padding: 5px 14px; font-size: 14px; }"
            )
            check.clicked.connect(lambda: self._check_quiz(self._quiz_answer))
            lay.addWidget(check, 0, Qt.AlignmentFlag.AlignRight)

        self.layout().insertWidget(self.layout().count() - 1, card)

    def _pick_order(self, idx: int) -> None:
        if idx not in self._quiz_answer:
            self._quiz_answer.append(idx)
        self._quiz_order_label.setText(
            " → ".join(str(i + 1) for i in self._quiz_answer)
        )

    def _check_quiz(self, answer) -> None:
        """Score locally, show result, emit quiz_result for mastery recording."""
        quiz = getattr(self, "_quiz_data", None)
        if quiz is None:
            return
        # local scoring: true_false exact; ordering fraction of correct positions
        qtype = quiz.get("type")
        if qtype == "true_false":
            ok = bool(answer) == bool(quiz.get("correct"))
            score = 1.0 if ok else 0.2
        else:
            correct = quiz.get("correct_order", [])
            if len(answer) != len(correct):
                score = 0.0
            else:
                hits = sum(1 for a, c in zip(answer, correct) if a == c)
                score = round(hits / len(correct), 2)

        result = QFrame()
        result.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border-left: 4px solid #2E7D32;"
            "border-radius: 6px; }"
        )
        rl = QVBoxLayout(result)
        rl.setContentsMargins(10, 8, 10, 8)
        rl.setSpacing(4)
        head = QHBoxLayout()
        verdict = _t("quiz_correct") if score >= 0.6 else _t("quiz_wrong")
        v = QLabel(f"{verdict}  ({score:.0%})")
        v.setStyleSheet(
            f"color: {'#2E7D32' if score >= 0.6 else '#C62828'};"
            "font-size: 14.5px; font-weight: bold;"
        )
        head.addWidget(v)
        head.addStretch()
        rl.addLayout(head)
        if qtype == "ordering" and quiz.get("correct_order"):
            right = " → ".join(str(i + 1) for i in quiz["correct_order"])
            rl.addWidget(QLabel(f"{_t('quiz_correct_order')}: {right}"))
        expl = quiz.get("explanation", "")
        if expl:
            e = QLabel(expl)
            e.setWordWrap(True)
            e.setStyleSheet("font-size: 14px; color: #37474F;")
            rl.addWidget(e)
        self.layout().insertWidget(self.layout().count() - 1, result)
        self.quiz_result.emit(float(score))

    # -- hands-on practice -------------------------------------------------------
    def _build_practice_area(self) -> None:
        """Button that asks the tutor to generate a hands-on task."""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border: 1px solid #A5D6A7;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        t = QLabel(_t("practice_title"))
        t.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E7D32;")
        lay.addWidget(t)
        hint = QLabel(_t("practice_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 13.5px; color: #558B2F;")
        lay.addWidget(hint)
        self._practice_btn = QPushButton(_t("practice_start"))
        self._practice_btn.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; border: none;"
            "border-radius: 6px; padding: 6px 14px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1B5E20; }"
        )
        self._practice_btn.clicked.connect(self.practice_requested)
        lay.addWidget(self._practice_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.layout().insertWidget(self.layout().count() - 1, card)

    def show_practice(self, task: dict | None) -> None:
        """Render the hands-on task with an answer box."""
        if task is None:
            t = QLabel(_t("practice_failed"))
            t.setStyleSheet("font-size: 14px; color: #9E9E9E; padding: 6px;")
            self.layout().insertWidget(self.layout().count() - 1, t)
            return
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border: 2px solid #66BB6A;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        badge = QLabel(_t("practice_badge"))
        badge.setStyleSheet(
            "background-color: #2E7D32; color: white; padding: 2px 10px;"
            "border-radius: 8px; font-size: 12px; font-weight: bold;"
        )
        lay.addWidget(badge)

        tk = QLabel(task.get("task", ""))
        tk.setWordWrap(True)
        tk.setStyleSheet("font-size: 15px; color: #1B5E20; font-weight: bold;")
        lay.addWidget(tk)

        hint = task.get("hint", "")
        if hint:
            h = QLabel(f"{_t('practice_hint_label')} {hint}")
            h.setWordWrap(True)
            h.setStyleSheet("font-size: 13.5px; color: #558B2F; font-style: italic;")
            lay.addWidget(h)

        self._practice_answer = QTextEdit()
        self._practice_answer.setPlaceholderText(_t("practice_answer_ph"))
        self._practice_answer.setMinimumHeight(90)
        self._practice_answer.setStyleSheet(
            "QTextEdit { border: 1px solid #A5D6A7; border-radius: 6px;"
            "padding: 8px; font-size: 14.5px; background-color: white; }"
        )
        lay.addWidget(self._practice_answer)

        submit = QPushButton(_t("practice_submit"))
        submit.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; border: none;"
            "border-radius: 6px; padding: 6px 16px; font-size: 14.5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1B5E20; }"
        )
        submit.clicked.connect(
            lambda: self.practice_submit.emit(self._practice_answer.toPlainText())
        )
        lay.addWidget(submit, 0, Qt.AlignmentFlag.AlignRight)

        self._practice_data = task
        self.layout().insertWidget(self.layout().count() - 1, card)

    def show_practice_result(self, result: dict) -> None:
        """Verdict card for a practice submission (score/feedback/reference)."""
        score = float(result.get("score", 0.0))
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #E8F5E9; border-left: 4px solid #2E7D32;"
            "border-radius: 6px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        verdict = _t("quiz_correct") if score >= 0.6 else _t("quiz_wrong")
        v = QLabel(f"{verdict}  ({score:.0%})")
        v.setStyleSheet(
            f"color: {'#2E7D32' if score >= 0.6 else '#C62828'};"
            "font-size: 14.5px; font-weight: bold;"
        )
        lay.addWidget(v)
        fb = result.get("feedback", "")
        if fb:
            f = QLabel(fb)
            f.setWordWrap(True)
            f.setStyleSheet("font-size: 14px; color: #37474F;")
            lay.addWidget(f)
        ref = result.get("reference", "")
        if ref:
            rt = QLabel(_t("eval_reference"))
            rt.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #2E7D32; margin-top: 2px;"
            )
            lay.addWidget(rt)
            r = QLabel(ref)
            r.setWordWrap(True)
            r.setStyleSheet(
                "font-size: 14px; color: #37474F; background-color: #F1F8E9;"
                "border-radius: 6px; padding: 8px;"
            )
            lay.addWidget(r)
        self.layout().insertWidget(self.layout().count() - 1, card)

    # -- follow-up conversation -------------------------------------------------
    def _build_followup(self) -> None:
        """Question box below the practice card -> grounded Q&A."""
        self._lesson = None
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F5F5F5; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        t = QLabel(_t("followup_title"))
        t.setStyleSheet("font-size: 14px; font-weight: bold; color: #37474F;")
        lay.addWidget(t)

        self._followup_input = QTextEdit()
        self._followup_input.setPlaceholderText(_t("followup_placeholder"))
        self._followup_input.setMaximumHeight(64)
        self._followup_input.setStyleSheet(
            "QTextEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
            "padding: 6px; font-size: 14.5px; background-color: white; }"
        )
        lay.addWidget(self._followup_input)

        ask_btn = QPushButton(_t("ask"))
        ask_btn.setStyleSheet(
            "QPushButton { background-color: #0284C7; color: white; border: none;"
            "border-radius: 6px; padding: 7px 18px; font-size: 14.5px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0369A1; }"
        )
        ask_btn.clicked.connect(self._ask)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(ask_btn)
        lay.addLayout(btn_row)

        self.layout().insertWidget(self.layout().count() - 1, card)

    def _ask(self) -> None:
        q = self._followup_input.toPlainText().strip()
        if not q:
            return
        self._followup_input.clear()
        self.followup_requested.emit(q)

    def append_exchange(self, question: str, answer: str) -> None:
        """Append a Q&A bubble pair to the conversation."""
        root = self.layout()
        q_lbl = QLabel(question)
        q_lbl.setWordWrap(True)
        q_lbl.setStyleSheet(
            "background-color: #E1F5FE; color: #01579B; border-radius: 8px;"
            "padding: 8px 10px; font-size: 14.5px;"
        )
        a_lbl = QLabel(answer)
        a_lbl.setWordWrap(True)
        a_lbl.setStyleSheet(
            "background-color: #F5F5F5; color: #37474F; border-radius: 8px;"
            "padding: 8px 10px; font-size: 14.5px;"
        )
        q_row = QHBoxLayout()
        q_row.addStretch()
        q_row.addWidget(q_lbl, 3)
        root.insertLayout(root.count() - 1, q_row)
        a_row = QHBoxLayout()
        a_row.addWidget(a_lbl, 3)
        a_row.addStretch()
        root.insertLayout(root.count() - 1, a_row)


# --------------------------------------------------------------------------- #
# TrendChartView
# --------------------------------------------------------------------------- #
