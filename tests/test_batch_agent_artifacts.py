"""Task-wide batch contracts keep data outside model responses."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "requires optional agent dependencies")
class BatchArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("batch_runner", ROOT / "scripts/run_agent_stage.py")
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.task = {"task_id": "test", "scope": {"gene_universe_path": "universe.json", "gene_field": "graph_genes"}, "candidate_categories": ["protein_complex"], "retrieval_budget": {"max_candidate_records": 1}}
        self.write("universe.json", {"graph_genes": ["G1", "G2"], "perturbation_targets": ["G1"]})
        self.write("task.input.json", self.task)
        self.write("plan.input.json", {"augmentations": [{"id": "P1"}]})
        self.records = self.directory / "records.jsonl"
        self.records.write_text(' {"gene":"G1"}\n {"gene":"G2"}\n {"gene":"G1"}\n')
        self.write("provenance.json", {"source": "synthetic"})
        self.write("validation.json", {"validated_rows": 3, "failed_rows": 0})
        self.coverage = {"universe_size": 2, "genes_screened": 2, "genes_annotated": 2, "record_count": 3}
        self.write("coverage.json", self.coverage)
        self.batch = {"id": "B1", "plan_item_id": "P1", "source_name": "synthetic", "source_version": "1", "source_uri": "urn:example:source", "records_path": "records.jsonl", "records_sha256": hashlib.sha256(self.records.read_bytes()).hexdigest(), "provenance_path": "provenance.json", "validation_report_path": "validation.json", "coverage_report_path": "coverage.json"}
        self.result = {"schema_version": "2.0", "task_id": "test", "batches": [self.batch], "coverage": [{"plan_item_id": "P1", "status": "covered", "notes": ""}], "open_questions": []}

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value))

    def validate(self, stage, result):
        name = {"retriever": "candidates", "reviewer": "review"}[stage]
        (self.directory / "schema.json").write_text((ROOT / f"schemas/agents/batch/{name}.schema.json").read_text())
        self.runner.validate_result(self.directory, {"stage": stage, "workflow": "task_batch", "working_directory": str(self.directory)}, result)

    def test_bulk_rows_are_not_capped_by_the_literature_record_budget(self):
        self.validate("retriever", self.result)

    def test_partial_gene_screening_is_rejected(self):
        self.coverage["genes_screened"] = 1
        self.write("coverage.json", self.coverage)
        with self.assertRaisesRegex(ValueError, "complete task gene universe"):
            self.validate("retriever", self.result)

    def test_modified_batch_file_is_rejected(self):
        self.records.write_text('{}\n')
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.validate("retriever", self.result)

    def test_validation_must_account_for_all_rows(self):
        self.write("validation.json", {"validated_rows": 2, "failed_rows": 0})
        with self.assertRaisesRegex(ValueError, "every batch row"):
            self.validate("retriever", self.result)

    def test_accepted_batch_requires_the_matching_approved_artifact(self):
        self.write("candidates.input.json", self.result)
        self.write("audit.json", {"review_method": "source_policy_and_sample", "sampled_record_ids": ["row1"]})
        review = {"schema_version": "2.0", "task_id": "test", "batch_decisions": [{"batch_id": "B1", "verdict": "accept", "reasons": ["source policy and sample checked"], "evidence_checked": ["urn:example:source"], "review_method": "source_policy_and_sample", "approved_records_path": "records.jsonl", "approved_records_sha256": self.batch["records_sha256"], "audit_report_path": "audit.json"}], "checks_performed": [], "human_questions": []}
        self.validate("reviewer", review)
        bad = copy.deepcopy(review)
        bad["batch_decisions"][0]["approved_records_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.validate("reviewer", bad)

    def test_preparation_selects_batch_schema_and_english_prompts(self):
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare_agent_stage.py"), "--stage", "planner", "--task", str(ROOT / "configs/agent_tasks/gears_norman.json"), "--run-dir", str(self.directory / "run")], check=True, capture_output=True, text=True)
        stage = self.directory / "run/planner"
        manifest = json.loads((stage / "manifest.json").read_text())
        self.assertEqual(manifest["workflow"], "task_batch")
        self.assertEqual(manifest["requested_reasoning_effort"], "medium")
        prompt = (stage / "prompt.md").read_text()
        self.assertFalse(any('\u4e00' <= char <= '\u9fff' for char in prompt))
        self.assertNotIn('"$schema"', prompt)
        schema = json.loads((stage / "schema.json").read_text())
        self.assertEqual(schema["properties"]["schema_version"]["enum"], ["2.0"])
        categories = schema["properties"]["augmentations"]["items"]["properties"]["category"]["enum"]
        self.assertEqual(categories, ["pathway", "protein_complex", "regulatory_program"])

    def test_background_auto_review_has_no_conflicting_sandbox_flag(self):
        task = json.loads((ROOT / "configs/agent_tasks/gears_norman.json").read_text())
        task["execution"]["approval_mode"] = "auto_review"
        path = self.directory / "background-task.json"
        path.write_text(json.dumps(task))
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare_agent_stage.py"), "--stage", "planner", "--task", str(path), "--run-dir", str(self.directory / "background-run")], check=True, capture_output=True, text=True)
        command = json.loads((self.directory / "background-run/planner/manifest.json").read_text())["command"]
        self.assertIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)


if __name__ == "__main__":
    unittest.main()
