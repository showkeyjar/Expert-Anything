# -*- coding: utf-8 -*-
"""Round 20 tests: 四项 UX 反馈的回归守卫。

1. SVG 预览保持宽高比（文字不再被压扁）+ 点击放大到原生分辨率
2. 概念地图双击下钻（任意节点恒可下钻）+ 面包屑逐级回退
3. 首屏折叠纪律（次级卡片进「更多」，默认收起但一键可开）
4. 教学轻量默认模式（一页卡 + 「想深入」折叠区）
"""
import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("EXPERTANYTHING_DATA_DIR", str(PROJECT / "data" / "_demo"))

from tests.util import ensure_demo, prepare_app  # noqa: E402

ensure_demo()
prepare_app()

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from expert_anything.core.i18n import t as _t  # noqa: E402
from expert_anything.ui.widgets._helpers import (  # noqa: E402
    CollapsibleSection,
    SvgScenePreview,
)

SCENE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="380" '
    'viewBox="0 0 720 380"><rect width="720" height="380" fill="#FFFFFF"/>'
    '<text x="20" y="40" font-size="16" fill="#000000">hello</text></svg>'
)


def _flush() -> None:
    """Deferred-delete queued widgets before counting children."""
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class TestSvgPreviewAspect(unittest.TestCase):
    """SVG 被拉伸填满是「文字压扁」的根因，必须保持宽高比。"""

    def test_preview_keeps_aspect_and_height_follows_width(self):
        preview = SvgScenePreview()
        self.addCleanup(preview.deleteLater)
        self.assertTrue(preview.load_svg(SCENE_SVG, zoom_title="t"))
        self.assertAlmostEqual(preview._aspect, 720 / 380, places=3)
        self.assertTrue(preview.hasHeightForWidth())
        # 高度必须随宽度等比变化（布局不再把它压扁）
        self.assertAlmostEqual(
            preview.heightForWidth(360), 360 / (720 / 380), delta=2
        )
        self.assertEqual(
            preview.renderer().aspectRatioMode(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def test_zoom_dialog_never_shrinks_below_viewbox(self):
        from expert_anything.ui.widgets._helpers import SvgZoomDialog

        dlg = SvgZoomDialog(SCENE_SVG, title="t")
        self.addCleanup(dlg.deleteLater)
        self.assertGreaterEqual(dlg.width(), 720)
        self.assertGreaterEqual(dlg.height(), 380)


class TestCollapsibleSection(unittest.TestCase):
    """共享折叠组件：默认收起、内容不删除、可展开。"""

    def test_body_hidden_by_default_and_kept(self):
        sec = CollapsibleSection("更多")
        self.addCleanup(sec.deleteLater)
        child = QWidget()
        sec.add(child)
        self.assertFalse(sec.is_expanded())
        self.assertEqual(sec.body_layout().count(), 1)
        self.assertFalse(child.isVisibleTo(sec))
        sec.set_expanded(True)
        self.assertTrue(sec.is_expanded())
        self.assertTrue(child.isVisibleTo(sec))


class TestTeachLightweight(unittest.TestCase):
    """问题4：默认一页卡，测验/练习等重流程收进「想深入」。"""

    def _view(self, payload: dict):
        from expert_anything.ui.widgets.teach_widgets import TeachResultView

        view = TeachResultView(payload)
        view.show()
        self.addCleanup(view.deleteLater)
        return view

    def test_quick_card_shows_definition_and_deep_is_folded(self):
        view = self._view(
            {
                "concept": "X",
                "definition": "核心定义正文",
                "explanation": "完整讲解正文",
                "example": "一个例子",
            }
        )
        texts = [lbl.text() for lbl in view.findChildren(QLabel)]
        self.assertIn(_t("quick_def_title"), texts)
        self.assertIn("核心定义正文", texts)
        self.assertIn("一个例子", texts)
        # 30 秒一页卡之外的重内容默认折叠
        self.assertTrue(view._deep_host.isHidden())
        self.assertIn(_t("deep_dive_toggle"), view._deep_btn.text())

    def test_toggle_opens_deep_section(self):
        view = self._view({"concept": "X", "explanation": "讲解"})
        self.assertTrue(view._deep_host.isHidden())
        view._deep_btn.click()
        _flush()
        self.assertFalse(view._deep_host.isHidden())
        self.assertIn("▾", view._deep_btn.text())

    def test_quiz_auto_expands_the_deep_section(self):
        view = self._view({"concept": "X", "explanation": "讲解"})
        # 模拟「从地图卡直接快速自测」：深入区还收着
        view._deep_host.setVisible(False)
        view.show_quiz(
            {"type": "true_false", "question": "测验题面", "correct": True}
        )
        _flush()
        self.assertFalse(view._deep_host.isHidden())
        texts = [lbl.text() for lbl in view.findChildren(QLabel)]
        self.assertIn("测验题面", texts)


class TestDrillDown(unittest.TestCase):
    """问题2：任意节点双击都能下钻，面包屑可逐级回退。"""

    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.win = load_main_window()

    def test_drill_enters_any_node_and_breadcrumb_returns(self):
        graph = self.win._graph_view_ref()
        asset = self.win.get_asset()
        if asset is None or len(asset.concepts) < 2:
            self.skipTest("demo asset needs at least two concepts")
        graph.set_asset(asset)
        graph.enable_drill_down()

        first, second = asset.concepts[0].id, asset.concepts[1].id
        self.assertTrue(graph.drill_down(first))
        self.assertEqual(graph.drill_path(), [first])
        ids = [node[0] for node in graph._nodes]
        self.assertIn(first, ids)
        self.assertGreaterEqual(len(ids), 2)  # 子图不只是孤立节点

        # 第二个节点同样可下钻（旧版无层级子节点时会静默失败）
        self.assertTrue(graph.drill_down(second))
        self.assertEqual(graph.drill_path(), [first, second])

        graph.drill_to(1)
        self.assertEqual(graph.drill_path(), [first])
        graph.drill_to(0)
        self.assertEqual(graph.drill_path(), [])


class TestFirstScreenFolds(unittest.TestCase):
    """问题3：首屏只留核心，次级内容进「更多」折叠区。"""

    @classmethod
    def setUpClass(cls):
        from tests.util import load_main_window

        cls.win = load_main_window()

    def test_knowledge_view_folds_secondary_cards(self):
        from expert_anything.ui.views.knowledge_view import KnowledgeView

        view = KnowledgeView(self.win)
        self.addCleanup(view.deleteLater)
        sec = getattr(view, "_more_section", None)
        self.assertIsNotNone(sec, "knowledge view ships a 「更多」 fold")
        self.assertFalse(sec.is_expanded())
        self.assertGreaterEqual(sec.body_layout().count(), 1)

    def test_import_guide_collapses_once_assets_exist(self):
        from expert_anything.ui.views.import_view import ImportView

        view = ImportView(self.win)
        self.addCleanup(view.deleteLater)
        sections = view.findChildren(CollapsibleSection)
        self.assertTrue(sections, "guide card is a collapsible section")
        self.assertFalse(
            sections[0].is_expanded(),
            "returning users (assets present) get a quiet first screen",
        )

    def test_teacher_view_fold_defaults_collapsed(self):
        from expert_anything.ui.views.teacher_view import TeacherView

        view = TeacherView(self.win)
        self.addCleanup(view.deleteLater)
        sec = getattr(view, "_more_section", None)
        self.assertIsNotNone(sec)
        self.assertFalse(sec.is_expanded())


class TestDecoderGeometrySafety(unittest.TestCase):
    """教学图解曾在「步骤超限」时退化成无坐标 spec，渲染 KeyError: 'x'。"""

    def _asset(self):
        import json

        from expert_anything.core.models import KnowledgeAsset

        path = (
            Path(os.environ["EXPERTANYTHING_DATA_DIR"])
            / "assets"
            / "a20260908-002.json"
        )
        return KnowledgeAsset.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def test_dense_fallback_scene_keeps_geometry_and_step_budget(self):
        from expert_anything.core import decoder
        from expert_anything.core.models import Relation

        asset = self._asset()
        concept = asset.concepts[0]
        concept.definition = "甲。乙。丙。丁。"
        concept.evidence = ["证据一" * 10, "证据二" * 10]
        asset.relations = [
            Relation(
                id=f"rel{i}",
                source=concept.id,
                target=other.id,
                label="关联",
                type="part_of",
            )
            for i, other in enumerate(asset.concepts[1:6])
        ] + list(asset.relations)

        spec = decoder.fallback_scene(asset, concept)
        self.assertLessEqual(len(spec["steps"]), decoder.MAX_STEPS)
        self.assertTrue(
            all("x" in node for node in spec["nodes"]),
            "every node must carry geometry before it reaches the renderer",
        )
        self.assertEqual(
            len(decoder.render_step_svgs(spec)), len(spec["steps"])
        )

    def test_renderer_heals_geometry_less_spec(self):
        from expert_anything.core import decoder

        bare = {
            "title": "x",
            "nodes": [{"id": "a", "label": "甲"}, {"id": "b", "label": "乙"}],
            "edges": [{"from": "a", "to": "b"}],
            "steps": [],
        }
        svg = decoder.render_svg(bare)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(all("x" in node for node in bare["nodes"]))


if __name__ == "__main__":
    unittest.main()
