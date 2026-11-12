"""Recover committed graph batches and publish their frozen membership product."""

import json
from pathlib import Path

from engine.knowledge import sha256, write_json
from engine.module_graph import apply_patch, coverage, fingerprint


def load_progress(root, baseline, catalog, facts, batches):
    root = Path(root)
    path = root / "graph/current.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, baseline)
        return baseline, []
    current = json.loads(path.read_text())
    committed = current.get("applied_batches", [])
    if committed != [b["id"] for b in batches[:len(committed)]]:
        raise ValueError("Committed batches must form the declared processing prefix")
    replayed, timings = baseline, []
    for batch in batches[:len(committed)]:
        directory = root / "batches" / batch["id"]
        patch = json.loads((directory / "accepted_patch.json").read_text())
        replayed = apply_patch(replayed, catalog, facts, patch, batch["modules"])
        validation = json.loads((directory / "validation.json").read_text())
        if not validation["passed"] or validation["after_sha256"] != fingerprint(replayed):
            raise ValueError("Committed batch differs from its validated graph")
        timings.append(json.loads((directory / "timing.json").read_text()))
    if fingerprint(replayed) != fingerprint(current):
        raise ValueError("Current graph differs from replayed accepted batches")
    return current, timings


def archive_attempt(root, batch_id):
    root = Path(root)
    parent = root / "failed_batches"; parent.mkdir(exist_ok=True)
    count = len(list(parent.glob(batch_id + "_attempt_*")))
    directory = root / "batches" / batch_id
    if directory.exists():
        directory.rename(parent / f"{batch_id}_attempt_{count + 1:03d}")
        count += 1
    return count


def publish_memberships(root, graph):
    """Publish reviewed graph coverage in the existing scientific knowledge format."""
    root = Path(root); output = root / "knowledge"; output.mkdir(exist_ok=False)
    propagated = coverage(graph)
    attributes = {gene: [] for gene in graph["genes"]}
    for term, genes in sorted(propagated.items()):
        for gene in genes:
            attributes[gene].append(term)
    with (output / "gene_attributes.jsonl").open("w") as stream:
        for gene in graph["genes"]:
            stream.write(json.dumps({"gene": gene, "attributes": attributes[gene]}) + "\n")
    task = json.loads((root / "task.json").read_text())
    write_json(output / "task.json", task)
    write_json(output / "validation.json", {"passed": True, "basis": "Frozen independently reviewed module graph",
        "gene_universe_count": len(graph["genes"]), "coverage_semantics": "Computational coverage along declared model edges"})
    write_json(output / "summary.json", {"genes": len(graph["genes"]), "attributes": len(graph["nodes"]),
        "gene_attribute_memberships": sum(map(len, attributes.values())),
        "source_policy": "database_only" if task.get("retrieval_budget", {}).get("reading_mode") == "database_only" else "reviewed_modules",
        "graph_freeze_sha256": sha256(root / "knowledge_graph/freeze_manifest.json")})
    source = json.loads((root / "inputs/manifest.json").read_text())
    inputs = [*source["files"], {"path": "task.json", "sha256": sha256(root / "task.json")},
              {"path": "knowledge_graph/graph.json", "sha256": sha256(root / "knowledge_graph/graph.json")},
              {"path": "knowledge_graph/freeze_manifest.json", "sha256": sha256(root / "knowledge_graph/freeze_manifest.json")}]
    write_json(output / "freeze_manifest.json", {"files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(output.iterdir())],
        "inputs": inputs, "derivation": "Reviewed module graph with complete fixed-universe source memberships"})
