"""Run agent-approved group recipes and deterministic graph expansion."""

from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import time
import traceback

from engine.knowledge import sha256
from engine.module_graph import apply_patch, filter_review, fingerprint, summary, validate_graph
from engine.module_recipes import compile_recipe, expand_group_review, recipe_context
from engine.module_prompts import instruction_receipts
from engine.module_progress import archive_attempt, load_progress, publish_memberships
from place_modules import agent, obj, report, schemas as module_schemas, verify_inputs, write


def schemas():
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    edge = module_schemas()[0]["properties"]["decisions"]["items"]["properties"]["edges"]["items"]
    anchor = obj({"parent": string, "modules": strings, "relation": edge["properties"]["relation"],
                  "model_edge": {"type": "boolean"}, "rationale": string})
    group = obj({"group_id": string, "modules": strings, "rationale": string, "inspected_concepts": strings,
        "native_hierarchy": {"type": "boolean"},
        "reuse": {"type": "array", "items": obj({"module_id": string, "target_id": string, "rationale": string})},
        "defer": {"type": "array", "items": obj({"module_id": string, "reason": string})},
        "anchors": {"type": "array", "items": anchor}, "extra_edges": {"type": "array", "items": edge}})
    recipe = obj({"batch_id": string, "graph_revision": {"type": "integer", "minimum": 0},
                  "groups": {"type": "array", "items": group}})
    verdict = {"type": "string", "enum": ["accept", "defer"]}
    review = obj({"batch_id": string, "graph_revision": {"type": "integer", "minimum": 0},
        "groups": {"type": "array", "items": obj({"group_id": string, "verdict": verdict, "reason": string,
            "exceptions": {"type": "array", "items": obj({"module_id": string, "verdict": verdict, "reason": string})}})}})
    return recipe, review


def event_accounting(root):
    records = []
    for path in sorted([*(root / "batches").glob("*/*/execution.json"),
                        *(root / "failed_batches").glob("*/*/execution.json")]):
        record = json.loads(path.read_text())
        events = path.with_name("events.jsonl")
        commands, failed, usage = 0, 0, Counter()
        if events.exists():
            for line in events.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item = event.get("item", {})
                if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                    commands += 1
                    failed += item.get("exit_code", 0) != 0
                if event.get("type") == "turn.completed":
                    usage.update({k: v for k, v in event.get("usage", {}).items() if isinstance(v, int)})
        records.append({"path": str(path.parent.relative_to(root)), "role": record["role"],
            "wall_seconds": record.get("wall_seconds"), "status": record["status"],
            "shell_commands": commands, "failed_shell_commands": failed, "usage": dict(usage)})
    return {"agent_invocations": len(records), "shell_commands": sum(x["shell_commands"] for x in records),
            "failed_shell_commands": sum(x["failed_shell_commands"] for x in records), "stages": records}


def run_batch(root, graph, catalog, facts, batch, runtime, status):
    start = time.monotonic(); original_hash = fingerprint(graph)
    directory = root / "batches" / batch["id"]
    directory.mkdir(parents=True, exist_ok=False)
    packet = recipe_context(graph, catalog, facts, batch)
    packet["shared_graph_summary"] = summary(graph)
    write(directory / "context.json", packet)
    context_seconds = time.monotonic() - start
    recipe_schema, review_schema = schemas()
    status("running", "recipe_editor", batch=batch["id"], modules=len(batch["modules"]), completed_batches=len(graph.get("applied_batches", [])))
    editor_seconds = 0.0
    for attempt in range(1, 3):
        recipe, execution = agent("recipe_editor", root, directory / f"editor_{attempt}", runtime, packet, recipe_schema)
        editor_seconds += execution["wall_seconds"]
        try:
            if recipe["batch_id"] != batch["id"]:
                raise ValueError("Recipe batch identity changed")
            compile_start = time.monotonic()
            patch, receipt = compile_recipe(graph, catalog, facts, recipe, batch["modules"])
            compile_seconds = time.monotonic() - compile_start
            break
        except ValueError as error:
            write(directory / f"editor_{attempt}/validation.json", {"passed": False, "error": str(error)})
            if attempt == 2:
                raise
            packet["repair"] = {"error": str(error), "previous_recipe": recipe}
    write(directory / "recipe.json", recipe)
    write(directory / "compiled_patch.json", patch)
    write(directory / "expansion_receipt.json", receipt)
    status("running", "recipe_reviewer", batch=batch["id"], groups=len(recipe["groups"]), completed_batches=len(graph.get("applied_batches", [])))
    review, execution = agent("recipe_reviewer", root, directory / "reviewer", runtime,
        {**packet, "proposed_recipe": recipe, "complete_expansion": receipt,
         "compiled_transaction_path": str((directory / "compiled_patch.json").relative_to(root))}, review_schema)
    expanded_review = expand_group_review(recipe, review, patch)
    write(directory / "expanded_review.json", expanded_review)
    accepted = filter_review(patch, expanded_review)
    commit_start = time.monotonic()
    updated = apply_patch(graph, catalog, facts, accepted, batch["modules"])
    verify_inputs(root)
    if fingerprint(json.loads((root / "graph/current.json").read_text())) != original_hash:
        raise ValueError("Agent altered the controller-owned graph")
    write(directory / "accepted_patch.json", accepted)
    write(directory / "validation.json", {"passed": True, "before_sha256": original_hash,
        "after_sha256": fingerprint(updated), "before_revision": graph["revision"], "after_revision": updated["revision"]})
    row = {"batch_id": batch["id"], "modules": len(batch["modules"]), "groups": len(recipe["groups"]),
        "actions": dict(Counter(d["action"] for d in accepted["decisions"])),
        "editor_seconds": editor_seconds, "reviewer_seconds": execution["wall_seconds"],
        "context_seconds": context_seconds, "compile_seconds": compile_seconds,
        "commit_seconds": time.monotonic() - commit_start, "total_wall_seconds": time.monotonic() - start}
    return updated, row


