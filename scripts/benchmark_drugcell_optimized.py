"""Verify and time released-mask versus packed DrugCell training steps.

Bundles contain fixed training observations, frozen ontologies and pinned code.
GPU measurements acquire a stable-idle GPU through the project reservation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(bundle, config_path, samples=5000):
    import numpy as np
    import run_drugcell as reference
    config = json.loads(Path(config_path).read_text())
    root = Path(config.get("project_root", ROOT))
    ontology = Path(config["knowledge"]["baseline_ontology"])
    source, splits, records, _ = reference.verify_inputs(Path(config_path), config, ontology, 0, root)
    sys.path.insert(0, str(source / "code"))
    import util
    cells = util.load_mapping(source / "data/cell2ind.txt")
    drugs = util.load_mapping(source / "data/drug2ind.txt")
    pairs, labels = reference.read_pairs(splits["train"], cells, drugs, samples)
    mutations = np.loadtxt(source / "data/cell2mutation.txt", delimiter=",", dtype=np.float32)
    fingerprints = np.loadtxt(source / "data/drug2fingerprint.txt", delimiter=",", dtype=np.float32)
    features = np.concatenate((mutations[pairs[:, 0]], fingerprints[pairs[:, 1]]), axis=1)
    bundle = Path(bundle)
    bundle.mkdir(parents=True, exist_ok=False)
    (bundle / "code").mkdir()
    for name in ["drugcell_packed.py", "drugcell_masked_layers.py", "run_drugcell.py",
                 "benchmark_drugcell_optimized.py", "wait_and_run_gears.py"]:
        shutil.copyfile(ROOT / "scripts" / name, bundle / "code" / name)
    for name in ("drugcell_NN.py", "util.py"):
        shutil.copyfile(source / "code" / name, bundle / "code" / name)
    shutil.copyfile(source / "data/gene2ind.txt", bundle / "gene2ind.txt")
    for arm in ("baseline", "augmented"):
        shutil.copyfile(config["knowledge"][arm + "_ontology"], bundle / (arm + ".txt"))
    np.savez_compressed(bundle / "training_batch.npz", features=features, labels=labels)
    write(bundle / "manifest.json", {"samples": len(labels), "seed": config["model_seed"],
          "training": config["released_training_settings"], "input_records": records,
          "scope": "Fixed training batch for implementation equivalence and runtime; knowledge stays frozen",
          "files": {str(p.relative_to(bundle)): digest(p) for p in sorted(bundle.rglob("*")) if p.is_file()}})
    print(json.dumps({"bundle": str(bundle.resolve()), "samples": len(labels)}))


def compare(reference, packed, gradients, torch):
    exported = packed.export_upstream(gradients=gradients)
    source = {name: p.grad for name, p in reference.named_parameters()} if gradients else reference.state_dict()
    errors, ratios = [], []
    if set(source) != set(exported):
        raise AssertionError("Reconstructed parameter schema differs")
    for name, value in source.items():
        if value is None:
            continue
        delta = (value.detach() - exported[name]).abs()
        errors.append(delta.max().float())
        ratios.append((delta / (1e-6 + 1e-4 * value.detach().abs())).max().float())
    maximum = float(torch.stack(errors).max())
    ratio = float(torch.stack(ratios).max())
    return {"max_absolute_error": maximum, "max_tolerance_ratio": ratio,
            "atol": 1e-6, "rtol": 1e-4, "passed": ratio <= 1, "tensors": len(errors)}


def benchmark(bundle, output, device, batch_size, steps, warmup, threads, arm):
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(threads)
    sys.dont_write_bytecode = True
    import numpy as np
    import torch
    import networkx
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new benchmark output directory")
    manifest = json.loads((bundle / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        if digest(bundle / name) != expected:
            raise ValueError(f"Benchmark bundle changed: {name}")
    torch.set_num_threads(threads)
    torch.manual_seed(manifest["seed"])
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    sys.path.insert(0, str(bundle / "code"))
    import drugcell_NN
    import util
    from drugcell_packed import PackedDrugCell
    from drugcell_masked_layers import install_masked_gene_forward
    from run_drugcell import initialize_model, apply_masks, make_masks
    genes = util.load_mapping(bundle / "gene2ind.txt")
    with contextlib.redirect_stdout(io.StringIO()):
        graph, root, sizes, direct = util.load_ontology(bundle / (arm + ".txt"), genes)
        original = drugcell_NN.drugcell_nn(sizes, direct, graph.copy(), len(genes), 2048, root, 6, [100, 50, 6], 6)
    initialize_model(original, torch)
    packed = PackedDrugCell(original)
    install_masked_gene_forward(original)
    original.to(device)
    packed.to(device)
    masks = make_masks(original, torch)
    data = np.load(bundle / "training_batch.npz")
    x = torch.as_tensor(data["features"][:batch_size], device=device)
    y = torch.as_tensor(data["labels"][:batch_size], device=device).reshape(-1, 1)
    settings = manifest["training"]
    optimizers = [torch.optim.Adam(m.parameters(), lr=settings["learning_rate"],
                  betas=tuple(settings["betas"]), eps=settings["epsilon"]) for m in (original, packed)]
    original.train()
    packed.train()
    sample_x, sample_y = x[:64], y[:64]
    heads, _ = original(sample_x)
    loss = sum((1 if name == "final" else 0.2) * (values - sample_y).square().mean()
               for name, values in heads.items())
    prediction, packed_loss = packed.objective(sample_x, sample_y)
    prediction_delta = float((prediction - heads["final"]).abs().max())
    torch.testing.assert_close(prediction, heads["final"], atol=1e-6, rtol=1e-4)
    torch.testing.assert_close(loss, packed_loss, atol=1e-3, rtol=1e-5)
    loss.backward()
    packed_loss.backward()
    apply_masks(masks, gradients=True)
    gradient_check = compare(original, packed, True, torch)
    for optimizer in optimizers:
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
    update_check = compare(original, packed, False, torch)
    output.mkdir(parents=True)
    verification = {"prediction_max_absolute_error": prediction_delta,
                    "loss_absolute_error": abs(float(loss) - float(packed_loss)),
                    "gradient": gradient_check, "Adam_update_and_BatchNorm": update_check}
    write(output / "verification.json", verification)
    if not gradient_check["passed"] or not update_check["passed"]:
        raise AssertionError("Full-ontology numerical verification exceeded tolerance")
    del heads, loss, packed_loss, prediction

    def synchronize():
        if device == "cuda":
            torch.cuda.synchronize()

    timings = {}
    for model, optimizer, name in zip((original, packed), optimizers, ("masked_gather", "packed_levels")):
        def step():
            optimizer.zero_grad(set_to_none=True)
            if name == "masked_gather":
                aux, _ = model(x)
                _ = aux["final"].detach().cpu().numpy()
                objective = sum((1 if key == "final" else 0.2) * (value - y).square().mean()
                                for key, value in aux.items())
                if not torch.isfinite(objective).item():
                    raise RuntimeError("Nonfinite reference objective")
            else:
                _, objective = model.objective(x, y)
            objective.backward()
            if name == "masked_gather":
                apply_masks(masks, gradients=True)
            optimizer.step()
            if name == "masked_gather":
                _ = float(objective.detach())
        for _ in range(warmup):
            step()
        synchronize()
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        for _ in range(steps):
            step()
        synchronize()
        elapsed = time.perf_counter() - started
        timings[name] = {"seconds_per_training_step": elapsed / steps,
                         "examples_per_second": len(x) * steps / elapsed,
                         "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else None}
    result = {"status": "passed", "arm": arm, "device": device,
              "GPU": torch.cuda.get_device_name() if device == "cuda" else None,
              "batch_size": len(x), "steps": steps, "warmup_steps": warmup,
              "versions": {"torch": torch.__version__, "numpy": np.__version__, "networkx": networkx.__version__},
              "verification": verification, "model": packed.statistics(), "timings": timings,
              "training_step_speedup": timings["masked_gather"]["seconds_per_training_step"] / timings["packed_levels"]["seconds_per_training_step"],
              "scope": "Same frozen ontology, training observations, FP32, optimizer and objective; excludes construction/checkpoint/test timing"}
    write(output / "benchmark.json", result)
    print(json.dumps(result, indent=2))


def queue(args):
    import wait_and_run_gears as gpu_queue
    root = Path(args.bundle).resolve()
    gpu_queue.ROOT = Path(args.lock_root).resolve() if args.lock_root else ROOT
    status = Path(args.output).with_name(Path(args.output).name + ".queue.json")
    streaks = {}
    while True:
        rows = gpu_queue.gpu_candidates()
        eligible = [r for r in rows if not r["has_compute_process"] and r["utilization_percent"] <= 5 and r["free_mib"] >= 16384]
        streaks = {r["uuid"]: streaks.get(r["uuid"], 0) + 1 for r in eligible}
        ready = [r for r in eligible if streaks[r["uuid"]] >= 3]
        selected, lock = gpu_queue.reserve_gpu(ready)
        if lock:
            environment = os.environ.copy()
            environment.update(CUDA_VISIBLE_DEVICES=selected["uuid"], OMP_NUM_THREADS=str(args.threads), PYTHONDONTWRITEBYTECODE="1")
            command = [sys.executable, "-u", str(Path(__file__).resolve()), "--bundle", str(root),
                       "--output", str(Path(args.output).resolve()), "--device", "cuda", "--arm", args.arm,
                       "--batch-size", str(args.batch_size), "--steps", str(args.steps),
                       "--warmup", str(args.warmup), "--threads", str(args.threads)]
            try:
                write(status, {"status": "running", "GPU": selected})
                result = subprocess.run(command, env=environment, pass_fds=(lock.fileno(),))
                write(status, {"status": "complete" if result.returncode == 0 else "failed", "GPU": selected})
                return result.returncode
            finally:
                lock.close()
        write(status, {"status": "waiting_for_unoccupied_GPU", "stable_idle_polls": streaks})
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--prepare-config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--arm", choices=("baseline", "augmented"), default="baseline")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--lock-root", type=Path)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--steps", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args()
    if min(args.batch_size, args.steps, args.threads) < 1 or args.batch_size < 2 or args.warmup < 0:
        parser.error("Require batch >=2, positive steps/threads and nonnegative warmup")
    if args.prepare_config:
        prepare(args.bundle, args.prepare_config, args.batch_size)
    elif not args.output:
        parser.error("Specify a fresh output directory")
    elif args.queue:
        return queue(args)
    else:
        benchmark(args.bundle, args.output, args.device, args.batch_size, args.steps, args.warmup, args.threads, args.arm)


if __name__ == "__main__":
    raise SystemExit(main())
