#!/usr/bin/env python3
"""Export accepted, validated review records as a versioned knowledge overlay."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from run_agent_stage import read_json, validate_result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-stage-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--text-corrections", type=Path, help="Optional recorded corrections to evidence summary wording; relation and context are retained.")
    args = parser.parse_args()
    stage = args.review_stage_dir.resolve()
    preparation = read_json(stage / "manifest.json")
    if preparation.get("workflow", "record") == "task_batch":
        parser.error("this exporter handles record reviews; task_batch approved artifacts require a batch compiler")
    execution = read_json(stage / "execution.json")
    if preparation["stage"] != "reviewer" or execution["status"] != "completed":
        parser.error("requires a successfully completed reviewer stage")
    if digest(stage / "result.json") != execution["result_sha256"]:
        parser.error("review result changed after validation")
    if digest(stage / "schema.json") != execution["schema_sha256"]:
        parser.error("schema changed after validation")
    for name in ("task", "plan", "candidates"):
        if digest(stage / f"{name}.input.json") != preparation["inputs"][name]["sha256"]:
            parser.error(f"{name} snapshot changed after preparation")
    review = read_json(stage / "result.json")
    validate_result(stage, preparation, review)
    accepted = sorted((decision["normalized_record"] for decision in review["decisions"] if decision["verdict"] == "accept"), key=lambda record: record["id"])
    remaining = [decision for decision in review["decisions"] if decision["verdict"] != "accept"]
    corrections = None
    if args.text_corrections:
        corrections = read_json(args.text_corrections)
        if not corrections.get("actor"):
            parser.error("text corrections require a recorded actor")
        by_id = {record["id"]: record for record in accepted}
        for edit in corrections["edits"]:
            if not edit.get("before") or not edit.get("after") or not edit.get("reason") or not edit.get("source_uri"):
                parser.error("text corrections require before, after, reason and source_uri")
            record = by_id.get(edit["candidate_id"])
            matches = [] if record is None else [item for item in record["evidence"] if edit["before"] in item["support_summary"]]
            if len(matches) != 1:
                parser.error("each correction must match exactly one accepted evidence summary")
            matches[0]["support_summary"] = matches[0]["support_summary"].replace(edit["before"], edit["after"])
        validate_result(stage, preparation, review)
    payload = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in accepted)
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("output directory exists; use a new overlay version")
    output.mkdir(parents=True)
    (output / "overlay.jsonl").write_text(payload, encoding="utf-8")
    (output / "unresolved.json").write_text(json.dumps(remaining, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if corrections is not None:
        (output / "text_corrections.json").write_text(json.dumps(corrections, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "1.0", "task_id": review["task_id"],
        "status": "reviewed_knowledge_overlay",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "review_stage": str(stage), "review_sha256": digest(stage / "result.json"),
        "input_hashes": {name: digest(stage / f"{name}.input.json") for name in ("task", "plan", "candidates")},
        "overlay_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "accepted_count": len(accepted), "decision_counts": dict(Counter(decision["verdict"] for decision in review["decisions"])),
        "knowledge_layers": dict(Counter(record["knowledge_layer"] for record in accepted)),
        "relations": dict(Counter(record["relation"] for record in accepted)),
        "projection_status": "not_projected",
        "text_corrections_sha256": digest(output / "text_corrections.json") if corrections is not None else None,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
