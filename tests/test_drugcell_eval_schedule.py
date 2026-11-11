"""Check freeze gating and frozen-code selection for scheduled evaluation."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import drugcell_ontology as ontology
import run_drugcell_comparison_optimized as comparison
import wait_and_run_drugcell_eval as schedule


class EvaluationScheduleTests(unittest.TestCase):
    def test_active_knowledge_waits_and_never_attempts_a_freeze_verification(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "status.json").write_text('{"status":"running","phase":"retriever","round":7}')
            with patch.object(comparison, "verify_frozen_product") as verify:
                ready, state = schedule.knowledge_readiness({"knowledge_workspace": str(root)})
            self.assertFalse(ready)
            self.assertEqual(state["round"], 7)
            verify.assert_not_called()

    def test_terminal_status_requires_a_verified_freeze(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "status.json").write_text('{"status":"completed_with_gaps"}')
            with patch.object(comparison, "verify_frozen_product", side_effect=ValueError("missing manifest")):
                with self.assertRaisesRegex(ValueError, "missing manifest"):
                    schedule.knowledge_readiness({"knowledge_workspace": str(root)})
            (root / "knowledge").mkdir()
            (root / "knowledge/freeze_manifest.json").write_text('{"files":[]}')
            with patch.object(comparison, "verify_frozen_product", return_value=({}, {"status": "completed_with_gaps"})):
                ready, state = schedule.knowledge_readiness({"knowledge_workspace": str(root)})
            self.assertTrue(ready)
            self.assertEqual(state["knowledge_freeze_sha256"], ontology.sha256(root / "knowledge/freeze_manifest.json"))

    def test_failed_augmentation_closes_the_evaluation_gate(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "status.json").write_text('{"status":"failed","phase":"reviewer"}')
            with self.assertRaisesRegex(RuntimeError, "Knowledge pipeline failed"):
                schedule.knowledge_readiness({"knowledge_workspace": str(root)})

    def test_code_snapshot_tampering_is_detected_before_waiting_or_preparation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "worker.py").write_text("# pinned\n")
            (root / "schedule_manifest.json").write_text(json.dumps({"files": [
                {"path": "worker.py", "sha256": ontology.sha256(root / "worker.py")}]}))
            plan = {"scientific_inputs": [], "baseline_contract": []}
            schedule.verify_schedule(root / "plan.json", plan)
            (root / "worker.py").write_text("# changed\n")
            with self.assertRaisesRegex(ValueError, "Scheduled evaluation input changed"):
                schedule.verify_schedule(root / "plan.json", plan)

    def test_initializer_copies_predeclared_code_instead_of_live_project_scripts(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project, snapshot = root / "project", root / "frozen_scripts"
            (project / "scripts").mkdir(parents=True)
            snapshot.mkdir()
            source_names = ["run_drugcell_optimized.py", "run_drugcell_comparison_optimized.py",
                            "drugcell_masked_layers.py", "drugcell_packed.py", "benchmark_drugcell_optimized.py",
                            "drugcell_ontology.py", "wait_and_run_gears.py"]
            for filename in source_names:
                (project / "scripts" / filename).write_text("# live revision\n")
                (snapshot / filename).write_text("# scheduled revision\n")
            data = project / "upstream/data"
            data.mkdir(parents=True)
            for filename in ["gene2ind.txt", "cell2ind.txt", "drug2ind.txt"]:
                (data / filename).write_text("0\tG1\n")
            (project / "source.json").write_text('{"local_path":"upstream"}')
            prepared = project / "prepared"
            prepared.mkdir()
            (prepared / "manifest.json").write_text('{}')
            (prepared / "split_manifest.json").write_text('{}')
            (project / "baseline.txt").write_text("GO:R\tGO:A\tdefault\nGO:A\tG1\tgene\n")
            config = {"project_root": str(project), "source_manifest": "source.json",
                      "runtime": {"code_source_directory": str(snapshot)},
                      "data": {"prepared_directory": "prepared"},
                      "knowledge": {"augmentation_workspace": str(root / "workspace"), "baseline_ontology": "baseline.txt"}}
            path = root / "config.json"
            path.write_text(json.dumps(config))
            comparison.initialize(path, root / "experiment")
            for filename in ["run_drugcell.py", "run_drugcell_comparison.py", "drugcell_packed.py"]:
                self.assertEqual((root / "experiment/code" / filename).read_text(), "# scheduled revision\n")
            comparison.verify_experiment(root / "experiment")


if __name__ == "__main__":
    unittest.main()
