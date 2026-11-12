"""Rebuild a complete module catalog using only pinned database-derived records."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import shutil
import tempfile

import drugcell_ontology as ontology
from prepare_module_graph_inputs import prepare


def rebuild(database_workspace, baseline, gene_map, task, output, batch_size=24, full_go_graph=None):
    source, output = Path(database_workspace), Path(output)
    raw = source / "acquisition/sources"
    genes = ontology.read_gene_map(gene_map); universe = set(genes)
    mapping_path = source / "acquisition/identifier_mapping.jsonl"
    mapping = {r["gene"]: r for r in map(json.loads, mapping_path.read_text().splitlines())}
    hgnc_path = raw / "hgnc.tsv"; hgnc_hash = ontology.sha256(hgnc_path)
    with hgnc_path.open() as stream:
        hgnc = {r["hgnc_id"]: r for r in csv.DictReader(stream, delimiter="\t") if r["status"] == "Approved"}
    proteins = defaultdict(set)
    for h in hgnc.values():
        for protein in h["uniprot_ids"].split("|"):
            if protein: proteins[protein].add(h["hgnc_id"])
    for gene, record in mapping.items():
        h = hgnc[record["hgnc"]]
        if (gene not in universe or record["hgnc_sha256"] != hgnc_hash
                or record["canonical_symbol"] != h["symbol"]
                or gene not in {h["symbol"], *h["alias_symbol"].split("|"), *h["prev_symbol"].split("|")}):
            raise ValueError("Identifier mapping differs from the pinned HGNC crosswalk")
    filenames = {"Reactome": ("reactome_raw.jsonl", "NCBI2Reactome_All_Levels.txt"),
                 "ComplexPortal": ("complexportal_mapping_refined.jsonl", "complexportal.tsv")}
    members = defaultdict(set); counts = Counter(); input_hashes = {}
    with tempfile.TemporaryDirectory(prefix="database-module-science-") as name:
        work = Path(name)
        for d in ("inputs", "knowledge", "acquisition/sources"):
            (work / d).mkdir(parents=True)
        (work / "inputs/go.obo").symlink_to((source / "inputs/go.obo").resolve())
        for filename in ("NCBI2Reactome_All_Levels.txt", "complexportal.tsv", "reactome_hierarchy.tsv", "reactome2go.txt"):
            (work / "acquisition/sources" / filename).symlink_to((raw / filename).resolve())
        with (work / "knowledge/statements.jsonl").open("w") as statements:
            for database, (records_name, snapshot_name) in filenames.items():
                records_path = source / "acquisition" / records_name
                input_hashes[records_name] = ontology.sha256(records_path)
                snapshot = raw / snapshot_name; snapshot_hash = ontology.sha256(snapshot)
                lines = snapshot.read_text().splitlines()
                for line in records_path.read_text().splitlines():
                    r = json.loads(line)
                    if r.get("evidence_class") != "database_derived" or any(e.get("source_name") != database for e in r["evidence"]):
                        raise ValueError("Database module inputs require database-derived source evidence")
                    if not r.get("projection_eligible") or r.get("polarity") != "positive":
                        continue
                    gene = r["subject_label"]
                    if gene not in universe or r["subject_id"] != mapping[gene]["hgnc"]:
                        raise ValueError("Database member differs from the task identifier mapping")
                    for e in r["evidence"]:
                        if e["snapshot_sha256"] != snapshot_hash:
                            raise ValueError("Database snapshot checksum changed")
                        number = int(e["locator"].removeprefix("line:"))
                        values = lines[number - 1].split("\t")
                        if database == "Reactome":
                            if (len(values) != 6 or values[0] != mapping[gene]["entrez"] or values[1] != r["object_id"]
                                    or values[4:] != ["TAS", "Homo sapiens"] or r["relation"] != "member_of_pathway"):
                                raise ValueError("Reactome member differs from its source row")
                        else:
                            h = mapping[gene]["hgnc"]; protein = e["source_protein_id"].split("-")[0]
                            if (values[0] != r["object_id"].removeprefix("ComplexPortal:") or values[3] != "9606"
                                    or not values[5].startswith("ECO:0000353") or proteins[protein] != {h}
                                    or e["source_protein_id"] not in values[-1] or r["relation"] != "member_of_complex"):
                                raise ValueError("Complex member differs from its source composition or mapping")
                    r["object_labels"] = [r["object_label"]]
                    statements.write(json.dumps(r, ensure_ascii=False) + "\n")
                    members[gene].add("EXTERNAL:" + r["object_id"]); counts[database] += 1
        ontology.write_rows(work / "knowledge/gene_attributes.jsonl", [
            {"gene": gene, "attributes": sorted(members[gene])} for gene in genes])
        prepare(work, baseline, gene_map, task, output, batch_size, "all", graph_source=full_go_graph)
    sources = json.loads((output / "sources.json").read_text())
    sources["go.obo"] = str((source / "inputs/go.obo").resolve())
    sources["gene_identifier_crosswalk.tsv"] = str(hgnc_path.resolve())
    shutil.copyfile(mapping_path, output / "identifier_mapping.jsonl")
    sources["identifier_mapping.jsonl"] = str((output / "identifier_mapping.jsonl").resolve())
    if full_go_graph is not None:
        base=Path(full_go_graph).resolve().parent
        manifest=json.loads((base/"full_go_manifest.json").read_text())
        if manifest["sources"]["obo"]["sha256"]!=ontology.sha256(sources["go.obo"]):
            raise ValueError("Complete GO and module catalog use different ontology versions")
        sources["original_go_annotations.gaf.gz"]=manifest["sources"]["gaf"]["path"]
        sources["original_go_annotation_evidence.tsv"]=str(base/"annotation_evidence.tsv")
    ontology.write_json(output / "sources.json", sources)
    modules = json.loads((output / "modules.json").read_text())
    batches = json.loads((output / "module_batches.json").read_text())
    receipt = {"source_policy": "database_only", "database_records": dict(counts),
        "database_modules": dict(Counter(m["source"] for m in modules.values())), "literature_records": 0,
        "catalog_modules": len(modules), "processing_modules": sum(len(b["modules"]) for b in batches),
        "processing_batches": len(batches), "batch_size": batch_size, "gene_universe": len(genes),
        "mapped_genes": len(mapping), "records_sha256": input_hashes,
        "graph_basis": "complete_GO_BP_before_pruning" if full_go_graph else "supplied_functional_graph",
        "source_files": {n: {"path": str(Path(p).resolve()), "sha256": ontology.sha256(p)} for n,p in sources.items()}}
    ontology.write_json(output / "database_lineage.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("database-workspace", "baseline", "gene-map", "task", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--full-go-graph", type=Path)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.database_workspace,args.baseline,args.gene_map,args.task,args.output,args.batch_size,args.full_go_graph),indent=2))
