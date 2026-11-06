"""Demo harness for the distributed-energy (DER) domain.

Run this to (1) generate + admit all four DER scenes, (2) render each to a
standalone offline HTML preview, and (3) exercise the two offline benchmarks
plus the quality gate for this single domain.  Pure stdlib + core layer only.
"""
import os
import json

from expert_anything.core import decoder as dc
import expert_anything.core.decoder_distributed_energy as der
from expert_anything.core.scene_benchmark import (
    build_toy_asset, run_domain_benchmark,
)
from expert_anything.core.learning_benchmark import run_learning_benchmarks
from expert_anything.core.quality_gate import run_quality_gate, evaluate_scene, evaluate_learning

OUT = os.path.join(os.path.dirname(__file__), "der_preview")
os.makedirs(OUT, exist_ok=True)

SCENES = [
    ("resource_form", "分布式发电资源形态", der.generate_resource_form_scene),
    ("aggregation", "微电网 · 虚拟电厂 · 需求响应", der.generate_aggregation_scene),
    ("balance", "削峰填谷 · 就地消纳 · 电压支撑", der.generate_balance_scene),
    ("value", "分布式能源价值链条", der.generate_value_scene),
]


def main():
    print("=" * 72)
    print("DER DOMAIN — scene generation + check_scene admission")
    print("=" * 72)
    for sid, label, fn in SCENES:
        spec = fn()
        ok, msgs = dc.check_scene(spec)
        types = sorted({e.get("type") for e in spec["edges"]})
        print(f"\n[{sid}] {label}")
        print(f"  admission : {'PASS' if ok else 'FAIL'}  (nodes={len(spec['nodes'])} "
              f"edges={len(spec['edges'])} steps={len(spec['steps'])} typed_edges={types})")
        print(f"  walkthrough: " + " → ".join(st["caption"] for st in spec["steps"]))
        # Render a standalone offline preview (L1/L2/L3 inline, no network).
        html = dc.render_interactive_html(
            spec, concept=label, source_title="分布式能源领域模板",
            definition="贴近用户侧、分散接入电网的小型发电/储能/可控负荷资源及其聚合形态。",
        )
        path = os.path.join(OUT, f"der_{sid}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"  preview    : {path}")

    print("\n" + "=" * 72)
    print("DER DOMAIN — scene_benchmark (curated vs fallback)")
    print("=" * 72)
    asset = build_toy_asset("distributed_energy")
    print(f"  toy asset  : {asset.asset_id} | concepts={len(asset.concepts)} "
          f"relations={len(asset.relations or [])}")
    srep = run_domain_benchmark("distributed_energy")
    av = srep.averages
    print(f"  curated structure_score = {av['curated_structure_score']}")
    print(f"  fallback structure_score = {av['fallback_structure_score']}")
    print(f"  Δstructure = {av['gain_structure']:+}")
    ok, detail = evaluate_scene(srep)
    print(f"  scene gate : {'PASS' if ok else 'FAIL'} — {detail}")

    print("\n" + "=" * 72)
    print("DER DOMAIN — learning_benchmark (coach loop really teaches)")
    print("=" * 72)
    lreports = run_learning_benchmarks(["distributed_energy"])
    for r in lreports:
        print(f"  [{r.asset_id:22s}] coverage={r.coverage:.2f} mean_mastery={r.mean_mastery:.2f} "
              f"weak_first={r.weak_first_rate:.2f} stuck={r.stuck_detected} "
              f"rerouted={r.stuck_rerouted} review_spaced={r.review_spaced_ok}")
    for r in lreports:
        for c in evaluate_learning(r):
            if not c["ok"]:
                print(f"    ! {c['name']} -> {c['detail']}")

    print("\n" + "=" * 72)
    print("DER DOMAIN — unified quality gate")
    print("=" * 72)
    gate = run_quality_gate(["distributed_energy"])
    print(gate.summary)
    for c in gate.checks:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']} — {c['detail']}")

    idx = os.path.join(OUT, "index.html")
    with open(idx, "w", encoding="utf-8") as fh:
        fh.write(_index_html())
    print(f"\n  index      : {idx}")


def _index_html() -> str:
    cards = "\n".join(
        f'    <li><a href="der_{sid}.html">{label}</a></li>'
        for sid, label, _ in SCENES
    )
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>分布式能源领域 · DER 预览</title>
<style>body{{font-family:'Microsoft YaHei',sans-serif;max-width:680px;margin:40px auto;padding:0 20px}}
h1{{font-size:22px}}li{{margin:8px 0;font-size:16px}}a{{color:#2563eb;text-decoration:none}}</style>
</head><body>
<h1>分布式能源（DER）领域 · 四个场景预览</h1>
<p>每个场景均为离线、自包含的 HTML，含 L1 静态总览 / L2 分步动画 / L3 排序小游戏。点击进入：</p>
<ul>
{cards}
</ul>
<p style="color:#666;font-size:13px">由 <code>decoder_distributed_energy.py</code> 生成，经 <code>check_scene</code> 准入，
并由 <code>core/decoder.render_interactive_html</code> 确定性渲染。</p>
</body></html>"""


if __name__ == "__main__":
    main()
