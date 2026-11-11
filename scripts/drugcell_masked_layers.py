"""Evaluate DrugCell's masked gene-input layers with indexed multiplication.

Each output row has exactly one allowed input gene. The official parameter
initialization, full parameter tensors, gradient masks and checkpoint keys remain
available; the forward pass computes their supported entries directly.
"""

from __future__ import annotations

from types import MethodType

import torch
from torch import nn


ROWS = "_drugcell_mask_rows"
COLUMNS = "_drugcell_mask_columns"


def _indexed_gene_forward(layer, inputs):
    columns = getattr(layer, COLUMNS)
    weights = layer.weight[getattr(layer, ROWS), columns]
    output = inputs.index_select(-1, columns) * weights
    return output + layer.bias if layer.bias is not None else output


def _layers(model):
    mapping = getattr(model, "term_direct_gene_map", None)
    if not isinstance(mapping, dict):
        raise TypeError("Expected DrugCell's term_direct_gene_map")
    for term, gene_indices in mapping.items():
        name = term + "_direct_gene_layer"
        layer = model._modules.get(name)
        indices = list(gene_indices)
        if not isinstance(layer, nn.Linear):
            raise TypeError(f"Expected the released linear gene-input layer: {name}")
        if not indices or len(indices) != layer.out_features or len(indices) != len(set(indices)):
            raise ValueError(f"Gene indices differ from output rows: {term}")
        if any(not isinstance(index, int) or not 0 <= index < layer.in_features for index in indices):
            raise ValueError(f"Invalid fixed-universe gene index: {term}")
        yield term, layer, indices


def _mask_is_valid(tensor, rows, columns):
    # Count selected nonzero entries, including legitimate selected zeros.
    return bool(torch.count_nonzero(tensor).item()
                == torch.count_nonzero(tensor[rows, columns]).item())


def validate_masked_gene_layers(model, check_gradients=False):
    """Validate the one-gene-per-row invariant without allocating dense masks."""
    total, active, count = 0, 0, 0
    with torch.no_grad():
        for term, layer, indices in _layers(model):
            rows = torch.arange(len(indices), device=layer.weight.device)
            columns = torch.tensor(indices, dtype=torch.long, device=layer.weight.device)
            if not _mask_is_valid(layer.weight, rows, columns):
                raise ValueError(f"Off-mask direct-gene weights are nonzero: {term}")
            if check_gradients and layer.weight.grad is not None:
                if not _mask_is_valid(layer.weight.grad, rows, columns):
                    raise ValueError(f"Off-mask direct-gene gradients are nonzero: {term}")
            total += layer.weight.numel()
            active += len(indices)
            count += 1
    return {"layers": count, "dense_weight_entries": total,
            "active_weight_entries": active, "masked_weight_entries": total - active,
            "weight_masks_valid": True, "gradient_masks_checked": check_gradients}


def install_masked_gene_forward(model):
    """Install the indexed forward after the original initialization and masks.

    Existing modules and parameters retain their identities. Nonpersistent index
    buffers move with ``model.to(device)`` and leave ``state_dict`` keys intact.
    Checkpoints use the original parameter schema and can load into either
    implementation. Calling this function again is idempotent.
    """
    statistics = validate_masked_gene_layers(model)
    for term, layer, indices in _layers(model):
        if hasattr(layer, ROWS) or hasattr(layer, COLUMNS):
            if not hasattr(layer, ROWS) or not hasattr(layer, COLUMNS):
                raise ValueError(f"Incomplete installed gene indices: {term}")
            expected = torch.tensor(indices, dtype=torch.long, device=layer.weight.device)
            if not torch.equal(getattr(layer, COLUMNS), expected):
                raise ValueError(f"Installed gene order changed: {term}")
        else:
            layer.register_buffer(ROWS, torch.arange(len(indices), device=layer.weight.device), persistent=False)
            layer.register_buffer(COLUMNS, torch.tensor(indices, dtype=torch.long,
                                                        device=layer.weight.device), persistent=False)
        layer.forward = MethodType(_indexed_gene_forward, layer)
    return {"implementation": "indexed_one_gene_per_output_row", **statistics,
            "parameter_storage": "original_full_tensors", "checkpoint_schema": "unchanged"}
