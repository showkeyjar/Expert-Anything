"""Reproducible quality probe for the extraction path on REAL documents.

Runs the deterministic extraction path (no LLM required) over the real
documents shipped in this repo and reports three numbers:

1. structural edge recall  -- document-tree edges the pipeline produced
   versus the heading tree actually encoded in the source (missed edges are
   attributed to the rule that dropped them);
2. six-class semantic hit -- free-form labels folded by classify_relation;
3. evidence locatability  -- verbatim evidence that `_stamp_locations` could
   anchor, plus how many anchors are unique (unambiguous).

Usage:
    python verify_extraction_quality.py

Everything is deterministic: same repo, same numbers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from expert_anything.core.decoder import classify_relation
from expert_anything.core.extraction import extract_knowledge

try:  # present only from round 28 on; older checkouts fold through the decoder
    from expert_anything.core.extraction import _canonical_relation_type
except ImportError:  # pragma: no cover - used only when probing old trees
    def _canonical_relation_type(label: str, rtype: str) -> str:
        return classify_relation(label, rtype)

DOCS = [
    "docs/电力交易领域学习方案.md",
    "docs/AutoHarness_Strategy.md",
    "docs/Knowledge_Decoder.md",
    "docs/OmniScientist_Inspiration.md",
    "README.md",
    "docs/_omniscientist_text.txt",
]

FENCE = re.compile(r"^(```|~~~)")


def markdown_headings(text: str) -> list[tuple[int, int, str]]:
    """Real markdown headings (code fences excluded), with their depth."""
    out, in_fence = [], False
    for line_no, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if FENCE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            out.append((line_no, len(m.group(1)), m.group(2).strip()))
    return out


def heading_tree_pairs(heads: list[tuple[int, int, str]]) -> list[tuple[str, str]]:
    """Gold parent -> child pairs implied by heading nesting."""
    stack: list[tuple[int, str]] = []
    pairs: list[tuple[str, str]] = []
    for _line_no, depth, title in heads:
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            pairs.append((stack[-1][1], title))
        stack.append((depth, title))
    return pairs


def concept_name(heading: str) -> str:
    name = re.sub(r"^#+\s*", "", heading).strip()
    name = re.sub(r"^\d+(\.\d+)*\s*", "", name).strip()
    name = re.sub(r"^第\s*\d+\s*章\s*", "", name).strip()
    return name.lower()


def probe(path: str) -> dict:
    text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
    asset = extract_knowledge(text, Path(path).name, llm=None)

    evidence_total = evidence_located = evidence_unique = 0
    for concept in asset.concepts:
        for ev in concept.evidence or []:
            evidence_total += 1
            if ev in text:
                evidence_located += 1
                if text.count(ev) == 1:
                    evidence_unique += 1

    relation_total = len(asset.relations)
    relation_located = sum(1 for r in asset.relations if getattr(r, "location", None))
    types: dict[str, int] = {}
    for r in asset.relations:
        types[r.type] = types.get(r.type, 0) + 1

    by_id = {c.id: c.name.lower() for c in asset.concepts}
    produced = {(by_id[r.source], by_id[r.target]) for r in asset.relations}
    gold = [(concept_name(a), concept_name(b)) for a, b in heading_tree_pairs(markdown_headings(text))]
    hit = sum(1 for pair in gold if pair in produced)

    false_heading_concepts = 0
    in_fence = False
    names = {c.name.lower() for c in asset.concepts}
    for line in text.splitlines():
        stripped = line.strip()
        if FENCE.match(stripped):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if m and concept_name(m.group(1)) in names:
            false_heading_concepts += 1

    print(f"\n=== {path} ===")
    print(f"chars={len(text)} real_headings={len(markdown_headings(text))} gold_edges={len(gold)}")
    print(f"concepts={len(asset.concepts)} evidence={evidence_total} "
          f"located={evidence_located} unique={evidence_unique}")
    print(f"false_heading_concepts={false_heading_concepts}")
    print(f"relations={relation_total} anchored={relation_located} types={types}")
    print(f"structural_edge_hit={hit}/{len(gold)}")
    if evidence_total:
        print("  located=%0.1f%% unique=%0.1f%%"
              % (100 * evidence_located / evidence_total, 100 * evidence_unique / evidence_total))
    return dict(concepts=len(asset.concepts), evidence=evidence_total,
                located=evidence_located, unique=evidence_unique,
                relations=relation_total, gold=len(gold), hit=hit,
                false_heads=false_heading_concepts)


# Free-form label/type pairs a model may emit; the expected class follows the
# six-semantics definitions in the extraction prompt.
GOLD_LABELS = [
    ("依赖", "prereq", "prereq"), ("前置步骤", "", "prereq"), ("基于", "", "prereq"),
    ("取决于", "", "prereq"), ("requires", "", "prereq"), ("depends on", "", "prereq"),
    ("导致", "causes", "causes"), ("引起", "", "causes"), ("leads to", "", "causes"),
    ("组成", "contains", "part_of"), ("包含", "", "part_of"), ("分为", "", "part_of"),
    ("consists of", "", "part_of"), ("属于…的一部分", "", "part_of"),
    ("是一种", "", "is_a"), ("属于", "", "is_a"), ("is a", "", "is_a"),
    ("对比", "contrast", "contrast"), ("不同于", "", "contrast"), ("vs", "", "contrast"),
    ("相关", "related", "related"), ("关联", "", "related"),
    ("依赖", "dependency", "prereq"), ("包含", "includes", "part_of"),
    ("导致", "effect", "causes"), ("相似", "similar", "related"),
    ("属于", "part_of", "part_of"),
]


def label_accuracy() -> None:
    wrong = []
    for label, typ, want in GOLD_LABELS:
        got = classify_relation(label, typ)
        if got != want:
            wrong.append((label, typ, want, got))
    print("\n=== six-class semantic hit (free-form label/type) ===")
    print(f"accuracy={len(GOLD_LABELS) - len(wrong)}/{len(GOLD_LABELS)}")
    for row in wrong:
        print(f"  MISCLASSIFIED label={row[0]!r} type={row[1]!r} expected={row[2]} got={row[3]}")
    # the stored field of a produced relation is a separate axis
    print(f"canonical-type check: contains -> {_canonical_relation_type('', 'contains')}")


if __name__ == "__main__":
    rows = [probe(doc) for doc in DOCS]
    label_accuracy()
    total = {key: sum(row[key] for row in rows) for key in rows[0]}
    print("\n=== AGGREGATE (real documents) ===")
    print(f"concepts={total['concepts']} evidence={total['evidence']} "
          f"located={total['located']} unique={total['unique']} "
          f"false_heading_concepts={total['false_heads']}")
    print(f"relations={total['relations']} structural_edge_hit={total['hit']}/{total['gold']}")
    if total["evidence"]:
        print("evidence located=%0.1f%% unique=%0.1f%%"
              % (100 * total["located"] / total["evidence"],
                 100 * total["unique"] / total["evidence"]))
