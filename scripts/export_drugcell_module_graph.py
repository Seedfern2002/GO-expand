"""Export a frozen agent-reviewed functional graph to the DrugCell format."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import drugcell_ontology as ontology


def safe(root, relative):
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Graph artifact path escapes its product")
    return path


def verify_product(product):
    product = Path(product).resolve()
    manifest = json.loads((product / "freeze_manifest.json").read_text())
    for row in manifest["files"]:
        if ontology.sha256(safe(product, row["path"])) != row["sha256"]:
            raise ValueError("Frozen graph artifact changed")
    if json.loads((product / "validation.json").read_text()).get("passed") is not True:
        raise ValueError("Graph product needs passed validation")
    workspace = product.parent
    for row in manifest["inputs"]["files"]:
        if ontology.sha256(safe(workspace, row["path"])) != row["sha256"]:
            raise ValueError("Graph scientific input changed")
    if ontology.sha256(workspace / "task.json") != manifest["inputs"]["task_sha256"]:
        raise ValueError("Graph scientific task changed")
    for batch in manifest["batch_receipts"]:
        directory = safe(workspace / "batches", batch["batch_id"])
        for relative, key in [("accepted_patch.json", "patch_sha256"), ("reviewer/result.json", "review_sha256")]:
            if ontology.sha256(directory / relative) != batch[key]:
                raise ValueError("Graph review receipt changed")
        for relative, key in [("recipe.json", "recipe_sha256"), ("expansion_receipt.json", "expansion_sha256")]:
            if key in batch and ontology.sha256(directory / relative) != batch[key]:
                raise ValueError("Graph recipe expansion receipt changed")
    return json.loads((product / "graph.json").read_text())


def export(product, baseline_path, gene_map, output):
    product, output = Path(product), Path(output)
    graph = verify_product(product)
    genes = ontology.read_gene_map(gene_map)
    baseline = ontology.read_ontology(baseline_path, genes)
    if graph["genes"] != genes or graph["root"] != baseline["root"]:
        raise ValueError("Graph and DrugCell must share gene order and functional root")
    aliases = {key: key if ontology.valid_model_term(key) else "OVERLAY:" + hashlib.sha256(key.encode()).hexdigest()
               for key in graph["nodes"]}
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("Model identifier collision")
    model_edges = [(aliases[e["parent"]], aliases[e["child"]]) for e in graph["edges"] if e["model_edge"]]
    if len(model_edges) != len(set(model_edges)):
        raise ValueError("Graph contains duplicate model edges")
    memberships = {(aliases[key], gene) for key, node in graph["nodes"].items() for gene in node["direct_genes"]}
    if not baseline["edges"] <= set(model_edges) or not baseline["memberships"] <= memberships:
        raise ValueError("Agent graph must preserve original model structure and memberships")
    combined = ontology.analyze(model_edges, memberships, genes)
    additional = memberships - baseline["memberships"]
    reduced = {pair for pair in additional if not any(
        pair[1] in combined["propagated"][child] for child in combined["children"][pair[0]])}
    final = ontology.analyze(model_edges, baseline["memberships"] | reduced, genes)
    if final["propagated"] != combined["propagated"]:
        raise AssertionError("Membership compression changed model coverage")
    output.mkdir(parents=True, exist_ok=False)
    original = Path(baseline_path).read_bytes()
    additions = set(model_edges) - baseline["edges"]
    with (output / "drugcell_ont.txt").open("wb") as stream:
        stream.write(original)
        if (additions or reduced) and original and not original.endswith(b"\n"):
            stream.write(b"\n")
        for parent, child in sorted(additions):
            stream.write(f"{parent}\t{child}\tdefault\n".encode())
        for term, gene in sorted(reduced):
            stream.write(f"{term}\t{gene}\tgene\n".encode())
    ontology.write_json(output / "annotations.json", final["annotations"])
    ontology.write_json(output / "propagated_annotations.json", final["propagated_annotations"])
    ontology.write_json(output / "genes.json", {"genes": genes})
    ontology.write_json(output / "identifier_map.json", aliases)
    ontology.write_json(output / "source_aliases.json", graph.get("aliases", {}))
    ontology.write_rows(output / "edge_provenance.jsonl", [
        {**edge, "parent": aliases[edge["parent"]], "child": aliases[edge["child"]],
         "semantics": edge["relation"], "original_parent": edge["parent"], "original_child": edge["child"]}
        for edge in graph["edges"]])
    shutil.copyfile(product / "freeze_manifest.json", output / "graph_freeze_manifest.json")
    report = {"status": "exported", "baseline_bytes_preserved": (output / "drugcell_ont.txt").read_bytes().startswith(original),
              "hierarchy_policy": "Use accepted agent-reviewed model edges and preserve their typed scientific provenance",
              "baseline_statistics": baseline["stats"], "statistics": final["stats"],
              "projection_counts": {"added_terms": len(final["terms"] - baseline["terms"]),
                  "added_hierarchy_edges": len(additions), "added_direct_memberships": len(reduced),
                  "compressed_redundant_new_memberships": len(additional - reduced),
                  "new_propagated_memberships": final["stats"]["propagated_memberships"] - baseline["stats"]["propagated_memberships"]},
              "sources": ontology.sources(graph=product / "graph.json", graph_freeze=product / "freeze_manifest.json",
                                           ontology=baseline_path, gene_map=gene_map)}
    report["artifacts"] = {p.name: ontology.sha256(p) for p in sorted(output.iterdir()) if p.is_file()}
    ontology.write_json(output / "projection_manifest.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("product", "baseline", "gene-map", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.product, args.baseline, args.gene_map, args.output), indent=2))
