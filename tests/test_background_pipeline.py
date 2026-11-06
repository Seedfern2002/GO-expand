"""Background failures must leave a readable final status without model calls."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class BackgroundPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("background_runner", ROOT / "scripts/run_agent_background.py")
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_stage_failure_is_saved_and_final_report_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "job.json").write_text(json.dumps({"source_hashes": {}, "codex_bin": "unused", "stage_timeout_seconds": 1}))
            with patch.object(self.runner.subprocess, "run", side_effect=subprocess.CalledProcessError(7, ["prepare"])), patch.object(self.runner.traceback, "print_exc"), patch("builtins.print"):
                result = self.runner.worker(directory)
            self.assertEqual(result, 1)
            state = json.loads((directory / "status.json").read_text())
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["phase"], "planner")
            self.assertIn("CalledProcessError", state["error"])
            self.assertTrue((directory / "REPORT.md").exists())
            self.assertEqual(json.loads((directory / "summary.json").read_text())["approved_batches"], [])

    def test_validation_retry_preserves_failed_output_and_stops_after_one_retry(self):
        for second_code in (0, 1):
            with self.subTest(second_code=second_code), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                (directory / "task.json").write_text(json.dumps({"task_id": "test"}))
                attempts = []

                def prepare(*args, **kwargs):
                    stage = directory / "planner"
                    stage.mkdir()
                    attempts.append(len(attempts) + 1)
                    (stage / "execution.json").write_text(json.dumps({"exit_code": 0, "error": "ValueError: invalid category"}))
                    (stage / "result.json").write_text(json.dumps({"attempt": attempts[-1]}))

                children = [SimpleNamespace(pid=100, wait=lambda **kw: 1), SimpleNamespace(pid=101, wait=lambda **kw: second_code)]
                with patch.object(self.runner.subprocess, "run", side_effect=prepare), patch.object(self.runner.subprocess, "Popen", side_effect=children), patch("builtins.print"):
                    if second_code:
                        with self.assertRaisesRegex(RuntimeError, "failed with exit code"):
                            self.runner.run_stage(directory, "planner", {"codex_bin": "unused", "stage_timeout_seconds": 1}, lambda **kw: None)
                    else:
                        self.runner.run_stage(directory, "planner", {"codex_bin": "unused", "stage_timeout_seconds": 1}, lambda **kw: None)
                self.assertEqual(attempts, [1, 2])
                self.assertEqual(json.loads((directory / "attempts/planner_1/result.json").read_text()), {"attempt": 1})
                self.assertEqual(json.loads((directory / "planner/result.json").read_text()), {"attempt": 2})
                self.assertIn("validation_feedback", json.loads((directory / "task.planner.repair.json").read_text()))


if __name__ == "__main__":
    unittest.main()
