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
    QMenu,
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
    hierarchy_neighbors,
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


def _hex_with_alpha(color: str, alpha: int) -> QColor:
    """Build a QColor from ``#RRGGBB`` with an explicit alpha (0-255)."""
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def _mastery_fill(m: float) -> QColor:
    if m >= 0.6:
        return _hex(_FILL_GREEN)
    if m >= 0.3:
        return _hex(_FILL_AMBER)
    if m > 0:
        return _hex(_FILL_ORANGE)
    return _hex(_FILL_GREY)


def _density_color(d: float) -> QColor:
    """Heatmap colour for knowledge density: blue(low) → yellow → red(high).

    d is a 0-1 value: 0 = low value (unimportant or already mastered),
    1 = high value (important + unlearned = highest learning ROI).
    """
    d = max(0.0, min(1.0, d))
    if d < 0.33:
        # blue → teal
        t = d / 0.33
        r = int(26 + 0 * t)
        g = int(35 + 120 * t)
        b = int(126 + 80 * t)
    elif d < 0.66:
        # teal → yellow
        t = (d - 0.33) / 0.33
        r = int(26 + 230 * t)
        g = int(155 + 100 * t)
        b = int(206 - 170 * t)
    else:
        # yellow → red
        t = (d - 0.66) / 0.34
        r = int(256 - 20 * t) if int(256 - 20 * t) <= 255 else 255
        g = int(255 - 130 * t)
        b = int(36 + 20 * t)
    return QColor(r, g, b)


def _mastery_heat_color(m: float) -> QColor:
    """Heatmap colour for mastery: red(weak) → orange → yellow → green(mastered).

    m is a 0-1 value: 0 = unstudied/weak (red), 0.6+ = mastered (green).
    Makes global weak spots instantly visible at a glance.
    """
    m = max(0.0, min(1.0, m))
    if m < 0.2:
        # deep red
        return QColor(198, 40, 40)
    elif m < 0.4:
        # red → orange
        t = (m - 0.2) / 0.2
        r = int(198 + 29 * t)
        g = int(40 + 61 * t)
        b = int(40 + 0 * t)
    elif m < 0.6:
        # orange → amber
        t = (m - 0.4) / 0.2
        r = int(227 + 28 * t)
        g = int(101 + 90 * t)
        b = int(40 + 3 * t)
    elif m < 0.8:
        # amber → light green
        t = (m - 0.6) / 0.2
        r = int(255 - 75 * t)
        g = int(191 + 36 * t)
        b = int(43 + 34 * t)
    else:
        # light green → deep green
        t = (m - 0.8) / 0.2
        r = int(180 - 48 * t)
        g = int(227 - 21 * t)
        b = int(77 - 13 * t)
    return QColor(r, g, b)


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


def _readable_path_layout(
    nodes: list[tuple[str, str, str]],
    asset: KnowledgeAsset,
) -> tuple[dict[str, tuple[float, float]], int, int]:
    """Place a sparse/fallback book model as a readable study path.

    A deterministic fallback has no semantic edges; force simulation then has
    nothing meaningful to stabilize and produces a cloud of labels. Arrange the
    selected path in a compact grid instead, with a stable reading order.
    """
    rank = {cid: i for i, cid in enumerate(asset.learning_path)}
    ordered = sorted(nodes, key=lambda item: (rank.get(item[0], 10**9), item[1]))
    cols = min(4, max(2, len(ordered)))
    x_gap, y_gap = 76, 72
    pos: dict[str, tuple[float, float]] = {}
    for i, (cid, _name, _role) in enumerate(ordered):
        col, row = i % cols, i // cols
        pos[cid] = (
            MARGIN + BOX_W / 2 + col * (BOX_W + x_gap),
            MARGIN + BOX_H / 2 + row * (BOX_H + y_gap),
        )
    rows = max(1, math.ceil(len(ordered) / cols))
    return (
        pos,
        int(2 * MARGIN + cols * BOX_W + (cols - 1) * x_gap),
        int(2 * MARGIN + rows * BOX_H + (rows - 1) * y_gap),
    )


