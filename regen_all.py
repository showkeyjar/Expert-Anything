"""ExpertAnything 演示数据重建脚本 (offline, no LLM, no GUI).

Rebuilds the demo dataset under ``data/_demo`` so the ``data`` test layer
(storage/learner integrity) can run in CI instead of skipping:

    python regen_all.py

What it produces:
    data/_demo/assets/<asset_id>.json            two demo assets (from templates)
    data/_demo/assets/teacher_<asset_id>.json    deterministic teacher models
    data/_demo/learner.json                      cross-asset learner state

Rules:
    * Fully deterministic: assets are assembled from the built-in domain
      templates (domain_templates.py); teacher models use the no-LLM
      deterministic fallback; learner state is built via learner.register_asset.
      ``created_at`` is a fixed demo timestamp, so re-running produces the same
      structure and the same evidence anchors.
    * Relations are evidence-first. The source body carries two generated
      sections — ``## 学习顺序`` (prereq chain, one sentence per edge) and
      ``## 关系速览`` (curated semantic edges) — and every ``Relation.evidence``
      is an *exact whole line* sliced from ``source_text``. No template notes,
      no paraphrases, no stitching; each asset covers at least three of the six
      semantics (prereq plus two others) and keeps the edge count readable.
    * No network, no API key, no GUI, no mutation of real user data under
      data/assets (only data/_demo is written).
    * Idempotent: safe to re-run; existing files under data/_demo/assets are
      regenerated deterministically. The optional import-source sample
      data/_demo/electricity_trading_asset.json is *kept* if it already
      exists (it is user-facing demo material referenced by run_demo.py /
      QUICKSTART) and only synthesized from the template when missing.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DEMO = ROOT / "data" / "_demo"
ASSETS_DIR = DEMO / "assets"
IMPORT_SAMPLE = DEMO / "electricity_trading_asset.json"

# asset ids double as file stems, so learner.assets keys always match
# data/_demo/assets/<stem>.json (see tests/test_demo_data.py).
# Ordering matters for the app default: MainWindow picks the alphabetically
# first asset id as the current one, so electricity (002) stays the default.
ELECTRICITY_ASSET_ID = "a20260908-002"
CARBON_ASSET_ID = "a20260908-003"
RENEWABLE_ASSET_ID = "a20260908-004"
DER_ASSET_ID = "a20260908-005"

# Fixed demo timestamp keeps regeneration byte-stable (created_at feeds the
# knowledge-index hash, so a wall-clock value would make reruns differ).
DEMO_CREATED_AT = "2026-09-08T00:00:00+00:00"

# Curated semantic edges per domain: (source id, target id, canonical type,
# label, sentence). The sentence is written into the demo source verbatim and
# then sliced back as evidence, so it must name both endpoints and read as
# natural material (never as a template note). Types are validated against
# ``classify_relation`` at generation time.
_SEMANTIC_HINTS: dict[str, list[tuple[str, str, str, str, str]]] = {
    "electricity_trading": [
        ("et-010", "et-012", "part_of", "组成",
         "销售电价由上网电价、输配电价与政府性基金及附加三部分构成。"),
        # 输配电价→销售电价 与前置链 et-011→et-012 同端点对，舍弃以避免双线重叠。
        ("et-003", "et-004", "contrast", "对比",
         "中长期交易与现货交易形成对照：前者以年度、月度合约为主要手段，"
         "后者覆盖日前、日内与实时平衡。"),
        ("et-017", "et-018", "contrast", "对比",
         "容量电费与电量电费是一组对照：前者回收固定成本，后者反映可变成本与边际定价。"),
        ("et-004", "et-013", "causes", "影响",
         "现货交易的实时出清会直接影响节点边际电价(LMP)。"),
    ],
    "carbon_trading": [
        ("ct-009", "ct-004", "part_of", "组成",
         "履约周期以 MRV 监测-报告-核查为组成部分，覆盖核算、报告、核查与配额清缴全过程。"),
        ("ct-005", "ct-008", "contrast", "对比",
         "强制履约的碳排放权交易市场与自愿减排量形成对照：前者按配额履约，"
         "后者经核证后用于抵消。"),
        ("ct-002", "ct-006", "causes", "影响",
         "碳排放配额的供需松紧会直接影响碳价形成。"),
    ],
    "renewable_forecasting": [
        ("rf-001", "rf-004", "part_of", "组成",
         "超短期预测是预测时间尺度的组成部分，覆盖未来数分钟至 4 小时。"),
        ("rf-002", "rf-004", "part_of", "组成",
         "短期预测是预测时间尺度的组成部分，覆盖未来 0 至 72 小时。"),
        # 风电↔光伏 与前置链 rf-009→rf-010 同端点对，改用超短期↔短期做对比。
        ("rf-001", "rf-002", "contrast", "对比",
         "超短期预测与短期预测形成对照：前者覆盖未来数分钟至 4 小时，"
         "后者以日前预测为主、覆盖 0 至 72 小时。"),
        ("rf-005", "rf-009", "causes", "影响",
         "数值天气预报(NWP)的误差会直接影响风电功率预测的准确度。"),
    ],
    "distributed_energy": [
        ("de-002", "de-001", "is_a", "属于",
         "分布式光伏属于分布式发电的一种。"),
        ("de-003", "de-001", "is_a", "属于",
         "分散式风电同样属于分布式发电的一种。"),
        ("de-005", "de-013", "causes", "影响",
         "微电网的孤岛运行能在主网故障时直接促成韧性提升。"),
        ("de-002", "de-003", "contrast", "对比",
         "分布式光伏与分散式风电形成对照：前者依赖辐照，后者依赖风速。"),
    ],
}

# Hints skipped at generation time (id missing / duplicate endpoint pair /
# label does not express the declared semantics / sentence does not name both
# endpoints). Reported by main() so a data regression is visible, never silent.
_DROPPED_RELATIONS: list[tuple[str, str, str, str]] = []


def build_asset_from_template(
    domain_id: str, asset_id: str, title: str, source_name: str
) -> dict:
    """Assemble one demo asset (plain dict, asset-ID space ``c*``) from a
    domain template.

    Relations are written *after* the source body exists: the quick_path chain
    becomes the ``## 学习顺序`` section (one natural sentence per edge) and the
    curated hints become ``## 关系速览``. Every ``Relation.evidence`` is then
    exactly one of those whole lines, so ``_stamp_locations`` can anchor it and
    the edge card can jump to it. The generator validates this before returning
    (ids exist, both names appear verbatim, label expresses the declared type,
    evidence is a whole unique source line, >=3 semantics including prereq).
    """
    from expert_anything.core.domain_templates import get_domain_template

    template = get_domain_template(domain_id)
    if template is None:  # pragma: no cover - guarded by caller
        raise ValueError(f"unknown domain template: {domain_id}")

    id_map: dict[str, str] = {}  # template concept id -> asset c-id
    concepts: list[dict] = []
    chapters: list[dict] = []
    for ch_ord, ch in enumerate(template.chapters, start=1):
        chapters.append(
            {
                "id": ch.get("id", f"ch-{ch_ord:03d}"),
                "title": ch.get("title", ""),
                "order": ch_ord,
            }
        )
        for c in ch.get("concepts", []):
            cid = f"c{len(concepts) + 1:03d}"
            id_map[c["id"]] = cid
            concepts.append(
                {
                    "id": cid,
                    "name": c["name"],
                    "definition": c.get("definition", ""),
                    "summary": c.get("significance", ""),
                    "evidence": [],  # stamped below — must quote source_text verbatim
                    "chapter": ch.get("title", ""),
                    "locations": [],
                }
            )

    from expert_anything.core.decoder import classify_relation

    concept_name = {c["id"]: c["name"] for c in concepts}

    # learning path = quick_path mapped into the asset ID space
    learning_path = [id_map[tid] for tid in template.quick_path if tid in id_map]

    # A short readable source body derived from the template (demo only).
    # Concept evidence is the whole source line (anchorable by _stamp_locations).
    body = [f"# {template.name}", ""]
    ci = 0
    for ch in template.chapters:
        body.append(f"## {ch.get('title', '')}")
        for c in ch.get("concepts", []):
            line = f"- {c['name']}：{c.get('definition', '')}"
            body.append(line)
            concepts[ci]["evidence"] = [line]
            ci += 1
        body.append("")

    # prereq main line: one natural sentence per adjacent path pair, written as
    # its own line so Relation.evidence can be sliced back verbatim.
    chain_sentences = [
        f"学习顺序上，先掌握「{concept_name[a]}」，再进入「{concept_name[b]}」。"
        for a, b in zip(learning_path, learning_path[1:])
    ]
    body.append("## 学习顺序")
    body.extend(chain_sentences)
    body.append("")

    relations: list[dict] = []
    used_pairs: set[frozenset[str]] = set()
    for a, b in zip(learning_path, learning_path[1:]):
        used_pairs.add(frozenset((a, b)))
        relations.append(
            {
                "id": f"r{len(relations) + 1:03d}",
                "source": a,
                "target": b,
                "label": "前置",
                "type": "prereq",
                "evidence": chain_sentences[len(relations)],
            }
        )

    # curated semantic hints: skip (and report) anything that is not grounded,
    # not readable, or would duplicate an existing endpoint pair.
    hint_sentences: list[str] = []
    for src_tid, tgt_tid, rtype, label, sentence in _SEMANTIC_HINTS.get(domain_id, []):
        src, tgt = id_map.get(src_tid), id_map.get(tgt_tid)
        if not src or not tgt:
            _DROPPED_RELATIONS.append((domain_id, src_tid, tgt_tid, "概念 ID 不存在"))
            continue
        if frozenset((src, tgt)) in used_pairs:
            _DROPPED_RELATIONS.append(
                (domain_id, src_tid, tgt_tid, "与已有关系端点对重复")
            )
            continue
        if classify_relation(label, "") != rtype:
            _DROPPED_RELATIONS.append(
                (domain_id, src_tid, tgt_tid, f"标签「{label}」不表达 {rtype} 语义")
            )
            continue
        if concept_name[src] not in sentence or concept_name[tgt] not in sentence:
            _DROPPED_RELATIONS.append(
                (domain_id, src_tid, tgt_tid, "句子未逐字点名两端")
            )
            continue
        used_pairs.add(frozenset((src, tgt)))
        hint_sentences.append(sentence)
        relations.append(
            {
                "id": f"r{len(relations) + 1:03d}",
                "source": src,
                "target": tgt,
                "label": label,
                "type": rtype,
                "evidence": sentence,
            }
        )

    body.append("## 关系速览")
    body.extend(hint_sentences)
    body.append("")
    source_text = "\n".join(body)

    # Generation-time guards: a relation is only accepted when its evidence can
    # be copied back out of the source as one whole, unique line.
    source_lines = set(source_text.splitlines())
    seen_evidence: set[str] = set()
    for r in relations:
        ev = r["evidence"]
        if ev not in source_lines:
            raise ValueError(f"{domain_id}: 证据不是 source_text 的整行: {ev!r}")
        if ev in seen_evidence:
            raise ValueError(f"{domain_id}: 证据行重复: {ev!r}")
        seen_evidence.add(ev)
        if classify_relation(r["label"], "") != r["type"]:
            raise ValueError(
                f"{domain_id}: 标签 {r['label']!r} 不表达 {r['type']} 语义"
            )
    types = {r["type"] for r in relations}
    if "prereq" not in types:
        raise ValueError(f"{domain_id}: 缺少前置主线")
    if len(types) < 3:
        raise ValueError(f"{domain_id}: 语义覆盖不足: {sorted(types)}")

    return {
        "asset_id": asset_id,
        "type": "article",
        "title": title,
        "source_name": source_name,
        "created_at": DEMO_CREATED_AT,
        "source_text": source_text,
        "chapters": chapters,
        "concepts": concepts,
        "relations": relations,
        "learning_path": learning_path,
        "method": f"regen_all_domain_template_{domain_id}_v2",
        "source_length": len(source_text),
    }


def teacher_dict_for(asset_data: dict) -> dict:
    """Deterministic no-LLM teacher model for a demo asset.

    ``build_teacher_model`` stamps ``synthesized_at`` with the wall clock and
    mints uuid-based anomaly ids; both are normalized here so re-running
    ``regen_all.py`` produces byte-identical teacher files.
    """
    from expert_anything.core.models import KnowledgeAsset
    from expert_anything.core.teacher import build_teacher_model

    asset = KnowledgeAsset.from_dict(asset_data)
    model = build_teacher_model(asset, llm=None)
    data = model.to_dict()
    data["synthesized_at"] = DEMO_CREATED_AT
    for index, anomaly in enumerate(data.get("anomalies", [])):
        raw = "|".join(
            str(anomaly.get(key, ""))
            for key in ("kind", "concept_id", "description")
        )
        anomaly["id"] = "an" + hashlib.sha1(
            f"{index}|{raw}".encode("utf-8")
        ).hexdigest()[:8]
    return data


def learner_state_for(asset_datas: list[dict]) -> dict:
    """Cross-asset learner state built with the same code path the app uses."""
    from expert_anything.core import learner
    from expert_anything.core.models import KnowledgeAsset

    state: dict = {"profile": {}, "concepts": {}, "assets": {}, "history": []}
    for ad in asset_datas:
        learner.register_asset(state, KnowledgeAsset.from_dict(ad))
    return state


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    _DROPPED_RELATIONS.clear()
    assets = [
        build_asset_from_template(
            "electricity_trading",
            ELECTRICITY_ASSET_ID,
            "中国电力市场交易体系：从政策到实践的快速理解",
            "电力市场入门指南.md",
        ),
        build_asset_from_template(
            "carbon_trading",
            CARBON_ASSET_ID,
            "碳排放权交易体系：总量、市场与 MRV",
            "碳市场基础指南.md",
        ),
        # The renewable/DER domain packs (templates + decoders + prompt
        # suffixes) were registered without demo assets — unreachable code.
        # These two assets make the chain end-to-end runnable (detect →
        # template → curated scenes → terminology).
        build_asset_from_template(
            "renewable_forecasting",
            RENEWABLE_ASSET_ID,
            "新能源功率预测体系：风电光伏与数值天气的协同",
            "新能源预测入门指南.md",
        ),
        build_asset_from_template(
            "distributed_energy",
            DER_ASSET_ID,
            "分布式能源资源体系：微电网与虚拟电厂",
            "分布式能源入门指南.md",
        ),
    ]

    # The import-source sample is user-facing demo material for run_demo.py /
    # QUICKSTART. Keep an existing one untouched; synthesize it from the
    # electricity template only when missing so a fresh checkout still works.
    if not IMPORT_SAMPLE.exists():
        _write_json(IMPORT_SAMPLE, assets[0])
        import_sample_state = "synthesized from template"
    else:
        import_sample_state = f"kept (already exists: {IMPORT_SAMPLE.name})"

    from expert_anything.core.extraction import _stamp_locations
    from expert_anything.core.models import KnowledgeAsset

    for i, ad in enumerate(assets):
        # stamp locations before persisting so the demo assets carry their
        # own anchors (load-time backfill is the safety net, not the source)
        assets[i] = ad = _stamp_locations(KnowledgeAsset.from_dict(ad)).to_dict()
        aid = ad["asset_id"]
        _write_json(ASSETS_DIR / f"{aid}.json", ad)
        _write_json(ASSETS_DIR / f"teacher_{aid}.json", teacher_dict_for(ad))

    learner_json = learner_state_for(assets)
    _write_json(DEMO / "learner.json", learner_json)

    # summary
    print("== ExpertAnything demo data regenerated ==")
    for ad in assets:
        print(f"  asset {ad['asset_id']}: {ad['title']}")
        print(
            f"    concepts={len(ad['concepts'])} "
            f"relations={len(ad['relations'])} "
            f"path={len(ad['learning_path'])} chapters={len(ad['chapters'])}"
        )
        print(f"    semantics={sorted({r['type'] for r in ad['relations']})}")
    if _DROPPED_RELATIONS:
        print("  dropped relation hints:")
        for domain_id, src, tgt, why in _DROPPED_RELATIONS:
            print(f"    {domain_id}: {src}->{tgt} — {why}")
    else:
        print("  dropped relation hints: none")
    print(
        f"  learner: concepts={len(learner_json['concepts'])} "
        f"assets={sorted(learner_json['assets'])}"
    )
    print(f"  import sample: {import_sample_state}")
    print(f"  written under {DEMO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
