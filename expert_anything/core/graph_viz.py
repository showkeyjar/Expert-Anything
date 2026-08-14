"""Offline concept-map rendering (Pillow + CJK font) for the 图示 teaching style.

flet 0.86.5 has no WebView, so we cannot embed a live Mermaid diagram. Instead
we draw the asset's *real* knowledge graph ourselves:

- nodes  = concepts
- edges  = relations (source -> target)

Two layout modes, chosen by ``focus_id``:

* **No focus** (full network): every concept laid out by dependency depth / a
  grid. Used by the knowledge-model overview, the learner mastery map and the
  cognitive-nav hub.
* **Focus mode** (per-concept teaching graph): the requested concept is placed
  at the *centre*, enlarged and vividly filled, its relation-neighbours sit in an
  inner ring, and learning-path neighbours (when the concept has no relations)
  appear as faint context in an outer ring. This makes every concept's graph
  look genuinely different instead of being the same whole-network picture with
  only the highlight moved.

The result is a PNG returned as raw bytes, ready for ``ft.Image(src=...)``.
No network, no external binary, no WebView — works fully offline on Windows.
"""
from __future__ import annotations

import io
import math
import os

from PIL import Image, ImageDraw, ImageFont

from expert_anything.core.i18n import t as _t
from expert_anything.core.models import KnowledgeAsset

# --- layout constants --------------------------------------------------------
BOX_W = 184
BOX_H = 56
FBOX_W = BOX_W + 40          # focused (centre) node box
FBOX_H = BOX_H + 18
CBOX_W = BOX_W - 34          # context (outer-ring) node box
CBOX_H = BOX_H - 14
X_GAP = 60
Y_GAP = 70
MARGIN = 40
FONT_PATHS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# Fills
NORMAL_FILL = (235, 238, 242)
FOCUS_FILL = (129, 212, 250)      # vivid light-blue — obviously "this concept"
CONTEXT_FILL = (224, 228, 232)    # greyed — background context
BORDER = (120, 144, 156)
FOCUS_BORDER = (2, 132, 199)
ANOMALY_BORDER = (230, 120, 40)
CONTEXT_BORDER = (176, 190, 197)
EDGE = (130, 150, 165)
EDGE_FOCUS = (2, 132, 199)
EDGE_ANOMALY = (230, 120, 40)
EDGE_CONTEXT = (200, 208, 214)
TEXT = (33, 37, 41)
TITLE = (20, 60, 90)


def _mastery_fill(m: float | None) -> tuple[int, int, int]:
    """Light node fills so dark text stays readable; colour encodes mastery."""
    if m is None:
        return (225, 228, 232)          # grey — not studied
    if m >= 0.6:
        return (197, 230, 198)          # green — mastered
    if m >= 0.3:
        return (253, 235, 206)          # amber — partial
    return (250, 214, 202)              # orange — weak


def _node_border(cid: str, focus_id: str | None, current_id: str | None,
                 anomaly_ids: set[str]) -> tuple[tuple[int, int, int], int]:
    if cid == focus_id or cid == current_id:
        return FOCUS_BORDER, 3
    if cid in anomaly_ids:
        return ANOMALY_BORDER, 3
    return BORDER, 1


def _font(size: int) -> ImageFont.ImageFont:
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.ImageFont, max_w: int, max_lines: int = 2) -> list[str]:
    out: list[str] = []
    for raw in (text or "").split("\n"):
        if not raw:
            out.append("")
            continue
        cur = ""
        for ch in raw:
            if font.getlength(cur + ch) <= max_w:
                cur += ch
            else:
                out.append(cur)
                cur = ch
                if len(out) >= max_lines:
                    break
        else:
            out.append(cur)
        if len(out) >= max_lines:
            # truncate last line with ellipsis if text remains
            last = out[-1]
            if len(last) >= 6:
                out[-1] = last[: len(last) - 1] + "…"
            break
    return out or [""]


