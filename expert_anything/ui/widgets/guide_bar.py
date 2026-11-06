"""GuideBar — the persistent proactive主张 strip (AGENTS.md §49).

Why this exists
---------------
The system already ranks what to study (``core/coach.py``), but the result used
to land in a one-line toast inside the teach view: invisible from anywhere else,
overwritten by the next render, and gone the moment the learner navigated away.
The learner therefore saw a dashboard of parallel cards and had to decide alone.

The guide bar gives the coach a permanent voice: it states the single next move,
says *why* in plain language, and offers one-click action — from every view.

Design rules
------------
- Passive by default: nothing auto-starts. The learner always presses the button.
- Silent on failure: any exception hides the bar rather than breaking the shell.
- Review semantics preserved: when the coach says "review", the action routes to
  the review entry point (``review=True``), never to a first-time lesson.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from expert_anything.core.i18n import t as _t
from expert_anything.ui import theme


class GuideBar(QWidget):
    """One主张 + one reason + one primary action, always visible.

    Signals
    -------
    start_requested(dict): the learner accepted the current主张.
    swap_requested(): the learner wants the runner-up instead.
    """

    start_requested = Signal(dict)
    swap_requested = Signal(dict)  # the claim that was declined
    dismiss_requested = Signal(dict)  # the learner explicitly passed on this

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rec: dict | None = None
        self._alternatives: list[dict] = []
        self._alt_index = 0
        self.setObjectName("guide_bar")
        self.setStyleSheet(
            f"#guide_bar {{ background-color: #F8FAFF;"
            f" border-bottom: 1px solid {theme.DIVIDER}; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 6, 16, 6)
        lay.setSpacing(10)

        self._now_lbl = QLabel()
        self._now_lbl.setStyleSheet(
            f"color: {theme.ACCENT_HOVER}; font-size: 11px; font-weight: 600;"
            f"background-color: {theme.ACCENT_TINT}; border-radius: 6px;"
            " padding: 2px 8px;"
        )
        lay.addWidget(self._now_lbl)

        self._text_lbl = QLabel()
        self._text_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px;"
        )
        self._text_lbl.setWordWrap(False)
        lay.addWidget(self._text_lbl, 1)

        self._go_btn = QPushButton()
        self._go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._go_btn.setStyleSheet(theme.primary_button_style(compact=True))
        self._go_btn.clicked.connect(self._emit_start)
        lay.addWidget(self._go_btn)

        self._swap_btn = QPushButton()
        self._swap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swap_btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.ACCENT}; border: none; padding: 6px 8px;"
            " font-size: 12.5px; }"
            f"QPushButton:hover {{ color: {theme.ACCENT_HOVER};"
            f" text-decoration: underline; }}"
        )
        self._swap_btn.clicked.connect(self._emit_swap)
        lay.addWidget(self._swap_btn)

        # Declining must be as cheap as accepting; without this the only
        # reaction the coach can ever observe is agreement.
        self._dismiss_btn = QPushButton()
        self._dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss_btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_FAINT}; border: none; padding: 6px 8px;"
            " font-size: 12.5px; }"
            f"QPushButton:hover {{ color: {theme.TEXT_MUTED}; }}"
        )
        self._dismiss_btn.clicked.connect(self._emit_dismiss)
        lay.addWidget(self._dismiss_btn)

        self.setVisible(False)

    # -- public API ----------------------------------------------------------

    def set_recommendation(self, rec: dict | None) -> None:
        """Render one主张. ``None`` or an unusable主张 hides the bar."""
        try:
            if not rec or not isinstance(rec, dict):
                self.setVisible(False)
                self._rec = None
                return
            if not rec.get("concept_name") and rec.get("kind") not in (
                "import",
                "explore",
            ):
                # Nothing actionable (e.g. a queue-empty edge case): stay hidden
                # rather than showing an empty instruction.  Asset-level kinds
                # ("import": nothing imported yet; "explore": everything
                # mastered) carry no concept name but are still actionable —
                # the coach may lower its voice, never disappear (§49).
                self.setVisible(False)
                self._rec = None
                return

            self._rec = rec
            self._alternatives = list(rec.get("alternatives") or [])
            self._alt_index = 0

            self._now_lbl.setText(_t("coach_now"))
            self._text_lbl.setText(self._describe(rec))
            self._text_lbl.setToolTip(self._describe(rec))
            self._go_btn.setText(_t("coach_go"))
            # render-time lookup so a language switch re-localises the label
            self._swap_btn.setText(_t("coach_swap"))
            self._dismiss_btn.setText(_t("coach_dismiss"))
            self._dismiss_btn.setToolTip(_t("coach_dismiss_tip"))

            has_swap = bool(self._alternatives)
            self._swap_btn.setVisible(has_swap)
            self.setVisible(True)
        except Exception:
            self.setVisible(False)

    def current(self) -> dict | None:
        """The主张 currently displayed (for tests and the shell)."""
        return self._rec

    # -- internals -----------------------------------------------------------

    def _describe(self, rec: dict) -> str:
        """Human sentence: concept name + localised reason (+ fatigue note).

        When a kind of advice has been skipped repeatedly the coach says so
        inline: a lowered voice must be explained, otherwise the change looks
        arbitrary (design intent §49 — guidance is explainable or it is noise).
        """
        args = dict(rec.get("why_args") or {})
        # The count stays in the main sentence; the concrete names are appended
        # as an example so the claim is verifiable, not just impressive.
        names = args.pop("names", "")
        why = _t(rec.get("why_key") or "", **args)
        name = rec.get("concept_name") or ""
        text = f"{name} — {why}" if name else why
        if names:
            text = f"{text}{_t('coach_unlocks_names', names=names)}"

        note = rec.get("fatigue_note") or {}
        try:
            n = int(note.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            text = f"{text}  {_t('coach_fatigue_note', n=n)}"
        return text

    def _emit_start(self) -> None:
        if self._rec:
            self.start_requested.emit(self._rec)

    def _emit_dismiss(self) -> None:
        """The learner passed on this claim without accepting or swapping."""
        if self._rec:
            self.dismiss_requested.emit(dict(self._rec))

    def _emit_swap(self) -> None:
        """Advance to the next runner-up主张 (no recomputation)."""
        try:
            if not self._alternatives:
                return
            rec = self._alternatives[self._alt_index % len(self._alternatives)]
            self._alt_index += 1
            # keep the remaining runner-ups reachable by pressing again
            rest = [a for a in self._alternatives if a is not rec]
            new_rec = dict(rec)
            new_rec["alternatives"] = rest
            # report the claim being declined, not the one we moved to: the
            # feedback log is about what the learner rejected
            self.swap_requested.emit(dict(self._rec or {}))
            self.set_recommendation(new_rec)
        except Exception:
            pass
