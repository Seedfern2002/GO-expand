"""Project a frozen task-wide knowledge product into a matched GEARS experiment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import pickle
import shutil
import time

from compare_gears_topk import candidate_edges, compare, select_neighbors, sha256, write_json
from prepare_gears_augmented import prepare

ROOT = Path(__file__).resolve().parents[1]


def prepare_knowledge(knowledge_run, reference_run, analysis, config_path, output):
    import numpy as np
    import pandas as pd
    import torch

    for path in (analysis, config_path, output):
        if path.exists():
            raise FileExistsError(f"Use a fresh experiment path: {path}")
    started = time.perf_counter()
    torch.set_num_threads(2)
    knowledge = knowledge_run / "knowledge"
    manifest = json.loads((knowledge / "freeze_manifest.json").read_text())
    if not json.loads((knowledge / "validation.json").read_text())["passed"]:
        raise ValueError("Knowledge validation must pass")
    for item in manifest["files"]:
        if sha256(knowledge / item["path"]) != item["sha256"]:
            raise ValueError(f"Frozen knowledge hash mismatch: {item['path']}")
    for item in manifest["inputs"]:
        path = knowledge_run / Path(item["path"]).relative_to("/workspace")
        if sha256(path) != item["sha256"]:
            raise ValueError(f"Frozen source hash mismatch: {item['path']}")

    config = json.loads((reference_run / "run_config.json").read_text())
    graphs_path = reference_run / "original_graphs.pt"
    graphs = torch.load(graphs_path, map_location="cpu", weights_only=False)
    genes = list(graphs["pert_list"])
    if genes != sorted(genes):
        raise ValueError("Expected upstream lexicographic gene order")
    universe = json.loads((knowledge_run / "inputs/genes.json").read_text())["genes"]
    if genes != universe:
        raise ValueError("Knowledge and GEARS gene universes differ")
    annotation_path = ROOT / config["data_path"] / "gene2go_all.pkl"
    with annotation_path.open("rb") as handle:
        original = pickle.load(handle)
    base = [set(original[gene]) for gene in genes]
    frozen_base = json.loads((knowledge_run / "inputs/annotations.json").read_text())
    if any(set(frozen_base[gene]) != terms for gene, terms in zip(genes, base)):
        raise ValueError("Original annotations differ from the reference baseline")
    attributes = {}
    with (knowledge / "gene_attributes.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            if row["gene"] in attributes or len(row["attributes"]) != len(set(row["attributes"])):
                raise ValueError("Duplicate gene or attribute in frozen knowledge")
            attributes[row["gene"]] = set(row["attributes"])
    if set(attributes) != set(genes):
        raise ValueError("Frozen attributes must cover exactly the GEARS universe")
    extended = [attributes[gene] for gene in genes]
    if any(not old <= new for old, new in zip(base, extended)):
        raise ValueError("Frozen knowledge must preserve original annotations")
    added = sum(len(new - old) for old, new in zip(base, extended))
    knowledge_summary = json.loads((knowledge / "summary.json").read_text())
    if added != knowledge_summary["added_memberships"]:
        raise ValueError("Membership count differs from the frozen summary")
    changed_genes = {gene for gene, old, new in zip(genes, base, extended) if old != new}
    split = json.loads((reference_run / "split.json").read_text())
    targets = {gene for conditions in split.values() for condition in conditions
               for gene in condition.split("+") if gene != "ctrl"}
    k, threshold = config["model"]["num_similar_genes_go_graph"], 0.1
    original_cache = reference_run / "data" / f"go_essential_{config['dataset']}.csv"
    original_candidates = pd.read_csv(original_cache)
    rebuilt = candidate_edges(genes, base, threshold)
    left = rebuilt.sort_values(["source", "target"]).reset_index(drop=True)
    right = original_candidates.sort_values(["source", "target"]).reset_index(drop=True)
    if not left[["source", "target"]].equals(right[["source", "target"]]) or not np.allclose(
        left.importance, right.importance, rtol=0, atol=1e-14
    ):
        raise ValueError("Original Jaccard reconstruction differs from the baseline cache")
    del rebuilt, left, right

    analysis.mkdir(parents=True)
    snapshot = analysis / "knowledge_snapshot"
    snapshot.mkdir()
    # Preserve the complete frozen product locally, including typed evidence.
    for item in manifest["files"]:
        shutil.copyfile(knowledge / item["path"], snapshot / item["path"])
    shutil.copyfile(knowledge / "freeze_manifest.json", snapshot / "freeze_manifest.json")
    for name in ("annotations.json", "genes.json"):
        shutil.copyfile(knowledge_run / "inputs" / name, snapshot / ("original_" + name))
    write_json(snapshot / "origin.json", {
        "workspace": str(knowledge_run), "freeze_sha256": sha256(knowledge / "freeze_manifest.json"),
        "source_inputs_verified": len(manifest["inputs"]),
    })
    candidates = candidate_edges(genes, extended, threshold)
    candidates.to_csv(analysis / "augmented_go_candidates.csv", index=False)
    candidates = pd.read_csv(analysis / "augmented_go_candidates.csv")
    before, after = select_neighbors(original_candidates, k), select_neighbors(candidates, k)
    expected = {(genes[int(s)], genes[int(t)]): float(w) for (s, t), w in
                zip(graphs["G_go"].T.tolist(), graphs["G_go_weight"].tolist())}
    if set(zip(before.source, before.target)) != set(expected) or any(
        not np.isclose(row.importance, expected[(row.source, row.target)], rtol=0, atol=1e-7)
        for row in before.itertuples(index=False)
    ):
        raise ValueError("Original selected graph differs from the trained baseline")
    report, per_gene, _ = compare(before, after, genes, targets, changed_genes)
    before.to_csv(analysis / "original_selected_edges.csv", index=False)
    after.to_csv(analysis / "augmented_selected_edges.csv", index=False)
    per_gene.to_csv(analysis / "per_gene_changes.tsv", sep="\t", index=False)
    sources = sorted(snapshot.iterdir()) + [Path(__file__).resolve()]
    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "k": k,
        "jaccard_threshold_exclusive": threshold,
        "projection": "Equal-weight Jaccard on the frozen gene_attributes product, including original GO, additional GO annotations and external memberships; original identifiers and projection policy preserved.",
        "selection": "GEARS groupby(target).nlargest(k+1, importance), with upstream CSV round-trip and lexicographic source order.",
        "genes_with_added_attributes": len(changed_genes), "added_memberships": added,
        "original_candidate_edges": len(original_candidates), "augmented_candidate_edges": len(candidates),
        "original_selected_edges": len(before), "augmented_selected_edges": len(after),
        "all_original_candidate_pairs_verified": True, "gears_behavior": report,
        "inputs": {"annotation_sha256": sha256(annotation_path), "baseline_graph_sha256": sha256(graphs_path),
                   "approved_sources": [{"path": str(p), "sha256": sha256(p)} for p in sources]},
        "wall_seconds": time.perf_counter() - started,
    }
    write_json(analysis / "summary.json", result)
    prepare(reference_run, analysis, config_path, output)
    prepared_config = json.loads(config_path.read_text())
    prepared_config["go_annotation_source"] = (
        f"Frozen {knowledge_run.parent.name} gene_attributes product with original GO and accepted "
        "GO/external memberships, using the matched GEARS Jaccard graph"
    )
    write_json(config_path, prepared_config)
    print(json.dumps({"stage": "knowledge_projection_ready", "added_memberships": added,
                      "genes_with_added_attributes": len(changed_genes), "graph_edges": len(after),
                      "neighborhoods": report["all_genes"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-run", type=Path, required=True)
    parser.add_argument("--reference-run", type=Path, default=ROOT / "outputs/gears/norman_baseline_seed1_retry1")
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.knowledge_run, args.reference_run, args.analysis, args.config, args.output)]
    prepare_knowledge(*paths)
    if args.run:
        from compare_gears_metrics import write_report
        from wait_and_run_gears import run
        comparison = args.comparison_output.resolve() if args.comparison_output else paths[2] / "metrics"
        write_report(paths[1], paths[4], comparison)
        try:
            run(config_path=paths[3])
        finally:
            write_report(paths[1], paths[4], comparison)


if __name__ == "__main__":
    main()
