"""Interactive knowledge-graph widget for Flet 0.86.5.

Replaces the static Pillow PNG with a pan/zoomable, clickable node-link graph:

- **Edges** are drawn on a ``flet.canvas.Canvas`` (Line shapes, coloured by
  relation type: focus → cyan, anomaly → orange, context → faint grey).
- **Node pills** are ``ft.Container`` widgets positioned via ``left``/``top``
  inside a ``ft.Stack``.  Each pill is clickable (``on_click`` → ``on_select``
  callback) and shows the concept name with mastery-coloured background.
- ``ft.InteractiveViewer`` wraps the whole stack providing pinch-zoom and
  drag-pan — no custom event handling needed.
- A colour legend sits below the graph.

Layout math (``_select_nodes``, ``_layered_layout``, ``_radial_layout``) is
reused from ``core.graph_viz`` so the interactive view is consistent with the
offline PNG renderer.
"""
from __future__ import annotations

import asyncio
import math

import flet as ft
from flet import canvas as cv

from expert_anything.core.graph_viz import (
    BOX_W, BOX_H, FBOX_W, FBOX_H, CBOX_W, CBOX_H, MARGIN,
    _select_nodes, _layered_layout, _radial_layout, _border_point,
)
from expert_anything.core.i18n import t
from expert_anything.core.models import KnowledgeAsset

# ── colour helpers (graph_viz RGB tuples → hex) ─────────────────────────────

def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02X}{g:02X}{b:02X}"

# fills
_FILL_GREY = _hex((225, 228, 232))      # not studied
_FILL_GREEN = _hex((197, 230, 198))     # mastered  (≥0.6)
_FILL_AMBER = _hex((253, 235, 206))      # partial   (≥0.3)
_FILL_ORANGE = _hex((250, 214, 202))    # weak      (<0.3)
_FILL_FOCUS = _hex((129, 212, 250))      # focused concept
_FILL_CONTEXT = _hex((224, 228, 232))   # outer-ring context

# borders
_BORDER_NORMAL = _hex((120, 144, 156))
_BORDER_FOCUS = _hex((2, 132, 199))
_BORDER_ANOMALY = _hex((230, 120, 40))
_BORDER_CONTEXT = _hex((176, 190, 197))

# edges
_EDGE_NORMAL = _hex((130, 150, 165))
_EDGE_FOCUS = _hex((2, 132, 199))
_EDGE_ANOMALY = _hex((230, 120, 40))
_EDGE_CONTEXT = _hex((200, 208, 214))


def _all_border(width: float, color: str) -> ft.Border:
    """Create a uniform 4-sided border (ft.Border has no ``all=`` kwarg)."""
    s = ft.BorderSide(width=width, color=color)
    return ft.Border(s, s, s, s)


def _mastery_hex(m: float | None) -> str:
    if m is None:
        return _FILL_GREY
    if m >= 0.6:
        return _FILL_GREEN
    if m >= 0.3:
        return _FILL_AMBER
    return _FILL_ORANGE


def _pill_size(role: str) -> tuple[int, int]:
    if role == "focus":
        return (FBOX_W, FBOX_H)
    if role == "context":
        return (CBOX_W, CBOX_H)
    return (BOX_W, BOX_H)


