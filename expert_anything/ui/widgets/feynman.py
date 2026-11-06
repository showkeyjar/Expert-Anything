"""复述自检对话框 — 学习者用自己的话复述，系统确定性对照覆盖度（无 LLM）。

渲染 ``core.feynman.coverage``：要点覆盖百分比 + 核心术语是否提到 +
漏掉的要点 / 可以再提到的术语。 结果一律来自概念自身证据与已登记领域术语，
不新增、不推断；无领域时按概念证据对照（术语部分自动缺省）。

入口：教学结果页 header 的 🗣 按钮、阅读页概念工具条的 🗣 按钮。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core import feynman
from expert_anything.core.i18n import t
from expert_anything.core.domain_templates import detect_domain_from_title


def _coverage_color(pct: int) -> str:
    if pct >= 80:
        return "#2E7D32"
    if pct >= 50:
        return "#E65100"
    return "#C62828"


def _resolve_asset_id(asset, concept, learner_state) -> str:
    """Real asset id for the trace — the global map asset is not a document.

    ``asset`` may be the merged global graph (``asset_id == "global"``) whose
    concept ids carry an ``<asset_id>:<concept_id>`` prefix; in that case the
    prefix (or an existing trace row) is the true source document.
    """
    aid = str(getattr(asset, "asset_id", "") or "")
    if aid and aid != "global":
        return aid
    cid = str(getattr(concept, "id", "") or "")
    if ":" in cid:
        return cid.split(":", 1)[0]
    from expert_anything.core.learner import normalize

    key = normalize(getattr(concept, "name", ""))
    for h in learner_state.get("history", []):
        if (h.get("key") or "") == key and h.get("asset_id"):
            return str(h["asset_id"])
    return ""


class FeynmanDialog(QDialog):
    """用自己的话复述 + 确定性覆盖度对照（active recall）。"""

    def __init__(self, asset, concept, learner_state, parent=None):
        super().__init__(parent)
        self._asset = asset
        self._concept = concept
        self._state = learner_state
        self._domain = detect_domain_from_title(getattr(asset, "title", "")) or ""
        self._last_result: dict | None = None
        self._recorded = False

        name = str(getattr(concept, "name", "") or "")
        self.setObjectName("feynman_dialog")
        self.setWindowTitle(t("recall_title"))
        self.resize(560, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel(t("recall_title"))
        title.setStyleSheet("font-size: 17px; font-weight: bold; color: #1F2933;")
        layout.addWidget(title)

        hint = QLabel(t("recall_hint", name=name))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 13px; color: #6B7A90;")
        layout.addWidget(hint)

        editor = QPlainTextEdit()
        editor.setObjectName("recall_editor")
        editor.setPlaceholderText(t("recall_placeholder"))
        editor.setMinimumHeight(160)
        editor.setStyleSheet("font-size: 14px;")
        from expert_anything.core.learner import get_note

        note = get_note(learner_state, name)
        if note:
            editor.setPlainText(note)
        layout.addWidget(editor)
        self._editor = editor

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._check_btn = QPushButton(t("recall_check"))
        self._check_btn.setObjectName("recall_check_btn")
        self._check_btn.setStyleSheet(
            "QPushButton { background-color: #1565C0; color: white;"
            "border: none; border-radius: 7px; padding: 6px 14px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0D47A1; }"
        )
        self._check_btn.clicked.connect(self._on_check)
        action_row.addWidget(self._check_btn)

        self._store_btn = QPushButton(t("recall_store_note"))
        self._store_btn.setObjectName("recall_store_btn")
        self._store_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #B45309;"
            "border: 1px solid #FCD34D; border-radius: 7px;"
            "padding: 5px 12px; font-size: 13px; }"
            "QPushButton:hover { background-color: #FFFBEB; }"
        )
        self._store_btn.clicked.connect(self._on_store)
        action_row.addWidget(self._store_btn)

        clear_btn = QPushButton(t("recall_clear"))
        clear_btn.clicked.connect(self._on_clear)
        action_row.addWidget(clear_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        self._result_box = QWidget()
        self._result_lay = QVBoxLayout(self._result_box)
        self._result_lay.setContentsMargins(0, 4, 0, 4)
        self._result_lay.setSpacing(6)
        layout.addWidget(self._result_box, 1)

        close_btn = QPushButton(t("flashcard_close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

    # -- actions --------------------------------------------------------------
    def _on_check(self):
        text = self._editor.toPlainText()
        if not text.strip():
            self._render_message(t("recall_empty"))
            return
        result = feynman.coverage(text, self._concept, self._domain)
        self._last_result = result
        self._recorded = False
        self._render_result(result)

    def _on_record(self) -> None:
        """Write this self-explanation into the learning trace (mastery).

        Active recall is first-hand evidence of understanding, so it must feed
        the learning loop (record_evaluation → mastery / teacher signals)
        instead of dying inside this dialog.  ``channel="recall"`` keeps
        teaching-side aggregators from mistaking coverage for a style result.
        """
        from expert_anything.core.learner import (
            RECALL_CHANNEL,
            record_evaluation,
            save as save_learner,
        )

        if self._recorded or not self._last_result:
            return
        name = str(getattr(self._concept, "name", "") or "")
        asset_id = _resolve_asset_id(self._asset, self._concept, self._state)
        if not name or not asset_id:
            return
        result = self._last_result
        pct = int(round(float(result.get("coverage", 0.0)) * 100))
        feedback = t(
            "recall_coverage",
            pct=pct,
            covered=int(result.get("covered_count", 0)),
            total=int(result.get("point_count", 0)),
        )
        record_evaluation(
            self._state,
            name,
            asset_id,
            float(result.get("coverage", 0.0)),
            self._editor.toPlainText(),
            feedback,
            meta={"channel": RECALL_CHANNEL},
        )
        save_learner(self._state)
        self._recorded = True
        btn = self.findChild(QPushButton, "recall_record_btn")
        if btn is not None:
            btn.setText(t("recall_recorded"))
            btn.setEnabled(False)

    def _on_store(self):
        name = str(getattr(self._concept, "name", "") or "")
        if not name:
            return
        from expert_anything.core.learner import save as save_learner, set_note

        set_note(self._state, name, self._editor.toPlainText())
        save_learner(self._state)
        self._store_btn.setText(t("note_edit_has"))

    def _on_clear(self):
        self._editor.clear()
        self._clear_results()

    # -- rendering ------------------------------------------------------------
    def _clear_results(self):
        while self._result_lay.count():
            item = self._result_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_message(self, text: str):
        self._clear_results()
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 13.5px; color: #6B7A90;")
        self._result_lay.addWidget(lbl)

    def _render_result(self, result: dict):
        self._clear_results()
        pct = int(round(float(result.get("coverage", 0.0)) * 100))
        covered = int(result.get("covered_count", 0))
        total = int(result.get("point_count", 0))
        color = _coverage_color(pct)

        head = QFrame()
        head.setStyleSheet(
            f"QFrame {{ background-color: {color}14; border: 1px solid {color}55;"
            "border-radius: 8px; }"
        )
        head_lay = QVBoxLayout(head)
        head_lay.setContentsMargins(12, 8, 12, 8)
        head_lay.setSpacing(5)

        cov_lbl = QLabel(
            t("recall_coverage", pct=pct, covered=covered, total=total)
        )
        cov_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {color};"
        )
        head_lay.addWidget(cov_lbl)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(pct)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(
            "QProgressBar { background-color: #ECEFF1; border: none;"
            "border-radius: 4px; }"
            f"QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}"
        )
        head_lay.addWidget(bar)

        self_name = str(result.get("self_name", "") or "")
        if self_name:
            if result.get("self_mentioned"):
                self_lbl = QLabel(t("recall_self_ok", name=self_name))
                self_lbl.setStyleSheet("font-size: 13px; color: #2E7D32;")
            else:
                self_lbl = QLabel(t("recall_self_missing", name=self_name))
                self_lbl.setStyleSheet("font-size: 13px; color: #C62828;")
            self_lbl.setWordWrap(True)
            head_lay.addWidget(self_lbl)
        self._result_lay.addWidget(head)

        # Record the self-explanation into the learning trace.  Coverage is
        # real evidence of understanding, so it feeds mastery — but only on
        # explicit consent (repeated checks must not inflate the score).
        record_btn = QPushButton(
            t("recall_recorded") if self._recorded else t("recall_record")
        )
        record_btn.setObjectName("recall_record_btn")
        record_btn.setEnabled(not self._recorded)
        record_btn.setToolTip(t("recall_record_tip"))
        record_btn.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white;"
            "border: none; border-radius: 7px; padding: 6px 14px; font-size: 13.5px; }"
            "QPushButton:hover { background-color: #1B5E20; }"
            "QPushButton:disabled { background-color: #E8F5E9; color: #2E7D32; }"
        )
        record_btn.clicked.connect(self._on_record)
        self._result_lay.addWidget(record_btn)

        if total and pct >= 100:
            done = QLabel(t("recall_all_covered"))
            done.setWordWrap(True)
            done.setStyleSheet(
                "font-size: 13.5px; font-weight: bold; color: #2E7D32;"
            )
            self._result_lay.addWidget(done)

        missed_points = [p for p in (result.get("missed_points") or []) if p]
        if missed_points:
            self._result_lay.addWidget(
                self._section(
                    t("recall_missed_points"),
                    [f"• {p}" for p in missed_points],
                    "#C62828",
                    "#FFEBEE",
                )
            )

        matched = result.get("matched_terms") or []
        if matched:
            names = " · ".join(str(m.get("name", "")) for m in matched if m.get("name"))
            if names:
                self._result_lay.addWidget(
                    self._section(t("terminology_related"), [names], "#00695C", "#E0F2F1")
                )

        missed_terms = result.get("missed_terms") or []
        if missed_terms:
            names = " · ".join(
                str(m.get("name", "")) for m in missed_terms if m.get("name")
            )
            if names:
                self._result_lay.addWidget(
                    self._section(
                        t("recall_missed_terms"), [names], "#6A1B9A", "#F3E5F5"
                    )
                )

        self._result_lay.addStretch()

    def _section(self, title: str, lines: list[str], color: str, bg: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {color}33;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"font-size: 13.5px; font-weight: bold; color: {color};")
        lay.addWidget(t_lbl)
        for line in lines:
            body = QLabel(line)
            body.setWordWrap(True)
            body.setStyleSheet("font-size: 13px; color: #455A64;")
            lay.addWidget(body)
        return frame
