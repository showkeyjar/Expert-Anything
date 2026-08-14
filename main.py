"""ExpertAnything desktop application (PySide6).

Personal Learning OS: knowledge assets -> knowledge model -> learning loop.
Built on the ExpertAnything core engine (expert_anything/core).
"""
import json
import math
import os
import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QStackedWidget,
    QTextEdit, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QProgressBar, QLineEdit, QTabWidget, QComboBox, QSplitter,
    QTableWidget, QTableWidgetItem,
    QGroupBox, QFormLayout, QCheckBox, QTextBrowser,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsLineItem,
    QGraphicsTextItem,
)
from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer, QRectF, QPointF
from PySide6.QtGui import QFont, QIcon, QPen, QColor, QPainter, QAction

# Add project root to path
sys_path = str(Path(__file__).parent)
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from expert_anything.core.learner import (
    adaptive_path, normalize, register_asset, record_evaluation,
    mark_completed, due_for_review, load as load_learner, save as save_learner,
)
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.teacher import build_teacher_model, TeacherModel
from expert_anything.core.tutor import Tutor
from expert_anything.core.llm import LLMClient, LLMNotConfigured
from expert_anything.core.models import KnowledgeAsset, Concept, Relation, Chapter
from expert_anything.core import config
from expert_anything.core.teacher import (
    TeacherModel,
    anomaly_concept_ids,
    record_learner_question,
)
from expert_anything.core.storage import save_teacher
from expert_anything.ui.pyside_graph import KnowledgeGraphView
from expert_anything.ui.pyside_widgets import (
    ConceptDetailPanel,
    SourceTextView,
    PathLadderView,
    TeachResultView,
    TrendChartView,
    MasteryDistributionBar,
)

def _install_excepthook():
    """Never die silently: log + show a dialog on uncaught exceptions."""
    import traceback as _tb
    from datetime import datetime as _dt

    def _hook(exc_type, exc, tb):
        msg = "".join(_tb.format_exception(exc_type, exc, tb))
        try:
            log = Path(__file__).resolve().parent / "error.log"
            log.write_text(
                f"=== {_dt.now().isoformat()} ===\n{msg}", encoding="utf-8"
            )
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "程序错误",
                f"发生未处理的错误：\n{exc}\n\n"
                f"详情已写入 error.log（{log.name}）。您可以继续使用，"
                f"但建议反馈此问题。",
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


_install_excepthook()

# Thread-safe progress signal
class ProgressSignal(QObject):
    updated = Signal(str, int, int, str)

progress_signal = ProgressSignal()


class ExtractWorker(QThread):
    """Background thread for knowledge extraction.

    Accepts raw file bytes (or utf-8 text) + filename; text extraction
    (pdf/epub/docx/md/txt/html) runs via core.parsers so binary formats
    are handled without blocking the UI thread.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, raw, filename, llm_client):
        super().__init__()
        self.raw = raw
        self.filename = filename
        self.llm_client = llm_client

    def run(self):
        try:
            from expert_anything.core.parsers import extract_from_bytes
            if isinstance(self.raw, str):
                text = self.raw
            else:
                text = extract_from_bytes(self.raw, self.filename)
            if not text.strip():
                self.error.emit(
                    "无法从文件中提取文本。扫描版 PDF 需要 OCR，暂不支持；"
                    "请确认文件不是加密或损坏的。"
                )
                return
            asset = extract_knowledge(
                text,
                self.filename,
                llm=self.llm_client,
                on_progress=lambda stage, current, total, msg: None
            )
            self.finished.emit(asset)
        except Exception as e:
            self.error.emit(str(e))


class TeacherWorker(QThread):
    """Background thread for teacher model building."""
    
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
                on_progress=lambda stage, current, total, msg: None
            )
            self.finished.emit(teacher)
        except Exception as e:
            self.error.emit(str(e))


class TeachWorker(QThread):
    """Background thread for teaching session."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, tutor, concept, vary=0):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
        self.vary = vary

    def run(self):
        try:
            result = self.tutor.teach(self.concept, vary=self.vary)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class FollowUpWorker(QThread):
    """Background thread for grounded follow-up answers."""

    finished = Signal(str, str)  # question, answer
    error = Signal(str)

    def __init__(self, tutor, concept, question, lesson, history):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
        self.question = question
        self.lesson = lesson
        self.history = history

    def run(self):
        try:
            answer = self.tutor.follow_up(
                self.concept, self.question,
                lesson=self.lesson, history=self.history,
            )
            self.finished.emit(self.question, answer)
        except Exception as e:
            self.error.emit(str(e))


