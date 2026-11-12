"""Prune a frozen DrugCell hierarchy using the published size/separation rules.

The deterministic reconstruction visits children before parents, contracts
removed nodes, and preserves propagated gene membership at every retained node.
Root connectivity and the declared gene universe are retained. Source artifacts
remain unchanged. The implementation choices are recorded with the product.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import drugcell_ontology as ontology


PAPER = "https://pmc.ncbi.nlm.nih.gov/articles/PMC7737474/"


def prune_graph(graph, genes, min_genes=10, min_difference=30, max_edges=5):
    if min(min_genes, max_edges) < 1 or min_difference < 0:
        raise ValueError("Size and depth must be positive; separation must be nonnegative")
    root = graph["root"]
    children = {term: set(values) for term, values in graph["children"].items()}
    parents = {term: set() for term in graph["terms"]}
    for parent, child in graph["edges"]:
        parents[child].add(parent)
    removed, lineage = {}, []

    def contract(term, reason):
        lineage.append({"term": term, "reason": reason,
                        "propagated_genes": len(graph["propagated"][term]),
                        "parents_at_removal": sorted(parents[term]),
                        "children_at_removal": sorted(children[term])})
        for parent in parents[term]:
            children[parent].remove(term)
            children[parent].update(children[term])
        for child in children[term]:
            parents[child].remove(term)
            parents[child].update(parents[term])
        removed[term] = reason

    for term in reversed(graph["order"]):
        if term == root:
            continue
        if len(graph["propagated"][term]) < min_genes:
            contract(term, "fewer_than_minimum_genes")
        elif any(len(graph["propagated"][term] - graph["propagated"][child]) < min_difference
                 for child in children[term]):
            contract(term, "insufficient_parent_child_gene_difference")

    heights = {}
    for term in reversed(graph["order"]):
        if term not in removed:
            heights[term] = max((heights[child] + 1 for child in children[term]), default=0)
    # The persistent common root uses one edge above the highest retained layer.
    # Limit the complete exported root-to-leaf path to max_edges.
    for term in graph["order"]:
        if term != root and term not in removed and heights[term] >= max_edges:
            contract(term, "exceeds_depth_cap_below_common_root")
    retained = graph["terms"] - removed.keys()
    edges = {(term, child) for term in retained for child in children[term]}
    if not edges:
        raise ValueError("Pruning leaves a root-only graph; the upstream loader requires hierarchy edges")
    memberships, recovered = set(), set()
    for term in retained:
        inherited = set().union(*(graph["propagated"][child] for child in children[term]))
        direct = graph["direct"][term] | (graph["propagated"][term] - inherited)
        memberships.update((term, gene) for gene in direct)
        recovered.update((term, gene) for gene in direct - graph["direct"][term])
    final = ontology.analyze(edges, memberships, genes)
    for term in retained:
        if final["propagated"][term] != graph["propagated"][term]:
            raise AssertionError("Contraction changed retained functional gene coverage")
        if term != root and len(final["propagated"][term]) < min_genes:
            raise AssertionError("Retained term violates size threshold")
        if term != root and any(len(final["propagated"][term] - final["propagated"][child]) < min_difference
                                for child in final["children"][term]):
            raise AssertionError("Retained term violates separation threshold")
    if final["stats"]["hierarchy_levels"] - 1 > max_edges:
        raise AssertionError("Export exceeds root-to-leaf edge cap")
    return final, {"removed": lineage, "removed_by_reason": dict(Counter(removed.values())),
                   "recovered_direct_memberships": sorted(recovered)}


def prune(ontology_path, gene_map, output, min_genes=10, min_difference=30, max_edges=5):
    ontology_path, gene_map, output = Path(ontology_path).resolve(), Path(gene_map).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new pruning product directory")
    genes = ontology.read_gene_map(gene_map)
    source = ontology.read_ontology(ontology_path, genes, allow_empty_terms=True)
    final, audit = prune_graph(source, genes, min_genes, min_difference, max_edges)
    output.mkdir(parents=True)
    with (output / "drugcell_ont.txt").open("w") as stream:
        for parent, child in sorted(final["edges"]):
            stream.write(f"{parent}\t{child}\tdefault\n")
        for term, gene in sorted(final["memberships"]):
            stream.write(f"{term}\t{gene}\tgene\n")
    ontology.write_json(output / "annotations.json", final["annotations"])
    ontology.write_json(output / "propagated_annotations.json", final["propagated_annotations"])
    ontology.write_json(output / "genes.json", {"genes": genes})
    ontology.write_rows(output / "removed_nodes.jsonl", audit["removed"])
    ontology.write_rows(output / "recovered_memberships.jsonl", (
        {"term": term, "gene": gene, "semantics": "coverage_recovered_after_node_contraction"}
        for term, gene in audit["recovered_direct_memberships"]))
    ontology.write_rows(output / "contracted_edges.jsonl", (
        {"parent": parent, "child": child,
         "semantics": "preserved_input_edge" if (parent, child) in source["edges"] else "contracted_input_ancestry"}
        for parent, child in sorted(final["edges"])))
    manifest = {
        "status": "pruned", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "paper": PAPER, "implementation": "deterministic reconstruction of published pruning rules",
        "policy": {"min_genes": min_genes, "min_parent_child_gene_difference": min_difference,
                   "max_root_to_leaf_edges": max_edges, "decision_order": "bottom-up on contracted children",
                   "root_policy": "retain original common root",
                   "gene_memberships": "preserve direct inputs at retained nodes; recover uncovered genes after contraction",
                   "edge_scope": "all typed relationships already present in the frozen exported hierarchy",
                   "external_modules": "apply the same size and separation thresholds",
                   "knowledge_selection_inputs": "frozen ontology and fixed gene universe"},
        "input_statistics": source["stats"], "statistics": final["stats"],
        "removed_by_reason": audit["removed_by_reason"],
        "removed_terms": len(source["terms"] - final["terms"]),
        "retained_gene_coverage_exact": True,
        "recovered_direct_memberships": len(audit["recovered_direct_memberships"]),
        "sources": ontology.sources(ontology=ontology_path, gene_map=gene_map),
        "script_sha256": ontology.sha256(Path(__file__)),
        "artifacts": {path.name: ontology.sha256(path) for path in sorted(output.iterdir()) if path.is_file()},
    }
    ontology.write_json(output / "pruning_manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--gene-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-genes", type=int, default=10)
    parser.add_argument("--min-difference", type=int, default=30)
    parser.add_argument("--max-edges", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(prune(args.ontology, args.gene_map, args.output,
                           args.min_genes, args.min_difference, args.max_edges), indent=2))


if __name__ == "__main__":
    main()
