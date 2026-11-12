"""Freeze a pruned-augmentation experiment and reuse matched completed baselines."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import drugcell_ontology as ontology
import prune_drugcell_ontology as pruning
import run_drugcell_comparison_optimized as comparison


def validate_knowledge_inputs(workspace, gene_map, baseline_ontology):
    """Bind a new scientific knowledge product to the matched baseline inputs."""
    task = comparison.read_json(Path(workspace) / "knowledge/task.json")
    gene_path = comparison.workspace_input(workspace, task["scope"]["gene_universe_path"])
    supplied_genes = comparison.read_json(gene_path)[task["scope"]["gene_field"]]
    genes = ontology.read_gene_map(gene_map)
    if supplied_genes != genes:
        raise ValueError("New knowledge uses a different gene universe or order")
    annotations = comparison.read_json(comparison.workspace_input(
        workspace, task["compilation"]["baseline_annotations_path"]))
    baseline = ontology.read_ontology(baseline_ontology, genes)
    if set(annotations) != set(genes) or any(
            set(annotations[gene]) != set(baseline["propagated_annotations"][gene]) for gene in genes):
        raise ValueError("New knowledge uses different baseline functional annotations")


def check_gene_alignment(source_directory, graph_genes, pruned_ontology, output):
    source_directory = Path(source_directory)
    feature_genes = ontology.read_gene_map(source_directory / "gene2ind.txt")
    indices = {gene: index for index,gene in enumerate(feature_genes)}
    missing = sorted(set(graph_genes) - indices.keys())
    if missing:
        raise ValueError("Augmented genes require measured mutation features: " + ", ".join(missing[:10]))
    rows = 0
    with (source_directory / "cell2mutation.txt").open() as stream:
        for line in stream:
            if len(line.rstrip().split(",")) != len(feature_genes):
                raise ValueError("Mutation feature width differs from its gene identifier map")
            rows += 1
    cells = ontology.read_gene_map(source_directory / "cell2ind.txt")
    if rows != len(cells):
        raise ValueError("Mutation feature rows differ from the cell identifier map")
    graph = ontology.read_ontology(pruned_ontology, graph_genes)
    columns = [indices[g] for g in graph_genes]
    result = {"available_feature_genes": len(feature_genes), "task_input_genes": len(graph_genes),
        "pruned_annotated_genes": graph["stats"]["annotated_genes"], "mutation_rows": rows,
        "gene_order_matches_features": columns == list(range(len(feature_genes))),
        "feature_columns_for_task_gene_order": columns, "missing_feature_genes": missing,
        "gene_order_sha256": hashlib.sha256(json.dumps(graph_genes).encode()).hexdigest()}
    if not result["gene_order_matches_features"]:
        raise ValueError("Training requires an explicitly prepared feature-column projection for the changed gene order")
    ontology.write_json(output, result)
    return result


def prepare(source, output, knowledge_workspace=None, code_source_directory=None, module_graph_product=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    comparison.verify_experiment(source)
    previous = comparison.read_json(source / "config.json")
    if knowledge_workspace is not None:
        knowledge_workspace = Path(knowledge_workspace).resolve()
        comparison.verify_frozen_product(knowledge_workspace)
        validate_knowledge_inputs(knowledge_workspace, source / "source_inputs/gene2ind.txt",
                                  source / "baseline/drugcell_ont.txt")
    frozen = comparison.read_json(source / "augmentation_status.json")
    if frozen.get("stage") != "ontology_frozen":
        raise ValueError("The source experiment needs a frozen augmented ontology")
    source_ontology = source / "augmentation/drugcell_ont.txt"
    if ontology.sha256(source_ontology) != frozen["ontology_sha256"]:
        raise ValueError("The source augmentation changed")
    config = deepcopy(previous)
    if code_source_directory is not None:
        config["runtime"]["code_source_directory"] = str(Path(code_source_directory).resolve())
    config["experiment_id"] = ("drugcell_new_knowledge_augmented_then_pruned_v1" if knowledge_workspace
                               else "drugcell_augmented_then_pruned_v1")
    if knowledge_workspace:
        config["knowledge"]["augmentation_workspace"] = str(knowledge_workspace)
    if module_graph_product is not None:
        if knowledge_workspace is None:
            raise ValueError("A module graph needs its corresponding frozen membership workspace")
        from export_drugcell_module_graph import verify_product
        product = Path(module_graph_product).resolve()
        verify_product(product)
        config["knowledge"].update(module_graph_product=str(product),
            module_graph_freeze_sha256=ontology.sha256(product / "freeze_manifest.json"))
    config["comparison_description"] = (
        "Released DrugCell baseline (completed matched folds reused) versus the frozen augmented GO after "
        "published size/separation/depth pruning. Data, grouped folds, model seed and training settings are shared.")
    config["knowledge"]["comparison"] = "Released pruned GO versus augmented-then-pruned GO"
    config["completed_run_references"] = {}
    for fold in config["data"]["folds"]:
        run = source / "runs/baseline" / f"fold_{fold}"
        metrics = comparison.read_json(run / "metrics.json")
        run_config = comparison.read_json(run / "run_config.json")
        if metrics.get("status") != "complete" or run_config.get("seed") != config["model_seed"]:
            raise ValueError("Baseline reference is incomplete or has a different seed")
        if any(value is not None for value in run_config["scope"].values()):
            raise ValueError("Baseline reference contains smoke or shortened training overrides")
        if run_config["training"] != config["released_training_settings"]:
            raise ValueError("Baseline reference has different training settings")
        for key, expected in [("data_manifest", config["data"]["frozen_manifest_sha256"]),
                              ("split_manifest", config["data"]["frozen_split_manifest_sha256"]),
                              ("ontology", ontology.sha256(source / "baseline/drugcell_ont.txt"))]:
            if run_config["inputs"][key]["sha256"] != expected:
                raise ValueError("Baseline reference has different frozen data, splits or ontology")
        config["completed_run_references"][f"baseline_{fold}"] = {
            "path": str(run), "source_experiment": str(source),
            "files": {name: ontology.sha256(run / name) for name in (
                "metrics.json", "run_config.json", "predictions.tsv.gz")}}
    with tempfile.TemporaryDirectory(prefix="drugcell-pruned-config-") as temporary:
        path = Path(temporary) / "config.json"
        comparison.write_json(path, config)
        config = comparison.initialize(path, output)

    source_copy = output / "source_augmentation"
    source_copy.mkdir()
    knowledge_source = source
    if knowledge_workspace:
        knowledge_source = output / "unpruned"
        (knowledge_source / "source_inputs").mkdir(parents=True)
        shutil.copyfile(output / "source_inputs/gene2ind.txt", knowledge_source / "source_inputs/gene2ind.txt")
        comparison.prepare_augmentation(knowledge_source, config)
    for filename in ("drugcell_ont.txt", "projection_manifest.json"):
        shutil.copyfile(knowledge_source / "augmentation" / filename, source_copy / filename)
    freeze = knowledge_source / "knowledge_snapshot/freeze_manifest.json"
    shutil.copyfile(freeze, output / "source_inputs/knowledge_freeze_manifest.json")
    shutil.copyfile(Path(__file__), output / "code/prepare_drugcell_pruned_experiment.py")
    shutil.copyfile(Path(pruning.__file__), output / "code/prune_drugcell_ontology.py")
    report = pruning.prune(source_copy / "drugcell_ont.txt", output / "source_inputs/gene2ind.txt",
                           output / "augmentation")
    config["knowledge"]["ontology_derivation"] = {
        "operation": "drugcell_prune", "manifest": str(output / "augmentation/pruning_manifest.json"),
        "manifest_sha256": ontology.sha256(output / "augmentation/pruning_manifest.json"),
        "parent_ontology": str(source_copy / "drugcell_ont.txt"),
        "parent_ontology_sha256": ontology.sha256(source_copy / "drugcell_ont.txt")}
    config["knowledge"]["parent_knowledge_experiment"] = str(knowledge_source)
    config["baseline_reference_experiment"] = str(source)
    config["knowledge"]["original_rows"] = "Retained in parent snapshot; pruning may contract original nodes"
    config["execution_projection_policy"] = report["policy"]
    config["runtime"]["preflight_bundle"] = str(output / "preflight_bundle")
    comparison.write_json(output / "config.json", config)
    project = Path(config["project_root"])
    interpreter = Path(config["runtime"]["python"])
    if not interpreter.is_absolute():
        interpreter = project / interpreter
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1")
    with (output / "prepare_bundle.log").open("w") as log:
        code_source = Path(config["runtime"].get("code_source_directory", project / "scripts"))
        subprocess.run([str(interpreter), str(code_source / "benchmark_drugcell_optimized.py"),
                        "--prepare-config", str(output / "config.json"),
                        "--bundle", config["runtime"]["preflight_bundle"]],
                       env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    config["runtime"]["preflight_bundle_manifest_sha256"] = ontology.sha256(output / "preflight_bundle/manifest.json")
    comparison.write_json(output / "config.json", config)

    genes = ontology.read_gene_map(output / "source_inputs/gene2ind.txt")
    original = ontology.read_ontology(source / "baseline/drugcell_ont.txt", genes)
    final = ontology.read_ontology(output / "augmentation/drugcell_ont.txt", genes)
    upstream_manifest = comparison.read_json(config["source_manifest"])
    upstream_data = Path(config["project_root"]) / upstream_manifest["local_path"] / "data"
    check_gene_alignment(upstream_data, genes, output / "augmentation/drugcell_ont.txt", output / "gene_alignment.json")
    retained_old = original["terms"] & final["terms"]
    changes = {"retained_released_terms": len(retained_old),
               "removed_released_terms": len(original["terms"] - final["terms"]),
               "retained_added_terms": len(final["terms"] - original["terms"]),
               "retained_external_terms": sum(not t.startswith("GO:") for t in final["terms"]),
               "retained_old_terms_gene_memberships_added": sum(
                   len(final["propagated"][t] - original["propagated"][t]) for t in retained_old)}
    comparison.write_json(output / "pruning_summary.json", {
        "input": report["input_statistics"], "pruned": report["statistics"],
        "released_baseline": original["stats"], "changes": changes,
        "source_experiment": str(knowledge_source), "baseline_reference_experiment": str(source),
        "source_knowledge_workspace": str(knowledge_workspace) if knowledge_workspace else previous["knowledge"]["augmentation_workspace"],
        "source_knowledge_freeze_sha256": ontology.sha256(freeze),
        "implementation_scope": "Published threshold reconstruction on the existing frozen graph; root retained",
        "baseline_diagnostic": "The released ontology has 65 nodes below the literal 30-gene separation threshold; completed released-baseline runs remain the comparator"})
    comparison.write_json(output / "augmentation_status.json", {
        "stage": "ontology_frozen", "updated_at_utc": comparison.now(),
        "ontology_sha256": ontology.sha256(output / "augmentation/drugcell_ont.txt"),
        "pruning_manifest_sha256": ontology.sha256(output / "augmentation/pruning_manifest.json"),
        "projection_counts": changes})
    manifest = comparison.read_json(output / "experiment_manifest.json")
    manifest["comparison"] = config["comparison_description"]
    manifest["source_experiment"] = str(source)
    manifest["source_knowledge_experiment"] = str(knowledge_source)
    manifest["files"] = [{"path": row["path"], "sha256": ontology.sha256(output / row["path"])}
                         for row in manifest["files"]]
    existing = {row["path"] for row in manifest["files"]}
    for directory in (output / "augmentation", source_copy, output / "preflight_bundle"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and str(path.relative_to(output)) not in existing:
                manifest["files"].append({"path": str(path.relative_to(output)), "sha256": ontology.sha256(path)})
    for path in [output / "source_inputs/knowledge_freeze_manifest.json", output / "pruning_summary.json", output / "gene_alignment.json",
                 output / "code/prune_drugcell_ontology.py", output / "code/prepare_drugcell_pruned_experiment.py"]:
        manifest["files"].append({"path": str(path.relative_to(output)), "sha256": ontology.sha256(path)})
    if knowledge_workspace:
        for directory in (knowledge_source / "augmentation", knowledge_source / "projection_inputs"):
            for path in sorted(directory.iterdir()):
                if path.is_file():
                    manifest["files"].append({"path": str(path.relative_to(output)), "sha256": ontology.sha256(path)})
        for filename in ("freeze_manifest.json", "snapshot_manifest.json"):
            path = knowledge_source / "knowledge_snapshot" / filename
            manifest["files"].append({"path": str(path.relative_to(output)), "sha256": ontology.sha256(path)})
    comparison.write_json(output / "experiment_manifest.json", manifest)
    comparison.verify_experiment(output)
    return {"output": str(output), "statistics": final["stats"], "changes": changes,
            "baseline_folds_reused": len(config["completed_run_references"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--knowledge-workspace", type=Path,
                        help="Use a new frozen knowledge product with the source experiment's matched baseline")
    parser.add_argument("--code-source-directory", type=Path,
                        help="Freeze evaluators from a predeclared code snapshot")
    parser.add_argument("--module-graph-product", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_experiment, args.output, args.knowledge_workspace,
                             args.code_source_directory, args.module_graph_product), indent=2))


if __name__ == "__main__":
    main()
