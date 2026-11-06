#!/usr/bin/env python3
"""Compare GEARS top-k neighborhoods before and after approved attribute union."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import time

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

import numpy as np
import pandas as pd
from scipy import sparse
import torch


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidate_edges(genes, annotations, threshold):
    vocabulary = {term: index for index, term in enumerate(sorted(set().union(*annotations)))}
    row, column = [], []
    for index, terms in enumerate(annotations):
        row.extend([index] * len(terms))
        column.extend(vocabulary[term] for term in terms)
    matrix = sparse.csr_matrix((np.ones(len(row), dtype=np.int32), (row, column)), shape=(len(genes), len(vocabulary)))
    intersections = (matrix @ matrix.T).toarray()
    sizes = np.asarray(matrix.sum(axis=1)).ravel().astype(np.int32)
    unions = sizes[:, None] + sizes[None, :] - intersections
    scores = np.divide(intersections, unions, out=np.zeros(intersections.shape, dtype=np.float64), where=unions != 0)
    source, target = np.nonzero(scores > threshold)
    names = np.asarray(genes)
    return pd.DataFrame({"source": names[source], "target": names[target], "importance": scores[source, target]})


def select_neighbors(candidates, k, strict_nonself=False):
    if strict_nonself:
        candidates = candidates[candidates.source != candidates.target]
    # Same input source order and pandas nlargest keep='first' as GEARS.
    selected = candidates.groupby("target", sort=True)[["source", "target", "importance"]].apply(
        lambda frame: frame.nlargest(k if strict_nonself else k + 1, ["importance"])
    ).reset_index(drop=True)
    return selected


def neighborhoods(edges, genes):
    result = {gene: [] for gene in genes}
    weights = {gene: {} for gene in genes}
    for row in edges.itertuples(index=False):
        if row.source != row.target:
            result[row.target].append(row.source)
            weights[row.target][row.source] = float(row.importance)
    return result, weights


def compare(before, after, genes, targets, augmented_genes):
    before_lists, before_weights = neighborhoods(before, genes)
    after_lists, after_weights = neighborhoods(after, genes)
    rows, details = [], []
    for gene in genes:
        old, new = before_lists[gene], after_lists[gene]
        old_set, new_set = set(old), set(new)
        added, removed = new_set - old_set, old_set - new_set
        shared = old_set & new_set
        weights_changed = any(not np.isclose(before_weights[gene][neighbor], after_weights[gene][neighbor], rtol=0, atol=1e-12) for neighbor in shared)
        rows.append({
            "gene": gene, "is_perturbation_target": gene in targets,
            "has_added_attributes": gene in augmented_genes,
            "neighbor_set_changed": old_set != new_set, "neighbor_order_changed": old != new,
            "order_only_changed": old_set == new_set and old != new,
            "shared_neighbor_weights_changed": weights_changed,
            "before_neighbors": len(old), "after_neighbors": len(new),
            "retained_neighbors": len(shared), "added_neighbors": len(added), "removed_neighbors": len(removed),
        })
        details.append({"gene": gene, "before": [{"gene": n, "score": before_weights[gene][n]} for n in old],
                        "after": [{"gene": n, "score": after_weights[gene][n]} for n in new],
                        "added": sorted(added), "removed": sorted(removed)})
    frame = pd.DataFrame(rows)

    def summarize(subset):
        count = int(subset.neighbor_set_changed.sum())
        return {"genes": len(subset), "neighbor_sets_changed": count,
                "neighbor_sets_changed_percent": round(100 * count / len(subset), 4) if len(subset) else None,
                "neighbor_sets_unchanged": len(subset) - count,
                "order_only_changed": int(subset.order_only_changed.sum()),
                "unchanged_sets_with_changed_weights": int((~subset.neighbor_set_changed & subset.shared_neighbor_weights_changed).sum()),
                "mean_added_neighbors": float(subset.added_neighbors.mean()) if len(subset) else None,
                "mean_removed_neighbors": float(subset.removed_neighbors.mean()) if len(subset) else None}

    report = {"all_genes": summarize(frame), "perturbation_targets": summarize(frame[frame.is_perturbation_target]),
              "genes_with_added_attributes": summarize(frame[frame.has_added_attributes]),
              "genes_without_added_attributes": summarize(frame[~frame.has_added_attributes]),
              "added_neighbor_histogram": {str(k): v for k, v in sorted(Counter(frame.added_neighbors).items())},
              "before_nonself_edges": int(frame.before_neighbors.sum()), "after_nonself_edges": int(frame.after_neighbors.sum()),
              "added_nonself_edges": int(frame.added_neighbors.sum()), "removed_nonself_edges": int(frame.removed_neighbors.sum())}
    return report, frame, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--augmentation-run", type=Path, default=ROOT / "outputs/agents/norman_task_background_002")
    parser.add_argument("--baseline-run", type=Path, default=ROOT / "outputs/gears/norman_baseline_seed1_retry1")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/gears_norman_baseline_retry1.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("output directory exists; choose a new analysis directory")
    output.mkdir(parents=True)
    torch.set_num_threads(2)
    config = json.loads(args.config.read_text())
    k, threshold = config["model"]["num_similar_genes_go_graph"], 0.1
    graphs_path = args.baseline_run / "original_graphs.pt"
    graphs = torch.load(graphs_path, map_location="cpu", weights_only=False)
    genes = [str(gene) for gene in graphs["pert_list"]]
    assert genes == sorted(genes), "Match upstream source order for ties"
    universe = json.loads((args.augmentation_run / "inputs/gene_universe.json").read_text())
    assert genes == universe["graph_genes"]
    targets = set(universe["perturbation_targets"])
    go_path = ROOT / config["data_path"] / "gene2go_all.pkl"
    with go_path.open("rb") as handle:
        original = pickle.load(handle)
    base = [set(original[gene]) for gene in genes]
    assert all(base)
    extended = [set(terms) for terms in base]
    index = {gene: i for i, gene in enumerate(genes)}
    summary = json.loads((args.augmentation_run / "summary.json").read_text())
    sources = []
    membership_count = 0
    for batch in summary["approved_batches"]:
        path = Path(batch["approved_records_path"])
        assert sha256(path) == batch["approved_records_sha256"]
        selected = 0
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if not record["projection_eligible"]:
                continue
            assert record["relation"] in ("member_of_pathway", "predicted_member_of_complex")
            assert record["polarity"] in ("not_applicable", "positive")
            extended[index[record["subject_label"]]].add("EXTERNAL:" + record["object_id"])
            membership_count += 1
            selected += 1
        sources.append({"path": str(path), "sha256": batch["approved_records_sha256"], "projection_eligible_records": selected})
    augmented_genes = {gene for gene, old, new in zip(genes, base, extended) if old != new}
    print(f"Building original and augmented candidate graphs for {len(genes)} genes; k={k}", flush=True)
    baseline_cache = args.baseline_run / "data/go_essential_norman.csv"
    original_candidates = pd.read_csv(baseline_cache)
    rebuilt = candidate_edges(genes, base, threshold)
    assert len(rebuilt) == len(original_candidates)
    # Compare all source/target candidate pairs and their scores, not only top-k.
    left = rebuilt.sort_values(["source", "target"]).reset_index(drop=True)
    right = original_candidates.sort_values(["source", "target"]).reset_index(drop=True)
    assert left[["source", "target"]].equals(right[["source", "target"]])
    assert np.allclose(left.importance, right.importance, rtol=0, atol=1e-14)
    del rebuilt, left, right
    augmented_candidates = candidate_edges(genes, extended, threshold)
    # Training consumes CSV caches. Round-trip the new scores through the same
    # pandas CSV path before nlargest to match upstream numerical tie handling.
    augmented_path = output / "augmented_go_candidates.csv"
    augmented_candidates.to_csv(augmented_path, index=False)
    augmented_candidates = pd.read_csv(augmented_path)
    before = select_neighbors(original_candidates, k)
    after = select_neighbors(augmented_candidates, k)
    reference_edges = {(genes[int(source)], genes[int(target)]) for source, target in graphs["G_go"].T.tolist()}
    before_edges = set(zip(before.source, before.target))
    assert before_edges == reference_edges, "Original neighborhood reconstruction differs from the trained baseline"
    reference_weights = {(genes[int(source)], genes[int(target)]): float(weight) for (source, target), weight in zip(graphs["G_go"].T.tolist(), graphs["G_go_weight"].tolist())}
    assert all(np.isclose(row.importance, reference_weights[(row.source, row.target)], rtol=0, atol=1e-7) for row in before.itertuples(index=False))
    report, frame, details = compare(before, after, genes, targets, augmented_genes)
    strict_report, strict_frame, _ = compare(select_neighbors(original_candidates, k, True), select_neighbors(augmented_candidates, k, True), genes, targets, augmented_genes)
    before.to_csv(output / "original_selected_edges.csv", index=False)
    after.to_csv(output / "augmented_selected_edges.csv", index=False)
    frame.to_csv(output / "per_gene_changes.tsv", sep="\t", index=False)
    strict_frame.to_csv(output / "strict_nonself_top20_changes.tsv", sep="\t", index=False)
    with (output / "neighborhoods.jsonl").open("w") as handle:
        for item in details:
            handle.write(json.dumps(item) + "\n")
    write_json(output / "changed_genes.json", frame.loc[frame.neighbor_set_changed, "gene"].tolist())
    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "k": k, "jaccard_threshold_exclusive": threshold,
        "projection": "Equal-weight union of original GO terms and namespaced approved primary external membership attributes; no ontology propagation or additional filtering.",
        "selection": "GEARS pandas groupby(target).nlargest(k+1, importance), keep first on ties; source order lexicographic. Self edges excluded from neighborhood-change statistics.",
        "primary_definition": "Changed means at least one nonself incoming neighbor was added or removed; order-only and weight-only changes are reported separately.",
        "genes_with_added_attributes": len(augmented_genes), "added_memberships": membership_count,
        "original_candidate_edges": len(original_candidates), "augmented_candidate_edges": len(augmented_candidates),
        "original_selected_edges": len(before), "augmented_selected_edges": len(after),
        "original_self_edges": int((before.source == before.target).sum()), "augmented_self_edges": int((after.source == after.target).sum()),
        "baseline_reference_edges_verified": len(reference_edges), "all_original_candidate_pairs_verified": True,
        "gears_behavior": report, "strict_top20_nonself_sensitivity": strict_report,
        "inputs": {"annotation_path": str(go_path), "annotation_sha256": sha256(go_path),
                   "baseline_graph_path": str(graphs_path), "baseline_graph_sha256": sha256(graphs_path),
                   "baseline_cache_sha256": sha256(baseline_cache), "approved_sources": sources,
                   "script_sha256": sha256(Path(__file__)), "config_sha256": sha256(args.config)},
        "wall_seconds": time.perf_counter() - started,
    }
    write_json(output / "summary.json", result)
    print(json.dumps({"gears_behavior": report, "strict_top20_nonself_sensitivity": strict_report, "wall_seconds": result["wall_seconds"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
