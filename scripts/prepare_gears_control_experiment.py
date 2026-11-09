"""Prepare and queue a frozen-knowledge or matched random-graph GEARS run."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import pickle

from compare_gears_topk import candidate_edges, select_neighbors
from gears_random_graph import randomize_go_graph
from prepare_gears_augmented import prepare
from prepare_gears_knowledge import prepare_knowledge
from run_gears_baseline import sha256, verify_augmentation_inputs, write_json

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_gears_matched.py"


def prepare_random(reference_run, analysis, config_path, output, seed):
    import numpy as np
    import pandas as pd
    import torch

    for path in (analysis, config_path, output):
        if path.exists():
            raise FileExistsError(f"Use a fresh experiment path: {path}")
    torch.set_num_threads(2)
    config = json.loads((reference_run / "run_config.json").read_text())
    graph_path = reference_run / "original_graphs.pt"
    graphs = torch.load(graph_path, map_location="cpu", weights_only=False)
    genes = list(graphs["pert_list"])
    annotation_path = ROOT / config["data_path"] / "gene2go_all.pkl"
    with annotation_path.open("rb") as stream:
        annotations = pickle.load(stream)
    cache = reference_run / "data" / f"go_essential_{config['dataset']}.csv"
    candidates = pd.read_csv(cache)
    rebuilt = candidate_edges(genes, [set(annotations[g]) for g in genes], 0.1)
    left = rebuilt.sort_values(["source", "target"]).reset_index(drop=True)
    right = candidates.sort_values(["source", "target"]).reset_index(drop=True)
    assert left[["source", "target"]].equals(right[["source", "target"]])
    assert np.allclose(left.importance, right.importance, rtol=0, atol=1e-14)
    k = config["model"]["num_similar_genes_go_graph"]
    original = select_neighbors(candidates, k)
    edges = graphs["G_go"].T.tolist()
    weights = graphs["G_go_weight"].tolist()
    expected = {(genes[s], genes[t]): w for (s, t), w in zip(edges, weights)}
    assert set(zip(original.source, original.target)) == set(expected)
    assert all(np.isclose(row.importance, expected[(row.source, row.target)], rtol=0, atol=1e-7)
               for row in original.itertuples(index=False))
    sampled, sampled_weights = randomize_go_graph(edges, weights, len(genes), seed)
    assert len(sampled) == len(edges) and len(set(sampled)) == len(edges)
    assert Counter(t for s, t in sampled) == Counter(t for s, t in edges)
    assert {(s, t) for s, t in sampled if s == t} == {(s, t) for s, t in edges if s == t}
    assert sorted(sampled_weights) == sorted(weights)
    assert set(sampled) != set(map(tuple, edges))
    frame = pd.DataFrame({"source": [genes[s] for s, t in sampled],
                          "target": [genes[t] for s, t in sampled], "importance": sampled_weights})
    analysis.mkdir(parents=True)
    frame.to_csv(analysis / "augmented_go_candidates.csv", index=False)
    frame = pd.read_csv(analysis / "augmented_go_candidates.csv")
    selected = select_neighbors(frame, k)
    assert len(selected) == len(edges)
    original.to_csv(analysis / "original_selected_edges.csv", index=False)
    selected.to_csv(analysis / "augmented_selected_edges.csv", index=False)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "experiment_type": "random_go_graph",
        "random_seed": seed, "k": k, "projection": "Uniform random nonself source endpoints per target; reference incoming degrees, self-loop locations and globally shuffled reference nonself weights preserved.",
        "original_candidate_edges": len(candidates), "augmented_candidate_edges": len(frame),
        "original_selected_edges": len(edges), "augmented_selected_edges": len(selected),
        "all_original_candidate_pairs_verified": True, "added_memberships": 0, "genes_with_added_attributes": 0,
        "self_edges": sum(s == t for s, t in sampled),
        "nonself_edges": sum(s != t for s, t in sampled),
        "overlap_with_reference_nonself_edges": len({(s, t) for s, t in sampled if s != t} & {tuple(e) for e in edges if e[0] != e[1]}),
        "incoming_degrees_match": True, "self_loop_locations_match": True, "edge_weight_multiset_matches": True,
        "inputs": {"baseline_graph_sha256": sha256(graph_path), "annotation_sha256": sha256(annotation_path),
                   "approved_sources": [{"path": str(p), "sha256": sha256(p)} for p in
                                        [cache, Path(__file__).resolve(), ROOT / "scripts/gears_random_graph.py"]]},
    }
    write_json(analysis / "summary.json", report)
    prepare(reference_run, analysis, config_path, output)
    config = json.loads(config_path.read_text())
    config["go_annotation_source"] = f"Random directed GO-graph control, graph seed {seed}; matched reference edge count, incoming degrees, self-loops and shuffled weight distribution"
    write_json(config_path, config)
    print(json.dumps({"stage": "random_graph_prepared", **{key: report[key] for key in
          ["random_seed", "augmented_selected_edges", "self_edges", "nonself_edges", "incoming_degrees_match", "edge_weight_multiset_matches"]}}), flush=True)


def freeze_runner(config_path, output):
    config = json.loads(config_path.read_text())
    manifest_path = ROOT / config["go_augmentation"]["manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    known = {entry["path"] for entry in manifest["files"]}
    for path in [Path(__file__).resolve(), RUNNER, ROOT / "scripts/gears_evaluation_context.py",
                 ROOT / "scripts/wait_and_run_gears.py"]:
        relative = str(path.relative_to(ROOT))
        if relative not in known:
            manifest["files"].append({"path": relative, "sha256": sha256(path)})
            known.add(relative)
    manifest["training_runner"] = str(RUNNER.relative_to(ROOT))
    manifest["telemetry"] = "Evaluation context bound to each result identity; training and validation phases reconciled before checkpoint logging"
    write_json(manifest_path, manifest)
    config["go_augmentation"]["manifest_sha256"] = sha256(manifest_path)
    write_json(config_path, config)
    preparation = json.loads((output / "preparation.json").read_text())
    preparation["augmentation_manifest_sha256"] = sha256(manifest_path)
    preparation["training_runner"] = str(RUNNER.relative_to(ROOT))
    write_json(output / "preparation.json", preparation)
    verify_augmentation_inputs(config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--knowledge-run", type=Path)
    choice.add_argument("--random-seed", type=int)
    parser.add_argument("--reference-run", type=Path, default=ROOT / "outputs/gears/norman_baseline_seed1_retry1")
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison-output", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    reference, analysis, config, output = [p.resolve() for p in
                                          [args.reference_run, args.analysis, args.config, args.output]]
    if args.knowledge_run:
        prepare_knowledge(args.knowledge_run.resolve(), reference, analysis, config, output)
    else:
        prepare_random(reference, analysis, config, output, args.random_seed)
    freeze_runner(config, output)
    if args.run:
        from compare_gears_metrics import write_report
        from wait_and_run_gears import run
        write_report(reference, output, args.comparison_output.resolve())
        try:
            run(config_path=config, runner_path=RUNNER)
        finally:
            write_report(reference, output, args.comparison_output.resolve())


if __name__ == "__main__":
    main()
