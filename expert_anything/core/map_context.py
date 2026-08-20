"""Cognitive-map context: siblings / next level / concept comparison.

Clicking a concept on the living map must yield *information gain*, not a lone
node. This module derives the reader's "position sense" from the asset itself
(deterministic, no LLM):

- **siblings**  — same-chapter concepts first, then same topic-cluster members.
  "What stands next to it" (同级知识要点).
- **next_level** — relation neighbours (labelled, directed) plus learning-path
  successors. "Where it leads" (下一级知识要点). Falls back to the learning
  path when the concept has no relations, so a click never dead-ends.
- **compare**   — a structured two-concept comparison: shared neighbours,
  relations unique to each side, chapter, mastery gap and teacher-note
  differences, distilled into human-readable evidence points.

Everything is pure (``KnowledgeAsset`` in, dict out); the UI renders it.
"""
from __future__ import annotations

import difflib

from expert_anything.core.i18n import t as _t
from expert_anything.core.models import KnowledgeAsset


def _concept_map(asset: KnowledgeAsset) -> dict[str, object]:
    return {c.id: c for c in asset.concepts}


def _rel_neighbors(asset: KnowledgeAsset, cid: str) -> list[dict]:
    """Directed relation neighbours: [{id, name, label, dir}] (out/in)."""
    out = []
    for r in asset.relations or []:
        if r.source == cid and r.target != cid:
            out.append({"id": r.target, "label": r.label or "", "dir": "out"})
        elif r.target == cid and r.source != cid:
            out.append({"id": r.source, "label": r.label or "", "dir": "in"})
    return out


def siblings(asset: KnowledgeAsset, concept_id: str,
             max_n: int = 6, learner_state: dict | None = None) -> list[dict]:
    """Same-level knowledge points: concepts that sit *alongside* the given one.

    Priority: same chapter (``concept.chapter``, the source-location light) →
    same topic cluster (relation connected-component from ``topic_clusters``).
    Each entry: {id, name, chapter, mastery}.
    """
    c = asset.concept_by_id(concept_id)
    if c is None or not asset.concepts:
        return []

    # 1) same chapter — the most precise notion of "alongside"; when it is
    #    non-empty it *is* the answer (a whole-book cluster would flood the
    #    view with unrelated concepts on a fully connected graph).
    by_chapter: list[str] = []
    if getattr(c, "chapter", ""):
        ch = c.chapter
        by_chapter = [x.id for x in asset.concepts
                      if x.id != concept_id and getattr(x, "chapter", "") == ch]

    # 2) same topic cluster — fallback only when the concept has no chapter
    same_cluster: list[str] = []
    if not by_chapter:
        try:
            from expert_anything.core.learner import topic_clusters
            for cl in topic_clusters(asset, min_size=2):
                ids = cl.get("concept_ids", []) or []
                if concept_id in ids:
                    same_cluster = [i for i in ids if i != concept_id]
                    break
        except Exception:
            same_cluster = []

    # union, chapter first, stable order by asset concept order
    order = {x.id: i for i, x in enumerate(asset.concepts)}
    seen: set[str] = set()
    ranked: list[str] = []
    for cid in by_chapter + same_cluster:
        if cid not in seen:
            seen.add(cid)
            ranked.append(cid)
    ranked.sort(key=lambda i: (0 if i in by_chapter else 1, order.get(i, 0)))

    out = []
    for cid in ranked[:max_n]:
        cc = asset.concept_by_id(cid)
        if cc is None:
            continue
        mastery = 0.0
        if learner_state:
            rec = next((v for v in learner_state.get("concepts", {}).values()
                        if v.get("name") == cc.name), None)
            if rec:
                mastery = float(rec.get("mastery", 0.0))
        out.append({"id": cid, "name": cc.name,
                    "chapter": getattr(cc, "chapter", ""), "mastery": mastery})
    return out


