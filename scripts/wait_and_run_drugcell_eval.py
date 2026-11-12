"""Wait for a frozen task knowledge product, then run the predeclared evaluation."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

import drugcell_ontology as ontology
import prepare_drugcell_pruned_experiment as preparation
import run_drugcell_comparison_optimized as comparison


def verify_schedule(plan_path, plan):
    queue = Path(plan_path).resolve().parent
    manifest = comparison.read_json(queue / "schedule_manifest.json")
    for item in manifest["files"]:
        path = comparison.safe_child(queue, item["path"])
        if ontology.sha256(path) != item["sha256"]:
            raise ValueError(f"Scheduled evaluation input changed: {item['path']}")
    for item in plan["scientific_inputs"]:
        if ontology.sha256(Path(plan["knowledge_workspace"]) / item["path"]) != item["sha256"]:
            raise ValueError("The augmentation task or original scientific inputs changed")
    for item in plan["baseline_contract"]:
        if ontology.sha256(Path(plan["baseline_experiment"]) / item["path"]) != item["sha256"]:
            raise ValueError("Matched baseline contract changed")
    for item in plan.get("external_scientific_inputs",[]):
        if ontology.sha256(item["path"])!=item["sha256"]:
            raise ValueError("Declared complete-GO or gene-map input changed")


def knowledge_readiness(plan):
    workspace = Path(plan["knowledge_workspace"])
    state = comparison.read_json(workspace / "status.json", {})
    if state.get("status") == "failed":
        raise RuntimeError("Knowledge pipeline failed: " + json.dumps(state))
    if state.get("status") not in comparison.TERMINAL_PIPELINE:
        return False, state
    # A terminal status and a verified artifact manifest jointly open evaluation.
    manifest, state = comparison.verify_frozen_product(workspace)
    state = {**state, "knowledge_freeze_sha256": ontology.sha256(workspace / "knowledge/freeze_manifest.json")}
    if plan.get("module_graph_product"):
        from export_drugcell_module_graph import verify_product
        product = Path(plan["module_graph_product"])
        verify_product(product)
        state["module_graph_freeze_sha256"] = ontology.sha256(product / "freeze_manifest.json")
    return True, state


def verify_prepared(plan):
    output = Path(plan["experiment_output"])
    comparison.verify_experiment(output)
    config = comparison.read_json(output / "config.json")
    if config["released_training_settings"] != plan["training"] or config["model_seed"] != plan["model_seed"]:
        raise ValueError("Prepared training differs from the scheduled protocol")
    if config["data"]["folds"] != plan["folds"]:
        raise ValueError("Prepared folds differ from the scheduled protocol")
    manifest = comparison.read_json(output / "augmentation/pruning_manifest.json")
    for key, value in plan["pruning"].items():
        if manifest["policy"][key] != value:
            raise ValueError("Pruning differs from the scheduled policy")
    source_hash = comparison.read_json(output / "pruning_summary.json")["source_knowledge_freeze_sha256"]
    if source_hash != ontology.sha256(Path(plan["knowledge_workspace"]) / "knowledge/freeze_manifest.json"):
        raise ValueError("Prepared experiment uses a different knowledge product")
    if plan.get("module_graph_product"):
        if config["knowledge"].get("module_graph_freeze_sha256") != ontology.sha256(Path(plan["module_graph_product"]) / "freeze_manifest.json"):
            raise ValueError("Prepared experiment uses a different module graph")
    if plan.get("full_go_source"):
        if config["knowledge"].get("full_go_source")!=plan["full_go_source"]:
            raise ValueError("Prepared control and augmentation use a different full-GO basis")
        for arm,p in config["knowledge"]["input_projections"].items():
            for key in ("gene_map","projection"):
                if ontology.sha256(p[key])!=p[key+"_sha256"]:
                    raise ValueError("Prepared model input projection changed")
    return config


def cpu_smoke(plan, config, arm="augmented"):
    output = Path(plan["experiment_output"])
    directory=output/("cpu_smoke" if arm=="augmented" else "cpu_smoke_"+arm)
    selected_ontology=Path(config["knowledge"][arm+"_ontology"])
    cached = comparison.read_json(directory / "metrics.json", {})
    if cached:
        if cached.get("status") != "smoke_complete":
            raise ValueError("Existing CPU smoke verification is incomplete")
        if cached["inputs"]["ontology"]["sha256"] != ontology.sha256(selected_ontology):
            raise ValueError("CPU smoke verified a different ontology")
        return
    smoke_config = json.loads(json.dumps(config))
    smoke_config["released_training_settings"]["batch_size"] = 32
    smoke_config_path=output/("cpu_smoke_config.json" if arm=="augmented" else "cpu_smoke_"+arm+"_config.json")
    comparison.write_json(smoke_config_path, smoke_config)
    interpreter = Path(config["runtime"]["python"])
    if not interpreter.is_absolute():
        interpreter = Path(config["project_root"]) / interpreter
    command = [str(interpreter), "-u", str(output / "code/run_drugcell.py"),
               "--config", str(smoke_config_path), "--fold", str(plan["folds"][0]),
               "--ontology", str(selected_ontology),
               "--output", str(directory), "--device", "cpu", "--threads", "2",
               "--max-epochs", "3", "--smoke-rows", "256"]
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1",
                       OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
    with (output / (directory.name+".log")).open("a") as log:
        subprocess.run(command, cwd=config["project_root"], env=environment, stdin=subprocess.DEVNULL,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    if comparison.read_json(directory / "metrics.json", {}).get("status") != "smoke_complete":
        raise RuntimeError("CPU training/evaluation smoke did not complete")


def write_results(queue, plan):
    output = Path(plan["experiment_output"])
    rows = []
    for reference in plan["comparison_references"]:
        for filename, digest in reference["files"].items():
            if ontology.sha256(Path(reference["directory"]) / filename) != digest:
                raise ValueError("Historical result reference changed")
        pooled = comparison.read_json(Path(reference["directory"]) / "pooled_metrics.json")["arms"][reference["arm"]]
        aggregate = comparison.read_json(Path(reference["directory"]) / "comparison.json")["arm_aggregates"][reference["arm"]]
        rows.append({"label": reference["label"], "pooled": pooled,
                     "per_drug_spearman_mean": aggregate["metrics"]["per_drug_spearman_mean"]["mean"]})
    current = comparison.read_json(output / "pooled_metrics.json")["arms"]["augmented"]
    aggregate = comparison.read_json(output / "comparison.json")["arm_aggregates"]["augmented"]
    if plan.get("include_current_baseline"):
        baseline = comparison.read_json(output / "pooled_metrics.json")["arms"]["baseline"]
        baseline_aggregate = comparison.read_json(output / "comparison.json")["arm_aggregates"]["baseline"]
        rows.append({"label":plan.get("baseline_label","Paired full GO control after pruning"),"pooled":baseline,
            "per_drug_spearman_mean":baseline_aggregate["metrics"]["per_drug_spearman_mean"]["mean"]})
    rows.append({"label": plan.get("result_label", "Latest prompts and skills, adaptive augmentation then pruning"), "pooled": current,
                 "per_drug_spearman_mean": aggregate["metrics"]["per_drug_spearman_mean"]["mean"]})
    comparison.write_json(queue / "results.json", {"scope": "Pooled held-out predictions and fold-averaged per-drug Spearman", "rows": rows})
    lines = ["# " + plan.get("report_title", "DrugCell evaluation after adaptive GO augmentation"), "", "Status: complete.", "",
             "Pooled metrics combine the five held-out test folds. Per-drug Spearman is averaged within each fold and then across folds.", "",
             "| Knowledge version | Spearman ↑ | Pearson ↑ | MSE ↓ | Mean per-drug Spearman ↑ |",
             "|---|---:|---:|---:|---:|"]
    for row in rows:
        m = row["pooled"]
        lines.append(f"| {row['label']} | {m['spearman']:.6f} | {m['pearson']:.6f} | {m['mse']:.8f} | {row['per_drug_spearman_mean']:.6f} |")
    lines += ["", f"Full fold report: `{output / 'REPORT.md'}`.", ""]
    (queue / "REPORT.md").write_text("\n".join(lines))


def run(plan_path):
    plan_path = Path(plan_path).resolve()
    queue = plan_path.parent
    plan = comparison.read_json(plan_path)

    def status(phase, **extra):
        record = {"phase": phase, "updated_at_utc": comparison.now(), "queue_pid": os.getpid(),
                  "experiment_output": plan["experiment_output"], **extra}
        comparison.write_json(queue / "status.json", record)
        if phase != "complete":
            lines = ["# Scheduled DrugCell evaluation", "", f"Phase: `{phase}`.", "",
                     "The fixed protocol is recorded in [PLAN.md](PLAN.md). Live scheduling state is in [status.json](status.json).", "",
                     f"Experiment output: `{plan['experiment_output']}`.", ""]
            if extra.get("error"):
                lines += ["Execution detail: " + extra["error"], ""]
            (queue / "REPORT.md").write_text("\n".join(lines))
        if plan.get("module_report_directory"):
            directory=Path(plan["module_report_directory"]);directory.mkdir(parents=True,exist_ok=True)
            pipeline=comparison.read_json(Path(plan["knowledge_workspace"])/"status.json",{})
            comparison.write_json(directory/"status.json",{**record,"augmentation":pipeline})
            if phase=="complete":
                (directory/"REPORT.md").write_text((queue/"REPORT.md").read_text())
            else:
                lines=["# Complete GO database augmentation and DrugCell evaluation","",f"Phase: `{phase}`.","",
                    f"Augmentation: {pipeline.get('status','pending')}; current stage: {pipeline.get('phase','pending')}.",
                    f"Committed batches: {pipeline.get('completed_batches',0)} / {plan.get('module_batches','unknown')}.",
                    f"Current batch: {pipeline.get('batch','not reported')}.","",
                    "Order: complete GO-BP, reviewed database augmentation, freeze, matched pruning, identifier-bound gene projection, paired five-fold training and evaluation.","",
                    f"Evaluation queue: `{queue}`.",f"Experiment output: `{plan['experiment_output']}`.","",
                    "The source versions and execution scope are recorded in [PLAN.md](PLAN.md)."]
                if extra.get("error"):lines += ["",extra["error"]]
                (directory/"REPORT.md").write_text("\n".join(lines)+"\n")
        print(json.dumps(record), flush=True)

    with (queue / "queue.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            while True:
                verify_schedule(plan_path, plan)
                ready, knowledge = knowledge_readiness(plan)
                if ready:
                    break
                status("waiting_for_knowledge", knowledge_status=knowledge.get("status"),
                       knowledge_phase=knowledge.get("phase"), knowledge_round=knowledge.get("round"),
                       knowledge_batch=knowledge.get("batch"), completed_batches=knowledge.get("completed_batches",0))
                time.sleep(plan["knowledge_poll_seconds"])
            status("preparing_frozen_experiment", knowledge=knowledge)
            output = Path(plan["experiment_output"])
            if not output.exists():
                if plan.get("full_go_source"):
                    from prepare_full_go_drugcell_experiment import prepare as full_preparation
                    full_preparation(plan,queue/"scripts")
                else:
                    preparation.prepare(plan["baseline_experiment"], output, plan["knowledge_workspace"], queue / "scripts",
                                        module_graph_product=plan.get("module_graph_product"))
            config = verify_prepared(plan)
            status("cpu_verification")
            if plan.get("full_go_source"):
                cpu_smoke(plan, config, arm="baseline")
            cpu_smoke(plan, config)
            status("starting_gpu_queue", max_concurrent=plan["max_concurrent"])
            command = ["/usr/bin/python3", "-u", str(output / "code/run_drugcell_comparison.py"),
                       "--resume", "--output", str(output), "--max-concurrent", str(plan["max_concurrent"]),
                       "--poll-seconds", "15", "--stable-polls", "3", "--threads", "8"]
            with (output / "supervisor.log").open("a") as log:
                child = subprocess.Popen(command, cwd=config["project_root"], stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), start_new_session=True)
            receipt = {"supervisor_pid": child.pid, "started_at_utc": comparison.now(),
                       "command": command, "scheduled_by": str(plan_path)}
            comparison.write_json(output / "launch.json", receipt)
            status("evaluation_running", supervisor_pid=child.pid, max_concurrent=plan["max_concurrent"])
            code = child.wait()
            if code or comparison.read_json(output / "run_status.json", {}).get("status") != "complete":
                raise RuntimeError(f"DrugCell evaluation ended with return code {code}; inspect its report and logs")
            write_results(queue, plan)
            status("complete", report=str(queue / "REPORT.md"))
        except Exception as error:
            status("failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    run(args.plan)


if __name__ == "__main__":
    main()
