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
    mark_completed, load as load_learner, save as save_learner,
)
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.teacher import build_teacher_model, TeacherModel
from expert_anything.core.tutor import Tutor
from expert_anything.core.llm import LLMClient, LLMNotConfigured
from expert_anything.core.models import KnowledgeAsset, Concept, Relation, Chapter
from expert_anything.core import config
from expert_anything.core.teacher import TeacherModel, anomaly_concept_ids
from expert_anything.ui.pyside_graph import KnowledgeGraphView

# Thread-safe progress signal
class ProgressSignal(QObject):
    updated = Signal(str, int, int, str)

progress_signal = ProgressSignal()


class ExtractWorker(QThread):
    """Background thread for knowledge extraction."""
    
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, text, filename, llm_client):
        super().__init__()
        self.text = text
        self.filename = filename
        self.llm_client = llm_client
    
    def run(self):
        try:
            asset = extract_knowledge(
                self.text, 
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
    
    def __init__(self, tutor, concept):
        super().__init__()
        self.tutor = tutor
        self.concept = concept
    
    def run(self):
        try:
            result = self.tutor.teach(self.concept)
            self.finished.emit(result)
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

        # Mastery bar
        progress = QFrame(self)
        progress.setMinimumHeight(6)
        progress.setMaximumHeight(6)
        progress.setStyleSheet("background-color: #E0E0E0; border-radius: 3px;")
        layout.addWidget(progress)

        fill = QFrame(progress)
        mastery_width = int(self.width() * max(self.mastery, 0.1)) if self.width() > 0 else 50
        fill.setFixedSize(mastery_width, 6)
        fill.setStyleSheet(self._get_mastery_color())
        fill.move(0, 0)

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
        # Load assets
        asset_dir = Path(__file__).parent / "data" / "assets"
        for fname in asset_dir.glob("*.json"):
            if not fname.name.startswith("teacher_"):
                with open(fname) as f:
                    aid = fname.stem
                    self.assets[aid] = json.load(f)
        
        # Load teacher models
        for fname in asset_dir.glob("teacher_*.json"):
            aid = fname.name.replace("teacher_", "", 1)
            with open(fname) as f:
                self.teacher_models[aid] = json.load(f)
        
        # Load learner
        learner_path = Path(__file__).parent / "data" / "learner.json"
        if learner_path.exists():
            with open(learner_path) as f:
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
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = self._build_sidebar()
        main_layout.addWidget(sidebar)

        # Content area with stacked widgets for different views
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
        
        main_layout.addWidget(self.content_stack)

    def _build_knowledge_view(self):
        """Build the knowledge model view with adaptive learning path."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background-color: #E3F2FD;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        title = QLabel("知识模型")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1A237E;")
        header_layout.addWidget(title)
        
        subtitle = QLabel(self._get_asset_subtitle())
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)
        
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

        # Get adaptive path from real data
        if self.current_asset_id:
            path_items = self.get_adaptive_path(self.current_asset_id)
            for i, item in enumerate(path_items):
                card = KnowledgeCard(
                    concept_name=item['name'],
                    mastery=item['mastery'],
                    tags=item['tags'],
                    is_top=(i == 0)
                )
                card.clicked.connect(self.on_card_click)
                cards_layout.addWidget(card)
        else:
            # Fallback to sample data
            sample_concepts = [
                ("pure mathematics", 0.0, ["weak", "foundation", "path"], True),
                ("consumer of mathematics", 0.0, ["weak", "unblock:2", "path"], False),
                ("producer of mathematics", 0.0, ["weak", "unblock:1", "path"], False),
            ]
            for name, mastery, tags, is_top in sample_concepts:
                card = KnowledgeCard(name, mastery, tags, is_top)
                card.clicked.connect(self.on_card_click)
                cards_layout.addWidget(card)

        cards_layout.addStretch()
        scroll_layout.addWidget(cards_container)

        # Graph section placeholder
        graph_container = QWidget()
        graph_layout = QVBoxLayout(graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(8)

        graph_title = QLabel("概念网络图")
        graph_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1565C0; padding: 4px 0;")
        graph_layout.addWidget(graph_title)

        graph_placeholder = QFrame()
        graph_placeholder.setMinimumHeight(300)
        graph_placeholder.setStyleSheet("background-color: #E3F2FD; border-radius: 8px;")
        graph_inner = QVBoxLayout(graph_placeholder)
        graph_label = QLabel("知识图谱将在这里显示\n（需要 QGraphicsView 实现）")
        graph_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        graph_label.setStyleSheet("color: #757575; font-size: 12px;")
        graph_inner.addWidget(graph_label)
        graph_layout.addWidget(graph_placeholder)

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
        header = QFrame()
        header.setStyleSheet("background-color: #E8F5E9;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("学习者模型")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2E7D32;")
        header_layout.addWidget(title)

        subtitle = QLabel(f"跨资产累积掌握度 | {len(self.learner.get('concepts', {}))} 个概念")
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

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

        section_title = QLabel("所有概念掌握度")
        section_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E7D32; padding: 4px 0;")
        concepts_layout.addWidget(section_title)

        concepts = sorted(
            self.learner.get('concepts', {}).values(),
            key=lambda x: x.get('mastery', 0)
        )

        for i, concept in enumerate(concepts):
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
            card.clicked.connect(self.on_card_click)
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

        history_text = QTextEdit()
        history_text.setReadOnly(True)
        history_text.setMinimumHeight(300)
        history_text.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                padding: 12px;
                font-size: 12px;
            }
        """)

        history = self.learner.get('history', [])
        if history:
            lines = []
            lines.append("=" * 70)
            lines.append(f"最近 {len(history)} 次评估记录:")
            lines.append("=" * 70)
            for h in history:
                at = h.get('at', '')[:19]
                score = h.get('score', 0)
                concept = h.get('concept', '?')
                feedback = h.get('feedback', '')[:50]
                lines.append(f"[{at}] {concept}")
                lines.append(f"  得分: {score:.2f} | 反馈: {feedback}...")
                lines.append("")
            history_text.setPlainText("\n".join(lines))
        else:
            history_text.setPlainText("暂无学习历史记录。开始学习并答题后将显示记录。")

        history_layout.addWidget(history_text)

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

    def on_asset_select(self, asset_id):
        """Handle asset selection."""
        self.current_asset_id = asset_id
        # Update checked state
        for child in self.findChildren(QPushButton):
            if child.text().startswith("📚"):
                child.setChecked(child.text().contains(asset_id))
        # Refresh knowledge view
        self.content_stack.widget(0).deleteLater()
        new_view = self._build_knowledge_view()
        self.content_stack.insertWidget(0, new_view)
        self.content_stack.setCurrentIndex(0)

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

        # Show teaching content
        self._show_teaching_content(concept)

    def _show_teaching_content(self, concept):
        """Show teaching content for a concept."""
        if not self.current_tutor:
            asset = self.get_asset()
            self.current_tutor = Tutor(asset, llm=self.llm_client)
        
        # Show progress
        self._teach_progress.setVisible(True)
        self._teach_progress.setValue(30)
        self._teach_result_label.setText("正在生成教学内容...")
        self._teach_result_label.repaint()
        
        # Run teaching in background
        self._teach_worker = TeachWorker(self.current_tutor, concept)
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
        """Display teaching result in the UI."""
        # Clear previous content
        for widget in self._teach_result_area.findChildren(QWidget):
            widget.deleteLater()
        
        layout = QVBoxLayout(self._teach_result_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Concept title
        title = QLabel(f"📖 {result.get('concept', '概念')}")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1565C0;")
        layout.addWidget(title)
        
        # Explanation
        explanation = result.get('explanation', '')
        if explanation:
            exp_label = QLabel("讲解:")
            exp_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
            layout.addWidget(exp_label)
            exp_text = QTextEdit()
            exp_text.setPlainText(explanation)
            exp_text.setReadOnly(True)
            exp_text.setMaximumHeight(150)
            exp_text.setStyleSheet("""
                QTextEdit {
                    background-color: #F5F5F5;
                    border: 1px solid #E0E0E0;
                    border-radius: 6px;
                    padding: 8px;
                    font-size: 12px;
                }
            """)
            layout.addWidget(exp_text)
        
        # Example
        example = result.get('example', '')
        if example:
            ex_label = QLabel("示例:")
            ex_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
            layout.addWidget(ex_label)
            ex_text = QTextEdit()
            ex_text.setPlainText(example)
            ex_text.setReadOnly(True)
            ex_text.setMaximumHeight(100)
            ex_text.setStyleSheet("""
                QTextEdit {
                    background-color: #FFF8E1;
                    border: 1px solid #FFE082;
                    border-radius: 6px;
                    padding: 8px;
                    font-size: 12px;
                }
            """)
            layout.addWidget(ex_text)
        
        # Steps
        steps = result.get('steps', [])
        if steps:
            step_label = QLabel("学习步骤:")
            step_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
            layout.addWidget(step_label)
            steps_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
            steps_label = QLabel(steps_text)
            steps_label.setWordWrap(True)
            steps_label.setStyleSheet("font-size: 12px; color: #555;")
            layout.addWidget(steps_label)
        
        # Practice question
        practice = result.get('practice', '')
        if practice:
            prac_label = QLabel("练习:")
            prac_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
            layout.addWidget(prac_label)
            
            self._teach_answer_input = QTextEdit()
            self._teach_answer_input.setPlaceholderText("请用自己的话回答这个问题...")
            self._teach_answer_input.setMinimumHeight(80)
            self._teach_answer_input.setStyleSheet("""
                QTextEdit {
                    border: 1px solid #E0E0E0;
                    border-radius: 6px;
                    padding: 8px;
                    font-size: 12px;
                }
            """)
            layout.addWidget(self._teach_answer_input)
            
            submit_btn = QPushButton("提交答案")
            submit_btn.setStyleSheet("""
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
            submit_btn.clicked.connect(self._on_submit_answer)
            layout.addWidget(submit_btn)
        
        # Evidence
        evidence = result.get('evidence', [])
        if evidence:
            ev_label = QLabel("原文证据:")
            ev_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
            layout.addWidget(ev_label)
            ev_text = "\n".join(f"- {e}" for e in evidence[:3])
            ev_label_widget = QLabel(ev_text)
            ev_label_widget.setWordWrap(True)
            ev_label_widget.setStyleSheet("font-size: 11px; color: #666; background-color: #E3F2FD; padding: 8px; border-radius: 4px;")
            layout.addWidget(ev_label_widget)
        
        layout.addStretch()
        
        self._teach_progress.setVisible(False)
        self._teach_result_label.setText("")

    def _on_submit_answer(self):
        """Handle answer submission."""
        answer = self._teach_answer_input.toPlainText().strip()
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
            
            # Show result
            msg = f"得分: {score:.2f}\n"
            if understood:
                msg += "✓ 已掌握"
            else:
                msg += "✗ 需继续努力"
            msg += f"\n\n反馈: {feedback}"
            
            QMessageBox.information(self, "评估结果", msg)
            
            # Refresh learner view if needed
            self._refresh_all_views()
        else:
            QMessageBox.warning(self, "提示", "请先开始教学会话")

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
        header = QFrame()
        header.setStyleSheet("background-color: #FFF3E0;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        title = QLabel("导入知识资产")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #E65100;")
        header_layout.addWidget(title)
        
        subtitle = QLabel("上传 Markdown/Text 文件，系统将自动提取概念并构建知识图谱")
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)
        
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
        header = QFrame()
        header.setStyleSheet("background-color: #E8F5E9;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("概念网络图")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #2E7D32;")
        header_layout.addWidget(title)

        subtitle = QLabel("可视化概念之间的关系和层次结构")
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # Content with interactive graph
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            asset = self.get_asset()
            concepts = data.get('concepts', [])
            relations = data.get('relations', [])

            info_label = QLabel(
                f"共 {len(concepts)} 个概念，{len(relations)} 条关系。"
                "单击节点聚焦其知识网络，双击开始学习；滚轮缩放，拖拽平移。"
            )
            info_label.setStyleSheet("font-size: 12px; color: #666;")
            content_layout.addWidget(info_label)

            # Interactive graph view (uses core.graph_viz layout math)
            self._graph_view = KnowledgeGraphView()
            self._graph_view.concept_clicked.connect(self.on_card_click)
            self._graph_view.setStyleSheet("""
                QGraphicsView {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                }
            """)
            self._graph_view.setMinimumHeight(420)
            content_layout.addWidget(self._graph_view)

            # Mastery map by concept id (cross-asset learner model)
            mastery_map = {}
            for c in concepts:
                norm_name = normalize(c.get('name', ''))
                mastery_map[c.get('id')] = (
                    self.learner.get('concepts', {}).get(norm_name, {}).get('mastery', 0.0)
                )

            # Anomaly-touched concept ids from the teacher model
            anomaly_ids = set()
            teacher_data = self.teacher_models.get(self.current_asset_id)
            if teacher_data:
                try:
                    tm = TeacherModel.from_dict(teacher_data)
                    anomaly_ids = anomaly_concept_ids(asset, tm)
                except Exception:
                    anomaly_ids = set()

            # Recommended-next concept (cyan border)
            current_id = None
            items = self.get_adaptive_path(self.current_asset_id)
            if items:
                current_id = items[0].get('cid')

            self._graph_view.set_asset(
                asset,
                mastery_map=mastery_map,
                anomaly_ids=anomaly_ids,
                current_id=current_id,
            )

            # Legend
            legend_label = QLabel(
                "图例：绿色 已掌握 · 琥珀 学习中 · 橙色 薄弱 · 灰色 未学 · 蓝框 聚焦/推荐 · 橙框 系统存疑"
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

    def _build_source_view(self):
        """Build the source text view for reading the original material."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background-color: #F3E5F5;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        title = QLabel("阅读原文")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #7B1FA2;")
        header_layout.addWidget(title)
        
        subtitle = QLabel("查看原始学习材料")
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)
        
        layout.addWidget(header)

        # Source text display
        if self.current_asset_id and self.current_asset_id in self.assets:
            data = self.assets[self.current_asset_id]
            source_text = data.get('source_text', '')
            
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            
            text_widget = QTextEdit()
            text_widget.setPlainText(source_text[:10000] + "..." if len(source_text) > 10000 else source_text)
            text_widget.setReadOnly(True)
            text_widget.setStyleSheet("""
                QTextEdit {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 8px;
                    padding: 16px;
                    font-size: 12px;
                    line-height: 1.6;
                }
            """)
            
            scroll.setWidget(text_widget)
            layout.addWidget(scroll)
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
        header = QFrame()
        header.setStyleSheet("background-color: #E3F2FD;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        title = QLabel("教学会话")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1565C0;")
        header_layout.addWidget(title)
        
        subtitle = QLabel("与 Tutor Agent 进行个性化学习")
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)
        
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
        header = QFrame()
        header.setStyleSheet("background-color: #FFF8E1;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        title = QLabel("教师模型")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #F57C00;")
        header_layout.addWidget(title)
        
        subtitle = QLabel("系统自己的理解和学习反馈")
        subtitle.setStyleSheet("color: #757575; font-size: 12px;")
        header_layout.addWidget(subtitle)
        
        layout.addWidget(header)

        # Content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(12)

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
                
                anom_text = QTextEdit()
                anom_text.setReadOnly(True)
                anom_text.setMaximumHeight(150)
                anom_lines = []
                for a in anomalies:
                    kind = a.get('kind', '?')
                    desc = a.get('description', '')
                    sev = a.get('severity', 'medium')
                    sev_color = "red" if sev == "high" else ("orange" if sev == "medium" else "gray")
                    anom_lines.append(f"[{sev.upper()}] {kind}: {desc}")
                anom_text.setPlainText("\n".join(anom_lines))
                anom_text.setStyleSheet("""
                    QTextEdit {
                        background-color: #FFF3E0;
                        border: 1px solid #FFE0B2;
                        border-radius: 6px;
                        padding: 8px;
                        font-size: 12px;
                    }
                """)
                content_layout.addWidget(anom_text)
            
            # Concept notes section
            notes = teacher_data.get('concept_notes', [])
            if notes:
                notes_label = QLabel(f"概念笔记 ({len(notes)} 条):")
                notes_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #666; margin-top: 12px;")
                content_layout.addWidget(notes_label)
                
                notes_scroll = QScrollArea()
                notes_scroll.setWidgetResizable(True)
                notes_scroll.setMaximumHeight(200)
                notes_scroll.setStyleSheet("""
                    QScrollArea {
                        border: 1px solid #E0E0E0;
                        border-radius: 6px;
                        background-color: white;
                    }
                """)
                
                notes_content = QWidget()
                notes_layout = QVBoxLayout(notes_content)
                notes_layout.setContentsMargins(8, 8, 8, 8)
                notes_layout.setSpacing(8)
                
                for note in notes[:5]:  # Show first 5
                    note_widget = QFrame()
                    note_widget.setStyleSheet("""
                        QFrame {
                            background-color: #F5F5F5;
                            border-radius: 4px;
                            padding: 8px;
                        }
                    """)
                    note_inner = QVBoxLayout(note_widget)
                    
                    name = note.get('name', '?')
                    sign = note.get('significance', '')
                    
                    name_label = QLabel(f"📌 {name}")
                    name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
                    note_inner.addWidget(name_label)
                    
                    if sign:
                        sign_label = QLabel(f"重要性: {sign}")
                        sign_label.setStyleSheet("font-size: 11px; color: #555;")
                        note_inner.addWidget(sign_label)
                    
                    miscon = note.get('misconceptions', [])
                    if miscon:
                        mc_label = QLabel(f"常见误解: {'; '.join(miscon[:3])}")
                        mc_label.setStyleSheet("font-size: 11px; color: #D32F2F;")
                        note_inner.addWidget(mc_label)
                    
                    note_inner.addStretch()
                    notes_layout.addWidget(note_widget)
                
                notes_layout.addStretch()
                notes_scroll.setWidget(notes_content)
                content_layout.addWidget(notes_scroll)
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
            "文本文件 (*.md *.txt);;所有文件 (*.*)"
        )
        if file_path:
            self._import_fname.setText(file_path)

    def _on_choose_file(self):
        """Handle file selection."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            str(Path(__file__).parent / "data" / "samples"),
            "文本文件 (*.md *.txt);;所有文件 (*.*)"
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
        
        # Try to read from file path
        content = ""
        if fname and Path(fname).exists():
            try:
                with open(fname, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取文件失败: {e}")
                return
        else:
            # Use pasted content
            content = self._import_paste.toPlainText()
        
        if not content.strip():
            QMessageBox.warning(self, "错误", "内容为空，请提供学习材料")
            return
        
        # Show progress
        self._import_progress.setVisible(True)
        self._import_progress.setValue(10)
        self._import_status_label.setText("正在分析文本...")
        self._import_status_label.repaint()
        
        # Run extraction in background thread
        self._extract_worker = ExtractWorker(content, fname, self.llm_client)
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
