"""Finalize a completed module-placement pilot and record export timings."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from export_drugcell_module_graph import export
import drugcell_ontology as ontology
import prune_drugcell_ontology as pruning


def finish(workspace, baseline, gene_map, output):
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    while True:
        path = workspace / "status.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        if state.get("status") == "failed":
            ontology.write_json(output / "status.json", {"status": "failed", "pipeline": state})
            raise RuntimeError(state.get("error", "Module-placement pipeline failed"))
        if state.get("status") == "completed":
            break
        ontology.write_json(output / "status.json", {"status": "waiting_for_graph", "pipeline": state,
            "updated_at_utc": datetime.now(timezone.utc).isoformat()})
        time.sleep(15)
    start = time.monotonic()
    report = export(workspace / "knowledge_graph", baseline, gene_map, output / "export")
    export_seconds = time.monotonic() - start
    start = time.monotonic()
    pruned = pruning.prune(output / "export/drugcell_ont.txt", gene_map, output / "pruned")
    prune_seconds = time.monotonic() - start
    timing = json.loads((workspace / "timing.json").read_text())
    graph = json.loads((workspace / "knowledge_graph/graph.json").read_text())
    decisions = []
    for directory in sorted((workspace / "batches").iterdir()):
        if (directory / "accepted_patch.json").is_file():
            decisions += json.loads((directory / "accepted_patch.json").read_text())["decisions"]
    added = {key for key, node in graph["nodes"].items() if node["origin"] != "baseline"}
    genes = ontology.read_gene_map(gene_map)
    retained = ontology.read_ontology(output / "pruned/drugcell_ont.txt", genes)
    result = {"status": "completed", "module_workspace": str(workspace), "timing": timing,
              "actions": dict(Counter(d["action"] for d in decisions)),
              "new_edge_relations": dict(Counter(e["relation"] for e in graph["edges"] if "placement_batch" in e)),
              "model_export": report["statistics"], "export_seconds": export_seconds,
              "pruning_seconds": prune_seconds, "pruned": pruned["statistics"],
              "added_nodes_retained_after_pruning": sorted(added & retained["terms"]),
              "source_task_genes": len(genes), "downstream_training_started": False}
    ontology.write_json(output / "results.json", result)
    lines = [(workspace / "REPORT.md").read_text(), "", "## DrugCell export", "",
             f"The consumer used the frozen reviewed edges. Export took {export_seconds:.2f} seconds; the published-threshold pruning pass took {prune_seconds:.2f} seconds.",
             f"Added nodes retained after pruning: {len(result['added_nodes_retained_after_pruning'])} / {len(added)}.",
             f"Reviewed actions: {json.dumps(result['actions'])}.",
             f"New edge relations: {json.dumps(result['new_edge_relations'])}.",
             "This pilot measures module placement using frozen scientific memberships and source snapshots. Acquisition time belongs to its source workflow. The full task gene universe is unchanged."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n")
    ontology.write_json(output / "status.json", {"status": "completed", "report": str(output / "REPORT.md"),
                         "updated_at_utc": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"status": "completed", "output": str(output), "timing": timing}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "baseline", "gene-map", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    finish(args.workspace, args.baseline, args.gene_map, args.output)
