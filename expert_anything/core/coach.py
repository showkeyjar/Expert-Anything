"""Coach — the single proactive主张 (recommendation) for the learner.

Product intent
--------------
ExpertAnything already *computes* everything a coach needs: which concepts are
weak, which are high-leverage, which are stuck, which anomalies are open, and
what is due for spaced review.  The problem was that this intelligence was
spread across a dozen parallel cards and a one-line toast — the learner saw a
dashboard of options and nobody said "do this now, because…".

This module is the missing **orchestrator**: it collapses every existing signal
into exactly ONE主张, with a machine-checkable reason, so the UI can lead
instead of listing.

Feedback write-back
-------------------
The coach records how the learner reacts (``record_coach_feedback``) and demotes
kinds that keep getting dismissed (``coach_fatigue`` / ``_select``).  ``anomaly``
and ``stuck`` are exempt from demotion: a known contradiction or a repeated
failure must never be hidden because the learner clicked past it.

Design rules (AGENTS.md)
------------------------
- Deterministic: no LLM, no network, no UI. Core layer contract.
- No new algorithm: it *ranks* signals that other modules already produce
  (``adaptive_path`` / ``due_for_review`` / ``stuck_concepts`` /
  ``anomaly_concept_ids``).  Scoring stays where it already lives.
- Never blocks: any failure degrades to a safer, less specific主张.
- Review semantics are part of the contract: a due-item主张 carries
  ``kind="review"`` so the UI passes ``review=True`` down to the teaching
  entry point (AGENTS.md 6 — re-teaching from a different angle).

The output is a plain dict so it stays trivially testable and serializable::

    {
      "kind": "review",              # anomaly|stuck|prereq|review|focus|path|explore|import
      "concept_id": "c004",
      "concept_name": "日前市场",
      "why_key": "coach_why_review", # i18n key for the human reason
      "why_args": {"days": 3},
      "urgency": 0.72,               # sortable strength of the claim
      "alternatives": [ {...}, ... ],# runner-ups, same shape, for "换一个"
    }
"""

from __future__ import annotations

from typing import Any

from expert_anything.core.models import KnowledgeAsset

# Priority order for the *kind* of主张.  Earlier kinds win when they exist,
# because they represent a blocked or decaying learner state rather than an
# opportunity:
#   anomaly   — the system found a contradiction; resolving it protects trust
#   stuck     — repeated failure: repeating the same lesson is known-harmful
#   review    — decay is happening right now (spacing effect)
#   focus     — high-leverage weak concept: best forward progress
#   path      — plain path progression
#   explore   — everything mastered; consolidate / broaden
#   import    — nothing to coach yet
KIND_ORDER = (
    "anomaly",
    "stuck",
    "prereq",
    "review",
    "focus",
    "path",
    "explore",
    "import",
)

# Kinds whose lesson must be launched as spaced review (vary=1), never as a
# first-time lesson.  The UI reads this via ``is_review``.
_REVIEW_KINDS = frozenset({"review"})


# Kinds whose claim reports a *problem in the material or the learner's own
# repeated failure*.  These are never demoted by dismissal fatigue: suppressing
# them would silently hide something the system already knows is wrong.
FATIGUE_EXEMPT = frozenset({"anomaly", "stuck"})

# Consecutive dismissals of one kind before the coach stops leading with it.
FATIGUE_THRESHOLD = 3

# Bounded feedback log (newest-first), mirroring learner.trim_history's stance.
COACH_EVENT_CAP = 40

ACTIONS = ("start", "swap", "dismiss")


def is_review(rec: dict | None) -> bool:
    """True when this主张 must be taught with review semantics (AGENTS.md 6)."""
    return bool(rec) and rec.get("kind") in _REVIEW_KINDS


def _blank(
    kind: str,
    *,
    why_key: str = "",
    why_args: dict | None = None,
    urgency: float = 0.0,
) -> dict:
    return {
        "kind": kind,
        "concept_id": "",
        "concept_name": "",
        "why_key": why_key,
        "why_args": dict(why_args or {}),
        "urgency": round(float(urgency), 3),
        "alternatives": [],
    }


