"""Import view: file selection, paste area, extraction pipeline."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)
from expert_anything.core import config
from expert_anything.core import parsers
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
                if Path(self.source).suffix.lower() == ".pdf" else None
            )
            asset = extract_knowledge(
                text, self.source, llm=self.llm_client,
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
    asset_extracted = Signal(object)   # KnowledgeAsset
    teacher_built = Signal(object)     # TeacherModel
    asset_selected = Signal(str)       # asset_id
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
        layout.addWidget(self._view_header(
            _t("import_title"),
            _t("import_subtitle2"),
        ))

        # Content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        # First-run path: make the product's core loop visible before asking
        # the learner to choose between file import and pasted content.
        self._flow_hint = QLabel("1  导入资料  →  2  生成知识地图  →  3  选择概念开始学习")
        self._flow_hint.setWordWrap(True)
        self._flow_hint.setStyleSheet(
            "background: #E8F1FF; color: #174A7E; border-radius: 6px; "
            "padding: 10px 12px; font-size: 12px; font-weight: bold;"
        )
        content_layout.addWidget(self._flow_hint)

        # File selection
        file_label = QLabel(_t("choose_file") + ":")
        file_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        content_layout.addWidget(file_label)

        self._import_fname = QLineEdit("learning-note.md")
        self._import_fname.textChanged.connect(self._update_ready)
        self._import_fname.setStyleSheet("""
            QLineEdit { padding: 8px; border: 1px solid #E0E0E0;
                        border-radius: 4px; font-size: 13px; }
        """)
        content_layout.addWidget(self._import_fname)

        # Paste area
        paste_label = QLabel(_t("paste_hint"))
        paste_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        content_layout.addWidget(paste_label)

        self._import_paste = QTextEdit()
        self._import_paste.setPlaceholderText(_t("paste_placeholder"))
        self._import_paste.textChanged.connect(self._update_ready)
        self._import_paste.setMinimumHeight(200)
        self._import_paste.setStyleSheet("""
            QTextEdit { padding: 8px; border: 1px solid #E0E0E0;
                        border-radius: 4px; font-size: 12px; }
        """)
        content_layout.addWidget(self._import_paste)

        # Buttons
        btn_layout = QHBoxLayout()

        choose_btn = QPushButton(_t("choose_file"))
        choose_btn.setStyleSheet("""
            QPushButton { background-color: #FF9800; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 13px; }
            QPushButton:hover { background-color: #F57C00; }
        """)
        choose_btn.clicked.connect(self._on_choose_file)
        btn_layout.addWidget(choose_btn)

        self._analysis_btn = QPushButton(_t("start_analysis"))
        self._analysis_btn.setEnabled(False)
        self._analysis_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; border: none;
                          border-radius: 6px; padding: 8px 16px; font-size: 13px; }
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

        self._import_status_label = QLabel("请先选择文件或粘贴学习内容")
        self._import_status_label.setStyleSheet("color: #666; font-size: 12px; margin-top: 8px;")
        content_layout.addWidget(self._import_status_label)

        self._update_ready()

        # LLM status
        llm_status = _t("llm_ready") if self._main.llm_client else (
            _t("llm_not_ready") + "；仍可导入，但知识定义、关系和教师自检会较简化。"
            "配置模型服务后重新导入可获得完整体验。"
        )
        self._llm_label = QLabel(llm_status)
        self._llm_label.setWordWrap(True)
        self._llm_label.setStyleSheet(
            "color: #4CAF50; font-size: 12px; margin-top: 8px;"
            if self._main.llm_client else
            "color: #FF9800; font-size: 12px; margin-top: 8px;"
        )
        content_layout.addWidget(self._llm_label)

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
                "已准备好，可以开始分析" if ready else "请先选择文件或粘贴学习内容"
            )

    def _on_choose_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _t("choose_file"),
            str(Path(__file__).parent.parent / "data" / "samples"),
            _t("filter_supported") +
            " (*.pdf *.epub *.docx *.md *.markdown *.txt *.html *.htm);;"
            "PDF (*.pdf);;EPUB (*.epub);;Word (*.docx);;"
            "Markdown/Text (*.md *.markdown *.txt);;HTML (*.html *.htm);;All (*.*)",
        )
        if file_path:
            self._import_fname.setText(file_path)
            self._import_status_label.setText("文件已选择，正在开始分析…")
            self._on_generate()

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

    def _on_generate(self):
        # Button disabling is not enough: keyboard activation and queued Qt
        # signals can still re-enter the slot before the first worker returns.
        if self._is_busy():
            self._analysis_btn.setEnabled(False)
            self._import_status_label.setText("分析正在进行，请等待当前任务完成")
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
        self._set_stage(10, "第 1/3 步：正在解析资料并抽取知识…", "分析中…")

        self._extract_worker = ExtractWorker(raw, fname, self._main.llm_client)
        self._extract_worker.finished.connect(self._on_extraction_finished)
        self._extract_worker.error.connect(self._on_extraction_error)
        self._extract_worker.start()

    def _on_extraction_finished(self, asset):
        self._set_stage(
            80,
            f"第 2/3 步：已抽取 {len(asset.concepts)} 个概念，正在构建教师模型…",
            "构建知识模型…",
        )

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
            "source_text": (
                asset.source_text[:5000] + "..."
                if len(asset.source_text) > 5000 else asset.source_text
            ),
        }

        self.asset_extracted.emit(asset)

        # Build teacher model
        self._set_stage(85, "第 2/3 步：正在构建教师模型并检查知识缺口…")
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

        self._set_stage(
            100,
            "第 3/3 步：分析完成。接下来可在知识地图中选择推荐概念开始学习。",
            "分析完成",
        )
        self._analysis_btn.setEnabled(False)

        self.teacher_built.emit(teacher)
        self.asset_selected.emit(teacher.asset_id)
        self.navigate_requested.emit("knowledge")

    def _on_extraction_error(self, error_msg):
        from PySide6.QtWidgets import QMessageBox
        self._last_error = str(error_msg).strip() or "未知错误"
        self._import_progress.setValue(0)
        self._import_progress.setVisible(True)
        self._analysis_btn.setText("重试分析")
        self._update_ready()
        self._import_status_label.setText(
            f"分析失败：{self._last_error}。输入内容已保留，可直接重试。"
        )
        QMessageBox.critical(self, _t("error"), _t("import_failed", msg=error_msg))
