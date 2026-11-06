"""术语对照表对话框 — 领域术语总表（确定性，无 LLM）。

渲染 ``core.terminology.glossary``（按章节分组）与 ``stats`` 覆盖数字。
每一行都来自已注册的领域模板，未登记的术语不会被推断（来源约束）。
命中**当前资产**概念的术语行带一个 ▶ 跳转按钮，信号
``concept_jump_requested(asset_concept_id)`` 交给上层打开概念详情。

**原文覆盖维度**（``core.terminology.terms_for_text``）：对当前资产原文做
一次注册拼写匹配，每行标注「原文出现 / 原文未出现」，未出现行降为灰字
（模板条目，仅供参考）——术语表从静态字典变成这份资产的词汇覆盖图。
无原文或未检出领域时不标注（保持旧行为）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.i18n import t
from expert_anything.core.terminology import glossary, stats, terms_for_text
from expert_anything.core.domain_templates import (
    build_concept_mapping,
    detect_domain_from_title,
    get_domain_template,
)


class GlossaryDialog(QDialog):
    """Modal domain term table (缩写 ↔ 全称 ↔ 定义)."""

    concept_jump_requested = Signal(str)  # asset concept id

    def __init__(self, asset, parent=None):
        super().__init__(parent)
        self._asset = asset
        self.setObjectName("glossary_dialog")
        self.setWindowTitle(t("glossary_title"))
        self.resize(640, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        domain = detect_domain_from_title(getattr(asset, "title", "")) or ""
        template = get_domain_template(domain) if domain else None
        self._groups = glossary(domain) if domain else {}
        info = stats(domain) if domain else {"term_count": 0, "chapter_count": 0}

        # Occurrence pass over the asset's own source text: which registered
        # terms actually appear verbatim (terms_for_text).  None → detection
        # unavailable (no domain / no source) and rows render without badges.
        occurred: set[str] | None = None
        source = getattr(asset, "source_text", "") or ""
        if domain and source.strip():
            try:
                occurred = {tm.id for tm in terms_for_text(source, domain)}
            except Exception:
                occurred = None

        # Mapping template term id -> asset concept id, so a term that is
        # actually present in this asset can jump straight to it.  Terms the
        # asset never mentions stay informational (no invented link).
        mapping: dict[str, str] = {}
        if template is not None:
            try:
                mapping = build_concept_mapping(asset, template).get("mapping", {}) or {}
            except Exception:
                mapping = {}

        title = QLabel(t("glossary_title"))
        title.setStyleSheet("font-size: 17px; font-weight: bold; color: #1F2933;")
        layout.addWidget(title)

        if info.get("term_count"):
            count_lbl = QLabel(
                t(
                    "terminology_count",
                    count=info.get("term_count", 0),
                    chapters=info.get("chapter_count", 0),
                )
            )
            count_lbl.setStyleSheet("font-size: 13.5px; color: #1565C0;")
            layout.addWidget(count_lbl)

        if occurred is not None and info.get("term_count"):
            occ_summary = QLabel(
                t(
                    "glossary_occ_summary",
                    hit=len(occurred),
                    total=info.get("term_count", 0),
                )
            )
            occ_summary.setObjectName("glossary_occ_summary")
            occ_summary.setStyleSheet("font-size: 12.5px; color: #00695C;")
            layout.addWidget(occ_summary)

        note = QLabel(t("terminology_source_note"))
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12.5px; color: #9E9E9E;")
        layout.addWidget(note)

        if not self._groups:
            empty = QLabel(t("glossary_empty"))
            empty.setWordWrap(True)
            empty.setStyleSheet("font-size: 14px; color: #6B7A90; padding: 24px 4px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty, 1)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #E0E0E0; border-radius: 8px;"
            "background-color: #FAFAFA; }"
        )
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(12, 10, 12, 10)
        body_lay.setSpacing(8)

        for chapter in self._groups:
            rows = self._groups.get(chapter) or []
            if not rows:
                continue
            if chapter:
                ch_lbl = QLabel(chapter)
                ch_lbl.setStyleSheet(
                    "font-size: 14.5px; font-weight: bold; color: #0c4a6e;"
                    "padding-top: 6px;"
                )
                body_lay.addWidget(ch_lbl)
            for row in rows:
                row_occ = None if occurred is None else row.get("id", "") in occurred
                body_lay.addWidget(
                    self._build_row(row, mapping.get(row.get("id", ""), ""), row_occ)
                )

        body_lay.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        close_btn = QPushButton(t("flashcard_close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

    def _build_row(self, row: dict, jump_cid: str, occurred: bool | None = None) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(12, 8, 10, 8)
        outer.setSpacing(8)

        col = QVBoxLayout()
        col.setSpacing(3)

        name_lbl = QLabel(str(row.get("term", "")))
        name_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #1F2933;")
        if occurred is False:
            # Template entry this asset never mentions: dim the whole row so
            # the reader's eye goes to the vocabulary this book actually uses.
            name_lbl.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #9E9E9E;"
            )
        col.addWidget(name_lbl)

        if occurred is not None:
            occ_key = "glossary_occ_yes" if occurred else "glossary_occ_no"
            occ_lbl = QLabel(t(occ_key))
            occ_lbl.setObjectName("glossary_occ_chip")
            occ_lbl.setToolTip(t(occ_key + "_tip"))
            if occurred:
                occ_lbl.setStyleSheet(
                    "font-size: 11.5px; color: #00695C; background-color: #E0F2F1;"
                    "border-radius: 6px; padding: 0 6px;"
                )
            else:
                occ_lbl.setStyleSheet(
                    "font-size: 11.5px; color: #9E9E9E; background-color: #F5F5F5;"
                    "border-radius: 6px; padding: 0 6px;"
                )
            col.addWidget(occ_lbl, 0, Qt.AlignmentFlag.AlignLeft)

        aliases = [a for a in (row.get("aliases") or []) if a]
        if aliases:
            alias_lbl = QLabel(" · ".join(aliases))
            alias_lbl.setWordWrap(True)
            alias_lbl.setStyleSheet(
                "font-size: 12.5px; color: #00695C; background-color: #E0F2F1;"
                "border-radius: 6px; padding: 1px 6px;"
            )
            alias_lbl.setMaximumWidth(560)
            col.addWidget(alias_lbl, 0, Qt.AlignmentFlag.AlignLeft)

        definition = str(row.get("definition", "") or "")
        if definition:
            def_lbl = QLabel(definition)
            def_lbl.setWordWrap(True)
            def_lbl.setStyleSheet("font-size: 13.5px; color: #455A64;")
            col.addWidget(def_lbl)

        points = [p for p in (row.get("key_points") or []) if p]
        if points:
            pt_lbl = QLabel(" · ".join(points))
            pt_lbl.setWordWrap(True)
            pt_lbl.setStyleSheet("font-size: 12.5px; color: #8D6E63;")
            col.addWidget(pt_lbl)

        outer.addLayout(col, 1)

        if jump_cid:
            jump = QPushButton("▶")
            jump.setToolTip(t("glossary_jump_tip"))
            jump.setFixedWidth(32)
            jump.setCursor(Qt.CursorShape.PointingHandCursor)
            jump.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #B0C4D8; border-radius: 6px;"
                "padding: 2px 4px; font-size: 13px; }"
                "QPushButton:hover { background-color: #E8F0F8; }"
            )
            jump.clicked.connect(
                lambda checked=False, cid=jump_cid: self.concept_jump_requested.emit(cid)
            )
            outer.addWidget(jump, 0, Qt.AlignmentFlag.AlignTop)
        return frame
