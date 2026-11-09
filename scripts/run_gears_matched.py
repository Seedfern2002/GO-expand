"""Run matched GEARS experiments with result-associated evaluation telemetry.

Upstream train(), optimizer, loss and checkpoint-selection logic are unchanged.
Evaluation wrappers persist their existing return values and timing information.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import pickle
import random
import subprocess
import sys
import time
import traceback

from gears_evaluation_context import EvaluationContexts

ROOT = Path(__file__).resolve().parents[1]


def normalize(value):
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if hasattr(value, "tolist"):
        return normalize(value.tolist())
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not __import__("math").isfinite(value):
        return None
    return value


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(normalize(value), ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def initialize_cuda_telemetry(torch, device):
    # The CUDA allocator's device statistics are populated lazily on its first
    # allocation. Resetting them before the probe fails in PyTorch 2.5.1.
    probe = torch.ones(8, device=device)
    assert probe.sum().item() == 8
    torch.cuda.synchronize(device)
    del probe
    torch.cuda.reset_peak_memory_stats(device)


def verify_augmentation_inputs(config):
    augmentation = config.get("go_augmentation")
    if augmentation is None:
        return None
    manifest_path = ROOT / augmentation["manifest_path"]
    if sha256(manifest_path) != augmentation["manifest_sha256"]:
        raise ValueError("Augmentation manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text())
    for artifact in manifest["files"]:
        if sha256(ROOT / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Frozen augmentation input changed: {artifact['path']}")
    reference = json.loads((ROOT / manifest["reference_config_path"]).read_text())
    metadata = {"experiment", "output_path", "go_annotation_source", "go_augmentation", "device"}
    if {k: v for k, v in config.items() if k not in metadata} != {k: v for k, v in reference.items() if k not in metadata}:
        raise ValueError("Training settings differ from the reference baseline")
    return manifest


def run(config, device):
    run_started = time.perf_counter()
    out = ROOT / config["output_path"]
    out.mkdir(parents=True, exist_ok=True)
    if (out / "metrics.json").exists():
        raise FileExistsError(f"Completed baseline already exists: {out}")

    def status(stage, **details):
        value = {"stage": stage, "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                 "wall_seconds": time.perf_counter() - run_started, **details}
        write_json(out / "status.json", value)
        print(json.dumps(normalize(value), ensure_ascii=False), flush=True)

    try:
        augmentation_manifest = verify_augmentation_inputs(config)
        status("importing_dependencies")
        import numpy as np
        import scipy.sparse as sp
        import scanpy as sc
        import torch
        import torch_geometric

        checkout = ROOT / "third_party/GEARS"
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        assert commit == config["implementation_commit"]
        sys.path.insert(0, str(checkout))
        from gears import PertData, GEARS
        import gears
        gears_module = importlib.import_module("gears.gears")
        assert Path(gears.__file__).resolve().is_relative_to(checkout)
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable in this execution environment")
        torch.set_num_threads(config["torch_threads"])
        torch.set_num_interop_threads(2)
        random.seed(config["model_seed"])
        np.random.seed(config["model_seed"])
        torch.manual_seed(config["model_seed"])
        torch.cuda.manual_seed_all(config["model_seed"])
        initialize_cuda_telemetry(torch, device)

        write_json(out / "run_config.json", {**config, "device": device})
        environment = {"python": sys.version, "torch": torch.__version__,
                       "cuda_runtime": torch.version.cuda, "torch_geometric": torch_geometric.__version__,
                       "scanpy": sc.__version__, "gpu": torch.cuda.get_device_name(device),
                       "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                       "source_commit": commit, "source_path": str(checkout)}
        write_json(out / "environment.json", environment)
        # Upstream make_GO uses ./data/go_essential_<dataset>.csv as its cache.
        # Keep that cache inside this run while keeping the raw dataset shared.
        (out / "data").mkdir(exist_ok=True)
        os.chdir(out)
        data_path = ROOT / config["data_path"]
        source_files = [data_path / "gene2go_all.pkl", data_path / "norman.zip",
                        data_path / "norman/perturb_processed.h5ad"]
        write_json(out / "input_files.json", [
            {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in source_files
        ])
        status("loading_official_norman_dataset", gpu=environment["gpu"])
        pert_data = PertData(str(data_path), default_pert_graph=config["default_pert_graph"])
        pert_data.load(data_name=config["dataset"])
        pert_data.prepare_split(
            split=config["split"], seed=config["split_seed"],
            train_gene_set_size=config["train_gene_set_size"],
            combo_seen2_train_frac=config["combo_seen2_train_frac"],
        )
        pert_data.get_dataloader(batch_size=config["batch_size"], test_batch_size=config["test_batch_size"])
        write_json(out / "split.json", pert_data.set2conditions)
        write_json(out / "subgroups.json", pert_data.subgroup)
        if augmentation_manifest is not None:
            reference_run = ROOT / augmentation_manifest["reference_run"]
            if normalize(pert_data.set2conditions) != json.loads((reference_run / "split.json").read_text()):
                raise ValueError("Augmented run split differs from the baseline")
            if normalize(pert_data.subgroup) != json.loads((reference_run / "subgroups.json").read_text()):
                raise ValueError("Augmented run subgroups differ from the baseline")
        write_json(out / "dataset_summary.json", {
            "cells": pert_data.adata.n_obs, "readout_genes": pert_data.adata.n_vars,
            "perturbation_graph_genes": len(pert_data.pert_names),
            "conditions": int(pert_data.adata.obs.condition.nunique()),
            "split_conditions": {key: len(value) for key, value in pert_data.set2conditions.items()},
            "split_examples": {key: len(loader.dataset) for key, loader in pert_data.dataloader.items()},
            "split_batches": {key: len(loader) for key, loader in pert_data.dataloader.items()},
        })
        # Build upstream's coexpression cache while X is still sparse; its
        # implementation explicitly calls X_tr.toarray().
        from gears.utils import get_coexpression_network_from_train
        get_coexpression_network_from_train(
            pert_data.adata, config["model"]["coexpress_threshold"],
            config["model"]["num_similar_genes_co_express_graph"], str(data_path),
            config["dataset"], config["split"], config["split_seed"],
            config["train_gene_set_size"], pert_data.set2conditions,
        )
        # SciPy 1.14 cannot index sparse matrices using a pandas Series in the
        # upstream constructor. Dense storage preserves every expression value.
        sparse_expression = None
        if sp.issparse(pert_data.adata.X):
            pert_data.adata = pert_data.adata.copy()
            sparse_expression = pert_data.adata.X
            pert_data.adata.X = pert_data.adata.X.toarray()
        status("initializing_model_and_original_graphs")
        # Explicitly preserve upstream's torch initialization seed (0), separate
        # from split seed (1), after dataset preparation consumed RNG state.
        random.seed(config["model_seed"])
        np.random.seed(config["model_seed"])
        torch.manual_seed(config["model_seed"])
        torch.cuda.manual_seed_all(config["model_seed"])
        model = GEARS(pert_data, device=device, weight_bias_track=False)
        # Upstream post-training analyses expect sparse X.toarray(). Only the
        # constructor needs the temporary dense representation.
        if sparse_expression is not None:
            model.adata.X = sparse_expression
            model.ctrl_adata = model.adata[model.adata.obs.condition == "ctrl"]
        model.model_initialize(**config["model"])
        if augmentation_manifest is not None:
            expected = torch.load(ROOT / augmentation_manifest["expected_graphs_path"], map_location="cpu", weights_only=False)
            for key in ("G_go", "G_go_weight", "G_coexpress", "G_coexpress_weight"):
                if not torch.equal(model.config[key].detach().cpu(), expected[key]):
                    raise ValueError(f"Initialized graph differs from frozen input: {key}")
            for key in ("pert_list", "gene_list"):
                if list(getattr(model, key)) != list(expected[key]):
                    raise ValueError(f"Gene ordering differs from baseline: {key}")
            write_json(out / "augmentation_verification.json", {
                "manifest_sha256": config["go_augmentation"]["manifest_sha256"],
                "split_matches_baseline": True, "subgroups_match_baseline": True,
                "go_graph_matches_topk_experiment": True, "coexpression_graph_matches_baseline": True,
                "training_settings_match_baseline": True, "gene_order_matches_baseline": True,
            })
        write_json(out / "model_summary.json", {
            "parameters": sum(parameter.numel() for parameter in model.model.parameters()),
            "go_edges": int(model.config["G_go"].shape[1]),
            "coexpression_edges": int(model.config["G_coexpress"].shape[1]),
        })
        torch.save({"G_go": model.config["G_go"].cpu(), "G_go_weight": model.config["G_go_weight"].cpu(),
                    "G_coexpress": model.config["G_coexpress"].cpu(),
                    "G_coexpress_weight": model.config["G_coexpress_weight"].cpu(),
                    "pert_list": model.pert_list, "gene_list": model.gene_list}, out / "original_graphs.pt")

        original_evaluate = gears_module.evaluate
        original_metrics = gears_module.compute_metrics
        events = []
        evaluation_contexts = EvaluationContexts()
        best_val = float("inf")
        epoch_number = 0
        loaders = model.dataloader

        def captured_evaluate(loader, net, uncertainty, target_device):
            nonlocal epoch_number
            phase = next(key.removesuffix("_loader") for key, value in loaders.items() if value is loader)
            if phase == "train":
                epoch_number += 1
            status(f"evaluating_{phase}", epoch=epoch_number)
            started = time.perf_counter()
            result = original_evaluate(loader, net, uncertainty, target_device)
            evaluation_contexts.remember(result, phase, epoch_number, time.perf_counter() - started)
            return result

        def captured_metrics(results):
            nonlocal best_val
            current = evaluation_contexts.take(results)
            metrics, per_perturbation = original_metrics(results)
            event = {**current, "metrics": metrics, "wall_seconds": time.perf_counter() - run_started}
            events.append(event)
            write_json(out / "history.json", events)
            if current["phase"] == "val" and metrics["mse_de"] < best_val:
                best_val = float(metrics["mse_de"])
                checkpoint = out / "checkpoint"
                checkpoint.mkdir(exist_ok=True)
                torch.save(model.model.state_dict(), checkpoint / "model.pt")
                with (checkpoint / "config.pkl").open("wb") as handle:
                    pickle.dump(model.config, handle)
                write_json(out / "best_validation.json", event)
            if current["phase"] == "test":
                write_json(out / "test_metrics.json", metrics)
                write_json(out / "test_per_perturbation.json", per_perturbation)
                perturbations = np.unique(results["pert_cat"])
                predictions, truths = [], []
                for perturbation in perturbations:
                    mask = results["pert_cat"] == perturbation
                    predictions.append(results["pred"][mask].mean(axis=0))
                    truths.append(results["truth"][mask].mean(axis=0))
                np.savez_compressed(out / "test_perturbation_means.npz", perturbations=perturbations,
                                    predictions=np.stack(predictions), truths=np.stack(truths),
                                    genes=np.asarray(model.gene_list),
                                    control_mean=model.ctrl_expression.detach().cpu().numpy())
            status("metrics_recorded", **event)
            return metrics, per_perturbation

        def capture_analysis(function, filename):
            def wrapped(*args, **kwargs):
                status(f"analysis_{filename}", epoch=epoch_number)
                result = function(*args, **kwargs)
                write_json(out / filename, result)
                return result
            return wrapped

        gears_module.evaluate = captured_evaluate
        gears_module.compute_metrics = captured_metrics
        gears_module.deeper_analysis = capture_analysis(gears_module.deeper_analysis, "test_deeper_analysis.json")
        gears_module.non_dropout_analysis = capture_analysis(gears_module.non_dropout_analysis, "test_non_dropout_analysis.json")
        status("training", epochs=config["training"]["epochs"])
        training_started = time.perf_counter()
        model.train(**config["training"])
        training_seconds = time.perf_counter() - training_started
        model.save_model(str(out / "checkpoint"))
        test_metrics = json.loads((out / "test_metrics.json").read_text())
        best = json.loads((out / "best_validation.json").read_text())
        metrics = {"test": test_metrics, "best_validation": best, "epochs_completed": epoch_number,
                   "train_eval_analysis_seconds": training_seconds,
                   "total_run_seconds": time.perf_counter() - run_started,
                   "peak_gpu_memory_bytes": torch.cuda.max_memory_allocated(device)}
        assert epoch_number == config["training"]["epochs"]
        write_json(out / "metrics.json", metrics)
        status("complete", **metrics)
    except BaseException as error:
        status("failed", error=repr(error), traceback=traceback.format_exc())
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/gears_norman_baseline.json")
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    run(json.loads((ROOT / args.config).read_text()), args.device)
