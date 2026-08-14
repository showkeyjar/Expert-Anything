"""Core data models for ExpertAnything.

Every model is plain dataclass-based so it can round-trip to JSON for
local persistence. Source grounding is a first-class concern: a Concept
must carry the original text snippets that support it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


@dataclass
class Concept:
    id: str
    name: str
    definition: str = ""
    summary: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition,
            "summary": self.summary,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Concept":
        return cls(
            id=d.get("id", _new_id("c")),
            name=d["name"],
            definition=d.get("definition", ""),
            summary=d.get("summary", ""),
            evidence=d.get("evidence", []),
        )


@dataclass
class Relation:
    id: str
    source: str  # concept id
    target: str  # concept id
    label: str = ""
    type: str = "related"
    evidence: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "label": self.label,
            "type": self.type,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Relation":
        return cls(
            id=d.get("id", _new_id("r")),
            source=d["source"],
            target=d["target"],
            label=d.get("label", ""),
            type=d.get("type", "related"),
            evidence=d.get("evidence", ""),
        )


@dataclass
class Chapter:
    id: str
    title: str
    order: int = 0

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "order": self.order}

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        return cls(
            id=d.get("id", _new_id("ch")),
            title=d["title"],
            order=d.get("order", 0),
        )


@dataclass
class KnowledgeAsset:
    asset_id: str
    type: str
    title: str
    source_name: str
    created_at: str
    source_text: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    learning_path: list[str] = field(default_factory=list)
    method: str = "unknown"
    source_length: int = 0

    def concept_by_id(self, cid: str) -> Concept | None:
        return next((c for c in self.concepts if c.id == cid), None)

    def concept_by_name(self, name: str) -> Concept | None:
        n = name.strip().lower()
        return next((c for c in self.concepts if c.name.strip().lower() == n), None)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "type": self.type,
            "title": self.title,
            "source_name": self.source_name,
            "created_at": self.created_at,
            "source_text": self.source_text,
            "chapters": [c.to_dict() for c in self.chapters],
            "concepts": [c.to_dict() for c in self.concepts],
            "relations": [r.to_dict() for r in self.relations],
            "learning_path": self.learning_path,
            "method": self.method,
            "source_length": len(self.source_text),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeAsset":
        return cls(
            asset_id=d.get("asset_id", _new_id("a")),
            type=d.get("type", "text"),
            title=d["title"],
            source_name=d.get("source_name", ""),
            created_at=d.get("created_at", ""),
            source_text=d.get("source_text", ""),
            chapters=[Chapter.from_dict(c) for c in d.get("chapters", [])],
            concepts=[Concept.from_dict(c) for c in d.get("concepts", [])],
            relations=[Relation.from_dict(r) for r in d.get("relations", [])],
            learning_path=d.get("learning_path", []),
            method=d.get("method", "unknown"),
            source_length=d.get("source_length", len(d.get("source_text", ""))),
        )

    def public_dict(self) -> dict:
        """Like to_dict but omits the full source text (kept on disk only)."""
        d = self.to_dict()
        d.pop("source_text", None)
        return d
