"""Check matched-input efficiency accounting and comparison boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from finish_module_recipe_pilot import compare


class TimingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, seconds in (("previous", 120), ("hybrid", 60)):
            root = self.root / name
            def write(path, value):
                target = root / path; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(value))
            for path, value in [("task.json", {"task_id": "science"}), ("inputs/baseline_graph.json", {}),
                ("inputs/modules.json", {"M": {}}), ("inputs/placement_evidence.json", {}),
                ("inputs/genes.json", {"genes": ["A"]}), ("runtime.json", {"model": "example", "reasoning_effort": "medium"}),
                ("inputs/module_batches.json", [{"id": "b", "modules": ["M"]}]),
                ("inputs/manifest.json", {"files": [{"path": "inputs/sources/source.tsv", "sha256": "same"}]}),
                ("timing.json", {"total_wall_seconds": seconds, "graph": {}, "batches": [{"actions": {"add": 1}}]}),
                ("batches/b/context.json", {}),
                ("batches/b/editor_1/execution.json", {"role": "editor", "wall_seconds": seconds})]:
                write(path, value)
            events = [{"type": "item.completed", "item": {"type": "command_execution", "exit_code": 1}},
                      {"type": "item.completed", "item": {"type": "command_execution", "exit_code": 0}},
                      {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}}]
            (root / "batches/b/editor_1/events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        self.output = self.root / "report"; self.output.mkdir(); (self.output / "REPORT.md").write_text("Timing\n")

    def test_comparison_preserves_failures_and_measures_same_scope(self):
        result = compare(self.root / "hybrid", self.root / "previous", self.output)
        self.assertEqual(result["speedup"], 2)
        self.assertEqual(result["hybrid"]["events"]["shell_commands"], 2)
        self.assertEqual(result["hybrid"]["events"]["failed_shell_commands"], 1)
        self.assertEqual(result["hybrid"]["events"]["usage"]["input_tokens"], 100)
        self.assertTrue(all(result["matched_inputs"].values()))

    def test_mismatched_scientific_inputs_stop_comparison(self):
        (self.root / "hybrid/task.json").write_text('{"task_id":"different"}')
        with self.assertRaisesRegex(ValueError, "scientific inputs"):
            compare(self.root / "hybrid", self.root / "previous", self.output)


if __name__ == "__main__":
    unittest.main()
