"""Scene-quality benchmark: curated domain scenes vs the no-LLM fallback.

The decoder ships two scene paths:

* **curated** — domain-specific ``SceneSpec`` generators in
  ``decoder_<domain>.py`` (electricity / carbon / renewable), built from a
  pre-curated template so a well-understood domain skips first-pass extraction.
* **fallback** — ``decoder.fallback_scene``, a deterministic graph built purely
  from the concept's own definition + evidence + relations, with no LLM.

This module *quantifies* the difference on objective, source-constrained
dimensions so we can answer "does the curated template actually produce richer
scenes?" with data instead of intuition. It is pure-stdlib, offline, and fully
deterministic — no network, no LLM, no randomness.

Dimensions scored (weights are transparent, see ``_W``):

* ``node_count`` / ``edge_count`` — structural richness (capped by MAX_NODES).
* ``typed_edge_count`` — edges carrying a semantic relation type (is_a / part_of
  / causes / prereq / contrast / related). Curated scenes tend to be richer.
* ``step_count`` — animation timeline length (the "see" layer).
* ``has_game`` — interactive sort-game present (the "play" layer).
* ``source_overlap`` — char-bigram precision of the scene text against the
  concept's *own* extracted definition/evidence/summary. Literal grounding.
* ``relation_anchored`` — the scene text references a relation neighbour's name.
* ``structure_score`` — weighted sum of the above *excluding* source_overlap.
* ``total`` — ``structure_score`` + ``_W['source'] * source_overlap``.

The benchmark is deliberately non-partisan: curated scenes usually win on
structure, while the fallback often wins on literal ``source_overlap`` (it is
built *from* the source). That trade-off is exactly the signal worth surfacing.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable

from expert_anything.core.decoder import fallback_scene, scene_for_concept, REL_SEMANTICS
from expert_anything.core.domain_templates import DOMAIN_TEMPLATES, detect_domain_from_title
from expert_anything.core.models import Concept, KnowledgeAsset, Relation

_REL_TYPES = set(REL_SEMANTICS)  # six semantic relation types

# Transparent, fixed scoring weights.
_W = {
    "node": 1.0,
    "edge": 0.4,
    "typed": 0.6,   # a semantically-typed edge (is_a / part_of / causes / ...)
    "step": 0.7,
    "game": 1.0,
    "rel_anchor": 0.5,
    "source": 2.0,  # literal grounding in the extracted knowledge
}


@dataclass
class SceneScore:
    """Objective quality score for one rendered SceneSpec."""

    path: str  # 'curated' | 'fallback'
    node_count: int = 0
    edge_count: int = 0
    typed_edge_count: int = 0
    step_count: int = 0
    has_game: bool = False
    source_overlap: float = 0.0   # 0..1, char-bigram precision vs source
    relation_anchored: bool = False
    structure_score: float = 0.0  # weighted, excludes source_overlap
    total: float = 0.0


def _scene_text(spec: dict) -> str:
    parts = [n.get("label", "") for n in spec.get("nodes", [])]
    parts += [s.get("caption", "") for s in spec.get("steps", [])]
    parts += [e.get("label", "") for e in spec.get("edges", [])]
    return " ".join(p for p in parts if p)


def _source_text(concept: Concept) -> str:
    return " ".join([
        concept.definition or "",
        " ".join(concept.evidence or []),
        concept.summary or "",
    ])


def _bigrams(s: str) -> set[str]:
    s = "".join(ch for ch in s if not ch.isspace())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else set()


def _source_overlap(spec: dict, concept: Concept) -> float:
    """Char-bigram precision of the scene text w.r.t. the concept's source."""
    scene_b = _bigrams(_scene_text(spec))
    src_b = _bigrams(_source_text(concept))
    if not scene_b or not src_b:
        return 0.0
    inter = scene_b & src_b
    return len(inter) / len(scene_b)


def _relation_neighbor_names(asset: KnowledgeAsset, concept: Concept) -> set[str]:
    names: set[str] = set()
    for r in (asset.relations or []):
        other_id = r.target if r.source == concept.id else (r.source if r.target == concept.id else None)
        if other_id:
            c = asset.concept_by_id(other_id)
            if c:
                names.add(c.name)
    return names


def score_scene(spec: dict, concept: Concept, asset: KnowledgeAsset, path: str) -> SceneScore:
    """Score one SceneSpec against the concept's extracted source."""
    nodes = spec.get("nodes", []) or []
    edges = spec.get("edges", []) or []
    steps = spec.get("steps", []) or []
    typed = sum(1 for e in edges if e.get("type") in _REL_TYPES and e.get("type"))
    overlap = _source_overlap(spec, concept)
    neighbors = _relation_neighbor_names(asset, concept)
    scene_txt = _scene_text(spec)
    rel_anchored = any(n in scene_txt for n in neighbors) if neighbors else False
    structure = (
        _W["node"] * len(nodes)
        + _W["edge"] * len(edges)
        + _W["typed"] * typed
        + _W["step"] * len(steps)
        + (_W["game"] if spec.get("game") else 0.0)
        + (_W["rel_anchor"] if rel_anchored else 0.0)
    )
    total = structure + _W["source"] * overlap
    return SceneScore(
        path=path,
        node_count=len(nodes),
        edge_count=len(edges),
        typed_edge_count=typed,
        step_count=len(steps),
        has_game=bool(spec.get("game")),
        source_overlap=round(overlap, 4),
        relation_anchored=rel_anchored,
        structure_score=round(structure, 3),
        total=round(total, 3),
    )