def _border_point(center: tuple[float, float], half: tuple[float, float], toward: tuple[float, float]) -> tuple[float, float]:
    cx, cy = center
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return center
    hw, hh = half
    tx = hw / abs(dx) if dx else float("inf")
    ty = hh / abs(dy) if dy else float("inf")
    t = min(tx, ty)
    return (cx + dx * t, cy + dy * t)


def _select_nodes(asset: KnowledgeAsset, focus_id: str | None) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Return (nodes, edges).

    nodes: [(concept_id, label, role)] with role in
    {"normal", "focus", "neighbor", "context"}.
    edges: [(src_id, tgt_id, label)].

    When ``focus_id`` is None we return the (capped) whole network. When a focus
    is given we return its ego-network (focus + relation neighbours) and, if that
    is a single isolated node, also the learning-path neighbours as faint context.
    """
    all_ids = [c.id for c in asset.concepts]
    id_to_name = {c.id: c.name for c in asset.concepts}

    if focus_id is None:
        keep = [cid for cid in all_ids if cid in id_to_name][:16]
        nodes = [(cid, id_to_name[cid], "normal") for cid in keep]
        keep_set = set(keep)
        edges: list[tuple[str, str, str]] = []
        for r in asset.relations:
            if r.source in keep_set and r.target in keep_set and r.source != r.target:
                edges.append((r.source, r.target, r.label or ""))
        if len(edges) < 4:
            # sparse relations -> backfill the learning-path skeleton so the
            # graph always shows a visible "how to study this" structure.
            seq = [cid for cid in asset.learning_path if cid in keep_set]
            have = {(s, t) for s, t, _ in edges}
            for a, b in zip(seq, seq[1:]):
                if (a, b) not in have and (b, a) not in have:
                    edges.append((a, b, _t("graph_path_edge")))
        return nodes, edges

    # --- focus mode --------------------------------------------------------
    neighbor_ids: set[str] = set()
    for r in asset.relations:
        if r.source == focus_id:
            neighbor_ids.add(r.target)
        if r.target == focus_id:
            neighbor_ids.add(r.source)

    roles: dict[str, str] = {focus_id: "focus"}
    for n in neighbor_ids:
        if n in id_to_name and n != focus_id:
            roles[n] = "neighbor"

    ego = [focus_id] + [n for n in neighbor_ids if n in id_to_name and n != focus_id]

    # If the concept has no relations, pull in learning-path neighbours as faint
    # context so its graph is not a lonely single box and still differs per concept.
    context: list[str] = []
    if len(ego) <= 1 and asset.learning_path:
        try:
            idx = asset.learning_path.index(focus_id)
        except ValueError:
            idx = -1
        if idx >= 0:
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(asset.learning_path):
                    c2 = asset.learning_path[j]
                    if c2 in id_to_name and c2 not in roles:
                        context.append(c2)
                        roles[c2] = "context"

    keep = ego + context
    nodes = [(cid, id_to_name[cid], roles.get(cid, "normal")) for cid in keep]
    keep_set = set(keep)
    edges = []
    for r in asset.relations:
        if r.source in keep_set and r.target in keep_set and r.source != r.target:
            edges.append((r.source, r.target, r.label or ""))
    for c2 in context:
        edges.append((focus_id, c2, _t("graph_path_edge")))
    # if the ego network has almost no relation edges, add learning-path
    # neighbours as faint context so the focused view is never a lone node
    if len(edges) < 2 and asset.learning_path:
        try:
            idx = asset.learning_path.index(focus_id)
        except ValueError:
            idx = -1
        if idx >= 0:
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(asset.learning_path):
                    c2 = asset.learning_path[j]
                    if c2 in id_to_name and c2 not in roles:
                        context.append(c2)
                        roles[c2] = "context"
                        edges.append((focus_id, c2, _t("graph_path_edge")))
    return nodes, edges


def _radial_layout(nodes, focus_id: str | None) -> tuple[dict[str, tuple[float, float]], int, int]:
    """Focus-centric layout. Returns (pos, width, height)."""
    focus = [n for n in nodes if n[2] == "focus"]
    neighbors = [n for n in nodes if n[2] == "neighbor"]
    context = [n for n in nodes if n[2] == "context"]

    if not neighbors and not context:
        # single isolated concept
        cx = MARGIN + FBOX_W / 2
        cy = MARGIN + 26 + FBOX_H / 2
        pos = {focus[0][0]: (cx, cy)}
        w = int(cx * 2 + MARGIN)
        h = int(cy + FBOX_H / 2 + MARGIN)
        return pos, w, h

    # ring radii
    r1 = FBOX_H / 2 + BOX_H / 2 + 62          # inner ring (relation neighbours)
    r2 = r1 + CBOX_H / 2 + BOX_H / 2 + 52     # outer ring (path context)
    if not neighbors:
        r1, r2 = r2, r2  # only context -> use one ring at r2

    ring_r = max(r1, r2)
    # half-sizes for bounding-box clearance (use the larger of w/h for safety)
    max_half_w = max(FBOX_W, BOX_W, CBOX_W) / 2
    max_half_h = max(FBOX_H, BOX_H, CBOX_H) / 2
    title_h = 26

    # compute image size first so the centre sits well inside
    w = int(2 * (MARGIN + ring_r + max_half_w + MARGIN))
    h = int(title_h + 2 * (MARGIN + ring_r + max_half_h + MARGIN))
    cx = w / 2
    cy = title_h + MARGIN + ring_r + max_half_h

    pos: dict[str, tuple[float, float]] = {}
    pos[focus[0][0]] = (cx, cy)
    n = len(neighbors)
    for i, (cid, _, _) in enumerate(neighbors):
        ang = -math.pi / 2 + (2 * math.pi * i / n if n else 0)
        pos[cid] = (cx + r1 * math.cos(ang), cy + r1 * math.sin(ang))
    m = len(context)
    for i, (cid, _, _) in enumerate(context):
        ang = -math.pi / 2 + (2 * math.pi * (i + 0.5) / m if m else 0)
        pos[cid] = (cx + r2 * math.cos(ang), cy + r2 * math.sin(ang))

    return pos, w, h


def _layered_layout(nodes, edges) -> dict[str, tuple[float, float]]:
    """Original layered/grid layout for the full-network (no-focus) view."""
    ids = [n[0] for n in nodes]
    layer: dict[str, int] = {i: 0 for i in ids}
    for _ in range(len(ids) + 2):
        changed = False
        for s, t, _ in edges:
            if s in layer and t in layer and layer[t] < layer[s] + 1:
                layer[t] = layer[s] + 1
                changed = True
        if not changed:
            break
    by_layer: dict[int, list[str]] = {}
    for i in ids:
        by_layer.setdefault(layer[i], []).append(i)
    pos: dict[str, tuple[float, float]] = {}
    for lyr, members in sorted(by_layer.items()):
        for idx, i in enumerate(members):
            pos[i] = (MARGIN + idx * (BOX_W + X_GAP) + BOX_W / 2,
                      MARGIN + lyr * (BOX_H + Y_GAP) + BOX_H / 2)
    return pos


def concept_map_png(
    asset: KnowledgeAsset,
    focus_id: str | None = None,
    mastery_map: dict[str, float] | None = None,
    anomaly_ids: set[str] | None = None,
    current_id: str | None = None,
    title: str | None = None,
) -> bytes:
    """Render the concept map to PNG bytes. Returns b"" on any failure.

    - focus_id: centre an ego-network on this concept (trim the rest).
    - mastery_map: {concept_id: 0..1} → colour nodes green/amber/orange/grey.
    - anomaly_ids: concept ids touched by open anomalies → orange outline.
    - current_id: e.g. the recommended-next concept → cyan outline (like focus).
    """
    try:
        return _render(asset, focus_id, mastery_map or {}, anomaly_ids or set(),
                       current_id, title)
    except Exception:
        # Never let diagram rendering break the lesson view.
        return b""


def _render(
    asset: KnowledgeAsset,
    focus_id: str | None,
    mastery_map: dict[str, float],
    anomaly_ids: set[str],
    current_id: str | None,
    title: str | None,
) -> bytes:
    nodes, edges = _select_nodes(asset, focus_id)
    if not nodes:
        return b""

    if focus_id is None:
        pos = _layered_layout(nodes, edges)
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        max_x = max(xs) + BOX_W / 2 + MARGIN
        max_y = max(ys) + BOX_H / 2 + MARGIN + 30
        w, h = int(max_x), int(max_y)
    else:
        pos, w, h = _radial_layout(nodes, focus_id)

    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    title_font = _font(18)
    focus_name = {c.id: c.name for c in asset.concepts}.get(focus_id, "")
    if title:
        draw.text((MARGIN, 8), title, fill=TITLE, font=title_font)
    elif focus_id:
        draw.text((MARGIN, 8), f"聚焦：{focus_name}（概念结构图）", fill=TITLE, font=title_font)
    else:
        draw.text((MARGIN, 8), "概念结构图", fill=TITLE, font=title_font)

    half = (BOX_W / 2, BOX_H / 2)
    fhalf = (FBOX_W / 2, FBOX_H / 2)
    chalf = (CBOX_W / 2, CBOX_H / 2)
    label_font = _font(15)
    edge_font = _font(11)

    def box_rect(cid, role):
        cx, cy = pos[cid]
        if role == "focus":
            hh = fhalf
        elif role == "context":
            hh = chalf
        else:
            hh = half
        return [cx - hh[0], cy - hh[1], cx + hh[0], cy + hh[1]], hh

    # edges first (under nodes)
    for s, t, lbl in edges:
        if s not in pos or t not in pos:
            continue
        is_context = lbl == "路径相邻"
        p1 = _border_point(pos[s], half, pos[t])
        p2 = _border_point(pos[t], half, pos[s])
        is_focus = s == focus_id or t == focus_id
        is_anom = s in anomaly_ids or t in anomaly_ids
        if is_context:
            color = EDGE_CONTEXT
        elif is_focus:
            color = EDGE_FOCUS
        elif is_anom:
            color = EDGE_ANOMALY
        else:
            color = EDGE
        width = 2
        draw.line([p1, p2], fill=color, width=width)
        if not is_context:
            _arrowhead(draw, p1, p2, color)
        if lbl:
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            tw = edge_font.getlength(lbl)
            draw.rectangle([mx - tw / 2 - 3, my - 8, mx + tw / 2 + 3, my + 8],
                           fill=(255, 255, 255))
            draw.text((mx - tw / 2, my - 7), lbl, fill=color, font=edge_font)

    # nodes
    for cid, label, role in nodes:
        rect, hh = box_rect(cid, role)
        if role == "focus":
            border_color, border_w = FOCUS_BORDER, 4
            fill = FOCUS_FILL
        elif role == "context":
            border_color, border_w = CONTEXT_BORDER, 1
            fill = CONTEXT_FILL
        else:
            border_color, border_w = _node_border(cid, focus_id, current_id, anomaly_ids)
            fill = _mastery_fill(mastery_map.get(cid))
        draw.rounded_rectangle(rect, radius=10, fill=fill, outline=border_color, width=border_w)
        lw = (FBOX_W - 16) if role == "focus" else ((CBOX_W - 12) if role == "context" else (BOX_W - 16))
        lines = _wrap(label, label_font, lw, max_lines=2)
        lh = 19
        total_h = lh * len(lines)
        start_y = rect[1] + (rect[3] - rect[1] - total_h) / 2
        for i, ln in enumerate(lines):
            tw = label_font.getlength(ln)
            draw.text((rect[0] + (rect[2] - rect[0] - tw) / 2, start_y + i * lh),
                      ln, fill=TEXT, font=label_font)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _arrowhead(draw: ImageDraw.ImageDraw, p1: tuple[float, float], p2: tuple[float, float], color) -> None:
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    L = 11
    a1 = (p2[0] - L * math.cos(ang - 0.45), p2[1] - L * math.sin(ang - 0.45))
    a2 = (p2[0] - L * math.cos(ang + 0.45), p2[1] - L * math.sin(ang + 0.45))
    draw.line([p2, a1], fill=color, width=2)
    draw.line([p2, a2], fill=color, width=2)
