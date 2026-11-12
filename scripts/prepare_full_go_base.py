"""Build the complete active GO-BP graph with source-bound human annotations."""

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path
import sys

import drugcell_ontology as ontology

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "standalone/task_go"))
from engine.ontology import Ontology
from engine.module_graph import summary, validate_graph


def prepare(obo_path, gaf_path, hgnc_path, mapping_path, gene_map, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    genes = ontology.read_gene_map(gene_map); universe = set(genes)
    obo = Ontology.read(obo_path)
    active = {t.id:t for t in obo.terms.values() if not t.obsolete and t.namespace == "biological_process"}
    lookup = {identifier:t for t in obo.terms.values() for identifier in [t.id,*t.alt_ids]}
    with Path(hgnc_path).open() as stream:
        hgnc = {r["hgnc_id"]:r for r in csv.DictReader(stream, delimiter="\t") if r["status"] == "Approved"}
    proteins, symbols = defaultdict(set), {}
    for ident,row in hgnc.items():
        symbols[row["symbol"]] = ident
        for protein in row["uniprot_ids"].split("|"):
            if protein: proteins[protein].add(ident)
    fixed = defaultdict(list)
    for row in map(json.loads, Path(mapping_path).read_text().splitlines()):
        if row["gene"] in universe:
            fixed[row["hgnc"]].append(row["gene"])
    direct = defaultdict(set); counts = Counter(); codes = Counter()
    with gzip.open(gaf_path,"rt") as stream, (output/"annotation_evidence.tsv").open("w") as evidence:
        writer=csv.writer(evidence,delimiter="\t")
        writer.writerow(["gene","canonical_GO","source_GO","source_line","protein","source_symbol","qualifier","evidence_code","reference","with_from","annotation_extension","gene_product_form"])
        for number,line in enumerate(stream,1):
            if line.startswith("!"):continue
            counts["source_annotations"] += 1
            fields=line.rstrip("\n").split("\t")
            if len(fields)<17:counts["excluded_malformed"]+=1;continue
            if fields[12].split("|")[0]!="taxon:9606" or fields[8]!="P":
                counts["excluded_taxon_or_other_aspect"]+=1;continue
            qualifiers=set(fields[3].split("|"))
            if "NOT" in qualifiers or qualifiers!={"involved_in"} or fields[6]=="ND":
                counts["excluded_polarity_relation_or_no_data"]+=1;continue
            candidates=proteins[fields[1].split("-")[0]]
            ident=symbols.get(fields[2])
            if ident not in candidates:
                ident=next(iter(candidates)) if len(candidates)==1 else None
            selected=fixed.get(ident,[])
            if len(selected)!=1:
                counts["excluded_unmeasured_or_ambiguous_gene"]+=1;continue
            term=lookup.get(fields[4]); seen=set()
            while term and term.obsolete and len(term.replaced_by)==1 and term.id not in seen:
                seen.add(term.id);term=lookup.get(term.replaced_by[0])
            if term is None or term.id not in active:
                counts["excluded_unresolved_GO"]+=1;continue
            gene=selected[0];direct[term.id].add(gene)
            counts["retained_source_annotations"]+=1;codes[fields[6]]+=1
            writer.writerow([gene,term.id,fields[4],number,fields[1],fields[2],fields[3],fields[6],fields[5],fields[7],fields[15],fields[16]])
    nodes={key:{"id":key,"label":t.name,"definition":t.definition,"kind":"biological_process",
                "origin":"baseline","direct_genes":sorted(direct[key])} for key,t in sorted(active.items())}
    edges=[]
    for child,t in sorted(active.items()):
        for relation,parent in t.edges:
            if parent in active:
                edges.append({"parent":parent,"child":child,"relation":relation,
                    "model_edge":relation in {"is_a","part_of"},"evidence_ids":[],
                    "rationale":"Original relationship in the pinned complete GO-BP ontology"})
    graph={"revision":0,"root":"GO:0008150","genes":genes,"nodes":nodes,"edges":edges,
           "aliases":{},"applied_batches":[],"gene_coverage_policy":"allow_unannotated"}
    validate_graph(graph)
    model_edges={(e["parent"],e["child"]) for e in edges if e["model_edge"]}
    memberships={(term,gene) for term,values in direct.items() for gene in values}
    analysis=ontology.analyze(model_edges,memberships,genes,allow_empty_terms=True)
    with (output/"full_go_ont.txt").open("w") as stream:
        for a,b in sorted(model_edges):stream.write(f"{a}\t{b}\tdefault\n")
        for term,gene in sorted(memberships):stream.write(f"{term}\t{gene}\tgene\n")
    ontology.write_json(output/"baseline_graph.json",graph)
    ontology.write_json(output/"genes.json",{"genes":genes})
    ontology.write_json(output/"annotations.json",analysis["propagated_annotations"])
    covered={g for _,g in memberships}
    ontology.write_json(output/"unannotated_genes.json",sorted(universe-covered))
    result={"basis":"complete_active_GO_BP_before_any_DrugCell_pruning", "graph":summary(graph),
        "GO_release":obo.metadata.get("data-version"),"GO_aspect":"biological_process",
        "all_active_BP_terms_retained":len(nodes)==len(active),"terms_without_task_gene_coverage":sum(not g for g in analysis["propagated"].values()),
        "annotation_counts":dict(counts),"annotation_evidence_codes":dict(codes),"unannotated_task_genes":len(universe-covered),
        "sources":ontology.sources(obo=obo_path,gaf=gaf_path,hgnc=hgnc_path,identifier_mapping=mapping_path,gene_map=gene_map),
        "artifacts":{p.name:ontology.sha256(p) for p in output.iterdir() if p.is_file()}}
    ontology.write_json(output/"full_go_manifest.json",result)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("obo","gaf","hgnc","mapping","gene-map","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    a=parser.parse_args()
    print(json.dumps(prepare(a.obo,a.gaf,a.hgnc,a.mapping,a.gene_map,a.output),indent=2))