def build_toy_asset(domain_id: str) -> KnowledgeAsset:
    """Synthesize a structurally-valid asset from a domain template (offline).

    The result is *not* a substitute for a real extracted book — it exists so
    the benchmark can run end-to-end with zero input. Concept ids match the
    template (``et-*`` etc.) and relations are reconstructed from the template's
    ``prerequisites`` / ``connections`` keys, so both the curated and fallback
    paths resolve cleanly.
    """
    template = DOMAIN_TEMPLATES.get(domain_id)
    if not template:
        raise ValueError(f"unknown domain: {domain_id}")
    concepts: list[Concept] = []
    relations: list[Relation] = []
    for ch in template.chapters:
        for c in ch.get("concepts", []):
            cid = c["id"]
            concepts.append(Concept(
                id=cid,
                name=c["name"],
                definition=c.get("definition", ""),
                summary=c.get("significance", ""),
                evidence=list(c.get("evidence", [])),
            ))
            for p in c.get("prerequisites", []) or []:
                relations.append(Relation(
                    id=f"{cid}->{p}", source=cid, target=p, type="prereq", label="前提"))
            for conn in c.get("connections", []) or []:
                relations.append(Relation(
                    id=f"{cid}->{conn}", source=cid, target=conn, type="related", label="关联"))
    return KnowledgeAsset(
        asset_id=domain_id,
        type="text",
        title=template.name,
        source_name=template.name,
        created_at="benchmark",
        source_text="",
        concepts=concepts,
        relations=relations,
    )


@dataclass
class ConceptComparison:
    concept_name: str
    curated: SceneScore
    fallback: SceneScore


@dataclass
class BenchmarkReport:
    domain_id: str
    n_concepts: int
    comparisons: list[ConceptComparison] = field(default_factory=list)
    averages: dict = field(default_factory=dict)
    wins: dict = field(default_factory=dict)   # dim -> [curated_wins, fallback_wins, ties]
    summary: str = ""

    def __str__(self) -> str:
        return _format_report(self)


def compare_for_asset(asset: KnowledgeAsset, domain: str | None = None) -> list[ConceptComparison]:
    """Score curated vs fallback for every concept in ``asset``."""
    if domain is None:
        domain = detect_domain_from_title(getattr(asset, "title", "") or "")
    if not domain or domain not in DOMAIN_TEMPLATES:
        return []
    out: list[ConceptComparison] = []
    for concept in asset.concepts:
        curated = scene_for_concept(asset, concept, domain=domain)
        fallback = fallback_scene(asset, concept)
        out.append(ConceptComparison(
            concept_name=concept.name,
            curated=score_scene(curated, concept, asset, "curated"),
            fallback=score_scene(fallback, concept, asset, "fallback"),
        ))
    return out


def run_domain_benchmark(domain_id: str) -> BenchmarkReport:
    return _aggregate(domain_id, compare_for_asset(build_toy_asset(domain_id), domain=domain_id))


def run_scene_benchmark(domain_ids: Iterable[str] | None = None) -> list[BenchmarkReport]:
    if domain_ids is None:
        domain_ids = list(DOMAIN_TEMPLATES)
    return [run_domain_benchmark(d) for d in domain_ids]


def _aggregate(domain_id: str, comps: list[ConceptComparison]) -> BenchmarkReport:
    dims = ["node_count", "edge_count", "typed_edge_count", "step_count",
            "source_overlap", "structure_score", "total"]
    avgs: dict = {}
    wins = {d: [0, 0, 0] for d in dims}  # [curated_wins, fallback_wins, ties]
    for d in dims:
        cv = [getattr(c.curated, d) for c in comps]
        fv = [getattr(c.fallback, d) for c in comps]
        avgs[f"curated_{d}"] = round(statistics.mean(cv), 3) if cv else 0.0
        avgs[f"fallback_{d}"] = round(statistics.mean(fv), 3) if fv else 0.0
        for a, b in zip(cv, fv):
            if a > b:
                wins[d][0] += 1
            elif b > a:
                wins[d][1] += 1
            else:
                wins[d][2] += 1
    # cross-dimension gains for quick reading
    avgs["gain_structure"] = round(avgs["curated_structure_score"] - avgs["fallback_structure_score"], 3)
    avgs["gain_source"] = round(avgs["curated_source_overlap"] - avgs["fallback_source_overlap"], 3)
    report = BenchmarkReport(domain_id=domain_id, n_concepts=len(comps),
                             comparisons=comps, averages=avgs, wins=wins)
    report.summary = _summarize(report)
    return report


def _summarize(r: BenchmarkReport) -> str:
    a = r.averages
    return (
        f"{r.domain_id}: {r.n_concepts} concepts | "
        f"structure {a['curated_structure_score']} vs {a['fallback_structure_score']} "
        f"(Δ{a['gain_structure']:+}) | "
        f"source-overlap {a['curated_source_overlap']} vs {a['fallback_source_overlap']} "
        f"(Δ{a['gain_source']:+})"
    )


def _format_report(r: BenchmarkReport) -> str:
    a = r.averages
    lines = [f"=== {r.domain_id} ({r.n_concepts} concepts) ===", r.summary, ""]
    lines.append(f"{'dim':<16}{'curated':>10}{'fallback':>10}{'curW':>8}{'fallW':>7}{'tie':>6}")
    for d in ["node_count", "edge_count", "typed_edge_count", "step_count",
             "source_overlap", "structure_score", "total"]:
        w = r.wins[d]
        lines.append(f"{d:<16}{a[f'curated_{d}']:>10}{a[f'fallback_{d}']:>10}{w[0]:>8}{w[1]:>7}{w[2]:>6}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    requested = sys.argv[1:] or list(DOMAIN_TEMPLATES)
    reports = run_scene_benchmark(requested)
    for rep in reports:
        print(rep)
    print("--- cross-domain ---")
    for rep in reports:
        print(rep.summary)
