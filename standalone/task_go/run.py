"""Run a task-only augmentation pipeline inside its private workspace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

from engine.knowledge import (
    compile_knowledge, read_json, sha256, universe_for, validate_batches,
    validate_contract, validate_knowledge_review, workspace_file, write_json,
)
from engine.rounds import next_action, validate_round
from engine.reading import adaptive, validate_reading_plan, round_reading_input, READING_PLAN_SCHEMA, READING_DECISION_SCHEMA
from engine.knowledge_context import KnowledgeContext


def validate_schema(value, schema, location="result"):
    """Validate the deliberately small schema subset used by the stage contracts."""
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "number": (int, float), "boolean": bool, "null": type(None)}
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(isinstance(value, kinds[t]) and not (t in {"integer", "number"} and isinstance(value, bool)) for t in types):
        raise ValueError(f"Wrong type at {location}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Invalid enum at {location}")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(f"Missing required fields at {location}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"Unexpected fields at {location}")
        for key, item in value.items():
            if key in props:
                validate_schema(item, props[key], f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise ValueError(f"Array length outside budget at {location}")
        for item in value:
            validate_schema(item, schema["items"], location + "[]")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, valid in [("minimum", lambda n: value >= n), ("maximum", lambda n: value <= n),
                           ("exclusiveMinimum", lambda n: value > n), ("exclusiveMaximum", lambda n: value < n)]:
            if key in schema and not valid(schema[key]):
                raise ValueError(f"Number outside bounds at {location}")


def unique(values, field):
    ids = [v[field] for v in values]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError(f"Nonunique or empty {field}")
    return set(ids)


def validate_stage(stage, task, result, root):
    if result["task_id"] != task["task_id"]:
        raise ValueError("Task identity changed")
    if stage == "planner":
        unique(result["augmentations"], "id")
        if any(a["category"] not in task["candidate_categories"] for a in result["augmentations"]):
            raise ValueError("Undeclared knowledge category")
        for key in ("gene_universe_path", "gene_field"):
            if result["scope"][key] != task["scope"][key]:
                raise ValueError("Planner changed the fixed gene universe")
        validate_contract(task, result)
        validate_reading_plan(task, result)
    elif stage == "retriever":
        plan = read_json(root / "stages/planner/result.json")
        plan_ids = unique(plan["augmentations"], "id")
        unique(result["batches"], "id")
        if unique(result["coverage"], "plan_item_id") != plan_ids:
            raise ValueError("Every planned knowledge family needs a coverage entry")
        if any(b["plan_item_id"] not in plan_ids for b in result["batches"]):
            raise ValueError("Batch references an unknown plan item")
        for b in result["batches"]:
            workspace_file(root, b["provenance_path"])
        write_json(root / "stages/retriever/independent_validation.json", validate_batches(task, result["batches"], root))
    else:
        candidates = read_json(root / "stages/retriever/result.json")
        unique(result["batch_decisions"], "batch_id")
        for decision in result["batch_decisions"]:
            audit = read_json(workspace_file(root, decision["audit_report_path"]))
            if audit["review_method"] != decision["review_method"]:
                raise ValueError("Review method differs from audit")
            if decision["verdict"] == "accept" and not decision["evidence_checked"]:
                raise ValueError("Accepted batch requires explicit evidence checks")
        validate_knowledge_review(task, candidates, result, root)


def run_stage(stage, task, runtime, root, directory=None, round_input=None):
    directory = directory or root / "stages" / stage
    directory.mkdir(parents=True)
    schema = read_json(root / "pipeline/schemas" / {"planner": "plan.schema.json", "retriever": "candidates.schema.json", "reviewer": "review.schema.json"}[stage])
    if stage == "planner" and adaptive(task):
        schema["properties"]["reading_plan"] = READING_PLAN_SCHEMA
        schema["required"].append("reading_plan")
    if stage == "planner":
        schema["properties"]["augmentations"]["items"]["properties"]["category"]["enum"] = task["candidate_categories"]
    if round_input is not None:
        extra = {"paper_inspections_path": {"type": "string"}, "usage_path": {"type": "string"},
                 "supersedes_batch_ids": {"type": "array", "items": {"type": "string"}}}
        schema["properties"].update(extra)
        schema["required"].extend(extra)
        if adaptive(task):
            schema["properties"]["reading_decision"] = READING_DECISION_SCHEMA
            schema["required"].append("reading_decision")
    write_json(directory / "schema.json", schema)
    # The complete task was allowlisted and copied before entering this runtime.
    write_json(directory / "task.input.json", task)
    inputs = {"task": task}
    if stage != "planner":
        inputs["plan"] = read_json(root / "stages/planner/result.json")
    if stage == "reviewer":
        inputs["candidates"] = read_json(root / "stages/retriever/result.json")
        if (root / "rounds/progress.json").exists():
            inputs["retrieval_progress"] = read_json(root / "rounds/progress.json")
    if round_input is not None:
        inputs["retrieval_round"] = round_input
    parts = [(root / "pipeline/prompts/common.md").read_text(), (root / f"pipeline/prompts/{stage}.md").read_text()]
    parts += [f"Input {name}:\n{json.dumps(value, ensure_ascii=False, separators=(',', ':'))}" for name, value in inputs.items()]
    if stage != "planner":
        parts.append((root / "pipeline/FORMAT.md").read_text())
    if round_input is not None:
        parts.append((root / "pipeline/prompts/retrieval_round.md").read_text())
    prompt = "\n\n".join(parts)
    (directory / "prompt.md").write_text(prompt)
    command = ["/opt/codex", "exec", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral",
               "--cd", str(root), "--json", "--output-schema", str(directory / "schema.json"),
               "--output-last-message", str(directory / "result.json"), "--model", runtime["model"],
               "--config", f'model_reasoning_effort="{runtime["reasoning_effort"]}"']
    for feature in ("apps", "memories", "multi_agent", "remote_plugin", "plugins", "hooks"):
        command += ["--disable", feature]
    if stage == "planner":
        command += ["--disable", "shell_tool", "--config", 'web_search="disabled"', "--sandbox", "read-only"]
    else:
        command += ["--approve-for-me", "--config", 'web_search="live"']
    command.append("-")
    execution = {"stage": stage, "status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                 "prompt_sha256": sha256(directory / "prompt.md"), "command": command,
                 "input_boundary": "task-only private filesystem; project directories are not mounted"}
    write_json(directory / "execution.json", execution)
    with (directory / "prompt.md").open() as stdin, (directory / "events.jsonl").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
        child = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, cwd=root, start_new_session=True)
        try:
            code = child.wait(timeout=runtime["stage_timeout_seconds"])
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=15)
            raise TimeoutError(f"{stage} exceeded the declared stage time budget")
    if code:
        raise RuntimeError(f"{stage} exited {code}; see its event and error logs")
    result = read_json(directory / "result.json")
    validate_schema(result, schema)
    if round_input is None:
        validate_stage(stage, task, result, root)
    execution.update(status="completed", finished_at_utc=datetime.now(timezone.utc).isoformat(),
                     result_sha256=sha256(directory / "result.json"))
    write_json(directory / "execution.json", execution)
    return result


def run_retrieval_rounds(task, runtime, root, status):
    directory = root / "rounds"
    directory.mkdir(exist_ok=True)
    state_path = directory / "state.json"
    plan = read_json(root / "stages/planner/result.json")
    initial = {"schema_version": "3.0", "task_id": task["task_id"], "batches": [], "open_questions": [],
               "coverage": [{"plan_item_id": a["id"], "status": "pending", "notes": "Acquisition pending"}
                            for a in plan["augmentations"]]}
    state = read_json(state_path) if state_path.exists() else {
        "candidates": initial, "observations": [], "progress": {}, "attempt": 0, "stalled": 0,
        "feedback": "Start the first retrieval-and-addition round", "stop_reason": "continue",
    }
    maximum = runtime["retrieval_rounds"]
    for number in range(state["attempt"] + 1, maximum + 1):
        stage_dir = directory / f"retriever_{number:03d}"
        previous = dict(state["progress"])
        context_path = directory / f"knowledge_context_{number:03d}.sqlite"
        context = KnowledgeContext.build(root, context_path, state["candidates"])
        context.close()
        round_input = {
            "number": number, "maximum_rounds": maximum,
            **round_reading_input(task, plan, runtime, previous, state.get("reading_decision")),
            "knowledge_context_index": str(context_path.relative_to(root)),
            "previous_progress": previous, "controller_feedback": state["feedback"],
            "active_candidates_path": "rounds/active_candidates.json",
            "previous_paper_inspections_path": "rounds/paper_inspections.jsonl",
            "output_directory": str(stage_dir.relative_to(root)),
        }
        write_json(directory / "active_candidates.json", state["candidates"])
        status("running", "retriever", round=number, progress=previous)
        try:
            result = run_stage("retriever", task, runtime, root, stage_dir, round_input)
            updated = validate_round(task, result, root, stage_dir, state)
            progress_keys = ("inspected_primary", "active_records") if adaptive(task) else ("inspected_primary", "full_text_inspected_primary")
            progressed = any(updated["progress"].get(key, 0) > previous.get(key, 0) for key in progress_keys)
            state.update(updated)
            state["stalled"] = 0 if progressed else state["stalled"] + 1
            state["feedback"] = ("Continue the remaining biological questions; use body reading for explicit information needs."
                                 if adaptive(task) else "Continue remaining topics and full-text upgrades using the cumulative validated progress")
            if not progressed:
                state["feedback"] = ("Report the remaining questions and evidence-based continuation or stopping decision."
                                     if adaptive(task) else "Reading counts were unchanged. Prioritize scientific reading of cached primary papers and body passages in the next round, then publish supported additions and inspection decisions.")
            write_json(stage_dir / "controller_validation.json", {
                "passed": True, "progress": state["progress"], "batches": updated["validation"],
            })
        except Exception as error:
            state["stalled"] += 1
            state["feedback"] = f"Repair this round's acquisition interface or continue its saved work: {type(error).__name__}: {error}"
            write_json(stage_dir / "controller_validation.json", {"passed": False, "error": state["feedback"]})
        state["attempt"] = number
        state["stop_reason"] = next_action(task, state["progress"], number, maximum, state["stalled"],
                                           runtime.get("stalled_round_limit", 3), state.get("reading_decision"))
        write_json(state_path, state)
        write_json(directory / "active_candidates.json", state["candidates"])
        paper_path = directory / "paper_inspections.jsonl"
        temporary = paper_path.with_suffix(".jsonl.tmp")
        temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in state["observations"]))
        temporary.replace(paper_path)
        write_json(directory / "progress.json", {"round": number, "maximum_rounds": maximum,
                   "stop_reason": state["stop_reason"], "progress": state["progress"],
                   "reading_mode": task["retrieval_budget"].get("reading_mode", "fixed_target"),
                   "reading_plan": plan.get("reading_plan"), "reading_decision": state.get("reading_decision"),
                   "feedback": state["feedback"], "targets": {
                       "papers": task["retrieval_budget"].get("target_papers_inspected", 0),
                       "full_texts": task["retrieval_budget"].get("target_full_text_papers_inspected", 0)}})
        if state["stop_reason"] != "continue":
            break
    aggregate = root / "stages/retriever"
    aggregate.mkdir(parents=True, exist_ok=True)
    write_json(aggregate / "result.json", state["candidates"])
    write_json(aggregate / "execution.json", {"stage": "retriever", "status": "completed",
               "rounds": state["attempt"], "stop_reason": state["stop_reason"], "progress": state["progress"]})
    validate_stage("retriever", task, state["candidates"], root)
    return state["stop_reason"]


def worker(root):
    root = Path(root).resolve()
    os.chdir(root)
    task, runtime = read_json(root / "task.json"), read_json(root / "runtime.json")
    def status(state, phase, **details):
        value = {"status": state, "phase": phase, "updated_at_utc": datetime.now(timezone.utc).isoformat(), **details}
        temporary = root / "status.json.tmp"
        write_json(temporary, value)
        temporary.replace(root / "status.json")
        print(json.dumps(value), flush=True)
    phase = "starting"
    try:
        universe_for(task, root)
        retrieval_stop = None
        for phase in ("planner", "retriever", "reviewer"):
            status("running", phase)
            if phase == "retriever" and (adaptive(task) or runtime.get("retrieval_rounds", 1) > 1):
                retrieval_stop = run_retrieval_rounds(task, runtime, root, status)
            else:
                run_stage(phase, task, runtime, root)
        phase = "compiling"
        status("running", phase)
        plan = read_json(root / "stages/planner/result.json")
        candidates = read_json(root / "stages/retriever/result.json")
        review = read_json(root / "stages/reviewer/result.json")
        accepted = validate_knowledge_review(task, candidates, review, root)
        provenance = [root / "task.json", root / "inputs/manifest.json"]
        provenance += [p for p in (root / "stages").rglob("*.json") if p.is_file()]
        provenance += [workspace_file(root, b["provenance_path"]) for b in candidates["batches"]]
        if (root / "rounds").exists():
            provenance += list((root / "rounds").rglob("*.json"))
            provenance += [root / "rounds/paper_inspections.jsonl"]
        summary = compile_knowledge(task, plan, accepted, root, root / "knowledge", provenance, review.get("equivalences_path"))
        write_json(root / "summary.json", summary)
        gaps = any(c["status"] != "covered" for c in candidates["coverage"])
        gaps = gaps or any(d["verdict"] != "accept" for d in review["batch_decisions"])
        gaps = gaps or retrieval_stop not in {None, "targets_met", "coverage_sufficient"}
        status("completed_with_gaps" if gaps else "completed", "finished", approved_batches=len(accepted))
        return 0
    except Exception as error:
        traceback.print_exc()
        status("failed", phase, error=f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    raise SystemExit(worker(parser.parse_args().workspace))
