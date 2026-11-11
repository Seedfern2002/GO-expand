"""Materialize scientific module inputs from frozen memberships and source facts.

The output carries scientific concepts, memberships and pinned external sources.
Task-agent histories, experiment configuration and evaluation results stay out.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

import drugcell_ontology as ontology

PACKAGE = Path(__file__).resolve().parents[1] / "standalone/task_go"
sys.path.insert(0, str(PACKAGE))
from engine.ontology import Ontology
from engine.module_graph import validate_graph
from launch import TASK_FIELDS


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def prepare(workspace, baseline, gene_map, task_card, output, batch_size=8):
    workspace, output = Path(workspace), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    genes = ontology.read_gene_map(gene_map)
    base = ontology.read_ontology(baseline, genes)
    obo_path = workspace / "inputs/go.obo"
    obo = Ontology.read(obo_path)
    nodes = {}
    for term in sorted(base["terms"]):
        concept = obo.terms.get(term)
        nodes[term] = {"id": term, "label": concept.name if concept else term,
                       "definition": concept.definition if concept else "Released functional process",
                       "kind": "biological_process", "origin": "baseline",
                       "direct_genes": sorted(base["direct"][term])}
    graph = {"revision": 0, "root": base["root"], "genes": genes, "nodes": nodes, "aliases": {}, "applied_batches": [],
             "edges": [{"parent": a, "child": b, "relation": "released_hierarchy", "model_edge": True,
                        "evidence_ids": [], "rationale": "Original supplied functional hierarchy"} for a, b in sorted(base["edges"])]}
    validate_graph(graph)
    members = defaultdict(set)
    with (workspace / "knowledge/gene_attributes.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            for attribute in row["attributes"]:
                if attribute.startswith("EXTERNAL:"):
                    members[attribute].add(row["gene"])
    modules = {key: {"id": key, "label": key, "definition": "", "kind": "pathway" if "R-HSA-" in key else "protein_complex",
                     "source": "Reactome" if "R-HSA-" in key else "ComplexPortal" if "ComplexPortal:" in key else "literature",
                     "genes": sorted(values), "go_annotations": [], "evidence_ids": [], "source_relatives": []}
               for key, values in sorted(members.items())}
    facts = {}
    sources = {}
    source_alias = {"reactome_hierarchy.tsv": "pathway_hierarchy.tsv", "reactome2go.txt": "pathway_go_annotations.txt",
                    "complexportal.tsv": "complexes.tsv", "NCBI2Reactome_All_Levels.txt": "pathway_gene_mapping.tsv"}
    for original, local in source_alias.items():
        sources[local] = str((workspace / "acquisition/sources" / original).resolve())
    source_shas = {name: ontology.sha256(path) for name, path in sources.items()}

    def fact(value):
        identifier = "EVID:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]
        facts[identifier] = {"id": identifier, **value}
        return identifier

    def attach(module_id, identifier):
        if module_id in modules and identifier not in modules[module_id]["evidence_ids"]:
            modules[module_id]["evidence_ids"].append(identifier)

    # Source memberships already form a frozen scientific input. One complete
    # source record supplies definition/context per concept; members stay in files.
    done = set()
    with (workspace / "knowledge/statements.jsonl").open() as stream:
        for line in stream:
            record = json.loads(line)
            identifier = "EXTERNAL:" + record["object_id"]
            if identifier not in modules or identifier in done or not record.get("projection_eligible"):
                continue
            done.add(identifier)
            module = modules[identifier]
            module["label"] = record["object_labels"][0]
            selected = next((e for e in record["evidence"] if e.get("snapshot_path", "").split("/")[-1] in source_alias), None)
            if selected is None:
                # A literature-only concept remains available with its scientific
                # definition; primary text import is required before placement.
                module["definition"] = module["label"]
                continue
            metadata = selected.get("concept_metadata", {})
            conditions = selected.get("source_conditions", {})
            module["definition"] = (metadata.get("definition") or conditions.get("Complex properties")
                                    or conditions.get("Description") or module["label"])
            # Keep compact source excerpts while pinning the complete row file.
            module["definition"] = module["definition"][:2400]
            filename = source_alias[selected["snapshot_path"].split("/")[-1]]
            source_path = Path(sources[filename])
            actual_sha = source_shas[filename]
            if actual_sha != selected["snapshot_sha256"]:
                raise ValueError("Pinned source snapshot differs from scientific evidence")
            row = {"type": "source_module_record", "module": identifier, "source": module["source"],
                   "path": "inputs/sources/" + filename, "sha256": actual_sha,
                   "locator": selected["locator"], "source_uri": selected.get("source_uri", ""),
                   "source_version": selected.get("source_version", ""),
                   "description": module["definition"]}
            attach(identifier, fact(row))
            for go in re.findall(r"GO:\d{7}", selected.get("source_GO_annotations", "")):
                concept = obo.terms.get(go)
                if concept and not concept.obsolete:
                    module["go_annotations"].append(go)
                    attach(identifier, fact({**row, "type": "source_go_annotation", "go_id": go,
                                             "go_name": concept.name, "go_namespace": concept.namespace}))
    with Path(sources["pathway_hierarchy.tsv"]).open() as stream:
        for number, line in enumerate(stream, 1):
            values = line.split()
            if len(values) < 2:
                continue
            parent, child = ["EXTERNAL:" + value for value in values[:2]]
            if parent in modules and child in modules:
                identifier = fact({"type": "source_hierarchy", "relation": "source_pathway_parent",
                    "parent": parent, "child": child, "path": "inputs/sources/pathway_hierarchy.tsv", "locator": f"line:{number}",
                    "description": modules[parent]["label"] + " has source child " + modules[child]["label"]})
                attach(parent, identifier); attach(child, identifier)
                modules[parent]["source_relatives"].append(child); modules[child]["source_relatives"].append(parent)
    with Path(sources["pathway_go_annotations.txt"]).open() as stream:
        for number, line in enumerate(stream, 1):
            match = re.search(r"Reactome:(R-HSA-\d+).*?>.*?(GO:\d{7})", line)
            if not match:
                continue
            module_id, go = "EXTERNAL:" + match[1], match[2]
            if module_id in modules and go in obo.terms and not obo.terms[go].obsolete:
                modules[module_id]["go_annotations"].append(go)
                attach(module_id, fact({"type": "source_go_annotation", "module": module_id, "go_id": go,
                    "go_name": obo.terms[go].name, "go_namespace": obo.terms[go].namespace,
                    "path": "inputs/sources/pathway_go_annotations.txt", "locator": f"line:{number}", "description": line.strip()}))
    for module in modules.values():
        module["go_annotations"] = sorted(set(module["go_annotations"]))
        module["source_relatives"] = sorted(set(module["source_relatives"]))
    # The timing pilot processes coherent source clusters; the catalog and shared
    # graph retain the complete task gene universe and all source concepts.
    wanted = ["EXTERNAL:R-HSA-73894", "EXTERNAL:R-HSA-1640170"]  # DNA Repair, Cell Cycle in the pinned source.
    batches = []
    selected = set()
    for i, seed in enumerate(wanted, 1):
        if seed not in modules:
            raise ValueError("The declared source cluster is absent")
        queue = [seed]; cluster = []
        for parent in queue:
            if parent not in selected:
                cluster.append(parent); selected.add(parent)
            if len(cluster) == batch_size:
                break
            children = sorted(f["child"] for f in facts.values() if f.get("parent") == parent and f.get("relation") == "source_pathway_parent")
            queue.extend(child for child in children if child not in queue)
        if len(cluster) != batch_size:
            raise ValueError("Insufficient modules in the declared source cluster")
        batches.append({"id": f"module_batch_{i:03d}", "modules": cluster})
    complexes = [key for key, module in modules.items() if module["source"] == "ComplexPortal"
                 and module["evidence_ids"] and any(go in base["terms"] for go in module["go_annotations"])]
    complexes.sort(key=lambda key: (-len(modules[key]["genes"]), modules[key]["label"]))
    batches.append({"id": "module_batch_003", "modules": complexes[:batch_size]})
    task = json.loads(Path(task_card).read_text())
    if task.keys() - TASK_FIELDS:
        raise ValueError("Supply a scientific task card")
    write(output / "task.json", task)
    write(output / "genes.json", {"genes": genes})
    write(output / "annotations.json", base["propagated_annotations"])
    write(output / "baseline_graph.json", graph)
    write(output / "modules.json", modules)
    write(output / "placement_evidence.json", facts)
    write(output / "module_batches.json", batches)
    sources["go.obo"] = str(obo_path.resolve())
    write(output / "sources.json", sources)
    write(output / "preparation_receipt.json", {"source_memberships_sha256": ontology.sha256(workspace / "knowledge/gene_attributes.jsonl"),
          "source_statements_sha256": ontology.sha256(workspace / "knowledge/statements.jsonl"),
          "baseline_sha256": ontology.sha256(baseline), "catalog_modules": len(modules),
          "pilot_modules": sum(len(b["modules"]) for b in batches), "batches": batches,
          "source_files": {key: {"path": value, "sha256": ontology.sha256(value)} for key, value in sources.items()}})
    print(json.dumps({"output": str(output), "catalog_modules": len(modules), "pilot_modules": sum(len(b["modules"]) for b in batches),
                      "batches": [{"id": b["id"], "labels": [modules[key]["label"] for key in b["modules"]]} for b in batches]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "baseline", "gene-map", "task", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    prepare(args.workspace, args.baseline, args.gene_map, args.task, args.output, args.batch_size)
