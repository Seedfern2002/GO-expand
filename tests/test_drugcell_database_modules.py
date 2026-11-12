"""Check database-only source binding and complete module partitions."""

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import drugcell_ontology as ontology
from prepare_database_module_graph import rebuild
from prepare_module_graph_inputs import partition_catalog
from prepare_drugcell_pruned_experiment import check_gene_alignment


class DatabaseModulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.source = self.root / "source"
        raw = self.source / "acquisition/sources";raw.mkdir(parents=True)
        (self.source / "inputs").mkdir()
        (self.source / "inputs/go.obo").write_text('format-version: 1.2\n\n[Term]\nid: GO:0008150\nname: biological_process\nnamespace: biological_process\n\n[Term]\nid: GO:0000001\nname: repair\nnamespace: biological_process\nis_a: GO:0008150\n')
        self.genes = self.root / "gene2ind.txt";self.genes.write_text("0\tA\n1\tB\n")
        self.baseline = self.root / "baseline.txt";self.baseline.write_text("GO:0008150\tGO:0000001\tdefault\nGO:0000001\tA\tgene\nGO:0000001\tB\tgene\n")
        self.task = self.root / "task.json";self.task.write_text('{"task_id":"database_task"}')
        (raw / "hgnc.tsv").write_text("hgnc_id\tsymbol\tstatus\talias_symbol\tprev_symbol\tuniprot_ids\nHGNC:1\tA\tApproved\t\t\tP1\nHGNC:2\tB\tApproved\t\t\tP2\n")
        mapping = [{"gene": g, "hgnc": "HGNC:"+str(i), "canonical_symbol":g, "entrez":str(i),
                    "hgnc_sha256":ontology.sha256(raw / "hgnc.tsv")} for i,g in enumerate(["A","B"],1)]
        ontology.write_rows(self.source / "acquisition/identifier_mapping.jsonl", mapping)
        (raw / "NCBI2Reactome_All_Levels.txt").write_text("1\tR-HSA-1\turi\tRepair\tTAS\tHomo sapiens\n2\tR-HSA-2\turi\tRepair branch\tTAS\tHomo sapiens\n")
        (raw / "reactome_hierarchy.tsv").write_text("R-HSA-1\tR-HSA-2\n")
        (raw / "reactome2go.txt").write_text("Reactome:R-HSA-1 > GO:repair ; GO:0000001\n")
        with (raw / "complexportal.tsv").open("w") as stream:
            writer=csv.writer(stream,delimiter="\t")
            writer.writerow(["id","name","aliases","taxon","members","evidence","expanded"])
            writer.writerow(["CPX-1","Repair complex","","9606","P2(1)","ECO:0000353","P2(1)"])
        def row(database,gene,num,obj,label,snapshot,locator,**extra):
            return {"subject_label":gene,"subject_id":"HGNC:"+str(num),"object_id":obj,"object_label":label,
                "evidence_class":"database_derived","polarity":"positive","projection_eligible":True,
                "relation":"member_of_pathway" if database=="Reactome" else "member_of_complex",
                "evidence":[{"source_name":database,"snapshot_path":"acquisition/sources/"+snapshot,
                    "snapshot_sha256":ontology.sha256(raw/snapshot),"locator":"line:"+str(locator),**extra}]}
        self.records=[row("Reactome","A",1,"R-HSA-1","Repair","NCBI2Reactome_All_Levels.txt",1),
                      row("Reactome","B",2,"R-HSA-2","Repair branch","NCBI2Reactome_All_Levels.txt",2)]
        ontology.write_rows(self.source/"acquisition/reactome_raw.jsonl",self.records)
        ontology.write_rows(self.source/"acquisition/complexportal_mapping_refined.jsonl",[
            row("ComplexPortal","B",2,"ComplexPortal:CPX-1","Repair complex","complexportal.tsv",2,source_protein_id="P2")])

    def test_all_database_records_rebuild_without_literature_or_temporary_source_paths(self):
        output=self.root/"output"
        result=rebuild(self.source,self.baseline,self.genes,self.task,output,2)
        self.assertEqual(result["catalog_modules"],3)
        self.assertEqual(result["processing_modules"],3)
        self.assertEqual(result["literature_records"],0)
        self.assertEqual(result["database_records"],{"Reactome":2,"ComplexPortal":1})
        batches=json.loads((output/"module_batches.json").read_text())
        order=[m for b in batches for m in b["modules"]]
        self.assertEqual(order[:2],["EXTERNAL:R-HSA-1","EXTERNAL:R-HSA-2"])
        self.assertTrue(all(Path(p).exists() for p in json.loads((output/"sources.json").read_text()).values()))

    def test_literature_contamination_and_changed_source_membership_are_rejected(self):
        self.records[0]["evidence_class"]="literature_extracted"
        ontology.write_rows(self.source/"acquisition/reactome_raw.jsonl",self.records)
        with self.assertRaisesRegex(ValueError,"database-derived"):
            rebuild(self.source,self.baseline,self.genes,self.task,self.root/"bad",2)
        self.records[0]["evidence_class"]="database_derived";self.records[0]["object_id"]="R-HSA-999"
        ontology.write_rows(self.source/"acquisition/reactome_raw.jsonl",self.records)
        with self.assertRaisesRegex(ValueError,"source row"):
            rebuild(self.source,self.baseline,self.genes,self.task,self.root/"bad2",2)

    def test_source_cycle_is_rejected_and_every_module_is_partitioned_once(self):
        modules={m:{"source":"Reactome"} for m in ["P","C","X"]}
        facts={"1":{"relation":"source_pathway_parent","parent":"P","child":"C"}}
        batches=partition_catalog(modules,facts,2)
        order=[m for b in batches for m in b["modules"]]
        self.assertEqual(set(order),set(modules));self.assertEqual(len(order),3)
        self.assertLess(order.index("P"),order.index("C"))
        facts["2"]={"relation":"source_pathway_parent","parent":"C","child":"P"}
        with self.assertRaisesRegex(ValueError,"cycle"):
            partition_catalog(modules,facts,2)

    def test_gene_alignment_uses_identifiers_and_detects_width_or_unmeasured_genes(self):
        data=self.root/"data";data.mkdir()
        (data/"gene2ind.txt").write_bytes(self.genes.read_bytes())
        (data/"cell2ind.txt").write_text("0\tCELL1\n1\tCELL2\n")
        (data/"cell2mutation.txt").write_text("0,1\n1,0\n")
        result=check_gene_alignment(data,["A","B"],self.baseline,self.root/"alignment.json")
        self.assertEqual(result["task_input_genes"],2)
        with self.assertRaisesRegex(ValueError,"measured mutation features"):
            check_gene_alignment(data,["A","MISSING"],self.baseline,self.root/"alignment2.json")
        (data/"cell2mutation.txt").write_text("0,1,0\n1,0,0\n")
        with self.assertRaisesRegex(ValueError,"feature width"):
            check_gene_alignment(data,["A","B"],self.baseline,self.root/"alignment3.json")


if __name__=="__main__":
    unittest.main()
