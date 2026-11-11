"""Check frozen knowledge, matched aggregation and GPU-gated supervision."""

import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("drugcell_supervisor_tests", SCRIPTS / "run_drugcell_comparison.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StopPolling(Exception):
    pass


class DrugCellSupervisorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def make_workspace(self):
        workspace = self.root / "workspace"
        inputs, knowledge = workspace / "inputs", workspace / "knowledge"
        inputs.mkdir(parents=True)
        knowledge.mkdir()
        (inputs / "genes.json").write_text(json.dumps({"genes": ["G1", "G2"]}))
        (inputs / "go.obo").write_text(
            "format-version: 1.2\n\n[Term]\nid: GO:0008150\nnamespace: biological_process\n"
            "\n[Term]\nid: GO:1\nnamespace: biological_process\nis_a: GO:0008150\n"
            "\n[Term]\nid: GO:2\nnamespace: biological_process\nis_a: GO:1\n"
            "\n[Term]\nid: GO:3\nnamespace: molecular_function\n"
        )
        task = {"compilation": {"ontology_path": "inputs/go.obo"}}
        (knowledge / "task.json").write_text(json.dumps(task))
        (knowledge / "validation.json").write_text('{"passed": true}')
        (knowledge / "summary.json").write_text('{"genes": 2}')
        rows = [{"gene": "G1", "attributes": ["GO:0008150", "GO:1", "GO:2"]},
                {"gene": "G2", "attributes": ["EXTERNAL:unsafe_label.1", "GO:3"]}]
        (knowledge / "gene_attributes.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        manifest = {"files": [{"path": path.name, "sha256": module.ontology_adapter.sha256(path)}
                              for path in sorted(knowledge.iterdir())],
                    "inputs": [{"path": "/workspace/inputs/" + path.name, "sha256": module.ontology_adapter.sha256(path)}
                               for path in sorted(inputs.iterdir())]}
        (knowledge / "freeze_manifest.json").write_text(json.dumps(manifest))
        (workspace / "status.json").write_text('{"status": "completed_with_gaps", "phase": "finished"}')
        return workspace

    def make_experiment(self):
        output = self.root / "experiment"
        output.mkdir()
        (output / "source_inputs").mkdir()
        (output / "source_inputs/gene2ind.txt").write_text("0\tG1\n1\tG2\n")
        (output / "baseline").mkdir()
        (output / "baseline/drugcell_ont.txt").write_text("GO:0008150\tGO:1\tdefault\nGO:1\tG1\tgene\n")
        return output

    def test_freeze_requires_finished_state_and_detects_modified_artifacts(self):
        workspace = self.make_workspace()
        module.verify_frozen_product(workspace)
        (workspace / "status.json").write_text('{"status": "running"}')
        with self.assertRaisesRegex(ValueError, "finish"):
            module.verify_frozen_product(workspace)
        (workspace / "status.json").write_text('{"status": "completed"}')
        (workspace / "knowledge/summary.json").write_text('{"genes": 99}')
        with self.assertRaisesRegex(ValueError, "mismatch"):
            module.verify_frozen_product(workspace)

    def test_initialization_pins_manifest_contract_independently_of_live_preparation(self):
        project = self.root / "project"
        scripts = project / "scripts"
        scripts.mkdir(parents=True)
        for name in ("run_drugcell.py", "run_drugcell_comparison.py", "drugcell_masked_layers.py",
                     "drugcell_ontology.py", "wait_and_run_gears.py"):
            (scripts / name).write_text("# Frozen test source\n")
        data = project / "third_party/DrugCell/data"
        data.mkdir(parents=True)
        for name in ("gene2ind.txt", "cell2ind.txt", "drug2ind.txt"):
            (data / name).write_text("0\tID\n")
        (project / "source.json").write_text(json.dumps({"local_path": "third_party/DrugCell"}))
        (project / "baseline.txt").write_text("GO:0008150\tGO:1\tdefault\nGO:1\tID\tgene\n")
        prepared = project / "prepared"
        prepared.mkdir()
        original_data = {"source": "original measured inputs"}
        original_splits = {"folds": [{"fold": 0, "test_hash": "original"}]}
        (prepared / "manifest.json").write_text(json.dumps(original_data))
        (prepared / "split_manifest.json").write_text(json.dumps(original_splits))
        config = {"project_root": str(project), "source_manifest": "source.json",
                  "data": {"prepared_directory": "prepared", "folds": [0]},
                  "knowledge": {"baseline_ontology": "baseline.txt", "augmentation_workspace": str(self.root / "workspace")}}
        config_path = project / "config.json"
        config_path.write_text(json.dumps(config))
        output = self.root / "frozen_experiment"
        frozen = module.initialize(config_path, output)
        (prepared / "manifest.json").write_text('{"source": "replaced live inputs"}')
        (prepared / "split_manifest.json").write_text('{"folds": []}')
        self.assertEqual(json.loads(Path(frozen["data"]["frozen_manifest"]).read_text()), original_data)
        self.assertEqual(json.loads(Path(frozen["data"]["frozen_split_manifest"]).read_text()), original_splits)
        for stem in ("frozen_manifest", "frozen_split_manifest"):
            self.assertEqual(module.ontology_adapter.sha256(frozen["data"][stem]), frozen["data"][stem + "_sha256"])
        module.verify_experiment(output)
        Path(frozen["data"]["frozen_split_manifest"]).write_text('{"folds": []}')
        with self.assertRaisesRegex(ValueError, "changed"):
            module.verify_experiment(output)

    def test_freeze_rejects_paths_outside_task_workspace(self):
        workspace = self.make_workspace()
        manifest_path = workspace / "knowledge/freeze_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["inputs"][0]["path"] = "/etc/passwd"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "outside"):
            module.verify_frozen_product(workspace)
        with self.assertRaisesRegex(ValueError, "escapes"):
            module.safe_child(workspace, "../../outside")

    def test_snapshot_preserves_provenance_and_can_be_verified_independently(self):
        workspace = self.make_workspace()
        snapshot = self.root / "snapshot"
        receipt = module.snapshot_knowledge(workspace, snapshot)
        self.assertTrue((snapshot / "provenance/inputs/go.obo").is_file())
        for row in receipt["copied_files"]:
            self.assertEqual(module.ontology_adapter.sha256(snapshot / row["path"]), row["sha256"])
        workspace.rename(self.root / "retired_workspace")
        self.assertEqual(module.snapshot_knowledge(workspace, snapshot), receipt)
        (snapshot / "provenance/inputs/go.obo").write_text("changed")
        with self.assertRaisesRegex(ValueError, "hash"):
            module.snapshot_knowledge(workspace, snapshot)

    def test_external_modules_use_explicit_aggregation_and_reversible_identifiers(self):
        workspace, output = self.make_workspace(), self.make_experiment()
        baseline = output / "baseline/drugcell_ont.txt"
        original = baseline.read_bytes()
        config = {"knowledge": {"augmentation_workspace": str(workspace), "baseline_ontology": str(baseline)}}
        result = module.prepare_augmentation(output, config)
        self.assertTrue((output / "augmentation/drugcell_ont.txt").read_bytes().startswith(original))
        aliases = json.loads((output / "projection_inputs/external_identifier_map.json").read_text())
        model_id = aliases["EXTERNAL:unsafe_label.1"]
        self.assertTrue(model_id.startswith("OVERLAY:"))
        self.assertNotIn("_", model_id)
        parent_map = json.loads((output / "projection_inputs/external_parent_map.json").read_text())
        self.assertEqual(parent_map[model_id], ["GO:0008150"])
        edges = [json.loads(row) for row in (output / "augmentation/edge_provenance.jsonl").read_text().splitlines()]
        self.assertEqual({row["semantics"] for row in edges}, {"explicit_model_aggregation", "compressed_GO_is_a_path"})
        self.assertEqual(result["projection_counts"]["added_terms"], 2)
        self.assertEqual(result["exclusion_reasons"]["new_term_requires_active_canonical_GO_BP"], 1)

    def test_gpu_policy_requires_stable_idle_and_resets_when_occupied(self):
        idle = {"index": 0, "uuid": "GPU-test", "free_mib": 60000,
                "utilization_percent": 0, "has_compute_process": False}
        ready, streak = module.eligible_gpu_rows([idle], {}, 3)
        self.assertEqual(ready, [])
        ready, streak = module.eligible_gpu_rows([idle], streak, 3)
        self.assertEqual(ready, [])
        ready, streak = module.eligible_gpu_rows([{**idle, "has_compute_process": True}], streak, 3)
        self.assertEqual((ready, streak), ([], {}))
        for _ in range(3):
            ready, streak = module.eligible_gpu_rows([idle], streak, 3)
        self.assertEqual(ready, [idle])
        for change in ({"free_mib": 1000}, {"utilization_percent": 10}, {"has_compute_process": True}):
            self.assertEqual(module.eligible_gpu_rows([{**idle, **change}], {}, 1)[0], [])

    def test_busy_gpu_supervisor_keeps_all_training_pending(self):
        output = self.make_experiment()
        config = {"project_root": str(self.root), "data": {"folds": [0]},
                  "knowledge": {"augmentation_workspace": str(self.root / "pending_workspace")}}
        (output / "config.json").write_text(json.dumps(config))
        busy = {"index": 0, "uuid": "GPU-busy", "free_mib": 60000,
                "utilization_percent": 0, "has_compute_process": True}
        with patch.object(module, "verify_experiment"), \
             patch.object(module.gpu_queue, "ROOT", output / "wrong_frozen_root"), \
             patch.object(module.gpu_queue, "gpu_candidates", return_value=[busy]), \
             patch.object(module.gpu_queue, "reserve_gpu") as reserve, \
             patch.object(module.subprocess, "Popen") as launch, \
             patch.object(module.time, "sleep", side_effect=StopPolling):
            with self.assertRaises(StopPolling):
                module.supervise(output)
            self.assertEqual(module.gpu_queue.ROOT, self.root)
            reserve.assert_not_called()
            launch.assert_not_called()
        state = json.loads((output / "run_status.json").read_text())
        self.assertEqual(state["job_stages"]["baseline_0"], "waiting_for_unoccupied_gpu")
        self.assertEqual(state["job_stages"]["augmented_0"], "waiting_for_knowledge")

    def test_report_uses_only_complete_and_paired_folds(self):
        output = self.make_experiment()
        jobs = {}
        for fold in range(2):
            for arm in ("baseline", "augmented"):
                run = output / arm / str(fold)
                run.mkdir(parents=True)
                jobs[f"{arm}_{fold}"] = {"arm": arm, "fold": fold, "output": str(run), "stage": "waiting_for_unoccupied_gpu"}
                if (arm, fold) != ("augmented", 1):
                    rho = {("baseline", 0): .5, ("baseline", 1): .7, ("augmented", 0): .8}[arm, fold]
                    (run / "metrics.json").write_text(json.dumps({"status": "complete", "selected_epoch": 3,
                        "test": {"spearman": rho, "pearson": rho, "mse": 1 - rho, "rmse": (1 - rho) ** .5}}))
        result, terminal = module.summarize(output, {"data": {"folds": [0, 1]}}, jobs, {"stage": "ontology_frozen"})
        self.assertFalse(terminal)
        self.assertEqual(result["arm_aggregates"]["baseline"]["completed_folds"], 2)
        self.assertEqual(result["arm_aggregates"]["augmented"]["completed_folds"], 1)
        self.assertAlmostEqual(result["arm_aggregates"]["baseline"]["metrics"]["spearman"]["mean"], .6)
        self.assertEqual([p["fold"] for p in result["paired_folds"]], [0])
        self.assertAlmostEqual(result["paired_metric_delta_means"]["spearman"], .3)
        self.assertIsNone(result["pooled_metrics"])

    def test_pooled_metrics_read_each_test_fold_once_and_handle_ties(self):
        output = self.make_experiment()
        rows = []
        for arm in ("baseline", "augmented"):
            run = output / arm
            run.mkdir(exist_ok=True)
            with gzip.open(run / "predictions.tsv.gz", "wt") as stream:
                stream.write("cell_index\tdrug_index\tobserved\tpredicted\n")
                for index, value in enumerate((1.0, 1.0, 3.0)):
                    stream.write(f"{index}\t0\t{value}\t{value}\n")
            rows.append({"arm": arm, "fold": 0, "stage": "complete", "run": str(run)})
        result = module.pooled_metrics(output, rows, [0])
        self.assertEqual(result["arms"]["baseline"]["n"], 3)
        self.assertEqual(result["arms"]["baseline"]["spearman"], 1.0)
        self.assertEqual(result["arms"]["augmented"]["mse"], 0.0)


if __name__ == "__main__":
    unittest.main()
