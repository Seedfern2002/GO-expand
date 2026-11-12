"""Exercise complete-GO retention, post-augmentation pruning and gene projection."""

import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import drugcell_ontology as ontology
from prepare_full_go_base import prepare
from export_drugcell_module_graph import export
from drugcell_input_projection import prepare_projection,project_inputs
import prune_drugcell_ontology as pruning
from run_drugcell_optimized import verify_ontology_origin


class FullGOTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.genes=self.root/"gene2ind.txt";self.genes.write_text("0\tA\n1\tB\n2\tC\n")
        self.obo=self.root/"go.obo"
        self.obo.write_text('format-version: 1.2\n\n[Term]\nid: GO:0008150\nname: biological_process\nnamespace: biological_process\n\n[Term]\nid: GO:0000001\nname: process A\nnamespace: biological_process\nis_a: GO:0008150\n\n[Term]\nid: GO:0000002\nname: process C\nnamespace: biological_process\nis_a: GO:0008150\n\n[Term]\nid: GO:0003674\nname: molecular_function\nnamespace: molecular_function\n')
        self.hgnc=self.root/"hgnc.tsv"
        self.hgnc.write_text("hgnc_id\tsymbol\tstatus\tuniprot_ids\nHGNC:1\tA\tApproved\tP1\nHGNC:2\tB\tApproved\tP2\nHGNC:3\tC\tApproved\tP3\n")
        self.mapping=self.root/"mapping.jsonl"
        ontology.write_rows(self.mapping,[{"gene":g,"hgnc":"HGNC:"+str(i)} for i,g in enumerate(["A","B","C"],1)])
        self.gaf=self.root/"human.gaf.gz"
        def row(protein,gene,qualifier,term):
            return "\t".join(["UniProtKB",protein,gene,qualifier,term,"PMID:1","IDA","","P","name","","protein","taxon:9606","20260101","Source","",""])+"\n"
        with gzip.open(self.gaf,"wt") as f:
            f.write("!gaf-version: 2.2\n"+row("P1","A","involved_in","GO:0000001")+row("P3","C","NOT|involved_in","GO:0000002"))
        self.base=self.root/"base"
        self.manifest=prepare(self.obo,self.gaf,self.hgnc,self.mapping,self.genes,self.base)

    def frozen_graph(self,graph):
        workspace=self.root/"workspace";product=workspace/"knowledge_graph";product.mkdir(parents=True)
        ontology.write_json(workspace/"task.json",{"task_id":"fixture"})
        ontology.write_json(product/"graph.json",graph)
        ontology.write_json(product/"validation.json",{"passed":True})
        ontology.write_json(product/"freeze_manifest.json",{"files":[{"path":p.name,"sha256":ontology.sha256(p)} for p in product.iterdir()],
            "inputs":{"files":[],"task_sha256":ontology.sha256(workspace/"task.json")},"batch_receipts":[]})
        return product

    def test_complete_graph_retains_an_empty_process_until_database_augmentation(self):
        graph=json.loads((self.base/"baseline_graph.json").read_text())
        self.assertEqual(set(graph["nodes"]),{"GO:0008150","GO:0000001","GO:0000002"})
        self.assertEqual(graph["nodes"]["GO:0000002"]["direct_genes"],[])
        self.assertEqual(self.manifest["graph"]["annotated_genes"],1)
        graph["nodes"]["GO:0000002"]["direct_genes"]=["C"]
        product=self.frozen_graph(graph)
        report=export(product,self.base/"full_go_ont.txt",self.genes,self.root/"export")
        self.assertTrue(report["baseline_bytes_preserved"])
        control=pruning.prune(self.base/"full_go_ont.txt",self.genes,self.root/"control",1,0,5)
        augmented=pruning.prune(self.root/"export/drugcell_ont.txt",self.genes,self.root/"augmented",1,0,5)
        self.assertEqual(control["statistics"]["annotated_genes"],1)
        self.assertEqual(augmented["statistics"]["annotated_genes"],2)
        self.assertIn("GO:0000002",ontology.read_ontology(self.root/"augmented/drugcell_ont.txt",["A","B","C"])["terms"])

    def test_each_arm_projects_gene_identifiers_to_noncontiguous_measured_columns(self):
        import numpy as np
        control=self.root/"control.txt";control.write_text("GO:0008150\tGO:0000001\tdefault\nGO:0000001\tA\tgene\n")
        augmented=self.root/"augmented.txt";augmented.write_text(control.read_text()+"GO:0000001\tC\tgene\n")
        a=prepare_projection(self.genes,control,self.root/"projection/control")
        b=prepare_projection(self.genes,augmented,self.root/"projection/augmented")
        self.assertEqual((a["model_genes"],b["model_genes"]),(1,2))
        config={"knowledge":{"baseline_ontology":str(control),"augmented_ontology":str(augmented),
                             "input_projections":{"baseline":a,"augmented":b}}}
        genes,features=project_inputs(config,augmented,{"A":0,"B":1,"C":2},np.array([[1,2,3],[4,5,6]]),self.root)
        self.assertEqual(genes,{"A":0,"C":1})
        np.testing.assert_array_equal(features,[[1,3],[4,6]])
        Path(b["projection"]).write_text('{}')
        with self.assertRaisesRegex(ValueError,"checksum"):
            project_inputs(config,augmented,{"A":0,"B":1,"C":2},np.array([[1,2,3]]),self.root)

    def test_full_GO_control_pruning_is_a_verified_origin_for_a_new_baseline(self):
        control=self.root/"control"
        pruning.prune(self.base/"full_go_ont.txt",self.genes,control,1,0,5)
        path=control/"drugcell_ont.txt"
        config={"knowledge":{"full_go_source":{"ontology":str(self.base/"full_go_ont.txt"),"sha256":ontology.sha256(self.base/"full_go_ont.txt")},
            "baseline_derivation":{"manifest":str(control/"pruning_manifest.json"),"manifest_sha256":ontology.sha256(control/"pruning_manifest.json")}}}
        def record(name,path,expected):
            if ontology.sha256(path)!=expected:raise ValueError("checksum mismatch")
            return Path(path)
        verify_ontology_origin(path,path,config,self.root,record)
        (self.base/"full_go_ont.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError,"checksum"):
            verify_ontology_origin(path,path,config,self.root,record)

    def test_augmented_pruned_origin_preserves_full_GO_instead_of_control_byte_layout(self):
        graph=json.loads((self.base/"baseline_graph.json").read_text())
        graph["nodes"]["GO:0000002"]["direct_genes"]=["C"]
        product=self.frozen_graph(graph)
        export(product,self.base/"full_go_ont.txt",self.genes,self.root/"export")
        pruning.prune(self.base/"full_go_ont.txt",self.genes,self.root/"control",1,0,5)
        pruning.prune(self.root/"export/drugcell_ont.txt",self.genes,self.root/"augmented",1,0,5)
        full=self.base/"full_go_ont.txt";control=self.root/"control/drugcell_ont.txt"
        augmented=self.root/"augmented/drugcell_ont.txt";parent=self.root/"export/drugcell_ont.txt"
        self.assertFalse(augmented.read_bytes().startswith(control.read_bytes()))
        config={"knowledge":{"full_go_source":{"ontology":str(full),"sha256":ontology.sha256(full)},
            "baseline_derivation":{"manifest":str(self.root/"control/pruning_manifest.json"),"manifest_sha256":ontology.sha256(self.root/"control/pruning_manifest.json")},
            "ontology_derivation":{"operation":"drugcell_prune","manifest":str(self.root/"augmented/pruning_manifest.json"),
                "manifest_sha256":ontology.sha256(self.root/"augmented/pruning_manifest.json"),
                "parent_ontology":str(parent),"parent_ontology_sha256":ontology.sha256(parent)}}}
        def record(name,path,expected):
            if ontology.sha256(path)!=expected:raise ValueError("checksum mismatch")
            return Path(path)
        verify_ontology_origin(augmented,control,config,self.root,record)


if __name__=="__main__":unittest.main()
