#!/usr/bin/env python3
"""Export GEARS gene/condition metadata and GO sets without reading expression values."""

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import h5py


def strings(values):
    return [value.decode() if isinstance(value, bytes) else str(value) for value in values]


def column_values(group, key):
    column = group[key]
    if isinstance(column, h5py.Group):
        categories = strings(column["categories"][:])
        codes = column["codes"][:]
    elif "__categories" in group and key in group["__categories"]:
        categories = strings(group["__categories"][key][:])
        codes = column[:]
    else:
        return strings(column[:])
    return [categories[int(code)] for code in codes if code >= 0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h5ad", type=Path, default=Path("data/raw/gears/norman/perturb_processed.h5ad"))
    parser.add_argument("--gene2go", type=Path, default=Path("data/raw/gears/gene2go_all.pkl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; choose a new metadata snapshot path")
    with h5py.File(args.h5ad, "r") as data:
        conditions = sorted(set(column_values(data["obs"], "condition")))
        genes = column_values(data["var"], "gene_name")
    raw_annotations = args.gene2go.read_bytes()
    gene2go = pickle.loads(raw_annotations)
    raw_targets = {gene for condition in conditions for gene in condition.split("+") if gene != "ctrl"}
    graph_genes = sorted((set(genes) | raw_targets) & set(gene2go))
    graph_set = set(graph_genes)
    eligible = [condition for condition in conditions if all(gene == "ctrl" or gene in graph_set for gene in condition.split("+"))]
    targets = sorted({gene for condition in eligible for gene in condition.split("+") if gene != "ctrl"})
    metadata = {
        "description": "GEARS gene/condition metadata only; no expression values or split assignments.",
        "input_accessed": ["obs/condition with categorical metadata", "var/gene_name with categorical metadata", "gene2go_all.pkl"],
        "h5ad_source": str(args.h5ad), "annotation_source": str(args.gene2go),
        "annotation_sha256": hashlib.sha256(raw_annotations).hexdigest(),
        "graph_definition": "unique(var gene symbols + perturbation target symbols) intersect keys(gene2go), matching default_pert_graph=False",
        "raw_condition_count": len(conditions), "eligible_condition_count": len(eligible),
        "excluded_conditions": sorted(set(conditions) - set(eligible)),
        "perturbation_targets": targets, "graph_genes": graph_genes,
        "original_gene2go_for_targets": {gene: sorted(gene2go[gene]) for gene in targets},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"conditions": len(eligible), "targets": len(targets), "graph_genes": len(graph_genes), "output": str(args.output)}))


if __name__ == "__main__":
    main()
