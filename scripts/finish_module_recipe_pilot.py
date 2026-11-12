"""Finalize the group-recipe pilot and compare timing outside agent context."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import drugcell_ontology as ontology
from finish_module_graph_pilot import finish


def events(workspace):
    stages, totals, tokens = [], Counter(), Counter()
    for path in sorted((workspace / "batches").glob("*/*/execution.json")):
        execution = json.loads(path.read_text())
        count = Counter(agent_invocations=1)
        for line in path.with_name("events.jsonl").read_text().splitlines():
            event = json.loads(line)
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                count["shell_commands"] += 1
                count["failed_shell_commands"] += item.get("exit_code", 0) != 0
            if event.get("type") == "turn.completed":
                tokens.update({k: v for k, v in event.get("usage", {}).items() if isinstance(v, int)})
        totals.update(count)
        stages.append({"path": str(path.parent.relative_to(workspace)), "role": execution["role"],
                       "wall_seconds": execution["wall_seconds"], **dict(count)})
    return {**dict(totals), "usage": dict(tokens), "stages": stages}


def compare(workspace, reference, output, reference_label="Earlier per-module transactions",
            current_label="Group recipe + code expansion", comparison_scope=None):
    workspace, reference, output = Path(workspace), Path(reference), Path(output)
    current = json.loads((workspace / "timing.json").read_text())
    previous = json.loads((reference / "timing.json").read_text())
    reference_modules = {m for b in json.loads((reference / "inputs/module_batches.json").read_text()) for m in b["modules"]}
    current_modules = {m for b in json.loads((workspace / "inputs/module_batches.json").read_text()) for m in b["modules"]}
    matched = {"processing_module_set": current_modules == reference_modules}
    for filename in ("task.json", "inputs/baseline_graph.json", "inputs/modules.json", "inputs/placement_evidence.json", "inputs/genes.json"):
        matched[filename] = json.loads((workspace / filename).read_text()) == json.loads((reference / filename).read_text())
    new_runtime = json.loads((workspace / "runtime.json").read_text())
    old_runtime = json.loads((reference / "runtime.json").read_text())
    matched.update({k: new_runtime[k] == old_runtime[k] for k in ("model", "reasoning_effort")})
    current_sources = {r["path"]: r["sha256"] for r in json.loads((workspace / "inputs/manifest.json").read_text())["files"]
                       if r["path"].startswith("inputs/sources/")}
    reference_sources = {r["path"]: r["sha256"] for r in json.loads((reference / "inputs/manifest.json").read_text())["files"]
                         if r["path"].startswith("inputs/sources/")}
    matched["pinned_source_snapshots"] = current_sources == reference_sources
    if not all(matched.values()):
        raise ValueError("Timing comparison scientific inputs or backend settings differ: " + str(matched))
    before_events, after_events = events(reference), events(workspace)
    def actions(timing):
        result = Counter()
        for b in timing["batches"]:
            result.update(b["actions"])
        return dict(result)
    old_seconds, new_seconds = previous["total_wall_seconds"], current["total_wall_seconds"]
    previous_context_bytes = sum(p.stat().st_size for p in (reference / "batches").glob("*/context.json"))
    current_context_bytes = sum(p.stat().st_size for p in (workspace / "batches").glob("*/context.json"))
    result = {"matched_inputs": matched, "baseline": {"workspace": str(reference), "seconds": old_seconds,
        "actions": actions(previous), "graph": previous["graph"], "events": before_events, "context_bytes": previous_context_bytes},
        "hybrid": {"workspace": str(workspace), "seconds": new_seconds, "actions": actions(current),
            "graph": current["graph"], "events": after_events, "context_bytes": current_context_bytes},
        "speedup": old_seconds / new_seconds, "wall_time_reduction_fraction": 1 - new_seconds / old_seconds,
        "context_byte_reduction_fraction": 1 - current_context_bytes / previous_context_bytes,
        "reference_label": reference_label, "current_label": current_label,
        "comparison_scope": comparison_scope or "Observed combined change in group recipes, batch size, compact context and execution configuration; single runs of the same 24 source modules. Independent biological ground-truth accuracy is outside this timing measurement."}
    ontology.write_json(output / "efficiency_comparison.json", result)
    lines = [(output / "REPORT.md").read_text(), "", "## Matched-input efficiency comparison", "",
        "The task card, original graph, complete gene universe, source catalog, pinned evidence, processing module set and model/reasoning settings match the earlier pilot.", "",
        f"| Measurement | {reference_label} | {current_label} |",
        "|---|---:|---:|",
        f"| Placement wall time (minutes) | {old_seconds / 60:.2f} | {new_seconds / 60:.2f} |",
        f"| Agent invocations | {before_events['agent_invocations']} | {after_events['agent_invocations']} |",
        f"| Shell commands | {before_events.get('shell_commands', 0)} | {after_events.get('shell_commands', 0)} |",
        f"| Failed shell commands | {before_events.get('failed_shell_commands', 0)} | {after_events.get('failed_shell_commands', 0)} |",
        f"| Context bytes | {previous_context_bytes} | {current_context_bytes} |",
        f"| Added / reused / deferred | {actions(previous).get('add', 0)} / {actions(previous).get('reuse', 0)} / {actions(previous).get('defer', 0)} | {actions(current).get('add', 0)} / {actions(current).get('reuse', 0)} / {actions(current).get('defer', 0)} |",
        "", f"Observed speedup: {result['speedup']:.2f}x; wall time reduction: {100 * result['wall_time_reduction_fraction']:.1f}%.",
        result["comparison_scope"], "", "The recipe and complete expansion are frozen with the accepted patch and independent review. Reviewer verdicts describe review outcomes; the table reports timing and graph retention."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    ontology.write_json(output / "status.json", {"status": "completed", "report": str(output / "REPORT.md"),
        "speedup": result["speedup"], "placement_wall_seconds": new_seconds})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "reference-workspace", "baseline", "gene-map", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--reference-label", default="Earlier per-module transactions")
    parser.add_argument("--current-label", default="Group recipe + code expansion")
    parser.add_argument("--comparison-scope")
    args = parser.parse_args()
    finish(args.workspace, args.baseline, args.gene_map, args.output)
    result = compare(args.workspace, args.reference_workspace, args.output,
                     args.reference_label, args.current_label, args.comparison_scope)
    print(json.dumps({"speedup": result["speedup"], "seconds": result["hybrid"]["seconds"]}), flush=True)
