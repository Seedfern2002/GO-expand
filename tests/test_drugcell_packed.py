"""Check packed DrugCell semantics against the released independent networks."""

import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
try:
    import torch
    import networkx as nx
except ImportError:
    torch = nx = None


@unittest.skipIf(torch is None, "Packed model verification uses the numerical environment")
class PackedDrugCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "third_party/DrugCell/code"))
        import drugcell_NN
        import run_drugcell
        import drugcell_packed
        cls.upstream, cls.runner, cls.packed = drugcell_NN, run_drugcell, drugcell_packed

    def make_models(self, dtype=None):
        dtype = dtype or torch.float64
        torch.manual_seed(31)
        graph = nx.DiGraph([("GO:R", "GO:A"), ("GO:R", "GO:B"), ("GO:R", "GO:C"),
                            ("GO:A", "GO:D"), ("GO:A", "GO:E"), ("GO:B", "GO:D")])
        direct = {"GO:R": {0}, "GO:A": {0, 2}, "GO:C": {1, 2, 3},
                  "GO:D": {2}, "GO:E": {0, 3}}
        with contextlib.redirect_stdout(io.StringIO()):
            original = self.upstream.drugcell_nn({t: 4 for t in graph}, direct,
                       graph, 4, 3, "GO:R", 3, [4, 3], 3).to(dtype=dtype)
        self.runner.initialize_model(original, torch)
        state = torch.get_rng_state().clone()
        packed = self.packed.PackedDrugCell(original)
        self.assertTrue(torch.equal(state, torch.get_rng_state()))
        return original, packed

    def assert_states_close(self, original, packed, atol=1e-10, rtol=1e-9):
        exported = packed.export_upstream()
        self.assertEqual(set(original.state_dict()), set(exported))
        for key, value in original.state_dict().items():
            torch.testing.assert_close(value, exported[key], atol=atol, rtol=rtol, msg=key)

    def test_initialization_export_and_parameter_independence(self):
        original, packed = self.make_models()
        self.assert_states_close(original, packed, atol=0, rtol=0)
        self.assertNotEqual(id(original.final_linear_layer.weight), id(packed.final_linear_layer.weight))
        statistics = packed.statistics()
        self.assertEqual(statistics["GO_terms"], 6)
        self.assertEqual(statistics["auxiliary_heads"], 9)

    def test_train_eval_outputs_and_BatchNorm_statistics(self):
        original, packed = self.make_models()
        for training in (True, True, False):
            original.train(training)
            packed.train(training)
            features = torch.randn(11, 7, dtype=torch.float64)
            left, states_left = original(features)
            right, states_right = packed(features)
            self.assertEqual(set(left), set(right))
            for name in left:
                torch.testing.assert_close(left[name], right[name], atol=1e-11, rtol=1e-9, msg=name)
                torch.testing.assert_close(states_left[name], states_right[name], atol=1e-11, rtol=1e-9, msg=name)
            self.assert_states_close(original, packed)

    def test_loss_gradients_and_three_Adam_steps(self):
        original, packed = self.make_models()
        optimizers = [torch.optim.Adam(m.parameters(), lr=0.001, betas=(0.9, 0.99), eps=1e-5)
                      for m in (original, packed)]
        for _ in range(3):
            features = torch.randn(13, 7, dtype=torch.float64, requires_grad=True)
            second = features.detach().clone().requires_grad_()
            target = torch.randn(13, 1, dtype=torch.float64)
            for optimizer in optimizers:
                optimizer.zero_grad(set_to_none=True)
            heads, _ = original(features)
            loss = sum((1 if name == "final" else 0.2) * (output - target).square().mean()
                       for name, output in heads.items())
            prediction, other_loss = packed.objective(second, target)
            torch.testing.assert_close(loss, other_loss, atol=1e-11, rtol=1e-10)
            loss.backward()
            other_loss.backward()
            self.runner.apply_masks(self.runner.make_masks(original, torch), gradients=True)
            exported = packed.export_upstream(gradients=True)
            for name, value in original.named_parameters():
                torch.testing.assert_close(value.grad, exported[name], atol=1e-10, rtol=1e-8, msg=name)
            torch.testing.assert_close(features.grad, second.grad, atol=1e-10, rtol=1e-8)
            for optimizer in optimizers:
                optimizer.step()
            self.assert_states_close(original, packed, atol=1e-9, rtol=1e-7)

    def test_fp32_forward_and_update_tolerance(self):
        original, packed = self.make_models(torch.float32)
        features = torch.randn(19, 7)
        target = torch.randn(19, 1)
        heads, _ = original(features)
        prediction, loss = packed.objective(features, target)
        torch.testing.assert_close(prediction, heads["final"], atol=1e-6, rtol=1e-5)
        left_loss = sum((1 if name == "final" else 0.2) * (output - target).square().mean()
                        for name, output in heads.items())
        torch.testing.assert_close(loss, left_loss, atol=1e-6, rtol=1e-5)
        loss.backward()
        left_loss.backward()
        self.runner.apply_masks(self.runner.make_masks(original, torch), gradients=True)
        for m in (original, packed):
            torch.optim.Adam(m.parameters(), lr=0.001, betas=(0.9, 0.99), eps=1e-5).step()
        self.assert_states_close(original, packed, atol=1e-6, rtol=1e-4)

    def test_unmasked_input_is_rejected(self):
        original, _ = self.make_models()
        with torch.no_grad():
            original._modules["GO:D_direct_gene_layer"].weight[0, 0] = 0.1
        with self.assertRaisesRegex(ValueError, "masks"):
            self.packed.PackedDrugCell(original)

    def test_compact_checkpoint_roundtrip_and_original_compatibility(self):
        original, packed = self.make_models()
        features = torch.randn(11, 7, dtype=torch.float64)
        packed(features)
        _, restored = self.make_models()
        restored.load_state_dict(packed.state_dict())
        packed.eval()
        restored.eval()
        original.load_state_dict(packed.export_upstream())
        original.eval()
        torch.testing.assert_close(packed.predict_final(features), restored.predict_final(features), atol=0, rtol=0)
        torch.testing.assert_close(original(features)[0]["final"], restored.predict_final(features), atol=1e-11, rtol=1e-9)

    def test_checkpoint_rejects_a_different_graph_binding(self):
        _, packed = self.make_models()
        state = copy.deepcopy(packed.state_dict())
        state["_extra_state"]["children"]["GO:R"] = ["GO:A", "GO:C"]
        with self.assertRaisesRegex(ValueError, "different GO graph"):
            packed.load_state_dict(state)


if __name__ == "__main__":
    unittest.main()
