"""Knowledge Decoder: 解码抽象知识为多模态表征。

Vision (AGENTS.md): 本系统是知识解码与生成系统——把概念"解译"成
图像 / 动画 / 互动演示与小游戏，直到用户完全理解。

Pipeline (OmniScientist pattern: open reasoning inside, deterministic shell):

    概念 + 原文证据 + 关系
      → LLM 只产出 SceneSpec（类型化 JSON 场景规范，见 SCENE_SCHEMA）
      → check_scene() 代码准入校验（节点/边/步骤/游戏的结构合法性）
      → 确定性渲染器：
          render_svg()            静态结构图（单步高亮可选）
          render_step_svgs()      分步动画帧（QtSvg 逐步播放）
          render_interactive_html 自包含 HTML（动画 + 排序小游戏，浏览器打开）
      → 小游戏得分经既有 quiz 通道回写掌握度（回到学习闭环）

铁律：LLM 永不直接输出 SVG/HTML——它只描述"场景里有什么"，
"怎么画"由本模块的确定性代码决定。场景内容必须源于概念的
定义 / 证据 / 关系（来源约束延伸到多模态）。
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any

from expert_anything.core.checks import CheckResult

# --- scene schema -----------------------------------------------------------

NODE_KINDS = {"box", "store", "flow", "note", "current"}
MAX_NODES = 8
MIN_NODES = 3
MAX_STEPS = 6
MIN_STEPS = 2
CANVAS_W = 720
CANVAS_H_MIN = 380
# deterministic layout constants (nodes never overlap: columns own disjoint
# x-ranges, rows inside a column own disjoint y-ranges)
NODE_W = 168
ROW_GAP_Y = 28
MARGIN_X = 26
MARGIN_Y = 26

# palette per node kind: fill / stroke / text
KIND_COLORS = {
    "box": ("#E3F2FD", "#42A5F5", "#0D47A1"),
    "store": ("#FFF8E1", "#FFB300", "#6D4C41"),
    "flow": ("#E8F5E9", "#66BB6A", "#1B5E20"),
    "note": ("#F3E5F5", "#AB47BC", "#4A148C"),
    "current": ("#1565C0", "#0D47A1", "#FFFFFF"),
}
# gradient stops (top → bottom) per kind — richer than flat fills
KIND_GRADIENTS = {
    "box": ("#EAF4FE", "#BBDEFB"),
    "store": ("#FFFDF2", "#FFE082"),
    "flow": ("#F0F9F0", "#C5E1A5"),
    "note": ("#FAF0FC", "#E1BEE7"),
    "current": ("#2196F3", "#0D47A1"),
}
# tiny glyph badge per kind (drawn as SVG text — no icon fonts, stays offline)
KIND_BADGE = {"box": "▪", "store": "▣", "flow": "➜", "note": "✎", "current": "★"}


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _as_bool(v: Any) -> bool:
    return bool(v) and str(v).lower() not in ("false", "0", "no")


def check_scene(spec: Any) -> tuple[CheckResult, dict | None]:
    """Code-enforced admission for a SceneSpec (same pattern as checks.py).

    Returns (verdict, normalized_spec). The normalized spec is safe to render:
    every node has an id/label/kind/geometry, every edge/step reference
    resolves, the game (if any) has a legal answer permutation.
    """
    if not isinstance(spec, dict):
        return CheckResult(False, "scene_not_dict", "场景规范必须是 JSON 对象"), None

    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or not (MIN_NODES <= len(raw_nodes) <= MAX_NODES):
        return CheckResult(
            False, "scene_bad_node_count",
            f"nodes 必须是 {MIN_NODES}-{MAX_NODES} 个节点的数组"), None

    nodes: list[dict] = []
    seen_ids: set[str] = set()
    for i, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            return CheckResult(False, "scene_node_not_dict", f"第 {i+1} 个节点不是对象"), None
        nid = _as_str(n.get("id"))
        label = _as_str(n.get("label"))
        if not nid or not label:
            return CheckResult(False, "scene_node_missing_field",
                               f"第 {i+1} 个节点缺 id 或 label")
        if nid in seen_ids:
            return CheckResult(False, "scene_dup_node_id", f"节点 id 重复：{nid}"), None
        seen_ids.add(nid)
        kind = _as_str(n.get("kind"), "box")
        if kind not in NODE_KINDS:
            kind = "box"
        nodes.append({
            "id": nid, "label": label[:24], "kind": kind,
            # x/y from the LLM are deliberately ignored: layout is
            # presentation, owned entirely by _layout() (no overlap, ever)
        })

    node_index = {n["id"]: n for n in nodes}

    edges: list[dict] = []
    raw_edges = spec.get("edges") or []
    if not isinstance(raw_edges, list):
        raw_edges = []
    for i, e in enumerate(raw_edges):
        if not isinstance(e, dict):
            continue
        src, dst = _as_str(e.get("from")), _as_str(e.get("to"))
        if src not in node_index or dst not in node_index:
            return CheckResult(False, "scene_edge_bad_ref",
                               f"第 {i+1} 条边引用了不存在的节点（{src}→{dst}）"), None
        edges.append({
            "from": src, "to": dst,
            "label": _as_str(e.get("label"))[:12],
            "dashed": _as_bool(e.get("dashed")),
        })

    steps: list[dict] = []
    raw_steps = spec.get("steps")
    if not isinstance(raw_steps, list) or not (MIN_STEPS <= len(raw_steps) <= MAX_STEPS):
        return CheckResult(False, "scene_bad_step_count",
                           f"steps 必须是 {MIN_STEPS}-{MAX_STEPS} 步的动画时间线"), None
    for i, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            return CheckResult(False, "scene_step_not_dict", f"第 {i+1} 步不是对象"), None
        show = s.get("show") or []
        if not isinstance(show, list):
            show = [show]
        show_ids = [_as_str(x) for x in show if _as_str(x)]
        bad = [x for x in show_ids if x not in node_index]
        if bad:
            return CheckResult(False, "scene_step_bad_ref",
                               f"第 {i+1} 步引用了不存在的节点：{bad}"), None
        active = _as_str(s.get("active"))
        if active and active not in node_index:
            active = ""
        caption = _as_str(s.get("caption"))
        if not caption:
            return CheckResult(False, "scene_step_no_caption", f"第 {i+1} 步缺 caption"), None
        steps.append({"caption": caption[:80], "show": show_ids, "active": active})

    game = None
    raw_game = spec.get("game")
    if isinstance(raw_game, dict) and _as_str(raw_game.get("type")) == "sort":
        items = [_as_str(x) for x in (raw_game.get("items") or []) if _as_str(x)]
        if not (3 <= len(items) <= 6):
            return CheckResult(False, "scene_game_bad_items", "游戏 items 需要 3-6 项"), None
        answer = raw_game.get("answer")
        if not isinstance(answer, list) or len(answer) != len(items):
            return CheckResult(False, "scene_game_bad_answer", "游戏 answer 长度必须等于 items"), None
        try:
            answer = [int(a) for a in answer]
        except (TypeError, ValueError):
            return CheckResult(False, "scene_game_bad_answer", "游戏 answer 必须是索引数组"), None
        if sorted(answer) != list(range(len(items))):
            return CheckResult(False, "scene_game_not_permutation",
                               "游戏 answer 必须是 0..n-1 的一个排列"), None
        game = {
            "type": "sort",
            "goal": _as_str(raw_game.get("goal"), "把下列内容排成正确顺序")[:60],
            "items": [x[:40] for x in items],
            "answer": answer,
        }

    norm = {
        "title": _as_str(spec.get("title"))[:40],
        "nodes": nodes,
        "edges": edges,
        "steps": steps,
        "game": game,
    }
    _layout(norm)
    return CheckResult(True), norm


# --- deterministic layout ---------------------------------------------------

def _layout(spec: dict) -> None:
    """Fully deterministic layout — LLM-supplied coordinates are ignored.

    Layered DAG layout: nodes are grouped by longest-path depth. Few layers
    (≤4) read left→right like a pipeline; many layers (long chains) switch
    to top→bottom so nodes stay readable instead of shrinking. Overlap is
    impossible by construction either way.
    """
    nodes = spec["nodes"]
    edges = spec["edges"]

    # node geometry from label length (never from the LLM)
    for n in nodes:
        n["w"] = NODE_W
        n["h"] = max(46, 18 + len(_wrap_label(n["label"])) * 16)

    depth = {n["id"]: 0 for n in nodes}
    for _ in range(len(nodes)):  # bounded relaxation — cycles can't loop
        changed = False
        for e in edges:
            s, t = e["from"], e["to"]
            if s == t:
                continue
            if depth[t] < depth[s] + 1:
                depth[t] = depth[s] + 1
                changed = True
        if not changed:
            break

    layers: dict[int, list[dict]] = {}
    for n in nodes:  # original spec order is deterministic within a layer
        layers.setdefault(depth[n["id"]], []).append(n)
    keys = sorted(layers)
    columns = [layers[k] for k in keys]
    n_cols = len(columns)

    if n_cols <= 4:
        # horizontal pipeline: layers as columns, each vertically centered
        canvas_w = max(
            CANVAS_W, 2 * MARGIN_X + n_cols * NODE_W + (n_cols - 1) * 36)
        canvas_h = max(
            CANVAS_H_MIN,
            2 * MARGIN_Y + max(
                sum(c["h"] for c in col) + ROW_GAP_Y * (len(col) - 1)
                for col in columns),
        )
        span = canvas_w - 2 * MARGIN_X - NODE_W
        for ci, col in enumerate(columns):
            x = MARGIN_X + (ci * span / (n_cols - 1) if n_cols > 1 else span / 2)
            total = sum(c["h"] for c in col) + ROW_GAP_Y * (len(col) - 1)
            y = max(MARGIN_Y, (canvas_h - total) / 2)
            for c in col:
                c["x"], c["y"] = int(x), int(y)
                y += c["h"] + ROW_GAP_Y
    else:
        # vertical flow: layers as rows (long chains stay readable)
        col_gap_x = 36
        row_gap_y = 34
        canvas_w = max(
            CANVAS_W,
            2 * MARGIN_X + max(len(col) for col in columns) * NODE_W
            + (max(len(col) for col in columns) - 1) * col_gap_x,
        )
        y = MARGIN_Y
        for col in columns:
            row_h = max(c["h"] for c in col)
            total_w = len(col) * NODE_W + (len(col) - 1) * col_gap_x
            x = (canvas_w - total_w) / 2
            for c in col:
                c["x"] = int(x)
                c["y"] = int(y + (row_h - c["h"]) / 2)  # center in the row
                x += NODE_W + col_gap_x
            y += row_h + row_gap_y
        canvas_h = y - row_gap_y + MARGIN_Y

    spec["width"] = int(canvas_w)
    spec["height"] = int(canvas_h)


# --- SVG rendering ----------------------------------------------------------

def _wrap_label(label: str, width_chars: int = 10, max_lines: int = 3) -> list[str]:
    """CJK-aware wrap: ~10 chars per line, at most 3 lines (+…)."""
    lines, cur = [], ""
    for ch in label:
        cur += ch
        if len(cur) >= width_chars:
            lines.append(cur)
            cur = ""
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and (sum(len(l) for l in lines) < len(label)):
        lines[-1] = lines[-1][:-1] + "…"
    return lines or [""]


def _esc(s: str) -> str:
    return _html.escape(str(s), quote=True)


def _svg_defs() -> str:
    """Shared <defs>: kind gradients, soft shadow, arrowhead, dotted grid."""
    parts = ["<defs>"]
    for kind, (c1, c2) in KIND_GRADIENTS.items():
        parts.append(
            f'<linearGradient id="g_{kind}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient>')
    parts.append(
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#FDFEFF"/><stop offset="1" stop-color="#EFF5FA"/>'
        "</linearGradient>")
    parts.append(
        '<pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">'
        '<circle cx="2" cy="2" r="1.1" fill="#DAE5F0"/></pattern>')
    parts.append(
        '<filter id="soft" x="-25%" y="-25%" width="150%" height="150%">'
        '<feDropShadow dx="0" dy="2.5" stdDeviation="3" '
        'flood-color="#23384D" flood-opacity="0.20"/></filter>')
    parts.append(
        '<marker id="ar" viewBox="0 0 10 10" refX="8.6" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#7E93A8"/></marker>')
    parts.append("</defs>")
    return "".join(parts)


def _edge_anchor(s: dict, t: dict) -> tuple[float, float, float, float]:
    """Anchor points for an edge: right→left of nodes, or bottom→top when
    the target sits left/above (keeps arrows readable in layered layouts)."""
    x1 = s["x"] + s["w"]; y1 = s["y"] + s["h"] / 2
    x2 = t["x"];          y2 = t["y"] + t["h"] / 2
    if x2 < x1 + 24:  # right-to-left / vertical
        x1, y1 = s["x"] + s["w"] / 2, s["y"] + s["h"]
        x2, y2 = t["x"] + t["w"] / 2, t["y"]
    return float(x1), float(y1), float(x2), float(y2)


def _quad_path(x1: float, y1: float, x2: float, y2: float,
               bow: float = 0.16) -> tuple[float, float, str]:
    """Curved edge: quadratic bezier bowed off the straight line."""
    dx, dy = x2 - x1, y2 - y1
    cx = (x1 + x2) / 2 - dy * bow
    cy = (y1 + y2) / 2 + dx * bow
    return cx, cy, f"M {x1:.0f},{y1:.0f} Q {cx:.0f},{cy:.0f} {x2:.0f},{y2:.0f}"


def _edge_shapes(e: dict, s: dict, t: dict, lit: bool) -> str:
    """Edge path + floating label chip. ``lit`` highlights edges touching the
    active node (orange, thicker)."""
    x1, y1, x2, y2 = _edge_anchor(s, t)
    cx, cy, d = _quad_path(x1, y1, x2, y2)
    color = "#F57C00" if lit else "#8FA5B8"
    width = 2.4 if lit else 1.7
    dash = ' stroke-dasharray="6,4"' if e.get("dashed") else ""
    parts = [
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"'
        f'{dash} stroke-linecap="round" marker-end="url(#ar)"/>',
    ]
    if e.get("label"):
        mx, my = cx, cy - 6
        parts.append(
            f'<rect x="{mx - len(e["label"]) * 6 - 4:.0f}" y="{my - 11:.0f}" '
            f'width="{len(e["label"]) * 12 + 8:.0f}" height="17" rx="8" '
            f'fill="{"#FFF3E0" if lit else "#FFFFFF"}" stroke="'
            f'{"#FFB74D" if lit else "#D7E1EC"}" stroke-width="1" opacity="0.96"/>'
            f'<text x="{mx:.0f}" y="{my:.0f}" text-anchor="middle" '
            f'font-size="11" font-weight="600" fill="{"#E65100" if lit else "#546E7A"}">'
            + _esc(e["label"]) + "</text>")
    return "".join(parts)


def _node_shapes(n: dict) -> str:
    """Node visuals: gradient body, soft shadow, kind badge, wrapped label,
    and an always-present halo ring (hidden unless the node is active)."""
    kind = n["kind"]
    _, stroke, color = KIND_COLORS.get(kind, KIND_COLORS["box"])
    x, y, nw, nh = n["x"], n["y"], n["w"], n["h"]
    parts = [
        # halo (visibility driven by caller / CSS class .act)
        f'<rect class="halo" x="{x - 6}" y="{y - 6}" width="{nw + 12}" '
        f'height="{nh + 12}" rx="13" fill="none" stroke="#FF9800" '
        'stroke-width="2.4"/>',
        f'<rect x="{x}" y="{y}" width="{nw}" height="{nh}" rx="10" '
        f'fill="url(#g_{kind})" stroke="{stroke}" stroke-width="1.6" '
        'filter="url(#soft)"/>',
        f'<circle cx="{x + 12}" cy="{y + 12}" r="8" fill="{stroke}" opacity="0.92"/>'
        f'<text x="{x + 12}" y="{y + 15.5}" text-anchor="middle" font-size="9" '
        'fill="#FFFFFF">' + _esc(KIND_BADGE.get(kind, "▪")) + "</text>",
    ]
    lines = _wrap_label(n["label"])
    line_h = 15
    ty = y + nh / 2 - (len(lines) - 1) * line_h / 2 + 5
    for ln in lines:
        parts.append(
            f'<text x="{x + nw / 2:.0f}" y="{ty:.0f}" text-anchor="middle" '
            f'font-size="12.5" font-weight="600" fill="{color}">'
            + _esc(ln) + "</text>")
        ty += line_h
    return "".join(parts)


def render_svg(spec: dict, step: int | None = None) -> str:
    """Render the scene as SVG.

    ``step``: index into spec["steps"] — nodes not shown by that step are
    faded (opacity 0.12) and the step's active node gets a highlight halo.
    ``None`` renders the full static diagram.
    """
    w, h = spec.get("width", CANVAS_W), spec.get("height", CANVAS_H_MIN)
    visible: set[str] | None = None
    active = ""
    if step is not None:
        steps = spec.get("steps") or []
        if steps:
            step = max(0, min(step, len(steps) - 1))
            visible = set()
            for s in steps[: step + 1]:
                visible.update(s.get("show") or [])
            active = steps[step].get("active") or ""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="100%" style="max-width:{w}px;font-family:'
        f"'Noto Sans','Microsoft YaHei',sans-serif\">",
        _svg_defs(),
        f'<rect width="{w}" height="{h}" rx="14" fill="url(#bg)"/>',
        f'<rect width="{w}" height="{h}" rx="14" fill="url(#dots)"/>',
    ]
    by_id = {n["id"]: n for n in spec["nodes"]}
    # edges first (under nodes)
    for e in spec.get("edges", []):
        s, t = by_id.get(e["from"]), by_id.get(e["to"])
        if s is None or t is None:
            continue
        both = s["id"] in visible and t["id"] in visible if visible is not None else True
        faded = visible is not None and not both
        op = 0.12 if faded else 1.0
        lit = bool(both) and active in (s["id"], t["id"])
        parts.append(f'<g opacity="{op}">' + _edge_shapes(e, s, t, lit) + "</g>")
    # nodes
    for n in spec["nodes"]:
        faded = visible is not None and n["id"] not in visible
        op = 0.12 if faded else 1.0
        act = n["id"] == active
        inner = _node_shapes(n)
        if not act:
            inner = inner.replace('<rect class="halo"', '<rect display="none" class="halo"', 1)
        parts.append(f'<g opacity="{op}">{inner}</g>')
    parts.append("</svg>")
    return "".join(parts)


def render_stage_svg(spec: dict) -> str:
    """Single SVG containing every node/edge, tagged with classes + data ids.

    The interactive HTML player toggles ``.off`` / ``.act`` / ``.pop`` /
    ``.lit`` classes for smooth CSS transitions — one DOM, animated states,
    instead of swapping pre-rendered frames. Browsers only; the desktop
    step player keeps using render_step_svgs() frames (QtSvg).
    """
    w, h = spec.get("width", CANVAS_W), spec.get("height", CANVAS_H_MIN)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="100%" style="font-family:'
        f"'Noto Sans','Microsoft YaHei',sans-serif\">",
        _svg_defs(),
        f'<rect width="{w}" height="{h}" rx="14" fill="url(#bg)"/>',
        f'<rect width="{w}" height="{h}" rx="14" fill="url(#dots)"/>',
    ]
    by_id = {n["id"]: n for n in spec["nodes"]}
    for i, e in enumerate(spec.get("edges", [])):
        s, t = by_id.get(e["from"]), by_id.get(e["to"])
        if s is None or t is None:
            continue
        parts.append(
            f'<g class="ed" data-f="{_esc(e["from"])}" data-t="{_esc(e["to"])}">'
            + _edge_shapes(e, s, t, False) + "</g>")
    for n in spec["nodes"]:
        parts.append(
            f'<g class="nd" data-id="{_esc(n["id"])}">' + _node_shapes(n) + "</g>")
    parts.append("</svg>")
    return "".join(parts)


def render_step_svgs(spec: dict) -> list[dict]:
    """All animation frames: [{caption, svg}] — the desktop step player and
    the HTML autoplay timeline both consume this."""
    out = []
    for i, s in enumerate(spec.get("steps") or []):
        out.append({"caption": s.get("caption", ""), "svg": render_svg(spec, step=i)})
    return out


# --- interactive HTML -------------------------------------------------------

def render_interactive_html(spec: dict, concept: str = "", source_title: str = "") -> str:
    """Self-contained offline HTML: progressive knowledge representation.

    Levels (minimal cognitive cost first — nothing animates by default):
      L1 static overview (all nodes visible, the default view)
      L2 step-by-step walkthrough (opt-in via button / → / Space)
      L3 ordering mini-game (score re-enters the mastery loop)

    Everything (steps, game, chrome text) is inlined — no network, no CDN.
    Chrome strings go through i18n at render time (never frozen at import).

    Visual architecture: the stage is ONE svg (render_stage_svg) whose
    nodes/edges carry classes; the player toggles .off/.act/.pop/.lit so
    step changes animate via CSS transitions instead of swapping frames.
    """
    from expert_anything.core.i18n import t

    stage_svg = render_stage_svg(spec)
    steps_meta = [
        {"caption": s.get("caption", ""), "show": s.get("show") or [],
         "active": s.get("active") or ""}
        for s in (spec.get("steps") or [])
    ]
    # keep the FRAMES name (existing embedders/tests) — now step descriptors
    # JSON inside <script>: "\/" (valid alias for "/") neutralizes "</script".
    frames_json = json.dumps(steps_meta, ensure_ascii=False).replace("</", "<\\/")

    game = spec.get("game")
    game_html = ""
    if game:
        items_json = json.dumps(game["items"], ensure_ascii=False).replace("</", "<\\/")
        partial_tpl = json.dumps(t("decoder_game_partial"), ensure_ascii=False)
        correct_txt = json.dumps(t("decoder_game_correct"), ensure_ascii=False)
        goal = _esc(game["goal"])
        n_items = len(game["items"])
        slots = "".join(
            f'<div class="slot" data-pos="{i}"><i>{i + 1}</i><span></span></div>'
            for i in range(n_items))
        chips = "".join(
            f'<button class="chip" data-i="{i}">{_esc(x)}</button>'
            for i, x in enumerate(game["items"]))
        game_html = f"""
    <section class="card">
      <div class="card-head">
        <h2>{_esc(t("decoder_game_title"))}</h2>
        <span class="pill">{_esc(t("decoder_game_hint"))}</span>
      </div>
      <p class="goal">{goal}</p>
      <div class="chips" id="pool">{chips}</div>
      <div class="slots" id="slots">{slots}</div>
      <div class="btns">
        <button id="check" class="primary">{_esc(t("decoder_game_check"))}</button>
        <button id="reveal">{_esc(t("decoder_game_answer"))}</button>
        <button id="retry">{_esc(t("decoder_game_retry"))}</button>
      </div>
      <p id="verdict" class="verdict"></p>
      <div id="confetti"></div>
    </section>
    <script>
    var ANSWER = {json.dumps(game["answer"])};
    var ITEMS = {items_json};
    var PARTIAL = {partial_tpl};
    var CORRECT = {correct_txt};
    var picked = ITEMS.map(function() {{ return null; }});
    function render() {{
      picked.forEach(function(it, pos) {{
        var slot = document.querySelector('.slot[data-pos="' + pos + '"]');
        slot.classList.toggle("filled", it !== null);
        slot.querySelector("span").textContent = it === null ? "" : ITEMS[it];
      }});
      Array.prototype.forEach.call(
        document.querySelectorAll("#pool .chip"),
        function(b) {{ b.disabled = picked.indexOf(+b.dataset.i) >= 0; }});
    }}
    function clearMarks() {{
      document.querySelectorAll(".slot").forEach(function(s) {{
        s.classList.remove("ok", "no", "reveal");
      }});
      var v = document.getElementById("verdict");
      v.className = "verdict"; v.textContent = "";
    }}
    document.getElementById("pool").onclick = function(ev) {{
      var b = ev.target.closest("button.chip");
      if (!b) return;
      var i = +b.dataset.i;
      if (picked.indexOf(i) >= 0) return;
      for (var p = 0; p < picked.length; p++) {{
        if (picked[p] === null) {{ picked[p] = i; break; }}
      }}
      render();
    }};
    document.getElementById("slots").onclick = function(ev) {{
      var slot = ev.target.closest(".slot");
      if (!slot || !slot.classList.contains("filled")) return;
      picked[+slot.dataset.pos] = null;
      clearMarks(); render();
    }};
    document.getElementById("check").onclick = function() {{
      if (picked.some(function(x) {{ return x === null; }})) return;
      var hits = 0;
      picked.forEach(function(x, pos) {{
        var slot = document.querySelector('.slot[data-pos="' + pos + '"]');
        var good = x === ANSWER[pos];
        if (good) hits++;
        slot.classList.add(good ? "ok" : "no");
      }});
      var v = document.getElementById("verdict");
      if (hits === ANSWER.length) {{
        v.textContent = CORRECT; v.className = "verdict ok"; confetti();
      }} else {{
        v.textContent = PARTIAL.replace("{{ok}}", hits).replace("{{n}}", ANSWER.length);
        v.className = "verdict no";
      }}
    }};
    document.getElementById("reveal").onclick = function() {{
      clearMarks();
      ANSWER.forEach(function(it, pos) {{ picked[pos] = it; }});
      render();
      document.querySelectorAll(".slot").forEach(function(s) {{
        s.classList.add("reveal");
      }});
    }};
    document.getElementById("retry").onclick = function() {{
      clearMarks();
      picked = ITEMS.map(function() {{ return null; }});
      render();
    }};
    function confetti() {{
      var c = document.getElementById("confetti");
      c.innerHTML = "";
      var colors = ["#F44336", "#FF9800", "#FDD835", "#43A047",
                    "#1E88E5", "#AB47BC"];
      for (var k = 0; k < 44; k++) {{
        var s = document.createElement("span");
        s.style.left = (Math.random() * 100) + "%";
        s.style.background = colors[k % colors.length];
        s.style.animationDelay = (Math.random() * 0.5).toFixed(2) + "s";
        c.appendChild(s);
      }}
      setTimeout(function() {{ c.innerHTML = ""; }}, 2600);
    }}
    render();
    </script>"""

    title = _esc(spec.get("title") or concept)
    head = _esc(" · ".join(x for x in (concept, source_title) if x))
    # progressive representation (L1 → L2): overview first, minimal cognitive
    # cost; step animation and the game are opt-in upgrades, never defaults.
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — ExpertAnything</title>
<style>
  :root {{ --ink:#1C2B3A; --muted:#7B8FA3; --line:#E3EAF3; }}
  body {{ font-family: 'Noto Sans','Microsoft YaHei',sans-serif; margin: 0;
         background: radial-gradient(1100px 420px at 50% -120px, #DCE9F8 0%,
                      rgba(220,233,248,0) 62%), #F5F8FC;
         color: var(--ink); }}
  .wrap {{ max-width: 800px; margin: 0 auto; padding: 26px 16px 70px; }}
  .hero {{ position: relative; overflow: hidden; color: #fff; border-radius: 18px;
          padding: 26px 26px 22px; margin-bottom: 18px;
          background: linear-gradient(120deg, #0D47A1 0%, #1976D2 55%, #00ACC1 100%);
          box-shadow: 0 12px 30px rgba(13, 71, 161, 0.28); }}
  .hero::after {{ content: ""; position: absolute; right: -55px; top: -55px;
          width: 210px; height: 210px; border-radius: 50%;
          background: rgba(255,255,255,0.10); }}
  .hero::before {{ content: ""; position: absolute; right: 60px; bottom: -95px;
          width: 180px; height: 180px; border-radius: 50%;
          background: rgba(255,255,255,0.08); }}
  .hero-badge {{ display: inline-block; font-size: 11px; letter-spacing: 2.5px;
          background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.35);
          padding: 3px 12px; border-radius: 999px; }}
  .hero h1 {{ margin: 10px 0 4px; font-size: 24px; letter-spacing: 0.5px; }}
  .hero .sub {{ color: rgba(255,255,255,0.78); font-size: 13px; }}
  .card {{ background: #fff; border: 1px solid var(--line); border-radius: 18px;
          padding: 18px; margin-bottom: 18px;
          box-shadow: 0 8px 24px rgba(23, 54, 93, 0.07); }}
  .card-head {{ display: flex; align-items: center; justify-content: space-between;
          gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }}
  h2 {{ font-size: 14px; color: #33475C; margin: 0; }}
  .pill {{ font-size: 11px; color: #5B7290; background: #EEF3FA;
          border-radius: 999px; padding: 3px 10px; transition: all 0.3s; }}
  .stage {{ border-radius: 12px; overflow: hidden; background: #FBFDFF;
          border: 1px solid #EDF2F8; }}
  .stage svg {{ display: block; width: 100%; height: auto; }}
  /* scene element state machine (classes toggled by the player) */
  .stage .nd, .stage .ed {{ transition: opacity 0.55s ease; }}
  .stage .nd {{ transform-box: fill-box; transform-origin: center; }}
  .stage .nd.off {{ opacity: 0.07; }}
  .stage .nd.pop {{ animation: ndpop 0.6s cubic-bezier(0.2, 0.8, 0.3, 1.25); }}
  @keyframes ndpop {{ 0% {{ opacity: 0; transform: scale(0.5); }}
          60% {{ transform: scale(1.07); }}
          100% {{ opacity: 1; transform: scale(1); }} }}
  .stage .nd .halo {{ opacity: 0; transition: opacity 0.4s; }}
  .stage .nd.act .halo {{ opacity: 1; animation: haloPulse 1.6s ease-in-out infinite; }}
  @keyframes haloPulse {{ 0%, 100% {{ stroke-opacity: 0.95; }}
          50% {{ stroke-opacity: 0.2; }} }}
  .stage .ed.off {{ opacity: 0.05; }}
  .stage .ed.lit path {{ stroke-dasharray: 7 5; animation: edflow 1.1s linear infinite; }}
  @keyframes edflow {{ to {{ stroke-dashoffset: -24; }} }}
  .caption {{ min-height: 40px; margin-top: 12px; font-size: 14.5px; color: #123B66;
          opacity: 0; transform: translateY(6px); transition: all 0.45s ease; }}
  .caption.show {{ opacity: 1; transform: none; }}
  .caption b {{ display: inline-block; color: #fff; border-radius: 8px;
          font-size: 12px; padding: 1px 9px; margin-right: 8px;
          background: linear-gradient(120deg, #1976D2, #00ACC1); }}
  .timeline {{ display: flex; gap: 8px; margin: 12px 0 2px; }}
  .dot {{ width: 27px; height: 27px; border-radius: 50%; border: 2px solid #C6D4E4;
          background: #fff; color: var(--muted); font-size: 12px; cursor: pointer;
          transition: all 0.25s; }}
  .dot:hover {{ transform: translateY(-2px); }}
  .dot.done {{ background: #DCEBFB; border-color: #64B5F6; color: #1565C0; }}
  .dot.cur {{ color: #fff; border-color: transparent;
          background: linear-gradient(120deg, #1976D2, #00ACC1);
          box-shadow: 0 4px 10px rgba(25, 118, 210, 0.4); }}
  .btns button {{ border: 1px solid #C9D6E5; background: #fff; border-radius: 10px;
          padding: 7px 16px; font-size: 13px; cursor: pointer; margin: 10px 6px 0 0;
          color: #33475C; transition: all 0.2s; }}
  .btns button:hover {{ transform: translateY(-1px);
          box-shadow: 0 4px 10px rgba(23, 54, 93, 0.12); }}
  .btns button.primary {{ color: #fff; border: none; font-weight: 600;
          background: linear-gradient(120deg, #1976D2, #00ACC1); }}
  .btns button.ghost {{ border-style: dashed; color: #5B7290; }}
  /* game */
  .goal {{ font-size: 13px; color: #5B7290; margin: 4px 0 10px; }}
  .chip {{ display: inline-block; margin: 4px; padding: 8px 14px;
          border-radius: 999px; border: 1.5px solid #90CAF9; color: #0D47A1;
          background: linear-gradient(180deg, #F4F9FF, #E3F2FD); font-size: 13px;
          cursor: pointer; transition: all 0.18s; }}
  .chip:hover:not(:disabled) {{ transform: translateY(-2px);
          box-shadow: 0 5px 12px rgba(33, 150, 243, 0.25); }}
  .chip:disabled {{ opacity: 0.25; cursor: default; }}
  .slots {{ display: flex; flex-direction: column; gap: 8px; margin: 8px 0 4px; }}
  .slot {{ display: flex; align-items: center; gap: 10px; min-height: 42px;
          border: 2px dashed #C6D4E4; border-radius: 12px; padding: 8px 12px;
          background: #FBFDFF; transition: all 0.25s; }}
  .slot i {{ font-style: normal; flex: none; width: 22px; height: 22px;
          border-radius: 50%; background: #E8EFF8; color: #5B7290;
          display: flex; align-items: center; justify-content: center;
          font-size: 12px; transition: all 0.25s; }}
  .slot span {{ font-size: 13.5px; color: #123B66; font-weight: 600; }}
  .slot.filled {{ border-style: solid; border-color: #64B5F6; background: #F1F8FF;
          cursor: pointer; }}
  .slot.filled:hover {{ border-color: #EF5350; }}
  .slot.ok {{ border-color: #66BB6A; background: #EDF7ED; }}
  .slot.ok i {{ background: #66BB6A; color: #fff; }}
  .slot.ok::after {{ content: "\\2713"; color: #2E7D32; font-weight: 700;
          margin-left: auto; }}
  .slot.no {{ border-color: #EF9A9A; background: #FDEDED; }}
  .slot.no i {{ background: #EF9A9A; color: #fff; }}
  .slot.no::after {{ content: "\\2717"; color: #C62828; font-weight: 700;
          margin-left: auto; }}
  .slot.reveal {{ border-color: #FFB74D; background: #FFF8E1; }}
  .verdict {{ font-size: 14px; min-height: 22px; font-weight: 600; }}
  .verdict.ok {{ color: #2E7D32; }}
  .verdict.no {{ color: #C62828; }}
  #confetti {{ position: relative; height: 74px; overflow: hidden; margin-top: 2px; }}
  #confetti span {{ position: absolute; top: -14px; width: 9px; height: 14px;
          border-radius: 2px; opacity: 0;
          animation: fall 1.7s ease-in forwards; }}
  @keyframes fall {{ 0% {{ opacity: 1; transform: translateY(0) rotate(0deg); }}
          100% {{ opacity: 0; transform: translateY(95px) rotate(340deg); }} }}
  .foot {{ text-align: center; color: #9FB1C4; font-size: 11px;
          letter-spacing: 1.5px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <span class="hero-badge">{_esc(t("decoder_badge"))}</span>
    <h1>{title}</h1>
    <div class="sub">{head}</div>
  </div>
  <section class="card">
    <div class="card-head">
      <h2>{_esc(t("decoder_card_title"))}</h2>
      <span class="pill" id="stagepill">{_esc(t("decoder_overview_pill"))}</span>
    </div>
    <div class="stage" id="stage">{stage_svg}</div>
    <div class="caption" id="caption"></div>
    <div class="timeline" id="dots" style="display:none"></div>
    <div class="btns">
      <button id="back" class="ghost" style="display:none">
        &#9678; {_esc(t("decoder_overview_btn"))}</button>
      <button id="start" class="primary">{_esc(t("decoder_step_btn"))} &#8250;</button>
      <span id="stepctl" style="display:none">
        <button id="prev">&#8249; {_esc(t("decoder_prev"))}</button>
        <button id="play">&#9654; {_esc(t("decoder_play"))}</button>
        <button id="next">{_esc(t("decoder_next"))} &#8250;</button>
      </span>
    </div>
  </section>
  {game_html}
  <div class="foot">EXPERTANYTHING &middot; KNOWLEDGE DECODER</div>
</div>
<script>
var FRAMES = {frames_json};
var OVERVIEW = {json.dumps(t("decoder_overview_hint"), ensure_ascii=False)};
var PILL_OV = {json.dumps(t("decoder_overview_pill"), ensure_ascii=False)};
var PILL_STEP = {json.dumps(t("decoder_step_pill"), ensure_ascii=False)};
var stage = document.getElementById("stage");
var nodesArr = stage.querySelectorAll(".nd");
var edgesArr = stage.querySelectorAll(".ed");
var dotsBox = document.getElementById("dots");
var cap = document.getElementById("caption");
var pill = document.getElementById("stagepill");
var playBtn = document.getElementById("play");
var backBtn = document.getElementById("back");
var startBtn = document.getElementById("start");
var stepCtl = document.getElementById("stepctl");
var PLAY_LABEL = playBtn.innerHTML;
FRAMES.forEach(function(f, k) {{
  var d = document.createElement("button");
  d.className = "dot"; d.textContent = k + 1;
  d.onclick = function() {{ enterStep(k); }};
  dotsBox.appendChild(d);
}});
var idx = 0, timer = null, inStep = false;
function setCaption(html) {{
  cap.classList.remove("show"); void cap.offsetWidth;
  cap.innerHTML = html; cap.classList.add("show");
}}
/* L1 — static overview: everything visible, nothing animates */
function showStatic() {{
  inStep = false; stopPlay();
  nodesArr.forEach(function(n) {{ n.classList.remove("off", "act", "pop"); }});
  edgesArr.forEach(function(e) {{ e.classList.remove("off", "lit"); }});
  setCaption("<b>&#9678;</b> " + OVERVIEW);
  pill.textContent = PILL_OV;
  dotsBox.style.display = "none";
  backBtn.style.display = "none";
  startBtn.style.display = "";
  stepCtl.style.display = "none";
}}
/* L2 — step-by-step walkthrough (opt-in, never the default) */
function enterStep(i) {{
  if (!inStep) {{
    inStep = true;
    dotsBox.style.display = "flex";
    backBtn.style.display = "";
    startBtn.style.display = "none";
    stepCtl.style.display = "";
    pill.textContent = PILL_STEP;
  }}
  show(i);
}}
function show(i) {{
  idx = Math.max(0, Math.min(FRAMES.length - 1, i));
  var vis = {{}};
  for (var k = 0; k <= idx; k++)
    FRAMES[k].show.forEach(function(id) {{ vis[id] = 1; }});
  var act = FRAMES[idx].active;
  nodesArr.forEach(function(n) {{
    var on = !!vis[n.dataset.id];
    var wasOff = n.classList.contains("off");
    n.classList.toggle("off", !on);
    if (on && wasOff) {{
      n.classList.remove("pop"); void n.getBoundingClientRect();
      n.classList.add("pop");
    }}
    n.classList.toggle("act", n.dataset.id === act);
  }});
  edgesArr.forEach(function(e) {{
    var on = !!vis[e.dataset.f] && !!vis[e.dataset.t];
    var wasOff = e.classList.contains("off");
    e.classList.toggle("off", !on);
    e.classList.remove("lit");
    if (on && wasOff) {{
      void e.getBoundingClientRect(); e.classList.add("lit");
      setTimeout(function() {{ e.classList.remove("lit"); }}, 1500);
    }}
  }});
  setCaption("<b>" + (idx + 1) + "/" + FRAMES.length + "</b> " +
             FRAMES[idx].caption);
  dotsBox.querySelectorAll(".dot").forEach(function(d, k) {{
    d.className = "dot" + (k === idx ? " cur" : (k < idx ? " done" : ""));
  }});
}}
document.getElementById("prev").onclick = function() {{ show(idx - 1); }};
document.getElementById("next").onclick = function() {{ show(idx + 1); }};
function stopPlay() {{
  if (timer) {{ clearInterval(timer); timer = null; }}
  playBtn.innerHTML = PLAY_LABEL;
}}
playBtn.onclick = function() {{
  if (timer) {{ stopPlay(); return; }}
  enterStep(0);
  playBtn.innerHTML = "&#10074;&#10074;";
  timer = setInterval(function() {{
    if (idx >= FRAMES.length - 1) {{ stopPlay(); return; }}
    show(idx + 1);
  }}, 2600);
}};
startBtn.onclick = function() {{ enterStep(0); }};
backBtn.onclick = function() {{ showStatic(); }};
document.addEventListener("keydown", function(ev) {{
  if (!inStep) {{
    if (ev.key === "ArrowRight" || ev.code === "Space") {{
      ev.preventDefault(); enterStep(0);
    }}
    return;
  }}
  if (ev.key === "ArrowLeft") show(idx - 1);
  else if (ev.key === "ArrowRight") show(idx + 1);
  else if (ev.key === "Escape") showStatic();
  else if (ev.code === "Space") {{ ev.preventDefault(); playBtn.click(); }}
}});
showStatic();
</script>
</body>
</html>"""


