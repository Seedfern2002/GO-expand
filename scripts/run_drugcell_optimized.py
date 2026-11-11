"""Train and evaluate a fixed DrugCell fold with packed independent GO networks.

The training objective and masked initialization follow the released source.
Validation Pearson chooses a single retained checkpoint. Test labels enter the
runtime after that choice; the selected model is evaluated once on its test fold.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DIRECT_SUFFIX = "_direct_gene_layer.weight"


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def resolve(root, path):
    path = Path(path)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def regression_metrics(truth, predicted):
    """Report undefined correlations as null, preserving sample counts/errors."""
    import numpy as np
    from scipy.stats import rankdata

    truth = np.asarray(truth, dtype=np.float64).reshape(-1)
    predicted = np.asarray(predicted, dtype=np.float64).reshape(-1)
    if len(truth) != len(predicted) or not len(truth):
        raise ValueError("Metrics require nonempty aligned observations and predictions")
    if not (np.isfinite(truth).all() and np.isfinite(predicted).all()):
        raise ValueError("Metrics require finite observations and predictions")

    def correlation(x, y):
        if len(x) < 2:
            return None
        centered_x, centered_y = x - x.mean(), y - y.mean()
        denominator = np.linalg.norm(centered_x) * np.linalg.norm(centered_y)
        if denominator == 0:
            return None
        return float(np.clip(np.dot(centered_x, centered_y) / denominator, -1, 1))

    mse = float(np.mean((truth - predicted) ** 2))
    return {"n": len(truth), "spearman": correlation(rankdata(truth), rankdata(predicted)),
            "pearson": correlation(truth, predicted), "mse": mse, "rmse": math.sqrt(mse)}


def improves_validation(candidate, incumbent):
    """Match the released >= comparison, including its latest-tie behavior."""
    return candidate is not None and math.isfinite(candidate) and (
        incumbent is None or candidate >= incumbent)


def make_masks(model, torch):
    masks = []
    for name, parameter in model.named_parameters():
        if name.endswith(DIRECT_SUFFIX):
            term = name.removesuffix(DIRECT_SUFFIX)
            genes = list(model.term_direct_gene_map[term])
            rows = torch.arange(len(genes), device=parameter.device)
            columns = torch.tensor(genes, dtype=torch.long, device=parameter.device)
            masks.append((parameter, rows, columns))
    return masks


def apply_masks(masks, gradients=False):
    for parameter, rows, columns in masks:
        tensor = parameter.grad if gradients else parameter.data
        if tensor is not None:
            retained = tensor[rows, columns].clone()
            tensor.zero_()
            tensor[rows, columns] = retained


def initialize_model(model, torch):
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.mul_(0.1)
        masks = make_masks(model, torch)
        apply_masks(masks)
    return masks


def read_pairs(path, cells, drugs, limit=None):
    import numpy as np

    pairs, labels = [], []
    with Path(path).open() as stream:
        for number, line in enumerate(stream, 1):
            cell, drug, label = line.rstrip().split("\t")
            if cell not in cells or drug not in drugs or not math.isfinite(float(label)):
                raise ValueError(f"Invalid response row at {path}:{number}")
            pairs.append((cells[cell], drugs[drug]))
            labels.append(float(label))
            if limit is not None and len(pairs) == limit:
                break
    if not pairs:
        raise ValueError(f"Empty response partition: {path}")
    return np.asarray(pairs, dtype=np.int64), np.asarray(labels, dtype=np.float32)


def batch_features(pairs, cell_features, drug_features, torch):
    indices = torch.as_tensor(pairs, dtype=torch.long, device=cell_features.device)
    return torch.cat((cell_features[indices[:, 0]], drug_features[indices[:, 1]]), dim=1)


def predict(model, pairs, cell_features, drug_features, batch_size, torch):
    model.eval()
    outputs = []
    pairs = torch.as_tensor(pairs, dtype=torch.long, device=cell_features.device)
    with torch.no_grad():
        for start in range(0, len(pairs), batch_size):
            features = batch_features(pairs[start:start + batch_size], cell_features, drug_features, torch)
            outputs.append(model.predict_final(features).reshape(-1))
    return torch.cat(outputs).cpu().numpy()


def per_drug_metrics(pairs, truth, predicted, output):
    import numpy as np

    rows, valid = [], []
    for drug in sorted(set(pairs[:, 1].tolist())):
        mask = pairs[:, 1] == drug
        result = regression_metrics(truth[mask], predicted[mask])
        rows.append({"drug_index": int(drug), **result})
        if result["spearman"] is not None:
            valid.append(result["spearman"])
    with Path(output).open("w") as stream:
        stream.write("drug_index\tn\tspearman\tpearson\tmse\trmse\n")
        for row in rows:
            stream.write("\t".join("" if row[key] is None else str(row[key])
                                   for key in ("drug_index", "n", "spearman", "pearson", "mse", "rmse")) + "\n")
    return {"per_drug_spearman_mean": float(np.mean(valid)) if valid else None,
            "per_drug_spearman_median": float(np.median(valid)) if valid else None,
            "per_drug_valid_count": len(valid), "per_drug_total_count": len(rows)}


def fit_model(model, train, validation, load_test, cell_features, drug_features,
              settings, output, torch, progress=None, install_forward=None):
    """Execute the matched objective and defer test loading until selection."""
    import numpy as np

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    train_pairs, train_labels = train
    validation_pairs, validation_labels = validation
    batch_size = settings["batch_size"]
    epochs = settings["max_epochs"]
    if len(train_pairs) % batch_size == 1 or len(train_pairs) < 2:
        raise ValueError("Training batches require at least two observations for BatchNorm")
    forward_adapter = model.statistics()
    train_indices = torch.as_tensor(train_pairs, dtype=torch.long, device=cell_features.device)
    train_targets = torch.as_tensor(train_labels, device=cell_features.device).reshape(-1, 1)
    optimizer = torch.optim.Adam(model.parameters(), lr=settings["learning_rate"],
                                 betas=tuple(settings["betas"]), eps=settings["epsilon"])
    best_epoch, best_validation, best_pearson = None, None, None
    auxiliary_heads = None
    checkpoint_path = output / "best.pt"
    history_path = output / "training_metrics.jsonl"
    for epoch in range(1, epochs + 1):
        epoch_started = time.monotonic()
        model.train()
        train_outputs = []
        summed_loss = torch.zeros((), dtype=torch.float64, device=cell_features.device)
        finite_losses = torch.ones((), dtype=torch.bool, device=cell_features.device)
        batch_count = math.ceil(len(train_pairs) / batch_size)
        for batch, start in enumerate(range(0, len(train_pairs), batch_size), 1):
            pairs = train_indices[start:start + batch_size]
            target = train_targets[start:start + batch_size]
            features = batch_features(pairs, cell_features, drug_features, torch)
            optimizer.zero_grad(set_to_none=True)
            final, loss = model.objective(features, target, settings["auxiliary_loss_weight_per_head"])
            auxiliary_heads = forward_adapter["auxiliary_heads"]
            train_outputs.append(final.detach().reshape(-1))
            finite_losses.logical_and_(torch.isfinite(loss.detach()))
            loss.backward()
            optimizer.step()
            summed_loss.add_(loss.detach().to(torch.float64) * len(pairs))
            if progress and (batch == 1 or batch % 10 == 0 or batch == batch_count):
                elapsed = time.monotonic() - epoch_started
                progress("training", epoch=epoch, max_epochs=epochs, batch=batch,
                         batches=batch_count, epoch_elapsed_seconds=elapsed,
                         estimated_training_epoch_seconds=elapsed / batch * batch_count,
                         best_epoch=best_epoch, best_validation_pearson=best_pearson)
        if not finite_losses.item():
            raise RuntimeError(f"Nonfinite objective during epoch {epoch}")
        train_result = regression_metrics(train_labels, torch.cat(train_outputs).cpu().numpy())
        validation_predictions = predict(model, validation_pairs, cell_features, drug_features, batch_size, torch)
        validation_result = regression_metrics(validation_labels, validation_predictions)
        selected = improves_validation(validation_result["pearson"], best_pearson)
        if selected:
            best_epoch, best_pearson, best_validation = epoch, validation_result["pearson"], validation_result
            temporary = checkpoint_path.with_name("best.pt.tmp")
            torch.save({"model_state_dict": model.state_dict(), "epoch": epoch,
                        "validation": validation_result, "selection_metric": "validation_pearson"}, temporary)
            temporary.replace(checkpoint_path)
        row = {"epoch": epoch, "train": train_result, "validation": validation_result,
               "training_objective": float(summed_loss) / len(train_pairs),
               "selected": selected, "best_epoch": best_epoch,
               "epoch_seconds": time.monotonic() - epoch_started}
        with history_path.open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
        print(json.dumps(row, allow_nan=False), flush=True)
    if best_epoch is None:
        raise RuntimeError("Validation Pearson was undefined at every epoch; no checkpoint selected")
    del optimizer
    if progress:
        progress("evaluating_selected_checkpoint", selected_epoch=best_epoch,
                 best_validation_pearson=best_pearson)
    checkpoint = torch.load(checkpoint_path, map_location=cell_features.device, weights_only=True)
    model.load_state_dict(checkpoint["model_state_dict"])
    del checkpoint
    test_pairs, test_labels = load_test()
    test_predictions = predict(model, test_pairs, cell_features, drug_features, batch_size, torch)
    test_result = regression_metrics(test_labels, test_predictions)
    test_result.update(per_drug_metrics(test_pairs, test_labels, test_predictions, output / "per_drug_metrics.tsv"))
    with gzip.open(output / "predictions.tsv.gz", "wt") as stream:
        stream.write("cell_index\tdrug_index\tobserved\tpredicted\n")
        for pair, truth, predicted in zip(test_pairs, test_labels, test_predictions):
            stream.write(f"{int(pair[0])}\t{int(pair[1])}\t{float(truth):.10g}\t{float(predicted):.10g}\n")
    return {"selected_epoch": best_epoch, "selection_metric": "validation_pearson",
            "best_validation": best_validation, "test": test_result,
            "training_epochs": epochs, "auxiliary_head_count": auxiliary_heads,
            "elapsed_training_evaluation_seconds": time.monotonic() - started,
            "forward_adapter": forward_adapter,
            "checkpoint": "best.pt", "predictions": "predictions.tsv.gz",
            "per_drug_metrics": "per_drug_metrics.tsv"}


def verify_ontology_origin(ontology, baseline, config, root, record):
    """Validate either an additive ontology or a declared, hashed pruning product."""
    if ontology.read_bytes().startswith(baseline.read_bytes()):
        return
    derivation = config["knowledge"].get("ontology_derivation", {})
    if derivation.get("operation") != "drugcell_prune":
        raise ValueError("The evaluated ontology must preserve the released pruned baseline as its byte prefix or declare a frozen pruning product")
    manifest_path = record("ontology_derivation_manifest", resolve(root, derivation["manifest"]),
                           derivation["manifest_sha256"])
    manifest = read_json(manifest_path)
    if manifest.get("status") != "pruned" or manifest["artifacts"]["drugcell_ont.txt"] != sha256(ontology):
        raise ValueError("Evaluated ontology differs from the frozen pruning product")
    parent = record("parent_augmented_ontology", resolve(root, derivation["parent_ontology"]),
                    derivation["parent_ontology_sha256"])
    if manifest["sources"]["ontology"]["sha256"] != sha256(parent):
        raise ValueError("Pruning manifest has a different parent ontology")
    if not parent.read_bytes().startswith(baseline.read_bytes()):
        raise ValueError("Parent augmentation does not preserve the released baseline")


def verify_inputs(config_path, config, ontology, fold, root):
    """Validate pinned code, feature/response inputs, split and ontology origin."""
    source_manifest_path = resolve(root, config["source_manifest"])
    source_manifest = read_json(source_manifest_path)
    source = resolve(root, source_manifest["local_path"])
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != source_manifest["commit"]:
        raise ValueError("DrugCell source commit differs from the pinned manifest")
    records = {}

    def record(name, path, expected=None):
        path = Path(path).resolve()
        digest = sha256(path)
        if expected is not None and digest != expected:
            raise ValueError(f"Pinned input checksum mismatch: {name}")
        records[name] = {"path": str(path), "sha256": digest}
        return path

    record("comparison_config", config_path)
    record("source_manifest", source_manifest_path)
    for name, expected in source_manifest["files"].items():
        record("upstream/" + name, source / name, expected)
    prepared = resolve(root, config["data"]["prepared_directory"])
    for name in ("frozen_manifest", "frozen_split_manifest"):
        if bool(config["data"].get(name)) != bool(config["data"].get(name + "_sha256")):
            raise ValueError(f"Frozen input requires both its path and SHA256: {name}")
    data_manifest_path = resolve(root, config["data"].get("frozen_manifest", prepared / "manifest.json"))
    record("data_manifest", data_manifest_path, config["data"].get("frozen_manifest_sha256"))
    data_manifest = read_json(data_manifest_path)
    if data_manifest["source_commit"] != commit:
        raise ValueError("Prepared data and pinned code have different source commits")
    for name, item in data_manifest["source_inputs"].items():
        record("prepared_input/" + name, item["path"], item["sha256"])
    expected_split_hash = data_manifest["split_manifest"]["sha256"]
    if config["data"].get("frozen_split_manifest_sha256", expected_split_hash) != expected_split_hash:
        raise ValueError("Frozen data and split manifests disagree on the split SHA256")
    split_manifest_path = record("split_manifest", resolve(root, config["data"].get("frozen_split_manifest",
                                 prepared / data_manifest["split_manifest"]["path"])), expected_split_hash)
    split_manifest = read_json(split_manifest_path)
    protocol = split_manifest["protocol"]
    if protocol["seed"] != config["data"]["split_seed"] or protocol["group_key"] != ["cell_identifier", "drug_identifier"]:
        raise ValueError("Split seed or unit differs from the experiment contract")
    if protocol["validation_unique_pairs_per_fold"] != config["data"]["validation_pairs_per_fold"]:
        raise ValueError("Validation size differs from the experiment contract")
    selected = next(item for item in split_manifest["folds"] if item["fold"] == fold)
    splits = {name: record("split/" + name, prepared / item["path"], item["sha256"])
              for name, item in selected["partitions"].items()}
    baseline = record("baseline_ontology", resolve(root, config["knowledge"]["baseline_ontology"]),
                      source_manifest["files"]["data/drugcell_ont.txt"])
    record("ontology", ontology)
    verify_ontology_origin(ontology, baseline, config, root, record)
    record("runner", Path(__file__).resolve())
    return source, splits, records, data_manifest


def run(config_path, fold, ontology, output, device="cuda", threads=8, max_epochs=None, smoke_rows=None):
    started = time.monotonic()
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    root = Path(config.get("project_root", ROOT)).resolve()
    ontology, output = resolve(root, ontology), resolve(root, output)
    output.mkdir(parents=True, exist_ok=True)
    if fold not in config["data"]["folds"]:
        raise ValueError("Fold is outside the declared experiment")
    lock = (output / "run.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (output / "run_config.json").exists() or (output / "metrics.json").exists():
        lock.close()
        raise FileExistsError("Use a fresh output directory for each training run")

    def progress(stage, **extra):
        atomic_json(output / "progress.json", {"stage": stage, "fold": fold, "pid": os.getpid(),
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": time.monotonic() - started, **extra})

    try:
        progress("validating_inputs")
        source, splits, inputs, data_manifest = verify_inputs(config_path, config, ontology, fold, root)
        if device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[name] = str(threads)
        sys.dont_write_bytecode = True
        import numpy as np
        import networkx as nx
        import scipy
        import torch

        torch.set_num_threads(threads)
        seed = config["model_seed"]
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if device == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("The selected CUDA device is unavailable")
            torch.cuda.manual_seed_all(seed)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            torch.backends.cudnn.benchmark = False
        target = torch.device(device)
        forward_mode = "packed_levels"
        helper_path = Path(__file__).with_name("drugcell_packed.py")
        helper_spec = importlib.util.spec_from_file_location("drugcell_packed", helper_path)
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        inputs["packed_model_adapter"] = {"path": str(helper_path), "sha256": sha256(helper_path)}
        code = source / "code"
        sys.path.insert(0, str(code))
        util = importlib.import_module("util")
        model_module = importlib.import_module("drugcell_NN")
        if Path(util.__file__).resolve() != code / "util.py" or Path(model_module.__file__).resolve() != code / "drugcell_NN.py":
            raise RuntimeError("Upstream modules resolved outside the pinned source")
        data = source / "data"
        genes = util.load_mapping(data / "gene2ind.txt")
        cells = util.load_mapping(data / "cell2ind.txt")
        drugs = util.load_mapping(data / "drug2ind.txt")
        cell_features_np = np.loadtxt(data / "cell2mutation.txt", delimiter=",", dtype=np.float32)
        drug_features_np = np.loadtxt(data / "drug2fingerprint.txt", delimiter=",", dtype=np.float32)
        if cell_features_np.shape != (len(cells), len(genes)) or drug_features_np.shape != (len(drugs), 2048):
            raise ValueError("Feature dimensions differ from the fixed entity maps")
        settings = dict(config["released_training_settings"])
        if max_epochs is not None:
            settings["max_epochs"] = max_epochs
        if settings["shuffle"] or settings["released_early_stopping"]:
            raise ValueError("This runner implements the released fixed-epoch, ordered-batch protocol")
        progress("constructing_model")
        with (output / "model_construction.log").open("w") as log, contextlib.redirect_stdout(log):
            graph, ontology_root, sizes, direct = util.load_ontology(str(ontology), genes)
            if not nx.is_directed_acyclic_graph(graph):
                raise ValueError("DrugCell ontology must be a DAG")
            graph_edges, graph_terms = graph.number_of_edges(), graph.number_of_nodes()
            model = model_module.drugcell_nn(sizes, direct, graph.copy(), len(genes), drug_features_np.shape[1],
                      ontology_root, settings["genotype_hiddens"], settings["drug_hiddens"], settings["final_hiddens"])
        initialize_model(model, torch)
        reference_parameter_count = sum(p.numel() for p in model.parameters())
        model = helper.PackedDrugCell(model).to(target)
        cell_features = torch.as_tensor(cell_features_np, device=target)
        drug_features = torch.as_tensor(drug_features_np, device=target)
        train = read_pairs(splits["train"], cells, drugs, smoke_rows)
        validation = read_pairs(splits["validation"], cells, drugs, smoke_rows)
        architecture = {"ontology_terms": graph_terms, "hierarchy_edges": graph_edges,
                        "direct_gene_memberships": sum(map(len, direct.values())),
                        "auxiliary_head_count": graph_terms + len(settings["drug_hiddens"]) + 1,
                        "genes": len(genes), "drugs": len(drugs), "cells": len(cells), "root": ontology_root}
        run_config = {"fold": fold, "seed": seed, "device": device, "threads": threads,
                      "training": settings, "architecture": architecture,
                      "parameter_count": reference_parameter_count,
                      "stored_parameter_count": sum(p.numel() for p in model.parameters()),
                      "packed_model": model.statistics(), "inputs": inputs,
                      "scope": {"smoke_rows_per_partition": smoke_rows,
                                "max_epochs_override": max_epochs},
                      "versions": {"python": sys.version.split()[0], "torch": torch.__version__,
                                   "numpy": np.__version__, "networkx": nx.__version__, "scipy": scipy.__version__},
                      "numerics": {"dtype": "float32", "tf32": False, "gene_layer_forward": forward_mode}}
        atomic_json(output / "run_config.json", run_config)
        result = fit_model(model, train, validation,
                   lambda: read_pairs(splits["test"], cells, drugs, smoke_rows),
                   cell_features, drug_features, settings, output, torch, progress)
        result.update({"status": "smoke_complete" if smoke_rows is not None or max_epochs is not None else "complete",
                       "fold": fold, "model_seed": seed, "architecture": architecture,
                       "parameter_count": run_config["parameter_count"],
                       "stored_parameter_count": run_config["stored_parameter_count"],
                       "packed_model": model.statistics(),
                       "elapsed_seconds": time.monotonic() - started, "inputs": inputs,
                       "scope": run_config["scope"]})
        atomic_json(output / "metrics.json", result)
        progress(result["status"], selected_epoch=result["selected_epoch"], test=result["test"])
        return result
    except BaseException as error:
        progress("failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/drugcell_comparison.json")
    parser.add_argument("--fold", type=int, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--max-epochs", type=int, help="Explicit reduced-epoch smoke check")
    parser.add_argument("--smoke-rows", type=int, help="Explicit per-partition smoke subset")
    args = parser.parse_args()
    if args.threads < 1 or (args.max_epochs is not None and args.max_epochs < 1) or (args.smoke_rows is not None and args.smoke_rows < 2):
        parser.error("Threads/epochs must be positive; smoke subsets require at least two rows")
    result = run(args.config, args.fold, args.ontology, args.output, args.device, args.threads, args.max_epochs, args.smoke_rows)
    print(json.dumps({key: result[key] for key in ("status", "fold", "selected_epoch", "test", "elapsed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
