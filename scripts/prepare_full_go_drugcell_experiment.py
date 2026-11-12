"""Prepare paired full-GO control and database-augmented DrugCell evaluations."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess

import drugcell_ontology as ontology
from drugcell_input_projection import prepare_projection
from export_drugcell_module_graph import export, verify_product
import prune_drugcell_ontology as pruning
import run_drugcell_comparison_optimized as comparison


def _verify_product(directory, manifest_name):
    manifest=comparison.read_json(directory/manifest_name)
    for name,digest in manifest["artifacts"].items():
        if ontology.sha256(directory/name)!=digest:raise ValueError("Prepared ontology artifact changed: "+name)
    return manifest


def prepare(plan, code_source):
    workspace=Path(plan["knowledge_workspace"]).resolve()
    graph_product=Path(plan["module_graph_product"]).resolve()
    graph=verify_product(graph_product)
    comparison.verify_frozen_product(workspace)
    full=Path(plan["full_go_source"]["ontology"]).resolve()
    if ontology.sha256(full)!=plan["full_go_source"]["sha256"]:
        raise ValueError("The declared complete GO ontology changed")
    gene_map=Path(plan["feature_gene_map"])
    if graph["genes"]!=ontology.read_gene_map(gene_map):raise ValueError("Shared graph uses different measured gene identifiers")
    cache=Path(code_source).parent/"preparation";cache.mkdir(exist_ok=True)
    control=cache/"control_pruned"
    if not control.exists():pruning.prune(full,gene_map,control)
    control_report=_verify_product(control,"pruning_manifest.json")
    if control_report["sources"]["ontology"]["sha256"]!=ontology.sha256(full):raise ValueError("Control uses a different complete GO source")
    exported=cache/"augmented_full"
    if not exported.exists():export(graph_product,full,gene_map,exported)
    export_report=_verify_product(exported,"projection_manifest.json")
    if export_report["sources"]["graph_freeze"]["sha256"]!=ontology.sha256(graph_product/"freeze_manifest.json"):
        raise ValueError("Augmented export uses a different graph freeze")
    augmented=cache/"augmented_pruned"
    if not augmented.exists():pruning.prune(exported/"drugcell_ont.txt",gene_map,augmented)
    augmented_report=_verify_product(augmented,"pruning_manifest.json")
    output=Path(plan["experiment_output"]).resolve()
    config=deepcopy(comparison.read_json(Path(plan["baseline_experiment"])/"config.json"))
    config.pop("completed_run_references",None)
    config.update(experiment_id="drugcell_full_GO_database_augmentation_then_pruning",
        comparison_description="The same complete GO-BP and original human annotations, with or without reviewed database module augmentation, followed by the same DrugCell pruning and five-fold training protocol.")
    config["runtime"].update(code_source_directory=str(Path(code_source).resolve()))
    config["data"]["folds"]=plan["folds"]
    config["model_seed"]=plan["model_seed"]
    config["released_training_settings"]=plan["training"]
    config["knowledge"].update(augmentation_workspace=str(workspace),
        baseline_ontology=str(control/"drugcell_ont.txt"),baseline_ontology_sha256=ontology.sha256(control/"drugcell_ont.txt"),
        module_graph_product=str(graph_product),module_graph_freeze_sha256=ontology.sha256(graph_product/"freeze_manifest.json"),
        full_go_source={"ontology":str(full),"sha256":ontology.sha256(full)},
        baseline_derivation={"manifest":str(output/"control_pruning/pruning_manifest.json"),
                             "manifest_sha256":ontology.sha256(control/"pruning_manifest.json")},
        comparison=config["comparison_description"],gene_universe="Fixed measured task universe; each model projects onto its annotated genes after pruning")
    config["evaluation"]["matched_inputs"]=["measured_feature_source","cell_features_by_gene_identifier","compound_fingerprints",
        "response_records","split_assignments","training_settings","random_seeds"]
    config_path=cache/"experiment_config.json";comparison.write_json(config_path,config)
    config=comparison.initialize(config_path,output,workspace)
    shutil.copytree(control,output/"control_pruning")
    shutil.copytree(exported,output/"source_augmentation")
    shutil.copytree(augmented,output/"augmentation")
    comparison.snapshot_knowledge(workspace,output/"knowledge_snapshot")
    ontology.write_json(output/"gene_alignment.json",{"available_measured_genes":len(graph["genes"]),"arms":{}})
    projections={arm:prepare_projection(gene_map,output/relative,output/"input_projections"/arm)
                 for arm,relative in [("baseline","baseline/drugcell_ont.txt"),("augmented","augmentation/drugcell_ont.txt")]}
    ontology.write_json(output/"gene_alignment.json",{"available_measured_genes":len(graph["genes"]),
        "arms":projections,"source_gene_map_sha256":ontology.sha256(gene_map),
        "input_policy":"Identifier-bound projection of measured mutation columns after augmentation and pruning"})
    config["knowledge"].update(input_projections=projections,
        ontology_derivation={"operation":"drugcell_prune","manifest":str(output/"augmentation/pruning_manifest.json"),
            "manifest_sha256":ontology.sha256(output/"augmentation/pruning_manifest.json"),
            "parent_ontology":str(output/"source_augmentation/drugcell_ont.txt"),
            "parent_ontology_sha256":ontology.sha256(output/"source_augmentation/drugcell_ont.txt")})
    config["runtime"]["preflight_bundle"]=str(output/"preflight_bundle")
    config["execution_projection_policy"]={"shared_task_genes":len(graph["genes"]),"model_genes":{arm:p["model_genes"] for arm,p in projections.items()},
        "graph_basis":"Complete active GO-BP hierarchy before augmentation and pruning","pruning":augmented_report["policy"]}
    comparison.write_json(output/"config.json",config)
    interpreter=Path(config["runtime"]["python"])
    if not interpreter.is_absolute():interpreter=Path(config["project_root"])/interpreter
    with (output/"prepare_bundle.log").open("w") as log:
        subprocess.run([str(interpreter),str(Path(code_source)/"benchmark_drugcell_optimized.py"),"--prepare-config",str(output/"config.json"),
            "--bundle",str(output/"preflight_bundle")],env=dict(os.environ,CUDA_VISIBLE_DEVICES="",PYTHONDONTWRITEBYTECODE="1"),
            stdout=log,stderr=subprocess.STDOUT,check=True)
    config["runtime"]["preflight_bundle_manifest_sha256"]=ontology.sha256(output/"preflight_bundle/manifest.json")
    comparison.write_json(output/"config.json",config)
    comparison.write_json(output/"pruning_summary.json",{"source_knowledge_freeze_sha256":ontology.sha256(workspace/"knowledge/freeze_manifest.json"),
        "complete_GO":ontology.read_ontology(full,graph["genes"],allow_empty_terms=True)["stats"],
        "control":control_report["statistics"],"augmented":augmented_report["statistics"],
        "model_gene_counts":{arm:p["model_genes"] for arm,p in projections.items()}})
    comparison.write_json(output/"augmentation_status.json",{"stage":"ontology_frozen","updated_at_utc":comparison.now(),
        "ontology_sha256":ontology.sha256(output/"augmentation/drugcell_ont.txt"),"projection_counts":augmented_report["statistics"]})
    manifest=comparison.read_json(output/"experiment_manifest.json")
    paths={r["path"] for r in manifest["files"]}
    for directory in ["augmentation","control_pruning","source_augmentation","input_projections","preflight_bundle","knowledge_snapshot"]:
        paths.update(str(p.relative_to(output)) for p in (output/directory).rglob("*") if p.is_file())
    paths.update(["config.json","gene_alignment.json","pruning_summary.json"])
    manifest["comparison"]=config["comparison_description"]
    manifest["files"]=[{"path":p,"sha256":ontology.sha256(output/p)} for p in sorted(paths)]
    comparison.write_json(output/"experiment_manifest.json",manifest)
    comparison.verify_experiment(output)
    return {"output":str(output),"control":control_report["statistics"],"augmented":augmented_report["statistics"],
            "model_gene_counts":{arm:p["model_genes"] for arm,p in projections.items()}}
