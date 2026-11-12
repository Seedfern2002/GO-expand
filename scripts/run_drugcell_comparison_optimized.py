"""Supervise packed DrugCell training after full CUDA implementation checks.

The augmentation workspace supplies scientific knowledge only. This supervisor
keeps evaluation artifacts in the project and uses the shared GPU reservation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import time
import traceback

import drugcell_ontology as ontology_adapter
import wait_and_run_gears as gpu_queue


ROOT = Path(__file__).resolve().parents[1]
METRICS = ("spearman", "pearson", "mse", "rmse",
           "per_drug_spearman_mean", "per_drug_spearman_median")
TERMINAL_PIPELINE = {"completed", "completed_with_gaps"}


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def safe_child(root, relative):
    relative = Path(relative)
    path = (Path(root) / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(Path(root).resolve()):
        raise ValueError(f"Artifact path escapes its snapshot: {relative}")
    return path


def workspace_input(workspace, name):
    path = Path(name)
    if path.is_absolute():
        try:
            path = path.relative_to("/workspace")
        except ValueError:
            if not path.resolve().is_relative_to(Path(workspace).resolve()):
                raise ValueError(f"Freeze input is outside the task workspace: {name}")
            path = path.resolve().relative_to(Path(workspace).resolve())
    return safe_child(workspace, path)


def verify_frozen_product(workspace):
    """Verify artifact and materialized input hashes before accepting a product."""
    workspace = Path(workspace).resolve()
    state = read_json(workspace / "status.json", {})
    if state.get("status") not in TERMINAL_PIPELINE:
        raise ValueError("The knowledge pipeline must finish before snapshot/export")
    knowledge = workspace / "knowledge"
    manifest = read_json(knowledge / "freeze_manifest.json")
    if not manifest or not isinstance(manifest.get("files"), list):
        raise ValueError("Knowledge product requires a freeze manifest")
    seen = set()
    for record in manifest["files"]:
        path = safe_child(knowledge, record["path"])
        if record["path"] in seen or ontology_adapter.sha256(path) != record["sha256"]:
            raise ValueError(f"Frozen knowledge artifact mismatch: {record['path']}")
        seen.add(record["path"])
    required = {"gene_attributes.jsonl", "validation.json", "summary.json", "task.json"}
    if not required <= seen:
        raise ValueError("Frozen knowledge is missing required artifacts")
    if read_json(knowledge / "validation.json").get("passed") is not True:
        raise ValueError("Knowledge structural/provenance validation did not pass")
    for record in manifest.get("inputs", []):
        path = workspace_input(workspace, record["path"])
        if ontology_adapter.sha256(path) != record["sha256"]:
            raise ValueError(f"Frozen knowledge input mismatch: {record['path']}")
    return manifest, state


def snapshot_knowledge(workspace, output):
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    if output.exists():
        receipt = read_json(output / "snapshot_manifest.json")
        source_freeze = workspace / "knowledge/freeze_manifest.json"
        if not receipt or (source_freeze.is_file() and receipt["source_freeze_sha256"] != ontology_adapter.sha256(source_freeze)):
            raise ValueError("Existing knowledge snapshot belongs to another freeze")
        for row in receipt["copied_files"]:
            if ontology_adapter.sha256(safe_child(output, row["path"])) != row["sha256"]:
                raise ValueError("Existing knowledge snapshot failed its hash check")
        return receipt
    manifest, state = verify_frozen_product(workspace)
    freeze_hash = ontology_adapter.sha256(workspace / "knowledge/freeze_manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".knowledge-", dir=output.parent) as temporary:
        staging = Path(temporary) / "product"
        staging.mkdir()
        copied = []
        for record in [*manifest["files"], {"path": "freeze_manifest.json", "sha256": freeze_hash}]:
            source = safe_child(workspace / "knowledge", record["path"])
            target = safe_child(staging, record["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append({"path": str(target.relative_to(staging)), "sha256": record["sha256"]})
        for record in manifest.get("inputs", []):
            source = workspace_input(workspace, record["path"])
            relative = Path("provenance") / source.relative_to(workspace)
            target = safe_child(staging, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append({"path": str(relative), "sha256": record["sha256"]})
        for record in copied:
            if ontology_adapter.sha256(staging / record["path"]) != record["sha256"]:
                raise ValueError(f"Knowledge input changed during copying: {record['path']}")
        if ontology_adapter.sha256(workspace / "knowledge/freeze_manifest.json") != freeze_hash:
            raise ValueError("Knowledge freeze changed during snapshot")
        receipt = {"created_at_utc": now(), "source_workspace": str(workspace),
                   "source_freeze_sha256": freeze_hash, "pipeline_status": state,
                   "copied_files": copied,
                   "scope": "Frozen knowledge and all materialized inputs referenced by its manifest"}
        write_json(staging / "snapshot_manifest.json", receipt)
        staging.rename(output)
    return receipt


def prepare_augmentation(experiment, config):
    """Build the downstream hierarchy through a predeclared aggregation policy."""
    experiment = Path(experiment)
    snapshot = experiment / "knowledge_snapshot"
    snapshot_knowledge(config["knowledge"]["augmentation_workspace"], snapshot)
    result_path = experiment / "augmentation/projection_manifest.json"
    if result_path.exists():
        report = read_json(result_path)
        for name, digest in report["artifacts"].items():
            if ontology_adapter.sha256(experiment / "augmentation" / name) != digest:
                raise ValueError("Augmented ontology snapshot changed")
        return report
    module_product = config["knowledge"].get("module_graph_product")
    if module_product:
        from export_drugcell_module_graph import export
        module_product = Path(module_product)
        expected = config["knowledge"]["module_graph_freeze_sha256"]
        if ontology_adapter.sha256(module_product / "freeze_manifest.json") != expected:
            raise ValueError("The selected module graph freeze changed")
        source_task = read_json(module_product.parent / "task.json")
        frozen_task = read_json(snapshot / "task.json")
        for field in ("task_description", "organism", "biological_context"):
            if source_task.get(field) != frozen_task.get(field):
                raise ValueError("Module graph and membership knowledge use different scientific tasks")
        return export(module_product, config["knowledge"]["baseline_ontology"],
                      experiment / "source_inputs/gene2ind.txt", experiment / "augmentation")
    attributes = snapshot / "gene_attributes.jsonl"
    baseline = Path(config["knowledge"]["baseline_ontology"])
    gene_map = experiment / "source_inputs/gene2ind.txt"
    genes = ontology_adapter.read_gene_map(gene_map)
    baseline_graph = ontology_adapter.read_ontology(baseline, genes)
    root = baseline_graph["root"]
    rows = [json.loads(line) for line in attributes.read_text().splitlines() if line.strip()]
    if {row["gene"] for row in rows} != set(genes) or len(rows) != len(genes):
        raise ValueError("Frozen augmentation must preserve the full fixed gene universe")
    external = sorted({term for row in rows for term in row["attributes"] if not term.startswith("GO:")})
    aliases = {term: term if ontology_adapter.valid_model_term(term)
               else "OVERLAY:" + hashlib.sha256(term.encode()).hexdigest() for term in external}
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("External module model identifiers collided")
    projection = experiment / "projection_inputs"
    projection.mkdir(exist_ok=True)
    converted = projection / "gene_attributes.jsonl"
    with converted.open("w") as stream:
        for row in rows:
            stream.write(json.dumps({"gene": row["gene"],
                                     "attributes": sorted({aliases.get(term, term) for term in row["attributes"]})}) + "\n")
    parents = projection / "external_parent_map.json"
    write_json(parents, {alias: [root] for alias in sorted(aliases.values())})
    write_json(projection / "external_identifier_map.json", aliases)
    write_json(projection / "policy.json", {
        "external_parent": root,
        "relationship_semantics": "computational aggregation into the model's common functional root",
        "membership_semantics": "Preserve each evidence-backed external gene-module membership",
        "GO_relationship_semantics": "New GO-BP terms use authoritative compressed is_a ancestry",
        "identifier_policy": "Preserve compatible identifiers; encode incompatible external identifiers using a reversible mapping artifact and SHA256-derived model IDs",
        "knowledge_freeze_sha256": ontology_adapter.sha256(snapshot / "freeze_manifest.json"),
        "external_modules": len(external),
    })
    task = read_json(snapshot / "task.json")
    obo_relative = task["compilation"].get("ontology_path")
    obo = safe_child(snapshot / "provenance", obo_relative) if obo_relative else None
    if obo and not obo.is_file():
        raise ValueError("The frozen input set must include its declared GO OBO")
    return ontology_adapter.augment(baseline, gene_map, converted, experiment / "augmentation", obo, parents)


def initialize(config_path, output, workspace=None):
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a fresh experiment directory or --resume an existing supervisor")
    config = read_json(config_path)
    project = Path(config.get("project_root", ROOT)).resolve()
    code_source = Path(config.get("runtime", {}).get("code_source_directory", project / "scripts")).resolve()
    workspace = Path(workspace or config["knowledge"]["augmentation_workspace"]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".drugcell-experiment-", dir=output.parent) as temporary:
        staging = Path(temporary) / "product"
        staging.mkdir()
        (staging / "code").mkdir()
        pinned = []
        code_names = ["run_drugcell.py", "run_drugcell_comparison.py", "drugcell_masked_layers.py",
                      "drugcell_packed.py", "benchmark_drugcell_optimized.py",
                      "drugcell_ontology.py", "wait_and_run_gears.py"]
        if config["knowledge"].get("module_graph_product"):
            code_names.append("export_drugcell_module_graph.py")
        if config["knowledge"].get("full_go_source"):
            code_names.append("drugcell_input_projection.py")
        for name in code_names:
            source_name = {"run_drugcell.py": "run_drugcell_optimized.py",
                           "run_drugcell_comparison.py": "run_drugcell_comparison_optimized.py"}.get(name, name)
            source = code_source / source_name
            destination = staging / "code" / name
            shutil.copyfile(source, destination)
            pinned.append({"path": str(destination.relative_to(staging)), "sha256": ontology_adapter.sha256(source)})
        (staging / "source_inputs").mkdir()
        source_manifest_path = project / config["source_manifest"]
        source_manifest = read_json(source_manifest_path)
        source = project / source_manifest["local_path"]
        for filename in ("gene2ind.txt", "cell2ind.txt", "drug2ind.txt"):
            destination = staging / "source_inputs" / filename
            shutil.copyfile(source / "data" / filename, destination)
            pinned.append({"path": str(destination.relative_to(staging)), "sha256": ontology_adapter.sha256(destination)})
        (staging / "baseline").mkdir()
        baseline = Path(config["knowledge"]["baseline_ontology"])
        if not baseline.is_absolute():
            baseline = project / baseline
        shutil.copyfile(baseline, staging / "baseline/drugcell_ont.txt")
        pinned.append({"path": "baseline/drugcell_ont.txt", "sha256": ontology_adapter.sha256(baseline)})
        for name, path in (("source_manifest.json", source_manifest_path),
                           ("data_manifest.json", Path(config["data"].get("frozen_manifest", project / config["data"]["prepared_directory"] / "manifest.json"))),
                           ("split_manifest.json", Path(config["data"].get("frozen_split_manifest", project / config["data"]["prepared_directory"] / "split_manifest.json")))):
            shutil.copyfile(path, staging / "source_inputs" / name)
            pinned.append({"path": "source_inputs/" + name, "sha256": ontology_adapter.sha256(path)})
        (staging / "original_config.json").write_bytes(config_path.read_bytes())
        pinned.append({"path": "original_config.json", "sha256": ontology_adapter.sha256(config_path)})
        config["project_root"] = str(project)
        config["source_manifest"] = str(output / "source_inputs/source_manifest.json")
        config["data"].update({
            "frozen_manifest": str(output / "source_inputs/data_manifest.json"),
            "frozen_manifest_sha256": ontology_adapter.sha256(staging / "source_inputs/data_manifest.json"),
            "frozen_split_manifest": str(output / "source_inputs/split_manifest.json"),
            "frozen_split_manifest_sha256": ontology_adapter.sha256(staging / "source_inputs/split_manifest.json"),
        })
        config["knowledge"]["baseline_ontology"] = str(output / "baseline/drugcell_ont.txt")
        config["knowledge"]["augmentation_workspace"] = str(workspace)
        config["knowledge"]["augmented_ontology"] = str(output / "augmentation/drugcell_ont.txt")
        config["execution_projection_policy"] = {
            "external_modules": "Attach each evidence-backed external module to the common functional root using explicitly recorded computational-aggregation edges.",
            "new_GO_terms": "Selected active GO-BP nodes with authoritative compressed is_a ancestry",
        }
        if config["knowledge"].get("module_graph_product"):
            product = Path(config["knowledge"]["module_graph_product"])
            if not product.is_absolute():
                product = project / product
            product = product.resolve()
            freeze_sha = ontology_adapter.sha256(product / "freeze_manifest.json")
            declared = config["knowledge"].get("module_graph_freeze_sha256", freeze_sha)
            if declared != freeze_sha:
                raise ValueError("The declared module graph freeze changed")
            config["knowledge"].update(module_graph_product=str(product), module_graph_freeze_sha256=freeze_sha)
            destination = staging / "source_inputs/module_graph_freeze_manifest.json"
            shutil.copyfile(product / "freeze_manifest.json", destination)
            pinned.append({"path": str(destination.relative_to(staging)), "sha256": freeze_sha})
            config["execution_projection_policy"] = {
                "module_graph": "Use frozen agent-reviewed typed edges and source aliases",
                "model_edges": "Select declared model_edge=true connections and preserve original ontology rows",
                "membership_compression": "Remove redundant new direct inputs while preserving model coverage"}
        write_json(staging / "config.json", config)
        pinned.append({"path": "config.json", "sha256": ontology_adapter.sha256(staging / "config.json")})
        write_json(staging / "experiment_manifest.json", {
            "created_at_utc": now(), "source_config": str(config_path),
            "source_config_sha256": ontology_adapter.sha256(config_path), "files": pinned,
            "comparison": "Released pruned GO versus additive task-specific augmentation",
            "workspace_boundary": "Evaluation files remain outside the task-only augmentation workspace",
        })
        staging.rename(output)
    return config


def cuda_preflight(output, config, environment, gpu_lock, chosen):
    """Check both frozen GO products on the allocated GPU before training."""
    receipt = output / "cuda_preflight.json"
    if receipt.is_file():
        value = read_json(receipt)
        if value.get("passed") is not True:
            raise ValueError("CUDA preflight previously failed")
        for arm, item in value["arms"].items():
            if ontology_adapter.sha256(output / "preflight" / arm / "benchmark.json") != item["sha256"]:
                raise ValueError("CUDA preflight receipt changed")
        return
    bundle = Path(config["runtime"]["preflight_bundle"])
    if ontology_adapter.sha256(bundle / "manifest.json") != config["runtime"]["preflight_bundle_manifest_sha256"]:
        raise ValueError("CUDA preflight bundle manifest changed")
    interpreter = Path(config["runtime"]["python"])
    if not interpreter.is_absolute():
        interpreter = Path(config["project_root"]) / interpreter
    write_json(output / "preflight_status.json", {"stage": "running", "GPU": chosen, "updated_at_utc": now()})
    arms = {}
    for arm in ("baseline", "augmented"):
        directory = output / "preflight" / arm
        command = [str(interpreter), "-u", str(bundle / "code/benchmark_drugcell_optimized.py"),
                   "--bundle", str(bundle), "--output", str(directory), "--arm", arm,
                   "--device", "cuda", "--batch-size", "5000", "--steps", "2", "--warmup", "1", "--threads", "8"]
        (output / "preflight").mkdir(exist_ok=True)
        with (output / "preflight" / (arm + ".log")).open("a") as log:
            subprocess.run(command, env=environment, stdin=subprocess.DEVNULL, stdout=log,
                           stderr=subprocess.STDOUT, pass_fds=(gpu_lock.fileno(),), check=True)
        result = read_json(directory / "benchmark.json")
        if result["status"] != "passed":
            raise ValueError("CUDA equivalence or throughput check failed")
        arms[arm] = {"sha256": ontology_adapter.sha256(directory / "benchmark.json"),
                     "speedup": result["training_step_speedup"], "timings": result["timings"],
                     "verification": result["verification"]}
    write_json(receipt, {"passed": True, "GPU": chosen, "arms": arms, "updated_at_utc": now()})
    write_json(output / "preflight_status.json", {"stage": "passed", "GPU": chosen, "updated_at_utc": now()})


def verify_experiment(output):
    manifest = read_json(Path(output) / "experiment_manifest.json")
    for row in manifest["files"]:
        if ontology_adapter.sha256(safe_child(output, row["path"])) != row["sha256"]:
            raise ValueError(f"Frozen experiment file changed: {row['path']}")


def scalar(value):
    return isinstance(value, (float, int)) and math.isfinite(value)


def pooled_metrics(output, rows, expected_folds):
    """Compute a single cross-validation readout after every test fold finishes."""
    output = Path(output)
    if len(rows) != 2 * len(expected_folds) or any(row["stage"] != "complete" for row in rows):
        return None
    cached = read_json(output / "pooled_metrics.json")
    if cached:
        return cached

    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            average = (start + end - 1) / 2
            for index in order[start:end]:
                result[index] = average
            start = end
        return result

    def correlation(x, y):
        try:
            return statistics.correlation(x, y)
        except statistics.StatisticsError:
            return None

    result = {"scope": "Pooled predictions from each pair's single held-out CV fold", "arms": {}}
    for arm in ("baseline", "augmented"):
        observed, predicted, files = [], [], []
        for row in sorted((row for row in rows if row["arm"] == arm), key=lambda item: item["fold"]):
            path = Path(row["run"]) / "predictions.tsv.gz"
            if not path.is_file():
                return None
            with gzip.open(path, "rt") as stream:
                header = next(stream).rstrip().split("\t")
                target_index, prediction_index = header.index("observed"), header.index("predicted")
                for line in stream:
                    fields = line.rstrip().split("\t")
                    observed.append(float(fields[target_index]))
                    predicted.append(float(fields[prediction_index]))
            files.append({"path": str(path), "sha256": ontology_adapter.sha256(path)})
        if any(not math.isfinite(value) for value in observed + predicted):
            raise ValueError("Pooled predictions contain nonfinite values")
        mse = statistics.mean((x - y) ** 2 for x, y in zip(observed, predicted))
        result["arms"][arm] = {"n": len(observed), "mse": mse, "rmse": math.sqrt(mse),
                                "pearson": correlation(observed, predicted),
                                "spearman": correlation(ranks(observed), ranks(predicted)),
                                "prediction_files": files}
    write_json(output / "pooled_metrics.json", result)
    return result


def summarize(output, config, jobs, augmentation_state):
    rows = []
    for key, job in jobs.items():
        metrics = read_json(Path(job["output"]) / "metrics.json", {})
        complete = metrics.get("status") == "complete"
        if complete:
            job["stage"] = "complete"
        progress = read_json(Path(job["output"]) / "progress.json", {})
        rows.append({"arm": job["arm"], "fold": job["fold"], "run": job["output"],
                     "stage": job["stage"], "progress": progress,
                     "reused_completed_run": bool(job.get("reused_completed_run")),
                     "selected_epoch": metrics.get("selected_epoch"),
                     "parameter_count": metrics.get("parameter_count"), "architecture": metrics.get("architecture"),
                     "metrics": metrics.get("test", {})})
    aggregates = {}
    for arm in ("baseline", "augmented"):
        complete = [row for row in rows if row["arm"] == arm and row["stage"] == "complete"]
        values = {}
        for name in METRICS:
            numbers = [row["metrics"][name] for row in complete if scalar(row["metrics"].get(name))]
            values[name] = {"n_folds": len(numbers), "mean": statistics.mean(numbers) if numbers else None,
                            "sample_std": statistics.stdev(numbers) if len(numbers) > 1 else None}
        aggregates[arm] = {"completed_folds": len(complete), "metrics": values}
    paired = []
    for fold in config["data"]["folds"]:
        arms = {row["arm"]: row for row in rows if row["fold"] == fold and row["stage"] == "complete"}
        if set(arms) == {"baseline", "augmented"}:
            delta = {name: arms["augmented"]["metrics"][name] - arms["baseline"]["metrics"][name]
                     for name in METRICS if scalar(arms["augmented"]["metrics"].get(name))
                     and scalar(arms["baseline"]["metrics"].get(name))}
            paired.append({"fold": fold, "augmented_minus_baseline": delta})
    finished = all(job["stage"] in {"complete", "failed", "augmentation_failed"} for job in jobs.values())
    state = ("complete" if all(job["stage"] == "complete" for job in jobs.values())
             else "completed_with_failures" if finished else "running")
    result = {"updated_at_utc": now(), "status": state, "augmentation": augmentation_state,
              "folds_expected": config["data"]["folds"], "runs": rows,
              "arm_aggregates": aggregates, "paired_folds": paired,
              "paired_metric_delta_means": {name: statistics.mean([p["augmented_minus_baseline"][name]
                    for p in paired if name in p["augmented_minus_baseline"]])
                    for name in METRICS if any(name in p["augmented_minus_baseline"] for p in paired)},
              "checkpoint_selection": "Highest validation Pearson within each run; held-out test measured for the selected checkpoint"}
    result["pooled_metrics"] = pooled_metrics(output, rows, config["data"]["folds"])
    write_json(Path(output) / "comparison.json", result)
    lines = ["# DrugCell pruned-GO augmentation comparison", "", f"Status: {state}.", "",
             config.get("comparison_description", "Released pruned GO and its additive augmentation share data, grouped folds, model seed and training settings."),
             "Checkpoints use validation Pearson. The table contains held-out test metrics.", "",
             "| Arm | Fold | Stage | Spearman ↑ | Pearson ↑ | MSE ↓ | RMSE ↓ | Selected epoch |",
             "|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        numbers = [f"{row['metrics'][name]:.8f}" if scalar(row["metrics"].get(name)) else "pending"
                   for name in ("spearman", "pearson", "mse", "rmse")]
        lines.append("| " + " | ".join([row["arm"], str(row["fold"]), row["stage"], *numbers,
                                       str(row["selected_epoch"] or "pending")]) + " |")
    lines += ["", "Aggregates use completed folds only; paired differences use folds completed in both arms.", "",
              f"Augmentation stage: `{augmentation_state.get('stage')}`.", ""]
    temporary = Path(output) / "REPORT.md.tmp"
    temporary.write_text("\n".join(lines))
    temporary.replace(Path(output) / "REPORT.md")
    return result, finished


def eligible_gpu_rows(rows, streaks, stable_polls):
    eligible = [row for row in rows if not row["has_compute_process"]
                and row["utilization_percent"] <= 5 and row["free_mib"] >= 16384]
    streaks = {row["uuid"]: streaks.get(row["uuid"], 0) + 1 for row in eligible}
    return [row for row in eligible if streaks[row["uuid"]] >= stable_polls], streaks


class RecordedProcess:
    """Monitor an already launched child after its supervisor is restarted."""

    def __init__(self, pid, output):
        self.pid, self.output = pid, Path(output)

    def poll(self):
        metrics = read_json(self.output / "metrics.json", {})
        try:
            command = Path(f"/proc/{self.pid}/cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            return 0 if metrics.get("status") == "complete" else 1
        if str(self.output).encode() not in command:
            return 0 if metrics.get("status") == "complete" else 1
        return None


def apply_completed_references(jobs, config):
    """Bind immutable, completed baseline artifacts to read-only comparison jobs."""
    for key, reference in config.get("completed_run_references", {}).items():
        if key not in jobs or jobs[key]["arm"] != "baseline":
            raise ValueError("Only completed baseline runs can be reused")
        reference_path = Path(reference["path"])
        for name, expected in reference["files"].items():
            if ontology_adapter.sha256(reference_path / name) != expected:
                raise ValueError(f"Completed baseline reference changed: {key}/{name}")
        if read_json(reference_path / "metrics.json", {}).get("status") != "complete":
            raise ValueError("Reused baseline must be complete")
        jobs[key].update(output=str(reference_path), reused_completed_run=True)


def supervise(output, max_concurrent=2, poll_seconds=30, stable_polls=3, threads=8):
    output = Path(output).resolve()
    config = read_json(output / "config.json")
    project = Path(config["project_root"])
    gpu_queue.ROOT = project
    folds = config["data"]["folds"]
    jobs = {f"{arm}_{fold}": {"arm": arm, "fold": fold,
            "output": str(output / "runs" / arm / f"fold_{fold}"),
            "stage": "waiting_for_unoccupied_gpu" if arm == "baseline" else "waiting_for_knowledge"}
            for fold in folds for arm in ("baseline", "augmented")}
    apply_completed_references(jobs, config)
    running, streaks = {}, {}
    for key, job in jobs.items():
        previous = read_json(Path(job["output"]) / "queue_status.json", {})
        metrics = read_json(Path(job["output"]) / "metrics.json", {})
        if metrics.get("status") == "complete":
            job["stage"] = "complete"
        elif previous.get("stage") == "running":
            job["stage"] = "running"
            running[key] = {"process": RecordedProcess(previous["training_pid"], job["output"]),
                            "gpu_lock": None, "gpu": previous["selected_gpu"], "log": None}
        elif previous.get("stage") == "failed":
            job["stage"] = "failed"
    augmentation = read_json(output / "augmentation_status.json", {"stage": "waiting_for_knowledge"})
    if augmentation.get("stage") == "ontology_frozen":
        if ontology_adapter.sha256(output / "augmentation/drugcell_ont.txt") != augmentation["ontology_sha256"]:
            raise ValueError("Augmented ontology changed after freezing")
        for job in jobs.values():
            if job["arm"] == "augmented" and job["stage"] == "waiting_for_knowledge":
                job["stage"] = "waiting_for_unoccupied_gpu"
    elif augmentation.get("stage") == "failed":
        for job in jobs.values():
            if job["arm"] == "augmented" and job["stage"] == "waiting_for_knowledge":
                job["stage"] = "augmentation_failed"
    while True:
        verify_experiment(output)
        for key, child in list(running.items()):
            code = child["process"].poll()
            if code is None:
                continue
            if child["gpu_lock"]:
                child["gpu_lock"].close()
            if child["log"]:
                child["log"].close()
            job = jobs[key]
            metrics = read_json(Path(job["output"]) / "metrics.json", {})
            job["stage"] = "complete" if code == 0 and metrics.get("status") == "complete" else "failed"
            write_json(Path(job["output"]) / "queue_status.json", {**job, "updated_at_utc": now(), "returncode": code,
                        "training_pid": child["process"].pid, "selected_gpu": child["gpu"]})
            del running[key]
        if augmentation.get("stage") == "waiting_for_knowledge":
            workspace = Path(config["knowledge"]["augmentation_workspace"])
            pipeline = read_json(workspace / "status.json", {})
            augmentation["pipeline"] = pipeline
            try:
                if pipeline.get("status") == "failed":
                    raise RuntimeError(f"Knowledge pipeline failed: {pipeline.get('error')}")
                if pipeline.get("status") in TERMINAL_PIPELINE:
                    report = prepare_augmentation(output, config)
                    augmentation = {"stage": "ontology_frozen", "updated_at_utc": now(),
                                    "projection_counts": report["projection_counts"],
                                    "ontology_sha256": ontology_adapter.sha256(output / "augmentation/drugcell_ont.txt")}
                    for job in jobs.values():
                        if job["arm"] == "augmented":
                            job["stage"] = "waiting_for_unoccupied_gpu"
            except Exception as error:
                augmentation = {"stage": "failed", "updated_at_utc": now(), "error": f"{type(error).__name__}: {error}",
                                "traceback": traceback.format_exc()}
                for job in jobs.values():
                    if job["arm"] == "augmented":
                        job["stage"] = "augmentation_failed"
            write_json(output / "augmentation_status.json", augmentation)
        ready = []
        gpu_error = None
        if len(running) < max_concurrent and any(job["stage"] == "waiting_for_unoccupied_gpu" for job in jobs.values()):
            try:
                ready, streaks = eligible_gpu_rows(gpu_queue.gpu_candidates(), streaks, stable_polls)
            except (subprocess.CalledProcessError, OSError) as error:
                gpu_error = str(error)
                streaks = {}
        for key, job in jobs.items():
            if len(running) >= max_concurrent or not ready:
                break
            if job["stage"] != "waiting_for_unoccupied_gpu":
                continue
            chosen, gpu_lock = gpu_queue.reserve_gpu(ready)
            if gpu_lock is None:
                break
            ready = [row for row in ready if row["uuid"] != chosen["uuid"]]
            ontology = output / ("baseline/drugcell_ont.txt" if job["arm"] == "baseline" else "augmentation/drugcell_ont.txt")
            if job["arm"] == "augmented" and ontology_adapter.sha256(ontology) != augmentation["ontology_sha256"]:
                gpu_lock.close()
                raise ValueError("Augmented ontology changed after freezing")
            run = Path(job["output"])
            run.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment.update(CUDA_VISIBLE_DEVICES=chosen["uuid"], PYTHONDONTWRITEBYTECODE="1",
                               OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS=str(threads))
            try:
                cuda_preflight(output, config, environment, gpu_lock, chosen)
            except Exception:
                gpu_lock.close()
                raise
            interpreter = Path(config["runtime"]["python"])
            if not interpreter.is_absolute():
                interpreter = project / interpreter
            command = [str(interpreter), "-u", str(output / "code/run_drugcell.py"), "--config", str(output / "config.json"),
                       "--fold", str(job["fold"]), "--ontology", str(ontology), "--output", str(run), "--device", "cuda", "--threads", str(threads)]
            log = (run / "run.log").open("a", buffering=1)
            try:
                child = subprocess.Popen(command, cwd=project, env=environment, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT, pass_fds=(gpu_lock.fileno(),))
            except Exception:
                gpu_lock.close()
                log.close()
                raise
            job["stage"] = "running"
            running[key] = {"process": child, "gpu_lock": gpu_lock, "gpu": chosen, "log": log}
            write_json(run / "queue_status.json", {**job, "training_pid": child.pid, "selected_gpu": chosen,
                        "command": command, "started_at_utc": now()})
        report, terminal = summarize(output, config, jobs, augmentation)
        status = {"status": report["status"], "updated_at_utc": now(), "supervisor_pid": os.getpid(),
                  "running_jobs": {key: child["process"].pid for key, child in running.items()},
                  "job_stages": {key: job["stage"] for key, job in jobs.items()},
                  "augmentation_stage": augmentation["stage"], "max_concurrent": max_concurrent,
                  "stable_idle_polls": streaks, "gpu_query_error": gpu_error, "next_check_seconds": poll_seconds}
        write_json(output / "run_status.json", status)
        print(json.dumps(status), flush=True)
        if terminal:
            return 0 if report["status"] == "complete" else 1
        time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/drugcell_comparison.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/drugcell/comparison_001")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--max-concurrent", type=int, default=2)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--stable-polls", type=int, default=3)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if min(args.max_concurrent, args.poll_seconds, args.stable_polls, args.threads) < 1:
        parser.error("Concurrency, polling, stability and thread counts must be positive")
    output = args.output.resolve()
    if not args.resume:
        initialize(args.config, output, args.workspace)
    if args.prepare_only:
        print(json.dumps({"status": "prepared", "output": str(output)}))
        return 0
    with (output / "supervisor.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.write(str(os.getpid()))
        lock.flush()
        try:
            return supervise(output, args.max_concurrent, args.poll_seconds, args.stable_polls, args.threads)
        except Exception as error:
            write_json(output / "supervisor_error.json", {"status": "failed", "updated_at_utc": now(),
                       "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc(),
                       "compute_process_policy": "Existing child and external compute processes remain running"})
            raise


if __name__ == "__main__":
    raise SystemExit(main())
