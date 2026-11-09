"""Regression checks for upstream's evaluate-train/evaluate-val/metrics order."""

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gears_evaluation_context.py"
spec = importlib.util.spec_from_file_location("evaluation_context", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvaluationContextTests(unittest.TestCase):
    def test_delayed_training_metrics_keep_their_own_phase_and_timing(self):
        contexts = module.EvaluationContexts()
        train, val, test = {}, {}, {}
        contexts.remember(train, "train", 1, 8.0)
        contexts.remember(val, "val", 1, 2.0)
        self.assertEqual(contexts.take(train), {"phase": "train", "epoch": 1, "evaluation_seconds": 8.0})
        self.assertEqual(contexts.take(val), {"phase": "val", "epoch": 1, "evaluation_seconds": 2.0})
        contexts.remember(test, "test", 15, 3.0)
        self.assertEqual(contexts.take(test)["phase"], "test")
        self.assertEqual(contexts.pending, {})

    def test_unknown_or_already_consumed_result_is_rejected(self):
        contexts = module.EvaluationContexts()
        result = {}
        with self.assertRaises(KeyError):
            contexts.take(result)
        contexts.remember(result, "val", 2, 1.0)
        contexts.take(result)
        with self.assertRaises(KeyError):
            contexts.take(result)


if __name__ == "__main__":
    unittest.main()
