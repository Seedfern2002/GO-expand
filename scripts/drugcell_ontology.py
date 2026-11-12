"""Prepare DrugCell's released pruned ontology and export additive overlays.

The original ontology bytes form the prefix of each exported ontology. GO
placements use compressed is_a paths to retained ancestors. Explicit placements
of external modules describe model aggregation and retain that distinction in
edge_provenance.jsonl.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_rows(path, rows):
    with Path(path).open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def read_gene_map(path):
    indexed, genes = {}, set()
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"Malformed gene map at line {number}")
        index, gene = int(fields[0]), fields[1]
        if index in indexed or gene in genes:
            raise ValueError("Gene map indices and identifiers must be unique")
        indexed[index] = gene
        genes.add(gene)
    if not indexed or set(indexed) != set(range(len(indexed))):
        raise ValueError("Gene indices must be contiguous and begin at zero")
    return [indexed[index] for index in range(len(indexed))]


def valid_model_term(term):
    # Upstream uses name.split('_')[0] to identify direct-gene masks. PyTorch
    # module names additionally exclude periods.
    return isinstance(term, str) and bool(term) and ":" in term and not any(
        char.isspace() or char in "_." for char in term
    )


def analyze(edges, memberships, genes, allow_empty_terms=False):
    """Validate the upstream hierarchy and calculate direct/propagated maps."""
    edges, memberships, genes = set(edges), set(memberships), list(genes)
    terms = {term for edge in edges for term in edge}
    if not terms or any(not valid_model_term(term) for term in terms):
        raise ValueError("Hierarchy requires compatible, namespaced term identifiers")
    if any(term not in terms or gene not in genes for term, gene in memberships):
        raise ValueError("Memberships require hierarchy terms and fixed-universe genes")
    children = {term: set() for term in terms}
    incoming = {term: 0 for term in terms}
    for parent, child in edges:
        children[parent].add(child)
        incoming[child] += 1
    roots = sorted(term for term, degree in incoming.items() if degree == 0)
    if len(roots) != 1:
        raise ValueError(f"Hierarchy requires one root; found {len(roots)}")
    pending, order = deque(roots), []
    while pending:
        parent = pending.popleft()
        order.append(parent)
        for child in sorted(children[parent]):
            incoming[child] -= 1
            if incoming[child] == 0:
                pending.append(child)
    if len(order) != len(terms):
        raise ValueError("Hierarchy contains a cycle or disconnected cyclic component")
    direct = {term: set() for term in terms}
    for term, gene in memberships:
        direct[term].add(gene)
    propagated = {term: set(values) for term, values in direct.items()}
    height = {}
    for term in reversed(order):
        for child in children[term]:
            propagated[term].update(propagated[child])
        if not propagated[term] and not allow_empty_terms:
            raise ValueError(f"Hierarchy term has no descendant genes: {term}")
        height[term] = 1 + max((height[child] for child in children[term]), default=0)
    gene_annotations = {gene: [] for gene in genes}
    gene_propagated = {gene: [] for gene in genes}
    for term in sorted(terms):
        for gene in direct[term]:
            gene_annotations[gene].append(term)
        for gene in propagated[term]:
            gene_propagated[gene].append(term)
    return {
        "terms": terms, "edges": edges, "memberships": memberships,
        "root": roots[0], "children": children, "direct": direct,
        "propagated": propagated, "order": order,
        "annotations": gene_annotations, "propagated_annotations": gene_propagated,
        "stats": {
            "genes": len(genes), "terms": len(terms), "hierarchy_edges": len(edges),
            "direct_memberships": len(memberships),
            "propagated_memberships": sum(map(len, propagated.values())),
            "annotated_genes": len({gene for _, gene in memberships}),
            "root": roots[0], "hierarchy_levels": height[roots[0]],
        },
    }


def read_ontology(path, genes, allow_empty_terms=False):
    rows, edges, memberships = set(), set(), set()
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        fields = tuple(line.split())
        if len(fields) != 3 or fields[2] not in {"default", "gene"}:
            raise ValueError(f"Malformed ontology row at line {number}")
        if fields in rows:
            raise ValueError(f"Duplicate ontology row at line {number}")
        rows.add(fields)
        (edges if fields[2] == "default" else memberships).add(fields[:2])
    return analyze(edges, memberships, genes, allow_empty_terms=allow_empty_terms)


def sources(**paths):
    return {name: {"path": str(Path(path).resolve()), "sha256": sha256(path)}
            for name, path in paths.items() if path is not None}


def prepare(ontology, gene_map, output):
    genes = read_gene_map(gene_map)
    baseline = read_ontology(ontology, genes)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "genes.json", {"genes": genes})
    write_json(output / "annotations.json", baseline["annotations"])
    write_json(output / "propagated_annotations.json", baseline["propagated_annotations"])
    with (output / "hierarchy.tsv").open("w") as stream:
        for parent, child in sorted(baseline["edges"]):
            stream.write(f"{parent}\t{child}\tdefault\n")
    (output / "drugcell_ont.txt").write_bytes(Path(ontology).read_bytes())
    manifest = {"status": "prepared", "basis": "released_pruned_ontology",
                "statistics": baseline["stats"], "sources": sources(ontology=ontology, gene_map=gene_map),
                "annotation_semantics": {
                    "annotations.json": "Direct gene memberships in the released ontology",
                    "propagated_annotations.json": "Direct memberships propagated through the released hierarchy",
                }}
    manifest["artifacts"] = {path.name: sha256(path) for path in sorted(output.iterdir())}
    write_json(output / "input_manifest.json", manifest)
    return manifest


def read_obo(path):
    terms, current = {}, None
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if line.startswith("["):
            current = {} if line == "[Term]" else None
        elif current is not None and ": " in line:
            key, value = line.split(": ", 1)
            if key == "id":
                if value in terms:
                    raise ValueError(f"Duplicate OBO term: {value}")
                current.update(id=value, parents=[], obsolete=False)
                terms[value] = current
            elif key == "is_a":
                current.setdefault("parents", []).append(value.split()[0])
            elif key == "namespace":
                current["namespace"] = value
            elif key == "is_obsolete":
                current["obsolete"] = value == "true"
    return terms


def retained_ancestor_paths(term, obo, retained):
    """Stop each is_a traversal branch at its first retained ancestor."""
    paths, pending, visited = {}, deque([(term, [term])]), {term}
    while pending:
        current, route = pending.popleft()
        for parent in sorted(obo.get(current, {}).get("parents", [])):
            if parent in route:
                raise ValueError("Cycle in OBO is_a ancestry")
            if parent in retained:
                paths.setdefault(parent, route + [parent])
            elif parent not in visited and not obo.get(parent, {}).get("obsolete", False):
                visited.add(parent)
                pending.append((parent, route + [parent]))
    return paths


def augment(ontology, gene_map, attributes, output, obo=None, parents=None):
    genes = read_gene_map(gene_map)
    gene_set = set(genes)
    baseline = read_ontology(ontology, genes)
    obo_terms = read_obo(obo) if obo else {}
    explicit = json.loads(Path(parents).read_text()) if parents else {}
    if not isinstance(explicit, dict):
        raise ValueError("Explicit parent mappings must be a JSON object")
    candidates, exclusions, seen_genes = set(), [], set()
    counts = Counter()
    for number, line in enumerate(Path(attributes).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        gene, terms = row.get("gene"), row.get("attributes")
        if not isinstance(gene, str) or not isinstance(terms, list) or any(not isinstance(t, str) for t in terms):
            raise ValueError(f"Malformed gene-attribute row at line {number}")
        if gene in seen_genes:
            raise ValueError(f"Repeated gene row: {gene}")
        seen_genes.add(gene)
        for term in terms:
            if gene not in gene_set:
                exclusions.append({"gene": gene, "term": term, "reason": "outside_gene_universe"})
            elif not valid_model_term(term):
                exclusions.append({"gene": gene, "term": term, "reason": "unsupported_model_identifier"})
            elif term in baseline["terms"] and gene in baseline["propagated"][term]:
                counts["already_implied_by_baseline"] += 1
            elif (term, gene) in candidates:
                counts["duplicate_input_memberships"] += 1
            else:
                candidates.add((term, gene))
    novel = {term for term, _ in candidates} - baseline["terms"]
    accepted_terms, rejected_terms, additions, provenance = set(), {}, set(), []
    eligible_go = {term for term in novel if term.startswith("GO:")
                   and obo_terms.get(term, {}).get("namespace") == "biological_process"
                   and not obo_terms[term].get("obsolete")
                   and retained_ancestor_paths(term, obo_terms, baseline["terms"])}
    for term in sorted(novel):
        if term.startswith("GO:"):
            details = obo_terms.get(term)
            if not details or details.get("obsolete") or details.get("namespace") != "biological_process":
                rejected_terms[term] = "new_term_requires_active_canonical_GO_BP"
                continue
            if term not in eligible_go:
                rejected_terms[term] = "no_retained_GO_is_a_ancestor"
                continue
            routes = retained_ancestor_paths(term, obo_terms, baseline["terms"] | eligible_go)
            for parent, route in sorted(routes.items()):
                additions.add((parent, term))
                provenance.append({"parent": parent, "child": term, "semantics": "compressed_GO_is_a_path",
                                   "child_to_ancestor_path": route})
        else:
            mapping = explicit.get(term)
            if not isinstance(mapping, list) or not mapping:
                rejected_terms[term] = "external_term_requires_explicit_parent_mapping"
                continue
            if any(not valid_model_term(parent) for parent in mapping):
                raise ValueError(f"Invalid explicit parent for {term}")
            for parent in sorted(set(mapping)):
                additions.add((parent, term))
                provenance.append({"parent": parent, "child": term, "semantics": "explicit_model_aggregation",
                                   "mapping_file_sha256": sha256(parents)})
        accepted_terms.add(term)
    for term, gene in sorted(candidates):
        if term in rejected_terms:
            exclusions.append({"gene": gene, "term": term, "reason": rejected_terms[term]})
    candidates = {(term, gene) for term, gene in candidates if term not in rejected_terms}
    known_terms = baseline["terms"] | accepted_terms
    if any(parent not in known_terms for parent, _ in additions):
        raise ValueError("Explicit parents must belong to the baseline or accepted new terms")
    combined_edges = baseline["edges"] | additions
    combined = analyze(combined_edges, baseline["memberships"] | candidates, genes)
    # Keep only new direct memberships that contribute beyond child membership.
    # Baseline rows remain immutable even when an added child implies them.
    minimal = set()
    for term, gene in sorted(candidates):
        if any(gene in combined["propagated"][child] for child in combined["children"][term]):
            counts["implied_by_child_memberships"] += 1
        else:
            minimal.add((term, gene))
    final = analyze(combined_edges, baseline["memberships"] | minimal, genes)
    if final["propagated"] != combined["propagated"]:
        raise AssertionError("Direct-membership reduction changed ontology closure")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = Path(ontology).read_bytes()
    with (output / "drugcell_ont.txt").open("wb") as stream:
        stream.write(original)
        if (additions or minimal) and original and not original.endswith(b"\n"):
            stream.write(b"\n")
        for parent, child in sorted(additions):
            stream.write(f"{parent}\t{child}\tdefault\n".encode())
        for term, gene in sorted(minimal):
            stream.write(f"{term}\t{gene}\tgene\n".encode())
    write_json(output / "genes.json", {"genes": genes})
    write_json(output / "annotations.json", final["annotations"])
    write_json(output / "propagated_annotations.json", final["propagated_annotations"])
    write_rows(output / "edge_provenance.jsonl", provenance)
    write_rows(output / "projection_exclusions.jsonl", exclusions)
    counts.update({"added_terms": len(accepted_terms), "added_hierarchy_edges": len(additions),
                   "added_direct_memberships": len(minimal), "excluded_memberships": len(exclusions),
                   "new_propagated_memberships": final["stats"]["propagated_memberships"] - baseline["stats"]["propagated_memberships"]})
    report = {"status": "exported", "baseline_statistics": baseline["stats"],
              "statistics": final["stats"], "projection_counts": dict(counts),
              "exclusion_reasons": dict(Counter(row["reason"] for row in exclusions)),
              "sources": sources(ontology=ontology, gene_map=gene_map, attributes=attributes, obo=obo, parents=parents),
              "baseline_bytes_preserved": (output / "drugcell_ont.txt").read_bytes().startswith(original),
              "hierarchy_policy": "Preserve released hierarchy; add GO is_a ancestor placements and explicit external-module aggregation placements",
              "artifacts": {path.name: sha256(path) for path in sorted(output.iterdir())}}
    write_json(output / "projection_manifest.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "augment"):
        child = sub.add_parser(action)
        child.add_argument("--ontology", type=Path, required=True)
        child.add_argument("--gene-map", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
        if action == "augment":
            child.add_argument("--attributes", type=Path, required=True)
            child.add_argument("--obo", type=Path)
            child.add_argument("--parents", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.ontology, args.gene_map, args.output)
    else:
        result = augment(args.ontology, args.gene_map, args.attributes, args.output, args.obo, args.parents)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