# --- deterministic fallback scene -------------------------------------------

def fallback_scene(asset, concept) -> dict:
    """No-LLM deterministic scene: the concept in the centre, its relation
    neighbours around it — a spec that always passes check_scene."""
    center = {"id": "c0", "label": concept.name[:20], "kind": "current"}
    nodes = [center]
    edges = []
    steps = [{"caption": f"定位「{concept.name}」——它居中高亮", "show": ["c0"], "active": "c0"}]
    i = 0
    for r in (getattr(asset, "relations", None) or []):
        other = None
        if r.source == concept.id:
            other = asset.concept_by_id(r.target)
        elif r.target == concept.id:
            other = asset.concept_by_id(r.source)
        if other is None or i >= 4:
            continue
        i += 1
        nid = f"c{i}"
        nodes.append({"id": nid, "label": other.name[:20], "kind": "box"})
        edges.append({"from": "c0" if r.target == concept.id else nid,
                      "to": nid if r.target == concept.id else "c0",
                      "label": (r.label or "")[:10], "dashed": False})
        steps.append({"caption": f"「{other.name[:14]}」——{(r.label or '关联')[:16]}",
                      "show": ["c0", nid], "active": nid})
    while len(nodes) < MIN_NODES:
        i += 1
        nodes.append({"id": f"c{i}", "label": f"相关概念 {i - 4}", "kind": "note"})
    # the admission gate requires >= MIN_STEPS — concepts without relations
    # still get a "read the evidence, restate it" closing step.
    if len(steps) < MIN_STEPS:
        steps.append({
            "caption": f"回到「{concept.name[:12]}」：对照原文证据，用自己的话复述它的定义与位置",
            "show": [n["id"] for n in nodes], "active": "c0",
        })
    verdict, spec = check_scene({"title": f"「{concept.name}」的知识结构",
                                 "nodes": nodes, "edges": edges, "steps": steps})
    if not verdict or spec is None:  # should never happen; guard anyway
        spec = {"title": concept.name, "nodes": nodes[:3], "edges": [], "steps": steps[:2],
                "game": None, "width": CANVAS_W, "height": CANVAS_H_MIN}
        for n in spec["nodes"]:
            n.setdefault("w", 160); n.setdefault("h", 52)
    return spec


def scene_summary(spec: dict | None) -> str:
    """One-line deterministic description (for logs / lesson card captions)."""
    if not spec:
        return ""
    bits = [f"nodes={len(spec.get('nodes', []))}",
            f"edges={len(spec.get('edges', []))}",
            f"steps={len(spec.get('steps', []))}"]
    if spec.get("game"):
        bits.append("game=sort")
    return " ".join(bits)


# tolerate trailing prose / fences (same as tutor._tolerant_json)
def tolerant_scene_json(text: str) -> dict:
    if not text:
        return {}
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
                return d if isinstance(d, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}
