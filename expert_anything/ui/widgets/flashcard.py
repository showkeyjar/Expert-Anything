"""Flashcard review dialog — spaced repetition cards for due concepts.

A lightweight, high-speed review surface: each card shows the concept name
(front), then flips to reveal the definition + first evidence (back). The
learner self-rates (✓ knew it / ~ half / ✗ forgot), and the score feeds
back into record_evaluation just like a quiz, keeping the learning loop
closed — no "reviewed but not measured" gap.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.i18n import t as _t
from expert_anything.core.learner import normalize, record_evaluation


class FlashCardDialog(QDialog):
    """A swipe-style flashcard deck for due-for-review concepts.

    Each card has two faces:
    - Front: concept name + mastery badge.
    - Back: definition + first evidence snippet.

    Self-rating buttons record an evaluation that feeds the same mastery
    smoothing as quizzes, so review outcome flows into the learning loop.
    """

    def __init__(self, concepts: list[dict], asset, learner_state: dict, parent=None):
        super().__init__(parent)
        self._concepts = concepts
        self._asset = asset
        self._learner = learner_state
        self._index = 0
        self._revealed = False
        self._scores: list[tuple[str, float]] = []

        self.setWindowTitle(_t("flashcard_title"))
        self.setModal(True)
        self.setMinimumSize(480, 380)
        self.setStyleSheet(
            "QDialog { background-color: #FAFAFA; }"
            "QLabel { color: #1F2933; }"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 20, 24, 20)
        self._layout.setSpacing(12)

        self._progress = QLabel()
        self._progress.setStyleSheet("font-size: 13px; color: #78909C;")
        self._layout.addWidget(self._progress)

        self._card_area = QVBoxLayout()
        self._card_area.setSpacing(10)
        self._layout.addLayout(self._card_area, 1)

        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(10)
        self._layout.addLayout(self._btn_row)

        self._render_card()

    def _render_card(self):
        self._clear_layout(self._card_area)
        self._clear_layout(self._btn_row)
        self._revealed = False

        if self._index >= len(self._concepts):
            self._render_summary()
            return

        item = self._concepts[self._index]
        name = item["name"]
        mastery = float(item.get("mastery", 0.0))

        self._progress.setText(
            _t("flashcard_progress", n=self._index + 1, total=len(self._concepts))
        )

        # Front face: concept name + mastery
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: white; border: 2px solid #E0E0E0;"
            "border-radius: 14px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 20, 20, 20)
        card_lay.setSpacing(10)

        hint = QLabel("📋 " + _t("flashcard_front_hint"))
        hint.setStyleSheet("font-size: 12px; color: #BDBDBD;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(hint)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size: 22px; font-weight: bold; color: #0c3d5f;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        card_lay.addWidget(name_lbl)

        m_badge = QLabel(f"{mastery:.0%}")
        m_badge.setStyleSheet(
            f"background-color: {_mastery_bg(mastery)}; color: white;"
            "padding: 3px 12px; border-radius: 10px; font-size: 12px; font-weight: bold;"
        )
        m_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(m_badge)

        self._card_area.addWidget(card)

        # Reveal button
        reveal_btn = QPushButton("👁  " + _t("flashcard_reveal"))
        reveal_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 8px; padding: 10px 24px; font-size: 15px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        reveal_btn.clicked.connect(self._reveal)
        self._btn_row.addWidget(reveal_btn)
        self._btn_row.addStretch()

        skip_btn = QPushButton(_t("flashcard_skip"))
        skip_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #9E9E9E;"
            "border: 1px solid #E0E0E0; border-radius: 8px; padding: 10px 16px;"
            "font-size: 13px; }"
            "QPushButton:hover { background-color: #F5F5F5; }"
        )
        skip_btn.clicked.connect(self._next)
        self._btn_row.addWidget(skip_btn)

    def _reveal(self):
        self._clear_layout(self._card_area)
        self._clear_layout(self._btn_row)
        self._revealed = True

        item = self._concepts[self._index]
        name = item["name"]
        cid = item.get("id", "")

        # Find the concept in the asset for definition + evidence
        concept = None
        if self._asset and cid:
            concept = self._asset.concept_by_id(cid)
        if concept is None and self._asset:
            for c in self._asset.concepts:
                if c.name == name:
                    concept = c
                    break

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: white; border: 2px solid #1565C0;"
            "border-radius: 14px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 20, 20, 20)
        card_lay.setSpacing(10)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #0c3d5f;")
        name_lbl.setWordWrap(True)
        card_lay.addWidget(name_lbl)

        if concept and (concept.definition or concept.summary):
            def_lbl = QLabel(concept.definition or concept.summary)
            def_lbl.setStyleSheet("font-size: 14px; color: #37474F;")
            def_lbl.setWordWrap(True)
            card_lay.addWidget(def_lbl)

        if concept and concept.evidence:
            ev_lbl = QLabel(
                "📖 " + concept.evidence[0][:200]
                + ("…" if len(concept.evidence[0]) > 200 else "")
            )
            ev_lbl.setStyleSheet(
                "font-size: 12.5px; color: #546E7A; background-color: #F0F8F0;"
                "border-radius: 6px; padding: 8px;"
            )
            ev_lbl.setWordWrap(True)
            card_lay.addWidget(ev_lbl)

        if concept is None:
            no_info = QLabel(_t("flashcard_no_info"))
            no_info.setStyleSheet("font-size: 13px; color: #BDBDBD;")
            card_lay.addWidget(no_info)

        self._card_area.addWidget(card)

        # Self-rate buttons
        rate_hint = QLabel("📊 " + _t("flashcard_rate_hint"))
        rate_hint.setStyleSheet("font-size: 13px; color: #78909C;")
        rate_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_row.addWidget(rate_hint)

        for score, label_key, color, emoji in [
            (0.9, "flashcard_knew", "#2E7D32", "✓"),
            (0.5, "flashcard_half", "#F57C00", "~"),
            (0.1, "flashcard_forgot", "#C62828", "✗"),
        ]:
            btn = QPushButton(f"{emoji}  {_t(label_key)}")
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; color: white; border: none;"
                "border-radius: 8px; padding: 10px 20px; font-size: 14px; font-weight: bold; }"
                f"QPushButton:hover {{ background-color: {color}CC; }}"
            )
            btn.clicked.connect(lambda checked, n=name, s=score: self._rate(n, s))
            self._btn_row.addWidget(btn)

    def _rate(self, concept_name: str, score: float):
        self._scores.append((concept_name, score))
        self._next()

    def _next(self):
        self._index += 1
        self._render_card()

    def _render_summary(self):
        self._clear_layout(self._card_area)
        self._clear_layout(self._btn_row)

        total = len(self._concepts)
        rated = len(self._scores)
        known = sum(1 for _, s in self._scores if s >= 0.9)
        forgot = sum(1 for _, s in self._scores if s <= 0.1)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: white; border: 2px solid #2E7D32;"
            "border-radius: 14px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(24, 24, 24, 24)
        card_lay.setSpacing(12)

        title = QLabel("✅ " + _t("flashcard_done"))
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2E7D32;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_lay.addWidget(title)

        stats = QLabel(
            _t("flashcard_summary", total=total, rated=rated, known=known, forgot=forgot)
        )
        stats.setStyleSheet("font-size: 15px; color: #37474F;")
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stats.setWordWrap(True)
        card_lay.addWidget(stats)

        self._card_area.addWidget(card)
        self._progress.setText("")

        close_btn = QPushButton(_t("flashcard_close"))
        close_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white; border: none;"
            "border-radius: 8px; padding: 10px 24px; font-size: 15px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        close_btn.clicked.connect(self.accept)
        self._btn_row.addStretch()
        self._btn_row.addWidget(close_btn)
        self._btn_row.addStretch()

    @staticmethod
    def _clear_layout(lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()


def _mastery_bg(m: float) -> str:
    if m >= 0.6:
        return "#2E7D32"
    elif m >= 0.3:
        return "#F57C00"
    else:
        return "#C62828"
