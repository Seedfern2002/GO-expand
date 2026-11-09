"""Maintain a compact metric table for a group of independently queued runs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from run_gears_baseline import write_json

METRICS = ("mse", "mse_de", "pearson", "pearson_de")


def summarize(runs, output):
    rows = []
    for label, path in runs:
        def read(name):
            item = path / name
            return json.loads(item.read_text()) if item.exists() else {}
        metrics, queue, status = read("metrics.json"), read("queue_status.json"), read("status.json")
        state = "complete" if metrics else "failed" if (
            queue.get("stage") == "baseline_failed" or status.get("stage") == "failed"
        ) else "pending"
        rows.append({"label": label, "run": str(path), "state": state,
                     "stage": status.get("stage") or queue.get("stage"),
                     "metrics": {key: metrics.get("test", {}).get(key) for key in METRICS}})
    terminal = all(row["state"] in {"complete", "failed"} for row in rows)
    state = "complete" if all(row["state"] == "complete" for row in rows) else "failed" if terminal else "pending"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "comparison.json", {"updated_at_utc": datetime.now(timezone.utc).isoformat(),
                                            "state": state, "runs": rows})
    lines = ["# Matched GEARS graph experiments", "", f"State: {state}.", "",
             "Test metrics from the model selected by minimum validation MSE_DE in each run.",
             "All runs use split seed 1, model seed 0 and the same 15-epoch training recipe.", "",
             "| Run | State | MSE ↓ | MSE_DE ↓ | Pearson ↑ | Pearson_DE ↑ |",
             "|---|---|---:|---:|---:|---:|"]
    for row in rows:
        values = ["pending" if row["metrics"][key] is None else f"{row['metrics'][key]:.8f}" for key in METRICS]
        lines.append("| " + " | ".join([row["label"], row["state"], *values]) + " |")
    lines += ["", *[f"{row['label']}: `{row['run']}`" for row in rows], ""]
    temporary = output / "REPORT.md.tmp"
    temporary.write_text("\n".join(lines))
    temporary.replace(output / "REPORT.md")
    return terminal


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    runs = [(label, Path(path).resolve()) for label, path in (item.split("=", 1) for item in args.run)]
    while True:
        terminal = summarize(runs, args.output.resolve())
        if terminal or not args.wait:
            break
        time.sleep(30)
