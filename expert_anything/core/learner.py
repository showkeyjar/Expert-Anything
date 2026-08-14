"""Learner Model: structured, cross-asset, persisted to learner.json.

Unlike the legacy MVP (a single mastery float per concept), this tracks:
- per-concept mastery keyed by *normalized name* so the same concept learned
  across different assets accumulates into one global memory;
- which assets introduced each concept;
- a per-asset learning path + progress cursor;
- a history of evaluated attempts (with the tutor's feedback).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from expert_anything.core import config, storage
from expert_anything.core.models import KnowledgeAsset

MASTERY_ALPHA = 0.4  # weight given to the newest evaluation


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).lower().strip()
    name = re.sub(r"[\s\-_/]+", " ", name)
    name = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    return name.strip()


def load() -> dict:
    return storage.load_learner()


def save(state: dict) -> None:
    storage.save_learner(state)


def set_profile(state: dict, goal: str, baseline: str, style: str) -> None:
    state.setdefault("profile", {})
    state["profile"].update(
        {"goal": goal, "baseline": baseline, "style": style}
    )


def register_asset(state: dict, asset: KnowledgeAsset) -> None:
    state.setdefault("assets", {})
    state.setdefault("concepts", {})
    entry = state["assets"].setdefault(
        asset.asset_id,
        {"title": asset.title, "path": list(asset.learning_path), "current_index": 0, "completed": []},
    )
    entry["title"] = asset.title
    if not entry["path"]:
        entry["path"] = list(asset.learning_path)
    # register each concept into the global memory
    for c in asset.concepts:
        key = normalize(c.name)
        if key not in state["concepts"]:
            state["concepts"][key] = {
                "name": c.name,
                "mastery": 0.0,
                "sources": [],
                "last_feedback": "",
                "updated_at": "",
            }
        if asset.asset_id not in state["concepts"][key]["sources"]:
            state["concepts"][key]["sources"].append(asset.asset_id)


def unregister_asset(state: dict, asset_id: str) -> None:
    """Remove every trace of an asset from the learner model.

    - drop the asset's learning-path entry;
    - remove this asset from each concept's source list, and purge concepts
      that no longer have any source (otherwise they'd dangle);
    - drop history rows belonging to this asset.
    """
    assets = state.get("assets")
    if assets and asset_id in assets:
        del assets[asset_id]

    concepts = state.get("concepts")
    if concepts:
        for key in list(concepts.keys()):
            rec = concepts[key]
            sources = rec.get("sources") or []
            if asset_id in sources:
                sources.remove(asset_id)
                rec["sources"] = sources
            if not sources:
                del concepts[key]

    history = state.get("history")
    if history:
        state["history"] = [h for h in history if h.get("asset_id") != asset_id]


def record_evaluation(
    state: dict,
    concept_name: str,
    asset_id: str,
    score: float,
    answer: str,
    feedback: str,
) -> float:
    key = normalize(concept_name)
    state.setdefault("concepts", {})
    rec = state["concepts"].setdefault(
        key,
        {
            "name": concept_name,
            "mastery": 0.0,
            "sources": [asset_id],
            "last_feedback": "",
            "updated_at": "",
        },
    )
    if asset_id not in rec["sources"]:
        rec["sources"].append(asset_id)
    old = float(rec.get("mastery", 0.0))
    new = round(old * (1 - MASTERY_ALPHA) + max(0.0, min(1.0, score)) * MASTERY_ALPHA, 2)
    rec["mastery"] = new
    rec["last_feedback"] = feedback
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()

    state.setdefault("history", [])
    state["history"].insert(
        0,
        {
            "concept": concept_name,
            "key": key,
            "asset_id": asset_id,
            "score": round(max(0.0, min(1.0, score)), 2),
            "answer": answer,
            "feedback": feedback,
            "at": rec["updated_at"],
        },
    )
    state["history"] = state["history"][:50]
    return new


def mark_completed(state: dict, asset_id: str, concept_id: str) -> None:
    entry = state.get("assets", {}).get(asset_id)
    if not entry:
        return
    if concept_id not in entry["completed"]:
        entry["completed"].append(concept_id)
    path = entry["path"]
    if concept_id in path:
        entry["current_index"] = min(len(path), path.index(concept_id) + 1)


def next_concept_id(state: dict, asset: KnowledgeAsset, path: list[str] | None = None) -> str | None:
    entry = state.get("assets", {}).get(asset.asset_id)
    if path is None:
        path = entry["path"] if entry else [c.id for c in asset.concepts]
    completed = set(entry.get("completed", [])) if entry else set()
    for cid in path:
        if cid not in completed and asset.concept_by_id(cid):
            return cid
    return None


def adaptive_path(asset: KnowledgeAsset, learner_state: dict, anomaly_ids: set | None = None,
                  path: list[str] | None = None, limit: int = 8) -> list[dict]:
    """Build an adaptive, ranked study queue for the learner.

    Returns a list ordered by priority (most urgent first). Each item is a dict:
        cid, name, mastery, score, downstream, completed, tags
    `tags` are reason codes the UI turns into chips: "anom", "weak",
    "foundation", "unblock:<n>", "ready", "blocked", "path".

    The score blends four signals so the queue reflects *real* adaptive
    behaviour instead of one hard-coded rule:
      * mastery deficit  (lower mastery -> higher priority);
      * anomaly link     (walk ahead of the student to resolve open anomalies);
      * foundational leverage (being a prerequisite for many downstream concepts);
      * declared-path position (earlier concepts get a mild boost).
    Readiness is reported via "ready"/"blocked" tags rather than silently
    reordering, so the learner sees *why* a concept is queued.
    """
    anomaly_ids = set(anomaly_ids or set())
    W = config.WEAKNESS_THRESHOLD
    entry = learner_state.get("assets", {}).get(asset.asset_id)
    completed = set(entry.get("completed", [])) if entry else set()
    by_norm = {
        normalize(k): float(r.get("mastery", 0.0))
        for k, r in learner_state.get("concepts", {}).items()
    }
    mm: dict[str, float] = {}
    for c in asset.concepts:
        nk = normalize(c.name)
        if nk in by_norm:
            mm[c.id] = by_norm[nk]
    if path is None:
        path = (entry.get("path") if entry else None) or list(asset.learning_path) or [c.id for c in asset.concepts]

    # prerequisite graph: source -> target means target depends on source
    incoming: dict[str, set] = {c.id: set() for c in asset.concepts}
    outgoing: dict[str, set] = {c.id: set() for c in asset.concepts}
    for r in asset.relations or []:
        s = getattr(r, "source", None) or (r.get("source") if isinstance(r, dict) else None)
        tg = getattr(r, "target", None) or (r.get("target") if isinstance(r, dict) else None)
        if s in incoming and tg in incoming and s != tg:
            incoming[tg].add(s)
            outgoing[s].add(tg)

    # transitive downstream width (how many concepts a mastered concept unblocks)
    downstream: dict[str, int] = {}
    for c in asset.concepts:
        seen: set = set()
        stack = list(outgoing[c.id])
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(outgoing.get(x, ()))
        downstream[c.id] = len(seen)

    pos = {cid: i for i, cid in enumerate(dict.fromkeys(path))}

    items: list[dict] = []
    for c in asset.concepts:
        cid = c.id
        m = mm.get(cid, 0.0)
        if m >= W and cid not in anomaly_ids:
            continue  # already mastered and not anomaly-linked -> skip
        tags: list[str] = []
        score = 0.0
        deficit = max(0.0, (W - m)) / W if W > 0 else 0.0
        if deficit > 0:
            score += deficit
            tags.append("weak")
        if cid in anomaly_ids:
            score += 0.35
            tags.append("anom")
        if incoming[cid] and not outgoing[cid]:
            score += 0.08
            tags.append("foundation")
        dw = downstream.get(cid, 0)
        if dw > 0:
            score += min(0.2, 0.025 * dw)
            tags.append(f"unblock:{dw}")
        if cid in pos:
            score += max(0.0, 0.05 * (1 - pos[cid] / max(1, len(pos))))
            tags.append("path")
        if incoming[cid]:
            pm = [mm.get(p, 0.0) for p in incoming[cid]]
            if pm and all(p >= W for p in pm):
                score += 0.05
                tags.append("ready")
            else:
                tags.append("blocked")
        items.append({
            "cid": cid, "name": c.name, "mastery": m,
            "score": round(score, 3), "downstream": dw,
            "completed": cid in completed, "tags": tags,
        })
    items.sort(key=lambda x: (-x["score"], x["name"]))
    return items[:limit]


def weaknesses(state: dict, limit: int = 8) -> list[dict]:
    out = []
    for key, rec in state.get("concepts", {}).items():
        if float(rec.get("mastery", 0.0)) < config.WEAKNESS_THRESHOLD:
            out.append({"key": key, "name": rec.get("name", key), "mastery": rec.get("mastery", 0.0)})
    out.sort(key=lambda x: x["mastery"])
    return out[:limit]
