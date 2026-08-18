"""Self-contained HTML learning report generator.

Produces an offline HTML file (no external CDN / fonts) that visualises the
learner's progress: a mastery bar overview, a force-laid-out concept network
coloured by mastery, per-concept detail, and the recent evaluation history.

The layout is computed in pure Python so the output is deterministic per seed
and has zero runtime dependencies beyond the standard library.
"""
from __future__ import annotations

import html
import math
import random
from typing import Any

from expert_anything.core.i18n import t
from expert_anything.core.learner import normalize


def localize_method(method: str) -> str:
    """Map an internal extraction-method identifier to a human-readable label.

    Examples
    --------
    ``llm_extraction_chunked_v1`` -> "LLM 抽取"
    ``llm_failed_fallback_v1``    -> "确定性模式（未深度加工）"
    """
    m = (method or "").lower()
    if "fallback" in m or "failed" in m or "deterministic" in m:
        return t("method_fallback")
    if "llm" in m or "extraction" in m or "chunked" in m:
        return t("method_llm")
    return t("method_unknown")


def _escape(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _color_for_mastery(m: float) -> str:
    if m >= 0.6:
        return "#4CAF50"  # mastered — green
    if m >= 0.3:
        return "#FF9800"  # learning — orange
    if m > 0:
        return "#E53935"  # weak — red
    return "#9E9E9E"  # unstudied — grey


def _force_layout(nodes: list[str], edges: list[tuple[str, str]],
                  width: int = 920, height: int = 560, seed: int = 7
                  ) -> dict[str, tuple[float, float]]:
    """Minimal force-directed layout (Fruchterman–Reingold style).

    Returns ``{node_id: (x, y)}`` in SVG coordinates. Deterministic for a
    given seed so the same data always renders the same picture.
    """
    random.seed(seed)
    n = len(nodes)
    if n == 0:
        return {}
    pos: dict[str, list[float]] = {}
    cx, cy = width / 2, height / 2
    R = min(width, height) / 2 - 70
    for i, nd in enumerate(nodes):
        ang = 2 * math.pi * i / max(n, 1)
        pos[nd] = [
            cx + R * math.cos(ang) + random.uniform(-25, 25),
            cy + R * math.sin(ang) + random.uniform(-25, 25),
        ]
    if n <= 1:
        return {k: (v[0], v[1]) for k, v in pos.items()}

    k = 110.0  # ideal edge length
    for _ in range(320):
        disp = {nd: [0.0, 0.0] for nd in nodes}
        # repulsion (all pairs)
        for i in range(n):
            a = nodes[i]
            for j in range(i + 1, n):
                b = nodes[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d2 = dx * dx + dy * dy
                if d2 < 0.01:
                    dx, dy = random.uniform(-1, 1), random.uniform(-1, 1)
                    d2 = dx * dx + dy * dy + 0.01
                d = math.sqrt(d2)
                rep = (k * k) / d
                fx, fy = dx / d * rep, dy / d * rep
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy
        # attraction along edges
        for a, b in edges:
            if a not in pos or b not in pos:
                continue
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) + 0.01
            att = (d * d) / k
            fx, fy = dx / d * att, dy / d * att
            disp[a][0] -= fx
            disp[a][1] -= fy
            disp[b][0] += fx
            disp[b][1] += fy
        # gravity to centre + clamped update
        for nd in nodes:
            px, py = pos[nd]
            disp[nd][0] += (cx - px) * 0.02
            disp[nd][1] += (cy - py) * 0.02
            dl = math.sqrt(disp[nd][0] ** 2 + disp[nd][1] ** 2) + 0.01
            step = min(dl, 22.0)
            pos[nd][0] = max(40, min(width - 40, px + disp[nd][0] / dl * step))
            pos[nd][1] = max(40, min(height - 40, py + disp[nd][1] / dl * step))
    return {k: (v[0], v[1]) for k, v in pos.items()}


def _pick_primary_asset(assets: dict, current_asset_id: str | None) -> str | None:
    if current_asset_id and current_asset_id in assets:
        return current_asset_id
    if not assets:
        return None
    # otherwise the asset with the most concepts
    return max(
        assets.items(),
        key=lambda kv: len(kv[1].get("concepts", []) or []),
    )[0]


def build_html_report(assets: dict, learner: dict,
                      lang: str = "zh-CN",
                      current_asset_id: str | None = None) -> str:
    """Build a complete, offline HTML report string.

    Parameters
    ----------
    assets : dict
        Mapping ``asset_id -> asset dict`` as stored on disk
        (``KnowledgeAsset.to_dict`` form with ``concepts``/``relations``/``method``).
    learner : dict
        The learner model (``concepts`` keyed by normalized name with
        ``mastery``/``sources``, and ``history`` list).
    lang : str
        Active UI language code (``zh-CN`` / ``en`` / ``ja``).
    current_asset_id : str | None
        The asset the network map focuses on (falls back to the largest asset).
    """
    learner = learner or {}
    concept_mastery = learner.get("concepts", {}) or {}
    history = learner.get("history", []) or []

    # ---------- header / asset summary ----------
    asset_rows = []
    total_concepts = 0
    for aid, data in assets.items():
        title = data.get("title", aid)
        n_c = len(data.get("concepts", []) or [])
        n_r = len(data.get("relations", []) or [])
        total_concepts += n_c
        method_label = localize_method(data.get("method", ""))
        asset_rows.append(
            f"<tr><td>{_escape(title)}</td>"
            f"<td class='num'>{n_c}</td>"
            f"<td class='num'>{n_r}</td>"
            f"<td>{_escape(method_label)}</td></tr>"
        )
    asset_table = (
        "<table class='tbl'>"
        "<thead><tr><th>{}</th><th class='num'>{}</th>"
        "<th class='num'>{}</th><th>{}</th></tr></thead><tbody>{}</tbody></table>"
    ).format(
        _escape(t("report_assets").strip("【】[]")),
        _escape(t("total_concepts")),
        _escape(t("relations")),
        _escape(t("method_label")),
        "".join(asset_rows) or f"<tr><td colspan='4'>{_escape(t('none'))}</td></tr>",
    ) if assets else f"<p class='muted'>{_escape(t('no_asset'))}</p>"

    # ---------- mastery overview (cross-asset) ----------
    mastery_items = sorted(
        concept_mastery.values(),
        key=lambda c: -float(c.get("mastery", 0.0)),
    )
    mastered = sum(1 for c in mastery_items if float(c.get("mastery", 0)) >= 0.6)
    learning = sum(1 for c in mastery_items if 0.3 <= float(c.get("mastery", 0)) < 0.6)
    unstudied = sum(1 for c in mastery_items if float(c.get("mastery", 0)) < 0.3)
    avg = (sum(float(c.get("mastery", 0)) for c in mastery_items) / len(mastery_items)
           if mastery_items else 0.0)

    bars = []
    for c in mastery_items[:18]:
        name = c.get("name", "?")
        m = float(c.get("mastery", 0.0))
        pct = int(round(m * 100))
        color = _color_for_mastery(m)
        bars.append(
            "<div class='bar-row'>"
            f"<span class='bar-label'>{_escape(name)}</span>"
            "<span class='bar-track'>"
            f"<span class='bar-fill' style='width:{pct}%;background:{color}'></span>"
            f"<span class='bar-pct' style='color:{color}'>{pct}%</span>"
            "</span></div>"
        )
    bars_html = "".join(bars) if bars else f"<p class='muted'>{_escape(t('no_mastery_yet'))}</p>"

    # ---------- concept network (SVG) ----------
    primary = _pick_primary_asset(assets, current_asset_id)
    svg_html = _build_network_svg(assets.get(primary, {}), concept_mastery)

    # ---------- concept detail (primary asset) ----------
    detail_html = _build_concept_details(assets.get(primary, {}), concept_mastery)

    # ---------- history ----------
    hist_html = _build_history(history)

    # ---------- trace audit (claim-level: mastery -> recorded attempts) ----------
    audit_html = _build_trace_audit(history, learner)

    # ---------- assemble ----------
    title_txt = _escape(t("report_title"))
    generated = _escape(t("report_generated", t=datetime_now()))
    overview_lbl = _escape(t("html_overview"))
    avg_lbl = _escape(t("html_avg"))
    network_lbl = _escape(t("html_network"))
    concepts_lbl = _escape(t("html_concepts"))
    history_lbl = _escape(t("report_history").strip("【】[]"))
    audit_lbl = _escape(t("audit_title"))
    legend_lbl = _escape(t("html_legend"))
    stats = (
        f"<div class='kpis'>"
        f"<div class='kpi'><span class='k-num'>{total_concepts}</span>"
        f"<span class='k-lbl'>{_escape(t('stat_total'))}</span></div>"
        f"<div class='kpi'><span class='k-num' style='color:#4CAF50'>{mastered}</span>"
        f"<span class='k-lbl'>{_escape(t('mastered'))}</span></div>"
        f"<div class='kpi'><span class='k-num' style='color:#FF9800'>{learning}</span>"
        f"<span class='k-lbl'>{_escape(t('partial'))}</span></div>"
        f"<div class='kpi'><span class='k-num' style='color:#9E9E9E'>{unstudied}</span>"
        f"<span class='k-lbl'>{_escape(t('unstudied'))}</span></div>"
        f"<div class='kpi'><span class='k-num'>{avg:.0%}</span>"
        f"<span class='k-lbl'>{avg_lbl}</span></div>"
        f"</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="{_escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_txt}</title>
<style>
  :root {{
    --bg:#f5f7fa; --card:#ffffff; --ink:#1F2933; --muted:#6B7A90;
    --line:#E2E8F0; --accent:#1565C0;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",
    "PingFang SC","Microsoft YaHei",sans-serif; line-height:1.55; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:28px 20px 60px; }}
  header {{ border-bottom:3px solid var(--accent); padding-bottom:14px; margin-bottom:22px; }}
  header h1 {{ margin:0 0 4px; font-size:24px; }}
  header .gen {{ color:var(--muted); font-size:13px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:18px 20px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,.04); }}
  .card h2 {{ margin:0 0 14px; font-size:17px; color:var(--accent); }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:12px; }}
  .kpi {{ flex:1 1 110px; background:var(--bg); border:1px solid var(--line);
    border-radius:10px; padding:12px; text-align:center; }}
  .k-num {{ display:block; font-size:26px; font-weight:700; }}
  .k-lbl {{ display:block; font-size:12px; color:var(--muted); margin-top:2px; }}
  .tbl {{ width:100%; border-collapse:collapse; font-size:14px; }}
  .tbl th,.tbl td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
  .tbl th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; }}
  .tbl .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .bar-row {{ display:flex; align-items:center; gap:10px; margin:7px 0; font-size:13px; }}
  .bar-label {{ width:160px; flex:none; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; color:var(--ink); }}
  .bar-track {{ position:relative; flex:1; height:20px; background:var(--bg);
    border-radius:6px; overflow:hidden; }}
  .bar-fill {{ position:absolute; left:0; top:0; bottom:0; border-radius:6px; }}
  .bar-pct {{ position:absolute; right:8px; top:0; line-height:20px; font-size:12px;
    font-weight:600; }}
  .net-wrap {{ display:flex; gap:16px; flex-wrap:wrap; align-items:flex-start; }}
  svg {{ background:var(--bg); border:1px solid var(--line); border-radius:10px; }}
  .legend {{ font-size:12px; color:var(--muted); }}
  .legend .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%;
    margin-right:5px; vertical-align:middle; }}
  .cgrid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }}
  .ccard {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:var(--card); }}
  .ccard h3 {{ margin:0 0 4px; font-size:15px; display:flex; align-items:center; gap:8px; }}
  .ccard .m {{ font-size:12px; font-weight:600; }}
  .ccard .def {{ font-size:13px; color:var(--ink); margin:6px 0; }}
  .ccard .ev {{ font-size:12px; color:var(--muted); margin:0; padding-left:14px; }}
  .ccard .loc {{ font-size:11px; color:#0284C7; margin:2px 0 4px; }}
  .ccard .locnum {{ color:#0284C7; }}
  .muted {{ color:var(--muted); font-size:13px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
  .chip {{ background:var(--bg); border:1px solid var(--line); border-radius:999px;
    padding:3px 12px; font-size:12px; color:var(--muted); }}
  footer {{ color:var(--muted); font-size:12px; text-align:center; margin-top:24px; }}
  @media (max-width:640px) {{ .bar-label {{ width:110px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{title_txt}</h1>
    <div class="gen">{generated}</div>
  </header>

  <section class="card">
    {stats}
  </section>

  <section class="card">
    <h2>{overview_lbl}</h2>
    {bars_html}
  </section>

  <section class="card">
    <h2>{network_lbl}</h2>
    <div class="net-wrap">
      {svg_html}
      <div class="legend">
        <div><span class="dot" style="background:#4CAF50"></span>{_escape(t('legend_mastered'))}</div>
        <div><span class="dot" style="background:#FF9800"></span>{_escape(t('legend_partial'))}</div>
        <div><span class="dot" style="background:#E53935"></span>{_escape(t('legend_weak'))}</div>
        <div><span class="dot" style="background:#9E9E9E"></span>{_escape(t('legend_unstudied'))}</div>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>{concepts_lbl}</h2>
    {detail_html}
  </section>

  <section class="card">
    <h2>{history_lbl}</h2>
    {hist_html}
  </section>

  <section class="card">
    <h2>{audit_lbl}</h2>
    {audit_html}
  </section>

  <footer>ExpertAnything · {title_txt}</footer>
</div>
</body>
</html>"""


def _build_network_svg(asset: dict, concept_mastery: dict) -> str:
    concepts = asset.get("concepts", []) or []
    relations = asset.get("relations", []) or []
    if not concepts:
        return f"<p class='muted'>{_escape(t('html_no_concepts'))}</p>"
    id_to_name = {c.get("id"): c.get("name", "?") for c in concepts}
    nodes = [c.get("id") for c in concepts]
    edges = []
    for r in relations:
        s, tg = r.get("source"), r.get("target")
        if s in id_to_name and tg in id_to_name:
            edges.append((s, tg))
    W, H = 640, 420
    pos = _force_layout(nodes, edges, width=W, height=H)
    # mastery lookup by normalized name
    def _m(cid):
        name = id_to_name.get(cid, "")
        rec = concept_mastery.get(normalize(name), {})
        return float(rec.get("mastery", 0.0)) if isinstance(rec, dict) else 0.0

    parts = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img">']
    # edges
    for a, b in edges:
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#CBD5E0" stroke-width="1.2" />'
        )
    if not edges:
        parts.append(f'<text x="{W/2:.0f}" y="{H-12:.0f}" text-anchor="middle" '
                     f'fill="#9E9E9E" font-size="12">{_escape(t("html_no_relations"))}</text>')
    # nodes
    for cid in nodes:
        x, y = pos[cid]
        m = _m(cid)
        color = _color_for_mastery(m)
        name = id_to_name.get(cid, "?")
        r = 7 + 3 * m  # bigger = more mastered
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}" '
            f'fill-opacity="0.85" stroke="#fff" stroke-width="1.5" />'
        )
        # label
        parts.append(
            f'<text x="{x:.1f}" y="{y + r + 12:.1f}" text-anchor="middle" '
            f'font-size="11" fill="#1F2933">{_escape(name)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _build_concept_details(asset: dict, concept_mastery: dict) -> str:
    concepts = asset.get("concepts", []) or []
    if not concepts:
        return f"<p class='muted'>{_escape(t('html_no_concepts'))}</p>"
    cards = []
    for c in concepts:
        name = c.get("name", "?")
        rec = concept_mastery.get(normalize(name), {})
        m = float(rec.get("mastery", 0.0)) if isinstance(rec, dict) else 0.0
        color = _color_for_mastery(m)
        definition = c.get("definition") or c.get("summary") or ""
        evidence = c.get("evidence", []) or []
        locations = c.get("locations", []) or []

        # map each evidence to its source line (tolerant match against snippets)
        line_by_ev: dict[str, int] = {}
        for loc in locations:
            snip = loc.get("snippet") or ""
            if snip:
                line_by_ev[snip] = loc.get("line") or 0

        def _match_line(e: str) -> int:
            if e in line_by_ev:
                return line_by_ev[e]
            for snip, ln in line_by_ev.items():
                if ln and (e.startswith(snip) or snip.startswith(e)):
                    return ln
            return 0

        # primary locator line (first grounded location)
        loc_html = ""
        if locations:
            first = locations[0]
            parts = []
            if first.get("line"):
                parts.append(t("loc_line", n=first["line"]))
            if first.get("chapter"):
                parts.append(t("chapter_label", ch=first["chapter"]))
            if parts:
                loc_html = (
                    f"<div class='loc'>{_escape(' · '.join(parts))}</div>"
                )

        ev_items = []
        for e in evidence[:3]:
            line = _match_line(e)
            suffix = (
                f" <span class='locnum'>({_escape(t('loc_line', n=line))})</span>"
                if line else ""
            )
            ev_items.append(f"<li>{_escape(e)}{suffix}</li>")
        ev_html = "".join(ev_items)

        cards.append(
            "<div class='ccard'>"
            f"<h3><span class='dot' style='display:inline-block;width:10px;height:10px;"
            f"border-radius:50%;background:{color}'></span>{_escape(name)}"
            f"<span class='m' style='color:{color}'>{m:.0%}</span></h3>"
            f"<div class='def'>{_escape(definition)}</div>"
            + loc_html
            + (f"<ul class='ev'>{ev_html}</ul>" if ev_html else "")
            + "</div>"
        )
    return f"<div class='cgrid'>{''.join(cards)}</div>"


def _build_history(history: list) -> str:
    if not history:
        return f"<p class='muted'>{_escape(t('history_empty'))}</p>"
    rows = []
    for h in history[-12:]:
        at = (h.get("at", "") or "")[:19]
        concept = h.get("concept", "?")
        score = float(h.get("score", 0.0))
        feedback = h.get("feedback", "")
        color = "#4CAF50" if score >= 0.6 else ("#FF9800" if score >= 0.3 else "#E53935")
        rows.append(
            "<tr>"
            f"<td class='num'>{_escape(at)}</td>"
            f"<td>{_escape(concept)}</td>"
            f"<td class='num' style='color:{color};font-weight:600'>{score:.2f}</td>"
            f"<td>{_escape(feedback)}</td>"
            "</tr>"
        )
    return (
        "<table class='tbl'>"
        f"<thead><tr><th class='num'>{_escape(t('history_col_time'))}</th>"
        f"<th>{_escape(t('history_col_concept'))}</th>"
        f"<th class='num'>{_escape(t('history_col_score'))}</th>"
        f"<th>{_escape(t('history_col_feedback'))}</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _build_trace_audit(history: list, learner: dict) -> str:
    """Claim-level audit section (OmniScientist claim-check analogue).

    Every mastery number shown elsewhere in the report must trace back to
    recorded attempt rows: per-concept attempt counts, average scores, the
    channels (answer / quiz / practice) that produced them, style rotations
    and cross-judge arbitrations — all read from the learning trace, never
    from narrative text.
    """
    if not history:
        return f"<p class='muted'>{_escape(t('audit_no_trace'))}</p>"

    channel_labels = {
        "answer": t("audit_channel_answer"),
        "quiz": t("audit_channel_quiz"),
        "practice": t("audit_channel_practice"),
    }
    per: dict[str, dict] = {}
    rotated = 0
    arbitrated = 0
    for h in history:
        key = h.get("key") or normalize(h.get("concept", ""))
        if not key:
            continue
        meta = h.get("meta") or {}
        agg = per.setdefault(key, {
            "name": h.get("concept", key), "n": 0, "scores": [], "channels": set(),
        })
        agg["n"] += 1
        try:
            agg["scores"].append(float(h.get("score", 0.0)))
        except (TypeError, ValueError):
            pass
        ch = meta.get("channel") or ""
        if ch:
            agg["channels"].add(channel_labels.get(ch, ch))
        if meta.get("rotated_style"):
            rotated += 1
        try:
            if int(meta.get("judges", 1)) >= 2:
                arbitrated += 1
        except (TypeError, ValueError):
            pass

    # summary chips
    chips = [
        f"<span class='chip'>{_escape(t('audit_rotated_n', n=rotated))}</span>",
        f"<span class='chip'>{_escape(t('audit_arbitrated_n', n=arbitrated))}</span>",
    ]

    # stuck concepts (read from the same trace via stuck_concepts)
    from expert_anything.core.learner import stuck_concepts
    stuck = stuck_concepts(learner)
    if stuck:
        items = ", ".join(
            f"{_escape(s['name'])} ({s['avg']:.2f})" for s in stuck
        )
        stuck_html = (
            f"<div class='stuck-line' style='color:#B71C1C;font-size:13px;margin-top:8px'>"
            f"{_escape(t('audit_stuck_label', n=len(stuck)))}：{items}</div>"
        )
    else:
        stuck_html = (
            f"<div class='stuck-line muted' style='margin-top:8px'>"
            f"{_escape(t('audit_stuck_none'))}</div>"
        )

    concepts_rec = learner.get("concepts", {}) or {}
    rows = []
    for key, agg in sorted(per.items(), key=lambda kv: -kv[1]["n"]):
        m = float((concepts_rec.get(key) or {}).get("mastery", 0.0))
        avg = (sum(agg["scores"]) / len(agg["scores"])) if agg["scores"] else 0.0
        color = _color_for_mastery(m)
        chans = "、".join(sorted(agg["channels"])) or "—"
        rows.append(
            "<tr>"
            f"<td>{_escape(agg['name'])}</td>"
            f"<td class='num'>{agg['n']}</td>"
            f"<td class='num'>{avg:.2f}</td>"
            f"<td class='num' style='color:{color};font-weight:600'>{m:.0%}</td>"
            f"<td>{_escape(chans)}</td>"
            "</tr>"
        )

    table = (
        "<table class='tbl'>"
        f"<thead><tr><th>{_escape(t('history_col_concept'))}</th>"
        f"<th class='num'>{_escape(t('audit_col_attempts'))}</th>"
        f"<th class='num'>{_escape(t('audit_col_avg'))}</th>"
        f"<th class='num'>{_escape(t('audit_col_mastery'))}</th>"
        f"<th>{_escape(t('audit_col_channels'))}</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return (
        f"<p class='muted' style='margin:0 0 10px'>{_escape(t('audit_hint'))}</p>"
        f"<div class='chips'>{''.join(chips)}</div>"
        f"{stuck_html}"
        f"<div style='margin-top:12px'>{table}</div>"
    )


def datetime_now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
