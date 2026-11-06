"""Prevent a matched augmentation run from using altered inputs or training settings."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class AugmentationInputTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "scripts/run_gears_baseline.py"
        spec = importlib.util.spec_from_file_location("augmented_run_test", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.module.ROOT = self.root
        self.reference = {"experiment": "baseline", "output_path": "old", "training": {"lr": 0.001}}
        self.module.write_json(self.root / "reference.json", self.reference)
        (self.root / "cache.csv").write_text("frozen graph cache\n")
        self.module.write_json(self.root / "manifest.json", {
            "reference_config_path": "reference.json",
            "files": [{"path": name, "sha256": self.module.sha256(self.root / name)}
                      for name in ("cache.csv", "reference.json")],
        })
        self.config = {**self.reference, "experiment": "augmented", "output_path": "new",
                       "go_augmentation": {"manifest_path": "manifest.json",
                                           "manifest_sha256": self.module.sha256(self.root / "manifest.json")}}

    def test_matching_run_accepts_new_output_with_identical_training_settings(self):
        self.assertIsNotNone(self.module.verify_augmentation_inputs(self.config))

    def test_changed_graph_cache_is_rejected(self):
        (self.root / "cache.csv").write_text("different graph\n")
        with self.assertRaisesRegex(ValueError, "input changed"):
            self.module.verify_augmentation_inputs(self.config)

    def test_training_change_is_rejected(self):
        self.config["training"] = {"lr": 0.002}
        with self.assertRaisesRegex(ValueError, "Training settings differ"):
            self.module.verify_augmentation_inputs(self.config)

    def test_original_baseline_requires_no_augmentation_manifest(self):
        self.assertIsNone(self.module.verify_augmentation_inputs(self.reference))


if __name__ == "__main__":
    unittest.main()
