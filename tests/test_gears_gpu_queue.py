"""Resource-gating checks that never start a real training process."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/wait_and_run_gears.py"


class StopPolling(Exception):
    pass


class GPUQueueTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("gears_queue_test", SCRIPT)
        self.queue = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.queue)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "configs").mkdir()
        (self.root / "configs/gears_norman_baseline.json").write_text(json.dumps({"output_path": "run"}))
        (self.root / "run").mkdir()
        (self.root / "run/preparation.json").write_text('{"graphs_prepared": true}')
        self.queue.ROOT = self.root

    def assert_waits(self, row, stable_polls=1):
        with patch.object(self.queue, "gpu_candidates", return_value=[row]), \
             patch.object(self.queue.subprocess, "Popen") as launch, \
             patch.object(self.queue.time, "sleep", side_effect=StopPolling):
            with self.assertRaises(StopPolling):
                self.queue.run(stable_polls=stable_polls)
            launch.assert_not_called()
        state = json.loads((self.root / "run/queue_status.json").read_text())
        self.assertEqual(state["stage"], "waiting_for_unoccupied_gpu")

    def test_existing_compute_process_blocks_launch_even_at_zero_utilization(self):
        self.assert_waits({"index": 0, "uuid": "GPU-occupied", "free_mib": 60000,
                           "utilization_percent": 0, "has_compute_process": True})

    def test_high_utilization_blocks_launch_even_if_process_query_is_empty(self):
        self.assert_waits({"index": 0, "uuid": "GPU-busy", "free_mib": 60000,
                           "utilization_percent": 100, "has_compute_process": False})

    def test_one_idle_sample_is_insufficient_for_three_sample_policy(self):
        self.assert_waits({"index": 0, "uuid": "GPU-idle", "free_mib": 140000,
                           "utilization_percent": 0, "has_compute_process": False}, stable_polls=3)

    def test_incomplete_cpu_preparation_blocks_gpu_queries_and_launch(self):
        (self.root / "run/preparation.json").write_text('{"graphs_prepared": false}')
        with patch.object(self.queue, "gpu_candidates") as query, \
             patch.object(self.queue.subprocess, "Popen") as launch, \
             patch.object(self.queue.time, "sleep", side_effect=StopPolling):
            with self.assertRaises(StopPolling):
                self.queue.run()
            query.assert_not_called()
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
