"""Prepare the official Norman dataset on CPU, leaving GPU work untouched."""

from pathlib import Path
import json
import os
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("OMP_NUM_THREADS", "8")
os.environ.setdefault("MKL_NUM_THREADS", "8")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "8")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "outputs/gears/.matplotlib"))
sys.path.insert(0, str(ROOT / "third_party/GEARS"))

if __name__ == "__main__":
    import numpy as np
    import torch
    from gears import PertData
    from gears.utils import get_coexpression_network_from_train, make_GO

    config = json.loads((ROOT / "configs/gears_norman_baseline.json").read_text())
    random.seed(config["model_seed"])
    np.random.seed(config["model_seed"])
    torch.manual_seed(config["model_seed"])
    torch.set_num_threads(config["torch_threads"])
    data = PertData(str(ROOT / config["data_path"]), default_pert_graph=config["default_pert_graph"])
    data.load(data_name=config["dataset"])
    data.prepare_split(split=config["split"], seed=config["split_seed"],
                       train_gene_set_size=config["train_gene_set_size"],
                       combo_seen2_train_frac=config["combo_seen2_train_frac"])
    out = ROOT / config["output_path"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(exist_ok=True)
    os.chdir(out)
    print("Preparing original coexpression and GO graphs on CPU...", flush=True)
    coexpression = get_coexpression_network_from_train(
        data.adata, config["model"]["coexpress_threshold"],
        config["model"]["num_similar_genes_co_express_graph"], str(ROOT / config["data_path"]),
        config["dataset"], config["split"], config["split_seed"],
        config["train_gene_set_size"], data.set2conditions,
    )
    go = make_GO(str(ROOT / config["data_path"]), data.pert_names, config["dataset"])
    summary = {"stage": "cpu_preparation_complete", "cells": data.adata.n_obs,
               "readout_genes": data.adata.n_vars, "perturbation_graph_genes": len(data.pert_names),
               "conditions": int(data.adata.obs.condition.nunique()),
               "split_conditions": {key: len(value) for key, value in data.set2conditions.items()},
               "coexpression_edges": len(coexpression), "go_candidate_edges": len(go),
               "graphs_prepared": True}
    (out / "preparation.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
