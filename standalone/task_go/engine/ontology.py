"""Read the OBO subset needed for exploration; this is not an OWL reasoner."""

from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from pathlib import Path

PROPAGATION_RELATIONS = frozenset({"is_a", "part_of"})


def open_text(path: str | Path):
    path = Path(path)
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8")


@dataclass
class Term:
    id: str
    name: str = ""
    namespace: str = ""
    definition: str = ""
    alt_ids: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    obsolete: bool = False
    replaced_by: list[str] = field(default_factory=list)
    consider: list[str] = field(default_factory=list)


@dataclass
class Ontology:
    terms: dict[str, Term]
    metadata: dict[str, list[str]]

    @classmethod
    def read(cls, path: str | Path) -> Ontology:
        terms: dict[str, Term] = {}
        metadata: dict[str, list[str]] = {}
        stanza = "header"
        current: Term | None = None
        with open_text(path) as handle:
            for number, raw in enumerate(handle, 1):
                line = raw.strip()
                if not line or line.startswith("!"):
                    continue
                if line.startswith("["):
                    stanza = line
                    current = None
                    continue
                if ": " not in line:
                    continue
                key, value = line.split(": ", 1)
                if stanza == "header":
                    metadata.setdefault(key, []).append(value)
                elif stanza == "[Term]":
                    if key == "id":
                        if value in terms:
                            raise ValueError(f"Line {number}: duplicate term {value}")
                        current = Term(value)
                        terms[value] = current
                    elif current is None:
                        raise ValueError(f"Line {number}: term field before id")
                    elif key in {"name", "namespace"}:
                        setattr(current, key, value)
                    elif key == "def":
                        current.definition = value
                    elif key == "alt_id":
                        current.alt_ids.append(value)
                    elif key == "is_a":
                        current.edges.append(("is_a", value.split()[0]))
                    elif key == "relationship":
                        relation, target, *_ = value.split()
                        current.edges.append((relation, target))
                    elif key == "is_obsolete":
                        current.obsolete = value == "true"
                    elif key in {"replaced_by", "consider"}:
                        getattr(current, key).append(value.split()[0])
        return cls(terms, metadata)

    def resolve(self, term_id: str) -> Term:
        if term_id in self.terms:
            return self.terms[term_id]
        for term in self.terms.values():
            if term_id in term.alt_ids:
                return term
        raise KeyError(f"Unknown term: {term_id}")

    def ancestors(self, term_id: str, relations=PROPAGATION_RELATIONS) -> set[str]:
        """Return reachable active terms, excluding self, along selected relations.

        Default edges support positive annotation grouping. Traversing other edge
        types is structural exploration, not a claim of annotation entailment.
        """
        origin = self.resolve(term_id)
        if origin.obsolete:
            raise ValueError(f"Obsolete term {origin.id}; review replaced_by/consider")
        seen = {origin.id}
        pending = [origin]
        while pending:
            for relation, target in pending.pop().edges:
                if relation not in relations:
                    continue
                parent = self.resolve(target)
                if parent.obsolete:
                    raise ValueError(f"Edge to obsolete term: {parent.id}")
                if parent.id not in seen:
                    seen.add(parent.id)
                    pending.append(parent)
        return seen - {origin.id}

    def closure(self, term_ids, exclude=()) -> set[str]:
        """Positive annotation term-set closure through is_a and part_of only."""
        expanded: set[str] = set()
        for term_id in term_ids:
            term = self.resolve(term_id)
            expanded.add(term.id)
            expanded.update(self.ancestors(term.id))
        return expanded - set(exclude)


def jaccard(left: set[str], right: set[str]) -> float | None:
    """Undefined for two empty sets: missing knowledge is not perfect similarity."""
    union = left | right
    return len(left & right) / len(union) if union else None
