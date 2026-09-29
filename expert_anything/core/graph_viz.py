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


def hierarchy_neighbors(asset: KnowledgeAsset, concept_id: str) -> tuple[list[str], list[str]]:
    """Return (parents, children) for a concept using decoded hierarchy edges."""
    hierarchy_types = {
        "contains", "包含", "包括", "涵盖", "下位概念", "parent-child",
        "parent_child", "child", "subconcept", "sub-concept", "层级",
        "上位-下位", "上位概念", "part-of", "has-part",
    }

    def is_hierarchy(relation) -> bool:
        values = (getattr(relation, "type", ""), getattr(relation, "label", ""),
                  getattr(relation, "relation_type", ""))
        normalized = {str(v or "").strip().lower() for v in values}
        return bool(normalized & hierarchy_types) or any(
            any(token in value for token in ("子概念", "下位", "包含", "组成"))
            for value in normalized
        )

    parents, children = [], []
    for relation in asset.relations:
        if not is_hierarchy(relation):
            continue
        if relation.target == concept_id and relation.source not in parents:
            parents.append(relation.source)
        elif relation.source == concept_id and relation.target not in children:
            children.append(relation.target)
    valid = {c.id for c in asset.concepts}
    # Deterministic EPUB extraction may have a sound chapter structure but no
    # semantic LLM relations. In that case a click must still descend into the
    # selected chapter's ordered sections. Treat the first concept in a
    # chapter as its chapter node; subsequent headings use it as parent and
    # expose the following headings as a bounded next level.
    if not parents and not children:
        current = asset.concept_by_id(concept_id)
        chapter = getattr(current, "chapter", "") if current else ""
        if chapter:
            order = [c.id for c in asset.concepts
                     if getattr(c, "chapter", "") == chapter]
            if len(order) > 1 and concept_id in order:
                index = order.index(concept_id)
                if index == 0:
                    children = order[1:9]
                else:
                    parents = order[:1]
                    children = order[index + 1:index + 5]
    return ([cid for cid in parents if cid in valid],
            [cid for cid in children if cid in valid])


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
        structural_only = bool(asset.relations) and all(
            str(getattr(r, "type", "") or "").lower()
            in {"contains", "parent-child", "parent_child", "child"}
            for r in asset.relations
        )
        if structural_only:
            # Overview = one root per chapter, not the first N concepts in
            # document order. This is both faster and cognitively legible;
            # sections/leaves appear when the learner focuses a chapter.
            chapter_roots: list[str] = []
            seen_chapters: set[str] = set()
            for concept in asset.concepts:
                chapter = getattr(concept, "chapter", "") or ""
                if chapter and chapter not in seen_chapters:
                    seen_chapters.add(chapter)
                    chapter_roots.append(concept.id)
            keep = chapter_roots[:24] or all_ids[:16]
        else:
            keep = [cid for cid in all_ids if cid in id_to_name][:16]
        nodes = [(cid, id_to_name[cid], "normal") for cid in keep]
        keep_set = set(keep)
        edges: list[tuple[str, str, str, str]] = []
        for r in asset.relations:
            if r.source in keep_set and r.target in keep_set and r.source != r.target:
                edges.append((r.source, r.target, r.label or "", getattr(r, "type", "") or ""))
        if len(edges) < 4:
            # sparse relations -> backfill the learning-path skeleton so the
            # graph always shows a visible "how to study this" structure.
            seq = [cid for cid in asset.learning_path if cid in keep_set]
            have = {(s, t) for s, t, _, _ in edges}
            for a, b in zip(seq, seq[1:]):
                if (a, b) not in have and (b, a) not in have:
                    edges.append((a, b, _t("graph_path_edge"), "prereq"))
        return nodes, edges

    # --- focus mode --------------------------------------------------------
    parent_ids, child_ids = hierarchy_neighbors(asset, focus_id)
    neighbor_ids: set[str] = set(parent_ids + child_ids)
    child_ids: list[str] = list(child_ids)
    hierarchy_types = {
        "contains", "包含", "包括", "涵盖", "下位概念", "parent-child",
        "parent_child", "child", "subconcept", "sub-concept", "层级",
        "上位-下位", "上位概念", "part-of", "has-part",
    }

    def _is_hierarchy_relation(relation) -> bool:
        values = (
            getattr(relation, "type", ""),
            getattr(relation, "label", ""),
            getattr(relation, "relation_type", ""),
        )
        normalized = {str(v or "").strip().lower() for v in values}
        return bool(normalized & hierarchy_types) or any(
            any(token in value for token in ("子概念", "下位", "包含", "组成"))
            for value in normalized
        )

    for r in asset.relations:
        if r.source == focus_id:
            neighbor_ids.add(r.target)
            # Outgoing hierarchy edges are the node's actual drill-down
            # contents. Keep their order from the source asset for stable UI.
            if _is_hierarchy_relation(r) and r.target not in child_ids:
                child_ids.append(r.target)
        elif r.target == focus_id:
            neighbor_ids.add(r.source)
            if _is_hierarchy_relation(r) and r.source not in child_ids:
                # Some decoders emit the hierarchy edge in the reverse
                # direction. Keep the parent visible as context, but do not
                # label it as a child.
                pass

    roles: dict[str, str] = {focus_id: "focus"}
    for cid in child_ids:
        if cid in id_to_name and cid != focus_id:
            roles[cid] = "child"

    # A reverse hierarchy edge identifies an upper concept. It is kept in
    # context and explicitly marked so the UI can offer an upward drill.
    for r in asset.relations:
        if r.target == focus_id and _is_hierarchy_relation(r):
            if r.source in id_to_name and r.source != focus_id:
                roles[r.source] = "parent"
    for n in neighbor_ids:
        if n in id_to_name and n != focus_id and n not in roles:
            roles[n] = "neighbor"

    # Preserve the semantic role assigned above: the generic neighbour pass
    # must not downgrade children/parents.  The focused view is a drillable
    # local subgraph, so every direct child remains visible and clickable.
    ego = [focus_id] + [n for n in child_ids if n in id_to_name and n != focus_id]
    ego += [n for n in neighbor_ids if n in id_to_name and n != focus_id and n not in ego]

    # If the concept has no relations, pull in learning-path neighbours as faint
    # context so its graph is not a lonely single box and still differs per concept.
    # Last resort: same-chapter brothers — a click must always surface *some*
    # alongside / next-level points (认知地图信息增量，永不孤点).
    context: list[str] = []

    def _path_context() -> None:
        if not asset.learning_path:
            return
        try:
            idx = asset.learning_path.index(focus_id)
        except ValueError:
            idx = -1
        if idx >= 0:
            for j in (idx - 1, idx + 1):
                if 0 <= j < len(asset.learning_path):
                    c2 = asset.learning_path[j]
                    if c2 in id_to_name and c2 not in roles and c2 not in context:
                        context.append(c2)
                        roles[c2] = "context"

    def _chapter_context() -> None:
        fc = asset.concept_by_id(focus_id)
        if fc is None or not getattr(fc, "chapter", ""):
            return
        for cc in asset.concepts:
            if (cc.id != focus_id and cc.id in id_to_name
                    and cc.id not in roles and cc.id not in context
                    and getattr(cc, "chapter", "") == fc.chapter):
                context.append(cc.id)
                roles[cc.id] = "context"
                if len(context) >= 3:
                    return

    # A focused map should provide a useful local neighborhood, not only the
    # explicitly decoded hierarchy edges. Add same-chapter concepts and nearby
    # learning-path concepts as context while keeping structural nodes primary.
    _path_context()
    _chapter_context()

    keep = ego + context
    nodes = [(cid, id_to_name[cid], roles.get(cid, "normal")) for cid in keep]
    keep_set = set(keep)
    edges = []
    for r in asset.relations:
        if r.source in keep_set and r.target in keep_set and r.source != r.target:
            edges.append((r.source, r.target, r.label or "", getattr(r, "type", "") or ""))
    # In a source-only asset, hierarchy_neighbors() derives chapter/section
    # structure from the ordered headings. Materialize those edges in the
    # focused view so the child nodes are not merely a second row of unrelated
    # boxes.
    if focus_id is not None:
        parent_ids, child_ids = hierarchy_neighbors(asset, focus_id)
        have = {(s, t) for s, t, _label, _rtype in edges}
        for parent_id in parent_ids:
            if (parent_id, focus_id) not in have:
                edges.append((parent_id, focus_id, _t("rel_part_of"), "contains"))
        for child_id in child_ids:
            if (focus_id, child_id) not in have:
                edges.append((focus_id, child_id, _t("rel_part_of"), "contains"))
    for c2 in context:
        edges.append((focus_id, c2, _t("graph_path_edge"), "related"))
    # if the ego network has almost no relation edges, add learning-path
    # neighbours — or same-chapter brothers — as faint context so the focused
    # view is never a lone node (context additions are kept inside `keep`
    # above via the helper, so no dangling edges).
    if len(edges) < 2:
        _path_context()
        _chapter_context()
        for c2 in context:
            if c2 in keep_set:
                continue
            keep.append(c2)
            keep_set.add(c2)
            nodes.append((c2, id_to_name[c2], "context"))
            edges.append((focus_id, c2, _t("graph_path_edge"), "related"))
    return nodes, edges


