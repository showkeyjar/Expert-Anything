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
from expert_anything.core.i18n import t

MASTERY_ALPHA = 0.4  # weight given to the newest evaluation

# Active-recall (Feynman self-explanation) evidence.  A recall score measures
# how completely the learner *explained* a concept — it is first-hand mastery
# evidence, but it is NOT evidence that a teaching strategy worked.  Teaching-
# side aggregators (stuck / regression / mastery prediction / style credit)
# skip it exactly like ``meta.review``; mastery, difficulty and the error book
# keep it (learner-view totality semantics).
RECALL_CHANNEL = "recall"


def is_recall_record(row: dict) -> bool:
    """True for Feynman self-explanation records (``meta.channel == recall``)."""
    return (row.get("meta") or {}).get("channel") == RECALL_CHANNEL

# History retention (AGENTS.md #12: the learning trace is the single source of
# truth for stuck/regression/session-report detection). A flat 50-row cap
# silently starved those detectors once a book covered >50 evaluations, so
# retention is per-concept with a global budget instead.
HISTORY_GLOBAL_CAP = 500
HISTORY_PER_CONCEPT_CAP = 20
HISTORY_PER_CONCEPT_FLOOR = 8


def trim_history(rows: list) -> list:
    """Bound the newest-first history while protecting observation windows.

    Order is preserved (newest first — stuck/regression detection and the
    session reports rely on it). Two passes:
    1. per-concept cap: no concept may occupy more than CAP rows;
    2. global cap: drop the *oldest* droppable rows (those beyond a concept's
       FLOOR newest) until the total fits; a concept always keeps its FLOOR
       most recent rows, so "went from good to bad" stays observable.
    """
    kept: list = []
    counts: dict = {}
    for row in rows:
        k = str(row.get("key") or row.get("concept") or "")
        if counts.get(k, 0) >= HISTORY_PER_CONCEPT_CAP:
            continue
        counts[k] = counts.get(k, 0) + 1
        kept.append(row)
    if len(kept) <= HISTORY_GLOBAL_CAP:
        return kept
    seen: dict = {}
    droppable = set()
    for i, row in enumerate(kept):
        k = str(row.get("key") or row.get("concept") or "")
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > HISTORY_PER_CONCEPT_FLOOR:
            droppable.add(i)
    excess = len(kept) - HISTORY_GLOBAL_CAP
    out = kept[:]
    for i in sorted(droppable, reverse=True):  # oldest first
        if excess <= 0:
            break
        out[i] = None
        excess -= 1
    out = [r for r in out if r is not None]
    # Hard bound: pathological breadth (hundreds of concepts, each ≤ FLOOR
    # rows) leaves nothing droppable. Single-row concepts can't feed the
    # stuck/regression detectors anyway, so drop oldest rows outright.
    if len(out) > HISTORY_GLOBAL_CAP:
        out = out[:HISTORY_GLOBAL_CAP]
    return out


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
    state["profile"].update({"goal": goal, "baseline": baseline, "style": style})


def set_study_goal(state: dict, target_concepts: int, days: int = 7) -> dict:
    """Set a study goal: master N concepts within D days.

    Returns the goal dict that was stored. Also tracks start state
    (how many were already mastered at goal creation time) so progress
    can be measured against the delta, not the absolute count.
    """
    # Count currently mastered concepts
    mastered_now = sum(
        1
        for rec in state.get("concepts", {}).values()
        if float(rec.get("mastery", 0.0)) >= 0.6
    )
    goal = {
        "target": target_concepts,
        "days": days,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_mastered": mastered_now,
    }
    state["study_goal"] = goal
    save(state)
    return goal


def study_goal_progress(state: dict) -> dict:
    """Check progress toward the study goal.

    Returns:
        target: number of concepts to master
        baseline: mastered count at goal creation
        current: mastered count now
        delta: concepts mastered since goal creation
        progress: delta / target (0-1+)
        days_left: days remaining
        on_track: whether current pace meets the target
        expired: whether the deadline has passed
    """
    goal = state.get("study_goal")
    if not goal:
        return {"active": False}

    from datetime import datetime, timezone

    try:
        created = datetime.fromisoformat(goal["created_at"])
    except (TypeError, ValueError):
        created = datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    days_elapsed = max(0.0, (now - created).total_seconds() / 86400)
    days_total = goal.get("days", 7)
    days_left = max(0, days_total - days_elapsed)

    current_mastered = sum(
        1
        for rec in state.get("concepts", {}).values()
        if float(rec.get("mastery", 0.0)) >= 0.6
    )
    baseline = goal.get("baseline_mastered", 0)
    delta = max(0, current_mastered - baseline)
    target = goal.get("target", 1)
    progress = delta / target if target > 0 else 0.0

    # On track: if pace (delta / days_elapsed) >= needed pace (remaining / days_left)
    remaining = max(0, target - delta)
    if days_left > 0 and days_elapsed > 0:
        current_pace = delta / days_elapsed
        needed_pace = remaining / days_left
        on_track = current_pace >= needed_pace
    elif delta >= target:
        on_track = True
    else:
        on_track = False

    expired = days_left <= 0 and delta < target
    completed = delta >= target

    return {
        "active": True,
        "target": target,
        "baseline": baseline,
        "current": current_mastered,
        "delta": delta,
        "progress": round(progress, 2),
        "days_left": round(days_left, 1),
        "days_elapsed": round(days_elapsed, 1),
        "on_track": on_track,
        "expired": expired,
        "completed": completed,
    }


def register_asset(state: dict, asset: KnowledgeAsset) -> None:
    state.setdefault("assets", {})
    state.setdefault("concepts", {})
    entry = state["assets"].setdefault(
        asset.asset_id,
        {
            "title": asset.title,
            "path": list(asset.learning_path),
            "current_index": 0,
            "completed": [],
        },
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
    meta: dict | None = None,
) -> float:
    """Record one evaluated attempt.

    ``meta`` (optional) carries the *learning trace* — which teaching
    strategy produced this attempt (style / vary), via which channel
    (answer / quiz / practice) and whether the generated artifact passed
    the admission checks. Borrowed from OmniScientist's "execution record
    as the source of truth": later audits (stuck detection, reports, the
    teacher model) read this record instead of trusting narrative text.
    """
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
    new = round(
        old * (1 - MASTERY_ALPHA) + max(0.0, min(1.0, score)) * MASTERY_ALPHA, 2
    )
    rec["mastery"] = new
    rec["last_feedback"] = feedback
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()

    state.setdefault("history", [])
    row = {
        "concept": concept_name,
        "key": key,
        "asset_id": asset_id,
        "score": round(max(0.0, min(1.0, score)), 2),
        "answer": answer,
        "feedback": feedback,
        "at": rec["updated_at"],
    }
    if meta:
        row["meta"] = {str(k): v for k, v in meta.items()}
    state["history"].insert(0, row)
    state["history"] = trim_history(state["history"])
    return new


def save_reading_position(state: dict, asset_id: str, position: int) -> None:
    """Persist the source reader's scroll offset for one asset.

    Lets the reader resume exactly where they stopped — losing the reading
    position every time they jump to a lesson and come back breaks flow.
    """
    if not asset_id:
        return
    state.setdefault("reading_positions", {})[asset_id] = max(0, int(position))


