"""Check cross-stage identity and coverage invariants without calling a model."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("jsonschema"), "requires the optional agent dependencies")
class AgentArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("agent_runner", ROOT / "scripts/run_agent_stage.py")
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.task = {"task_id": "test", "candidate_categories": ["protein_complex"], "retrieval_budget": {"max_candidate_records": 1}}
        self.plan = {"augmentations": [{"id": "P1"}]}
        self.record = {
            "id": "C1", "plan_item_id": "P1", "knowledge_layer": "external_attribute",
            "subject": {"id": "DEMO:G1", "label": "gene1"}, "relation": "member_of",
            "object": {"id": "LOCAL:M1", "label": "module1", "definition": "Synthetic module", "term_status": "candidate_module"},
            "polarity": "positive", "context": {"taxon_id": "DEMO:taxon", "cell_type": "", "tissue": "", "condition": ""},
            "evidence": [{"source_name": "synthetic", "source_uri": "urn:example:source", "version_or_access_date": "1", "locator": "row1", "support_summary": "Synthetic membership", "derivation": "curated_record", "analysis_method": ""}],
            "limitations": [],
        }
        self.candidates = {"schema_version": "1.0", "task_id": "test", "records": [self.record], "coverage": [{"plan_item_id": "P1", "status": "covered", "notes": ""}], "open_questions": []}
        self.review = {"schema_version": "1.0", "task_id": "test", "decisions": [{"candidate_id": "C1", "verdict": "accept", "reasons": ["Synthetic evidence checked"], "evidence_checked": ["urn:example:source#row1"], "requested_follow_up": [], "normalized_record": copy.deepcopy(self.record)}], "checks_performed": [], "human_questions": []}
        for name, value in [("task", self.task), ("plan", self.plan), ("candidates", self.candidates)]:
            (self.directory / f"{name}.input.json").write_text(json.dumps(value))

    def validate(self, stage, result):
        name = {"retriever": "candidates", "reviewer": "review"}[stage]
        (self.directory / "schema.json").write_text((ROOT / f"schemas/agents/{name}.schema.json").read_text())
        self.runner.validate_result(self.directory, {"stage": stage}, result)

    def test_valid_candidate_and_review_chain(self):
        self.validate("retriever", self.candidates)
        self.validate("reviewer", self.review)

    def test_unknown_plan_item_is_rejected(self):
        self.candidates["records"][0]["plan_item_id"] = "P2"
        with self.assertRaisesRegex(ValueError, "unknown plan item"):
            self.validate("retriever", self.candidates)

    def test_incomplete_coverage_is_rejected(self):
        self.candidates["coverage"] = []
        with self.assertRaisesRegex(ValueError, "every plan item"):
            self.validate("retriever", self.candidates)

    def test_review_must_account_for_all_candidates(self):
        self.review["decisions"] = []
        with self.assertRaisesRegex(ValueError, "every candidate"):
            self.validate("reviewer", self.review)

    def test_accept_requires_checked_evidence_and_normalized_record(self):
        self.review["decisions"][0]["evidence_checked"] = []
        with self.assertRaisesRegex(ValueError, "checked evidence"):
            self.validate("reviewer", self.review)
        self.review["decisions"][0]["evidence_checked"] = ["urn:example:source#row1"]
        self.review["decisions"][0]["normalized_record"] = None
        with self.assertRaisesRegex(ValueError, "retain its candidate id"):
            self.validate("reviewer", self.review)

    def test_different_task_is_rejected(self):
        self.candidates["task_id"] = "different_task"
        with self.assertRaisesRegex(ValueError, "task_id"):
            self.validate("retriever", self.candidates)

    def prepare_completed_review(self):
        self.validate("reviewer", self.review)
        result_path = self.directory / "result.json"
        result_path.write_text(json.dumps(self.review))
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        preparation = {"stage": "reviewer", "inputs": {name: {"sha256": digest(self.directory / f"{name}.input.json")} for name in ("task", "plan", "candidates")}}
        execution = {"status": "completed", "result_sha256": digest(result_path), "schema_sha256": digest(self.directory / "schema.json")}
        (self.directory / "manifest.json").write_text(json.dumps(preparation))
        (self.directory / "execution.json").write_text(json.dumps(execution))

    def export(self, *extra):
        return subprocess.run([sys.executable, str(ROOT / "scripts/export_agent_overlay.py"), "--review-stage-dir", str(self.directory), "--output-dir", str(self.directory / "overlay"), *extra], capture_output=True, text=True)

    def test_export_preserves_negation_and_excludes_rejected_candidates(self):
        other = copy.deepcopy(self.record)
        other["id"] = "C2"
        self.candidates["records"].append(other)
        (self.directory / "candidates.input.json").write_text(json.dumps(self.candidates))
        self.review["decisions"][0]["normalized_record"]["polarity"] = "negative"
        self.review["decisions"].append({"candidate_id": "C2", "verdict": "reject", "reasons": ["unsupported"], "evidence_checked": [], "requested_follow_up": [], "normalized_record": None})
        self.prepare_completed_review()
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in (self.directory / "overlay/overlay.jsonl").read_text().splitlines()]
        self.assertEqual([row["id"] for row in rows], ["C1"])
        self.assertEqual(rows[0]["polarity"], "negative")
        self.assertEqual(json.loads((self.directory / "overlay/manifest.json").read_text())["projection_status"], "not_projected")

    def test_export_rejects_review_modified_after_validation(self):
        self.prepare_completed_review()
        with (self.directory / "result.json").open("a") as handle:
            handle.write("\n")
        result = self.export()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("review result changed", result.stderr)
        self.assertFalse((self.directory / "overlay").exists())

    def test_text_correction_preserves_original_review_and_relation(self):
        self.prepare_completed_review()
        original = (self.directory / "result.json").read_bytes()
        corrections = {"actor": "test_curator", "edits": [{"candidate_id": "C1", "before": "Synthetic membership", "after": "Corrected assay wording", "reason": "Terminology check", "source_uri": "urn:example:source"}]}
        path = self.directory / "corrections.json"
        path.write_text(json.dumps(corrections))
        result = self.export("--text-corrections", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((self.directory / "overlay/overlay.jsonl").read_text())
        self.assertEqual(record["evidence"][0]["support_summary"], "Corrected assay wording")
        self.assertEqual(record["relation"], self.record["relation"])
        self.assertEqual((self.directory / "result.json").read_bytes(), original)
        self.assertTrue((self.directory / "overlay/text_corrections.json").exists())


if __name__ == "__main__":
    unittest.main()
