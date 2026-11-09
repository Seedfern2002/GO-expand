"""Materialize evidence-backed database or literature batches for task_knowledge.

Literature claims are extracted by the retriever agent from cached paper texts;
this program binds and checks quotations, then screens the fixed gene universe.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path.cwd().resolve()
from engine.knowledge import read_json, read_records, sha256, universe_for, workspace_file, write_json, write_rows


def import_batch(task, rows_path, output, batch_id, plan_item_id, root=ROOT, provenance_path=None,
                 snapshot_dir=None, paper_manifest=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new import directory")
    genes, _ = universe_for(task, root)
    rows_path = workspace_file(root, rows_path)
    raw_rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()]
    papers = {}
    provenance = read_json(workspace_file(root, provenance_path)) if provenance_path else None
    if paper_manifest:
        for paper in read_json(workspace_file(root, paper_manifest)):
            if paper["paper_id"] in papers:
                raise ValueError("Deduplicate paper IDs before importing the shared paper bundle")
            if paper["source_uri"] in {p["source_uri"] for p in papers.values()}:
                raise ValueError("A paper URL must be cached only once per evidence bundle")
            text = workspace_file(root, paper["text_path"])
            if sha256(text) != paper["text_sha256"]:
                raise ValueError("Paper text checksum mismatch")
            papers[paper["paper_id"]] = paper
    rows = []
    for original in raw_rows:
        row = dict(original)
        if papers:
            evidence = []
            for ref in row.pop("paper_evidence"):
                paper = papers[ref["paper_id"]]
                evidence.append({"source_name": paper["source_name"], "source_version": paper["source_version"],
                                 "source_uri": paper["source_uri"], "study_id": paper["study_id"],
                                 "locator": ref["locator"], "snapshot_path": paper["text_path"],
                                 "snapshot_sha256": paper["text_sha256"], "quote": ref["quote"],
                                 "assertion_type": ref["assertion_type"]})
            row.update(evidence_class="literature_extracted", evidence=evidence)
        elif "evidence" not in row:
            if not provenance or snapshot_dir is None:
                raise ValueError("Legacy database rows require provenance and a local snapshot directory")
            evidence = []
            for ref in row.pop("evidence_refs"):
                meta = provenance["snapshots"][ref["snapshot"]]
                snapshot = workspace_file(root, str(Path(snapshot_dir) / ref["snapshot"]))
                evidence.append({"source_name": provenance["source_name"], "source_version": provenance["source_version"],
                                 "source_uri": meta["url"], "study_id": "UNRESOLVED:" + provenance["source_name"],
                                 "locator": "line:" + str(ref["line"]), "snapshot_path": str(snapshot),
                                 "snapshot_sha256": meta["sha256"], "assertion_type": "database_record",
                                 "source_evidence_code": ref.get("source_evidence_code"),
                                 "source_confidence": row.get("source_confidence")})
            row.update(evidence_class="database_derived", evidence=evidence)
        rows.append(row)
    output.mkdir(parents=True)
    records_path = output / "records.jsonl"
    write_rows(records_path, rows)
    checked = read_records(records_path, task, root)
    annotated = {r["subject_label"] for r in checked}
    write_json(output / "coverage.json", {"universe_size": len(genes), "genes_screened": len(genes),
                                          "genes_annotated": len(annotated), "record_count": len(rows),
                                          "screening_basis": "All fixed-universe genes matched against this imported evidence batch"})
    write_rows(output / "screening.jsonl", ({"gene": g, "status": "annotated" if g in annotated else "no_support_in_imported_batch"} for g in genes))
    write_json(output / "validation.json", {"validated_rows": len(checked), "failed_rows": 0})
    sources = [{"path": str(rows_path), "sha256": sha256(rows_path)}]
    for name in (provenance_path, paper_manifest):
        if name:
            path = workspace_file(root, name)
            sources.append({"path": str(path), "sha256": sha256(path)})
    write_json(output / "provenance.json", {"input_files": sources, "program_path": str(Path(__file__).resolve()),
                                            "program_sha256": sha256(__file__), "paper_count": len(papers),
                                            "study_ids": sorted({e["study_id"] for r in rows for e in r["evidence"]})})
    batch = {"id": batch_id, "plan_item_id": plan_item_id,
             "source_name": "literature_bundle" if papers else provenance["source_name"] if provenance else "typed_records",
             "source_version": "frozen_bundle", "source_uri": rows_path.as_uri(),
             "records_path": str(records_path), "records_sha256": sha256(records_path),
             "coverage_report_path": str(output / "coverage.json"), "validation_report_path": str(output / "validation.json"),
             "provenance_path": str(output / "provenance.json")}
    write_json(output / "batch.json", batch)
    return batch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--plan-item-id", required=True)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--paper-manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_batch(read_json(args.task), args.records, args.output_dir, args.batch_id,
                                 args.plan_item_id, provenance_path=args.provenance, snapshot_dir=args.snapshot_dir,
                                 paper_manifest=args.paper_manifest), indent=2))
