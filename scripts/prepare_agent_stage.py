#!/usr/bin/env python3
"""Prepare one file-based agent stage and print its Codex command; no model call."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex


ROOT = Path(__file__).resolve().parents[1]
STAGES = {"planner": "plan", "retriever": "candidates", "reviewer": "review"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--model", help="Explicit Codex model; otherwise inherit CLI configuration.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable, including an IDE-bundled binary if needed.")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"), help="Explicit reasoning effort supported by the selected model.")
    parser.add_argument("--workflow", choices=("record", "task_batch"), help="Override the task's workflow profile.")
    args = parser.parse_args()
    if args.stage != "planner" and args.plan is None:
        parser.error("--plan is required for retriever and reviewer")
    if args.stage == "reviewer" and args.candidates is None:
        parser.error("--candidates is required for reviewer")
    if args.stage == "planner" and (args.plan or args.candidates):
        parser.error("planner accepts only the task card")
    if args.stage == "retriever" and args.candidates:
        parser.error("retriever accepts the task card and plan")

    stage_dir = args.run_dir.resolve() / args.stage
    if stage_dir.exists():
        parser.error(f"stage already exists: {stage_dir}; choose another run directory for revisions")

    task_preview = json.loads(args.task.read_text(encoding="utf-8"))
    workflow = args.workflow or task_preview.get("execution", {}).get("workflow", "record")
    if workflow not in ("record", "task_batch"):
        parser.error(f"unsupported workflow: {workflow}")
    schema_directory = ROOT / "schemas/agents" / ("batch" if workflow == "task_batch" else "")
    paths = {
        "common_prompt": ROOT / "prompts/agents/common.md",
        "role_prompt": ROOT / f"prompts/agents/{args.stage}.md",
        "schema": schema_directory / f"{STAGES[args.stage]}.schema.json",
        "task": args.task.resolve(),
    }
    if args.plan:
        paths["plan"] = args.plan.resolve()
    if args.candidates:
        paths["candidates"] = args.candidates.resolve()
    contents = {}
    metadata = {}
    for name, path in paths.items():
        raw = path.read_bytes()
        contents[name] = raw.decode("utf-8")
        metadata[name] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    task = json.loads(contents["task"])
    task_id = task["task_id"]
    model = args.model or task.get("execution", {}).get("model")
    reasoning_effort = args.reasoning_effort or task.get("execution", {}).get("reasoning_effort")
    sandbox = task.get("execution", {}).get("sandbox", "read-only")
    if sandbox not in ("read-only", "workspace-write"):
        parser.error("supported task sandboxes are read-only and workspace-write")
    for name in ("plan", "candidates"):
        if name in contents and json.loads(contents[name]).get("task_id") != task_id:
            parser.error(f"{name} task_id must match task card {task_id!r}")
    schema = json.loads(contents["schema"])
    if args.stage == "planner":
        schema["properties"]["augmentations"]["items"]["properties"]["category"]["enum"] = task["candidate_categories"]
        contents["schema"] = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        metadata["schema"]["source_sha256"] = metadata["schema"]["sha256"]
        metadata["schema"]["sha256"] = hashlib.sha256(contents["schema"].encode("utf-8")).hexdigest()

    prompt_parts = [contents["common_prompt"], contents["role_prompt"]]
    for name in ("task", "plan", "candidates"):
        if name in contents:
            compact = json.dumps(json.loads(contents[name]), ensure_ascii=False, separators=(",", ":"))
            prompt_parts.append(f"## Input: {name}\n\n```json\n{compact}\n```\n")
    prompt_parts.append(f"## Output format\n\nWorkflow: {workflow}. The CLI supplies the output schema through --output-schema. In an IDE session, read {stage_dir / 'schema.json'} before writing the final JSON. Keep large data artifacts outside the final response.\n")
    prompt = "\n\n".join(prompt_parts)
    command = [
        args.codex_bin, "exec", "--cd", str(ROOT), "--json",
        "--output-schema", str(stage_dir / "schema.json"),
        "--output-last-message", str(stage_dir / "result.json"),
    ]
    if task.get("execution", {}).get("approval_mode") == "auto_review":
        command.append("--approve-for-me")
    else:
        command.extend(["--sandbox", sandbox])
    if model:
        command.extend(["--model", model])
    if reasoning_effort:
        command.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
    command.append("-")
    manifest = {
        "schema_version": "1.0", "task_id": task_id, "stage": args.stage,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "codex", "requested_model": model,
        "requested_reasoning_effort": reasoning_effort,
        "workflow": workflow,
        "status": "prepared", "inputs": metadata,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "command": command,
        "working_directory": str(ROOT),
    }
    stage_dir.mkdir(parents=True)
    for name in ("task", "plan", "candidates"):
        if name in contents:
            (stage_dir / f"{name}.input.json").write_text(contents[name], encoding="utf-8")
    (stage_dir / "schema.json").write_text(contents["schema"], encoding="utf-8")
    (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    (stage_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        shlex.join(command)
        + " < " + shlex.quote(str(stage_dir / "prompt.md"))
        + " > " + shlex.quote(str(stage_dir / "events.jsonl"))
        + " 2> " + shlex.quote(str(stage_dir / "stderr.log"))
    )


if __name__ == "__main__":
    main()
