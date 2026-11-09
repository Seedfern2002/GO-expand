"""Check the scientific input boundary without reading a model response."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from launch import prepare, sandbox_command


class TaskBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = {
            "task_id": "example", "task_description": "Functional knowledge for perturbation prediction",
            "organism": {"name": "human", "taxon_id": "NCBITaxon:9606"},
            "biological_context": {"cell_type": "K562"}, "candidate_categories": ["pathway"],
            "knowledge_requirements": ["Database and literature functional knowledge"],
            "retrieval_budget": {"max_papers": 2, "max_candidate_records": 5, "max_download_bytes": 10000},
            "projection_policy": {"membership_relations": ["annotated_to"], "singleton_policy": "retain", "context_policy": "preserve"},
        }
        self.task_path = self.root / "task.json"
        self.genes_path = self.root / "metadata.json"
        self.annotations_path = self.root / "base.json"
        self.write(self.task_path, self.task)
        self.write(self.genes_path, {"genes": ["A", "B"], "old_run_score": 9999, "test_conditions": ["UNWANTED_CONTEXT"]})
        self.write(self.annotations_path, {"A": ["GO:0000001"], "B": ["GO:0000002"], "OUTSIDE": ["GO:9999999"]})

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def prepare(self):
        return prepare(self.task_path, self.genes_path, "genes", self.annotations_path, None,
                       self.root / "run", "test-model", "medium", 30)

    def test_only_gene_identifiers_cross_metadata_boundary(self):
        workspace = self.prepare()
        genes = json.loads((workspace / "inputs/genes.json").read_text())
        self.assertEqual(genes, {"genes": ["A", "B"]})
        annotations = json.loads((workspace / "inputs/annotations.json").read_text())
        self.assertEqual(set(annotations), {"A", "B"})
        model_task = (workspace / "task.json").read_text()
        self.assertNotIn("old_run_score", model_task)
        self.assertNotIn("UNWANTED_CONTEXT", model_task)
        self.assertNotIn(str(self.root), model_task)

    def test_project_references_are_rejected(self):
        self.task["reference_files"] = ["project/README.md"]
        self.write(self.task_path, self.task)
        with self.assertRaisesRegex(ValueError, "outside the scientific input contract"):
            self.prepare()

    def test_experiment_metadata_is_rejected(self):
        self.task["biological_context"]["previous_mse"] = 0.1
        self.write(self.task_path, self.task)
        with self.assertRaisesRegex(ValueError, "non-task metadata"):
            self.prepare()

    def test_sandbox_mounts_only_private_workspace_and_backend_dependencies(self):
        self.prepare()
        command = sandbox_command(self.root / "run", "/usr/bin/python3", self.root / "auth.json")
        self.assertIn("--unshare-pid", command)
        self.assertIn("/workspace", command)
        self.assertNotIn(str(PACKAGE), command)
        self.assertNotIn("--ro-bind / /", " ".join(command))

    def test_package_runs_after_copy_outside_containing_project(self):
        copied = self.root / "independent_package"
        shutil.copytree(PACKAGE, copied, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        result = subprocess.run([sys.executable, str(copied / "launch.py"), "--task", str(self.task_path),
                                 "--genes", str(self.genes_path), "--annotations", str(self.annotations_path),
                                 "--run-dir", str(self.root / "independent_run"), "--codex-bin", "/usr/bin/python3",
                                 "--model", "test-model", "--prepare-only"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "prepared")

    def test_paper_cache_imports_external_text_without_prior_agent_metadata(self):
        source = self.root / "source_task"
        papers = source / "acquisition/papers"
        papers.mkdir(parents=True)
        (papers / "paper.txt").write_text("Scientific abstract and results")
        (papers / "manifest.jsonl").write_text(json.dumps({"paper_id": "PMID:1", "pmid": "1",
            "title": "A primary paper", "text_path": "acquisition/papers/paper.txt",
            "old_agent_plan": "Unwanted history", "previous_metric": 9999}) + "\n")
        workspace = prepare(self.task_path, self.genes_path, "genes", self.annotations_path, None,
                            self.root / "cached_run", "test-model", "medium", 30, source)
        manifest = (workspace / "inputs/paper_cache/manifest.jsonl").read_text()
        self.assertNotIn("old_agent_plan", manifest)
        self.assertNotIn("previous_metric", manifest)
        self.assertNotIn(str(source), manifest)
        self.assertIn("paper_00001.txt", manifest)


if __name__ == "__main__":
    unittest.main()