def next_level(asset: KnowledgeAsset, concept_id: str,
               max_n: int = 8, learner_state: dict | None = None) -> list[dict]:
    """Next-level knowledge points: where the concept leads.

    Relation neighbours (labelled, direction-aware) first; learning-path
    successors after. If the concept has *no* relations, the learning path
    (predecessor + successor) fills the role so the view never dead-ends.
    Each entry: {id, name, label, dir ("out"/"in"/"path"), mastery}.
    """
    c = asset.concept_by_id(concept_id)
    if c is None:
        return []

    rels = _rel_neighbors(asset, concept_id)
    rel_ids = {r["id"] for r in rels}

    path_neighbors: list[str] = []
    if asset.learning_path:
        try:
            idx = asset.learning_path.index(concept_id)
        except ValueError:
            idx = -1
        if idx >= 0:
            # successors first (the concept "opens up" into these), then the
            # immediate predecessor as the "came from" anchor
            for j in range(idx + 1, len(asset.learning_path)):
                if asset.learning_path[j] not in rel_ids:
                    path_neighbors.append(asset.learning_path[j])
            if idx - 1 >= 0 and asset.learning_path[idx - 1] not in rel_ids:
                path_neighbors.append(asset.learning_path[idx - 1])

    # relation-less concept -> path neighbours become the primary content
    if not rels:
        path_neighbors = []
        if asset.learning_path:
            try:
                idx = asset.learning_path.index(concept_id)
            except ValueError:
                idx = -1
            if idx >= 0:
                for j in (idx - 1, idx + 1):
                    if 0 <= j < len(asset.learning_path) \
                            and asset.learning_path[j] != concept_id:
                        path_neighbors.append(asset.learning_path[j])

    order = {x.id: i for i, x in enumerate(asset.concepts)}
    out = []
    seen: set[str] = set()
    for r in rels[:max_n]:
        cc = asset.concept_by_id(r["id"])
        if cc is None or r["id"] in seen:
            continue
        seen.add(r["id"])
        mastery = _mastery_for(asset, learner_state, cc.name)
        out.append({"id": r["id"], "name": cc.name,
                    "label": r["label"] or _t("edge_related"),
                    "dir": r["dir"], "mastery": mastery})
    for cid in path_neighbors:
        if len(out) >= max_n:
            break
        cc = asset.concept_by_id(cid)
        if cc is None or cid in seen:
            continue
        seen.add(cid)
        out.append({"id": cid, "name": cc.name, "label": "", "dir": "path",
                    "mastery": _mastery_for(asset, learner_state, cc.name)})
    out.sort(key=lambda x: order.get(x["id"], 999))
    return out


def _mastery_for(asset: KnowledgeAsset, learner_state: dict | None, name: str) -> float:
    if not learner_state:
        return 0.0
    rec = next((v for v in learner_state.get("concepts", {}).values()
                if v.get("name") == name), None)
    return float(rec.get("mastery", 0.0)) if rec else 0.0