def _dedupe(recs: list[dict], limit: int = 3) -> list[dict]:
    """Keep at most *limit* alternatives, one per concept, best first."""
    out: list[dict] = []
    seen: set[str] = set()
    for r in recs:
        key = r.get("concept_name") or r.get("concept_id") or r.get("kind", "")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _unlock_count(tags: Any) -> int:
    """Parse the ``unblock:<n>`` tag adaptive_path emits."""
    for t in tags or ():
        if isinstance(t, str) and t.startswith("unblock:"):
            try:
                return int(t.split(":", 1)[1])
            except (TypeError, ValueError):
                return 0
    return 0


def _from_path_item(
    item: dict,
    kind: str,
    why_key: str,
    why_args: dict | None = None,
) -> dict:
    """Build a主张 from an ``adaptive_path`` item (keys: cid/name/score)."""
    rec = _blank(kind, why_key=why_key, why_args=why_args)
    rec["concept_id"] = item.get("cid", "") or ""
    rec["concept_name"] = item.get("name", "") or ""
    rec["urgency"] = round(float(item.get("score") or 0.0), 3)
    return rec


def _from_due_row(item: dict, why_key: str, why_args: dict | None = None) -> dict:
    """Build a主张 from a ``due_for_review`` row (keys: id/name/mastery)."""
    rec = _blank("review", why_key=why_key, why_args=why_args)
    rec["concept_id"] = item.get("id", "") or ""
    rec["concept_name"] = item.get("name", "") or ""
    mastery = float(item.get("mastery") or 0.0)
    rec["urgency"] = round(1.0 - min(1.0, max(0.0, mastery)), 3)
    return rec


def _unlocked_names(asset: KnowledgeAsset, concept_id: str, limit: int = 3) -> list[str]:
    """Names of the concepts this one directly unblocks (ordering edges only).

    Naming them is what turns "unlocks 6 downstream" into advice the learner can
    evaluate — they can see whether those are the concepts they actually care
    about.
    """
    if not concept_id:
        return []
    from expert_anything.core.decoder import classify_relation

    # Walk ordering edges transitively, nearest first: adaptive_path's count is
    # transitive, so a direct-edge list would print "1" next to "unlocks 6" and
    # read like a contradiction.
    direct: dict[str, list[str]] = {}
    for r in getattr(asset, "relations", None) or []:
        label = getattr(r, "label", "") or ""
        rtype = getattr(r, "type", "") or ""
        if classify_relation(label, rtype) not in ("prereq", "causes"):
            continue
        src = getattr(r, "source", None)
        tgt = getattr(r, "target", None)
        if src and tgt and src != tgt:
            direct.setdefault(src, []).append(tgt)

    out: list[str] = []
    seen = {concept_id}
    queue = list(direct.get(concept_id, ()))
    while queue and len(out) < limit:
        cid = queue.pop(0)
        if cid in seen:
            continue
        seen.add(cid)
        c = asset.concept_by_id(cid)
        if c is not None:
            out.append(c.name)
        queue.extend(direct.get(cid, ()))
    return out


def _prereq_of(
    asset: KnowledgeAsset, item: dict, learner_state: dict | None = None
) -> str:
    """Weakest direct prerequisite concept id of *item*, or "" if none.

    Only ordering edges (prereq / causes) count: contrast relations link
    different concepts rather than dependent ones, so treating them as
    prerequisites would send the learner to the wrong place.
    """
    item_id = item.get("cid") or ""
    if not item_id:
        return ""
    from expert_anything.core.decoder import classify_relation
    from expert_anything.core.learner import normalize as _norm

    state = learner_state or {}
    concepts_by_norm = state.get("concepts", {}) if isinstance(state, dict) else {}

    weakest_id = ""
    weakest_m = 2.0
    for r in getattr(asset, "relations", None) or []:
        if getattr(r, "target", None) != item_id:
            continue
        label = getattr(r, "label", "") or ""
        rtype = getattr(r, "type", "") or ""
        if classify_relation(label, rtype) not in ("prereq", "causes"):
            continue
        src = getattr(r, "source", None)
        p = asset.concept_by_id(src) if src else None
        if p is None:
            continue
        rec = concepts_by_norm.get(_norm(p.name), {}) if concepts_by_norm else {}
        try:
            m = float(rec.get("mastery", 0.0))
        except (TypeError, ValueError):
            m = 0.0
        if m < weakest_m:
            weakest_m = m
            weakest_id = p.id
    return weakest_id


