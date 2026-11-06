#!/usr/bin/env python3
"""Run a prepared Codex stage, preserve logs, and validate its structured artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import jsonschema


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def unique_ids(items, key):
    ids = [item[key] for item in items]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{key} values must be nonempty and unique")
    return set(ids)


def checked_artifact(name: str, manifest: dict, checksum: str | None = None) -> Path:
    root = Path(manifest["working_directory"]).resolve()
    path = Path(name)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"artifact must be an existing workspace file: {name}")
    if checksum is not None:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != checksum:
            raise ValueError(f"artifact checksum mismatch: {name}")
    return path


def validate_batch_result(stage_dir: Path, manifest: dict, task: dict, result: dict) -> None:
    if manifest["stage"] == "planner":
        unique_ids(result["augmentations"], "id")
        if any(item["category"] not in task["candidate_categories"] for item in result["augmentations"]):
            raise ValueError("plan category is outside the task's candidate categories")
        for key in ("gene_universe_path", "gene_field"):
            if result["scope"][key] != task["scope"][key]:
                raise ValueError("batch plan must retain the task-wide gene universe")
        return
    plan_ids = unique_ids(read_json(stage_dir / "plan.input.json")["augmentations"], "id")
    if manifest["stage"] == "retriever":
        unique_ids(result["batches"], "id")
        if unique_ids(result["coverage"], "plan_item_id") != plan_ids:
            raise ValueError("coverage must account for every plan item")
        universe = read_json(checked_artifact(task["scope"]["gene_universe_path"], manifest))
        universe_size = len(set(universe[task["scope"]["gene_field"]]))
        for batch in result["batches"]:
            if batch["plan_item_id"] not in plan_ids:
                raise ValueError("batch references an unknown plan item")
            checked_artifact(batch["records_path"], manifest, batch["records_sha256"])
            checked_artifact(batch["provenance_path"], manifest)
            validation = read_json(checked_artifact(batch["validation_report_path"], manifest))
            coverage = read_json(checked_artifact(batch["coverage_report_path"], manifest))
            if coverage["universe_size"] != universe_size or coverage["genes_screened"] != universe_size:
                raise ValueError("a materialized batch must screen the complete task gene universe")
            if not 0 <= coverage["genes_annotated"] <= universe_size:
                raise ValueError("invalid annotated-gene count")
            if validation["validated_rows"] != coverage["record_count"] or not 0 <= validation["failed_rows"] <= validation["validated_rows"]:
                raise ValueError("validation must account for every batch row")
        return
    batches = read_json(stage_dir / "candidates.input.json")["batches"]
    expected = unique_ids(batches, "id")
    if unique_ids(result["batch_decisions"], "batch_id") != expected:
        raise ValueError("review must account for every batch exactly once")
    for decision in result["batch_decisions"]:
        audit = read_json(checked_artifact(decision["audit_report_path"], manifest))
        if audit["review_method"] != decision["review_method"]:
            raise ValueError("audit review method differs from the decision")
        if decision["verdict"] == "accept":
            if not decision["approved_records_path"] or not decision["approved_records_sha256"] or not decision["evidence_checked"]:
                raise ValueError("accepted batch requires an approved artifact and checked evidence")
            checked_artifact(decision["approved_records_path"], manifest, decision["approved_records_sha256"])
        elif decision["approved_records_path"] is not None or decision["approved_records_sha256"] is not None:
            raise ValueError("only accepted batches may contain approved artifacts")


def validate_result(stage_dir: Path, manifest: dict, result: dict) -> None:
    jsonschema.Draft202012Validator(read_json(stage_dir / "schema.json")).validate(result)
    task = read_json(stage_dir / "task.input.json")
    if result["task_id"] != task["task_id"]:
        raise ValueError("result task_id differs from input task")
    if manifest.get("workflow", "record") == "task_batch":
        validate_batch_result(stage_dir, manifest, task, result)
        return
    if manifest["stage"] == "planner":
        unique_ids(result["augmentations"], "id")
        allowed = set(task["candidate_categories"])
        if any(item["category"] not in allowed for item in result["augmentations"]):
            raise ValueError("plan category is outside the task's candidate categories")
        return
    plan_ids = unique_ids(read_json(stage_dir / "plan.input.json")["augmentations"], "id")
    if manifest["stage"] == "retriever":
        unique_ids(result["records"], "id")
        if any(record["plan_item_id"] not in plan_ids for record in result["records"]):
            raise ValueError("candidate references an unknown plan item")
        if unique_ids(result["coverage"], "plan_item_id") != plan_ids:
            raise ValueError("coverage must account for every plan item")
        if len(result["records"]) > task["retrieval_budget"]["max_candidate_records"]:
            raise ValueError("candidate record budget exceeded")
        return
    candidates = read_json(stage_dir / "candidates.input.json")["records"]
    expected = unique_ids(candidates, "id")
    if unique_ids(result["decisions"], "candidate_id") != expected:
        raise ValueError("review must cover every candidate exactly once")
    for decision in result["decisions"]:
        record = decision["normalized_record"]
        if decision["verdict"] == "accept":
            if record is None or record["id"] != decision["candidate_id"]:
                raise ValueError("accepted record must retain its candidate id")
            if record["plan_item_id"] not in plan_ids:
                raise ValueError("accepted record references an unknown plan item")
            if not decision["evidence_checked"]:
                raise ValueError("accepted record needs checked evidence")
        elif record is not None:
            raise ValueError("only accepted decisions may contain normalized records")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.stage_dir.resolve()
    manifest = read_json(directory / "manifest.json")
    if (directory / "result.json").exists():
        parser.error("result.json already exists; prepare a new stage directory for another attempt")
    if hashlib.sha256((directory / "prompt.md").read_bytes()).hexdigest() != manifest["prompt_sha256"]:
        parser.error("prompt changed since preparation; prepare a new stage with the revised inputs")
    for name in ("task", "plan", "candidates", "schema"):
        if name in manifest["inputs"]:
            snapshot = directory / ("schema.json" if name == "schema" else f"{name}.input.json")
            if hashlib.sha256(snapshot.read_bytes()).hexdigest() != manifest["inputs"][name]["sha256"]:
                parser.error(f"{name} snapshot changed since preparation")
    schema = read_json(directory / "schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    references = []
    for name in read_json(directory / "task.input.json").get("reference_files", []):
        path = Path(name)
        if not path.is_absolute():
            path = Path(manifest["working_directory"]) / path
        references.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    command = manifest["command"]
    version = subprocess.run([command[0], "--version"], capture_output=True, text=True, check=True)
    execution = {
        "status": "running", "started_at_utc": now(),
        "cli_version": version.stdout.strip(), "command": command,
        "requested_model": manifest["requested_model"],
        "requested_reasoning_effort": manifest.get("requested_reasoning_effort"),
        "prompt_sha256": manifest["prompt_sha256"],
        "schema_sha256": hashlib.sha256((directory / "schema.json").read_bytes()).hexdigest(),
        "reference_files": references,
    }
    execution_path = directory / "execution.json"
    with execution_path.open("x", encoding="utf-8") as handle:
        json.dump(execution, handle, ensure_ascii=False, indent=2)
    print(f"Running {manifest['stage']} with {execution['cli_version']}", flush=True)
    try:
        with (directory / "prompt.md").open() as prompt, (directory / "events.jsonl").open("x") as events, (directory / "stderr.log").open("x") as errors:
            process = subprocess.run(command, stdin=prompt, stdout=events, stderr=errors, cwd=manifest["working_directory"])
        execution["exit_code"] = process.returncode
        if process.returncode:
            execution["status"] = "failed"
        else:
            validate_result(directory, manifest, read_json(directory / "result.json"))
            for reference in references:
                if hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest() != reference["sha256"]:
                    raise ValueError(f"reference changed during execution: {reference['path']}")
            execution["status"] = "completed"
            execution["result_sha256"] = hashlib.sha256((directory / "result.json").read_bytes()).hexdigest()
    except Exception as exc:
        execution["status"] = "failed"
        execution["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        execution["finished_at_utc"] = now()
        execution_path.write_text(json.dumps(execution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(execution, ensure_ascii=False, indent=2), flush=True)
    return 0 if execution["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
