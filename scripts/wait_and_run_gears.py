"""Wait for an unoccupied GPU, then run the authorized baseline once.

Only queries nvidia-smi. Never stops or modifies another GPU process.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def gpu_candidates():
    result = subprocess.run([
        "nvidia-smi", "--query-gpu=index,uuid,memory.free,utilization.gpu", "--format=csv,noheader,nounits"
    ], text=True, capture_output=True, check=True)
    process_result = subprocess.run([
        "nvidia-smi", "--query-compute-apps=gpu_uuid", "--format=csv,noheader,nounits"
    ], text=True, capture_output=True, check=True)
    busy = {line.strip() for line in process_result.stdout.splitlines() if line.strip().startswith("GPU-")}
    rows = []
    for row in csv.reader(result.stdout.splitlines()):
        index, uuid, free, utilization = [value.strip() for value in row]
        rows.append({"index": int(index), "uuid": uuid, "free_mib": int(free),
                     "utilization_percent": int(utilization), "has_compute_process": uuid in busy})
    return rows


def reserve_gpu(ready):
    """Hold a project-wide per-GPU lock and recheck occupancy before launch."""
    directory = ROOT / "outputs/gears/.gpu_locks"
    directory.mkdir(parents=True, exist_ok=True)
    for chosen in sorted(ready, key=lambda row: row["index"]):
        lock = (directory / (chosen["uuid"] + ".lock")).open("a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            continue
        try:
            current = next((row for row in gpu_candidates() if row["uuid"] == chosen["uuid"]), None)
            if current and not current["has_compute_process"] and current["utilization_percent"] <= 5 and current["free_mib"] >= 16384:
                lock.seek(0)
                lock.truncate()
                lock.write(str(os.getpid()))
                lock.flush()
                return current, lock
        except BaseException:
            lock.close()
            raise
        lock.close()
    return None, None


def run(poll_seconds=30, stable_polls=3, config_path=None, runner_path=None):
    config_path = Path(config_path) if config_path else ROOT / "configs/gears_norman_baseline.json"
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = json.loads(config_path.read_text())
    out = ROOT / config["output_path"]
    out.mkdir(parents=True, exist_ok=True)
    with (out / "queue.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock.write(str(os.getpid()))
        lock.flush()
        return wait_and_run(out, poll_seconds, stable_polls, config_path, runner_path)


def wait_and_run(out, poll_seconds, stable_polls, config_path=None, runner_path=None):

    def status(stage, **extra):
        value = {"stage": stage, "queue_pid": os.getpid(),
                 "updated_at_utc": datetime.now(timezone.utc).isoformat(), **extra}
        temporary = out / "queue_status.json.tmp"
        temporary.write_text(json.dumps(value, indent=2) + "\n")
        temporary.replace(out / "queue_status.json")
        print(json.dumps(value), flush=True)

    if (out / "metrics.json").exists():
        status("already_complete")
        return
    streaks = {}
    while True:
        try:
            preparation_path = out / "preparation.json"
            if not preparation_path.exists() or not json.loads(preparation_path.read_text()).get("graphs_prepared"):
                status("waiting_for_cpu_preparation", next_check_seconds=poll_seconds)
                time.sleep(poll_seconds)
                continue
            rows = gpu_candidates()
            eligible = [row for row in rows if not row["has_compute_process"]
                        and row["utilization_percent"] <= 5 and row["free_mib"] >= 16384]
            streaks = {row["uuid"]: streaks.get(row["uuid"], 0) + 1 for row in eligible}
            ready = [row for row in eligible if streaks[row["uuid"]] >= stable_polls]
            if not ready:
                status("waiting_for_unoccupied_gpu", occupied_gpus=sum(row["has_compute_process"] for row in rows),
                       visible_gpus=len(rows), stable_idle_polls=streaks,
                       next_check_seconds=poll_seconds)
                time.sleep(poll_seconds)
                continue
            chosen, gpu_lock = reserve_gpu(ready)
            if gpu_lock is None:
                status("waiting_for_unoccupied_gpu", reservation_pending=True, next_check_seconds=poll_seconds)
                time.sleep(poll_seconds)
                continue
            environment = os.environ.copy()
            environment.update(CUDA_VISIBLE_DEVICES=chosen["uuid"], OMP_NUM_THREADS="8", MKL_NUM_THREADS="8",
                               OPENBLAS_NUM_THREADS="8", MPLCONFIGDIR=str(ROOT / "outputs/gears/.matplotlib"))
            try:
                with (out / "run.log").open("a", buffering=1) as log:
                    runner = Path(runner_path) if runner_path else ROOT / "scripts/run_gears_baseline.py"
                    command = [str(ROOT / ".venv-gears/bin/python"), "-u", str(runner)]
                    if config_path is not None:
                        command.extend(["--config", str(config_path)])
                    child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                             pass_fds=(gpu_lock.fileno(),))
                    status("baseline_running", selected_gpu=chosen, training_pid=child.pid, runner=str(runner))
                    code = child.wait()
            finally:
                gpu_lock.close()
            status("complete" if code == 0 else "baseline_failed", returncode=code, selected_gpu=chosen)
            return
        except subprocess.CalledProcessError as error:
            status("gpu_query_failed_waiting", error=error.stderr.strip(), next_check_seconds=poll_seconds)
            time.sleep(poll_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--stable-polls", type=int, default=3)
    parser.add_argument("--config", default="configs/gears_norman_baseline.json")
    parser.add_argument("--runner", type=Path)
    args = parser.parse_args()
    if args.poll_seconds < 1 or args.stable_polls < 1:
        parser.error("Polling interval and stable poll count must be positive")
    run(args.poll_seconds, args.stable_polls, args.config, args.runner)
