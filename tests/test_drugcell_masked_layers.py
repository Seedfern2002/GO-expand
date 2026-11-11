"""Compare indexed DrugCell input layers with the released masked linear form."""

import copy
import importlib.util
from pathlib import Path
import unittest

try:
    import torch
except ImportError:
    torch = None


if torch is not None:
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts/drugcell_masked_layers.py"
    spec = importlib.util.spec_from_file_location("drugcell_masked_layers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class ToyDrugCell(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.term_direct_gene_map = {"GO:1": {0, 3}, "GO:2": {1, 2, 3}}
            for term, indices in self.term_direct_gene_map.items():
                layer = torch.nn.Linear(5, len(indices), dtype=torch.float64)
                self.add_module(term + "_direct_gene_layer", layer)
                with torch.no_grad():
                    mask = torch.zeros_like(layer.weight)
                    mask[torch.arange(len(indices)), list(indices)] = 1
                    layer.weight.mul_(mask)

        def forward(self, inputs):
            return torch.cat([self._modules[term + "_direct_gene_layer"](inputs)
                              for term in self.term_direct_gene_map], dim=-1)

    def mask_original_gradients(model):
        for term, indices in model.term_direct_gene_map.items():
            weight = model._modules[term + "_direct_gene_layer"].weight
            with torch.no_grad():
                mask = torch.zeros_like(weight)
                mask[torch.arange(len(indices)), list(indices)] = 1
                weight.grad.mul_(mask)


@unittest.skipUnless(torch is not None, "PyTorch is available in .venv-gears")
class DrugCellMaskedLayersTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(13)
        self.original = ToyDrugCell()
        self.optimized = copy.deepcopy(self.original)
        self.inputs = torch.randn(7, 5, dtype=torch.float64)

    def test_forward_input_gradient_and_masked_parameter_gradients_match(self):
        module.install_masked_gene_forward(self.optimized)
        dense_input = self.inputs.clone().requires_grad_()
        indexed_input = self.inputs.clone().requires_grad_()
        dense = self.original(dense_input)
        indexed = self.optimized(indexed_input)
        torch.testing.assert_close(indexed, dense, rtol=1e-13, atol=1e-13)
        dense.square().sum().backward()
        indexed.square().sum().backward()
        mask_original_gradients(self.original)
        torch.testing.assert_close(indexed_input.grad, dense_input.grad, rtol=1e-13, atol=1e-13)
        for (left_name, left), (right_name, right) in zip(
                self.original.named_parameters(), self.optimized.named_parameters()):
            self.assertEqual(left_name, right_name)
            torch.testing.assert_close(right.grad, left.grad, rtol=1e-13, atol=1e-13)
        self.assertTrue(module.validate_masked_gene_layers(self.optimized, True)["weight_masks_valid"])

    def test_one_original_adam_step_matches(self):
        module.install_masked_gene_forward(self.optimized)
        options = {"lr": 0.001, "betas": (0.9, 0.99), "eps": 1e-5}
        original_adam = torch.optim.Adam(self.original.parameters(), **options)
        optimized_adam = torch.optim.Adam(self.optimized.parameters(), **options)
        self.original(self.inputs).square().mean().backward()
        self.optimized(self.inputs).square().mean().backward()
        mask_original_gradients(self.original)
        original_adam.step()
        optimized_adam.step()
        for left, right in zip(self.original.parameters(), self.optimized.parameters()):
            torch.testing.assert_close(right, left, rtol=1e-13, atol=1e-13)
        module.validate_masked_gene_layers(self.optimized)

    def test_install_preserves_rng_parameter_identity_and_checkpoint_keys(self):
        parameters = {name: id(parameter) for name, parameter in self.optimized.named_parameters()}
        keys = list(self.optimized.state_dict())
        rng = torch.get_rng_state().clone()
        report = module.install_masked_gene_forward(self.optimized)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertEqual(parameters, {name: id(parameter) for name, parameter in self.optimized.named_parameters()})
        self.assertEqual(keys, list(self.optimized.state_dict()))
        self.assertEqual(report["dense_weight_entries"], 25)
        self.assertEqual(report["active_weight_entries"], 5)
        self.assertEqual(module.install_masked_gene_forward(self.optimized), report)
        self.original.load_state_dict(self.optimized.state_dict(), strict=True)

    def test_index_buffers_move_with_model_and_keep_integer_dtype(self):
        module.install_masked_gene_forward(self.optimized)
        self.optimized.to(dtype=torch.float32)
        for term in self.optimized.term_direct_gene_map:
            layer = self.optimized._modules[term + "_direct_gene_layer"]
            self.assertEqual(getattr(layer, module.COLUMNS).dtype, torch.int64)
        torch.testing.assert_close(self.optimized(self.inputs.float()), self.original(self.inputs).float(),
                                   rtol=1e-6, atol=1e-6)

    def test_install_rejects_off_mask_weights_and_gradient_validation_detects_unmasked_updates(self):
        with torch.no_grad():
            self.optimized._modules["GO:1_direct_gene_layer"].weight[0, 4] = 0.25
        with self.assertRaisesRegex(ValueError, "Off-mask direct-gene weights"):
            module.install_masked_gene_forward(self.optimized)
        self.original(self.inputs).sum().backward()
        with self.assertRaisesRegex(ValueError, "Off-mask direct-gene gradients"):
            module.validate_masked_gene_layers(self.original, check_gradients=True)


if __name__ == "__main__":
    unittest.main()