def _radial_layout(nodes, focus_id: str | None) -> tuple[dict[str, tuple[float, float]], int, int]:
    """Focus-centric layout with explicit reading order.

    The old ring layout made a focused concept look like a radial mind map:
    parents, children and path context all shared one circle, so labels and
    edges crossed in ways that hid the learning sequence.  Use rows instead:
    parent → focus → children/neighbours → context.  Within each row the
    source order is retained and nodes are evenly spaced.
    """
    focus = [n for n in nodes if n[2] == "focus"]
    if not focus:
        return {}, 640, 360

    def chunks(items, size=8):
        return [items[i:i + size] for i in range(0, len(items), size)]

    rows = []
    rows.extend(chunks([n for n in nodes if n[2] == "parent"]))
    rows.append(focus[:1])
    rows.extend(chunks([n for n in nodes if n[2] == "child"]))
    rows.extend(chunks([n for n in nodes if n[2] == "neighbor"]))
    rows.extend(chunks([n for n in nodes if n[2] == "context"]))
    rows = [row for row in rows if row]
    max_count = max(len(row) for row in rows)
    gap = 22
    side = 64
    w = max(760, max_count * (BOX_W + gap) + side * 2)
    row_gap = 58
    row_heights = [
        FBOX_H if any(n[2] == "focus" for n in row) else BOX_H
        for row in rows
    ]
    h = int(sum(row_heights) + row_gap * (len(rows) - 1) + 72)
    center_x = w / 2
    pos: dict[str, tuple[float, float]] = {}
    y = 36
    for row, row_h in zip(rows, row_heights):
        total = len(row) * BOX_W + max(0, len(row) - 1) * gap
        start_x = center_x - total / 2 + BOX_W / 2
        for index, (cid, _name, role) in enumerate(row):
            # Keep the focus node visually centred even though it is wider.
            node_w = FBOX_W if role == "focus" else BOX_W
            x = center_x if role == "focus" and len(row) == 1 else (
                start_x + index * (BOX_W + gap)
            )
            pos[cid] = (x, y + row_h / 2)
        y += row_h + row_gap
    return pos, int(w), int(h)


def _layered_layout(nodes, edges) -> dict[str, tuple[float, float]]:
    """Original layered/grid layout for the full-network (no-focus) view."""
    ids = [n[0] for n in nodes]
    layer: dict[str, int] = {i: 0 for i in ids}
    for _ in range(len(ids) + 2):
        changed = False
        for s, t, _, _ in edges:
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
        draw.text((MARGIN, 8), _t("focus_title", name=focus_name), fill=TITLE, font=title_font)
    else:
        draw.text((MARGIN, 8), _t("concept_structure"), fill=TITLE, font=title_font)

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
    from expert_anything.core.decoder import rel_semantic_color, classify_relation
    for s, t, lbl, rtype in edges:
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
            color = rel_semantic_color(lbl or "", rtype or "")
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
