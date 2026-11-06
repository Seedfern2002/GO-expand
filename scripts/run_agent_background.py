#!/usr/bin/env python3
"""Launch or supervise a detached, task-wide Codex batch experiment."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
STAGES = ("planner", "retriever", "reviewer")


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(run_dir):
    stages = {}
    for name in STAGES:
        directory = run_dir / name
        if not (directory / "execution.json").exists():
            continue
        execution = read_json(directory / "execution.json")
        usage = {}
        queries = 0
        events_path = directory / "events.jsonl"
        if events_path.exists():
            for line in events_path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "turn.completed":
                    usage = event.get("usage", {})
                item = event.get("item", {})
                if event.get("type") == "item.completed" and item.get("type") == "web_search":
                    action = item.get("action", {})
                    if action.get("type") == "search":
                        queries += len(action.get("queries") or ([action["query"]] if action.get("query") else []))
        stages[name] = {"status": execution["status"], "usage": usage, "search_queries": queries}
        if execution.get("started_at_utc") and execution.get("finished_at_utc"):
            stages[name]["seconds"] = round((datetime.fromisoformat(execution["finished_at_utc"]) - datetime.fromisoformat(execution["started_at_utc"])).total_seconds(), 2)
    candidates_path = run_dir / "retriever/result.json"
    candidates = read_json(candidates_path) if candidates_path.exists() and candidates_path.stat().st_size else {}
    review_path = run_dir / "reviewer/result.json"
    review = read_json(review_path) if review_path.exists() and review_path.stat().st_size else {}
    batches = candidates.get("batches", [])
    decisions = review.get("batch_decisions", [])
    approved = [item for item in decisions if item["verdict"] == "accept"]
    coverage_reports = {}
    for batch in batches:
        path = Path(batch["coverage_report_path"])
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            coverage_reports[batch["id"]] = read_json(path)
    return {
        "generated_at_utc": now(), "run_directory": str(run_dir), "stages": stages,
        "batch_count": len(batches), "decision_counts": dict(Counter(item["verdict"] for item in decisions)),
        "approved_batches": approved, "coverage": candidates.get("coverage", []),
        "coverage_reports": coverage_reports,
        "total_search_queries_observed": sum(item["search_queries"] for item in stages.values()),
        "projection_status": "not_projected",
    }


def run_stage(run_dir, stage, job, update):
    task_path = run_dir / "task.json"
    for attempt in range(2):
        update(phase=stage, attempt=attempt + 1)
        print(f"{now()} Starting {stage}, attempt {attempt + 1}", flush=True)
        prepare = [sys.executable, str(ROOT / "scripts/prepare_agent_stage.py"), "--stage", stage, "--task", str(task_path), "--run-dir", str(run_dir), "--codex-bin", job["codex_bin"]]
        if stage != "planner":
            prepare.extend(["--plan", str(run_dir / "planner/result.json")])
        if stage == "reviewer":
            prepare.extend(["--candidates", str(run_dir / "retriever/result.json")])
        subprocess.run(prepare, cwd=ROOT, check=True, timeout=60)
        command = [sys.executable, str(ROOT / "scripts/run_agent_stage.py"), "--stage-dir", str(run_dir / stage)]
        with (run_dir / f"{stage}.log").open("x") as log:
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            update(child_pid=child.pid)
            try:
                code = child.wait(timeout=job["stage_timeout_seconds"])
            except subprocess.TimeoutExpired:
                # This process group belongs solely to the stage we just created.
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                raise RuntimeError(f"Stage timeout: {stage}")
        update(child_pid=None)
        if code == 0:
            print(f"{now()} Completed {stage}", flush=True)
            return
        execution_path = run_dir / stage / "execution.json"
        execution = read_json(execution_path) if execution_path.exists() else {}
        result_path = run_dir / stage / "result.json"
        if attempt == 0 and execution.get("exit_code") == 0 and execution.get("error") and result_path.exists() and result_path.stat().st_size:
            archive = run_dir / "attempts" / f"{stage}_1"
            archive.parent.mkdir(exist_ok=True)
            (run_dir / stage).rename(archive)
            (run_dir / f"{stage}.log").rename(archive / "controller.log")
            task = read_json(run_dir / "task.json")
            task["validation_feedback"] = {
                "error": execution["error"], "previous_result_path": str(archive / "result.json"),
                "instruction": "Repair the failed output contract. Reuse the previous evidence and task-wide policies; avoid repeating searches. Keep workflow helpers in audit_policy, and use only task.candidate_categories for augmentations."
            }
            task_path = run_dir / f"task.{stage}.repair.json"
            write_json(task_path, task)
            write_json(archive / "retry.json", {"retry_at_utc": now(), "original_stage_directory": str(run_dir / stage), "validation_error": execution["error"]})
            print(f"{now()} Retrying {stage} once after artifact validation failure; archived original output at {archive}", flush=True)
            continue
        raise RuntimeError(f"Stage {stage} failed with exit code {code}; see {stage}.log and {stage}/stderr.log")


def worker(run_dir):
    with (run_dir / "job.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        job = read_json(run_dir / "job.json")
        state = {"status": "running", "phase": "starting", "pid": os.getpid(), "started_at_utc": now(), "run_directory": str(run_dir)}
        mutex = threading.Lock()
        stop = threading.Event()

        def update(**values):
            with mutex:
                state.update(values)
                state["heartbeat_at_utc"] = now()
                write_json(run_dir / "status.json", state)

        def heartbeat():
            while not stop.wait(15):
                update()

        update()
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            for stage in STAGES:
                for path, expected in job["source_hashes"].items():
                    if digest(ROOT / path) != expected:
                        raise RuntimeError(f"Experiment code or prompt changed during this run: {path}")
                run_stage(run_dir, stage, job, update)
            summary = summarize(run_dir)
            write_json(run_dir / "summary.json", summary)
            gaps = any(item.get("status") != "covered" for item in summary["coverage"])
            if not summary["approved_batches"]:
                outcome = "completed_without_approved_batches"
            elif gaps or any(item["verdict"] != "accept" for item in read_json(run_dir / "reviewer/result.json")["batch_decisions"]):
                outcome = "completed_with_gaps"
            else:
                outcome = "completed"
            update(status=outcome, phase="finished", finished_at_utc=now())
        except Exception as exc:
            traceback.print_exc()
            update(status="failed", error=f"{type(exc).__name__}: {exc}", finished_at_utc=now())
            try:
                write_json(run_dir / "summary.json", summarize(run_dir))
            except Exception:
                traceback.print_exc()
        finally:
            stop.set()
            thread.join(timeout=2)
            status = read_json(run_dir / "status.json")
            summary = read_json(run_dir / "summary.json") if (run_dir / "summary.json").exists() else {}
            report = ["# Task-wide augmentation background test", "", f"Status: {status['status']}", f"Phase: {status['phase']}", f"Run: {run_dir}", "", f"Materialized batches: {summary.get('batch_count', 0)}", f"Approved batches: {len(summary.get('approved_batches', []))}", "", "See summary.json for coverage, timing, token usage, and approved artifact paths."]
            if status.get("error"):
                report.extend(["", f"Error: {status['error']}"])
            (run_dir / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
            print(json.dumps(status, ensure_ascii=False), flush=True)
        return 1 if state["status"] == "failed" else 0


def launch(args):
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT / "outputs"):
        raise ValueError("Use a run directory under the project's outputs directory")
    if directory.exists():
        raise ValueError("Run directory already exists; choose a new run")
    codex = Path(shutil.which(args.codex_bin) or args.codex_bin).resolve()
    if not codex.is_file() or not os.access(codex, os.X_OK):
        raise ValueError("Codex executable is missing")
    if shutil.disk_usage(ROOT).free < 2 * 1024**3:
        raise ValueError("Less than 2 GiB free disk space")
    task = read_json(args.task)
    if task.get("execution", {}).get("workflow") != "task_batch":
        raise ValueError("This job requires task_batch workflow")
    universe = Path(task["scope"]["gene_universe_path"])
    if not universe.is_absolute():
        universe = ROOT / universe
    directory.mkdir(parents=True)
    inputs = directory / "inputs"
    inputs.mkdir()
    shutil.copy2(universe, inputs / "gene_universe.json")
    task["scope"]["gene_universe_path"] = str(inputs / "gene_universe.json")
    references = []
    for index, name in enumerate(task.get("reference_files", [])):
        source = Path(name)
        if not source.is_absolute():
            source = ROOT / source
        target = inputs / f"context_{index}{source.suffix}"
        shutil.copy2(source, target)
        references.append(str(target))
    task["reference_files"] = references
    task["execution"]["approval_mode"] = "auto_review"
    task["retrieval_budget"]["max_download_bytes"] = min(task["retrieval_budget"]["max_download_bytes"], 256 * 1024**2)
    task["background_test"] = {
        "artifact_root": str(directory),
        "scope": "Run task-wide acquisition and review across the complete declared universe. Prioritize reusable bulk Reactome and hu.MAP membership processing; record other knowledge families as pending when appropriate.",
        "implementation": "You are authorized to implement missing source connectors and row validators under artifact_root/connectors and execute them with existing local Python environments. Keep them reusable. Write all new files under artifact_root; do not modify shared project code, configurations, original GO, or baseline artifacts.",
        "data_contract": "Store normalized records as JSONL with stable record IDs, subject/object identifiers and labels, explicit relation, polarity, context, evidence references, and source confidence. Provenance, validation and coverage reports are separate files. All rows require programmatic checks; batch reports use the exact fields required by scripts/run_agent_stage.py.",
        "review_contract": "Save a machine-readable audit report for each batch with review_method, sampling_seed, sampled_record_ids, findings, exclusions and source checks. Distinguish source-policy/sample auditing from per-record literature verification.",
        "completion": "Use task_batch schema. Return pending directions explicitly rather than inventing artifacts. Keep source/policy decisions independent of downstream results. Do not launch training, GPU work, other background jobs, or additional agents.",
        "resources": "At most 2 CPU threads, 256 MiB aggregate downloaded data, and the task's bounded literature budget. Prefer small official bulk files over raw assay data."
    }
    write_json(directory / "task.json", task)
    tracked = ["scripts/prepare_agent_stage.py", "scripts/run_agent_stage.py", "scripts/run_agent_background.py", "AGENTS.md"]
    tracked += [str(p.relative_to(ROOT)) for p in (ROOT / "prompts/agents").glob("*.md")]
    tracked += [str(p.relative_to(ROOT)) for p in (ROOT / "schemas/agents/batch").glob("*.json")]
    write_json(directory / "job.json", {"created_at_utc": now(), "codex_bin": str(codex), "stage_timeout_seconds": args.stage_timeout_seconds, "source_hashes": {name: digest(ROOT / name) for name in tracked}})
    write_json(directory / "status.json", {"status": "launching", "phase": "starting", "created_at_utc": now()})
    env = os.environ.copy()
    env.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "PYTHONUNBUFFERED": "1"})
    with (directory / "job.log").open("x") as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", "--run-dir", str(directory)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True, env=env)
    launched = {"pid": child.pid, "run_directory": str(directory), "log": str(directory / "job.log"), "status": str(directory / "status.json"), "started_at_utc": now()}
    write_json(directory / "launch.json", launched)
    write_json(ROOT / "outputs/agents/latest_background.json", launched)
    print(json.dumps(launched, indent=2), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--task", type=Path, default=ROOT / "configs/agent_tasks/gears_norman.json")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--stage-timeout-seconds", type=int, default=1800)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.stage_timeout_seconds <= 0:
        parser.error("stage timeout must be positive")
    return worker(args.run_dir.resolve()) if args.worker else launch(args)


if __name__ == "__main__":
    sys.exit(main())
