import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launch import sandbox_command
from launch_modules import prepare_modules
from place_modules import assert_external_boundary


class ModuleBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        task = {"task_id": "example", "task_description": "Human functional knowledge for drug response",
                "organism": {"taxon_id": "NCBITaxon:9606"}, "biological_context": {"cell_type": "human cancer cells"},
                "candidate_categories": ["pathway"], "knowledge_requirements": ["Evidence-backed pathways"],
                "retrieval_budget": {"max_papers": 1}, "projection_policy": {"membership_relations": ["member_of_pathway"]}}
        self.module = {"EXTERNAL:R-HSA-1": {"id": "EXTERNAL:R-HSA-1", "label": "Repair process", "definition": "A source-defined process",
             "kind": "pathway", "source": "Reactome", "genes": ["A"], "go_annotations": ["GO:0000001"],
             "evidence_ids": ["E1"], "source_relatives": []}}
        graph = {"genes": ["A"], "root": "GO:0008150", "revision": 0, "aliases": {}, "applied_batches": [],
                 "nodes": {key: {"id": key, "label": key, "definition": "Original process", "kind": "biological_process",
                                 "origin": "baseline", "direct_genes": members}
                           for key, members in [("GO:0008150", []), ("GO:0000001", ["A"])]},
                 "edges": [{"parent": "GO:0008150", "child": "GO:0000001", "relation": "released_hierarchy", "model_edge": True}]}
        self.facts = {"E1": {"id": "E1", "type": "source_go_annotation", "module": "EXTERNAL:R-HSA-1", "go_id": "GO:0000001",
                             "path": "inputs/sources/biological_source.tsv", "locator": "line:1"}}
        source = self.root / "source.tsv";source.write_text("R-HSA-1 Repair process > GO:0000001\n")
        data = {"task": task, "genes": {"genes": ["A"]}, "annotations": {"A": ["GO:0008150", "GO:0000001"]},
                "graph": graph, "modules": self.module, "evidence": self.facts,
                "batches": [{"id": "b1", "modules": ["EXTERNAL:R-HSA-1"]}], "sources": {"biological_source.tsv": str(source)}}
        for key, value in data.items():
            (self.root / (key + ".json")).write_text(json.dumps(value))

    def prepare(self, workflow="module_placement"):
        return prepare_modules(*(self.root / (key + ".json") for key in ["task", "genes", "annotations"]),
                               None, *(self.root / (key + ".json") for key in ["graph", "modules", "evidence", "batches", "sources"]),
                               self.root / "run", "test-model", workflow=workflow)

    def test_recipe_workflow_is_explicit_and_scientific_inputs_stay_identical(self):
        root = self.prepare("module_recipes")
        self.assertEqual(json.loads((root / "runtime.json").read_text())["workflow"], "module_recipes")
        self.assertEqual(json.loads((root / "inputs/modules.json").read_text()), self.module)
        self.assertTrue((root / "pipeline/prompts/modules/recipe_editor.md").is_file())
        receipt = json.loads((root.parent / "receipt.json").read_text())
        self.assertEqual([x["skill"] for x in receipt["module_instructions"]],
                         ["place-functional-modules", "review-functional-modules"])
        for instruction in receipt["module_instructions"]:
            self.assertTrue(all((root / resource["path"]).is_file() for resource in instruction["resources"]))

    def test_source_rows_are_bound_and_host_paths_stay_outside_agent_inputs(self):
        root = self.prepare()
        sources = json.loads((root / "inputs/manifest.json").read_text())
        self.assertNotIn(str(self.root), json.dumps(sources))
        self.assertTrue((root / "inputs/sources/biological_source.tsv").is_file())
        command = sandbox_command(self.root / "run", "/usr/bin/python3", self.root / "auth", "place_modules.py")
        self.assertIn("/workspace/inputs", command)
        self.assertIn("/workspace/pipeline", command)
        self.assertIn("/opt/python", command)
        self.assertIn("/opt:/usr/local/bin:/usr/bin:/bin", command)
        self.assertEqual(command[-3], "/workspace/pipeline/place_modules.py")

    def test_extra_experiment_metadata_is_rejected(self):
        self.module["EXTERNAL:R-HSA-1"]["old_test_score"] = .999
        (self.root / "modules.json").write_text(json.dumps(self.module))
        with self.assertRaisesRegex(ValueError, "scientific input contract"):
            self.prepare()

    def test_source_GO_mismatch_is_rejected(self):
        self.facts["E1"]["go_id"] = "GO:9999999"
        (self.root / "evidence.json").write_text(json.dumps(self.facts))
        with self.assertRaisesRegex(ValueError, "source row"):
            self.prepare()

    def test_full_access_backend_refuses_execution_outside_outer_sandbox(self):
        with self.assertRaisesRegex(RuntimeError, "task-only launcher"):
            assert_external_boundary(self.root)


if __name__ == "__main__":
    unittest.main()