def load_reading_position(state: dict, asset_id: str) -> int | None:
    """Return the saved source scroll offset for an asset, if any."""
    pos = state.get("reading_positions", {}).get(asset_id)
    if isinstance(pos, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(pos, (int, float)) and pos > 0:
        return int(pos)
    return None


RECENT_TAUGHT_CAP = 8


def record_taught_concept(state: dict, concept_name: str) -> None:
    """Push a concept onto the MRU list of lessons started.

    Captures teaching *intent* even when no evaluation follows (a lesson the
    learner read but did not answer), which the evaluation history misses —
    powers the one-tap re-teach bar in the teach view.
    """
    if not concept_name:
        return
    recent = [c for c in state.get("recent_taught", []) if c != concept_name]
    recent.insert(0, concept_name)
    state["recent_taught"] = recent[:RECENT_TAUGHT_CAP]


def recent_taught_concepts(state: dict, limit: int = 5) -> list[str]:
    """Most-recently-taught concept names, newest first."""
    return [c for c in state.get("recent_taught", []) if c][:limit]


def toggle_favorite(state: dict, concept_name: str) -> bool:
    """Toggle a concept bookmark; returns the new state (True = now favorite).

    Keyed by normalized concept *name* (same convention as
    ``record_taught_concept``) so a favorite survives asset reloads and follows
    the same-named concept across assets — the learner bookmarks the idea,
    not one asset's row id.
    """
    if not concept_name:
        return False
    key = normalize(concept_name)
    favs = state.setdefault("favorites", [])
    if key in favs:
        favs.remove(key)
        return False
    favs.append(key)
    return True


def is_favorite(state: dict, concept_name: str) -> bool:
    """Whether the concept (by name) is bookmarked."""
    if not concept_name:
        return False
    return normalize(concept_name) in state.get("favorites", [])


def favorite_set(state: dict) -> set[str]:
    """All bookmarked normalized concept names."""
    return set(state.get("favorites", []))


# ---- personal notes (generation effect: writing beats reading) ---------------

NOTE_CAP = 2000


def set_note(state: dict, concept_name: str, text: str) -> bool:
    """Write the learner's own-words note for a concept; returns True when a
    note exists after the call (empty text deletes the note).

    Keyed by normalized concept *name* — same convention as favorites — so a
    note follows the idea across assets and survives asset reloads. Writing
    an explanation in your own words is the strongest cheap comprehension
    check the system can offer, so notes live in the learner state (the one
    source of truth) rather than in any asset file.
    """
    if not concept_name:
        return False
    key = normalize(concept_name)
    notes = state.setdefault("notes", {})
    text = (text or "").strip()
    if text:
        notes[key] = text[:NOTE_CAP]
        return True
    notes.pop(key, None)
    return False


def get_note(state: dict, concept_name: str) -> str:
    """The learner's note for a concept, or "" when absent."""
    if not concept_name:
        return ""
    val = state.get("notes", {}).get(normalize(concept_name), "")
    return val if isinstance(val, str) else ""


def has_note(state: dict, concept_name: str) -> bool:
    return bool(get_note(state, concept_name))


def note_set(state: dict) -> set[str]:
    """All normalized concept names carrying a non-empty note."""
    return {k for k, v in state.get("notes", {}).items() if isinstance(v, str) and v}


# ---- lesson snapshots (re-read a past explanation at zero LLM cost) ----------

LESSON_SNAPSHOT_CAP = 4000
LESSON_STEP_CAP = 500
LESSON_STEPS_MAX = 8


def save_lesson_snapshot(
    state: dict,
    concept_name: str,
    asset_id: str,
    style: str,
    explanation: str,
    steps: list | None,
) -> bool:
    """Persist the *latest* lesson content for a concept (bounded).

    Review wants "show me that explanation again", not "generate a fresh
    one" — the snapshot closes that loop without another LLM call. Only the
    most recent lesson per concept is kept; lengths are clamped so the
    learner state file stays small.
    """
    explanation = (explanation or "").strip()
    if not concept_name or not explanation:
        return False
    snap = {
        "name": concept_name,
        "asset_id": asset_id or "",
        "style": style or "",
        "explanation": explanation[:LESSON_SNAPSHOT_CAP],
        "steps": [str(s)[:LESSON_STEP_CAP] for s in (steps or []) if str(s).strip()][
            :LESSON_STEPS_MAX
        ],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    state.setdefault("lesson_snapshots", {})[normalize(concept_name)] = snap
    return True


def get_lesson_snapshot(state: dict, concept_name: str) -> dict | None:
    """The latest saved lesson snapshot for a concept, or None."""
    if not concept_name:
        return None
    snap = state.get("lesson_snapshots", {}).get(normalize(concept_name))
    if isinstance(snap, dict) and snap.get("explanation"):
        return snap
    return None


def score_trail(state: dict, concept_name: str, limit: int = 5) -> list[dict]:
    """Chronological recent evaluation scores for one concept.

    Each item: ``{"score": float, "review": bool, "recall": bool}``. Returns []
    when fewer than two records exist — a single point is not a trend, and the
    detail card should stay silent rather than render noise.
    """
    if not concept_name:
        return []
    key = normalize(concept_name)
    rows = [h for h in state.get("history", []) if h.get("key") == key]
    out = [
        {
            "score": float(h.get("score", 0.0)),
            "review": bool((h.get("meta") or {}).get("review")),
            "recall": (h.get("meta") or {}).get("channel") == RECALL_CHANNEL,
        }
        for h in reversed(rows[: max(1, limit)])
    ]
    return out if len(out) >= 2 else []


# Canonical channel order for the mastery breakdown ("where did this % come
# from?").  Unknown channels keep their raw name and sink to the end.
CHANNEL_ORDER = ("answer", "quiz", "practice", "flashcard", "recall", "harness")


def mastery_breakdown(state: dict, concept_name: str) -> list[dict]:
    """Per-channel breakdown of how a concept's mastery was earned.

    Projects the history trace (``meta.channel``) into
    ``[{channel, count, avg, last_score}]`` ordered by :data:`CHANNEL_ORDER`.
    Legacy rows without ``meta`` count as ``"answer"`` (the teaching loop).
    Pure function, no LLM — it answers the learner's "why is my mastery 62%?".
    """
    if not concept_name:
        return []
    key = normalize(concept_name)
    buckets: dict[str, dict] = {}
    for h in state.get("history", []):  # newest first
        if (h.get("key") or normalize(h.get("concept", ""))) != key:
            continue
        meta = h.get("meta") or {}
        channel = str(meta.get("channel") or "answer")
        rec = buckets.setdefault(
            channel, {"channel": channel, "scores": [], "last_score": None}
        )
        try:
            score = float(h.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        rec["scores"].append(score)
        if rec["last_score"] is None:
            rec["last_score"] = round(score, 2)  # newest row seen first
    out = []
    for channel, rec in buckets.items():
        scores = rec["scores"]
        out.append(
            {
                "channel": channel,
                "count": len(scores),
                "avg": round(sum(scores) / len(scores), 2) if scores else 0.0,
                "last_score": rec["last_score"] or 0.0,
            }
        )

    def _rank(item: dict) -> tuple[int, str]:
        channel = item["channel"]
        idx = CHANNEL_ORDER.index(channel) if channel in CHANNEL_ORDER else -1
        return (idx if idx >= 0 else len(CHANNEL_ORDER), channel)

    out.sort(key=_rank)
    return out


def recall_trend(state: dict, concept_name: str, limit: int = 5) -> list[float]:
    """Coverage of the most recent self-explanations, oldest → newest.

    The direct "did I actually get better at explaining it?" signal.  Pure
    projection of ``channel="recall"`` rows; returns [] when the learner has
    never done a Feynman check on this concept.
    """
    if not concept_name:
        return []
    key = normalize(concept_name)
    rows = [
        h
        for h in state.get("history", [])
        if (h.get("meta") or {}).get("channel") == RECALL_CHANNEL
        and (h.get("key") or normalize(h.get("concept", ""))) == key
    ][: max(1, limit)]
    try:
        return [round(float(h.get("score", 0.0)), 2) for h in reversed(rows)]
    except (TypeError, ValueError):
        return []


def learning_streak(state: dict) -> dict:
    """Calculate the current and best learning streak (consecutive days).

    A "day" counts if there is at least one evaluation in the learner's
    history with a timestamp on that calendar day (UTC). The streak
    extends backwards from today: if today has no activity yet but
    yesterday did, the streak is still alive (today just hasn't started).

    Returns:
        current: consecutive days ending today or yesterday
        best: longest streak ever achieved
        total_days: total distinct days with activity
        last_active: ISO date string of the most recent active day
    """
    from datetime import date as _date

    history = state.get("history", [])
    if not history:
        return {"current": 0, "best": 0, "total_days": 0, "last_active": ""}

    active_days: set[_date] = set()
    for h in history:
        ts_str = h.get("at", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            active_days.add(ts.date())
        except (TypeError, ValueError):
            continue

    if not active_days:
        return {"current": 0, "best": 0, "total_days": 0, "last_active": ""}

    sorted_days = sorted(active_days, reverse=True)
    today = datetime.now(timezone.utc).date()
    yesterday = today.fromordinal(today.toordinal() - 1)

    # Current streak: count back from today (or yesterday if today is empty)
    current = 0
    cursor = today if today in active_days else (yesterday if yesterday in active_days else None)
    if cursor is not None:
        current = 1
        check = cursor.fromordinal(cursor.toordinal() - 1)
        while check in active_days:
            current += 1
            check = check.fromordinal(check.toordinal() - 1)

    # Best streak: iterate sorted days and find longest consecutive run
    best = 1
    run = 1
    for i in range(1, len(sorted_days)):
        prev = sorted_days[i]
        before = sorted_days[i - 1]
        if (before - prev).days == 1:
            run += 1
            best = max(best, run)
        else:
            run = 1

    return {
        "current": current,
        "best": max(best, current),
        "total_days": len(active_days),
        "last_active": sorted_days[0].isoformat(),
    }


def mark_completed(state: dict, asset_id: str, concept_id: str) -> None:
    entry = state.get("assets", {}).get(asset_id)
    if not entry:
        return
    if concept_id not in entry["completed"]:
        entry["completed"].append(concept_id)
    path = entry["path"]
    if concept_id in path:
        entry["current_index"] = min(len(path), path.index(concept_id) + 1)


def next_concept_id(
    state: dict, asset: KnowledgeAsset, path: list[str] | None = None
) -> str | None:
    entry = state.get("assets", {}).get(asset.asset_id)
    if path is None:
        path = entry["path"] if entry else [c.id for c in asset.concepts]
    completed = set(entry.get("completed", [])) if entry else set()
    for cid in path:
        if cid not in completed and asset.concept_by_id(cid):
            return cid
    return None


def weak_history(
    state: dict, asset_id: str | None = None, threshold: float = 0.5
) -> list[dict]:
    """Collect low-score evaluation records as an "error book".

    Returns history entries where score < threshold, newest-first.
    Groups by concept name — each concept's most recent weak attempt is kept
    so the learner sees the freshest failure, not an old one that's since
    been mastered.

    If asset_id is given, only returns entries for that asset.
    """
    seen_concepts: set[str] = set()
    out: list[dict] = []
    for h in state.get("history", []):
        if asset_id and h.get("asset_id") != asset_id:
            continue
        score = float(h.get("score", 1.0))
        if score >= threshold:
            continue
        concept = h.get("concept", "")
        if concept in seen_concepts:
            continue
        seen_concepts.add(concept)
        out.append(h)
    return out


def concept_difficulty(state: dict, asset_id: str | None = None) -> dict[str, str]:
    """Auto-label each concept's difficulty based on evaluation history.

    Returns a mapping ``concept_name -> "easy" | "medium" | "hard"``.

    Difficulty is derived from the learner's pass rate per concept:
      - >= 0.8  -> easy  (learner consistently scores high)
      - >= 0.5  -> medium
      - <  0.5  -> hard  (learner keeps failing this concept)

    Concepts with no evaluation history are labelled "unknown".
    If asset_id is given, only counts evaluations for that asset.
    """
    # Group scores by concept name
    scores: dict[str, list[float]] = {}
    for h in state.get("history", []):
        if asset_id and h.get("asset_id") != asset_id:
            continue
        name = h.get("concept", "")
        if not name:
            continue
        scores.setdefault(name, []).append(float(h.get("score", 0.0)))

    out: dict[str, str] = {}
    for name, scs in scores.items():
        if not scs:
            out[name] = "unknown"
            continue
        pass_rate = sum(1 for s in scs if s >= 0.6) / len(scs)
        if pass_rate >= 0.8:
            out[name] = "easy"
        elif pass_rate >= 0.5:
            out[name] = "medium"
        else:
            out[name] = "hard"
    return out


def structural_complexity(asset: KnowledgeAsset) -> dict[str, float]:
    """Compute structural complexity per concept based on graph centrality.

    A concept is structurally complex when many other concepts depend on it
    (high in-degree in prereq/causes relations) and/or it has many connections
    overall (high degree centrality). This is independent of the learner's
    evaluation history — it measures inherent knowledge structure difficulty.

    Returns ``{concept_id: 0.0–1.0}`` where 1.0 = maximally connected hub.
    """
    from expert_anything.core.decoder import classify_relation

    degree: dict[str, int] = {c.id: 0 for c in asset.concepts}
    in_degree: dict[str, int] = {c.id: 0 for c in asset.concepts}

    for r in asset.relations:
        if r.source in degree:
            degree[r.source] += 1
        if r.target in degree:
            degree[r.target] += 1
        # In-degree: how many concepts point TO this one (depend on it)
        sem = classify_relation(r.label or "", r.type or "")
        if sem in ("prereq", "causes", "part_of") and r.target in in_degree:
            in_degree[r.target] += 1

    max_degree = max(degree.values()) if degree and max(degree.values()) > 0 else 1
    max_in = max(in_degree.values()) if in_degree and max(in_degree.values()) > 0 else 1

    out: dict[str, float] = {}
    for cid in degree:
        deg_score = degree[cid] / max_degree
        in_score = in_degree[cid] / max_in
        # Weighted: in-degree (dependency load) matters more than raw degree
        out[cid] = round(0.4 * deg_score + 0.6 * in_score, 2)
    return out


def knowledge_blind_spots(
    asset: KnowledgeAsset, state: dict, top_n: int = 8
) -> list[dict]:
    """Detect "blind spot" concepts — high in-degree but zero/low mastery.

    A blind spot is a concept that many other concepts depend on (prerequisite
    or causal relations point TO it) but the learner hasn't studied or scored
    low on. These are the highest-risk gaps: leaving them unlearned undermines
    everything downstream.

    Returns list of dicts sorted by risk score (descending):
        name, id, in_degree, mastery, dependents (list of names), risk
    """
    from expert_anything.core.decoder import classify_relation

    # Count incoming structural edges (prereq/causes/is_a/part_of)
    in_degree: dict[str, int] = {c.id: 0 for c in asset.concepts}
    dependents_map: dict[str, list[str]] = {c.id: [] for c in asset.concepts}
    for r in asset.relations or []:
        sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
        if sem not in ("prereq", "causes", "is_a", "part_of"):
            continue
        if r.target in in_degree and r.source in in_degree:
            in_degree[r.target] += 1
            src_c = asset.concept_by_id(r.source)
            if src_c:
                dependents_map[r.target].append(src_c.name)

    # Build mastery lookup
    mastery_map: dict[str, float] = {}
    for k, v in state.get("concepts", {}).items():
        mastery_map[k] = float(v.get("mastery", 0.0))

    results = []
    for c in asset.concepts:
        deg = in_degree.get(c.id, 0)
        if deg == 0:
            continue
        nk = normalize(c.name)
        m = mastery_map.get(nk, 0.0)
        if m >= 0.3:
            continue  # Already learned — not a blind spot
        # Risk = in_degree * (1 - mastery) — more dependents + lower mastery = higher risk
        risk = round(deg * (1.0 - m), 2)
        results.append(
            {
                "name": c.name,
                "id": c.id,
                "in_degree": deg,
                "mastery": m,
                "dependents": dependents_map.get(c.id, [])[:5],
                "risk": risk,
            }
        )

    results.sort(key=lambda x: -x["risk"])
    return results[:top_n]


def generate_study_plan(
    asset: KnowledgeAsset,
    state: dict,
    minutes: int = 30,
    teacher: "object | None" = None,
) -> list[dict]:
    """Generate a time-boxed study plan for today.

    Picks concepts from the adaptive path (highest priority first) and
    estimates ~5 minutes per concept (teach + quiz). Also interleaves
    due reviews if time allows.

    ``teacher`` is a core.teacher.TeacherModel (or None). When given,
    open/investigating anomalies (plus surfaced learner-gap) promote the
    touched concepts inside adaptive_path — the plan inherits that
    priority instead of silently dropping it.

    Returns list of dicts: name, id, type ("new" or "review"), est_minutes, reason
    """
    from expert_anything.core.teacher import anomaly_concept_ids
    from expert_anything.core.decoder import classify_relation

    # anomaly-driven priority comes from the teacher model (AGENTS.md §2);
    # None keeps the old behaviour for callers that have no teacher yet
    anomaly_ids = anomaly_concept_ids(asset, teacher)

    plan: list[dict] = []
    remaining = minutes

    # 1) Due reviews first (quick, 3 min each) — if any
    due = due_for_review(state, asset=asset)
    for d in due:
        if remaining < 3:
            break
        plan.append(
            {
                "name": d["name"],
                "id": d.get("id", ""),
                "type": "review",
                "est_minutes": 3,
                "reason": t("plan_reason_due"),
            }
        )
        remaining -= 3

    # 2) New concepts from adaptive path (5 min each)
    items = adaptive_path(asset, state, anomaly_ids, limit=20)
    for item in items:
        if remaining < 5:
            break
        # Skip if already in plan
        if any(p["name"] == item["name"] for p in plan):
            continue
        tags = item.get("tags", [])
        reason_parts = []
        if "anom" in tags:
            reason_parts.append(t("plan_reason_anomaly"))
        if "stuck" in tags:
            reason_parts.append(t("plan_reason_stuck"))
        if "high_leverage" in tags:
            reason_parts.append(t("plan_reason_leverage"))
        if "weak" in tags:
            reason_parts.append(t("plan_reason_weak"))
        if not reason_parts:
            reason_parts.append(t("plan_reason_path"))
        plan.append(
            {
                "name": item["name"],
                "id": item.get("cid", ""),
                "type": "new",
                "est_minutes": 5,
                "reason": " · ".join(reason_parts),
            }
        )
        remaining -= 5

    # 3) Fill remaining time with blind spot concepts
    spots = knowledge_blind_spots(asset, state, top_n=5)
    for sp in spots:
        if remaining < 5:
            break
        if any(p["name"] == sp["name"] for p in plan):
            continue
        plan.append(
            {
                "name": sp["name"],
                "id": sp["id"],
                "type": "blind_spot",
                "est_minutes": 5,
                "reason": f"盲区(风险{sp['risk']:.1f})",
            }
        )
        remaining -= 5

    return plan


def review_gain(state: dict) -> dict:
    """Measure how much review sessions actually consolidate (AGENTS.md §5/§6).

    For each concept, the baseline is the score of its LAST first-time
    (review=False) attempt; every review (review=True) attempt after that
    counts as consolidation effect. Gain = review_avg - baseline.

    Records without ``meta.review`` (legacy data) count as first-time, so
    the metric degrades gracefully instead of silently dropping history.

    Returns:
      {"concepts": [{concept, baseline, review_avg, gain, n}],
       "avg_gain": float, "review_count": int, "measurable": int}
    """
    history = list(reversed(state.get("history", [])))  # oldest first
    by_concept: dict[str, list[tuple[bool, float]]] = {}
    for h in history:
        name = h.get("concept", "")
        if not name:
            continue
        meta = h.get("meta") or {}
        score = float(h.get("score", 0.0))
        by_concept.setdefault(name, []).append((bool(meta.get("review")), score))

    rows: list[dict] = []
    review_count = 0
    for name, marks in by_concept.items():
        first_scores = [s for r, s in marks if not r]
        review_scores = [s for r, s in marks if r]
        review_count += len(review_scores)
        if not review_scores or not first_scores:
            continue  # need both a baseline and reviews to measure gain
        # Baseline: best first-time score — a conservative estimate of
        # what the learner reached before reviews kicked in.
        baseline = max(first_scores)
        review_avg = sum(review_scores) / len(review_scores)
        rows.append(
            {
                "concept": name,
                "baseline": round(baseline, 2),
                "review_avg": round(review_avg, 2),
                "gain": round(review_avg - baseline, 2),
                "n": len(review_scores),
            }
        )
    avg_gain = round(sum(r["gain"] for r in rows) / len(rows), 2) if rows else 0.0
    return {
        "concepts": sorted(rows, key=lambda r: -r["gain"]),
        "avg_gain": avg_gain,
        "review_count": review_count,
        "measurable": len(rows),
    }


def style_effectiveness(state: dict) -> dict[str, dict]:
    """Analyze which teaching styles work best for this learner.

    Reads the ``meta`` field from history records — specifically
    ``style`` and ``channel`` — and computes per-style average score
    and attempt count.

    Review records are counted separately under a ``"review"`` bucket:
    a high review score proves the learner *retained* material, not
    that the original teaching style was effective — mixing both into
    one average would dilute style attribution (review scores skew
    high because only mastered concepts get reviewed).

    Returns ``{style_name: {"avg": float, "count": int, "best_for": [concept_names], "review": {...}}}``.
    Styles not present in history are omitted.
    """
    style_scores: dict[str, list[tuple[float, str]]] = {}
    for h in state.get("history", []):
        meta = h.get("meta") or {}
        if meta.get("review"):
            continue  # retention evidence, not teaching evidence
        if meta.get("channel") == RECALL_CHANNEL:
            continue  # self-explanation coverage, not a teaching style
        style = meta.get("style") or meta.get("channel") or "default"
        score = float(h.get("score", 0.0))
        concept = h.get("concept", "")
        style_scores.setdefault(style, []).append((score, concept))

    # Review records keep their own bucket (per review style) so the
    # retention signal stays visible without polluting teaching-style
    # averages.
    review_scores: dict[str, list[tuple[float, str]]] = {}
    for h in state.get("history", []):
        meta = h.get("meta") or {}
        if not meta.get("review"):
            continue
        style = meta.get("style") or meta.get("channel") or "default"
        score = float(h.get("score", 0.0))
        concept = h.get("concept", "")
        review_scores.setdefault(style, []).append((score, concept))

    out: dict[str, dict] = {}
    for style, pairs in style_scores.items():
        scores = [s for s, _ in pairs]
        avg = sum(scores) / len(scores) if scores else 0.0
        # Best-for: concepts where this style scored >= 0.8
        best_for = sorted({c for s, c in pairs if s >= 0.8})
        out[style] = {
            "avg": round(avg, 2),
            "count": len(scores),
            "best_for": best_for[:5],
        }
    for style, pairs in review_scores.items():
        scores = [s for s, _ in pairs]
        entry = out.get(style)
        if entry is None:
            out[style] = {
                "avg": 0.0,
                "count": 0,
                "best_for": [],
                "review": {
                    "avg": round(sum(scores) / len(scores), 2),
                    "count": len(scores),
                },
            }
        else:
            entry["review"] = {
                "avg": round(sum(scores) / len(scores), 2),
                "count": len(scores),
            }
    return out


def style_rotation_hint(
    state: dict,
    current: str,
    fallback_next: str,
    styles: list[str] | None = None,
    min_samples: int = 2,
    margin: float = 0.15,
) -> tuple[str, str]:
    """Retention-aware target for a stuck-driven style rotation.

    The blind cycle (fallback_next) treats all styles equally, but a style
    can teach well in-session and consolidate poorly (high teaching avg,
    low review retention). When the trace has enough evidence that the
    next stop in the cycle consolidates *clearly worse* than the current
    style, and some other style holds at least as well as the current
    one, deviate to that style instead.

    Returns (style, reason): the style to rotate to and why. With
    insufficient evidence the fallback pair is returned unchanged —
    conservative default, no small-sample overfitting.
    """
    try:
        eff = style_effectiveness(state)
    except Exception:
        return fallback_next, ""

    def retention(style: str) -> tuple[float, int] | None:
        bucket = (eff.get(style) or {}).get("review") or {}
        n = int(bucket.get("count", 0))
        if n < min_samples:
            return None
        return float(bucket.get("avg", 0.0)), n

    cur = retention(current)
    nxt = retention(fallback_next)
    if cur is None or nxt is None:
        return fallback_next, ""
    cur_avg, _ = cur
    nxt_avg, _ = nxt
    if nxt_avg >= cur_avg - margin:
        return fallback_next, ""

    pool = styles if styles else [s for s in eff.keys()]
    best: tuple[float, str] | None = None
    for s in pool:
        if s == current or s == fallback_next:
            continue
        r = retention(s)
        if r is None:
            continue
        avg, n = r
        if avg >= cur_avg and (best is None or avg > best[0]):
            best = (avg, s)
    if best is None:
        return fallback_next, ""
    return best[1], "retention"


def learning_efficiency(state: dict) -> dict:
    """Analyze learning ROI: time investment vs mastery growth.

    Computes:
      - total_sessions: number of evaluation records
      - total_concepts_studied: distinct concepts with at least 1 evaluation
      - avg_score: mean across all evaluations
      - mastery_delta: total mastery increase (sum of per-concept latest mastery)
      - efficiency: mastery_delta / total_sessions (ROI per session)
      - trend: "improving" | "stable" | "declining" — comparing recent vs older scores
      - recent_avg vs early_avg: for trend detection
    """
    history = state.get("history", [])
    if not history:
        return {
            "total_sessions": 0,
            "total_concepts_studied": 0,
            "avg_score": 0.0,
            "mastery_delta": 0.0,
            "efficiency": 0.0,
            "trend": "unknown",
            "recent_avg": 0.0,
            "early_avg": 0.0,
        }

    total_sessions = len(history)
    concepts_seen: set[str] = set()
    scores: list[float] = []
    for h in history:
        c = h.get("concept", "")
        if c:
            concepts_seen.add(c)
        scores.append(float(h.get("score", 0.0)))
    avg_score = sum(scores) / len(scores) if scores else 0.0

    # Mastery delta: sum of latest mastery per concept
    mastery_delta = 0.0
    for rec in state.get("concepts", {}).values():
        mastery_delta += float(rec.get("mastery", 0.0))

    efficiency = round(mastery_delta / total_sessions, 3) if total_sessions else 0.0

    # Trend: compare last 1/3 vs first 1/3 of history
    third = max(1, len(scores) // 3)
    early_avg = sum(scores[:third]) / third
    recent_avg = sum(scores[-third:]) / third
    if recent_avg > early_avg + 0.1:
        trend = "improving"
    elif recent_avg < early_avg - 0.1:
        trend = "declining"
    else:
        trend = "stable"

    return {
        "total_sessions": total_sessions,
        "total_concepts_studied": len(concepts_seen),
        "avg_score": round(avg_score, 2),
        "mastery_delta": round(mastery_delta, 1),
        "efficiency": efficiency,
        "trend": trend,
        "recent_avg": round(recent_avg, 2),
        "early_avg": round(early_avg, 2),
    }


def dependency_chain(
    asset: KnowledgeAsset, concept_id: str, max_depth: int = 10
) -> list[dict]:
    """Recursively extract the full prerequisite chain for a concept.

    Traverses prereq/causes relations backwards (from target to source)
    to find all concepts that must be learned before this one.

    Returns a list of dicts ordered from root → target:
        id, name, depth, mastery, relation_to_child
    """
    from expert_anything.core.decoder import classify_relation

    # Build reverse adjacency: target_id -> [(source_id, label, sem)]
    reverse: dict[str, list[tuple[str, str, str]]] = {}
    for r in asset.relations or []:
        sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
        if sem not in ("prereq", "causes"):
            continue
        reverse.setdefault(r.target, []).append((r.source, r.label or "", sem))

    # BFS from concept_id, collecting ancestors
    visited: set[str] = set()
    chain: list[dict] = []
    queue: list[tuple[str, int, str]] = [(concept_id, 0, "")]
    while queue and len(chain) < max_depth * 5:
        cid, depth, rel = queue.pop(0)
        if cid in visited:
            continue
        visited.add(cid)
        c = asset.concept_by_id(cid)
        if not c:
            continue
        chain.append(
            {
                "id": cid,
                "name": c.name,
                "depth": depth,
                "relation_to_child": rel,
            }
        )
        for src_id, label, sem in reverse.get(cid, []):
            if src_id not in visited:
                queue.append((src_id, depth + 1, label))

    # Sort by depth (root first), then name for determinism
    chain.sort(key=lambda x: (x["depth"], x["name"]))

    # Build mastery lookup
    nk = normalize(c.name) if c else ""
    return chain


def mastery_prediction(state: dict, concept_name: str) -> dict:
    """Predict if a concept will reach mastery (>=0.6) based on trend.

    Analyzes the score trajectory for a concept and predicts whether
    it's on track to reach 0.6 mastery.

    Review-channel records (``meta.review``) are excluded: sessions here
    mean teaching sessions, and the forgetting dips spaced review is
    *designed to surface* would drag the slope negative — predicting
    "will never achieve" from data that only says "needs another review".

    Returns:
        predicted_mastery: linear extrapolation of current trend
        will_achieve: bool, whether predicted >= 0.6
        sessions_needed: estimated sessions to reach 0.6
        trend: "rising" | "falling" | "flat" | "unknown"
    """
    scores: list[float] = []
    for h in state.get("history", []):
        meta = h.get("meta") or {}
        if meta.get("review") or meta.get("channel") == RECALL_CHANNEL:
            continue  # retention / self-explanation dips are not teaching trends
        if normalize(h.get("concept", "")) == normalize(concept_name):
            scores.append(float(h.get("score", 0.0)))

    if len(scores) < 2:
        nk = normalize(concept_name)
        current = float(state.get("concepts", {}).get(nk, {}).get("mastery", 0.0))
        return {
            "predicted_mastery": round(current, 2),
            "will_achieve": current >= 0.6,
            "sessions_needed": 0 if current >= 0.6 else -1,
            "trend": "unknown",
        }

    # ``record_evaluation`` stores history newest-first.  Regression time must
    # run oldest -> newest, otherwise genuine improvement is reported as a
    # decline and the forecast moves in the wrong direction.
    scores.reverse()

    # Linear regression on scores (y = a + b*x)
    n = len(scores)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(scores) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, scores))
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den else 0.0
    intercept = mean_y - slope * mean_x

    current_mastery = float(
        state.get("concepts", {}).get(normalize(concept_name), {}).get("mastery", 0.0)
    )
    predicted = current_mastery + slope * 2  # 2 more sessions
    predicted = max(0.0, min(1.0, predicted))

    if slope > 0.05:
        trend = "rising"
    elif slope < -0.05:
        trend = "falling"
    else:
        trend = "flat"

    # Sessions needed to reach 0.6
    if slope > 0 and current_mastery < 0.6:
        sessions_needed = max(1, int((0.6 - current_mastery) / slope))
    elif current_mastery >= 0.6:
        sessions_needed = 0
    else:
        sessions_needed = -1

    return {
        "predicted_mastery": round(predicted, 2),
        "will_achieve": predicted >= 0.6,
        "sessions_needed": sessions_needed,
        "trend": trend,
    }


def adaptive_path(
    asset: KnowledgeAsset,
    learner_state: dict,
    anomaly_ids: set | None = None,
    path: list[str] | None = None,
    limit: int = 8,
) -> list[dict]:
    """Build an adaptive, ranked study queue for the learner.

    Returns a list ordered by priority (most urgent first). Each item is a dict:
        cid, name, mastery, score, downstream, completed, tags
    `tags` are reason codes the UI turns into chips: "anom", "weak",
    "foundation", "unblock:<n>", "ready", "blocked", "path".

    The score blends five signals so the queue reflects *real* adaptive
    behaviour instead of one hard-coded rule:
      * mastery deficit  (lower mastery -> higher priority);
      * anomaly link     (walk ahead of the student to resolve open anomalies);
      * stuck link       (repeated failed attempts -> change strategy, re-teach);
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
        path = (
            (entry.get("path") if entry else None)
            or list(asset.learning_path)
            or [c.id for c in asset.concepts]
        )

    # prerequisite graph: source -> target means target depends on source.
    # Only ordering-type relations (prerequisite / causes / sequence) create
    # real learning dependencies. Contrast relations link *different*
    # concepts, not dependent ones — including them would make "A vs B" pairs
    # look like "you must learn A before B", which is wrong.
    from expert_anything.core.decoder import classify_relation

    _ORDERING_SEMS = {"prereq", "causes"}

    incoming: dict[str, set] = {c.id: set() for c in asset.concepts}
    outgoing: dict[str, set] = {c.id: set() for c in asset.concepts}
    for r in asset.relations or []:
        s = getattr(r, "source", None) or (
            r.get("source") if isinstance(r, dict) else None
        )
        tg = getattr(r, "target", None) or (
            r.get("target") if isinstance(r, dict) else None
        )
        if s in incoming and tg in incoming and s != tg:
            rtype = getattr(r, "type", "") or (
                r.get("type", "") if isinstance(r, dict) else ""
            )
            rlabel = getattr(r, "label", "") or (
                r.get("label", "") if isinstance(r, dict) else ""
            )
            sem = classify_relation(rlabel or "", rtype or "")
            if sem in _ORDERING_SEMS:
                incoming[tg].add(s)
                outgoing[s].add(tg)

    # transitive downstream width (how many concepts a mastered concept unblocks)
    downstream: dict[str, int] = {}
    # leverage value: downstream count weighted by downstream concepts' own
    # outgoing edges — a concept that unlocks *other* hub concepts has higher
    # learning leverage than one that only unlocks leaf concepts.
    leverage: dict[str, float] = {}
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
        # Leverage = count * (1 + avg_outdegree_of_downstream / 2)
        # This rewards concepts that unlock *other* multipliers.
        if seen:
            avg_out = sum(len(outgoing.get(x, ())) for x in seen) / len(seen)
            leverage[c.id] = len(seen) * (1.0 + avg_out / 2.0)
        else:
            leverage[c.id] = 0.0

    pos = {cid: i for i, cid in enumerate(dict.fromkeys(path))}
    stuck_keys = {s["key"] for s in stuck_concepts(learner_state)}

    items: list[dict] = []
    for c in asset.concepts:
        cid = c.id
        m = mm.get(cid, 0.0)
        if m >= W and cid not in anomaly_ids and normalize(c.name) not in stuck_keys:
            continue  # already mastered, not anomaly/stuck-linked -> skip
        tags: list[str] = []
        score = 0.0
        deficit = max(0.0, (W - m)) / W if W > 0 else 0.0
        if deficit > 0:
            score += deficit
            tags.append("weak")
        if cid in anomaly_ids:
            score += 0.35
            tags.append("anom")
        if normalize(c.name) in stuck_keys:
            score += 0.45
            tags.append("stuck")
        if incoming[cid] and not outgoing[cid]:
            score += 0.08
            tags.append("foundation")
        dw = downstream.get(cid, 0)
        lev = leverage.get(cid, 0.0)
        if dw > 0:
            # Unlock value: scales with leverage (how much of the knowledge
            # network opens up when you master this concept). The multiplier
            # is proportional to mastery deficit — a fully-mastered hub
            # concept doesn't need prioritisation just because it's a hub.
            unlock_bonus = min(0.35, 0.03 * lev)
            score += (
                unlock_bonus * deficit
            )  # weighted by how much we still need to learn it
            # A concept that transitively unlocks >= 3 downstream concepts is
            # high-leverage regardless of the bonus magnitude — the bonus
            # formula saturates slowly (leverage 5 only yields 0.15), which
            # hid genuine hubs from the coach's focus claim.
            if dw >= 3 or unlock_bonus >= 0.15:
                tags.append("high_leverage")
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
                # If a prerequisite is very weak (< 0.5), the dependent
                # concept should NOT be taught before the prerequisite is
                # shored up — otherwise the learner keeps failing on a
                # concept whose foundation is shaky.
                min_prereq_m = min(pm) if pm else 1.0
                if min_prereq_m < 0.5:
                    prereq_gap = (0.5 - min_prereq_m) / 0.5
                    score -= 0.2 * prereq_gap
                    tags.append("prereq_shaky")
        # Prerequisites of stuck concepts get a boost — fixing the
        # foundation unblocks everything downstream.
        if outgoing[cid] and normalize(c.name) not in stuck_keys:
            for dep_id in outgoing[cid]:
                dep_c = asset.concept_by_id(dep_id)
                if dep_c and normalize(dep_c.name) in stuck_keys:
                    score += 0.2
                    tags.append("unblock_stuck")
                    break
        items.append(
            {
                "cid": cid,
                "name": c.name,
                "mastery": m,
                "score": round(score, 3),
                "downstream": dw,
                "completed": cid in completed,
                "tags": tags,
            }
        )
    items.sort(key=lambda x: (-x["score"], x["name"]))
    return items[:limit]


def concept_density(asset: KnowledgeAsset, state: dict) -> dict[str, dict]:
    """Knowledge-density marking for each concept.

    density = importance x novelty:
      - importance (1-5): relational degree (hub concepts in the graph are
        structurally important), scaled and clipped.
      - novelty (0-1): 1 - mastery (unlearned concepts are the newest for
        this learner).
    Returns {cid: {"importance": int, "novelty": float, "badge": str}} where
    badge is a reason code for the UI: "hot" / "important" / "new" / "".
    """
    adj: dict[str, set] = {c.id: set() for c in asset.concepts}
    for r in asset.relations or []:
        s = getattr(r, "source", None)
        t = getattr(r, "target", None)
        if s in adj and t in adj and s != t:
            adj[s].add(t)
            adj[t].add(s)

    by_norm = {
        normalize(k): float(r.get("mastery", 0.0))
        for k, r in state.get("concepts", {}).items()
    }
    out: dict[str, dict] = {}
    for c in asset.concepts:
        deg = len(adj[c.id])
        importance = min(5, max(1, round(deg / 1.5) + 1))
        mastery = by_norm.get(normalize(c.name), 0.0)
        novelty = round(1.0 - mastery, 2)
        if importance >= 4 and mastery == 0:
            badge = "hot"
        elif importance >= 4:
            badge = "important"
        elif mastery == 0 and importance >= 2:
            badge = "new"
        else:
            badge = ""
        out[c.id] = {"importance": importance, "novelty": novelty, "badge": badge}
    return out


def topic_clusters(asset: KnowledgeAsset, min_size: int = 1) -> list[dict]:
    """Group a book's concepts into topic clusters.

    Clusters are the connected components of the relation graph (concepts
    linked by any *non-contrast* relation belong to one topic). Contrast
    relations link *different/opposing* concepts, not similar ones —
    including them would merge "A vs B" into the same cluster, defeating
    the purpose of topic grouping. Each cluster is named after its hub
    (highest-degree concept).
    """
    from expert_anything.core.decoder import classify_relation

    adj: dict[str, set] = {c.id: set() for c in asset.concepts}
    for r in asset.relations or []:
        s = getattr(r, "source", None)
        t = getattr(r, "target", None)
        if s in adj and t in adj and s != t:
            rtype = getattr(r, "type", "") or ""
            rlabel = getattr(r, "label", "") or ""
            sem = classify_relation(rlabel or "", rtype or "")
            if sem == "contrast":
                continue
            adj[s].add(t)
            adj[t].add(s)

    seen: set[str] = set()
    clusters: list[list[str]] = []
    for c in asset.concepts:
        if c.id in seen:
            continue
        comp: list[str] = []
        stack = [c.id]
        seen.add(c.id)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        clusters.append(comp)

    out: list[dict] = []
    for comp in clusters:
        if len(comp) < min_size:
            continue
        deg = {cid: len(adj[cid]) for cid in comp}
        hub = max(comp, key=lambda cid: deg[cid])
        hub_c = asset.concept_by_id(hub)
        # Ordered learning sequence: follow the asset's learning_path first
        # (curated order), then append any remaining concepts in degree order.
        comp_set = set(comp)
        ordered = [c for c in asset.learning_path if c in comp_set]
        remaining = sorted(
            [c for c in comp if c not in set(ordered)],
            key=lambda cid: -deg.get(cid, 0),
        )
        ordered.extend(remaining)
        out.append(
            {
                "id": hub,
                "name": hub_c.name if hub_c else hub,
                "concept_ids": comp,
                "ordered_ids": ordered,
                "size": len(comp),
            }
        )
    out.sort(key=lambda x: -x["size"])
    return out


def stuck_concepts(
    state: dict, attempts: int = 3, threshold: float | None = None
) -> list[dict]:
    """Concepts whose last N evaluated attempts ALL fell below the weakness
    threshold — the learning-loop analog of OmniScientist's "null result →
    re-ideate": when repeated tests keep failing, the pipeline must change
    its teaching strategy instead of repeating it.

    Reads the history trace (source of truth), newest-first; returns
    [{key, name, attempts, avg}] for every concept with >= ``attempts``
    recent evaluations whose maximum score is still below ``threshold``.

    Review-channel records (``meta.review``) are skipped: normal forgetting
    during spaced review is expected behaviour, not a strategy failure —
    low review scores are already handled by the review_gain→gain_weak
    pipeline (retention signal). Mixing channels would fire stuck → style
    rotation / O1 evolution on data that only says "the learner forgot",
    double-signalling one root cause with the learner_gap anomaly.
    """
    if attempts < 2:
        attempts = 2
    if threshold is None:
        threshold = config.WEAKNESS_THRESHOLD
    recent: dict[str, list[float]] = {}
    names: dict[str, str] = {}
    for h in state.get("history", []):  # newest first
        meta = h.get("meta") or {}
        if meta.get("review") or meta.get("channel") == RECALL_CHANNEL:
            continue  # retention / self-explanation evidence — not strategy failure
        key = h.get("key") or normalize(h.get("concept", ""))
        if not key:
            continue
        scores = recent.setdefault(key, [])
        names.setdefault(key, h.get("concept", key))
        if len(scores) >= attempts:
            continue  # only the most recent N attempts matter
        try:
            scores.append(float(h.get("score", 0.0)))
        except (TypeError, ValueError):
            continue
    out: list[dict] = []
    for key, scores in recent.items():
        if len(scores) >= attempts and max(scores) < threshold:
            out.append(
                {
                    "key": key,
                    "name": names.get(key, key),
                    "attempts": len(scores),
                    "avg": round(sum(scores) / len(scores), 2),
                }
            )
    out.sort(key=lambda x: x["avg"])
    return out


def is_stuck(state: dict, concept_name: str, attempts: int = 3) -> bool:
    """Fast predicate: is THIS concept currently stuck?"""
    key = normalize(concept_name)
    return any(s["key"] == key for s in stuck_concepts(state, attempts=attempts))


def due_for_review(state: dict, limit: int = 8, asset=None, now=None) -> list[dict]:
    """Concepts whose mastery needs refreshing (spacing-effect based).

    A concept becomes *due* when the days since its last evaluation exceed a
    review interval that grows with mastery: weak concepts (mastery < 0.6) are
    due after 1 day, stronger ones after ~3-6 days (3 * (1 + mastery)). This
    turns the Learner Model into an active review scheduler instead of a
    passive scoreboard, so learned material is revisited right before it would
    fade (Ebbinghaus-style spacing).

    ``now`` is an optional ``datetime`` used as "today" instead of
    ``datetime.now(timezone.utc)`` — injected only by the benchmark/tests so
    the spacing algorithm can be fast-forwarded deterministically (no wall
    clock, no randomness).  Callers that don't pass it keep the original
    behaviour.

    If ``asset`` is provided, concepts whose prerequisite/causes neighbours are
    weak get a boost — reviewing a shaky foundation is more urgent because it
    undermines everything built on top of it. Concepts without a source anchor
    (template-enriched / unlocatable, the ◌ population) get a shorter interval:
    the learner cannot re-read the passage to self-reinforce, so system-side
    review is the only consolidation channel they have.
    """
    from datetime import datetime, timezone
    from expert_anything.core.decoder import classify_relation

    # The asset graph addresses concepts by stable ids while learner memory
    # addresses them by normalized names.  Translate once at the boundary so
    # asset-scoped review and prerequisite boosting operate on the same keys.
    asset_key_to_id: dict[str, str] = {}
    asset_keys: set[str] | None = None
    unanchored_ids: set[str] = set()
    if asset is not None:
        asset_key_to_id = {
            normalize(c.name): c.id for c in getattr(asset, "concepts", [])
            if getattr(c, "name", "")
        }
        asset_keys = set(asset_key_to_id)
        unanchored_ids = {
            c.id for c in getattr(asset, "concepts", [])
            if not getattr(c, "locations", None)
        }

    # Build a map of weak prerequisite concepts (mastery < 0.5) whose
    # dependents should be prioritised for review.  Relations use concept ids,
    # so resolve ids through the asset rather than looking them up directly in
    # the learner model.
    weak_prereqs: set[str] = set()
    if asset and getattr(asset, "relations", None):
        id_to_key = {cid: key for key, cid in asset_key_to_id.items()}
        for r in asset.relations:
            sem = classify_relation(r.label or "", getattr(r, "type", "") or "")
            if sem in ("prereq", "causes"):
                source_key = id_to_key.get(r.source, "")
                target_key = id_to_key.get(r.target, "")
                # For “A depends on B”, B is the prerequisite and A is the
                # concept whose review should be pulled forward.  Causal
                # edges have the opposite useful direction: a weak cause
                # makes its effect worth revisiting sooner.
                weak_key, dependent_key = (
                    (target_key, source_key) if sem == "prereq"
                    else (source_key, target_key)
                )
                rec = state.get("concepts", {}).get(weak_key, {})
                if rec and float(rec.get("mastery", 0.0)) < 0.5 and dependent_key:
                    weak_prereqs.add(dependent_key)

    # Review-consolidation scheduling (§6): concepts whose reviews reliably
    # score above their first-time baseline have demonstrably stuck, so the
    # next interval can stretch; concepts whose reviews fall below baseline
    # need another pass soon regardless of what mastery alone suggests.
    gain_by_key: dict[str, dict] = {
        normalize(r.get("concept", "")): r for r in review_gain(state)["concepts"]
    }

    out: list[dict] = []
    now = now if now is not None else datetime.now(timezone.utc)
    for key, rec in state.get("concepts", {}).items():
        if asset_keys is not None and key not in asset_keys:
            continue
        mastery = float(rec.get("mastery", 0.0))
        updated = rec.get("updated_at", "")
        if not updated or mastery <= 0:
            continue  # never evaluated -> nothing to refresh yet
        try:
            last = datetime.fromisoformat(updated)
        except (TypeError, ValueError):
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        else:
            last = last.astimezone(timezone.utc)
        days = max(0.0, (now - last).total_seconds() / 86400)
        # Dynamic interval: base on mastery, then expand based on review count
        # (spaced repetition: each successful review grows the interval)
        review_count = 0
        for h in state.get("history", []):
            if (
                h.get("key") == key
                or normalize(h.get("concept", "")) == key
            ):
                review_count += 1
        # Base interval: 1 day for weak, 3*(1+mastery) for strong
        base_interval = 1.0 if mastery < 0.6 else 3.0 * (1.0 + mastery)
        # Growth factor: interval * 1.5^(review_count-1), capped at 30 days
        # More successful reviews = longer interval (Ebbinghaus-style)
        if review_count > 1:
            interval = min(30.0, base_interval * (1.5 ** (review_count - 1)))
        else:
            interval = base_interval
        # If this concept depends on a weak prerequisite, shorten the
        # interval — the foundation it rests on is shaky, so review sooner.
        boost = key in weak_prereqs
        if boost:
            interval = min(interval, 1.0)
        # Review-gain modulation: reviews consistently above baseline mean
        # the material stuck — stretch the next interval (Ebbinghaus-style
        # expansion earned by evidence, not by time alone). Reviews below
        # baseline mean consolidation failed — come back tomorrow instead
        # of trusting the mastery-based interval.
        g = gain_by_key.get(key)
        gain_stretched = g is not None and g["gain"] >= 0.15 and g["n"] >= 2
        gain_weak = g is not None and g["gain"] <= -0.1
        if gain_stretched:
            interval = min(60.0, interval * 1.5)
        if gain_weak:
            interval = min(interval, 1.0)
        # No source anchor -> the learner can't jump to the passage and
        # re-read it, so halve the interval: system-side review carries the
        # full consolidation load for this concept.
        cid_here = asset_key_to_id.get(key, "")
        unanchored = cid_here in unanchored_ids
        if unanchored:
            interval = interval / 2.0
        if days >= interval:
            overdue = days - interval
            # Urgency: how far past the review window (0 = just due, higher = more urgent)
            # Normalised: overdue / interval, capped at 2.0 (2x overdue = max urgency)
            urgency = min(2.0, overdue / interval) if interval > 0 else 2.0
            # Urgency tiers: "overdue" (≥1.0), "due" (≥0.3), "soon" (<0.3)
            if urgency >= 1.0:
                urgency_tier = "overdue"
            elif urgency >= 0.3:
                urgency_tier = "due"
            else:
                urgency_tier = "soon"
            out.append(
                {
                    "key": key,
                    "id": asset_key_to_id.get(key, ""),
                    "name": rec.get("name", key),
                    "mastery": mastery,
                    "days_since": round(days, 1),
                    "interval": round(interval, 1),
                    "overdue_days": round(overdue, 1),
                    "urgency": round(urgency, 2),
                    "urgency_tier": urgency_tier,
                    "prereq_weak": boost,
                    "gain_stretched": gain_stretched,
                    "gain_weak": gain_weak,
                    "unanchored": unanchored,
                }
            )
    # Sort: prerequisite-weak and review-ineffective concepts first (both
    # are "the foundation is shaky" signals), then by urgency.
    out.sort(
        key=lambda x: (
            not (x.get("prereq_weak", False) or x.get("gain_weak", False)),
            -x["urgency"],
        )
    )
    return out[:limit]


def weaknesses(state: dict, limit: int = 8) -> list[dict]:
    out = []
    for key, rec in state.get("concepts", {}).items():
        if float(rec.get("mastery", 0.0)) < config.WEAKNESS_THRESHOLD:
            out.append(
                {
                    "key": key,
                    "name": rec.get("name", key),
                    "mastery": rec.get("mastery", 0.0),
                }
            )
    out.sort(key=lambda x: x["mastery"])
    return out[:limit]


# --------------------------------------------------------------------------- #
# Domain user profile (Phase 4) — deterministic, no LLM, no network
# --------------------------------------------------------------------------- #

#: Levels ``detect_user_profile`` may report (``unknown`` is reported too, but
#: only as a refusal — see :data:`PROFILE_UNKNOWN`).
PROFILE_LEVELS = ("novice", "some", "practiced")

#: Returned when the evidence is not enough to place the learner at all.
PROFILE_UNKNOWN = "unknown"

#: Share of the template's concepts the learner must have registered (and, for
#: ``practiced``, actually mastered) for each level.  Both constants are
#: deliberately conservative: a level is a claim about the learner, so the
#: module prefers ``unknown`` over a generous guess.
COVERAGE_PRACTICED = 0.5
COVERAGE_SOME = 0.15

#: Minimum evaluations before the learner's own scores outrank asset coverage.
MIN_SCORE_EVIDENCE = 3
SCORE_PRACTICED = 0.75
SCORE_SOME = 0.5

#: Claimed background -> teaching difficulty code the tutor/UI may surface.
DIFFICULTY_BY_LEVEL = {
    "novice": "foundation",
    "some": "standard",
    "practiced": "advanced",
    PROFILE_UNKNOWN: "unknown",
}


def _template_concept_keys(domain_id: str) -> tuple[str, dict[str, str]]:
    """Template concept variants -> template concept ID, plus template name.

    Built from the domain template only (name + bracketed alias), mirroring
    the variant rules used by :func:`concept_name_variants` so that an asset
    concept and a template concept are compared on the same key space.
    """
    try:
        from expert_anything.core import domain_templates
    except Exception:  # pragma: no cover - import guard for minimal installs
        return "", {}
    template = domain_templates.get_domain_template(domain_id)
    if template is None:
        return "", {}
    index: dict[str, str] = {}
    for chapter in template.chapters:
        for data in chapter.get("concepts", []) or []:
            cid = str(data.get("id", "") or "")
            if not cid:
                continue
            keys = set(
                domain_templates.concept_name_variants(str(data.get("name", "")))
            )
            for alias in data.get("aliases") or []:
                keys |= set(domain_templates.concept_name_variants(str(alias)))
            for key in keys:
                index.setdefault(key, cid)
    return template.name, index


def detect_user_profile(state: dict, domain_id: str = "electricity_trading") -> dict:
    """依据资产内容与领域模板给出确定性学习者背景判定 (Phase 4).

    Evidence, in priority order:

    1. the learner's own evaluation history — 3+ attempts give a direct
       score signal (avg >= 0.75 and half the touched concepts mastered ->
       ``practiced``; avg >= 0.5 -> ``some``; below -> ``novice``);
    2. otherwise, how much of the domain template the learner has already
       met — registered concepts are matched against the template's own
       concepts (name + alias, same normalization), and the covered share
       decides the level.

    Returns ``{"level", "known", "domain_id", "template_name",
    "difficulty_hint", "signals", "reasons"}``.  ``reasons`` carries
    ``{"code", "params"}`` entries — i18n keys plus their numbers — so the UI
    can render the *why* in any language instead of hard-coding prose.

    Deterministic and self-contained: no LLM, no network, no writes.  When
    the evidence is insufficient (no assets, no domain template, or no
    concept matching the template) it returns ``level = "unknown"`` with the
    corresponding reason rather than guessing.
    """
    assets = state.get("assets") or {}
    concepts = state.get("concepts") or {}
    history = state.get("history") or []
    template_name, template_index = _template_concept_keys(domain_id)
    template_ids = set(template_index.values())

    touched_ids: set[str] = set()
    mastered_ids: set[str] = set()
    weakness = float(getattr(config, "WEAKNESS_THRESHOLD", 0.5) or 0.5)
    for key, rec in concepts.items():
        cid = template_index.get(key) or template_index.get(
            normalize(str(rec.get("name", key)))
        )
        if not cid:
            continue
        touched_ids.add(cid)
        mastery = float(rec.get("mastery", 0.0) or 0.0)
        if mastery >= weakness:
            mastered_ids.add(cid)

    scores: list[float] = []
    for row in history:
        try:
            scores.append(float(row.get("score", 0.0)))
        except (TypeError, ValueError):
            continue
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    total = len(template_ids)
    coverage = round(len(touched_ids) / total, 2) if total else 0.0
    declared = ""
    profile = state.get("profile") or {}
    if str(profile.get("baseline", "") or "").strip() in PROFILE_LEVELS:
        declared = str(profile["baseline"]).strip()

    signals = {
        "assets": len(assets),
        "concepts": len(concepts),
        "template_concepts": total,
        "matched": len(touched_ids),
        "mastered": len(mastered_ids),
        "coverage": coverage,
        "evaluations": len(scores),
        "avg_score": avg_score,
        "declared_baseline": declared,
    }

    reasons: list[dict] = []
    if not assets and not concepts:
        reasons.append({"code": "profile_reason_no_data", "params": {}})
        level = PROFILE_UNKNOWN
    elif not template_ids:
        reasons.append(
            {"code": "profile_reason_no_template", "params": {"domain": domain_id}}
        )
        level = PROFILE_UNKNOWN
    elif not touched_ids:
        reasons.append({"code": "profile_reason_no_match", "params": {"total": total}})
        level = PROFILE_UNKNOWN
    elif len(scores) >= MIN_SCORE_EVIDENCE:
        mastered_ratio = len(mastered_ids) / len(touched_ids) if touched_ids else 0.0
        if avg_score >= SCORE_PRACTICED and mastered_ratio >= 0.5:
            level = "practiced"
        elif avg_score >= SCORE_SOME:
            level = "some"
        else:
            level = "novice"
        reasons.append(
            {
                "code": "profile_reason_scores",
                "params": {"n": len(scores), "avg": avg_score},
            }
        )
        reasons.append(
            {
                "code": "profile_reason_coverage",
                "params": {
                    "matched": len(touched_ids),
                    "total": total,
                    "percent": int(round(coverage * 100)),
                },
            }
        )
    elif declared:
        # No score signal, but the learner stated a baseline: trust it as-is
        # (it is still an explicit input, never an inference).
        level = declared
        reasons.append(
            {"code": "profile_reason_declared", "params": {"baseline": declared}}
        )
        reasons.append(
            {
                "code": "profile_reason_coverage",
                "params": {
                    "matched": len(touched_ids),
                    "total": total,
                    "percent": int(round(coverage * 100)),
                },
            }
        )
    else:
        mastered_ratio = len(mastered_ids) / len(touched_ids) if touched_ids else 0.0
        if coverage >= COVERAGE_PRACTICED and mastered_ratio >= 0.5:
            level = "practiced"
        elif coverage >= COVERAGE_SOME:
            level = "some"
        else:
            level = "novice"
        reasons.append(
            {
                "code": "profile_reason_coverage",
                "params": {
                    "matched": len(touched_ids),
                    "total": total,
                    "percent": int(round(coverage * 100)),
                },
            }
        )
        if mastered_ids:
            reasons.append(
                {
                    "code": "profile_reason_mastered",
                    "params": {
                        "mastered": len(mastered_ids),
                        "matched": len(touched_ids),
                    },
                }
            )
    if level not in PROFILE_LEVELS and level != PROFILE_UNKNOWN:  # pragma: no cover
        level = PROFILE_UNKNOWN

    return {
        "level": level,
        "known": level in PROFILE_LEVELS,
        "domain_id": domain_id,
        "template_name": template_name,
        "difficulty_hint": DIFFICULTY_BY_LEVEL.get(level, "unknown"),
        "signals": signals,
        "reasons": reasons,
    }


def profile_reason_text(profile: dict, translate) -> str:
    """Render :func:`detect_user_profile` reasons through ``translate``.

    ``translate`` is a ``key -> text`` callable (the UI passes ``i18n.t``),
    so the caller keeps control of the language and no prose is hard-coded
    here.  Unknown keys fall through to the raw code, which keeps the line
    readable instead of crashing on a missing translation.
    """
    parts: list[str] = []
    for reason in (profile or {}).get("reasons", []) or []:
        code = str(reason.get("code", "") or "")
        params = reason.get("params") or {}
        if not code:
            continue
        try:
            text = translate(code, **params)
        except Exception:
            text = code
        if text:
            parts.append(str(text))
    return " · ".join(parts)
