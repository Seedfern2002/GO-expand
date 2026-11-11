"""Check the released DrugCell model with one CPU optimization step.

This uses a few observations from the released sample training file to exercise
the original forward pass, auxiliary losses, masked gradients and Adam update.
The resulting JSON describes runtime compatibility; it is not an evaluation.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DIRECT_SUFFIX = "_direct_gene_layer.weight"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def retain_direct_entries_(tensor, gene_indices, torch):
    """Apply the original one-gene-per-row mask without a dense mask copy."""
    rows = torch.arange(len(gene_indices), device=tensor.device)
    columns = torch.tensor(list(gene_indices), dtype=torch.long, device=tensor.device)
    retained = tensor[rows, columns].clone()
    tensor.zero_()
    tensor[rows, columns] = retained


def check(source, ontology, output, batch_size=4, threads=2, seed=0):
    started = time.monotonic()
    output = Path(output)
    if output.exists():
        raise FileExistsError("Use a fresh output path for each runtime check")
    # Establish CPU execution before importing torch or the upstream module.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[key] = str(threads)
    import networkx as nx
    import numpy as np
    import torch

    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    np.random.seed(seed)
    source = Path(source).resolve()
    ontology = Path(ontology).resolve() if ontology else source / "data/drugcell_ont.txt"
    code = source / "code"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(code))
    util = importlib.import_module("util")
    model_module = importlib.import_module("drugcell_NN")
    if Path(util.__file__).resolve() != code / "util.py":
        raise RuntimeError("DrugCell utility module resolved outside the pinned source")
    if Path(model_module.__file__).resolve() != code / "drugcell_NN.py":
        raise RuntimeError("DrugCell model module resolved outside the pinned source")

    files = {
        "ontology": ontology,
        **{name: source / "data" / name for name in (
            "gene2ind.txt", "cell2ind.txt", "drug2ind.txt", "cell2mutation.txt",
            "drug2fingerprint.txt", "drugcell_train.txt")},
        "upstream_model": code / "drugcell_NN.py",
        "upstream_util": code / "util.py",
        "runtime_check": Path(__file__).resolve(),
    }
    genes = util.load_mapping(files["gene2ind.txt"])
    cells = util.load_mapping(files["cell2ind.txt"])
    drugs = util.load_mapping(files["drug2ind.txt"])
    cell_features = np.loadtxt(files["cell2mutation.txt"], delimiter=",", dtype=np.float32)
    drug_features = np.loadtxt(files["drug2fingerprint.txt"], delimiter=",", dtype=np.float32)
    if cell_features.shape != (len(cells), len(genes)):
        raise ValueError("Mutation dimensions differ from the fixed cell/gene maps")
    if drug_features.shape[0] != len(drugs):
        raise ValueError("Fingerprint dimensions differ from the fixed drug map")

    pairs, labels = [], []
    with files["drugcell_train.txt"].open() as stream:
        for line in stream:
            cell, drug, label = line.rstrip().split("\t")
            pairs.append([cells[cell], drugs[drug]])
            labels.append([float(label)])
            if len(pairs) == batch_size:
                break
    if len(pairs) != batch_size:
        raise ValueError("The sample training file has fewer rows than the smoke batch")
    features = util.build_input_vector(torch.tensor(pairs), cell_features, drug_features)
    target = torch.tensor(labels, dtype=torch.float32)
    upstream_log = io.StringIO()
    with contextlib.redirect_stdout(upstream_log):
        graph, root, sizes, direct = util.load_ontology(str(ontology), genes)
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("The DrugCell hierarchy must be a DAG")
        graph_terms = graph.number_of_nodes()
        graph_edges = graph.number_of_edges()
        model = model_module.drugcell_nn(
            sizes, direct, graph.copy(), len(genes), drug_features.shape[1],
            root, 6, [100, 50, 6], 6,
        )

    with torch.no_grad():
        for name, parameter in model.named_parameters():
            parameter.mul_(0.1)
            if name.endswith(DIRECT_SUFFIX):
                term = name.removesuffix(DIRECT_SUFFIX)
                retain_direct_entries_(parameter, direct[term], torch)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=0.001, betas=(0.9, 0.99), eps=1e-5,
    )
    model.train()
    optimizer.zero_grad()
    auxiliary, _ = model(features)
    final_before = auxiliary["final"].detach().clone()
    loss = sum((1.0 if name == "final" else 0.2)
               * torch.nn.functional.mse_loss(value, target)
               for name, value in auxiliary.items())
    if not torch.isfinite(loss).item():
        raise RuntimeError("The upstream auxiliary loss is nonfinite")
    loss.backward()
    finite_gradients = True
    masked_layers = 0
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if parameter.grad is None:
                continue
            if name.endswith(DIRECT_SUFFIX):
                term = name.removesuffix(DIRECT_SUFFIX)
                retain_direct_entries_(parameter.grad, direct[term], torch)
                masked_layers += 1
            if not torch.isfinite(parameter.grad).all().item():
                finite_gradients = False
    if not finite_gradients:
        raise RuntimeError("The upstream model produced nonfinite gradients")
    optimizer.step()
    # Release optimizer states and training activations before the second pass.
    optimizer.zero_grad(set_to_none=True)
    loss_value = float(loss.detach())
    auxiliary_heads = len(auxiliary)
    del auxiliary, loss, optimizer
    model.eval()
    with torch.no_grad():
        evaluated, _ = model(features)
        final_after = evaluated["final"]
        finite_output = bool(torch.isfinite(final_after).all().item())
        masked_weights = all(
            torch.count_nonzero(parameter).item() <= parameter.shape[0]
            for name, parameter in model.named_parameters()
            if name.endswith(DIRECT_SUFFIX)
        )
    if not finite_output or not masked_weights:
        raise RuntimeError("Evaluation outputs or the direct-gene mask failed the runtime check")
    try:
        import resource
        peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        peak_rss_mib = None

    result = {
        "status": "passed",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "check_scope": "CPU forward, one masked-gradient Adam update, and evaluation forward on a sample training batch",
        "device": "cpu",
        "threads": threads,
        "seed": seed,
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_mib": peak_rss_mib,
        "versions": {"python": sys.version.split()[0], "torch": torch.__version__,
                     "numpy": np.__version__, "networkx": nx.__version__},
        "dimensions": {"genes": len(genes), "cells": len(cells), "drugs": len(drugs),
                       "drug_fingerprint": drug_features.shape[1], "batch": batch_size,
                       "ontology_terms": graph_terms, "ontology_edges": graph_edges,
                       "root": root, "direct_gene_memberships": sum(map(len, direct.values()))},
        "parameters": {"total": sum(p.numel() for p in model.parameters()),
                       "trainable": sum(p.numel() for p in model.parameters() if p.requires_grad),
                       "direct_gene_dense": sum(p.numel() for n, p in model.named_parameters()
                                                if "_direct_gene_layer." in n)},
        "architecture": {"genotype_hiddens": 6, "drug_hiddens": [100, 50, 6], "final_hiddens": 6},
        "optimizer": {"name": "Adam", "learning_rate": 0.001, "betas": [0.9, 0.99], "eps": 1e-5},
        "checks": {"finite_auxiliary_loss": True, "finite_gradients": finite_gradients,
                   "finite_evaluation_output": finite_output, "direct_gene_mask_preserved": masked_weights,
                   "masked_direct_gene_layers": masked_layers,
                   "upstream_graph_preserved": graph.number_of_nodes() == graph_terms},
        "sample_step": {"auxiliary_heads": auxiliary_heads, "total_auxiliary_loss": loss_value,
                        "training_predictions_before_step": final_before.flatten().tolist(),
                        "evaluation_predictions_after_step": final_after.flatten().tolist()},
        "inputs": {name: {"path": str(path), "sha256": sha256(path)} for name, path in files.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "third_party/DrugCell")
    parser.add_argument("--ontology", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/drugcell/initialization/cpu_smoke.json")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if not 2 <= args.batch_size <= 16 or args.threads < 1:
        parser.error("Use a batch size between 2 and 16 and a positive CPU thread count")
    result = check(args.source, args.ontology, args.output, args.batch_size, args.threads, args.seed)
    print(json.dumps({key: result[key] for key in ("status", "device", "elapsed_seconds", "dimensions", "parameters", "checks")}, indent=2))


if __name__ == "__main__":
    main()