def build_knowledge_graph(
    asset: KnowledgeAsset,
    focus_id: str | None = None,
    mastery_map: dict[str, float] | None = None,
    anomaly_ids: set[str] | None = None,
    current_id: str | None = None,
    on_select=None,
    height: int = 420,
) -> ft.Control:
    """Build an interactive, pan/zoomable, clickable knowledge graph.

    Parameters
    ----------
    asset : KnowledgeAsset
        The asset whose concepts and relations will be drawn.
    focus_id : str | None
        If set, render an ego-network centred on this concept (radial layout).
        If None, render the full network (layered/grid layout).
    mastery_map : dict[str, float] | None
        ``{concept_id: 0..1}`` → node fill colour encodes mastery level.
    anomaly_ids : set[str] | None
        Concept ids touched by open anomalies → orange outline.
    current_id : str | None
        E.g. the recommended-next concept → cyan outline (like focus).
    on_select : callable | None
        ``on_select(concept_id)`` fired when the user taps a node.  May be sync
        or async; the internal handler awaits coroutines automatically.
    height : int
        Pixel height of the graph viewport (legend rendered below).

    Returns
    -------
    ft.Column
        A Column containing the InteractiveViewer (graph) + legend + hint.
    """
    mmap = mastery_map or {}
    aids = anomaly_ids or set()

    # ── layout ──────────────────────────────────────────────────────────
    nodes, edges = _select_nodes(asset, focus_id)
    if not nodes:
        return ft.Text(
            "（无可绘制概念）", size=12, color=ft.Colors.GREY_600,
        )

    if focus_id is None:
        pos = _layered_layout(nodes, edges)
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        cw = int(max(xs) + BOX_W / 2 + MARGIN)
        ch = int(max(ys) + BOX_H / 2 + MARGIN + 10)
    else:
        pos, cw, ch = _radial_layout(nodes, focus_id)

    # ── canvas shapes: edges ─────────────────────────────────────────────
    shapes: list[cv.Shape] = []

    for s_id, t_id, label in edges:
        if s_id not in pos or t_id not in pos:
            continue
        is_ctx = (label == "路径相邻")
        p1 = _border_point(pos[s_id], (BOX_W / 2, BOX_H / 2), pos[t_id])
        p2 = _border_point(pos[t_id], (BOX_W / 2, BOX_H / 2), pos[s_id])
        is_fe = s_id == focus_id or t_id == focus_id
        is_ae = s_id in aids or t_id in aids

        if is_ctx:
            ec, sw = _EDGE_CONTEXT, 1.5
        elif is_fe:
            ec, sw = _EDGE_FOCUS, 2.5
        elif is_ae:
            ec, sw = _EDGE_ANOMALY, 2.5
        else:
            ec, sw = _EDGE_NORMAL, 1.5

        shapes.append(cv.Line(
            x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1],
            paint=ft.Paint(
                color=ec, stroke_width=sw,
                style=ft.PaintingStyle.STROKE,
                stroke_cap=ft.StrokeCap.ROUND,
            ),
        ))
        if label and not is_ctx:
            mx = (p1[0] + p2[0]) / 2
            my = (p1[1] + p2[1]) / 2
            shapes.append(cv.Text(
                x=mx - len(label) * 3.5, y=my - 8,
                value=label,
                style=ft.TextStyle(size=10, color=ft.Colors.GREY_700),
            ))

    # ── canvas shapes: node background rects ──────────────────────────────
    for cid, name, role in nodes:
        if cid not in pos:
            continue
        cx, cy = pos[cid]
        pw, ph = _pill_size(role)
        if role == "focus":
            fill = _FILL_FOCUS
        elif role == "context":
            fill = _FILL_CONTEXT
        else:
            fill = _mastery_hex(mmap.get(cid))
        shapes.append(cv.Rect(
            x=cx - pw / 2, y=cy - ph / 2,
            width=pw, height=ph, border_radius=10,
            paint=ft.Paint(color=fill, style=ft.PaintingStyle.FILL),
        ))

    # ── clickable node pills (Stack overlay) ──────────────────────────────
    async def _on_click(e):
        cid_val = e.control.data
        if on_select:
            result = on_select(cid_val)
            if asyncio.iscoroutine(result):
                await result

    pills: list[ft.Control] = []
    for cid, name, role in nodes:
        if cid not in pos:
            continue
        cx, cy = pos[cid]
        pw, ph = _pill_size(role)

        if role == "focus" or cid == current_id:
            bc, bw = _BORDER_FOCUS, 3
        elif cid in aids:
            bc, bw = _BORDER_ANOMALY, 3
        elif role == "context":
            bc, bw = _BORDER_CONTEXT, 1
        else:
            bc, bw = _BORDER_NORMAL, 1

        font_sz = 14 if role == "focus" else 12

        pill = ft.Container(
            data=cid,
            left=cx - pw / 2, top=cy - ph / 2,
            width=pw, height=ph,
            border=_all_border(bw, bc),
            border_radius=10,
            content=ft.Text(
                name, size=font_sz, text_align=ft.TextAlign.CENTER,
                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                color=ft.Colors.BLACK87,
            ),
            on_click=_on_click,
            ink=True,
            tooltip=name,
        )
        pills.append(pill)

    # ── assemble: Canvas + pills in a Stack inside InteractiveViewer ──────
    graph_canvas = cv.Canvas(shapes=shapes, width=cw, height=ch)
    graph_stack = ft.Stack(
        controls=[graph_canvas] + pills,
        width=cw, height=ch,
    )
    viewer = ft.InteractiveViewer(
        content=graph_stack,
        max_scale=4.0,
        min_scale=0.25,
        pan_enabled=True,
        scale_enabled=True,
    )

    # ── legend ───────────────────────────────────────────────────────────
    def _legend_chip(color: str, label: str, is_border: bool = False) -> ft.Row:
        if is_border:
            dot = ft.Container(
                width=14, height=14, border_radius=4,
                border=_all_border(2, color),
            )
        else:
            dot = ft.Container(
                width=14, height=14, border_radius=4, bgcolor=color,
            )
        return ft.Row(
            [dot, ft.Text(label, size=10, color=ft.Colors.GREY_700)],
            spacing=4,
        )

    legend_items = [
        _legend_chip(_FILL_GREEN, t("legend_mastered")),
        _legend_chip(_FILL_AMBER, t("legend_partial")),
        _legend_chip(_FILL_ORANGE, t("legend_weak")),
        _legend_chip(_FILL_GREY, t("legend_unstudied")),
    ]
    if aids:
        legend_items.append(
            _legend_chip(_BORDER_ANOMALY, t("legend_anomaly"), is_border=True),
        )
    if focus_id:
        legend_items.append(
            _legend_chip(_BORDER_FOCUS, t("legend_focus"), is_border=True),
        )

    return ft.Column(
        [
            ft.Container(content=viewer, height=height),
            ft.Row(legend_items, spacing=16, wrap=True),
            ft.Text(
                t("graph_hint"),
                size=10, color=ft.Colors.GREY_500, italic=True,
            ),
        ],
        spacing=4,
    )
