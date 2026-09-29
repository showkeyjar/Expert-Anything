"""JSON-file persistence for assets and the learner model.

No database yet: local-first, one file per asset under data/assets/,
plus a single learner.json for the (cross-asset) learner model.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from expert_anything.core import config
from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.teacher import TeacherModel


def _write_json_atomic(path: Path, data: Any) -> None:
    """Persist JSON without exposing readers to a partially written file.

    The learner history is the learning loop's source of truth.  A crash while
    replacing it must leave either the previous complete document or the new
    complete document, never a truncated one.  The temporary file lives in the
    same directory so ``os.replace`` stays atomic on supported local filesystems.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def save_asset(asset: KnowledgeAsset) -> None:
    config.ensure_dirs()
    path = config.ASSETS_DIR / f"{asset.asset_id}.json"
    _write_json_atomic(path, asset.to_dict())


def _ensure_locations(asset: KnowledgeAsset) -> KnowledgeAsset:
    """Backfill source anchors for assets persisted before evidence-location
    stamping existed (or written by older regen tools). Conservative: assets
    that already carry any location are left untouched — PDF page numbers
    are not recoverable from a re-stamp without page offsets.
    """
    if asset.concepts and not any(c.locations for c in asset.concepts):
        from expert_anything.core.extraction import _stamp_locations

        _stamp_locations(asset)
    return asset


def load_assets() -> list[KnowledgeAsset]:
    if not config.ASSETS_DIR.exists():
        return []
    assets: list[KnowledgeAsset] = []
    for file in sorted(
        config.ASSETS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        if file.name.startswith("teacher_"):
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            assets.append(_ensure_locations(KnowledgeAsset.from_dict(data)))
        except Exception:  # corrupt file resilience — stay audible, not fatal
            logging.getLogger("expert_anything.storage").warning(
                "skipping unreadable asset file: %s", file.name
            )
            continue
    return assets


def load_asset(asset_id: str) -> KnowledgeAsset | None:
    """Single-file read (was: full load_assets() + linear filter)."""
    if not asset_id:
        return None
    path = config.ASSETS_DIR / f"{asset_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _ensure_locations(KnowledgeAsset.from_dict(data))
    except Exception:
        logging.getLogger("expert_anything.storage").warning(
            "asset file unreadable: %s", path.name
        )
        return None


def delete_asset(asset_id: str) -> None:
    path = config.ASSETS_DIR / f"{asset_id}.json"
    path.unlink(missing_ok=True)
    teacher_path = config.ASSETS_DIR / f"teacher_{asset_id}.json"
    teacher_path.unlink(missing_ok=True)


def save_learner(state: dict) -> None:
    config.ensure_dirs()
    _write_json_atomic(config.LEARNER_FILE, state)


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
    _write_json_atomic(path, model.to_dict())


def load_teacher(asset_id: str) -> TeacherModel | None:
    path = config.ASSETS_DIR / f"teacher_{asset_id}.json"
    if not path.exists():
        return None
    try:
        return TeacherModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # pragma: no cover
        return None
