"""JSON-file persistence for assets and the learner model.

No database yet: local-first, one file per asset under data/assets/,
plus a single learner.json for the (cross-asset) learner model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from expert_anything.core import config
from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.teacher import TeacherModel


def save_asset(asset: KnowledgeAsset) -> None:
    config.ensure_dirs()
    path = config.ASSETS_DIR / f"{asset.asset_id}.json"
    path.write_text(
        json.dumps(asset.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_assets() -> list[KnowledgeAsset]:
    if not config.ASSETS_DIR.exists():
        return []
    assets: list[KnowledgeAsset] = []
    for file in sorted(
        config.ASSETS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            assets.append(KnowledgeAsset.from_dict(data))
        except Exception:  # pragma: no cover - corrupt file resilience
            continue
    return assets


def load_asset(asset_id: str) -> KnowledgeAsset | None:
    return next((a for a in load_assets() if a.asset_id == asset_id), None)


def delete_asset(asset_id: str) -> None:
    path = config.ASSETS_DIR / f"{asset_id}.json"
    path.unlink(missing_ok=True)
    teacher_path = config.ASSETS_DIR / f"teacher_{asset_id}.json"
    teacher_path.unlink(missing_ok=True)


def save_learner(state: dict) -> None:
    config.ensure_dirs()
    config.LEARNER_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_learner() -> dict:
    if config.LEARNER_FILE.exists():
        try:
            return json.loads(config.LEARNER_FILE.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover
            pass
    return {"profile": {}, "concepts": {}, "assets": {}, "history": []}


def save_teacher(asset_id: str, model: TeacherModel) -> None:
    config.ensure_dirs()
    path = config.ASSETS_DIR / f"teacher_{asset_id}.json"
    path.write_text(
        json.dumps(model.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_teacher(asset_id: str) -> TeacherModel | None:
    path = config.ASSETS_DIR / f"teacher_{asset_id}.json"
    if not path.exists():
        return None
    try:
        return TeacherModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # pragma: no cover
        return None


def _coerce(value: Any) -> Any:
    # dataclasses.asdict can leave non-serialisable objects; we only store dicts.
    return value
