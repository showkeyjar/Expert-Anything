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
    * No network, no API key, no GUI, no mutation of real user data under
      data/assets (only data/_demo is written).
    * Idempotent: safe to re-run; existing files under data/_demo/assets are
      regenerated deterministically. The optional import-source sample
      data/_demo/electricity_trading_asset.json is *kept* if it already
      exists (it is user-facing demo material referenced by run_demo.py /
      QUICKSTART) and only synthesized from the template when missing.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DEMO = ROOT / "data" / "_demo"
ASSETS_DIR = DEMO / "assets"
IMPORT_SAMPLE = DEMO / "electricity_trading_asset.json"

# asset ids double as file stems, so learner.assets keys always match
# data/_demo/assets/<stem>.json (see tests/test_demo_data.py).
ELECTRICITY_ASSET_ID = "a20260908-002"
CARBON_ASSET_ID = "a20260908-003"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_asset_from_template(
    domain_id: str, asset_id: str, title: str, source_name: str
) -> dict:
    """Assemble one demo asset (plain dict, asset-ID space ``c*``) from a
    domain template. Relations come from the template quick_path chain
    (learning order); labels use the deterministic 'prereq' semantics."""
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
                    "evidence": c.get("evidence", []),
                    "chapter": ch.get("title", ""),
                    "locations": [],
                }
            )

    # learning path = quick_path mapped into the asset ID space
    learning_path = [id_map[tid] for tid in template.quick_path if tid in id_map]
    # relations: consecutive quick_path items form a 'prereq' chain
    relations: list[dict] = []
    for i in range(len(learning_path) - 1):
        relations.append(
            {
                "id": f"r{len(relations) + 1:03d}",
                "source": learning_path[i],
                "target": learning_path[i + 1],
                "label": "前置",
                "type": "prereq",
                "evidence": "模板推荐学习路径中相邻概念（演示数据，由 regen_all.py 确定性生成）",
            }
        )

    # a short readable source body derived from the template (demo only)
    body = [f"# {template.name}", ""]
    for ch in template.chapters:
        body.append(f"## {ch.get('title', '')}")
        for c in ch.get("concepts", []):
            body.append(f"- {c['name']}：{c.get('definition', '')}")
        body.append("")
    source_text = "\n".join(body)

    return {
        "asset_id": asset_id,
        "type": "article",
        "title": title,
        "source_name": source_name,
        "created_at": _now(),
        "source_text": source_text,
        "chapters": chapters,
        "concepts": concepts,
        "relations": relations,
        "learning_path": learning_path,
        "method": f"regen_all_domain_template_{domain_id}_v1",
        "source_length": len(source_text),
    }


def teacher_dict_for(asset_data: dict) -> dict:
    """Deterministic no-LLM teacher model for a demo asset."""
    from expert_anything.core.models import KnowledgeAsset
    from expert_anything.core.teacher import build_teacher_model

    asset = KnowledgeAsset.from_dict(asset_data)
    model = build_teacher_model(asset, llm=None)
    return model.to_dict()


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
    ]

    # The import-source sample is user-facing demo material for run_demo.py /
    # QUICKSTART. Keep an existing one untouched; synthesize it from the
    # electricity template only when missing so a fresh checkout still works.
    if not IMPORT_SAMPLE.exists():
        _write_json(IMPORT_SAMPLE, assets[0])
        import_sample_state = "synthesized from template"
    else:
        import_sample_state = f"kept (already exists: {IMPORT_SAMPLE.name})"

    for ad in assets:
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
    print(
        f"  learner: concepts={len(learner_json['concepts'])} "
        f"assets={sorted(learner_json['assets'])}"
    )
    print(f"  import sample: {import_sample_state}")
    print(f"  written under {DEMO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
