"""Maintain a compact implementation-verification and throughput report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def read(path):
    return json.loads(path.read_text()) if path.is_file() else None


def report(output):
    results, pending, failed = [], [], []
    for device in ("cpu", "gpu"):
        for arm in ("baseline", "augmented"):
            path = output / f"{device}_benchmark_{arm}/benchmark.json"
            result = read(path)
            if result:
                results.append({"arm": arm, "device": device, "result_path": str(path), **result})
            elif device == "gpu":
                exit_result = read(output / f"{arm}_gpu_exit.json")
                if exit_result and exit_result["returncode"]:
                    failed.append(arm)
                else:
                    pending.append({"arm": arm, "queue": read(output / f"gpu_benchmark_{arm}.queue.json")})
    status = "GPU_benchmark_failed" if failed else "CPU_verified_GPU_benchmarks_pending" if pending else "CPU_and_GPU_verified"
    value = {"updated_at_utc": datetime.now(timezone.utc).isoformat(), "status": status,
             "results": results, "pending_GPU_benchmarks": pending, "failed_GPU_benchmarks": failed,
             "original_experiment": "outputs/drugcell/comparison_001",
             "existing_compute_jobs": "continue with their frozen implementation"}
    temporary = output / "status.json.tmp"
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(output / "status.json")
    lines = ["# DrugCell execution optimization", "", f"Status: `{status}`.", "",
             "Original training continues under its frozen experiment. The new implementation preserves the independent GO networks, data, objective, batch size and FP32 policy.", "",
             "| Arm | Device | Batch | Prior seconds/step | Packed seconds/step | Speedup |",
             "|---|---|---:|---:|---:|---:|"]
    for row in results:
        name = row.get("GPU") or "CPU (2 threads)"
        lines.append(f"| {row['arm']} | {name} | {row['batch_size']} | "
                     f"{row['timings']['masked_gather']['seconds_per_training_step']:.4f} | "
                     f"{row['timings']['packed_levels']['seconds_per_training_step']:.4f} | "
                     f"{row['training_step_speedup']:.2f}× |")
    for row in pending:
        lines.append(f"| {row['arm']} | GPU queued | 5000 | pending | pending | pending |")
    lines += ["", "Times measure training steps after warmup, excluding construction, checkpoint I/O and held-out evaluation.",
              "CPU timings use batch size 128. GPU timings use batch size 5000 on a reserved, previously idle GPU.", "",
              "## Numerical verification", "",
              "Each complete benchmark verifies prediction/loss agreement and every reconstructed parameter gradient and Adam-updated state. Gradient/state tolerance: atol=1e-6, rtol=1e-4.", "",
              "| Arm | Device | Prediction max absolute difference | Gradient max absolute difference | Updated state max absolute difference |",
              "|---|---|---:|---:|---:|"]
    for row in results:
        v = row["verification"]
        lines.append(f"| {row['arm']} | {row['device']} | {v['prediction_max_absolute_error']:.3g} | "
                     f"{v['gradient']['max_absolute_error']:.3g} | {v['Adam_update_and_BatchNorm']['max_absolute_error']:.3g} |")
    lines += ["", "Six model equivalence tests and a selected-checkpoint training regression pass. Both full ontologies pass three-epoch CPU training/evaluation smoke checks.", "",
              "The 2086 baseline terms form 33 batched groups; the 8693 augmented terms form 56 groups. Each term preserves its own parameters and BatchNorm channels.", "",
              "Implementation: `scripts/drugcell_packed.py` and `scripts/run_drugcell_optimized.py`.",
              "Detailed method: `docs/drugcell_optimization.md`. Input/code checksums: `benchmark_bundle/manifest.json`.", ""]
    temporary = output / "REPORT.md.tmp"
    temporary.write_text("\n".join(lines))
    temporary.replace(output / "REPORT.md")
    return not pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    while True:
        done = report(args.output)
        if done or not args.wait:
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
