"""Check DrugCell checkpoint selection, masks and pinned experiment inputs."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_drugcell", ROOT / "scripts/run_drugcell.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
try:
    import numpy as np
    import scipy
    import torch
    import networkx as nx
except ImportError:
    np = torch = nx = None


class DrugCellInputTests(unittest.TestCase):
    def make_fixture(self, root):
        source = root / "source"
        (source / "data").mkdir(parents=True)
        baseline = source / "data/drugcell_ont.txt"
        baseline.write_text("GO:ROOT\tGO:LEAF\tdefault\nGO:LEAF\tG1\tgene\n")
        feature = source / "data/features.txt"
        feature.write_text("0,1\n")
        source_manifest = root / "source.json"
        module.atomic_json(source_manifest, {"local_path": "source", "commit": "PIN",
                   "files": {"data/drugcell_ont.txt": module.sha256(baseline)}})
        prepared = root / "prepared"
        prepared.mkdir()
        parts = {}
        for name in ("train", "validation", "test"):
            file = prepared / (name + ".tsv")
            file.write_text("C1\tD1\t0.5\n")
            parts[name] = {"path": file.name, "sha256": module.sha256(file)}
        split = prepared / "split_manifest.json"
        module.atomic_json(split, {"protocol": {"seed": 0, "group_key": ["cell_identifier", "drug_identifier"],
                   "validation_unique_pairs_per_fold": 1}, "folds": [{"fold": 0, "partitions": parts}]})
        module.atomic_json(prepared / "manifest.json", {"source_commit": "PIN",
                   "source_inputs": {"features": {"path": str(feature), "sha256": module.sha256(feature)}},
                   "split_manifest": {"path": split.name, "sha256": module.sha256(split)}})
        config = {"source_manifest": "source.json", "data": {"prepared_directory": "prepared",
                  "split_seed": 0, "validation_pairs_per_fold": 1},
                  "knowledge": {"baseline_ontology": "source/data/drugcell_ont.txt"}}
        config_path = root / "config.json"
        module.atomic_json(config_path, config)
        return config_path, config, baseline

    def test_pinned_splits_and_ontology_prefix_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, config, baseline = self.make_fixture(root)
            with mock.patch.object(module.subprocess, "check_output", return_value="PIN\n"):
                _, splits, records, _ = module.verify_inputs(config_path, config, baseline, 0, root)
                self.assertEqual(set(splits), {"train", "validation", "test"})
                self.assertEqual(records["ontology"]["sha256"], module.sha256(baseline))
                different = root / "wrong_ontology.txt"
                different.write_text("GO:CHANGED\tG1\tgene\n")
                with self.assertRaisesRegex(ValueError, "preserve"):
                    module.verify_inputs(config_path, config, different, 0, root)
                (root / "prepared/test.tsv").write_text("C1\tD1\t1.0\n")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    module.verify_inputs(config_path, config, baseline, 0, root)

    def test_selection_handles_negative_scores_and_latest_ties(self):
        self.assertTrue(module.improves_validation(-0.9, None))
        self.assertTrue(module.improves_validation(0.8, 0.8))
        self.assertFalse(module.improves_validation(None, 0.8))
        self.assertFalse(module.improves_validation(float("nan"), 0.8))
        self.assertFalse(module.improves_validation(0.7, 0.8))

    def test_frozen_manifest_pins_splits_after_live_manifest_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path, config, baseline = self.make_fixture(root)
            for key, source in (("frozen_manifest", "manifest.json"),
                                ("frozen_split_manifest", "split_manifest.json")):
                frozen = root / ("frozen_" + source)
                frozen.write_bytes((root / "prepared" / source).read_bytes())
                config["data"][key] = str(frozen)
                config["data"][key + "_sha256"] = module.sha256(frozen)
            module.atomic_json(config_path, config)
            (root / "prepared/manifest.json").write_text("replacement live manifest\n")
            with mock.patch.object(module.subprocess, "check_output", return_value="PIN\n"):
                _, _, records, _ = module.verify_inputs(config_path, config, baseline, 0, root)
                self.assertEqual(records["data_manifest"]["path"], config["data"]["frozen_manifest"])
                changed = root / "prepared/train.tsv"
                changed.write_text("C1\tD1\t0.9\n")
                live_split = module.read_json(root / "prepared/split_manifest.json")
                live_split["folds"][0]["partitions"]["train"]["sha256"] = module.sha256(changed)
                module.atomic_json(root / "prepared/split_manifest.json", live_split)
                with self.assertRaisesRegex(ValueError, "checksum"):
                    module.verify_inputs(config_path, config, baseline, 0, root)


@unittest.skipIf(torch is None, "DrugCell numerical runtime requires the GEARS environment")
class DrugCellTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)

    def settings(self, epochs=2):
        return {"batch_size": 2, "max_epochs": epochs, "learning_rate": 0.001,
                "betas": [0.9, 0.99], "epsilon": 1e-5,
                "auxiliary_loss_weight_per_head": 0.2}

    def test_metrics_handle_ties_constants_and_nonfinite_values(self):
        result = module.regression_metrics([1, 1, 2, 3], [2, 2, 4, 6])
        self.assertAlmostEqual(result["spearman"], 1.0)
        self.assertAlmostEqual(result["pearson"], 1.0)
        self.assertIsNone(module.regression_metrics([1, 2, 3], [5, 5, 5])["spearman"])
        self.assertIsNone(module.regression_metrics([1], [2])["pearson"])
        with self.assertRaises(ValueError):
            module.regression_metrics([1, 2], [float("nan"), 2])

    def test_validation_selects_checkpoint_before_test_is_loaded(self):
        class TinyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(3, 1)
                self.term_direct_gene_map = {}

            def forward(self, features):
                final = self.linear(features)
                return {"GO:ROOT": final * 0.5, "final": final}, {}

        torch.manual_seed(0)
        model = TinyModel()
        features = torch.tensor([[0., 1.], [1., 0.]])
        drugs = torch.tensor([[0.], [1.]])
        training = (np.array([[0, 0], [1, 0], [0, 1], [1, 1]]), np.array([0., 1., 1., 2.], dtype=np.float32))
        validation = (np.array([[0, 0], [1, 0], [1, 1]]), np.array([1., 2., 3.], dtype=np.float32))
        test_pairs = np.array([[1, 1], [1, 0], [0, 0]])
        events, first_state = [], {}

        def fake_predict(current, pairs, *_):
            if pairs is test_pairs:
                events.append("test_prediction")
                for key, value in current.state_dict().items():
                    torch.testing.assert_close(value, first_state[key])
                return np.array([3., 2., 1.])
            events.append("validation")
            if len(events) == 1:
                first_state.update({key: value.detach().clone() for key, value in current.state_dict().items()})
                return np.array([1., 2., 3.])
            return np.array([3., 2., 1.])

        def load_test():
            events.append("load_test")
            return test_pairs, np.array([3., 2., 1.], dtype=np.float32)

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(module, "predict", side_effect=fake_predict):
            with contextlib.redirect_stdout(io.StringIO()):
                result = module.fit_model(model, training, validation, load_test, features, drugs,
                                           self.settings(), temporary, torch)
            self.assertEqual(result["selected_epoch"], 1)
            self.assertEqual(events, ["validation", "validation", "load_test", "test_prediction"])
            self.assertAlmostEqual(result["test"]["spearman"], 1.0)
            self.assertEqual(len(list(Path(temporary).glob("*.pt"))), 1)
            history = [json.loads(line) for line in (Path(temporary) / "training_metrics.jsonl").read_text().splitlines()]
            self.assertEqual([row["selected"] for row in history], [True, False])

    def test_upstream_model_trains_with_exact_gene_masks(self):
        source = ROOT / "third_party/DrugCell/code"
        if not (source / "drugcell_NN.py").is_file():
            self.skipTest("Official DrugCell checkout is required for this integration check")
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(source))
        import importlib
        upstream = importlib.import_module("drugcell_NN")
        torch.manual_seed(4)
        with contextlib.redirect_stdout(io.StringIO()):
            model = upstream.drugcell_nn({"GO:ROOT": 2, "GO:LEAF": 1},
                      {"GO:ROOT": {0}, "GO:LEAF": {1}}, nx.DiGraph([("GO:ROOT", "GO:LEAF")]),
                      2, 2, "GO:ROOT", 3, [3], 2).double()
        cells = torch.tensor([[0., 0.], [0., 1.], [1., 0.], [1., 1.]], dtype=torch.float64)
        drugs = torch.tensor([[0., 1.], [1., 0.]], dtype=torch.float64)
        pairs = np.array([[0, 0], [1, 1], [2, 0], [3, 1], [0, 1], [3, 0]])
        labels = np.array([0., 1., 0.5, 2., 0.2, 1.5], dtype=np.float64)
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            result = module.fit_model(model, (pairs, labels), (pairs, labels), lambda: (pairs, labels),
                                      cells, drugs, self.settings(1), temporary, torch)
        self.assertEqual(result["auxiliary_head_count"], 4)
        self.assertEqual(result["training_epochs"], 1)
        self.assertEqual(result["test"]["n"], 6)
        for parameter, rows, columns in module.make_masks(model, torch):
            self.assertEqual(torch.count_nonzero(parameter).item(),
                             torch.count_nonzero(parameter[rows, columns]).item())


if __name__ == "__main__":
    unittest.main()