def compare_concepts(asset: KnowledgeAsset, id_a: str, id_b: str,
                     teacher=None, learner_state: dict | None = None) -> dict:
    """Structured comparison of two concepts → evidence points for the UI.

    Returns {a, b, similarity, shared_neighbors, rel_only_a, rel_only_b,
    chapter_same, mastery_diff, note_diff, points, learning_hint}.
    ``points`` is a list of human-readable, i18n-keyed strings; the UI renders
    them directly. ``learning_hint`` tells the learner which side to study
    first and what bridges the two.
    """
    ca = asset.concept_by_id(id_a)
    cb = asset.concept_by_id(id_b)
    if ca is None or cb is None or id_a == id_b:
        raise ValueError("compare_concepts needs two distinct existing concepts")

    def _text(c) -> str:
        return (c.definition or c.summary or "").strip()

    ta, tb = _text(ca), _text(cb)
    sim = difflib.SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0

    rel_a = {r["id"]: r for r in _rel_neighbors(asset, id_a)}
    rel_b = {r["id"]: r for r in _rel_neighbors(asset, id_b)}
    shared = sorted(set(rel_a) & set(rel_b),
                    key=lambda i: asset.concept_by_id(i).name if asset.concept_by_id(i) else i)
    only_a = [i for i in rel_a if i not in rel_b]
    only_b = [i for i in rel_b if i not in rel_a]

    def _rel_label(rel: dict) -> str:
        cc = asset.concept_by_id(rel["id"])
        arrow = "→" if rel["dir"] == "out" else "←"
        return f"{arrow} {rel['label'] or _t('edge_related')}　{cc.name if cc else rel['id']}"

    # teacher-note differences (only what each side uniquely claims)
    note_diff: dict = {"prereq_only_a": [], "prereq_only_b": [],
                       "miscon_only_a": [], "miscon_only_b": [],
                       "conn_only_a": [], "conn_only_b": []}
    if teacher is not None:
        na = teacher.concept_note_by_id(id_a)
        nb = teacher.concept_note_by_id(id_b)
        if na is not None and nb is not None:
            def _uniq(x, y): return [i for i in (x or []) if i not in (y or [])]
            note_diff["prereq_only_a"] = _uniq(na.prerequisites, nb.prerequisites)
            note_diff["prereq_only_b"] = _uniq(nb.prerequisites, na.prerequisites)
            note_diff["miscon_only_a"] = _uniq(na.misconceptions, nb.misconceptions)
            note_diff["miscon_only_b"] = _uniq(nb.misconceptions, na.misconceptions)
            note_diff["conn_only_a"] = _uniq(na.connections, nb.connections)
            note_diff["conn_only_b"] = _uniq(nb.connections, na.connections)

    chapter_same = bool(getattr(ca, "chapter", "") and
                        getattr(ca, "chapter", "") == getattr(cb, "chapter", ""))
    ma = _mastery_for(asset, learner_state, ca.name)
    mb = _mastery_for(asset, learner_state, cb.name)
    mastery_diff = round(mb - ma, 2)

    # ---- evidence points (the readable "information gain") -----------------
    points: list[str] = []
    if shared:
        names = "、".join(
            asset.concept_by_id(i).name if asset.concept_by_id(i) else i
            for i in shared[:5])
        points.append(_t("compare_shared", n=len(shared), names=names))
    for i in only_a[:4]:
        points.append(_t("compare_only_a", rel=_rel_label(rel_a[i])))
    for i in only_b[:4]:
        points.append(_t("compare_only_b", rel=_rel_label(rel_b[i])))
    if not chapter_same and getattr(ca, "chapter", "") and getattr(cb, "chapter", ""):
        points.append(_t("compare_chapter_diff",
                         a=ca.chapter, b=cb.chapter))
    for key, tmpl in (("prereq_only_a", "compare_prereq_only_a"),
                      ("prereq_only_b", "compare_prereq_only_b")):
        if note_diff[key]:
            points.append(_t(tmpl, names="；".join(note_diff[key][:3])))
    for key, tmpl in (("miscon_only_a", "compare_miscon_only_a"),
                      ("miscon_only_b", "compare_miscon_only_b")):
        if note_diff[key]:
            points.append(_t(tmpl, names="；".join(note_diff[key][:3])))
    if not points:
        points.append(_t("compare_no_points"))

    # ---- learning hint ------------------------------------------------------
    hint = ""
    if learner_state:
        low, high = (ca, cb) if ma <= mb else (cb, ca)
        if abs(ma - mb) >= 0.2:
            hint = _t("compare_hint_gap", name=low.name,
                      diff=f"{abs(ma - mb):.0%}")
        elif shared:
            hint = _t("compare_hint_shared", name=shared[0] and
                      (asset.concept_by_id(shared[0]).name if asset.concept_by_id(shared[0]) else ""))
    if not hint:
        hint = _t("compare_hint_default")

    return {
        "a": {"id": id_a, "name": ca.name,
              "chapter": getattr(ca, "chapter", ""),
              "definition": ta, "evidence_count": len(ca.evidence),
              "mastery": ma},
        "b": {"id": id_b, "name": cb.name,
              "chapter": getattr(cb, "chapter", ""),
              "definition": tb, "evidence_count": len(cb.evidence),
              "mastery": mb},
        "similarity": round(sim, 2),
        "shared_neighbors": [
            asset.concept_by_id(i).name if asset.concept_by_id(i) else i
            for i in shared],
        "rel_only_a": [_rel_label(rel_a[i]) for i in only_a],
        "rel_only_b": [_rel_label(rel_b[i]) for i in only_b],
        "chapter_same": chapter_same,
        "mastery_diff": mastery_diff,
        "note_diff": note_diff,
        "points": points,
        "learning_hint": hint,
    }
