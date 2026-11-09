"""Write a matched baseline/augmentation metric comparison, optionally on completion."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]


def read_optional(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_report(baseline, augmented, output):
    original = read_optional(baseline / "metrics.json")
    modified = read_optional(augmented / "metrics.json")
    queue = read_optional(augmented / "queue_status.json")
    status = read_optional(augmented / "status.json")
    complete = bool(original and modified)
    failed = status.get("stage") == "failed" or queue.get("stage") == "baseline_failed"
    state = "complete" if complete else "failed" if failed else "pending"
    rows = []
    for key in ("mse", "mse_de", "pearson", "pearson_de"):
        before = original.get("test", {}).get(key)
        after = modified.get("test", {}).get(key)
        row = {"metric": key, "lower_is_better": key.startswith("mse"), "baseline": before,
               "augmented": after, "delta_augmented_minus_baseline": None, "relative_error_reduction_percent": None}
        if before is not None and after is not None:
            row["delta_augmented_minus_baseline"] = after - before
            if row["lower_is_better"] and before != 0:
                row["relative_error_reduction_percent"] = 100 * (before - after) / before
        rows.append(row)
    result = {"updated_at_utc": datetime.now(timezone.utc).isoformat(), "state": state,
              "baseline_run": str(baseline), "augmented_run": str(augmented), "metrics": rows,
              "augmentation_verification": read_optional(augmented / "augmentation_verification.json"),
              "queue_stage": queue.get("stage"), "training_stage": status.get("stage"),
              "metric_files": [{"path": str(run / "metrics.json"),
                                "sha256": hashlib.sha256((run / "metrics.json").read_bytes()).hexdigest()}
                               for run in (baseline, augmented) if (run / "metrics.json").exists()]}
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "comparison.json.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output / "comparison.json")
    lines = ["# Matched GEARS GO comparison", "", f"State: {state}.", "",
             "Augmentation: " + read_optional(augmented / "run_config.json").get(
                 "go_annotation_source", "Frozen task-specific knowledge overlay"
             ) + ".",
             "Training settings, split, model seed, gene order and coexpression graph are checked against the baseline.",
             "Checkpoint selection uses validation mse_de. The table contains test metrics.", "",
             "| Metric | Baseline | Augmented | Augmented - baseline | Error reduction (%) |",
             "|---|---:|---:|---:|---:|"]
    def fmt(value):
        return "pending" if value is None else f"{value:.8f}"
    for row in rows:
        values = [row["baseline"], row["augmented"], row["delta_augmented_minus_baseline"], row["relative_error_reduction_percent"]]
        cells = [fmt(value) for value in values]
        if not row["lower_is_better"]:
            cells[-1] = "—"
        lines.append("| " + " | ".join([row["metric"], *cells]) + " |")
    lines += ["", "MSE metrics: lower is better. Pearson metrics: higher is better.", "",
              f"Baseline: `{baseline}`", f"Augmented: `{augmented}`", ""]
    temporary = output / "REPORT.md.tmp"
    temporary.write_text("\n".join(lines))
    temporary.replace(output / "REPORT.md")
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "outputs/gears/norman_baseline_seed1_retry1")
    parser.add_argument("--augmented", type=Path, default=ROOT / "outputs/gears/norman_augmented_seed1")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/analysis/norman_gears_comparison_001")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        state = write_report(args.baseline.resolve(), args.augmented.resolve(), args.output.resolve())
        if state != "pending" or not args.wait:
            print(json.dumps({"state": state, "report": str(args.output / "REPORT.md")}), flush=True)
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Metric comparison remains pending after the requested wait period")
        time.sleep(30)