class KnowledgeCard(QFrame):
    """A card widget displaying a knowledge concept with mastery status."""

    clicked = Signal(str)

    def __init__(self, concept_name, mastery=0.0, tags=None, is_top=False, parent=None):
        super().__init__(parent)
        self.concept_name = concept_name
        self.mastery = mastery
        self.tags = tags or []
        self.is_top = is_top
        self.setup_ui()
        self.apply_style()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title_label = QLabel(self.concept_name)
        font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        title_label.setFont(font)
        title_row.addWidget(title_label)

        # Tags
        for tag in self.tags[:2]:
            tag_label = QLabel(tag)
            tag_label.setStyleSheet("""
                QLabel {
                    background-color: #E3F2FD;
                    color: #1565C0;
                    padding: 2px 8px;
                    border-radius: 4px;
                    font-size: 10px;
                }
            """)
            title_row.addWidget(tag_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # Mastery indicator: colour dot + percent (no horizontal bar)
        dot_row = QHBoxLayout()
        dot_row.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {self._get_mastery_hex()}; font-size: 12px;")
        dot_row.addWidget(dot)
        pct = QLabel(f"{self.mastery:.0%}")
        pct.setStyleSheet("color: #616161; font-size: 12px; font-weight: bold;")
        dot_row.addWidget(pct)
        dot_row.addStretch()
        layout.addLayout(dot_row)

        # Action button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        learn_btn = QPushButton("开始学习")
        learn_btn.setStyleSheet("""
            QPushButton {
                background-color: #1565C0;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0D47A1;
            }
        """)
        learn_btn.clicked.connect(lambda: self.clicked.emit(self.concept_name))
        btn_row.addWidget(learn_btn)
        layout.addLayout(btn_row)

    def apply_style(self):
        if self.is_top:
            self.setStyleSheet("""
                QFrame {
                    background-color: #E3F2FD;
                    border: 2px solid #1565C0;
                    border-radius: 12px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                }
                QFrame:hover {
                    border: 1px solid #90CAF9;
                }
            """)

    def _get_mastery_color(self):
        if self.mastery >= 0.6:
            return "background-color: #4CAF50;"
        elif self.mastery >= 0.3:
            return "background-color: #FF9800;"
        else:
            return "background-color: #F44336;"

    def _get_mastery_hex(self):
        if self.mastery >= 0.6:
            return "#4CAF50"
        elif self.mastery >= 0.3:
            return "#FF9800"
        else:
            return "#F44336"

    def mousePressEvent(self, event):
        self.clicked.emit(self.concept_name)
        super().mousePressEvent(event)


class StatCard(QFrame):
    """Dashboard statistic card."""

    def __init__(self, icon, label, value, color, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        # Icon circle
        icon_circle = QFrame(self)
        icon_circle.setFixedSize(32, 32)
        icon_circle.setStyleSheet(f"background-color: {color}20; border-radius: 16px;")
        icon_layout = QVBoxLayout(icon_circle)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(f"color: {color}; font-size: 16px;")
        icon_layout.addWidget(icon_label)

        header = QHBoxLayout()
        header.addWidget(icon_circle)
        header.addWidget(QLabel(label))
        header.addStretch()
        layout.addLayout(header)

        value_widget = QLabel(str(value))
        value_widget.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
        layout.addWidget(value_widget)
        layout.addStretch()

        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 10px;
            }
        """)


class MainWindow(QMainWindow):
    """Main application window with full functionality."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ExpertAnything · 个人学习 OS")
        self.setMinimumSize(1100, 760)
        self.resize(1200, 800)
        self.setStyleSheet(self._get_stylesheet())
        
        # Load real data
        self.assets = {}
        self.teacher_models = {}
        self.learner = {}
        self.current_asset_id = None
        self.llm_client = None
        self.current_tutor = None
        self.load_data()
        self.init_llm()
        
        self.setup_ui()

    def init_llm(self):
        """Initialize LLM client if configured."""
        try:
            if config.has_llm():
                self.llm_client = LLMClient.from_config(
                    config.LLM_API_KEY,
                    config.LLM_BASE_URL,
                    config.LLM_MODEL,
                )
        except LLMNotConfigured:
            self.llm_client = None

    def load_data(self):
        """Load real data from ExpertAnything core."""
        # Load assets (data dir comes from config, override via EXPERTANYTHING_DATA_DIR)
        asset_dir = config.DATA_DIR / "assets"
        if asset_dir.exists():
            for fname in asset_dir.glob("*.json"):
                if not fname.name.startswith("teacher_"):
                    with open(fname, encoding="utf-8") as f:
                        aid = fname.stem
                        self.assets[aid] = json.load(f)
        
        # Load teacher models
        for fname in asset_dir.glob("teacher_*.json"):
            aid = fname.stem.removeprefix("teacher_")
            with open(fname, encoding="utf-8") as f:
                self.teacher_models[aid] = json.load(f)
        
        # Load learner
        learner_path = config.DATA_DIR / "learner.json"
        if learner_path.exists():
            with open(learner_path, encoding="utf-8") as f:
                self.learner = json.load(f)
        
        # Select first asset by default
        if self.assets:
            self.current_asset_id = next(iter(self.assets))

    def get_asset(self, asset_id=None):
        """Build a KnowledgeAsset object from the loaded JSON data."""
        aid = asset_id or self.current_asset_id
        if not aid or aid not in self.assets:
            return None
        data = self.assets[aid]
        return KnowledgeAsset(
            asset_id=aid,
            type=data.get("type", "text"),
            title=data.get("title", aid),
            source_name=data.get("source_name", aid),
            created_at=data.get("created_at", ""),
            source_text=data.get("source_text", ""),
            chapters=[Chapter.from_dict(c) for c in data.get("chapters", [])],
            concepts=[Concept.from_dict(c) for c in data.get("concepts", [])],
            relations=[Relation.from_dict(r) for r in data.get("relations", [])],
            learning_path=data.get(
                "learning_path",
                [c["id"] for c in data.get("concepts", [])],
            ),
            method=data.get("method", "unknown"),
        )

    def get_adaptive_path(self, asset_id):
        """Compute adaptive learning path for an asset."""
        if asset_id not in self.assets:
            return []
        
        data = self.assets[asset_id]
        asset = KnowledgeAsset(
            asset_id=asset_id,
            type=data.get("type", "text"),
            title=data.get("title", asset_id),
            source_name=data.get("source_name", asset_id),
            created_at=data.get("created_at", ""),
            concepts=[Concept.from_dict(c) for c in data.get("concepts", [])],
            relations=[Relation.from_dict(r) for r in data.get("relations", [])],
            learning_path=data.get("learning_path", [c["id"] for c in data.get("concepts", [])])
        )
        
        return adaptive_path(asset, self.learner)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top function bar (always visible): asset + progress + quick actions
        self.topbar = self._build_topbar()
        main_layout.addWidget(self.topbar)

        # Body: navigation sidebar + content stack
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar (navigation area)
        sidebar = self._build_sidebar()
        body.addWidget(sidebar)

        # Content area (display area) with stacked views
        self.content_stack = QStackedWidget()
        
        # Build all views
        self.import_view = self._build_import_view()
        self.knowledge_view = self._build_knowledge_view()
        self.concept_map_view = self._build_concept_map_view()
        self.source_view = self._build_source_view()
        self.teach_view = self._build_teach_view()
        self.learner_view = self._build_learner_view()
        self.teacher_view = self._build_teacher_view()
        
        for view in [
            self.import_view,
            self.knowledge_view,
            self.concept_map_view,
            self.source_view,
            self.teach_view,
            self.learner_view,
            self.teacher_view,
        ]:
            self.content_stack.addWidget(view)

        body.addWidget(self.content_stack, 1)
        main_layout.addLayout(body, 1)
        self._update_topbar()

    def _build_knowledge_view(self):
        """Build the knowledge model view with adaptive learning path."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "知识模型",
            self._get_asset_subtitle(),
        )
        layout.addWidget(header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(20, 16, 20, 20)
        scroll_layout.setSpacing(16)

        # Dashboard stats
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)
        stats = self._compute_stats()
        for card in [
            ("📚", "总概念", stats['total'], "#1565C0"),
            ("✓", "已掌握", stats['mastered'], "#4CAF50"),
            ("↗", "学习中", stats['learning'], "#FF9800"),
            ("○", "未学习", stats['unstudied'], "#9E9E9E"),
            ("⚠", "异常", stats['anomalies'], "#F44336"),
        ]:
            stats_layout.addWidget(StatCard(*card))
        stats_layout.addStretch()
        scroll_layout.addLayout(stats_layout)

        # Concept cards from adaptive path
        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)

        section_title = QLabel("推荐下一步")
        section_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1565C0; padding: 4px 0;")
        cards_layout.addWidget(section_title)

        # Adaptive path ladder (ranked, with status chips)
        self._path_ladder = PathLadderView()
        self._path_ladder.concept_clicked.connect(self._open_concept_panel)
        if self.current_asset_id:
            path_items = self.get_adaptive_path(self.current_asset_id)
            entry = self.learner.get('assets', {}).get(self.current_asset_id, {})
            completed = set(entry.get('completed', []))
            self._path_ladder.set_items(path_items, completed=completed)
        cards_layout.addWidget(self._path_ladder)

        cards_layout.addStretch()
        scroll_layout.addWidget(cards_container)

        # Live concept graph (embedded dashboard view)
        graph_container = QWidget()
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(8)

        graph_title = QLabel("概念网络图")
        graph_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1565C0; padding: 4px 0;")
        graph_layout.addWidget(graph_title)

        self._dash_graph = KnowledgeGraphView()
        self._dash_graph.setMinimumHeight(300)
        self._dash_graph.setStyleSheet(
            "QGraphicsView { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        graph_layout.addWidget(self._dash_graph)

        if self.current_asset_id:
            asset = self.get_asset()
            if asset is not None:
                data = self.assets[self.current_asset_id]
                mastery_map = {}
                for c in asset.concepts:
                    norm_name = normalize(c.name)
                    mastery_map[c.id] = (
                        self.learner.get('concepts', {}).get(norm_name, {}).get('mastery', 0.0)
                    )
                anomaly_ids = set()
                td = self.teacher_models.get(self.current_asset_id)
                if td:
                    try:
                        anomaly_ids = anomaly_concept_ids(
                            asset, TeacherModel.from_dict(td)
                        )
                    except Exception:
                        anomaly_ids = set()
                items = self.get_adaptive_path(self.current_asset_id)
                current_id = items[0].get('cid') if items else None
                self._dash_graph.set_asset(
                    asset,
                    mastery_map=mastery_map,
                    anomaly_ids=anomaly_ids,
                    current_id=current_id,
                )
                self._dash_graph.concept_clicked.connect(self.on_card_click)

        scroll_layout.addWidget(graph_container)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        return widget

    def _build_learner_view(self):
        """Build the learner model view showing all concepts."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "学习者模型",
            f"跨资产累积掌握度 | {len(self.learner.get('concepts', {}))} 个概念",
        )
        layout.addWidget(header)

        # Learning-gain stat cards
        stats = self._compute_stats()
        due = due_for_review(self.learner)
        stat_row = QHBoxLayout()
        stat_row.setSpacing(12)
        stat_row.addWidget(StatCard("✓", "已掌握 (≥60%)", stats["mastered"], "#2E7D32"))
        stat_row.addWidget(StatCard("◐", "学习中", stats["learning"], "#B45309"))
        stat_row.addWidget(StatCard("⏰", "待复习", len(due), "#C62828"))
        stat_row.addWidget(StatCard("🧠", "跨资产概念", len(self.learner.get('concepts', {})), "#0284C7"))
        stat_row.addStretch()
        layout.addLayout(stat_row)

        # Learning overview: plain-language narrative + mastery distribution
        concepts_all = self.learner.get('concepts', {})
        total_c = len(concepts_all)
        mastered_c = sum(1 for v in concepts_all.values() if float(v.get('mastery', 0)) >= 0.6)
        learning_c = sum(1 for v in concepts_all.values() if 0.3 <= float(v.get('mastery', 0)) < 0.6)
        weak_c = sum(1 for v in concepts_all.values() if 0 < float(v.get('mastery', 0)) < 0.3)
        unstudied_c = sum(1 for v in concepts_all.values() if float(v.get('mastery', 0)) == 0)
        avg_c = (sum(float(v.get('mastery', 0)) for v in concepts_all.values()) / total_c) if total_c else 0

        weak_names = sorted(
            (v.get('name', k) for k, v in concepts_all.items()
             if 0 < float(v.get('mastery', 0)) < 0.6),
            key=lambda n: float(next(
                (v.get('mastery', 0) for k2, v in concepts_all.items() if v.get('name') == n), 0)),
        )[:3]

        summary = f"你共接触 {total_c} 个概念：已掌握 {mastered_c} 个（{mastered_c / total_c:.0%}），平均掌握度 {avg_c:.0%}。"
        if due:
            summary += f"有 {len(due)} 个概念到了复习时间（如「{due[0]['name']}」），现在复习效果最好。"
        if weak_names:
            summary += f"较薄弱的是：{'、'.join(weak_names)}。"
        elif total_c and mastered_c == total_c:
            summary += "全部掌握，非常棒！"

        overview = QFrame()
        overview.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 10px; }"
        )
        ov_lay = QVBoxLayout(overview)
        ov_lay.setContentsMargins(16, 12, 16, 12)
        ov_lay.setSpacing(6)

        ov_title = QLabel("学习总览")
        ov_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2933;")
        ov_lay.addWidget(ov_title)

        sum_lbl = QLabel(summary)
        sum_lbl.setWordWrap(True)
        sum_lbl.setStyleSheet("font-size: 13px; color: #37474F;")
        ov_lay.addWidget(sum_lbl)

        dist = MasteryDistributionBar({
            "mastered": mastered_c, "learning": learning_c,
            "weak": weak_c, "unstudied": unstudied_c,
        })
        ov_lay.addWidget(dist)

        leg_row = QHBoxLayout()
        leg_row.setSpacing(6)
        for color, text in [
            ("#4CAF50", f"已掌握 {mastered_c}"),
            ("#FF9800", f"学习中 {learning_c}"),
            ("#F44336", f"薄弱 {weak_c}"),
            ("#BDBDBD", f"未学 {unstudied_c}"),
        ]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 10px;")
            t = QLabel(text)
            t.setStyleSheet("color: #757575; font-size: 11px;")
            leg_row.addWidget(dot)
            leg_row.addWidget(t)
        leg_row.addStretch()
        ov_lay.addLayout(leg_row)
        layout.addWidget(overview)

        # Tab widget for concepts and history
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 4px; }
            QTabBar::tab { background: white; padding: 8px 16px; margin-right: 2px; }
            QTabBar::tab:selected { background: #E8F5E9; color: #2E7D32; }
        """)

        # Concepts tab
        concepts_widget = QWidget()
        concepts_layout = QVBoxLayout(concepts_widget)
        concepts_layout.setContentsMargins(20, 16, 20, 20)
        concepts_layout.setSpacing(8)

        # Review queue (spacing-effect based)
        due = due_for_review(self.learner)
        if due:
            due_title = QLabel(f"待复习（{len(due)} 个概念 · 基于遗忘曲线）")
            due_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #C62828; padding: 4px 0;")
            concepts_layout.addWidget(due_title)
            for d in due:
                card = KnowledgeCard(
                    concept_name=d['name'],
                    mastery=d['mastery'],
                    tags=[f"距上次 {d['days_since']:.0f} 天"],
                    is_top=False,
                )
                card.clicked.connect(
                    lambda e, n=d['name']: self._start_teach_by_name(n, review=True)
                )
                concepts_layout.addWidget(card)
            due_hint = QLabel(
                "间隔复习：薄弱概念 1 天、掌握概念 3-6 天到期——在遗忘前重温效果最好。"
            )
            due_hint.setStyleSheet("font-size: 11px; color: #9E9E9E;")
            concepts_layout.addWidget(due_hint)

        section_title = QLabel("所有概念掌握度")
        section_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E7D32; padding: 4px 0;")
        concepts_layout.addWidget(section_title)

        # group concepts by their first source asset
        groups = {}
        for key, rec in self.learner.get('concepts', {}).items():
            srcs = rec.get('sources', [])
            gid = srcs[0] if srcs else '?'
            groups.setdefault(gid, []).append(rec)

        for gid, items in groups.items():
            g_title = (
                self.assets.get(gid, {}).get('title', '未知资产')
                if gid != '?' else '其他来源'
            )
            g_label = QLabel(f"📚 {g_title}（{len(items)} 个概念）")
            g_label.setStyleSheet(
                "font-size: 12.5px; font-weight: bold; color: #0c4a6e;"
                "background-color: #E8F0F8; border-radius: 4px; padding: 4px 8px; margin-top: 6px;"
            )
            concepts_layout.addWidget(g_label)

            for i, concept in enumerate(sorted(items, key=lambda x: x.get('mastery', 0))):
                name = concept.get('name', concept.get('key', '?'))
                mastery = concept.get('mastery', 0)
                sources = concept.get('sources', [])
                tags = []
                if mastery < 0.3:
                    tags.append("薄弱")
                if len(sources) > 1:
                    tags.append("跨资产")

                card = KnowledgeCard(
                    concept_name=name,
                    mastery=mastery,
                    tags=tags,
                    is_top=(i == 0 and mastery == 0)
                )
                card.clicked.connect(self._open_concept_panel_by_name)
                concepts_layout.addWidget(card)

        concepts_layout.addStretch()
        tabs.addTab(concepts_widget, "概念掌握度")

        # History tab
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(20, 16, 20, 20)

        history_title = QLabel("学习历史记录")
        history_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E7D32; padding: 4px 0;")
        history_layout.addWidget(history_title)

        # Learning-gain trend (recent evaluation scores, time order)
        trend = TrendChartView()
        hist_series = self.learner.get('history', [])
        trend_items = [
            {"label": h.get('concept', '?'), "score": float(h.get('score', 0))}
            for h in reversed(hist_series[-12:])
        ]
        trend.set_data(trend_items)
        trend.setStyleSheet("background-color: white; border: 1px solid #E0E0E0; border-radius: 8px;")
        history_layout.addWidget(trend)

        history_table = QTableWidget()
        history_table.setColumnCount(4)
        history_table.setHorizontalHeaderLabels(["时间", "概念", "得分", "反馈"])
        history_table.horizontalHeader().setStretchLastSection(True)
        history_table.verticalHeader().setVisible(False)
        history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        history_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                font-size: 12px;
            }
            QTableWidget::item { padding: 6px; border-bottom: 1px solid #F0F0F0; }
            QHeaderView::section {
                background-color: #E8F5E9; color: #2E7D32;
                border: none; padding: 6px; font-weight: bold;
            }
        """)

        history = self.learner.get('history', [])
        history_table.setRowCount(len(history))
        for row, h in enumerate(history):
            at = h.get('at', '')[:19]
            score = float(h.get('score', 0))
            concept = h.get('concept', '?')
            feedback = h.get('feedback', '')[:80]

            at_item = QTableWidgetItem(at)
            con_item = QTableWidgetItem(concept)
            score_item = QTableWidgetItem(f"{score:.2f}")
            if score >= 0.6:
                score_item.setForeground(QColor("#2E7D32"))
            elif score >= 0.3:
                score_item.setForeground(QColor("#B45309"))
            else:
                score_item.setForeground(QColor("#C62828"))
            fb_item = QTableWidgetItem(feedback)

            history_table.setItem(row, 0, at_item)
            history_table.setItem(row, 1, con_item)
            history_table.setItem(row, 2, score_item)
            history_table.setItem(row, 3, fb_item)

        history_table.setColumnWidth(0, 170)
        history_table.setColumnWidth(1, 190)
        history_table.setColumnWidth(2, 60)
        if not history:
            history_table.setRowCount(1)
            empty = QTableWidgetItem("暂无学习历史记录。开始学习并答题后将显示记录。")
            history_table.setSpan(0, 0, 1, 4)
            history_table.setItem(0, 0, empty)

        history_layout.addWidget(history_table)

        # Export button
        export_btn = QPushButton("导出学习报告")
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #388E3C; }
        """)
        export_btn.clicked.connect(self._on_export_report)
        history_layout.addWidget(export_btn)
        history_layout.addStretch()

        tabs.addTab(history_widget, "学习历史")

        layout.addWidget(tabs)

        return widget

    def _get_asset_subtitle(self):
        """Get asset subtitle string."""
        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            title = data.get('title', self.current_asset_id)
            method = data.get('method', 'llm_extraction_chunked_v1')
            concepts = len(data.get('concepts', []))
            return f"来源：{title} | 概念数：{concepts} | 方法：{method}"
        return "加载知识数据..."

    def _compute_stats(self):
        """Compute dashboard statistics."""
        if not self.current_asset_id or self.current_asset_id not in self.assets:
            return {'total': 0, 'mastered': 0, 'learning': 0, 'unstudied': 0, 'anomalies': 0}
        
        data = self.assets[self.current_asset_id]
        concepts = data.get('concepts', [])
        total = len(concepts)
        
        # Count by mastery level
        mastered = 0
        learning = 0
        unstudied = 0
        
        for c in concepts:
            norm_name = normalize(c.get('name', ''))
            learner_rec = self.learner.get('concepts', {}).get(norm_name, {})
            m = learner_rec.get('mastery', 0)
            if m >= 0.6:
                mastered += 1
            elif m >= 0.3:
                learning += 1
            else:
                unstudied += 1
        
        return {
            'total': total,
            'mastered': mastered,
            'learning': learning,
            'unstudied': unstudied,
            'anomalies': 0
        }

    def _view_header(self, title, subtitle="") -> QFrame:
        """Compact unified view header: one row (title + subtitle inline)."""
        header = QFrame()
        header.setStyleSheet(
            "background-color: white; border-bottom: 2px solid #1565C0;"
        )
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

    def _build_topbar(self) -> QFrame:
        """Always-visible function bar: current asset, progress, quick actions."""
        bar = QFrame()
        bar.setStyleSheet(
            "background-color: white; border-bottom: 1px solid #E0E0E0;"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(12)

        self._topbar_asset = QLabel("未选择资产")
        self._topbar_asset.setStyleSheet(
            "font-size: 13.5px; font-weight: bold; color: #1F2933;"
        )
        lay.addWidget(self._topbar_asset)

        self._topbar_progress = QLabel("")
        self._topbar_progress.setStyleSheet("font-size: 12px; color: #6B7A90;")
        lay.addWidget(self._topbar_progress)
        lay.addStretch()

        for text, view_name in [
            ("🎓 开始学习", "teach"),
            ("🕸 概念网络", "concept_map"),
            ("📖 阅读原文", "source"),
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px; padding: 6px 14px;"
                "font-size: 12.5px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            btn.clicked.connect(lambda checked, v=view_name: self.on_nav_click(v))
            lay.addWidget(btn)
        return bar

    def _update_topbar(self) -> None:
        """Refresh the top bar after asset/learner changes."""
        if not self.current_asset_id or self.current_asset_id not in self.assets:
            self._topbar_asset.setText("未选择资产")
            self._topbar_progress.setText("")
            return
        data = self.assets[self.current_asset_id]
        title = data.get("title", self.current_asset_id)
        self._topbar_asset.setText(f"📚 {title}")
        stats = self._compute_stats()
        due = due_for_review(self.learner)
        self._topbar_progress.setText(
            f"已掌握 {stats['mastered']}/{stats['total']} · "
            f"学习中 {stats['learning']} · 待复习 {len(due)}"
        )

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background-color: #1A237E;")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(12)

        logo = QLabel("ExpertAnything")
        logo.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        layout.addWidget(logo)

        layout.addStretch()

        nav_items = [
            ("📥", "导入知识资产", "import"),
            ("🌳", "知识模型", "knowledge"),
            ("🗺️", "概念图", "concept_map"),
            ("📖", "阅读原文", "source"),
            ("🎓", "教学会话", "teach"),
            ("🧠", "学习者模型", "learner"),
            ("👨‍🏫", "教师模型", "teacher"),
        ]

        for icon, text, view_name in nav_items:
            btn = QPushButton(f"{icon}  {text}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #BBDEFB;
                    text-align: left;
                    padding: 10px 12px;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #283593;
                    color: white;
                }
            """)
            btn.clicked.connect(lambda checked, v=view_name: self.on_nav_click(v))
            layout.addWidget(btn)

        layout.addStretch()

        assets_label = QLabel("知识资产")
        assets_label.setStyleSheet("color: #90CAF9; font-size: 11px;")
        layout.addWidget(assets_label)

        # Add asset buttons dynamically
        self._asset_buttons = {}
        for aid, data in self.assets.items():
            title = data.get('title', aid)
            btn = QPushButton(f"📚 {title[:25]}{'...' if len(title) > 25 else ''}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #BBDEFB;
                    text-align: left;
                    padding: 8px 12px;
                    border: none;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #283593;
                }
                QPushButton:checked {
                    background-color: #3949AB;
                }
            """)
            btn.setCheckable(True)
            btn.setChecked(aid == self.current_asset_id)
            btn.clicked.connect(lambda checked, a=aid: self.on_asset_select(a))
            self._asset_buttons[aid] = btn
            layout.addWidget(btn)

        return sidebar

    def on_nav_click(self, view_name):
        """Handle navigation between views."""
        view_map = {
            "import": 0,
            "knowledge": 1,
            "concept_map": 2,
            "source": 3,
            "teach": 4,
            "learner": 5,
            "teacher": 6,
        }
        if view_name in view_map:
            self.content_stack.setCurrentIndex(view_map[view_name])

    def _rebuild_all_views(self):
        """Rebuild every view (after asset switch) without leaking widgets."""
        self._update_topbar()
        # clear stale widget refs BEFORE rebuilding so no handler can touch a
        # deleted object, and the new views re-register fresh references
        self._teach_view = None
        self._teach_graph = None
        self._graph_view = None
        self._source_view_widget = None
        self._dash_graph = None
        self._path_ladder = None
        self._teach_answer_input = None
        self.import_view = self._build_import_view()
        self.knowledge_view = self._build_knowledge_view()
        self.concept_map_view = self._build_concept_map_view()
        self.source_view = self._build_source_view()
        self.teach_view = self._build_teach_view()
        self.learner_view = self._build_learner_view()
        self.teacher_view = self._build_teacher_view()
        while self.content_stack.count():
            w = self.content_stack.widget(0)
            self.content_stack.removeWidget(w)
            w.deleteLater()
        for v in [
            self.import_view,
            self.knowledge_view,
            self.concept_map_view,
            self.source_view,
            self.teach_view,
            self.learner_view,
            self.teacher_view,
        ]:
            self.content_stack.addWidget(v)

    def on_asset_select(self, asset_id):
        """Handle asset selection (rebuild all views, show knowledge model)."""
        self.current_asset_id = asset_id
        # Update checked state on the sidebar buttons
        for aid, btn in getattr(self, "_asset_buttons", {}).items():
            btn.setChecked(aid == asset_id)
        # Refresh all views
        self._rebuild_all_views()
        self.content_stack.setCurrentIndex(1)  # knowledge model view

    def _get_stylesheet(self):
        return """
            QMainWindow {
                background-color: #FAFAFA;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #F5F5F5;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #BDBDBD;
                min-height: 30px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #9E9E9E;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }
        """

    def _build_global_asset(self):
        """Virtual asset merging every loaded asset (global knowledge map).

        Concepts of the current asset keep their ids and colours; concepts
        from other assets get prefixed ids and are rendered grey. Concepts
        shared across assets (same normalized name) are linked with a
        '共享概念' edge so the map shows cross-book connections.
        """
        from uuid import uuid4 as _uuid4
        from expert_anything.core.learner import normalize as _norm

        cur = self.get_asset()
        concepts, relations, id_map, grey_ids = [], [], {}, set()
        name_to_ids = {}
        for aid, data in self.assets.items():
            is_cur = aid == self.current_asset_id
            for c in data.get("concepts", []):
                cid = c["id"] if is_cur else f"{aid}:{c['id']}"
                concepts.append(Concept(
                    id=cid, name=c.get("name", "?"),
                    definition=c.get("definition", ""),
                    summary=c.get("summary", ""),
                    evidence=c.get("evidence", []),
                ))
                if not is_cur:
                    grey_ids.add(cid)
                id_map[(aid, c["id"])] = cid
                name_to_ids.setdefault(_norm(c.get("name", "")), []).append(cid)
            for r in data.get("relations", []):
                s = id_map.get((aid, r.get("source")))
                t = id_map.get((aid, r.get("target")))
                if s and t and s != t:
                    relations.append(Relation(
                        id=str(_uuid4()), source=s, target=t,
                        label=r.get("label", ""), type="related"))
        for norm, ids in name_to_ids.items():
            for a in ids:
                for b in ids:
                    if a < b:
                        relations.append(Relation(
                            id=str(_uuid4()), source=a, target=b,
                            label="共享概念", type="related"))

        # supplement edges from teacher notes: prerequisites -> '前置' edges,
        # connections mentioning another concept -> '关联' edges. This makes
        # the map richer even when the raw relation list is sparse.
        for aid, data in self.assets.items():
            tp = self.teacher_models.get(aid)
            if not tp:
                continue
            name_to_id_asset = {
                _norm(c.get("name", "")): id_map.get((aid, c["id"]))
                for c in data.get("concepts", [])
            }
            for n in tp.get("concept_notes", []):
                src_id = id_map.get((aid, n.get("concept_id")))
                if not src_id:
                    continue
                for pre in n.get("prerequisites", []) or []:
                    tgt = name_to_id_asset.get(_norm(pre))
                    if tgt and tgt != src_id:
                        relations.append(Relation(
                            id=str(_uuid4()), source=tgt, target=src_id,
                            label="前置", type="related"))
                for conn in n.get("connections", []) or []:
                    for c in data.get("concepts", []):
                        cname = c.get("name", "")
                        tgt = id_map.get((aid, c["id"]))
                        if cname and tgt and tgt != src_id and cname in conn:
                            relations.append(Relation(
                                id=str(_uuid4()), source=src_id, target=tgt,
                                label="关联", type="related"))
        path = []
        if cur is not None:
            path = [id_map.get((self.current_asset_id, cid), cid)
                    for cid in cur.learning_path]
        return KnowledgeAsset(
            asset_id="global", type="global", title="全局知识图谱",
            source_name="", created_at="", source_text="",
            concepts=concepts, relations=relations, learning_path=path,
        ), grey_ids

    def _open_concept_panel(self, concept_id: str) -> None:
        """Open the concept hub dialog for a concept id."""
        asset = self.get_asset()
        if asset is None or not concept_id:
            return
        teacher = None
        td = self.teacher_models.get(self.current_asset_id)
        if td:
            try:
                teacher = TeacherModel.from_dict(td)
            except Exception:
                teacher = None
        panel = ConceptDetailPanel(
            asset, concept_id, self.learner, teacher, self
        )
        panel.teach_requested.connect(self._start_teach_by_name)
        panel.focus_requested.connect(self._focus_in_graph)
        panel.evidence_requested.connect(self._jump_to_evidence)
        self._concept_panel = panel  # keep a reference (prevent GC)
        panel.show()

    def _open_concept_panel_by_name(self, concept_name: str) -> None:
        asset = self.get_asset()
        if asset is None:
            return
        c = asset.concept_by_name(concept_name)
        if c is not None:
            self._open_concept_panel(c.id)

    def _start_teach_by_name(self, concept_name: str, review: bool = False) -> None:
        """Select a concept in the teach view and start the lesson.

        ``review=True`` starts a review lesson (vary>0 -> the LLM is told to
        explain from a different angle so the review adds something new).
        """
        self.on_nav_click("teach")
        for i in range(self._teach_concept_list.count()):
            if self._teach_concept_list.item(i).text() == concept_name:
                self._teach_concept_list.setCurrentRow(i)
                break
        self._review_mode = review
        self._on_start_teach()

    def _focus_in_graph(self, concept_id: str) -> None:
        self.on_nav_click("concept_map")
        if getattr(self, "_graph_view", None) is not None:
            self._graph_view.focus_concept(concept_id)

    def _jump_to_evidence(self, concept_id: str, evidence: str) -> None:
        self.on_nav_click("source")
        if getattr(self, "_source_view_widget", None) is not None:
            self._source_view_widget.scroll_to_concept(concept_id, evidence)

    def on_card_click(self, concept_name):
        """Handle concept card click - start teaching session."""
        # Navigate to teach view
        self.on_nav_click("teach")
        # Find and select the concept
        for i in range(self._teach_concept_list.count()):
            if self._teach_concept_list.item(i).text() == concept_name:
                self._teach_concept_list.setCurrentRow(i)
                break

    def _on_start_teach(self):
        """Handle starting teaching session."""
        selected = self._teach_concept_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择一个概念")
            return

        concept_name = selected.text()
        asset = self.get_asset()
        if not asset:
            return

        # Find the concept
        concept = None
        for c in asset.concepts:
            if normalize(c.name) == normalize(concept_name):
                concept = c
                break

        if not concept:
            QMessageBox.warning(self, "提示", f"未找到概念: {concept_name}")
            return

        # Create tutor if needed
        if self.current_asset_id:
            self.current_tutor = Tutor(asset, llm=self.llm_client)

        # Show teaching content (review -> fresh angle)
        vary = 1 if getattr(self, "_review_mode", False) else 0
        self._show_teaching_content(concept, vary=vary)

    def _show_teaching_content(self, concept, vary=0):
        """Show teaching content for a concept (vary>0 = fresh angle, review)."""
        if not self.current_tutor:
            asset = self.get_asset()
            self.current_tutor = Tutor(asset, llm=self.llm_client)
        
        # Show progress
        self._teach_progress.setVisible(True)
        self._teach_progress.setValue(30)
        self._teach_result_label.setText("正在生成教学内容...")
        self._teach_result_label.repaint()

        # focus the position graph on the concept being taught
        try:
            asset = self.get_asset()
            if asset is not None:
                mastery_map = {}
                for c in asset.concepts:
                    norm_name = normalize(c.name)
                    mastery_map[c.id] = (
                        self.learner.get('concepts', {}).get(norm_name, {}).get('mastery', 0.0)
                    )
                anomaly_ids = set()
                td = self.teacher_models.get(self.current_asset_id)
                if td:
                    try:
                        anomaly_ids = anomaly_concept_ids(
                            asset, TeacherModel.from_dict(td)
                        )
                    except Exception:
                        anomaly_ids = set()
                self._teach_graph.set_asset(
                    asset,
                    mastery_map=mastery_map,
                    anomaly_ids=anomaly_ids,
                    current_id=concept.id,
                )
                self._teach_graph.focus_concept(concept.id)
                self._teach_graph.setVisible(True)
        except Exception:
            tg = getattr(self, "_teach_graph", None)
            if tg is not None:
                tg.setVisible(False)
        
        # Run teaching in background
        self._teach_worker = TeachWorker(self.current_tutor, concept, vary=vary)
        self._teach_worker.finished.connect(self._on_teach_finished)
        self._teach_worker.error.connect(self._on_teach_error)
        self._teach_worker.start()

    def _on_teach_finished(self, result):
        """Handle teaching completion."""
        self._teach_progress.setValue(100)
        
        # Display teaching content
        self._display_teach_result(result)

    def _on_teach_error(self, error_msg):
        """Handle teaching error."""
        self._teach_progress.setVisible(False)
        QMessageBox.critical(self, "错误", f"教学失败: {error_msg}")

    def _display_teach_result(self, result):
        """Display teaching result in the UI (structured cards)."""
        old = self._teach_result_area.takeWidget()
        if old is not None:
            old.deleteLater()

        view = TeachResultView(result)
        view.submit_requested.connect(self._on_submit_answer)
        view.followup_requested.connect(self._on_followup)
        view.neighbor_clicked.connect(self._start_teach_by_name)
        self._teach_lesson = result
        if view.answer_input is not None:
            self._teach_answer_input = view.answer_input
        self._teach_view = view
        self._teach_concept_now = result.get("concept", "")
        self._teach_result_area.setWidget(view)

        # related-concepts navigation (follow the knowledge network)
        asset = self.get_asset()
        if asset is not None:
            concept = asset.concept_by_name(result.get("concept", ""))
            if concept is not None:
                seen, neighbors = set(), []
                for r in asset.relations:
                    if r.source == concept.id:
                        other = asset.concept_by_id(r.target)
                        if other and other.id not in seen:
                            seen.add(other.id)
                            neighbors.append((r.label or "关联", other.name, other.id))
                    elif r.target == concept.id:
                        other = asset.concept_by_id(r.source)
                        if other and other.id not in seen:
                            seen.add(other.id)
                            neighbors.append((r.label or "关联", other.name, other.id))
                    if len(neighbors) >= 6:
                        break
                view.set_neighbors(neighbors)

        self._teach_progress.setVisible(False)
        self._teach_result_label.setText("")

    def _on_followup(self, question: str) -> None:
        """Answer a follow-up question in the background (grounded Q&A)."""
        if self.current_tutor is None:
            asset = self.get_asset()
            if asset is None:
                return
            self.current_tutor = Tutor(asset, llm=self.llm_client)
        concept = None
        asset = self.get_asset()
        if asset is not None:
            concept = asset.concept_by_name(self._teach_concept_now or "")
        if concept is None:
            return

        self._followup_history = getattr(self, "_followup_history", [])
        lesson = getattr(self, "_teach_lesson", None)
        self._followup_worker = FollowUpWorker(
            self.current_tutor, concept, question, lesson, self._followup_history
        )
        self._followup_worker.finished.connect(self._on_followup_done)
        self._followup_worker.error.connect(
            lambda msg: self._teach_view.append_exchange(question, f"（追问失败：{msg}）")
        )
        self._followup_worker.start()

    def _on_followup_done(self, question: str, answer: str) -> None:
        if getattr(self, "_teach_view", None) is not None:
            self._teach_view.append_exchange(question, answer)
        self._followup_history = getattr(self, "_followup_history", [])
        self._followup_history.append((question, answer))
        self._followup_history = self._followup_history[-4:]

        # sink the question into the teacher model (learner signals)
        try:
            asset = self.get_asset()
            if asset is not None:
                concept = asset.concept_by_name(self._teach_concept_now or "")
                if concept is not None:
                    teacher = None
                    td = self.teacher_models.get(self.current_asset_id)
                    if td:
                        teacher = TeacherModel.from_dict(td)
                    teacher = record_learner_question(
                        asset, teacher, concept.id, question
                    )
                    save_teacher(self.current_asset_id, teacher)
                    self.teacher_models[self.current_asset_id] = teacher.to_dict()
        except Exception:
            pass

    def _on_submit_answer(self):
        """Handle answer submission."""
        box = getattr(self, "_teach_answer_input", None)
        if box is None or not hasattr(box, "toPlainText"):
            QMessageBox.warning(self, "提示", "当前没有可提交的教学内容，请重新开始教学。")
            return
        answer = box.toPlainText().strip()
        if not answer:
            QMessageBox.warning(self, "提示", "请先输入你的回答")
            return
        
        selected = self._teach_concept_list.currentItem()
        if not selected:
            return
        
        concept_name = selected.text()
        asset = self.get_asset()
        if not asset:
            return
        
        # Find concept
        concept = None
        for c in asset.concepts:
            if normalize(c.name) == normalize(concept_name):
                concept = c
                break
        
        if not concept:
            QMessageBox.warning(self, "提示", f"未找到概念: {concept_name}")
            return
        
        # Evaluate answer
        if self.current_tutor:
            result = self.current_tutor.evaluate(concept, answer)
            score = result.get('score', 0)
            feedback = result.get('feedback', '')
            understood = result.get('understood', False)
            
            # Record evaluation
            new_mastery = record_evaluation(
                self.learner,
                concept.name,
                asset.asset_id,
                score,
                answer,
                feedback,
            )
            self.save_learner_state()
            
            # Show result as an evaluation card (reference + gap)
            reference = result.get('reference', '')
            gap = result.get('gap', '')
            if getattr(self, "_teach_view", None) is not None:
                self._teach_view.append_evaluation(
                    score, feedback, reference, gap
                )
            else:
                msg = f"得分: {score:.2f}\n"
                msg += "已掌握" if understood else "需继续努力"
                msg += f"\n\n反馈: {feedback}"
                QMessageBox.information(self, "评估结果", msg)
            
            # Refresh learner view if needed
            self._refresh_all_views()
        else:
            QMessageBox.warning(self, "提示", "请先开始教学会话")

    def save_learner_state(self):
        """Persist the in-memory learner model to disk (learner.json)."""
        save_learner(self.learner)

    def _refresh_all_views(self):
        """Refresh all views after learner state change."""
        # Refresh knowledge view
        if self.content_stack.currentIndex() == 1:
            old_view = self.content_stack.widget(1)
            new_view = self._build_knowledge_view()
            self.content_stack.replaceWidget(old_view, new_view)
            old_view.deleteLater()
        
        # Refresh learner view
        if self.content_stack.currentIndex() == 5:
            old_view = self.content_stack.widget(5)
            new_view = self._build_learner_view()
            self.content_stack.replaceWidget(old_view, new_view)
            old_view.deleteLater()

    def _build_import_view(self):
        """Build the import view for adding new knowledge assets."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "导入知识资产",
            "支持 PDF / EPUB / Word (.docx) / Markdown / TXT / HTML，自动提取概念并构建知识图谱",
        )
        layout.addWidget(header)

        # Content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        # File selection
        file_label = QLabel("选择文件:")
        file_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        content_layout.addWidget(file_label)

        self._import_fname = QLineEdit("learning-note.md")
        self._import_fname.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                font-size: 13px;
            }
        """)
        content_layout.addWidget(self._import_fname)

        # Paste area
        paste_label = QLabel("或粘贴内容:")
        paste_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        content_layout.addWidget(paste_label)

        self._import_paste = QTextEdit()
        self._import_paste.setPlaceholderText("在此粘贴你的学习材料...")
        self._import_paste.setMinimumHeight(200)
        self._import_paste.setStyleSheet("""
            QTextEdit {
                padding: 8px;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                font-size: 12px;
            }
        """)
        content_layout.addWidget(self._import_paste)

        # Buttons
        btn_layout = QHBoxLayout()
        
        choose_btn = QPushButton("选择文件")
        choose_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        choose_btn.clicked.connect(self._on_choose_file)
        btn_layout.addWidget(choose_btn)

        generate_btn = QPushButton("生成知识图谱")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #388E3C;
            }
        """)
        generate_btn.clicked.connect(self._on_generate)
        btn_layout.addWidget(generate_btn)
        btn_layout.addStretch()
        
        content_layout.addLayout(btn_layout)

        # Progress
        self._import_progress = QProgressBar()
        self._import_progress.setMaximumHeight(20)
        self._import_progress.setValue(0)
        self._import_progress.setVisible(False)
        content_layout.addWidget(self._import_progress)
        
        # Status label
        self._import_status_label = QLabel("")
        self._import_status_label.setStyleSheet("color: #666; font-size: 12px; margin-top: 8px;")
        content_layout.addWidget(self._import_status_label)
        
        # LLM status
        llm_status = "✓ LLM 已配置" if self.llm_client else "⚠ LLM 未配置（使用确定性回退）"
        llm_label = QLabel(llm_status)
        llm_label.setStyleSheet("color: #4CAF50; font-size: 12px; margin-top: 8px;") if self.llm_client else llm_label.setStyleSheet("color: #FF9800; font-size: 12px; margin-top: 8px;")
        content_layout.addWidget(llm_label)

        layout.addWidget(content)

        return widget

    def _build_concept_map_view(self):
        """Build the concept map view showing the interactive knowledge graph."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "概念网络图",
            "可视化概念之间的关系和层次结构",
        )
        layout.addWidget(header)

        # Content with interactive graph
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        if self.current_asset_id and self.current_asset_id in self.assets:
            # Toolbar: search / reset / scope
            toolbar = QHBoxLayout()
            toolbar.setSpacing(8)

            self._map_search = QLineEdit()
            self._map_search.setPlaceholderText("🔍 搜索概念并定位（回车）")
            self._map_search.setStyleSheet(
                "QLineEdit { border: 1px solid #BDBDBD; border-radius: 6px;"
                "padding: 5px 10px; font-size: 12.5px; background-color: white; }"
            )
            self._map_search.returnPressed.connect(self._on_map_search)
            toolbar.addWidget(self._map_search, 1)

            reset_btn = QPushButton("复位全图")
            reset_btn.setStyleSheet(
                "QPushButton { background-color: white; color: #1565C0;"
                "border: 1px solid #BBDEFB; border-radius: 6px; padding: 5px 14px;"
                "font-size: 12.5px; }"
                "QPushButton:hover { background-color: #E3F2FD; }"
            )
            reset_btn.clicked.connect(
                lambda: self._graph_view.reset_focus() if hasattr(self, "_graph_view") else None
            )
            toolbar.addWidget(reset_btn)

            self._map_scope = QComboBox()
            self._map_scope.addItems(["全部资产", "仅当前资产"])
            self._map_scope.setStyleSheet(
                "QComboBox { border: 1px solid #BDBDBD; border-radius: 6px;"
                "padding: 4px 8px; font-size: 12.5px; background-color: white; }"
            )
            self._map_scope.currentIndexChanged.connect(self._on_map_scope)
            toolbar.addWidget(self._map_scope)

            content_layout.addLayout(toolbar)

            # Interactive graph view (uses core.graph_viz layout math)
            self._graph_view = KnowledgeGraphView()
            self._graph_view.concept_clicked.connect(self.on_card_click)
            self._graph_view.node_single_clicked.connect(self._open_concept_panel)
            self._graph_view.setStyleSheet("""
                QGraphicsView {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                }
            """)
            self._graph_view.setMinimumHeight(420)
            content_layout.addWidget(self._graph_view)

            self._refresh_map_view()

            # Legend
            legend_label = QLabel(
                "图例：绿色 已掌握 · 琥珀 学习中 · 橙色 薄弱 · 深灰 未学 · 浅灰 其它资产概念 ·"
                "蓝框 聚焦/推荐 · 橙框 系统存疑 · 悬停节点高亮邻居"
            )
            legend_label.setStyleSheet("font-size: 11px; color: #666; margin-top: 8px;")
            content_layout.addWidget(legend_label)
        else:
            placeholder = QLabel("请先导入知识资产")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #757575; font-size: 14px; margin: 40px;")
            content_layout.addWidget(placeholder)

        layout.addWidget(content)

        return widget

    def _refresh_map_view(self) -> None:
        """(Re)load the concept map per the current scope selection."""
        if not hasattr(self, "_graph_view") or not self.current_asset_id:
            return
        scope_all = getattr(self, "_map_scope", None) is None or self._map_scope.currentIndex() == 0
        if scope_all:
            asset, grey_ids = self._build_global_asset()
        else:
            asset = self.get_asset()
            grey_ids = set()

        mastery_map = {}
        for c in asset.concepts:
            norm_name = normalize(c.name)
            mastery_map[c.id] = (
                self.learner.get('concepts', {}).get(norm_name, {}).get('mastery', 0.0)
            )

        anomaly_ids = set()
        teacher_data = self.teacher_models.get(self.current_asset_id)
        if teacher_data:
            try:
                tm = TeacherModel.from_dict(teacher_data)
                anomaly_ids = anomaly_concept_ids(asset, tm)
            except Exception:
                anomaly_ids = set()

        current_id = None
        items = self.get_adaptive_path(self.current_asset_id)
        if items:
            current_id = items[0].get('cid')

        self._graph_view.set_asset(
            asset,
            mastery_map=mastery_map,
            anomaly_ids=anomaly_ids,
            current_id=current_id,
            grey_ids=grey_ids,
        )

    def _on_map_search(self) -> None:
        """Locate a concept by keyword and focus it in the graph."""
        kw = self._map_search.text().strip().lower()
        if not kw or not hasattr(self, "_graph_view"):
            return
        gv = self._graph_view
        for cid, name, _role in gv._nodes:
            if kw in name.lower():
                gv.focus_concept(cid)
                return
        QMessageBox.information(self, "未找到", f"图谱中没有名为「{self._map_search.text().strip()}」的概念")

    def _on_map_scope(self, _idx: int) -> None:
        self._refresh_map_view()

    def _build_source_view(self):
        """Build the source text view for reading the original material."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "阅读原文",
            "查看原始学习材料",
        )
        layout.addWidget(header)

        # Source text display with concept highlighting
        if self.current_asset_id and self.current_asset_id in self.assets:
            asset = self.get_asset()

            # concept index chips (click -> jump to first occurrence)
            chips_scroll = QScrollArea()
            chips_scroll.setWidgetResizable(True)
            chips_scroll.setFixedHeight(42)
            chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
            chips_host = QWidget()
            chips_layout = QHBoxLayout(chips_host)
            chips_layout.setContentsMargins(0, 0, 0, 0)
            chips_layout.setSpacing(6)
            for c in asset.concepts:
                chip = QPushButton(c.name)
                chip.setStyleSheet(
                    "QPushButton { background-color: #F3E5F5; color: #7B1FA2;"
                    "border: 1px solid #E1BEE7; border-radius: 12px; padding: 3px 12px;"
                    "font-size: 11px; }"
                    "QPushButton:hover { background-color: #E1BEE7; }"
                )
                chip.clicked.connect(
                    lambda checked, cid=c.id: self._source_view_widget.scroll_to_concept(cid)
                )
                chips_layout.addWidget(chip)
            chips_layout.addStretch()
            chips_scroll.setWidget(chips_host)
            layout.addWidget(chips_scroll)

            self._source_view_widget = SourceTextView()
            self._source_view_widget.set_asset(asset)
            self._source_view_widget.concept_anchor_clicked.connect(
                self._open_concept_panel
            )
            layout.addWidget(self._source_view_widget, 1)
        else:
            placeholder = QLabel("请先导入知识资产")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #757575; font-size: 14px; margin: 40px;")
            layout.addWidget(placeholder)

        return widget

    def _build_teach_view(self):
        """Build the teaching session view."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "教学会话",
            "与 Tutor Agent 进行个性化学习",
        )
        layout.addWidget(header)

        # Splitter for concept list and content
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Concept list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 8, 16)
        
        concept_label = QLabel("选择要学习的概念:")
        concept_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        left_layout.addWidget(concept_label)

        self._teach_concept_list = QListWidget()
        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            for c in data.get('concepts', []):
                self._teach_concept_list.addItem(c.get('name', '?'))
        left_layout.addWidget(self._teach_concept_list)
        
        # Style selector
        style_label = QLabel("教学风格:")
        style_label.setStyleSheet("font-size: 12px; font-weight: bold; margin-top: 12px;")
        left_layout.addWidget(style_label)
        
        self._teach_style_combo = QComboBox()
        self._teach_style_combo.addItems(["例子", "图示", "拆解步骤"])
        self._teach_style_combo.setStyleSheet("""
            QComboBox {
                padding: 6px;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                font-size: 12px;
            }
        """)
        left_layout.addWidget(self._teach_style_combo)

        # Start button
        start_btn = QPushButton("开始教学")
        start_btn.setStyleSheet("""
            QPushButton {
                background-color: #1565C0;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #0D47A1;
            }
        """)
        start_btn.clicked.connect(self._on_start_teach)
        left_layout.addWidget(start_btn)
        left_layout.addStretch()
        
        splitter.addWidget(left_panel)
        
        # Right panel: Teaching content
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 16, 16, 16)
        
        self._teach_result_label = QLabel("选择一个概念开始学习")
        self._teach_result_label.setStyleSheet("color: #757575; font-size: 13px;")
        right_layout.addWidget(self._teach_result_label)

        # concept-position mini graph: shows where the current concept sits
        self._teach_graph = KnowledgeGraphView()
        self._teach_graph.setMinimumHeight(190)
        self._teach_graph.setStyleSheet(
            "QGraphicsView { background-color: white; border: 1px solid #E0E0E0;"
            "border-radius: 8px; }"
        )
        self._teach_graph.setVisible(False)
        right_layout.addWidget(self._teach_graph)
        
        self._teach_progress = QProgressBar()
        self._teach_progress.setVisible(False)
        right_layout.addWidget(self._teach_progress)
        
        self._teach_result_area = QScrollArea()
        self._teach_result_area.setWidgetResizable(True)
        self._teach_result_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                background-color: white;
            }
        """)
        right_layout.addWidget(self._teach_result_area)
        
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        
        layout.addWidget(splitter)

        return widget

    def _build_teacher_view(self):
        """Build the teacher model view showing system's understanding."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._view_header(
            "教师模型",
            "系统自己的理解和学习反馈",
        )
        layout.addWidget(header)

        # Content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        # What is this view? (plain-language explainer)
        explain = QFrame()
        explain.setStyleSheet(
            "QFrame { background-color: #FFF8E1; border: 1px solid #FFE0B2;"
            "border-radius: 8px; }"
        )
        ex_lay = QVBoxLayout(explain)
        ex_lay.setContentsMargins(12, 10, 12, 10)
        ex_lay.setSpacing(4)
        ex_t = QLabel("这个视图是什么？")
        ex_t.setStyleSheet("font-size: 12.5px; font-weight: bold; color: #B45309;")
        ex_lay.addWidget(ex_t)
        ex_b = QLabel(
            "教师模型 = 系统对这本书自己的理解（不是你的学习记录）。"
            "它深读材料后，为每个概念标注「为什么重要 / 前置知识 / 常见误解 / 外部连接」，"
            "并标出材料中矛盾、未定义、逻辑断点等可疑点（待解项）。"
            "「重新自检」= 让系统再深读一遍材料并更新理解（需要 LLM）。"
            "下方「概念笔记」逐条对应书中的概念，点击笔记可查看概念详情并开始学习。"
        )
        ex_b.setWordWrap(True)
        ex_b.setStyleSheet("font-size: 12px; color: #5D4037;")
        ex_lay.addWidget(ex_t)
        ex_lay.addWidget(ex_b)
        content_layout.addWidget(explain)

        # Check if teacher data exists
        if self.current_asset_id in self.teacher_models:
            teacher_data = self.teacher_models[self.current_asset_id]
            
            # Display teacher status
            status = teacher_data.get('status', 'unknown')
            status_label = QLabel(f"状态: {status}")
            status_color = "#2E7D32" if status == "done" else ("#FF9800" if status == "fallback" else "#F44336")
            status_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {status_color};")
            content_layout.addWidget(status_label)
            
            # Method info
            method = teacher_data.get('method', '')
            if method:
                method_label = QLabel(f"方法: {method}")
                method_label.setStyleSheet("font-size: 12px; color: #666;")
                content_layout.addWidget(method_label)
            
            # Synthesized time
            synthesized = teacher_data.get('synthesized_at', '')
            if synthesized:
                synth_label = QLabel(f"生成时间: {synthesized[:19]}")
                synth_label.setStyleSheet("font-size: 12px; color: #666;")
                content_layout.addWidget(synth_label)
            
            # Buttons
            btn_layout = QHBoxLayout()
            
            recheck_btn = QPushButton("重新自检")
            recheck_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
            """)
            recheck_btn.clicked.connect(self._on_recheck_teacher)
            btn_layout.addWidget(recheck_btn)
            
            if not self.llm_client:
                hint_label = QLabel("（需要配置 LLM 才能重新自检）")
                hint_label.setStyleSheet("color: #999; font-size: 12px;")
                btn_layout.addWidget(hint_label)
            
            btn_layout.addStretch()
            content_layout.addLayout(btn_layout)
            
            # Anomalies section
            anomalies = teacher_data.get('anomalies', [])
            if anomalies:
                anom_label = QLabel(f"待解项 ({len(anomalies)} 条):")
                anom_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #E65100; margin-top: 12px;")
                content_layout.addWidget(anom_label)
                
                kind_labels = {
                    "contradiction": "矛盾", "undefined_term": "未定义术语",
                    "logical_gap": "逻辑断点", "surprising_claim": "反常主张",
                    "learner_gap": "学习者信号", "needs_llm": "需要 LLM",
                }
                sev_colors = {
                    "high": "#C62828", "medium": "#E65100",
                    "low": "#616161", "info": "#0277BD",
                }
                sev_bgs = {
                    "high": "#FFEBEE", "medium": "#FFF3E0",
                    "low": "#F5F5F5", "info": "#E1F5FE",
                }
                for a in anomalies:
                    kind = a.get('kind', '?')
                    desc = a.get('description', '')
                    sev = a.get('severity', 'medium')
                    loc = a.get('location', '')
                    sev_color = sev_colors.get(sev, "#616161")
                    sev_bg = sev_bgs.get(sev, "#F5F5F5")

                    acard = QFrame()
                    acard.setStyleSheet(
                        f"QFrame {{ background-color: {sev_bg};"
                        f"border-left: 4px solid {sev_color}; border-radius: 6px; }}"
                    )
                    a_lay = QVBoxLayout(acard)
                    a_lay.setContentsMargins(12, 8, 12, 8)
                    a_lay.setSpacing(4)

                    head = QHBoxLayout()
                    head.setSpacing(8)
                    badge = QLabel(f"{kind_labels.get(kind, kind)} · {sev}")
                    badge.setStyleSheet(
                        f"background-color: {sev_color}; color: white;"
                        "padding: 2px 10px; border-radius: 8px; font-size: 10px; font-weight: bold;"
                    )
                    head.addWidget(badge)
                    if loc:
                        loc_lbl = QLabel(f"位置：{loc[:40]}")
                        loc_lbl.setStyleSheet("color: #757575; font-size: 10.5px;")
                        head.addWidget(loc_lbl)
                    head.addStretch()
                    a_lay.addLayout(head)

                    desc_lbl = QLabel(desc)
                    desc_lbl.setWordWrap(True)
                    desc_lbl.setStyleSheet("font-size: 12.5px; color: #37474F;")
                    a_lay.addWidget(desc_lbl)
                    content_layout.addWidget(acard)
            
            # Concept notes section
            notes = teacher_data.get('concept_notes', [])
            if notes:
                notes_label = QLabel(f"概念笔记 ({len(notes)} 条):")
                notes_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #666; margin-top: 12px;")
                content_layout.addWidget(notes_label)
                
                notes_hint = QLabel(
                    f"{len(notes)} 个概念的理解笔记——点击任意一条，查看该概念的证据、关系与教师理解。"
                )
                notes_hint.setStyleSheet("font-size: 11.5px; color: #8D6E63;")
                content_layout.addWidget(notes_hint)

                notes_list = QListWidget()
                notes_list.setStyleSheet("""
                    QListWidget {
                        background-color: white;
                        border: 1px solid #E0E0E0;
                        border-radius: 6px;
                        font-size: 12.5px;
                    }
                    QListWidget::item {
                        padding: 7px 10px;
                        border-bottom: 1px solid #F0F0F0;
                    }
                    QListWidget::item:hover { background-color: #FFF8E1; }
                """)
                for note in notes:
                    name = note.get('name', '?')
                    sign = note.get('significance', '')
                    miscon = note.get('misconceptions', [])
                    parts = [name]
                    if sign:
                        parts.append(sign[:46] + ("…" if len(sign) > 46 else ""))
                    if miscon:
                        parts.append(f"误区：{miscon[0][:24]}")
                    item = QListWidgetItem("　".join(parts))
                    item.setData(Qt.ItemDataRole.UserRole, note.get('concept_id', ''))
                    notes_list.addItem(item)
                notes_list.itemClicked.connect(
                    lambda it: self._open_concept_panel(it.data(Qt.ItemDataRole.UserRole))
                    if it.data(Qt.ItemDataRole.UserRole) else None
                )
                content_layout.addWidget(notes_list)
        else:
            placeholder = QLabel("教师模型数据尚未生成\n请先完成知识资产导入和自学习过程")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #757575; font-size: 14px; margin: 40px;")
            content_layout.addWidget(placeholder)
            
            # Try to build teacher model now
            build_btn = QPushButton("立即生成教师模型")
            build_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #388E3C;
                }
            """)
            build_btn.clicked.connect(self._on_build_teacher_now)
            content_layout.addWidget(build_btn)

        layout.addWidget(content)

        return widget

    def _on_recheck_teacher(self):
        """Handle re-checking teacher model."""
        if not self.llm_client:
            QMessageBox.warning(self, "提示", "需要配置 LLM 才能重新自检")
            return
        
        asset = self.get_asset()
        if not asset:
            return
        
        QMessageBox.information(self, "提示", "正在重新自检，请稍候...")
        
        self._teacher_worker = TeacherWorker(asset, self.llm_client)
        self._teacher_worker.finished.connect(self._on_teacher_recheck_finished)
        self._teacher_worker.error.connect(lambda e: QMessageBox.critical(self, "错误", f"自检失败: {e}"))
        self._teacher_worker.start()

    def _on_teacher_recheck_finished(self, teacher):
        """Handle teacher recheck completion."""
        self.teacher_models[teacher.asset_id] = teacher.to_dict()
        QMessageBox.information(self, "完成", f"自检完成: {len(teacher.anomalies)} 条待解项")
        # Refresh teacher view
        old_view = self.content_stack.widget(6)
        new_view = self._build_teacher_view()
        self.content_stack.replaceWidget(old_view, new_view)
        old_view.deleteLater()

    def _on_build_teacher_now(self):
        """Handle building teacher model now."""
        if not self.llm_client:
            QMessageBox.warning(self, "提示", "需要配置 LLM 才能生成教师模型")
            return
        
        asset = self.get_asset()
        if not asset:
            return
        
        QMessageBox.information(self, "提示", "正在生成教师模型，请稍候...")
        
        self._teacher_worker = TeacherWorker(asset, self.llm_client)
        self._teacher_worker.finished.connect(self._on_teacher_build_finished)
        self._teacher_worker.error.connect(lambda e: QMessageBox.critical(self, "错误", f"生成失败: {e}"))
        self._teacher_worker.start()

    def _on_teacher_build_finished(self, teacher):
        """Handle teacher model building completion."""
        self.teacher_models[teacher.asset_id] = teacher.to_dict()
        QMessageBox.information(self, "完成", f"教师模型生成完成: {len(teacher.anomalies)} 条待解项")
        # Refresh teacher view
        old_view = self.content_stack.widget(6)
        new_view = self._build_teacher_view()
        self.content_stack.replaceWidget(old_view, new_view)
        old_view.deleteLater()
        """Handle file selection."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            str(Path(__file__).parent / "data" / "samples"),
            "支持的文件 (*.pdf *.epub *.docx *.md *.markdown *.txt *.html *.htm);;PDF (*.pdf);;EPUB (*.epub);;Word (*.docx);;Markdown/文本 (*.md *.markdown *.txt);;HTML (*.html *.htm);;所有文件 (*.*)"
        )
        if file_path:
            self._import_fname.setText(file_path)

    def _on_choose_file(self):
        """Handle file selection."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            str(Path(__file__).parent / "data" / "samples"),
            "支持的文件 (*.pdf *.epub *.docx *.md *.markdown *.txt *.html *.htm);;PDF (*.pdf);;EPUB (*.epub);;Word (*.docx);;Markdown/文本 (*.md *.markdown *.txt);;HTML (*.html *.htm);;所有文件 (*.*)"
        )
        if file_path:
            self._import_fname.setText(file_path)

    def _on_generate(self):
        """Handle knowledge extraction with progress."""
        # Read file content
        fname = self._import_fname.text().strip()
        if not fname:
            QMessageBox.warning(self, "错误", "请先选择或输入文件名")
            return
        
        # Try to read from file path (raw bytes; binary formats parsed later)
        raw = b""
        if fname and Path(fname).exists():
            try:
                raw = Path(fname).read_bytes()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取文件失败: {e}")
                return
        else:
            # Use pasted content
            raw = self._import_paste.toPlainText().encode("utf-8")
        
        if not raw.strip():
            QMessageBox.warning(self, "错误", "内容为空，请提供学习材料")
            return
        
        # Show progress
        self._import_progress.setVisible(True)
        self._import_progress.setValue(10)
        self._import_status_label.setText("正在分析文本...")
        self._import_status_label.repaint()
        
        # Run extraction in background thread
        self._extract_worker = ExtractWorker(raw, fname, self.llm_client)
        self._extract_worker.finished.connect(self._on_extraction_finished)
        self._extract_worker.error.connect(self._on_extraction_error)
        self._extract_worker.start()

    def _on_extraction_finished(self, asset):
        """Handle extraction completion."""
        self._import_progress.setValue(80)
        self._import_status_label.setText(f"已抽取 {len(asset.concepts)} 个概念")
        
        # Register asset in learner
        register_asset(self.learner, asset)
        self.assets[asset.asset_id] = {
            "asset_id": asset.asset_id,
            "type": asset.type,
            "title": asset.title,
            "source_name": asset.source_name,
            "created_at": asset.created_at,
            "concepts": [c.to_dict() for c in asset.concepts],
            "relations": [r.to_dict() for r in asset.relations],
            "learning_path": asset.learning_path,
            "method": asset.method,
            "source_text": asset.source_text[:5000] + "..." if len(asset.source_text) > 5000 else asset.source_text,
        }
        
        # Build teacher model
        self._import_progress.setValue(85)
        self._import_status_label.setText("正在自我学习...")
        self._teacher_worker = TeacherWorker(asset, self.llm_client)
        self._teacher_worker.finished.connect(self._on_teacher_finished)
        self._teacher_worker.error.connect(self._on_extraction_error)
        self._teacher_worker.start()

    def _on_teacher_finished(self, teacher):
        """Handle teacher model building."""
        self._import_progress.setValue(95)
        self._import_status_label.setText(f"自我学习完成: {len(teacher.anomalies)} 条待解项")
        
        # Save teacher model
        self.teacher_models[teacher.asset_id] = teacher.to_dict()
        
        # Save learner state
        self.save_learner_state()
        
        # Refresh asset list in sidebar
        self._refresh_asset_list()
        
        self._import_progress.setValue(100)
        QMessageBox.information(
            self,
            "导入成功",
            f"知识资产《{self.assets[self.current_asset_id]['title']}》导入完成！\n\n"
            f"概念数: {len(self.assets[self.current_asset_id]['concepts'])}\n"
            f"关系数: {len(self.assets[self.current_asset_id]['relations'])}\n"
            f"异常数: {len(self.teacher_models[self.current_asset_id]['anomalies']) if self.current_asset_id in self.teacher_models else 0}"
        )
        # Switch to knowledge view
        self.on_nav_click("knowledge")

    def _on_extraction_error(self, error_msg):
        """Handle extraction error."""
        self._import_progress.setVisible(False)
        QMessageBox.critical(self, "错误", f"处理失败: {error_msg}")

    def _refresh_asset_list(self):
        """Refresh asset list in sidebar."""
        # Find asset section
        for child in self.findChildren(QPushButton):
            if child.text().startswith("📚"):
                child.deleteLater()

        # Re-add asset buttons
        sidebar = self.findChildren(QFrame)[0]  # Get sidebar
        layout = sidebar.layout()
        assets_label = QLabel("知识资产")
        assets_label.setStyleSheet("color: #90CAF9; font-size: 11px;")
        layout.addWidget(assets_label)

        for aid, data in self.assets.items():
            title = data.get('title', aid)
            btn = QPushButton(f"📚 {title[:25]}{'...' if len(title) > 25 else ''}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #BBDEFB;
                    text-align: left;
                    padding: 8px 12px;
                    border: none;
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #283593;
                }
            """)
            btn.setCheckable(True)
            btn.setChecked(aid == self.current_asset_id)
            btn.clicked.connect(lambda checked, a=aid: self.on_asset_select(a))
            self._asset_buttons[aid] = btn
            layout.addWidget(btn)

    def _on_export_report(self):
        """Export learning report to file."""
        # Build report content
        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append("ExpertAnything 学习报告")
        report_lines.append("=" * 70)
        report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")

        # Asset info
        report_lines.append("【知识资产】")
        report_lines.append("-" * 70)
        for aid, data in self.assets.items():
            title = data.get('title', aid)
            concepts = len(data.get('concepts', []))
            relations = len(data.get('relations', []))
            report_lines.append(f"  • {title}")
            report_lines.append(f"    概念数: {concepts}, 关系数: {relations}")
        report_lines.append("")

        # Concept mastery
        report_lines.append("【概念掌握度】")
        report_lines.append("-" * 70)
        concepts = self.learner.get('concepts', {})
        sorted_concepts = sorted(concepts.values(), key=lambda x: -x.get('mastery', 0))
        for c in sorted_concepts[:15]:
            name = c.get('name', '?')
            mastery = c.get('mastery', 0)
            sources = ', '.join(c.get('sources', []))
            bar = '█' * int(mastery * 10) + '░' * (10 - int(mastery * 10))
            report_lines.append(f"  [{bar}] {name}: {mastery:.0%}")
            report_lines.append(f"      来源: {sources}")
        report_lines.append("")

        # History
        history = self.learner.get('history', [])
        if history:
            report_lines.append("【最近评估记录】")
            report_lines.append("-" * 70)
            for h in history[-10:]:
                at = h.get('at', '')[:19]
                score = h.get('score', 0)
                concept = h.get('concept', '?')
                feedback = h.get('feedback', '')[:60]
                report_lines.append(f"  [{at}] {concept}")
                report_lines.append(f"    得分: {score:.2f} | 反馈: {feedback}")
            report_lines.append("")

        report_lines.append("=" * 70)
        report_lines.append("报告生成完毕")

        # Save to file
        report_content = "\n".join(report_lines)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "保存学习报告",
            f"学习报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(report_content)
                QMessageBox.information(
                    self,
                    "导出成功",
                    f"学习报告已保存到:\n{filename}"
                )
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def _get_stylesheet(self):
        return """
            QMainWindow {
                background-color: #FAFAFA;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #F5F5F5;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #BDBDBD;
                min-height: 30px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #9E9E9E;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }
        """


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    import sys
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
