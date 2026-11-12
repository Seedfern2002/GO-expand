"""Bind each pruned ontology to measured mutation columns by gene identifier."""

import json
from pathlib import Path

import drugcell_ontology as ontology


def resolve(root, value):
    path=Path(value)
    return path.resolve() if path.is_absolute() else (Path(root)/path).resolve()


def prepare_projection(source_gene_map, ontology_path, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    source_genes=ontology.read_gene_map(source_gene_map)
    graph=ontology.read_ontology(ontology_path,source_genes)
    used={gene for _,gene in graph["memberships"]}
    genes=[g for g in source_genes if g in used]
    columns=[i for i,g in enumerate(source_genes) if g in used]
    if not genes:raise ValueError("A training ontology requires measured annotated genes")
    with (output/"gene2ind.txt").open("w") as stream:
        for i,gene in enumerate(genes):stream.write(f"{i}\t{gene}\n")
    value={"genes":genes,"source_columns":columns,"source_gene_map_sha256":ontology.sha256(source_gene_map),
           "ontology_sha256":ontology.sha256(ontology_path),"available_feature_genes":len(source_genes),
           "model_genes":len(genes),"policy":"Select measured mutation columns in source order by exact gene identifier"}
    ontology.write_json(output/"projection.json",value)
    return {"gene_map":str((output/"gene2ind.txt").resolve()),"gene_map_sha256":ontology.sha256(output/"gene2ind.txt"),
            "projection":str((output/"projection.json").resolve()),"projection_sha256":ontology.sha256(output/"projection.json"),
            "model_genes":len(genes)}


def project_inputs(config, ontology_path, available_genes, mutation_features, root, records=None):
    definitions=config["knowledge"].get("input_projections")
    if not definitions:return available_genes,mutation_features
    selected=[arm for arm in definitions if resolve(root,config["knowledge"][arm+"_ontology"])==Path(ontology_path).resolve()]
    if len(selected)!=1:raise ValueError("Evaluated ontology has no unique declared gene projection")
    arm=selected[0];definition=definitions[arm]
    paths={name:resolve(root,definition[name]) for name in ("gene_map","projection")}
    for name,path in paths.items():
        if ontology.sha256(path)!=definition[name+"_sha256"]:
            raise ValueError("Gene projection checksum changed: "+name)
        if records is not None:records[f"input_projection/{arm}/{name}"]={"path":str(path),"sha256":definition[name+"_sha256"]}
    value=json.loads(paths["projection"].read_text())
    genes=ontology.read_gene_map(paths["gene_map"]);columns=value["source_columns"]
    source_order=[g for g,_ in sorted(available_genes.items(),key=lambda x:x[1])]
    if (value["ontology_sha256"]!=ontology.sha256(ontology_path) or genes!=value["genes"]
            or len(columns)!=len(genes) or len(set(columns))!=len(columns)
            or any(not isinstance(c,int) or c<0 or c>=len(source_order) for c in columns)
            or [source_order[c] for c in columns]!=genes or mutation_features.shape[1]!=len(source_order)):
        raise ValueError("Gene projection differs from the measured feature identifiers or ontology")
    return {g:i for i,g in enumerate(genes)},mutation_features[:,columns]


def full_go_basis(config, root, baseline, record):
    basis=config["knowledge"].get("full_go_source")
    if not basis:return baseline
    source=record("full_GO_source",resolve(root,basis["ontology"]),basis["sha256"])
    derivation=config["knowledge"]["baseline_derivation"]
    path=record("control_pruning_manifest",resolve(root,derivation["manifest"]),derivation["manifest_sha256"])
    manifest=json.loads(path.read_text())
    if (manifest.get("status")!="pruned" or manifest["artifacts"]["drugcell_ont.txt"]!=ontology.sha256(baseline)
            or manifest["sources"]["ontology"]["sha256"]!=ontology.sha256(source)):
        raise ValueError("Control ontology differs from the declared full-GO pruning product")
    return source
