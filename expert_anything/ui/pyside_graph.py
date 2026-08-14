"""PySide6 interactive knowledge-graph widget for ExpertAnything.

Reuses the layout math from ``core.graph_viz`` (ego-network selection,
radial focus layout, layered full-network layout) so the desktop graph stays
consistent with the offline PNG renderer and with the retired Flet widget:

- **Full view**: layered/grid layout of the (capped) whole network.
- **Focus view**: single-click a node to re-layout its ego-network radially
  (focus + relation neighbours, path neighbours as faint context); click
  empty space to return to the full view.
- **Mastery colours**: green >= 0.6, amber >= 0.3, orange > 0, grey unseen.
- **Anomaly highlight**: orange border on concepts touched by open anomalies.
- **Recommended-next highlight**: cyan border.
- **Interaction**: drag to pan, wheel to zoom, double-click to start teaching.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from expert_anything.core.graph_viz import (
    BOX_W,
    BOX_H,
    FBOX_W,
    FBOX_H,
    CBOX_W,
    CBOX_H,
    MARGIN,
    _border_point,
    _layered_layout,
    _radial_layout,
    _select_nodes,
)
from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.teacher import anomaly_concept_ids

# --------------------------------------------------------------------------- #
# colour palette (consistent with core/graph_viz + the retired Flet widget)
# --------------------------------------------------------------------------- #
_FILL_GREY = "#E1E4E8"        # unseen
_FILL_GREEN = "#C5E6C6"       # mastered  >= 0.6
_FILL_AMBER = "#FDEBCE"       # partial   >= 0.3
_FILL_ORANGE = "#FAD6CA"      # weak      > 0
_FILL_FOCUS = "#81D4FA"       # focused concept
_FILL_CONTEXT = "#E0E4E8"     # outer-ring path context

_BORDER_NORMAL = "#78909C"
_BORDER_FOCUS = "#0284C7"
_BORDER_ANOMALY = "#E67828"
_BORDER_CONTEXT = "#B0BEC5"

_EDGE_NORMAL = "#8296A5"
_EDGE_FOCUS = "#0284C7"
_EDGE_ANOMALY = "#E67828"
_EDGE_CONTEXT = "#C8D0D6"

_RADIUS = 10


def _hex(color: str) -> QColor:
    return QColor(color)


def _mastery_fill(m: float) -> QColor:
    if m >= 0.6:
        return _hex(_FILL_GREEN)
    if m >= 0.3:
        return _hex(_FILL_AMBER)
    if m > 0:
        return _hex(_FILL_ORANGE)
    return _hex(_FILL_GREY)


class KnowledgeGraphView(QGraphicsView):
    """Interactive, pan/zoom knowledge graph for the desktop app."""

    concept_clicked = Signal(str)   # double-click -> teach (concept name)
    node_single_clicked = Signal(str)  # single-click on a node (concept id)
    view_changed = Signal()         # focus/full mode changed (for status label)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self._asset: KnowledgeAsset | None = None
        self._mastery: dict[str, float] = {}
        self._anomaly_ids: set[str] = set()
        self._grey_ids: set[str] = set()
        self._current_id: str | None = None
        self._focus_id: str | None = None
        self._nodes: list[tuple[str, str, str]] = []   # (cid, name, role)
        self._pos: dict[str, QPointF] = {}
        self._box: dict[str, tuple[float, float]] = {}  # cid -> (w, h)
        self._node_items: dict[str, QGraphicsPathItem] = {}
        self._edges: list[tuple[str, str, str]] = []

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def set_asset(
        self,
        asset: KnowledgeAsset,
        mastery_map: dict[str, float] | None = None,
        anomaly_ids: set[str] | None = None,
        current_id: str | None = None,
        grey_ids: set[str] | None = None,
    ) -> None:
        """Bind the asset and render the full network (no focus).

        ``grey_ids``: concept ids rendered grey (e.g. concepts from other
        assets in the global map) so the map covers a wider scope while the
        current asset stays colourful.
        """
        self._asset = asset
        self._mastery = mastery_map or {}
        self._anomaly_ids = anomaly_ids or set()
        self._grey_ids = grey_ids or set()
        self._current_id = current_id
        self._focus_id = None
        self.render_graph()

    def render_graph(self, focus_id: str | None = None) -> None:
        """Re-render. ``focus_id=None`` draws the full network."""
        if self._asset is None:
            return
        self._focus_id = focus_id
        nodes, edges = _select_nodes(self._asset, focus_id)
        self._nodes = nodes
        self._edges = edges

        # layout --------------------------------------------------------
        if focus_id is None:
            pos = _layered_layout(nodes, edges)
            xs = [p[0] for p in pos.values()]
            ys = [p[1] for p in pos.values()]
            w = int(max(xs) + BOX_W / 2 + MARGIN) if xs else 400
            h = int(max(ys) + BOX_H / 2 + MARGIN) if ys else 300
        else:
            pos, w, h = _radial_layout(nodes, focus_id)

        self._pos = {cid: QPointF(x, y) for cid, (x, y) in pos.items()}
        self._box = {
            cid: (FBOX_W, FBOX_H) if role == "focus"
            else (CBOX_W, CBOX_H) if role == "context"
            else (BOX_W, BOX_H)
            for cid, _n, role in nodes
        }

        # rebuild scene ------------------------------------------------
        scene = self.scene()
        scene.clear()
        self._node_items = {}

        def _box_of(cid: str) -> tuple[float, float]:
            return self._box.get(cid, (BOX_W, BOX_H))

        # edges first (behind nodes)
        for s_id, t_id, label in edges:
            if s_id not in self._pos or t_id not in self._pos:
                continue
            p1 = self._pos[s_id]
            p2 = self._pos[t_id]
            hw1, hh1 = _box_of(s_id)[0] / 2, _box_of(s_id)[1] / 2
            hw2, hh2 = _box_of(t_id)[0] / 2, _box_of(t_id)[1] / 2
            b1 = _border_point((p1.x(), p1.y()), (hw1, hh1), (p2.x(), p2.y()))
            b2 = _border_point((p2.x(), p2.y()), (hw2, hh2), (p1.x(), p1.y()))

            is_ctx = label == "路径相邻"
            is_fe = (s_id == focus_id or t_id == focus_id) and focus_id is not None
            is_ae = s_id in self._anomaly_ids or t_id in self._anomaly_ids
            if is_ctx:
                color, width = _EDGE_CONTEXT, 1.5
            elif is_fe:
                color, width = _EDGE_FOCUS, 2.5
            elif is_ae:
                color, width = _EDGE_ANOMALY, 2.5
            else:
                color, width = _EDGE_NORMAL, 1.5

            line = QGraphicsLineItem(b1[0], b1[1], b2[0], b2[1])
            pen = QPen(_hex(color), width)
            line.setPen(pen)
            scene.addItem(line)

            if label and not is_ctx:
                mx, my = (b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2
                lbl = QGraphicsSimpleTextItem(label)
                lbl.setBrush(QColor("#546E7A"))
                f = QFont()
                f.setPointSize(8)
                lbl.setFont(f)
                lbl.setPos(mx - lbl.boundingRect().width() / 2,
                           my - lbl.boundingRect().height() / 2)
                scene.addItem(lbl)

        # nodes
        for cid, name, role in nodes:
            if cid not in self._pos:
                continue
            c = self._pos[cid]
            bw, bh = _box_of(cid)
            rect = QRectF(-bw / 2, -bh / 2, bw, bh)

            if role == "focus":
                fill = _hex(_FILL_FOCUS)
                border, bwidth = _hex(_BORDER_FOCUS), 3
            elif role == "context":
                fill = _hex(_FILL_CONTEXT)
                border, bwidth = _hex(_BORDER_CONTEXT), 1
            else:
                if cid in self._grey_ids:
                    fill = _hex(_FILL_GREY)
                    border, bwidth = _hex(_BORDER_CONTEXT), 1
                else:
                    fill = _mastery_fill(self._mastery.get(cid, 0.0))
                    if cid in self._anomaly_ids:
                        border, bwidth = _hex(_BORDER_ANOMALY), 3
                    elif cid == self._current_id:
                        border, bwidth = _hex(_BORDER_FOCUS), 3
                    else:
                        border, bwidth = _hex(_BORDER_NORMAL), 1

            path = QPainterPath()
            path.addRoundedRect(rect, _RADIUS, _RADIUS)
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(fill))
            item.setPen(QPen(border, bwidth))
            item.setPos(c)
            item.setData(0, cid)
            item.setData(1, name)
            item.setToolTip(name)
            scene.addItem(item)
            self._node_items[cid] = item

            text = QGraphicsSimpleTextItem(name)
            text.setBrush(QColor("#212529"))
            tf = QFont()
            tf.setPointSize(10 if role == "focus" else 8)
            text.setFont(tf)
            text.setParentItem(item)
            text.setPos(-text.boundingRect().width() / 2,
                        -text.boundingRect().height() / 2)

        scene.setSceneRect(0, 0, max(w, 400), max(h, 300))
        self.resetTransform()
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.view_changed.emit()

    def focus_concept(self, concept_id: str) -> None:
        """Radial ego-network centred on ``concept_id``."""
        self.render_graph(focus_id=concept_id)

    def reset_focus(self) -> None:
        """Back to the full-network view."""
        self.render_graph(focus_id=None)

    def is_focused(self) -> bool:
        return self._focus_id is not None

    # ------------------------------------------------------------------ #
    # interaction
    # ------------------------------------------------------------------ #
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = self.transform().m11() * factor
        if 0.3 <= new_zoom <= 4.0:
            self.scale(factor, factor)
        event.accept()

    def _item_concept(self, pos) -> tuple[str, str] | None:
        item = self.itemAt(pos)
        if item is None:
            return None
        # text labels are children of the node path item
        node = item
        while node is not None and node.data(0) is None:
            node = node.parentItem()
        if node is not None and node.data(0) is not None:
            return node.data(0), node.data(1)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._item_concept(event.pos())
            if hit is not None:
                cid, _name = hit
                if self._focus_id == cid:
                    self.reset_focus()
                else:
                    self.focus_concept(cid)
                self.node_single_clicked.emit(cid)
                event.accept()
                return
            # clicked empty space -> back to full view
            if self._focus_id is not None:
                self.reset_focus()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        hit = self._item_concept(event.pos())
        if hit is not None:
            cid, name = hit
            # make sure the ego view is shown for the concept being taught
            if self._focus_id != cid:
                self.focus_concept(cid)
            self.concept_clicked.emit(name)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