def _focus_or_path(
    item: dict, asset: KnowledgeAsset | None = None, learner_state: dict | None = None
) -> dict:
    """Classify a queue item into prereq / focus (high-leverage, weak) / path.

    Ready-first: a concept whose prerequisites are still shaky is *not* handed
    to the learner as the next move — that would guarantee a poor session.  The
    claim becomes "shore up its prerequisite first" instead.
    """
    tags = set(item.get("tags") or [])
    if asset is not None and ("prereq_shaky" in tags or "blocked" in tags):
        prereq_id = _prereq_of(asset, item, learner_state)
        if prereq_id:
            p = asset.concept_by_id(prereq_id)
            if p is not None:
                from expert_anything.core.learner import normalize as _norm

                state = learner_state or {}
                rec = (
                    state.get("concepts", {}).get(_norm(p.name), {})
                    if isinstance(state, dict)
                    else {}
                )
                try:
                    p_mastery = float(rec.get("mastery", 0.0))
                except (TypeError, ValueError):
                    p_mastery = 0.0
                # Only redirect while the prerequisite is genuinely weak: a
                # stale block (already mastered) must not override the ranking.
                if p_mastery < 0.5:
                    r = _blank(
                        "prereq",
                        why_key="coach_why_prereq",
                        why_args={"name": item.get("name", ""), "pct": int(p_mastery * 100)},
                    )
                    r["concept_id"] = p.id
                    r["concept_name"] = p.name
                    r["urgency"] = round(min(1.0, 0.9 + (0.5 - p_mastery)), 3)
                    return r
    if "high_leverage" in tags:
        unlock = _unlock_count(tags)
        rec = _from_path_item(
            item,
            "focus",
            "coach_why_focus_unlock" if unlock else "coach_why_focus",
            {"n": unlock} if unlock else None,
        )
        if unlock and asset is not None:
            # Name what this unlocks.  The count from adaptive_path is
            # transitive; this list is the *direct* dependents, so it is
            # presented as an example rather than an exhaustive enumeration.
            names = _unlocked_names(asset, rec.get("concept_id") or "")
            if names:
                rec["why_args"]["names"] = "、".join(names)
        return rec
    if "weak" in tags:
        return _from_path_item(item, "focus", "coach_why_weak")
    return _from_path_item(item, "path", "coach_why_path")


def _alternatives(
    path_items: list[dict],
    exclude: dict | None = None,
    limit: int = 3,
    asset: KnowledgeAsset | None = None,
    learner_state: dict | None = None,
) -> list[dict]:
    """Runner-up主张s from the same ranked queue, for the "换一个" affordance.

    Uses the same ready-first classification as the main claim, so a swap can
    never drop the learner onto a concept whose prerequisites are shaky.
    """
    ex_name = (exclude or {}).get("concept_name", "")
    ex_id = (exclude or {}).get("concept_id", "")
    out: list[dict] = []
    for item in path_items:
        if item.get("cid") == ex_id or item.get("name") == ex_name:
            continue
        cand = _focus_or_path(item, asset, learner_state)
        # A prereq redirect can land on the very concept the main claim already
        # names (the shaky prerequisite itself). Re-offering it as a runner-up
        # would be a no-op "swap".
        if cand.get("concept_name") == ex_name or (
            ex_id and cand.get("concept_id") == ex_id
        ):
            continue
        out.append(cand)
    return _dedupe(out, limit=limit)


