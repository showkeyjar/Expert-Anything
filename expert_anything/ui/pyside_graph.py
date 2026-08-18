"""PySide6 interactive knowledge-graph widget for ExpertAnything.

A *living* concept network (mind-map style):

- **Force-directed layout**: in full-map mode the nodes drift under a
  repulsion + spring + gravity simulation until they settle, then keep a
  subtle floating motion — the map feels alive, not static.
- **Drag nodes**: grab any node and pull it; connected neighbours follow
  via springs.
- **Roam**: hover highlights neighbours, single-click opens the concept
  panel and re-centres the ego network on it, double-click teaches.
- **Scope**: current book colourful, other assets grey (``grey_ids``).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
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
from expert_anything.core.i18n import t as _t
from expert_anything.core.learner import topic_clusters
from expert_anything.core.models import KnowledgeAsset

# --------------------------------------------------------------------------- #
# colour palette (consistent with core/graph_viz)
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


def _clustered_layout(
    nodes: list[tuple[str, str, str]],
    asset: KnowledgeAsset,
) -> tuple[dict[str, tuple[float, float]], int, int]:
    """Cluster-aware initial layout: each topic cluster gets its own
    territory on an outer ring; members scatter around their cluster centre.

    Falls back to a plain circular scatter if clustering is not available or
    every node ends up unassigned.
    """
    node_ids = [cid for cid, _n, _r in nodes]
    node_set = set(node_ids)
    try:
        clusters = topic_clusters(asset)
    except Exception:
        clusters = []

    # cid -> cluster index (only for displayed nodes)
    cid_to_clidx: dict[str, int] = {}
    for i, cl in enumerate(clusters):
        for cid in cl.get("concept_ids", []) or []:
            if cid in node_set:
                cid_to_clidx[cid] = i

    cl_groups: dict[int, list[str]] = {}
    unassigned: list[str] = []
    for cid in node_ids:
        if cid in cid_to_clidx:
            cl_groups.setdefault(cid_to_clidx[cid], []).append(cid)
        else:
            unassigned.append(cid)
    # singletons are not a "territory" — scatter them with unassigned
    singleton_clusters = [k for k, v in cl_groups.items() if len(v) < 2]
    for k in singleton_clusters:
        for cid in cl_groups.pop(k):
            unassigned.append(cid)

    # nothing clustered at all -> circular fallback
    if not cl_groups and not unassigned:
        n = len(node_ids)
        radius = 70 + 26 * n
        cx, cy = 700.0, 450.0
        pos = {}
        for i, cid in enumerate(node_ids):
            ang = -math.pi / 2 + 2 * math.pi * i / max(1, n)
            pos[cid] = (cx + radius * math.cos(ang), cy + radius * math.sin(ang))
        w = h = int(radius * 2 + 500)
        return pos, w, h

    cx, cy = 700.0, 450.0
    visible_clusters = sorted(cl_groups.keys())
    n_slots = len(visible_clusters) + (1 if unassigned else 0)
    outer_r = 150 + 80 * max(1, n_slots)
    pos: dict[str, tuple[float, float]] = {}
    centres: dict[int, tuple[float, float]] = {}
    for k, cl_idx in enumerate(visible_clusters):
        ang = -math.pi / 2 + 2 * math.pi * k / max(1, n_slots)
        centres[cl_idx] = (cx + outer_r * math.cos(ang), cy + outer_r * math.sin(ang))
    if unassigned:
        ang = -math.pi / 2 + 2 * math.pi * len(visible_clusters) / max(1, n_slots)
        centres[-1] = (cx + outer_r * math.cos(ang), cy + outer_r * math.sin(ang))

    for cl_idx, members in cl_groups.items():
        hx, hy = centres.get(cl_idx, (cx, cy))
        nm = len(members)
        for j, cid in enumerate(members):
            if nm == 1:
                pos[cid] = (hx, hy)
            else:
                r = 38 + 16 * nm
                a = 2 * math.pi * j / max(1, nm)
                pos[cid] = (hx + r * math.cos(a), hy + r * math.sin(a))
    for j, cid in enumerate(unassigned):
        hx, hy = centres.get(-1, (cx, cy))
        nm = len(unassigned)
        if nm == 1:
            pos[cid] = (hx, hy)
        else:
            r = 38 + 16 * nm
            a = 2 * math.pi * j / max(1, nm)
            pos[cid] = (hx + r * math.cos(a), hy + r * math.sin(a))

    w = h = int(outer_r * 2 + 360)
    return pos, w, h


def _cluster_regions(
    nodes: list[tuple[str, str, str]],
    asset: KnowledgeAsset,
    pos: dict[str, tuple[float, float]],
) -> list[dict]:
    """Padded bounding rect per topic cluster — used to draw faint
    territory backgrounds behind the nodes."""
    node_set = set(cid for cid, _n, _r in nodes)
    try:
        clusters = topic_clusters(asset)
    except Exception:
        return []
    regions: list[dict] = []
    for i, cl in enumerate(clusters):
        members = [cid for cid in (cl.get("concept_ids") or []) if cid in node_set and cid in pos]
        # singletons are not territories — skip region drawing
        if len(members) < 2:
            continue
        pts = [pos[cid] for cid in members]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        pad = 58
        minx, miny = min(xs) - pad, min(ys) - pad
        maxx, maxy = max(xs) + pad, max(ys) + pad
        regions.append({
            "label": cl.get("name", "Topic"),
            "rect": QRectF(minx, miny, maxx - minx, maxy - miny),
            "idx": i,
            "hub_id": cl.get("id"),
            "members": members,
        })
    return regions


# physics tuning --------------------------------------------------------------
_PHYS = {
    "repulsion": 6000.0,   # k_rep (gentler so nodes do not scatter far)
    "spring": 0.015,       # k_spring
    "rest": 165.0,         # rest length
    "gravity": 0.0015,     # pull to centre
    "damp": 0.90,          # heavier damping -> quick settle
    "energy_stop": 0.06,   # settle threshold
    "settle_frames": 25,   # consecutive calm frames before sleeping
}
_FLOAT_AMP = 0.4           # subtle drifting after settling (never disturbs clicks)


class KnowledgeGraphView(QGraphicsView):
    """Interactive, living knowledge graph."""

    concept_clicked = Signal(str)          # double-click -> teach (concept name)
    node_single_clicked = Signal(str)      # single-click on a node (concept id)
    view_changed = Signal()                # focus/full mode changed

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
        self._nodes: list[tuple[str, str, str]] = []
        self._edges: list[tuple[str, str, str]] = []
        self._node_items: dict[str, QGraphicsPathItem] = {}
        self._edge_items: dict[tuple[str, str], QGraphicsLineItem] = {}
        self._hover_cid: str | None = None

        # physics state: cid -> [x, y, vx, vy]
        self._physics: dict[str, list[float]] = {}
        self._phys_timer = QTimer(self)
        self._phys_timer.setInterval(16)
        self._phys_timer.timeout.connect(self._physics_step)
        self._float_timer = QTimer(self)
        self._float_timer.setInterval(50)
        self._float_timer.timeout.connect(self._float_step)
        self._calm_frames = 0
        self._tick = 0
        self._phases: dict[str, float] = {}
        self._freqs: dict[str, float] = {}

        # cognitive-map analytics: node importance + learning frontier
        self._centrality: dict[str, float] = {}
        self._frontier_ids: set[str] = set()

        # cluster territories (drawn behind nodes)
        self._cluster_regions: list[dict] = []
        self._region_items: list[tuple] = []  # (rect_item, label_item)

        # dragging
        self._drag_cid: str | None = None
        self._drag_start = QPointF()
        self._dragged = False

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
        """Bind the asset and render the full network (living layout)."""
        self._asset = asset
        self._mastery = mastery_map or {}
        self._anomaly_ids = anomaly_ids or set()
        self._grey_ids = grey_ids or set()
        self._current_id = current_id
        self._focus_id = None
        self.render_graph()

    def render_graph(self, focus_id: str | None = None) -> None:
        """(Re)render. focus=None -> full network with force-directed motion."""
        if self._asset is None:
            return
        self._phys_timer.stop()
        self._float_timer.stop()
        self._drag_cid = None
        self._focus_id = focus_id
        nodes, edges = _select_nodes(self._asset, focus_id)
        self._nodes = nodes
        self._edges = edges

        # cognitive-map analytics: hub sizing + learning frontier
        self._centrality = self._compute_centrality()
        self._frontier_ids = self._compute_frontier()

        # layout ----------------------------------------------------------
        if focus_id is None:
            # cluster-aware initial layout: each topic cluster gets its own
            # territory on an outer ring so the map reads as named regions,
            # not a featureless scatter. Physics then settles within each
            # territory without breaking the regional structure.
            pos, w, h = _clustered_layout(nodes, self._asset)
            self._cluster_regions = _cluster_regions(nodes, self._asset, pos)
        else:
            pos, w, h = _radial_layout(nodes, focus_id)
            self._cluster_regions = []

        self._rebuild_scene(pos, w, h)

        if focus_id is None:
            self._start_physics()

    def focus_concept(self, concept_id: str) -> None:
        """Radial ego-network centred on ``concept_id`` (motion sleeps)."""
        self.render_graph(focus_id=concept_id)

    def reset_focus(self) -> None:
        """Back to the full living network."""
        self.render_graph(focus_id=None)

    def is_focused(self) -> bool:
        return self._focus_id is not None

    # ------------------------------------------------------------------ #
    # cognitive-map analytics
    # ------------------------------------------------------------------ #
    def _compute_centrality(self) -> dict[str, float]:
        """Degree-based importance: hubs (more connections) render larger."""
        deg: dict[str, int] = {}
        for s_id, t_id, _label in self._edges:
            deg[s_id] = deg.get(s_id, 0) + 1
            deg[t_id] = deg.get(t_id, 0) + 1
        if not deg:
            return {}
        maxd = max(deg.values())
        out: dict[str, float] = {}
        for cid, _name, _role in self._nodes:
            d = deg.get(cid, 0)
            f = 0.85 + 0.9 * (d / maxd if maxd else 0.0)
            out[cid] = max(0.85, min(1.9, f))
        return out

    def _compute_frontier(self) -> set[str]:
        """Learning-frontier concepts: unstudied but buildable from what you
        already know (an adjacent mastered concept). On a fresh map with nothing
        mastered yet, the highest-centrality hubs become the starting frontier.
        """
        if not self._asset:
            return set()
        neigh: dict[str, set[str]] = {cid: set() for cid, _n, _r in self._nodes}
        for s_id, t_id, _label in self._edges:
            if s_id in neigh:
                neigh[s_id].add(t_id)
            if t_id in neigh:
                neigh[t_id].add(s_id)
        mastered = {
            cid for cid, _n, _r in self._nodes
            if not str(cid).startswith("ext:") and self._mastery.get(cid, 0.0) >= 0.6
        }
        unstudied = [
            cid for cid, _n, _r in self._nodes
            if not str(cid).startswith("ext:")
            and self._mastery.get(cid, 0.0) < 0.3
        ]
        frontier: set[str] = set()
        if mastered:
            for cid in unstudied:
                if any(n in mastered for n in neigh.get(cid, set())):
                    frontier.add(cid)
        else:
            ranked = sorted(
                unstudied, key=lambda c: -self._centrality.get(c, 1.0)
            )
            frontier = set(ranked[: max(3, len(ranked) // 4 + 1)])
        return frontier

    # ------------------------------------------------------------------ #
    # scene building
    # ------------------------------------------------------------------ #
    def _rebuild_scene(self, pos: dict[str, tuple[float, float]], w: int, h: int) -> None:
        scene = self.scene()
        scene.clear()
        self._node_items = {}
        self._edge_items = {}
        self._physics = {}
        self._phases = {}
        self._freqs = {}

        def _box_of(cid: str) -> tuple[float, float]:
            role = next((r for cc, _n, r in self._nodes if cc == cid), "normal")
            if role == "focus":
                return FBOX_W, FBOX_H
            if role == "context":
                return CBOX_W, CBOX_H
            f = self._centrality.get(cid, 1.0)
            return BOX_W * f, BOX_H * f

        # cluster territories (faint background; drawn first / lowest z) ----
        self._region_items = []
        for _i, reg in enumerate(self._cluster_regions):
            rect = reg["rect"]
            rpath = QPainterPath()
            rpath.addRoundedRect(rect, 18, 18)
            ritem = QGraphicsPathItem(rpath)
            ritem.setBrush(QBrush(QColor(0x66, 0x9A, 0xD6, 32)))
            pen = QPen(QColor(0x4A, 0x7A, 0xB0, 170), 1.4)
            pen.setStyle(Qt.PenStyle.DashLine)
            ritem.setPen(pen)
            ritem.setZValue(-10)
            ritem.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            scene.addItem(ritem)
            label = QGraphicsSimpleTextItem(reg["label"])
            lf = QFont()
            lf.setPointSize(9)
            lf.setBold(True)
            label.setFont(lf)
            label.setBrush(QColor(0x2A, 0x4A, 0x6E, 220))
            label.setPos(rect.x() + 10, rect.y() + 4)
            label.setZValue(-9)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            scene.addItem(label)
            self._region_items.append((ritem, label))

        # edges ------------------------------------------------------------
        for s_id, t_id, _label in self._edges:
            if s_id not in pos or t_id not in pos:
                continue
            key = tuple(sorted((s_id, t_id)))
            line = QGraphicsLineItem()
            line.setPen(QPen(_hex(_EDGE_NORMAL), 1.5))
            scene.addItem(line)
            self._edge_items[key] = line

        # nodes -------------------------------------------------------------
        for cid, name, role in self._nodes:
            if cid not in pos:
                continue
            c = pos[cid]
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
            item.setPos(QPointF(*c))
            item.setData(0, cid)
            item.setData(1, name)
            definition = next(
                (c.definition or c.summary for c in self._asset.concepts
                 if c.id == cid), "")
            tip = name
            if definition:
                tip += "\n\n" + definition[:120]
            # frontier nodes get an explicit affordance — the legend explains
            # the orange dashed ring, but the tooltip removes any guesswork
            if cid in self._frontier_ids:
                tip = "🎯 " + _t("frontier_tip_prefix") + "\n\n" + tip
            item.setToolTip(tip)
            scene.addItem(item)
            self._node_items[cid] = item

            # learning-frontier ring (does not capture mouse events)
            if cid in self._frontier_ids:
                rw, rh = bw + 12, bh + 12
                rpath = QPainterPath()
                rpath.addRoundedRect(
                    QRectF(-rw / 2, -rh / 2, rw, rh), _RADIUS + 3, _RADIUS + 3
                )
                ring = QGraphicsPathItem(rpath)
                rpen = QPen(_hex(_BORDER_ANOMALY), 2.5)
                rpen.setStyle(Qt.PenStyle.DashLine)
                ring.setPen(rpen)
                ring.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                ring.setPos(QPointF(*c))
                ring.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                ring.setZValue(item.zValue() - 1)
                scene.addItem(ring)

            # mastery growth arc: a thin progress ring around the node that
            # visually shows how much of this concept the learner has acquired.
            # drawn after the frontier ring so it sits on top of node fill.
            mastery = self._mastery.get(cid, 0.0)
            if mastery > 0 and role not in ("focus", "context") and cid not in self._grey_ids:
                if mastery >= 0.6:
                    arc_color = QColor(0x2E, 0x7D, 0x32)
                elif mastery >= 0.3:
                    arc_color = QColor(0xC8, 0x82, 0x1E)
                else:
                    arc_color = QColor(0xE6, 0x78, 0x28)
                arc_r = max(bw, bh) / 2 + 4
                arc_rect = QRectF(-arc_r, -arc_r, arc_r * 2, arc_r * 2)
                arc_path = QPainterPath()
                # start at 12 o'clock, sweep clockwise proportional to mastery
                arc_path.arcMoveTo(arc_rect, 90)
                arc_path.arcTo(arc_rect, 90, -360 * mastery)
                arc_item = QGraphicsPathItem(arc_path)
                apen = QPen(arc_color, 3)
                apen.setCapStyle(Qt.PenCapStyle.RoundCap)
                arc_item.setPen(apen)
                arc_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                arc_item.setPos(QPointF(*c))
                arc_item.setZValue(item.zValue() + 1)
                arc_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                scene.addItem(arc_item)

            text = QGraphicsSimpleTextItem(name)
            text.setBrush(QColor("#212529"))
            tf = QFont()
            tf.setPointSize(12 if role == "focus" else 10)
            tf.setBold(role == "focus")
            text.setFont(tf)
            text.setParentItem(item)
            text.setPos(-text.boundingRect().width() / 2,
                        -text.boundingRect().height() / 2)

            self._physics[cid] = [float(c[0]), float(c[1]), 0.0, 0.0]
            self._phases[cid] = (hash(cid) % 628) / 100.0
            self._freqs[cid] = 0.8 + (hash(cid) % 40) / 100.0

        # scene geometry: generous canvas for the drifting motion
        canvas_w = max(w, 1400)
        canvas_h = max(h, 900)
        scene.setSceneRect(0, 0, canvas_w, canvas_h)
        self.resetTransform()
        self.fit_content()
        self._hover_cid = None
        self._update_edges()
        self.view_changed.emit()

    # ------------------------------------------------------------------ #
    # zoom control
    # ------------------------------------------------------------------ #
    def fit_content(self) -> None:
        """Zoom so the node cluster fills the viewport (readable by default)."""
        scene = self.scene()
        if not self._node_items:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            return
        content = QRectF()
        for item in self._node_items.values():
            content = content.united(item.sceneBoundingRect())
        content.adjust(-70, -70, 70, 70)
        self.fitInView(content, Qt.AspectRatioMode.KeepAspectRatio)
        # guarantee a readable minimum zoom (nodes ~150px+ wide, text legible)
        if self.transform().m11() < 0.85:
            self.scale(0.85 / self.transform().m11(),
                       0.85 / self.transform().m11())

    def zoom_in(self) -> None:
        self.scale(1.25, 1.25)

    def zoom_out(self) -> None:
        new_zoom = self.transform().m11() * (1 / 1.25)
        if new_zoom >= 0.2:
            self.scale(1 / 1.25, 1 / 1.25)

    # ------------------------------------------------------------------ #
    # force-directed physics
    # ------------------------------------------------------------------ #
    def _start_physics(self) -> None:
        self._calm_frames = 0
        self._tick = 0
        if self._physics:
            self._phys_timer.start()

    def _physics_step(self) -> None:
        if self._focus_id is not None or len(self._physics) < 2:
            self._phys_timer.stop()
            return
        P = _PHYS
        cids = list(self._physics.keys())
        center = self.scene().sceneRect().center()

        energy = 0.0
        for a in cids:
            if a == self._drag_cid:
                continue  # user holds this node
            x, y, vx, vy = self._physics[a]
            fx = fy = 0.0
            for b in cids:
                if a == b:
                    continue
                bx, by, _bvx, _bvy = self._physics[b]
                dx, dy = x - bx, y - by
                d2 = dx * dx + dy * dy + 1e-6
                d = d2 ** 0.5
                f = P["repulsion"] / d2
                fx += f * dx / d
                fy += f * dy / d
            for s, t, _label in self._edges:
                if s == a:
                    b = t
                elif t == a:
                    b = s
                else:
                    continue
                if b not in self._physics:
                    continue
                bx, by, _bvx, _bvy = self._physics[b]
                dx, dy = bx - x, by - y
                d = (dx * dx + dy * dy) ** 0.5 + 1e-6
                f = P["spring"] * (d - P["rest"])
                fx += f * dx / d
                fy += f * dy / d
            fx += P["gravity"] * (center.x() - x)
            fy += P["gravity"] * (center.y() - y)

            vx = (vx + fx) * P["damp"]
            vy = (vy + fy) * P["damp"]
            x += vx
            y += vy
            self._physics[a] = [x, y, vx, vy]
            energy += abs(vx) + abs(vy)
            item = self._node_items.get(a)
            if item is not None:
                item.setPos(QPointF(x, y))

        self._update_edges()
        self._tick += 1
        if energy < P["energy_stop"]:
            self._calm_frames += 1
            if self._calm_frames >= P["settle_frames"]:
                self._phys_timer.stop()
                self._float_timer.start()  # settled -> gentle floating
        else:
            self._calm_frames = 0

    def _float_step(self) -> None:
        """Subtle drifting after the layout settled (the 'living' feel)."""
        t = self._tick
        for cid, state in self._physics.items():
            if cid == self._drag_cid:
                continue
            state[1] += math.sin(t * self._freqs.get(cid, 1.0) + self._phases.get(cid, 0.0)) * _FLOAT_AMP * 0.2
            item = self._node_items.get(cid)
            if item is not None:
                item.setPos(QPointF(state[0], state[1]))
        self._tick += 1
        self._update_edges()

    def _update_edges(self) -> None:
        for (s, t), line in self._edge_items.items():
            if s not in self._node_items or t not in self._node_items:
                continue
            p1 = self._node_items[s].pos()
            p2 = self._node_items[t].pos()
            b1 = _border_point((p1.x(), p1.y()), (BOX_W / 2, BOX_H / 2),
                               (p2.x(), p2.y()))
            b2 = _border_point((p2.x(), p2.y()), (BOX_W / 2, BOX_H / 2),
                               (p1.x(), p1.y()))
            line.setLine(b1[0], b1[1], b2[0], b2[1])
            # edge colour by roles
            if s == self._focus_id or t == self._focus_id:
                line.setPen(QPen(_hex(_EDGE_FOCUS), 2.2))
            elif s in self._anomaly_ids or t in self._anomaly_ids:
                line.setPen(QPen(_hex(_EDGE_ANOMALY), 2.0))
            elif self._is_context_edge(s, t):
                line.setPen(QPen(_hex(_EDGE_CONTEXT), 1.4))
            else:
                line.setPen(QPen(_hex(_EDGE_NORMAL), 1.5))

    def _is_context_edge(self, s: str, t: str) -> bool:
        for a, b, label in self._edges:
            if {a, b} == {s, t} and label in ("路径相邻", _t("graph_path_edge")):
                return True
        return False

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
                self._drag_cid = hit[0]
                self._drag_start = event.pos()
                self._dragged = False
                event.accept()
                return
            if self._focus_id is not None:
                self.reset_focus()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_cid is not None:
            if not self._dragged and (event.pos() - self._drag_start).manhattanLength() > 6:
                self._dragged = True
            if self._dragged:
                item = self._node_items.get(self._drag_cid)
                if item is not None:
                    sp = self.mapToScene(event.pos())
                    item.setPos(sp)
                    state = self._physics.get(self._drag_cid)
                    if state is not None:
                        state[0], state[1] = sp.x(), sp.y()
                    self._update_edges()
                event.accept()
                return
        hit = self._item_concept(event.pos())
        cid = hit[0] if hit else None
        if cid != self._hover_cid:
            self._hover_cid = cid
            self._apply_hover()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_cid is not None:
            if not self._dragged:
                cid = self._drag_cid
                if self._focus_id == cid:
                    self.reset_focus()
                else:
                    self.focus_concept(cid)
                self.node_single_clicked.emit(cid)
            else:
                # after a drag, nudge the simulation to re-settle
                if self._focus_id is None and self._physics:
                    self._calm_frames = 0
                    if not self._phys_timer.isActive():
                        self._phys_timer.start()
            self._drag_cid = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        hit = self._item_concept(event.pos())
        if hit is not None:
            cid, name = hit
            if self._focus_id != cid:
                self.focus_concept(cid)
            self.concept_clicked.emit(name)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        if self._hover_cid is not None:
            self._hover_cid = None
            self._apply_hover()
        super().leaveEvent(event)

    def _apply_hover(self) -> None:
        if self._asset is None:
            return
        cid = self._hover_cid
        neighbours: set[str] = set()
        if cid is not None:
            for s, t, _label in self._edges:
                if s == cid:
                    neighbours.add(t)
                elif t == cid:
                    neighbours.add(s)
        for nid, item in self._node_items.items():
            if nid == self._focus_id or nid == self._current_id:
                continue
            if cid is not None and nid in neighbours:
                item.setPen(QPen(_hex("#0284C7"), 2.5))
            elif nid == cid:
                item.setPen(QPen(_hex("#0EA5E9"), 3))
            else:
                role = next((r for cc, _n, r in self._nodes if cc == nid), "normal")
                if nid in self._grey_ids or role == "context":
                    item.setPen(QPen(_hex(_BORDER_CONTEXT), 1))
                elif nid in self._anomaly_ids:
                    item.setPen(QPen(_hex(_BORDER_ANOMALY), 3))
                else:
                    item.setPen(QPen(_hex(_BORDER_NORMAL), 1))
