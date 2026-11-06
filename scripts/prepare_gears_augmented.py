"""Freeze an existing top-k augmentation experiment for a matched GEARS run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_gears_baseline import normalize, sha256, verify_augmentation_inputs, write_json


def prepare(reference_run, analysis, config_path, output):
    import pandas as pd
    import torch

    torch.set_num_threads(2)
    sys.path.insert(0, str(ROOT / "third_party/GEARS"))
    from gears.utils import GeneSimNetwork

    if output.exists() or config_path.exists():
        raise FileExistsError("Use new output and configuration paths")
    report = json.loads((analysis / "summary.json").read_text())
    reference_config_path = reference_run / "run_config.json"
    config = json.loads(reference_config_path.read_text())
    config.pop("device", None)
    assert report["k"] == config["model"]["num_similar_genes_go_graph"]
    assert report["all_original_candidate_pairs_verified"]
    assert sha256(reference_run / "original_graphs.pt") == report["inputs"]["baseline_graph_sha256"]
    assert sha256(ROOT / config["data_path"] / "gene2go_all.pkl") == report["inputs"]["annotation_sha256"]
    for source in report["inputs"]["approved_sources"]:
        assert sha256(Path(source["path"])) == source["sha256"]

    graphs = torch.load(reference_run / "original_graphs.pt", map_location="cpu", weights_only=False)
    genes = list(graphs["pert_list"])
    candidates = pd.read_csv(analysis / "augmented_go_candidates.csv")
    selected = candidates.groupby("target").apply(
        lambda frame: frame.nlargest(report["k"] + 1, ["importance"]), include_groups=False
    ).reset_index(level=0).reset_index(drop=True)
    saved = pd.read_csv(analysis / "augmented_selected_edges.csv")
    pd.testing.assert_frame_equal(selected[saved.columns], saved)
    assert len(selected) == report["augmented_selected_edges"]
    assert not selected.duplicated(["source", "target"]).any()
    assert set(candidates.source) | set(candidates.target) == set(genes)
    network = GeneSimNetwork(selected, genes, {gene: index for index, gene in enumerate(genes)})
    graphs["G_go"] = network.edge_index
    graphs["G_go_weight"] = network.edge_weight

    output.mkdir(parents=True)
    (output / "data").mkdir()
    cache = output / "data" / f"go_essential_{config['dataset']}.csv"
    shutil.copyfile(analysis / "augmented_go_candidates.csv", cache)
    expected_path = output / "expected_graphs.pt"
    torch.save(graphs, expected_path)
    shutil.copyfile(reference_config_path, output / "reference_config.json")
    reference_config_path = output / "reference_config.json"
    input_paths = [reference_config_path, reference_run / "original_graphs.pt", reference_run / "split.json",
                   reference_run / "subgroups.json", analysis / "summary.json",
                   analysis / "augmented_go_candidates.csv", analysis / "augmented_selected_edges.csv",
                   cache, expected_path, ROOT / "scripts/run_gears_baseline.py", Path(__file__).resolve()]
    input_paths += [Path(source["path"]) for source in report["inputs"]["approved_sources"]]
    input_paths += [ROOT / item["path"] for item in json.loads((reference_run / "input_files.json").read_text())]
    # Freeze the existing training-only coexpression cache as well as the tensor.
    coexpression = ROOT / config["data_path"] / config["dataset"] / (
        f"{config['split']}_{config['split_seed']}_{config['train_gene_set_size']}_"
        f"{config['model']['coexpress_threshold']}_{config['model']['num_similar_genes_co_express_graph']}_co_expression_network.csv"
    )
    if not coexpression.is_file():
        raise FileNotFoundError(f"Reference coexpression cache is missing: {coexpression}")
    input_paths.append(coexpression)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "reference_run": str(reference_run.relative_to(ROOT)),
        "reference_config_path": str(reference_config_path.relative_to(ROOT)),
        "expected_graphs_path": str(expected_path.relative_to(ROOT)),
        "projection": report["projection"], "k": report["k"],
        "added_memberships": report["added_memberships"],
        "genes_with_added_attributes": report["genes_with_added_attributes"],
        "go_edges": len(selected),
        "files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in input_paths],
    }
    manifest_path = output / "augmentation_manifest.json"
    write_json(manifest_path, manifest)
    config.update(experiment=output.name, output_path=str(output.relative_to(ROOT)),
                  go_annotation_source="Original GEARS GO plus the frozen primary Reactome/hu.MAP overlay, via its verified Jaccard cache",
                  go_augmentation={"manifest_path": str(manifest_path.relative_to(ROOT)), "manifest_sha256": sha256(manifest_path)})
    verify_augmentation_inputs(config)
    write_json(config_path, config)
    write_json(output / "preparation.json", {
        "stage": "cpu_preparation_complete", "graphs_prepared": True,
        "go_candidate_edges": len(candidates), "go_selected_edges": len(selected),
        "coexpression_edges": graphs["G_coexpress"].shape[1],
        "perturbation_graph_genes": len(genes), "reference_run": str(reference_run.relative_to(ROOT)),
        "augmentation_manifest_sha256": sha256(manifest_path),
    })
    print(json.dumps(normalize({"config": str(config_path), "output": str(output), "go_edges": len(selected)})), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-run", type=Path, default=ROOT / "outputs/gears/norman_baseline_seed1_retry1")
    parser.add_argument("--analysis", type=Path, default=ROOT / "outputs/analysis/norman_topk_neighbors_001")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.reference_run.resolve(), args.analysis.resolve(), args.config.resolve(), args.output.resolve())