def worker(root):
    root = Path(root).resolve(); os.chdir(root)
    def status(state, phase, **details):
        value = {"status": state, "phase": phase, "updated_at_utc": datetime.now(timezone.utc).isoformat(), **details}
        write(root / "status.json", value); print(json.dumps(value), flush=True)
    graph, timings, lock = None, [], None
    started = time.monotonic()
    try:
        lock = (root / "controller.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_inputs(root)
        runtime = json.loads((root / "runtime.json").read_text())
        catalog = json.loads((root / "inputs/modules.json").read_text())
        facts = json.loads((root / "inputs/placement_evidence.json").read_text())
        batches = json.loads((root / "inputs/module_batches.json").read_text())
        baseline = json.loads((root / "inputs/baseline_graph.json").read_text())
        validate_graph(baseline)
        if (root / "knowledge_graph/freeze_manifest.json").exists():
            raise ValueError("The module graph is already frozen")
        graph, timings = load_progress(root, baseline, catalog, facts, batches)
        for batch in batches:
            if batch["id"] in graph.get("applied_batches", []):
                continue
            start = time.monotonic(); failed_seconds = Counter()
            if (root / "batches" / batch["id"]).exists():
                archive_attempt(root, batch["id"])
            failures = len(list((root / "failed_batches").glob(batch["id"] + "_attempt_*")))
            limit = runtime.get("batch_attempts", 3)
            while True:
                if failures >= limit:
                    raise RuntimeError("Batch attempt budget exhausted: " + batch["id"])
                try:
                    updated, row = run_batch(root, graph, catalog, facts, batch, runtime, status)
                    break
                except Exception as error:
                    verify_inputs(root)
                    if fingerprint(json.loads((root / "graph/current.json").read_text())) != fingerprint(graph):
                        raise ValueError("Current graph changed outside a validated commit") from error
                    directory = root / "batches" / batch["id"]
                    write(directory / "failure.json", {"error": f"{type(error).__name__}: {error}",
                        "graph_revision": graph["revision"], "updated_at_utc": datetime.now(timezone.utc).isoformat()})
                    for path in directory.glob("*/execution.json"):
                        execution = json.loads(path.read_text())
                        key = "editor_seconds" if execution["role"] == "recipe_editor" else "reviewer_seconds"
                        failed_seconds[key] += execution.get("wall_seconds", 0)
                    failures = archive_attempt(root, batch["id"])
                    status("running", "batch_retry", batch=batch["id"], failed_attempts=failures,
                           attempt_limit=limit, error=str(error), completed_batches=len(timings))
            row.update({key: row.get(key, 0) + value for key,value in failed_seconds.items()})
            row.update(total_wall_seconds=time.monotonic() - start, failed_attempts=failures)
            write(root / "batches" / batch["id"] / "timing.json", row)
            write(root / "graph/current.json", updated)
            graph = updated; timings.append(row)
            report(root, graph, timings, "running")
            status("running", "batch_committed", batch=batch["id"], completed_batches=len(timings), graph=summary(graph))
        output = root / "knowledge_graph"; output.mkdir(exist_ok=False)
        write(output / "graph.json", graph)
        write(output / "summary.json", summary(graph))
        write(output / "instructions.json", instruction_receipts(root))
        write(output / "validation.json", {"passed": True, "checks": ["agent_selected_group_scopes", "complete_module_review_coverage",
            "source_bound_native_edge_expansion", "revision_bound_transactions", "fixed_gene_universe", "connected_model_DAG",
            "unique_model_edges", "independent_group_and_exception_review", "unchanged_scientific_inputs"]})
        write(output / "freeze_manifest.json", {"files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(output.iterdir())],
            "inputs": json.loads((root / "inputs/manifest.json").read_text()),
            "batch_receipts": [{"batch_id": b["id"],
                "patch_sha256": sha256(root / "batches" / b["id"] / "accepted_patch.json"),
                "review_sha256": sha256(root / "batches" / b["id"] / "reviewer/result.json"),
                "recipe_sha256": sha256(root / "batches" / b["id"] / "recipe.json"),
                "expansion_sha256": sha256(root / "batches" / b["id"] / "expansion_receipt.json")}
                for b in batches]})
        if runtime.get("publish_memberships"):
            publish_memberships(root, graph)
        report(root, graph, timings, "completed")
        accounting = event_accounting(root)
        write(root / "efficiency.json", {"workflow": "module_recipes", "run_wall_seconds": time.monotonic() - started,
            "context_bytes": sum((root / "batches" / b["id"] / "context.json").stat().st_size for b in batches), **accounting})
        status("completed", "finished", completed_batches=len(timings), graph=summary(graph))
        return 0
    except Exception as error:
        traceback.print_exc(); status("failed", "module_recipes", error=f"{type(error).__name__}: {error}")
        if graph is not None:
            report(root, graph, timings, "failed")
        return 1
    finally:
        if lock is not None:
            lock.close()
