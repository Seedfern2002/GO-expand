"""Run sequential graph-aware module batches with independent scientific review."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

from engine.knowledge import sha256
from engine.module_graph import GraphContext, apply_patch, filter_review, fingerprint, summary, validate_graph
from run import validate_schema


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def schemas():
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    edge = obj({"parent": string, "child": string, "relation": {"type": "string", "enum": [
        "source_pathway_parent", "is_a", "part_of", "participates_in", "model_aggregation", "related_to", "regulates"]},
        "model_edge": {"type": "boolean"}, "evidence_ids": strings, "rationale": string})
    decision = obj({"module_id": string, "action": {"type": "string", "enum": ["add", "reuse", "defer"]},
                    "target_id": string, "rationale": string, "inspected_concepts": strings,
                    "evidence_ids": strings, "edges": {"type": "array", "items": edge}})
    patch = obj({"batch_id": string, "graph_revision": {"type": "integer", "minimum": 0},
                 "decisions": {"type": "array", "items": decision}})
    verdict = obj({"module_id": string, "verdict": {"type": "string", "enum": ["accept", "defer"]},
                   "reason": string, "evidence_ids": strings})
    review = obj({"batch_id": string, "graph_revision": {"type": "integer", "minimum": 0},
                  "decisions": {"type": "array", "items": verdict}})
    return patch, review


def verify_inputs(root):
    manifest = json.loads((root / "inputs/manifest.json").read_text())
    for record in manifest["files"]:
        if sha256(root / record["path"]) != record["sha256"]:
            raise ValueError("A declared scientific input changed: " + record["path"])
    if sha256(root / "task.json") != manifest["task_sha256"]:
        raise ValueError("The scientific task changed")


def assert_external_boundary(root):
    if Path(root).resolve() != Path("/workspace") or not Path("/opt/codex").is_file():
        raise RuntimeError("Module agents run inside the declared task-only launcher")
    mounts = {}
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        mounts[fields[4]] = set(fields[5].split(","))
    for path in ("/workspace/inputs", "/workspace/pipeline"):
        if "ro" not in mounts.get(path, set()):
            raise RuntimeError("Module-agent scientific inputs and pipeline code require read-only mounts")


def agent(role, root, directory, runtime, context, schema):
    assert_external_boundary(root)
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "schema.json", schema)
    prompt = ((root / f"pipeline/prompts/modules/{role}.md").read_text() + "\n\n"
              + "Scientific task:\n" + (root / "task.json").read_text()
              + "\n\nCurrent batch context:\n" + json.dumps(context, separators=(",", ":")))
    (directory / "prompt.md").write_text(prompt)
    command = ["/opt/codex", "exec", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral",
               "--cd", str(root), "--json", "--output-schema", str(directory / "schema.json"),
               "--output-last-message", str(directory / "result.json"), "--model", runtime["model"],
               "--config", f'model_reasoning_effort="{runtime["reasoning_effort"]}"',
               "--sandbox", "danger-full-access", "--config", 'approval_policy="never"',
               "--config", 'web_search="disabled"']
    for feature in ("apps", "memories", "multi_agent", "remote_plugin", "plugins", "hooks"):
        command += ["--disable", feature]
    command.append("-")
    started = time.monotonic()
    execution = {"role": role, "status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                 "prompt_sha256": sha256(directory / "prompt.md"), "command": command}
    write(directory / "execution.json", execution)
    with (directory / "prompt.md").open() as stdin, (directory / "events.jsonl").open("w") as stdout, (directory / "stderr.log").open("w") as stderr:
        child = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, cwd=root)
        code = child.wait(timeout=runtime["stage_timeout_seconds"])
    execution.update(exit_code=code, wall_seconds=time.monotonic() - started,
                     finished_at_utc=datetime.now(timezone.utc).isoformat())
    if code:
        execution["status"] = "failed"; write(directory / "execution.json", execution)
        raise RuntimeError(role + " exited " + str(code))
    result = json.loads((directory / "result.json").read_text())
    validate_schema(result, schema)
    execution.update(status="completed", result_sha256=sha256(directory / "result.json"))
    write(directory / "execution.json", execution)
    return result, execution


def report(root, graph, timings, status):
    totals = summary(graph)
    value = {"status": status, "graph": totals, "batches": timings,
             "total_wall_seconds": sum(t["total_wall_seconds"] for t in timings),
             "modules_processed": sum(t["modules"] for t in timings)}
    if timings:
        rate = value["total_wall_seconds"] / value["modules_processed"]
        catalog_count = len(json.loads((root / "inputs/modules.json").read_text()))
        value["throughput_seconds_per_module"] = rate
        value["full_catalog_modules"] = catalog_count
        value["linear_full_catalog_hours"] = rate * catalog_count / 3600
        value["estimate_scope"] = "Linear estimate at observed sequential editor/reviewer throughput; source complexity and batch size affect runtime."
    write(root / "timing.json", value)
    lines = ["# Graph-aware module placement timing", "", f"Status: {status}.", "",
             "One shared fixed-gene graph; source memberships are joined by code and module identities/edges are proposed and independently reviewed by agents.", "",
             "| Batch | Modules | Added | Reused | Deferred | Editor seconds | Reviewer seconds | Total seconds |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in timings:
        lines.append(f"| {row['batch_id']} | {row['modules']} | {row['actions'].get('add', 0)} | {row['actions'].get('reuse', 0)} | {row['actions'].get('defer', 0)} | {row['editor_seconds']:.1f} | {row['reviewer_seconds']:.1f} | {row['total_wall_seconds']:.1f} |")
    lines += ["", f"Added nodes by depth: {json.dumps(totals['added_nodes_by_depth'])}.",
              f"Added nodes directly attached to the common root: {totals['added_nodes_attached_to_root']}."]
    if timings:
        lines += [f"Observed total: {value['total_wall_seconds'] / 60:.2f} minutes for {value['modules_processed']} modules.",
                  f"Linear sequential estimate for {catalog_count} catalog modules: {value['linear_full_catalog_hours']:.2f} hours.", value["estimate_scope"]]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")


def worker(root):
    if json.loads((Path(root) / "runtime.json").read_text()).get("workflow") == "module_recipes":
        from place_module_recipes import worker as recipe_worker
        return recipe_worker(root)
    root = Path(root).resolve(); os.chdir(root)
    def status(state, phase, **details):
        value = {"status": state, "phase": phase, "updated_at_utc": datetime.now(timezone.utc).isoformat(), **details}
        write(root / "status.json", value); print(json.dumps(value), flush=True)
    graph = None; timings = []
    try:
        lock = (root / "controller.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_inputs(root)
        runtime = json.loads((root / "runtime.json").read_text())
        catalog = json.loads((root / "inputs/modules.json").read_text())
        facts = json.loads((root / "inputs/placement_evidence.json").read_text())
        batches = json.loads((root / "inputs/module_batches.json").read_text())
        graph = json.loads((root / "inputs/baseline_graph.json").read_text())
        validate_graph(graph)
        if (root / "graph/current.json").exists():
            graph = json.loads((root / "graph/current.json").read_text())
            timings = json.loads((root / "timing.json").read_text())["batches"]
        else:
            write(root / "graph/current.json", graph)
        patch_schema, review_schema = schemas()
        for batch in batches:
            if batch["id"] in graph.get("applied_batches", []):
                continue
            start = time.monotonic(); original_hash = fingerprint(graph)
            directory = root / "batches" / batch["id"]
            directory.mkdir(parents=True, exist_ok=False)
            context = GraphContext(graph, catalog, facts)
            packet = {"batch_id": batch["id"], "graph_revision": graph["revision"],
                      "graph_sha256": original_hash, "shared_graph_summary": summary(graph),
                      "current_graph_path": "graph/current.json",
                      "modules": [context.module(module) for module in batch["modules"]]}
            write(directory / "context.json", packet)
            status("running", "editor", batch=batch["id"], modules=len(batch["modules"]), completed_batches=len(timings))
            editor_time = 0.0
            for attempt in range(1, 3):
                patch, execution = agent("editor", root, directory / f"editor_{attempt}", runtime, packet, patch_schema)
                editor_time += execution["wall_seconds"]
                try:
                    if patch["batch_id"] != batch["id"]:
                        raise ValueError("Batch identity changed")
                    apply_patch(graph, catalog, facts, patch, batch["modules"])
                    break
                except ValueError as error:
                    write(directory / f"editor_{attempt}/validation.json", {"passed": False, "error": str(error)})
                    if attempt == 2:
                        raise
                    packet["repair"] = {"error": str(error), "previous_patch": patch}
            status("running", "reviewer", batch=batch["id"], completed_batches=len(timings))
            review, execution = agent("reviewer", root, directory / "reviewer", runtime,
                                       {**packet, "proposed_transaction": patch}, review_schema)
            if review["batch_id"] != batch["id"] or review["graph_revision"] != graph["revision"]:
                raise ValueError("Review refers to a different batch or revision")
            for decision in review["decisions"]:
                if not set(decision["evidence_ids"]) <= facts.keys() or not decision["reason"].strip():
                    raise ValueError("Review needs declared evidence and a reason")
            accepted = filter_review(patch, review)
            updated = apply_patch(graph, catalog, facts, accepted, batch["modules"])
            verify_inputs(root)
            if fingerprint(json.loads((root / "graph/current.json").read_text())) != original_hash:
                raise ValueError("Agent altered the controller-owned graph")
            write(directory / "accepted_patch.json", accepted)
            write(directory / "validation.json", {"passed": True, "before_sha256": original_hash,
                  "after_sha256": fingerprint(updated), "before_revision": graph["revision"], "after_revision": updated["revision"]})
            graph = updated
            row = {"batch_id": batch["id"], "modules": len(batch["modules"]),
                   "actions": dict(Counter(d["action"] for d in accepted["decisions"])),
                   "editor_seconds": editor_time, "reviewer_seconds": execution["wall_seconds"],
                   "total_wall_seconds": time.monotonic() - start}
            timings.append(row)
            write(root / "graph/current.json", graph)
            report(root, graph, timings, "running")
            status("running", "batch_committed", batch=batch["id"], completed_batches=len(timings), graph=summary(graph))
        output = root / "knowledge_graph"
        output.mkdir(exist_ok=False)
        write(output / "graph.json", graph)
        write(output / "summary.json", summary(graph))
        write(output / "validation.json", {"passed": True, "checks": ["revision_bound_transactions", "fixed_gene_universe", "connected_model_DAG", "unique_model_edges", "declared_source_evidence", "independent_module_review", "unchanged_scientific_inputs"]})
        write(output / "freeze_manifest.json", {"files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(output.iterdir())],
              "inputs": json.loads((root / "inputs/manifest.json").read_text()),
              "batch_receipts": [{"batch_id": batch["id"], "patch_sha256": sha256(root / "batches" / batch["id"] / "accepted_patch.json"),
                                  "review_sha256": sha256(root / "batches" / batch["id"] / "reviewer/result.json")}
                                 for batch in batches]})
        report(root, graph, timings, "completed")
        status("completed", "finished", completed_batches=len(timings), graph=summary(graph))
        return 0
    except Exception as error:
        traceback.print_exc(); status("failed", "module_placement", error=f"{type(error).__name__}: {error}")
        if graph is not None:
            report(root, graph, timings, "failed")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    raise SystemExit(worker(parser.parse_args().workspace))
