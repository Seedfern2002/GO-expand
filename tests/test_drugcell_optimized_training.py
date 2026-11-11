"""Check selected-checkpoint evaluation in the packed training loop."""

import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
try:
    import torch
    import numpy as np
    import networkx as nx
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Requires the numerical runtime")
class OptimizedTrainingTests(unittest.TestCase):
    def test_validation_selection_and_compact_checkpoint_reload_precede_test(self):
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "third_party/DrugCell/code"))
        import drugcell_NN
        import drugcell_packed
        import run_drugcell_optimized as runner
        torch.set_num_threads(2)
        torch.manual_seed(42)
        with contextlib.redirect_stdout(io.StringIO()):
            original = drugcell_NN.drugcell_nn({"GO:R": 2, "GO:L": 2},
                       {"GO:L": {0, 1}}, nx.DiGraph([("GO:R", "GO:L")]),
                       2, 2, "GO:R", 3, [3], 2)
        runner.initialize_model(original, torch)
        model = drugcell_packed.PackedDrugCell(original)
        cells = torch.tensor([[0., 1.], [1., 0.]])
        drugs = torch.tensor([[0., 1.], [1., 0.]])
        pairs = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
        labels = np.array([0., 1., 2., 3.], dtype=np.float32)
        test_pairs = pairs.copy()
        events, selected = [], {}

        def prediction(current, incoming, *_):
            if incoming is test_pairs:
                events.append("test_prediction")
                for key, value in current.state_dict().items():
                    if isinstance(value, torch.Tensor):
                        torch.testing.assert_close(value, selected[key], atol=0, rtol=0)
                    else:
                        self.assertEqual(value, selected[key])
                return labels
            events.append("validation")
            if len(events) == 1:
                selected.update(copy.deepcopy(current.state_dict()))
                return labels
            return labels[::-1].copy()

        def load_test():
            events.append("load_test")
            return test_pairs, labels

        settings = {"batch_size": 2, "max_epochs": 2, "learning_rate": 0.001,
                    "betas": [0.9, 0.99], "epsilon": 1e-5, "auxiliary_loss_weight_per_head": 0.2}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(runner, "predict", side_effect=prediction):
            with contextlib.redirect_stdout(io.StringIO()):
                result = runner.fit_model(model, (pairs, labels), (pairs, labels), load_test,
                                           cells, drugs, settings, temp, torch)
            self.assertEqual(result["selected_epoch"], 1)
            self.assertEqual(events, ["validation", "validation", "load_test", "test_prediction"])
            self.assertAlmostEqual(result["test"]["spearman"], 1)
            self.assertEqual(len(list(Path(temp).glob("*.pt"))), 1)


if __name__ == "__main__":
    unittest.main()
