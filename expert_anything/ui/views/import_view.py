"""Import view: file selection, paste area, extraction pipeline."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from expert_anything.core import config
from expert_anything.core import parsers
from expert_anything.core.domain_templates import (
    apply_domain_template,
    build_concept_mapping,
    detect_domain_from_title,
    get_domain_template,
)
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.learner import register_asset
from expert_anything.core.llm import LLMClient, LLMNotConfigured
from expert_anything.core.teacher import TeacherModel, build_teacher_model
from expert_anything.core.i18n import t as _t


class ExtractWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, raw: bytes, source: str, llm_client):
        super().__init__()
        self.raw = raw
        self.source = source
        self.llm_client = llm_client

    def run(self):
        try:
            # Decode bytes -> text (parsers handles pdf/epub/docx/md/txt/html).
            text = parsers.extract_from_bytes(self.raw, self.source)
            # PDF only: record per-page character offsets so SourceLocation can
            # carry a 1-based page number for the reader/report.
            page_offsets = (
                parsers.pdf_page_offsets(self.raw)
                if Path(self.source).suffix.lower() == ".pdf"
                else None
            )
            asset = extract_knowledge(
                text,
                self.source,
                llm=self.llm_client,
                page_offsets=page_offsets,
            )
            self.finished.emit(asset)
        except Exception as e:
            self.error.emit(str(e))


class TeacherWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, asset, llm_client):
        super().__init__()
        self.asset = asset
        self.llm_client = llm_client

    def run(self):
        try:
            teacher = build_teacher_model(
                self.asset,
                llm=self.llm_client,
                on_progress=lambda stage, current, total, msg: None,
            )
            self.finished.emit(teacher)
        except Exception as e:
            self.error.emit(str(e))


class ImportView(QWidget):
    """View 1 — Import knowledge assets."""

    # Signals emitted back to MainWindow
    asset_extracted = Signal(object)  # KnowledgeAsset
    teacher_built = Signal(object)  # TeacherModel
    asset_selected = Signal(str)  # asset_id
    navigate_requested = Signal(str)  # view_name

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._extract_worker = None
        self._teacher_worker = None
        self._last_error = ""
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        layout.addWidget(
            self._view_header(
                _t("import_title"),
                _t("import_subtitle2"),
            )
        )

        # Content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        # First-run path: make the product's core loop visible before asking
        # the learner to choose between file import and pasted content.
        content_layout.addWidget(self._build_guide_card())

        # File selection
        file_label = QLabel(_t("choose_file") + ":")
        file_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        content_layout.addWidget(file_label)

        self._import_fname = QLineEdit("learning-note.md")
        self._import_fname.textChanged.connect(self._update_ready)
        self._import_fname.setStyleSheet("""
            QLineEdit { padding: 8px; border: 1px solid #E0E0E0;
                        border-radius: 4px; font-size: 15px; }
        """)
        content_layout.addWidget(self._import_fname)

        # Paste area
        paste_label = QLabel(_t("paste_hint"))
        paste_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        content_layout.addWidget(paste_label)

        self._import_paste = QTextEdit()
        self._import_paste.setPlaceholderText(_t("paste_placeholder"))
        self._import_paste.textChanged.connect(self._update_ready)
        self._import_paste.setMinimumHeight(200)
        self._import_paste.setStyleSheet("""
            QTextEdit { padding: 8px; border: 1px solid #E0E0E0;
                        border-radius: 4px; font-size: 14px; }
        """)
        content_layout.addWidget(self._import_paste)

        # Buttons
        btn_layout = QHBoxLayout()

        choose_btn = QPushButton(_t("choose_file"))
        choose_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 15px; }
            QPushButton:hover { background-color: #F57C00; }
        """)
        choose_btn.clicked.connect(self._on_choose_file)
        btn_layout.addWidget(choose_btn)

        self._analysis_btn = QPushButton(_t("start_analysis"))
        self._analysis_btn.setEnabled(False)
        self._analysis_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 15px; }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:disabled { background-color: #BDBDBD; }
        """)
        self._analysis_btn.clicked.connect(self._on_generate)
        btn_layout.addWidget(self._analysis_btn)
        btn_layout.addStretch()
        content_layout.addLayout(btn_layout)

        # Progress
        self._import_progress = QProgressBar()
        self._import_progress.setMaximumHeight(20)
        self._import_progress.setRange(0, 100)
        self._import_progress.setValue(0)
        self._import_progress.setFormat("%p%")
        self._import_progress.setVisible(True)
        content_layout.addWidget(self._import_progress)

        self._import_status_label = QLabel(_t("import_status_wait"))
        self._import_status_label.setStyleSheet(
            "color: #666; font-size: 14px; margin-top: 8px;"
        )
        content_layout.addWidget(self._import_status_label)

        self._update_ready()

        # LLM status
        llm_status = (
            _t("llm_ready")
            if self._main.llm_client
            else _t("llm_not_ready_detail")
        )
        self._llm_label = QLabel(llm_status)
        self._llm_label.setWordWrap(True)
        self._llm_label.setStyleSheet(
            "color: #4CAF50; font-size: 14px; margin-top: 8px;"
            if self._main.llm_client
            else "color: #FF9800; font-size: 14px; margin-top: 8px;"
        )
        content_layout.addWidget(self._llm_label)

        layout.addWidget(content)

    def _build_guide_card(self) -> QFrame:
        """First-run guide card: a three-step walkthrough for newcomers."""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: #F7FAFF; border: 1px solid #D6E4F5;"
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(10)

        title = QLabel(_t("guide_title"))
        title.setStyleSheet("font-size: 15.5px; font-weight: bold; color: #174A7E;")
        lay.addWidget(title)

        steps = QHBoxLayout()
        steps.setSpacing(10)
        for num, title_key, desc_key in [
            (1, "guide_step1_title", "guide_step1_desc"),
            (2, "guide_step2_title", "guide_step2_desc"),
            (3, "guide_step3_title", "guide_step3_desc"),
        ]:
            steps.addWidget(self._guide_step(num, _t(title_key), _t(desc_key)), 1)
        lay.addLayout(steps)

        note = QLabel(_t("guide_note"))
        note.setWordWrap(True)
        note.setStyleSheet("color: #6B7A90; font-size: 13.5px;")
        lay.addWidget(note)

        return card

    @staticmethod
    def _guide_step(num: int, title: str, desc: str) -> QFrame:
        step = QFrame()
        step.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #D6E4F5;"
            "border-radius: 6px; }"
        )
        lay = QVBoxLayout(step)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        badge = QLabel(str(num))
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "QLabel { background-color: #1565C0; color: white;"
            "border-radius: 11px; font-size: 14px; font-weight: bold; }"
        )
        head.addWidget(badge)
        head.addWidget(QLabel(title), 1)
        lay.addLayout(head)

        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet("color: #5F6B7A; font-size: 14px; line-height: 1.4;")
        lay.addWidget(d)

        return step

    def _view_header(self, title, subtitle=""):
        header = QFrame()
        header.setStyleSheet(
            "background-color: white; border-bottom: 2px solid #1565C0;"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 7, 20, 7)
        lay.setSpacing(10)
        t = QLabel(str(title))
        t.setStyleSheet("font-size: 18px; font-weight: bold; color: #1F2933;")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(str(subtitle))
            s.setStyleSheet("color: #6B7A90; font-size: 13.5px;")
            lay.addWidget(s)
        lay.addStretch()
        return header

    def _update_ready(self):
        if not hasattr(self, "_analysis_btn"):
            return
        fname = self._import_fname.text().strip()
        has_file = bool(fname and Path(fname).exists())
        has_paste = bool(self._import_paste.toPlainText().strip())
        ready = has_file or has_paste
        busy = bool(self._extract_worker and self._extract_worker.isRunning())
        busy = busy or bool(self._teacher_worker and self._teacher_worker.isRunning())
        self._analysis_btn.setEnabled(ready and not busy)
        if not busy and self._import_progress.value() == 0:
            self._import_status_label.setText(
                _t("import_status_ready") if ready else _t("import_status_wait")
            )

    def _on_choose_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _t("choose_file"),
            str(Path(__file__).parent.parent / "data" / "samples"),
            _t("filter_supported")
            + " (*.pdf *.epub *.docx *.md *.markdown *.txt *.html *.htm);;"
            "PDF (*.pdf);;EPUB (*.epub);;Word (*.docx);;"
            "Markdown/Text (*.md *.markdown *.txt);;HTML (*.html *.htm);;All (*.*)",
        )
        if file_path:
            self._import_fname.setText(file_path)
            self._import_status_label.setText(_t("import_status_file_chosen"))

    def _is_busy(self):
        return bool(
            (self._extract_worker and self._extract_worker.isRunning())
            or (self._teacher_worker and self._teacher_worker.isRunning())
        )

    def _set_stage(self, progress, message, button_text=None):
        self._import_progress.setValue(progress)
        self._import_status_label.setText(message)
        if button_text is not None:
            self._analysis_btn.setText(button_text)
        self._import_status_label.repaint()

    @staticmethod
    def _stage_msg(cur: int, msg: str) -> str:
        """Localized "Step N of 3: …" progress message."""
        return _t("import_step_progress", cur=cur, msg=msg)

    def _on_generate(self):
        # Button disabling is not enough: keyboard activation and queued Qt
        # signals can still re-enter the slot before the first worker returns.
        if self._is_busy():
            self._analysis_btn.setEnabled(False)
            self._import_status_label.setText(_t("import_status_busy"))
            return

        fname = self._import_fname.text().strip()
        if not fname:
            return

        raw = b""
        if Path(fname).exists():
            try:
                raw = Path(fname).read_bytes()
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(self, _t("error"), _t("read_failed", e=e))
                return
        else:
            raw = self._import_paste.toPlainText().encode("utf-8")

        if not raw.strip():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, _t("error"), _t("empty_content"))
            return

        self._last_error = ""
        self._analysis_btn.setEnabled(False)
        self._set_stage(10, self._stage_msg(1, _t("import_stage_parse")), _t("analyzing"))

        self._extract_worker = ExtractWorker(raw, fname, self._main.llm_client)
        self._extract_worker.finished.connect(self._on_extraction_finished)
        self._extract_worker.error.connect(self._on_extraction_error)
        self._extract_worker.start()

    # -- domain template entry ------------------------------------------- #
    #: ``TemplateApplicationResult.reason`` values that have localized copy.
    _TEMPLATE_REASONS = (
        "degraded_no_mapping",
        "degraded_low_coverage",
        "unknown_domain",
    )

    @staticmethod
    def _template_offer(asset):
        """The domain template that could enrich ``asset``, or ``None``.

        Read-only: title-based domain detection plus a dry-run coverage
        estimate.  No LLM, no mutation — safe to compute before the learner
        decides whether to apply the template.
        """
        domain_id = detect_domain_from_title(getattr(asset, "title", "") or "")
        if not domain_id:
            return None
        template = get_domain_template(domain_id)
        if template is None:
            return None
        report = build_concept_mapping(asset, template)
        return {
            "domain_id": domain_id,
            "template_name": template.name,
            "matched_count": report["matched_count"],
            "template_concept_count": report["template_concept_count"],
            "coverage": report["coverage"],
        }

    def _offer_domain_template(self, asset):
        """Offer the detected domain template to the learner and apply it.

        Three no-op paths keep the plain import behaviour byte-for-byte: the
        title carries no domain signal, the domain ships no template, or the
        learner declines.  When confirmed, the template is applied here —
        before the asset is registered — so the learner model and every view
        snapshot pick up the enriched concepts and the domain learning path in
        a single pass.
        """
        offer = self._template_offer(asset)
        if offer is None:
            return
        answer = QMessageBox.question(
            self,
            _t("domain_template_title"),
            _t(
                "domain_template_ask",
                template=offer["template_name"],
                matched=offer["matched_count"],
                total=offer["template_concept_count"],
                pct=f"{offer['coverage']:.0%}",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = apply_domain_template(asset, offer["domain_id"])
        except Exception as exc:  # defensive: an import must always finish
            QMessageBox.warning(
                self, _t("error"), _t("domain_template_failed", e=str(exc))
            )
            return
        QMessageBox.information(
            self,
            _t("domain_template_title"),
            self._template_result_text(result),
        )

    def _template_result_text(self, result) -> str:
        """Localized summary of a ``TemplateApplicationResult``."""
        stats = {
            "template": result.template_name or result.domain_id,
            "matched": result.matched_count,
            "total": result.template_concept_count,
            "pct": f"{result.coverage:.0%}",
            "enriched": result.enriched_count,
        }
        if result.applied and result.learning_path_applied:
            return _t("domain_template_applied", **stats)
        reason = result.reason if result.reason in self._TEMPLATE_REASONS else "other"
        return _t(
            "domain_template_applied_degraded",
            reason=_t(f"domain_template_reason_{reason}"),
            **stats,
        )

    def _on_extraction_finished(self, asset):
        # Domain template first: on confirmation the asset is enriched before
        # it is registered / snapshotted, so nothing downstream sees a stale
        # concept set or learning path.
        self._offer_domain_template(asset)

        self._set_stage(80, self._stage_msg(2, _t("import_extracted_concepts", n=len(asset.concepts))), "…")

        # Register in learner
        register_asset(self._main.learner, asset)

        # Store asset data
        self._main.assets[asset.asset_id] = {
            "asset_id": asset.asset_id,
            "type": asset.type,
            "title": asset.title,
            "source_name": asset.source_name,
            "created_at": asset.created_at,
            "concepts": [c.to_dict() for c in asset.concepts],
            "relations": [r.to_dict() for r in asset.relations],
            "learning_path": asset.learning_path,
            "method": asset.method,
            # Keep the complete source in the persisted asset.  The reader
            # may render a preview, but truncating here breaks long-document
            # navigation and makes evidence locations invalid after restart.
            "source_text": asset.source_text,
        }

        self.asset_extracted.emit(asset)

        # Build teacher model
        self._set_stage(85, self._stage_msg(2, _t("import_stage_teacher")))
        self._teacher_worker = TeacherWorker(asset, self._main.llm_client)
        self._teacher_worker.finished.connect(self._on_teacher_finished)
        self._teacher_worker.error.connect(self._on_extraction_error)
        self._teacher_worker.start()

    def _on_teacher_finished(self, teacher):
        self._import_progress.setValue(95)
        self._import_status_label.setText(
            _t("selflearning_done", n=len(teacher.anomalies))
        )
        self._main.teacher_models[teacher.asset_id] = teacher.to_dict()
        self._main.current_asset_id = teacher.asset_id

        self._main.save_learner_state()
        self._main._refresh_asset_list()
        self._main._rebuild_all_views()

        self._set_stage(100, self._stage_msg(3, _t("import_done")), _t("done"))
        self._analysis_btn.setEnabled(False)

        self.teacher_built.emit(teacher)
        self.asset_selected.emit(teacher.asset_id)
        self.navigate_requested.emit("knowledge")

    def _on_extraction_error(self, error_msg):
        from PySide6.QtWidgets import QMessageBox

        self._last_error = str(error_msg).strip() or _t("unknown_error")
        self._import_progress.setValue(0)
        self._import_progress.setVisible(True)
        self._analysis_btn.setText(_t("retry"))
        self._update_ready()
        self._import_status_label.setText(_t("import_failed_state", msg=self._last_error))
        QMessageBox.critical(self, _t("error"), _t("import_failed", msg=error_msg))
