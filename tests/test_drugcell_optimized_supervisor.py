"""Gate packed training on reproducible CUDA implementation checks."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("packed_supervisor", SCRIPTS / "run_drugcell_comparison_optimized.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CUDApreflightTests(unittest.TestCase):
    def setup_paths(self, root):
        bundle = root / "bundle"
        bundle.mkdir()
        (bundle / "manifest.json").write_text('{"files": {}}')
        return {"runtime": {"python": sys.executable, "preflight_bundle": str(bundle),
                "preflight_bundle_manifest_sha256": module.ontology_adapter.sha256(bundle / "manifest.json")}}

    def test_both_arms_are_checked_and_receipt_is_verified_on_reuse(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = self.setup_paths(root)
            called = []
            def run(command, **kwargs):
                arm = command[command.index("--arm") + 1]
                called.append(arm)
                path = Path(command[command.index("--output") + 1])
                path.mkdir()
                (path / "benchmark.json").write_text(json.dumps({"status": "passed", "training_step_speedup": 2,
                                 "timings": {}, "verification": {"passed": True}}))
            lock = mock.Mock()
            lock.fileno.return_value = 7
            with mock.patch.object(module.subprocess, "run", side_effect=run):
                module.cuda_preflight(root, config, {}, lock, {"index": 0})
                self.assertEqual(called, ["baseline", "augmented"])
                module.cuda_preflight(root, config, {}, lock, {"index": 0})
                self.assertEqual(len(called), 2)
                (root / "preflight/baseline/benchmark.json").write_text("changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    module.cuda_preflight(root, config, {}, lock, {"index": 0})

    def test_failed_cuda_check_does_not_publish_a_training_permit(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = self.setup_paths(root)
            lock = mock.Mock()
            lock.fileno.return_value = 7
            with mock.patch.object(module.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "check")):
                with self.assertRaises(subprocess.CalledProcessError):
                    module.cuda_preflight(root, config, {}, lock, {"index": 0})
            self.assertFalse((root / "cuda_preflight.json").exists())


if __name__ == "__main__":
    unittest.main()