# physics tuning — prioritise structural clarity over visual motion
_PHYS = {
    "repulsion": 5200.0,   # gentler repulsion: nodes stay closer, easier to read
    "spring": 0.018,       # stronger springs: layout settles faster, reads as structure
    "rest": 150.0,         # shorter rest length: tighter clusters
    "gravity": 0.0020,     # stronger centre pull: prevents outward drift
    "damp": 0.92,          # heavier damping: settle in fewer frames
    "energy_stop": 0.08,   # higher threshold: stops sooner
    "settle_frames": 18,   # fewer calm frames needed before sleeping
}
_FLOAT_AMP = 0.15          # barely-perceptible drift (structure readability > motion)


class KnowledgeGraphView(QGraphicsView):
    """Interactive, living knowledge graph."""

    # A full force-directed graph is useful for exploration, but becomes
    # unreadable as an entry view for a book-sized asset.  Keep the complete
    # network available through the skeleton toggle while making the first
    # render a legible learning map.
    _SKELETON_DEFAULT_THRESHOLD = 24

    concept_clicked = Signal(str)          # double-click -> teach (concept name)
    concept_drilldown = Signal(str)       # single-click -> focus and drill into children
    node_single_clicked = Signal(str)      # single-click on a node (concept id)
    edge_clicked = Signal(str, str, str)  # source_id, target_id, relation_label -> teach relation
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
        self._drill_path: list[str] = []
        self._nodes: list[tuple[str, str, str]] = []
        self._edges: list[tuple[str, str, str, str]] = []
        self._edge_type_map: dict[tuple[str, str, str], str] = {}
        self._node_items: dict[str, QGraphicsPathItem] = {}
        self._edge_items: dict[tuple[str, str, str], QGraphicsLineItem] = {}
        self._hover_cid: str | None = None

        # dependency chain highlight state
        self._chain_highlight_id: str | None = None
        self._chain_node_ids: set[str] = set()
        self._chain_edge_keys: set[tuple] = set()

        # physics state: cid -> [x, y, vx, vy]
        self._physics: dict[str, list[float]] = {}
        self._phys_timer = QTimer(self)
        self._phys_timer.setInterval(33)   # 30fps — calmer, less CPU
        self._phys_timer.timeout.connect(self._physics_step)
        self._float_timer = QTimer(self)
        self._float_timer.setInterval(90)   # slow drift, minimal distraction
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

        # semantic edge filtering: set of active semantic type keys
        # empty set = no filter (all edges shown normally)
        self._semantic_filter: set[str] = set()

        # skeleton mode: show only the most important concepts and backbone relations
        self._skeleton_mode: bool = False

        # learning path highlight: ordered list of concept IDs on the current path
        self._path_ids: list[str] = []
        self._path_rank: dict[str, int] = {}  # cid -> 1-based rank

        # teaching context: the concept currently being taught + its neighbourhood
        self._teach_context_id: str | None = None
        self._teach_prereq_ids: set[str] = set()   # concepts you need to know first
        self._teach_next_ids: set[str] = set()     # concepts this unlocks

        # density heatmap mode: node colour shows knowledge density (importance × novelty)
        self._density_mode: bool = False
        self._density_map: dict[str, float] = {}  # cid -> density score 0-1

        # mastery heatmap mode: node colour shows mastery as a heat gradient
        # (red=weak → yellow → green=mastered), making global gaps visible at a glance
        self._mastery_heat_mode: bool = False

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
        path_ids: list[str] | None = None,
    ) -> None:
        """Bind the asset and render the full network (living layout)."""
        self._asset = asset
        self._mastery = mastery_map or {}
        self._anomaly_ids = anomaly_ids or set()
        self._grey_ids = grey_ids or set()
        self._current_id = current_id
        self._focus_id = None
        if len(asset.concepts) > self._SKELETON_DEFAULT_THRESHOLD:
            self._skeleton_mode = True
        self._drill_path = []
        # Learning path highlight: top 6 items from adaptive path
        self._path_ids = list(path_ids or [])[:6]
        self._path_rank = {cid: i + 1 for i, cid in enumerate(self._path_ids)}
        self.render_graph()

    def drill_down(self, concept_id: str) -> bool:
        """Move one level down, returning whether child concepts exist."""
        if self._asset is None:
            return False
        _, children = hierarchy_neighbors(self._asset, concept_id)
        if not children:
            return False
        if not self._drill_path or self._drill_path[-1] != concept_id:
            self._drill_path.append(concept_id)
        self.render_graph(concept_id)
        return True

    def drill_up(self) -> bool:
        """Move to the parent level in the recorded drill path."""
        if self._asset is None or not self._drill_path:
            return False
        self._drill_path.pop()
        self.render_graph(self._drill_path[-1] if self._drill_path else None)
        return True

    def drill_path(self) -> list[str]:
        return list(self._drill_path)

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

        structural_only = bool(self._asset.relations) and all(
            str(getattr(r, "type", "") or "").lower()
            in {"contains", "parent-child", "parent_child", "child"}
            for r in self._asset.relations
        )

        # Skeleton mode: reduce to the core backbone of the knowledge network.
        # Only active in semantic full-network view. A structural EPUB already
        # has a compact chapter-root overview; reducing it again would hide
        # chapters and make the map feel arbitrary.
        if self._skeleton_mode and focus_id is None and len(nodes) > 8 and not structural_only:
            nodes, edges = self._skeleton_subset(nodes, edges)
            self._nodes = nodes
            self._edges = edges

        self._edge_type_map = {
            (s, t, lbl): rtype for s, t, lbl, rtype in edges
        }

        # cognitive-map analytics: hub sizing + learning frontier
        self._centrality = self._compute_centrality()
        self._frontier_ids = self._compute_frontier()

        # Layout ----------------------------------------------------------
        # A deterministic EPUB now carries real heading-containment edges.
        # They are useful for drill-down but should not trigger force physics:
        # physics would destroy the chapter/section reading order. Only mixed
        # semantic networks need the living force layout.
        if focus_id is None and (not self._asset.relations or structural_only):
            pos, w, h = _readable_path_layout(nodes, self._asset)
            self._cluster_regions = []
        elif focus_id is None:
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

        # Re-apply semantic filter after rebuild (edge items are fresh)
        if self._semantic_filter:
            self._update_edges()

        if focus_id is None and self._asset.relations and not structural_only:
            self._start_physics()

    def focus_concept(self, concept_id: str) -> None:
        """Radial ego-network centred on ``concept_id`` (motion sleeps)."""
        self.render_graph(focus_id=concept_id)

    def reset_focus(self) -> None:
        """Back to the full living network."""
        self.render_graph(focus_id=None)

    def set_semantic_filter(self, sem_types: set[str]) -> None:
        """Filter/highlight edges by semantic relation type.

        Pass an empty set to clear the filter (all edges shown normally).
        When active, matching edges stay bold/coloured while non-matching
        edges fade into the background — the map stays readable but the
        selected relation type jumps out.
        """
        self._semantic_filter = set(sem_types) if sem_types else set()
        self._update_edges()

    def highlight_dependency_chain(self, concept_id: str | None) -> None:
        """Highlight the full prerequisite chain for a concept.

        When set, only nodes/edges on the path from roots to this concept
        are fully visible; all others fade. Pass None to clear.
        """
        self._chain_highlight_id = concept_id
        if concept_id is None:
            self._chain_node_ids = set()
            self._chain_edge_keys = set()
        else:
            from expert_anything.core.learner import dependency_chain
            asset = self._asset
            if asset is None:
                return
            chain = dependency_chain(asset, concept_id)
            self._chain_node_ids = {item["id"] for item in chain}
            # Build edge keys for chain edges
            self._chain_edge_keys = set()
            chain_ids = self._chain_node_ids
            for key, (s_id, t_id, label, _) in self._edge_items.items():
                if s_id in chain_ids and t_id in chain_ids:
                    self._chain_edge_keys.add(key)
        self._update_edges()
        self.update()

    def toggle_skeleton_mode(self, enabled: bool | None = None) -> bool:
        """Toggle "core skeleton" view — only the most important concepts.

        Returns the new state. When enabled, only high-centrality +
        high-leverage concepts (the "backbone" of the knowledge network)
        are shown, connected by their prerequisite/causal relations.
        This gives the learner a 1-minute overview of the entire asset.
        """
        if enabled is None:
            self._skeleton_mode = not self._skeleton_mode
        else:
            self._skeleton_mode = bool(enabled)
        self.render_graph(focus_id=self._focus_id)
        return self._skeleton_mode

    def set_teaching_context(self, concept_id: str | None) -> None:
        """Highlight the concept currently being taught + its context.

        Shows what you need to know first (prerequisites) and what this
        concept unlocks (downstream dependents). Pass None to clear.
        The learner sees at a glance: "where am I, what's before, what's next".
        """
        if not concept_id or not self._asset:
            self._teach_context_id = None
            self._teach_prereq_ids = set()
            self._teach_next_ids = set()
            self._update_edges()
            return

        from expert_anything.core.decoder import classify_relation
        _ORDER_SEMS = {"prereq", "causes", "is_a"}

        prereqs = set()
        nexts = set()
        for r in self._asset.relations or []:
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            if sem not in _ORDER_SEMS:
                continue
            # source → target means source is prerequisite for target
            if r.target == concept_id and r.source != concept_id:
                prereqs.add(r.source)
            if r.source == concept_id and r.target != concept_id:
                nexts.add(r.target)

        self._teach_context_id = concept_id
        self._teach_prereq_ids = prereqs
        self._teach_next_ids = nexts
        self._update_edges()

    def is_focused(self) -> bool:
        return self._focus_id is not None

    def toggle_density_mode(self, enabled: bool | None = None) -> bool:
        """Toggle knowledge-density heatmap view.

        When on, node colours show knowledge density (importance × novelty)
        instead of mastery. High-density = important but unlearned — the
        highest-value targets for learning. Returns the new state.
        """
        if enabled is None:
            self._density_mode = not self._density_mode
        else:
            self._density_mode = bool(enabled)
        if self._density_mode:
            self._compute_density()
        else:
            self._density_map = {}
        if self._density_mode:
            self._mastery_heat_mode = False
        self.render_graph(focus_id=self._focus_id)
        return self._density_mode

    def toggle_mastery_heatmap(self, enabled: bool | None = None) -> bool:
        """Toggle mastery heatmap view.

        When on, node colours show a red→yellow→green gradient where
        red = weak (mastery < 0.3), green = mastered (≥ 0.6), making
        the learner's global weak spots visible at a glance.
        """
        if enabled is None:
            self._mastery_heat_mode = not self._mastery_heat_mode
        else:
            self._mastery_heat_mode = bool(enabled)
        if self._mastery_heat_mode:
            self._density_mode = False
            self._density_map = {}
        self.render_graph(focus_id=self._focus_id)
        return self._mastery_heat_mode

    def _compute_density(self) -> None:
        """Compute density = importance × novelty for each visible node."""
        from expert_anything.core.learner import normalize as _norm
        deg: dict[str, int] = {}
        for s_id, t_id, _l, _r in self._edges:
            deg[s_id] = deg.get(s_id, 0) + 1
            deg[t_id] = deg.get(t_id, 0) + 1
        max_deg = max(deg.values()) if deg else 1
        density: dict[str, float] = {}
        for cid, _name, _role in self._nodes:
            importance = deg.get(cid, 0) / max_deg if max_deg > 0 else 0.0
            mastery = 0.0
            if self._mastery:
                # Find mastery by concept name (same lookup as nodes use)
                for _cid2, cname, _r in self._nodes:
                    if _cid2 == cid:
                        mastery = float(self._mastery.get(_norm(cname), 0.0))
                        break
            novelty = 1.0 - mastery
            density[cid] = min(1.0, importance * novelty)
        self._density_map = density

    # ------------------------------------------------------------------ #
    # cognitive-map analytics
    # ------------------------------------------------------------------ #
    def _compute_centrality(self) -> dict[str, float]:
        """Degree-based importance: hubs (more connections) render larger."""
        deg: dict[str, int] = {}
        for s_id, t_id, _label, _ in self._edges:
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
        for s_id, t_id, _label, _ in self._edges:
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

    def _skeleton_subset(
        self,
        nodes: list[tuple[str, str, str]],
        edges: list[tuple[str, str, str, str]],
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str, str]]]:
        """Extract the core skeleton: most important concepts + backbone edges.

        Selection criterion: combined score of degree (hub importance) +
        out-degree (leverage — how many concepts it unblocks).
        Only structural relations (prereq / causes / is_a / part_of) are
        kept between skeleton nodes — contrast / related edges are noise
        in a "backbone" view.
        """
        from expert_anything.core.decoder import classify_relation

        # Degree-based importance
        indeg: dict[str, int] = {cid: 0 for cid, _n, _r in nodes}
        outdeg: dict[str, int] = {cid: 0 for cid, _n, _r in nodes}
        for s, t, _lbl, _rtype in edges:
            if s in outdeg:
                outdeg[s] += 1
            if t in indeg:
                indeg[t] += 1

        # Importance = total degree + out-degree bonus (leverage)
        # Out-degree matters more because it means the concept unlocks things.
        scores: dict[str, float] = {}
        for cid, _n, _r in nodes:
            total = indeg.get(cid, 0) + outdeg.get(cid, 0)
            leverage = outdeg.get(cid, 0)
            scores[cid] = total + 0.5 * leverage

        # Target size: enough context to read a book overview, clamped to
        # [8, 12]. Five nodes made the large-book map look empty and arbitrary.
        n_total = len(nodes)
        target = max(8, min(12, int(n_total * 0.5)))
        if target >= n_total:
            return nodes, edges  # already small enough

        # Pick top concepts by importance
        ranked = sorted(scores.keys(), key=lambda c: (-scores[c], c))
        core_ids = set(ranked[:target])

        # Filter nodes
        core_nodes = [(cid, name, role) for cid, name, role in nodes if cid in core_ids]

        # Filter edges: both ends in core AND structural relation type
        _STRUCT_SEMS = {"prereq", "causes", "is_a", "part_of"}
        core_edges = []
        for s, t, lbl, rtype in edges:
            if s not in core_ids or t not in core_ids:
                continue
            sem = classify_relation(lbl or "", rtype or "")
            if sem in _STRUCT_SEMS:
                core_edges.append((s, t, lbl, rtype))

        return core_nodes, core_edges

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
        for s_id, t_id, _label, _rtype in self._edges:
            if s_id not in pos or t_id not in pos:
                continue
            key = (s_id, t_id, _label)
            line = QGraphicsLineItem()
            # Apply semantic colour immediately at initial render, not just
            # in _update_edges — so the first frame already shows the
            # relation's structural meaning (causes / part-of / …).
            from expert_anything.core.decoder import classify_relation, REL_SEMANTICS, rel_semantic_color
            from expert_anything.core.i18n import t as _tt
            sem = classify_relation(_label or "", _rtype or "")
            sem_info = REL_SEMANTICS.get(sem, REL_SEMANTICS["related"])
            sem_color = rel_semantic_color(_label or "", _rtype or "")
            pen = QPen(_hex(sem_color), 1.6)
            if sem == "contrast":
                pen.setStyle(Qt.PenStyle.DashLine)
            line.setPen(pen)
            tip = f"[{sem_info['label']}] {_label or _tt('edge_related')}"
            line.setToolTip(tip)
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
            elif role == "child":
                fill = _hex(_FILL_CONTEXT)
                border, bwidth = _hex(_BORDER_FOCUS), 2
            elif role == "parent":
                fill = _hex(_FILL_CONTEXT)
                border, bwidth = _hex(_BORDER_ANOMALY), 2
            elif role == "context":
                fill = _hex(_FILL_CONTEXT)
                border, bwidth = _hex(_BORDER_CONTEXT), 1
            else:
                if cid in self._grey_ids:
                    fill = _hex(_FILL_GREY)
                    border, bwidth = _hex(_BORDER_CONTEXT), 1
                else:
                    if self._density_mode and cid in self._density_map:
                        # Density heatmap: blue(low) → yellow → red(high)
                        fill = _density_color(self._density_map[cid])
                    elif self._mastery_heat_mode:
                        fill = _mastery_heat_color(self._mastery.get(cid, 0.0))
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

            # Learning-path rank badge — shows the queue position on the
            # adaptive path, so the learner can see "what's next" at a glance.
            if cid in self._path_rank and role not in ("focus", "context"):
                rank = self._path_rank[cid]
                badge_text = str(rank)
                badge_size = 20
                badge_x = bw / 2 - badge_size / 2
                badge_y = -bh / 2 - badge_size / 2
                badge_rect = QRectF(badge_x, badge_y, badge_size, badge_size)
                badge_path = QPainterPath()
                badge_path.addEllipse(badge_rect)
                badge_item = QGraphicsPathItem(badge_path)
                # gradient: gold/orange for top-3, blue for the rest
                if rank <= 3:
                    badge_fill = QColor(0xFF, 0x8F, 0x00)
                else:
                    badge_fill = QColor(0x15, 0x65, 0xC0)
                badge_item.setBrush(QBrush(badge_fill))
                badge_item.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2))
                badge_item.setPos(QPointF(*c))
                badge_item.setZValue(item.zValue() + 2)
                badge_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                scene.addItem(badge_item)
                # Badge number text
                btext = QGraphicsSimpleTextItem(badge_text)
                bf = QFont()
                bf.setPointSize(9)
                bf.setBold(True)
                btext.setFont(bf)
                btext.setBrush(QColor("#FFFFFF"))
                btext.setPos(
                    badge_x + badge_size / 2 - btext.boundingRect().width() / 2,
                    badge_y + badge_size / 2 - btext.boundingRect().height() / 2 - 1,
                )
                btext.setParentItem(badge_item)

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

    def export_png(self, file_path: str) -> bool:
        """Render the current graph to a PNG file.

        Captures the full scene (not just the visible viewport) at 2x
        resolution for crisp output. Returns True on success.
        """
        scene = self.scene()
        if not self._node_items:
            return False

        # Calculate bounding rect of all items
        content = QRectF()
        for item in scene.items():
            content = content.united(item.sceneBoundingRect())
        content.adjust(-40, -40, 40, 40)

        # Create high-res image (2x scale)
        scale = 2.0
        img_w = int(content.width() * scale)
        img_h = int(content.height() * scale)
        if img_w <= 0 or img_h <= 0 or img_w > 10000 or img_h > 10000:
            return False

        from PySide6.QtGui import QImage, QPainter, QColor
        image = QImage(img_w, img_h, QImage.Format.Format_ARGB32)
        image.fill(QColor("#FAFBFC"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(scale, scale)
        scene.render(painter, content, content)
        painter.end()

        return image.save(file_path, "PNG")

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
            for s, t, _label, _ in self._edges:
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
        from expert_anything.core.decoder import rel_semantic_color, classify_relation
        sem_filter = self._semantic_filter

        role_by_id = {cid: role for cid, _name, role in self._nodes}

        def half_size(cid: str) -> tuple[float, float]:
            role = role_by_id.get(cid, "normal")
            if role == "focus":
                return FBOX_W / 2, FBOX_H / 2
            if role == "context":
                return CBOX_W / 2, CBOX_H / 2
            return BOX_W / 2, BOX_H / 2

        for (s, t, label), line in self._edge_items.items():
            if s not in self._node_items or t not in self._node_items:
                continue
            p1 = self._node_items[s].pos()
            p2 = self._node_items[t].pos()
            b1 = _border_point((p1.x(), p1.y()), half_size(s),
                               (p2.x(), p2.y()))
            b2 = _border_point((p2.x(), p2.y()), half_size(t),
                               (p1.x(), p1.y()))
            line.setLine(b1[0], b1[1], b2[0], b2[1])

            # Determine the edge's semantic type once
            rtype = self._edge_type_map.get((s, t, label), "")
            sem = classify_relation(label or "", rtype or "")

            # Semantic filter: compute opacity boost / dim
            if sem_filter:
                if sem in sem_filter:
                    filter_alpha = 255   # fully visible, bold
                    filter_width = 2.4
                else:
                    filter_alpha = 70    # faded into background
                    filter_width = 1.2
            else:
                filter_alpha = 255
                filter_width = 1.6

            # edge colour: focus > anomaly > teaching context > path highlight > semantic colour > context
            if s == self._focus_id or t == self._focus_id:
                pen = QPen(_hex_with_alpha(_EDGE_FOCUS, filter_alpha), max(filter_width, 2.2))
            elif s in self._anomaly_ids or t in self._anomaly_ids:
                pen = QPen(_hex_with_alpha(_EDGE_ANOMALY, filter_alpha), max(filter_width, 2.0))
            elif self._is_teach_context_edge(s, t):
                # Edges connecting the taught concept to its prereqs/nexts
                # get a teal highlight — the learner sees "what leads here,
                # and where this leads".
                tc_color = "#00897B"
                pen = QPen(_hex_with_alpha(tc_color, filter_alpha), max(filter_width + 1.5, 3.0))
                pen.setStyle(Qt.PenStyle.SolidLine)
            elif self._is_path_edge(s, t):
                # Edges between consecutive concepts on the learning path
                # get a golden highlight — the learner sees the "trail" of
                # what to study next.
                pen = QPen(_hex_with_alpha("#FF8F00", filter_alpha), max(filter_width + 1.2, 2.8))
                pen.setStyle(Qt.PenStyle.SolidLine)
            elif self._is_context_edge(s, t):
                pen = QPen(_hex_with_alpha(_EDGE_CONTEXT, filter_alpha), max(filter_width * 0.8, 1.2))
            else:
                # Semantic colour by relation label + type
                sem_color = rel_semantic_color(label or "", rtype or "")
                pen = QPen(_hex_with_alpha(sem_color, filter_alpha), filter_width)
                # contrast relations get dashed style
                if sem == "contrast":
                    pen.setStyle(Qt.PenStyle.DashLine)
            line.setPen(pen)

    def _is_context_edge(self, s: str, t: str) -> bool:
        for a, b, label, _ in self._edges:
            if {a, b} == {s, t} and label in ("路径相邻", _t("graph_path_edge")):
                return True
        return False

    def _is_path_edge(self, s: str, t: str) -> bool:
        """Check if an edge connects two consecutive concepts on the learning path.

        This highlights the "trail" of what to study next — the learner
        sees a clear golden path through the knowledge network.
        """
        if not self._path_rank:
            return False
        rs = self._path_rank.get(s)
        rt = self._path_rank.get(t)
        if rs is None or rt is None:
            return False
        # Consecutive ranks (either direction) → part of the path trail
        return abs(rs - rt) == 1

    def _is_teach_context_edge(self, s: str, t: str) -> bool:
        """Check if an edge is part of the current teaching context.

        True when one end is the concept being taught and the other is
        either a prerequisite or a downstream dependent. This highlights
        the "before → now → next" chain around the current concept.
        """
        if not self._teach_context_id:
            return False
        tc = self._teach_context_id
        if s == tc:
            return t in self._teach_next_ids or t in self._teach_prereq_ids
        if t == tc:
            return s in self._teach_next_ids or s in self._teach_prereq_ids
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

    def _item_edge(self, scene_pos) -> tuple[str, str, str] | None:
        """Check if a scene point is near an edge line. Returns (src_id, tgt_id, label) or None."""
        if not self._edges:
            return None
        from PySide6.QtCore import QLineF
        threshold = 6.0  # pixels from line center to count as a hit
        for (src_id, tgt_id, label, _) in self._edges:
            src_state = self._physics.get(src_id)
            tgt_state = self._physics.get(tgt_id)
            if not src_state or not tgt_state:
                continue
            line = QLineF(src_state[0], src_state[1], tgt_state[0], tgt_state[1])
            # Distance from point to line segment
            import math
            x1, y1 = line.x1(), line.y1()
            x2, y2 = line.x2(), line.y2()
            px, py = scene_pos.x(), scene_pos.y()
            dx, dy = x2 - x1, y2 - y1
            length_sq = dx * dx + dy * dy
            if length_sq == 0:
                dist = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy
                dist = math.hypot(px - proj_x, py - proj_y)
            if dist <= threshold:
                return (src_id, tgt_id, label)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._item_concept(event.position().toPoint())
            if hit is not None:
                self._drag_cid = hit[0]
                self._drag_start = event.pos()
                self._dragged = False
                event.accept()
                return
            # Check edge click — if no node was hit, check if an edge line was clicked
            scene_pos = self.mapToScene(event.pos())
            edge_hit = self._item_edge(scene_pos)
            if edge_hit is not None:
                src_id, tgt_id, rel_label = edge_hit
                self.edge_clicked.emit(src_id, tgt_id, rel_label)
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
                # Focusing rebuilds the scene.  Doing that synchronously here can
                # delete the clicked QGraphicsItem while Qt is still dispatching
                # its release event, which may terminate the process.  Run the
                # complete click action after event dispatch has unwound instead.
                QTimer.singleShot(0, lambda concept_id=cid: self._handle_node_click(concept_id))
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

    def _handle_node_click(self, concept_id: str) -> None:
        # The timer may fire after an asset switch or another scene rebuild.
        # Only handle concepts that still belong to the currently rendered map.
        if concept_id not in self._node_items:
            return
        # Keep the current focus until the view-level handler receives the
        # signal.  The previous implementation reset focus here and then
        # emitted node_single_clicked; the handler could no longer tell that
        # this was a second click on the focused node, so drill-down never
        # happened. A blank-canvas click or the reset button still exits focus.
        if self._focus_id != concept_id:
            self.focus_concept(concept_id)
        self.node_single_clicked.emit(concept_id)
        self.concept_drilldown.emit(concept_id)

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

    def contextMenuEvent(self, event):
        """Right-click context menu on graph nodes for quick actions."""
        hit = self._item_concept(event.pos())
        if hit is None:
            super().contextMenuEvent(event)
            return
        cid, name = hit
        menu = QMenu(self)
        from expert_anything.core.i18n import t as _tt
        act_teach = menu.addAction(f"\u25b6  {_tt('ctx_teach')}")
        act_evidence = menu.addAction(f"\u270e  {_tt('ctx_evidence')}")
        act_compare = menu.addAction(f"\u29c9  {_tt('ctx_compare')}")
        menu.addSeparator()
        act_focus = menu.addAction(f"\u25cb  {_tt('ctx_focus')}")
        chosen = menu.exec(event.globalPos())
        if chosen is act_teach:
            self.concept_clicked.emit(name)
        elif chosen is act_evidence:
            self.concept_drilldown.emit(cid)
        elif chosen is act_compare:
            self.node_single_clicked.emit(cid)
        elif chosen is act_focus:
            self.focus_concept(cid)

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
            for s, t, _label, _ in self._edges:
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
