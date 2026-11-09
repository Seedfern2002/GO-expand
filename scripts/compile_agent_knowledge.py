"""Compile validated task_knowledge stage artifacts into an immutable task overlay."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from go_enrichment.knowledge import compile_knowledge, read_json, sha256, validate_knowledge_review


def compile_run(run_dir, output, root=ROOT):
    run_dir, root = Path(run_dir).resolve(), Path(root).resolve()
    for stage in ("planner", "retriever", "reviewer"):
        directory = run_dir / stage
        execution = read_json(directory / "execution.json")
        manifest = read_json(directory / "manifest.json")
        if manifest.get("workflow") != "task_knowledge" or execution["status"] != "completed":
            raise ValueError("Only completed task_knowledge stages can be compiled")
        if execution["result_sha256"] != sha256(directory / "result.json"):
            raise ValueError("Stage result changed after validation")
        if execution["schema_sha256"] != sha256(directory / "schema.json"):
            raise ValueError("Validated stage schema changed")
        for name in ("task", "plan", "candidates"):
            if name in manifest["inputs"] and manifest["inputs"][name]["sha256"] != sha256(directory / f"{name}.input.json"):
                raise ValueError("Validated stage input changed")
    task = read_json(run_dir / "reviewer/task.input.json")
    plan = read_json(run_dir / "reviewer/plan.input.json")
    candidates = read_json(run_dir / "reviewer/candidates.input.json")
    review = read_json(run_dir / "reviewer/result.json")
    if plan != read_json(run_dir / "planner/result.json") or candidates != read_json(run_dir / "retriever/result.json"):
        raise ValueError("Stage handoff differs from validated upstream result")
    if any(read_json(run_dir / s / "task.input.json") != task for s in ("planner", "retriever")):
        # Validation repairs may add feedback but must not change the task policy.
        def without_feedback(value):
            return {k: v for k, v in value.items() if k != "validation_feedback"}
        if any(without_feedback(read_json(run_dir / s / "task.input.json")) != without_feedback(task) for s in ("planner", "retriever")):
            raise ValueError("Task changed between agent stages")
    paths = validate_knowledge_review(task, candidates, review, root)
    provenance = []
    for s in ("planner", "retriever", "reviewer"):
        provenance += list((run_dir / s).glob("*.input.json"))
        provenance += [run_dir / s / n for n in ("result.json", "execution.json", "manifest.json", "schema.json")]
    provenance += [Path(root / b[k]).resolve() for b in candidates["batches"]
                   for k in ("provenance_path", "coverage_report_path", "validation_report_path")]
    provenance += [Path(root / d["audit_report_path"]).resolve() for d in review["batch_decisions"]]
    return compile_knowledge(task, plan, paths, root, output, provenance, review.get("equivalences_path"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compile_run(args.run_dir, args.output_dir), indent=2))
