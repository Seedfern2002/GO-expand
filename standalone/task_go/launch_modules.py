"""Launch isolated module placement from declared scientific graph inputs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

from engine.knowledge import sha256
from engine.module_graph import validate_graph
from launch import prepare, sandbox_command
from place_modules import write


def prepare_modules(task, genes, annotations, ontology, graph, modules, evidence, batches,
                    sources, output, model, reasoning_effort="medium", timeout=3600, workflow="module_placement"):
    if workflow not in {"module_placement", "module_recipes"}:
        raise ValueError("Unknown module workflow")
    source_files = json.loads(Path(sources).read_text())
    root = prepare(task, genes, "genes", annotations, ontology, output, model, reasoning_effort, timeout)
    values = {"baseline_graph.json": json.loads(Path(graph).read_text()),
              "modules.json": json.loads(Path(modules).read_text()),
              "placement_evidence.json": json.loads(Path(evidence).read_text()),
              "module_batches.json": json.loads(Path(batches).read_text())}
    graph_value = values["baseline_graph.json"]
    if graph_value.keys() - {"revision", "root", "genes", "nodes", "edges", "aliases", "applied_batches"}:
        raise ValueError("The graph contains fields outside the scientific input contract")
    for node in graph_value["nodes"].values():
        if node.keys() - {"id", "label", "definition", "kind", "origin", "direct_genes"}:
            raise ValueError("Node metadata contains fields outside the scientific input contract")
    for module in values["modules.json"].values():
        if module.keys() - {"id", "label", "definition", "kind", "source", "genes", "go_annotations", "evidence_ids", "source_relatives"}:
            raise ValueError("Module metadata contains fields outside the scientific input contract")
    validate_graph(values["baseline_graph.json"])
    universe = json.loads((root / "inputs/genes.json").read_text())["genes"]
    if values["baseline_graph.json"]["genes"] != universe:
        raise ValueError("The graph and task need the same fixed gene universe and order")
    supplied = [m for batch in values["module_batches.json"] for m in batch["modules"]]
    if len(supplied) != len(set(supplied)) or not set(supplied) <= values["modules.json"].keys():
        raise ValueError("Each processing module must be declared exactly once")
    if len({b["id"] for b in values["module_batches.json"]}) != len(values["module_batches.json"]):
        raise ValueError("Batch identities must be unique")
    for module in values["modules.json"].values():
        if not set(module["genes"]) <= set(universe):
            raise ValueError("Source module contains a gene outside the task")
    for name, value in values.items():
        write(root / "inputs" / name, value)
    target = root / "inputs/sources"; target.mkdir()
    for name, path in source_files.items():
        if Path(name).name != name:
            raise ValueError("A scientific source name must be a basename")
        shutil.copyfile(path, target / name)
    source_lines = {}
    for identifier, fact in values["placement_evidence.json"].items():
        if fact.get("id") != identifier or fact.keys() - {
                "id", "type", "module", "source", "path", "sha256", "locator", "source_uri", "source_version",
                "description", "go_id", "go_name", "go_namespace", "relation", "parent", "child"}:
            raise ValueError("Evidence requires a scientific source-bound record")
        relative = Path(fact["path"])
        if relative.parent != Path("inputs/sources") or relative.name not in source_files:
            raise ValueError("Evidence must reference a declared source snapshot")
        if relative.name not in source_lines:
            source_lines[relative.name] = (target / relative.name).read_text().splitlines()
        locator = fact["locator"]
        if not locator.startswith("line:"):
            raise ValueError("Source evidence requires an exact row locator")
        number = int(locator[5:])
        if not 1 <= number <= len(source_lines[relative.name]):
            raise ValueError("Source locator is outside its pinned file")
        line = source_lines[relative.name][number - 1]
        if fact["type"] == "source_hierarchy":
            expected = [fact["parent"].removeprefix("EXTERNAL:"), fact["child"].removeprefix("EXTERNAL:")]
            if line.split()[:2] != expected:
                raise ValueError("Native hierarchy endpoints differ from the source row")
        elif fact["type"] == "source_go_annotation" and fact["go_id"] not in line:
            raise ValueError("GO annotation differs from the source row")
        if fact.get("module"):
            source_id = fact["module"].removeprefix("EXTERNAL:").removeprefix("ComplexPortal:")
            if source_id not in line:
                raise ValueError("Module identity differs from the source row")
    # Input manifests contain local scientific paths; host source paths stay outside.
    manifest = json.loads((root / "inputs/manifest.json").read_text())
    manifest["input_types"] += ["original_functional_graph", "source_module_catalog", "source_evidence", "module_processing_partitions"]
    manifest["files"] = [{"path": str(p.relative_to(root)), "sha256": sha256(p)}
                         for p in sorted((root / "inputs").rglob("*")) if p.is_file() and p.name != "manifest.json"]
    write(root / "inputs/manifest.json", manifest)
    runtime = json.loads((root / "runtime.json").read_text())
    runtime.update(workflow=workflow, module_batch_sizes=[len(b["modules"]) for b in values["module_batches.json"]])
    write(root / "runtime.json", runtime)
    receipt = json.loads((Path(output) / "receipt.json").read_text())
    receipt.update(workflow=workflow, inputs_sha256=sha256(root / "inputs/manifest.json"),
                   source_modules=len(values["modules.json"]), processing_modules=len(supplied),
                   processing_batches=len(values["module_batches.json"]),
                   module_prompts=[{"path": str(p.relative_to(root)), "sha256": sha256(p)}
                                   for p in sorted((root / "pipeline/prompts/modules").glob("*.md"))])
    write(Path(output) / "receipt.json", receipt)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task", "genes", "annotations", "ontology", "graph", "modules", "evidence", "batches", "sources", "run-dir", "codex-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--stage-timeout-seconds", type=int, default=3600)
    parser.add_argument("--workflow", choices=["module_placement", "module_recipes"], default="module_placement")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.run_dir.resolve()
    root = prepare_modules(args.task, args.genes, args.annotations, args.ontology, args.graph,
                           args.modules, args.evidence, args.batches, args.sources, output,
                           args.model, args.reasoning_effort, args.stage_timeout_seconds, args.workflow)
    if args.prepare_only:
        print(json.dumps({"workspace": str(root), "status": "prepared"})); return
    auth_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    auth = auth_root / "auth.json"
    if not auth.is_file() or not shutil.which("bwrap"):
        raise RuntimeError("The isolated Codex runtime needs existing login and bubblewrap")
    with (output / "pipeline.log").open("w") as log:
        child = subprocess.Popen(sandbox_command(output, args.codex_bin, auth, "place_modules.py"),
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    receipt = {"pid": child.pid, "workspace": str(root), "log": str(output / "pipeline.log"),
               "detached": True, "created_at_utc": datetime.now(timezone.utc).isoformat()}
    write(output / "launch.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