def record_coach_feedback(state: dict, rec: dict | None, action: str) -> None:
    """Persist one reaction to a claim: ``start`` / ``swap`` / ``dismiss``.

    Best-effort by contract: a malformed claim or state is ignored rather than
    raised, because losing a feedback row must never interrupt a lesson.
    """
    if not isinstance(state, dict) or action not in ACTIONS:
        return
    if not isinstance(rec, dict):
        return
    kind = rec.get("kind") or ""
    if not kind:
        return
    bucket = state.setdefault("coach", {})
    if not isinstance(bucket, dict):
        return
    from datetime import datetime, timezone

    events = bucket.setdefault("events", [])
    if not isinstance(events, list):
        return
    events.insert(
        0,
        {
            "kind": str(kind),
            "concept": str(rec.get("concept_name") or ""),
            "action": action,
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )
    del events[COACH_EVENT_CAP:]


def coach_fatigue(state: dict, threshold: int = FATIGUE_THRESHOLD) -> dict:
    """``{kind: consecutive_dismissals}`` for kinds the learner keeps skipping.

    Counts dismissals newest-first and stops at the first reaction of that kind
    which is *not* a dismissal, so an accepted claim resets the run.  Only kinds
    meeting ``threshold`` are returned, and ``FATIGUE_EXEMPT`` kinds are never
    included.
    """
    out: dict[str, int] = {}
    if not isinstance(state, dict):
        return out
    bucket = state.get("coach")
    if not isinstance(bucket, dict):
        return out
    events = bucket.get("events")
    if not isinstance(events, list):
        return out

    run: dict[str, int] = {}
    closed: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind") or "")
        if not kind or kind in closed:
            continue
        if ev.get("action") == "dismiss":
            run[kind] = run.get(kind, 0) + 1
        else:
            closed.add(kind)  # accepted (or swapped): the run ends here
    for kind, n in run.items():
        if n >= max(2, int(threshold)) and kind not in FATIGUE_EXEMPT:
            out[kind] = n
    return out


def _kind_rank(kind: str) -> int:
    """Priority index of a kind (unknown kinds sort last)."""
    try:
        return KIND_ORDER.index(kind)
    except ValueError:
        return len(KIND_ORDER)


def _select(candidates: list[dict], state: dict) -> dict:
    """First candidate not under dismissal fatigue; never suppress, only defer.

    The demoted claim is preserved among the alternatives so the learner can
    still reach it with "换一个", and when every candidate is fatigued the
    highest-priority one is returned regardless — the coach may lower its voice,
    never disappear.
    """
    if not candidates:
        rec = _blank("explore", why_key="coach_why_explore")
        rec["urgency"] = 0.1
        return rec
    if len(candidates) == 1:
        return candidates[0]

    fatigued = coach_fatigue(state)
    chosen = None
    if fatigued:
        chosen = next((c for c in candidates if c.get("kind") not in fatigued), None)
    if chosen is None:
        chosen = candidates[0]

    rec = dict(chosen)
    others = [c for c in candidates if c is not chosen]
    rec["alternatives"] = _dedupe(
        list(chosen.get("alternatives") or []) + others, limit=3
    )
    if fatigued:
        # Say plainly which suggestion was set aside and how often it was
        # skipped.  Reporting the *demoted* kind (not the chosen one) is what
        # makes the note truthful: the learner skipped that, not this.
        worst = max(fatigued.items(), key=lambda kv: (-kv[1], _kind_rank(kv[0])))
        rec["fatigue_note"] = {"n": worst[1], "kind": worst[0]}
    return rec


def _anomaly_ids(asset: KnowledgeAsset, teacher: Any) -> set:
    """Open anomaly concept ids, accepting a TeacherModel or its dict form."""
    if teacher is None:
        return set()
    from expert_anything.core.teacher import TeacherModel, anomaly_concept_ids

    model = teacher
    if isinstance(teacher, dict):
        model = TeacherModel.from_dict(teacher)
    return set(anomaly_concept_ids(asset, model))


def recommend(
    asset: KnowledgeAsset | None,
    learner_state: dict,
    teacher: Any | None = None,
) -> dict:
    """Return the ONE thing the learner should do next, plus runner-ups.

    ``teacher`` is a ``TeacherModel`` (or its dict form) used for anomaly
    signals.  Every branch is guarded so a failure in one signal degrades to
    the next-best主张 instead of raising — coaching must never block the app.
    """
    if asset is None or not getattr(asset, "concepts", None):
        rec = _blank("import", why_key="coach_why_import")
        rec["urgency"] = 1.0
        return rec

    state = learner_state if isinstance(learner_state, dict) else {}

    # --- gather signals, each guarded: a broken signal must not kill coaching
    try:
        anomaly_ids = _anomaly_ids(asset, teacher)
    except Exception:
        anomaly_ids = set()

    try:
        from expert_anything.core.learner import due_for_review

        due = due_for_review(state, asset=asset) or []
    except Exception:
        due = []

    try:
        from expert_anything.core.learner import stuck_concepts

        stuck = stuck_concepts(state) or []
    except Exception:
        stuck = []

    try:
        from expert_anything.core.learner import adaptive_path

        path_items = adaptive_path(asset, state, anomaly_ids, limit=8) or []
    except Exception:
        path_items = []

    # --- gather one candidate claim per signal, in priority order ------------
    # Building the list first (instead of returning from each branch) is what
    # makes dismissal fatigue possible: the coach can lower its voice on one
    # kind without losing the others.
    candidates: list[dict] = []

    # 1) anomaly: the system is holding an open question about the material
    if anomaly_ids:
        rec = None
        for item in path_items:
            if item.get("cid") in anomaly_ids:
                rec = _from_path_item(item, "anomaly", "coach_why_anomaly")
                rec["alternatives"] = _alternatives(path_items, exclude=rec)
                break
        if rec is None:
            # anomaly concept outside the ranked queue: still surface it by name
            for cid in sorted(anomaly_ids):
                name, resolved = _name_and_id(asset, cid)
                if name:
                    rec = _blank("anomaly", why_key="coach_why_anomaly")
                    rec["concept_id"] = resolved
                    rec["concept_name"] = name
                    rec["urgency"] = 0.95
                    rec["alternatives"] = _alternatives(path_items)
                    break
        if rec is not None:
            candidates.append(rec)

    # 2) stuck: repeating the current approach is known-harmful
    if stuck:
        from expert_anything.core.learner import normalize as _norm

        stuck_keys = {s.get("key") or "" for s in stuck}
        rec = None
        for item in path_items:
            if _norm(item.get("name", "")) in stuck_keys:
                rec = _from_path_item(item, "stuck", "coach_why_stuck")
                rec["alternatives"] = _alternatives(path_items, exclude=rec)
                break
        if rec is None:
            # stuck concept lives outside this asset's queue: still worth acting
            rec = _blank("stuck", why_key="coach_why_stuck")
            rec["concept_name"] = stuck[0].get("name", "") or ""
            rec["urgency"] = 0.9
            rec["alternatives"] = _alternatives(path_items)
        candidates.append(rec)

    # 3) review: decay is happening now (spacing effect)
    if due:
        top = due[0]
        rec = _from_due_row(
            top, "coach_why_review", {"days": int(top.get("days_since") or 0)}
        )
        rec["alternatives"] = _dedupe(
            [
                _from_due_row(d, "coach_why_review", {"days": int(d.get("days_since") or 0)})
                for d in due[1:4]
            ],
            limit=3,
        )
        candidates.append(rec)

    # 4) focus / path / prereq: forward progress, best concept first.
    # Goal-directed, not substitution: the top-ranked item is what the system
    # believes is the best next move.  If its prerequisites are still shaky the
    # claim names THAT bottleneck (kind "prereq") instead of silently swapping
    # in some other, easier concept — the learner keeps their goal and learns
    # what actually unblocks it.
    if path_items:
        rec = _focus_or_path(path_items[0], asset, state)
        rec["alternatives"] = _alternatives(
            path_items,
            exclude=rec,
            asset=asset,
            learner_state=state,
        )
        candidates.append(rec)

    # 5) dismissal fatigue may defer one kind, never silence a claim
    return _select(candidates, state)


def _name_and_id(asset: KnowledgeAsset, concept_id: str) -> tuple[str, str]:
    """(name, id) for a concept id; ("", "") when it is unknown."""
    c = asset.concept_by_id(concept_id) if concept_id else None
    if c is None:
        return "", ""
    return c.name, c.id
