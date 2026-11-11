"""Pack independent DrugCell GO networks into level-wise batched operations.

Conversion consumes an initialized, masked released model. Every GO subsystem
retains its own linear parameters, BatchNorm channels and auxiliary head. Known
zero gene-input weights are represented by their active entries. The original
checkpoint schema can be reconstructed for numerical verification/export.
"""

from __future__ import annotations

import copy
import math

import torch
from torch import nn


def parameter(value):
    return nn.Parameter(value.detach().clone())


class TermGroup(nn.Module):
    def __init__(self, reference, terms, width, positions):
        super().__init__()
        self.terms = list(terms)
        self.width = width
        self.hidden = reference.num_hiddens_genotype
        exemplar = reference._modules[terms[0] + "_linear_layer"].weight
        count = len(terms)
        weight = exemplar.new_zeros(count, self.hidden, width)
        bias = exemplar.new_empty(count, self.hidden)
        gene_weight = exemplar.new_zeros(count, width)
        gene_bias = exemplar.new_zeros(count, width)
        gene_indices = torch.zeros(count, width, dtype=torch.long, device=exemplar.device)
        child_indices = torch.zeros_like(gene_indices)
        gene_mask = exemplar.new_zeros(count, width)
        child_mask = exemplar.new_zeros(count, width)
        self.direct = {}
        self.actual_widths = []
        normals = []
        aux_w1, aux_b1, aux_w2, aux_b2 = [], [], [], []
        for index, term in enumerate(terms):
            linear = reference._modules[term + "_linear_layer"]
            actual = linear.in_features
            self.actual_widths.append(actual)
            weight[index, :, :actual] = linear.weight.detach()
            bias[index] = linear.bias.detach()
            children = reference.term_neighbor_map[term]
            child_count = len(children) * self.hidden
            ids = [positions[child] * self.hidden + channel
                   for child in children for channel in range(self.hidden)]
            if ids:
                child_indices[index, :child_count] = torch.tensor(ids, device=exemplar.device)
                child_mask[index, :child_count] = 1
            if term in reference.term_direct_gene_map:
                genes = list(reference.term_direct_gene_map[term])
                direct = reference._modules[term + "_direct_gene_layer"]
                rows = torch.arange(len(genes), device=exemplar.device)
                columns = torch.tensor(genes, device=exemplar.device)
                selected = direct.weight.detach()[rows, columns]
                if torch.count_nonzero(direct.weight).item() != torch.count_nonzero(selected).item():
                    raise ValueError("Pack the model after applying its direct-gene masks")
                stop = child_count + len(genes)
                gene_weight[index, child_count:stop] = selected
                gene_bias[index, child_count:stop] = direct.bias.detach()
                gene_indices[index, child_count:stop] = columns
                gene_mask[index, child_count:stop] = 1
                self.direct[term] = (genes, child_count)
            normals.append(reference._modules[term + "_batchnorm_layer"])
            first = reference._modules[term + "_aux_linear_layer1"]
            last = reference._modules[term + "_aux_linear_layer2"]
            aux_w1.append(first.weight.detach().flatten())
            aux_b1.append(first.bias.detach().flatten())
            aux_w2.append(last.weight.detach().flatten())
            aux_b2.append(last.bias.detach().flatten())
        self.weight, self.bias = parameter(weight), parameter(bias)
        self.has_genes = bool(self.direct)
        self.has_children = bool(child_mask.any().item())
        if self.has_genes:
            self.gene_weight, self.gene_bias = parameter(gene_weight), parameter(gene_bias)
        else:
            self.register_parameter("gene_weight", None)
            self.register_parameter("gene_bias", None)
        for name, value in [("gene_indices", gene_indices), ("child_indices", child_indices),
                            ("gene_mask", gene_mask), ("child_mask", child_mask)]:
            self.register_buffer(name, value, persistent=False)
        child_positions = child_mask.flatten().nonzero().flatten()
        self.register_buffer("child_positions", child_positions, persistent=False)
        self.register_buffer("child_sources", child_indices.flatten()[child_positions], persistent=False)
        norm = normals[0]
        if any((x.eps, x.momentum, x.affine, x.track_running_stats)
               != (norm.eps, norm.momentum, norm.affine, norm.track_running_stats) for x in normals):
            raise ValueError("Grouped BatchNorm layers must share their configuration")
        self.norm = nn.BatchNorm1d(count * self.hidden, eps=norm.eps, momentum=norm.momentum,
                                  affine=norm.affine, track_running_stats=norm.track_running_stats,
                                  device=exemplar.device, dtype=exemplar.dtype)
        with torch.no_grad():
            if norm.affine:
                self.norm.weight.copy_(torch.cat([x.weight for x in normals]))
                self.norm.bias.copy_(torch.cat([x.bias for x in normals]))
            if norm.track_running_stats:
                if any(x.num_batches_tracked.item() != norm.num_batches_tracked.item() for x in normals):
                    raise ValueError("Grouped BatchNorm layers have different update counts")
                self.norm.running_mean.copy_(torch.cat([x.running_mean for x in normals]))
                self.norm.running_var.copy_(torch.cat([x.running_var for x in normals]))
                self.norm.num_batches_tracked.copy_(norm.num_batches_tracked)
        self.aux_weight1 = parameter(torch.stack(aux_w1))
        self.aux_bias1 = parameter(torch.cat(aux_b1))
        self.aux_weight2 = parameter(torch.cat(aux_w2))
        self.aux_bias2 = parameter(torch.cat(aux_b2))

    def forward(self, genes, previous):
        batch, count = genes.shape[0], len(self.terms)
        inputs = None
        if self.has_genes:
            selected = genes.index_select(1, self.gene_indices.flatten()).reshape(batch, count, self.width)
            inputs = (selected * self.gene_weight + self.gene_bias) * self.gene_mask
        if self.has_children:
            selected = previous.index_select(1, self.child_sources)
            children = genes.new_zeros(batch, count * self.width)
            children.index_copy_(1, self.child_positions, selected)
            children = children.reshape(batch, count, self.width)
            inputs = children if inputs is None else inputs + children
        linear = torch.bmm(inputs.transpose(0, 1), self.weight.transpose(1, 2)).transpose(0, 1) + self.bias
        hidden = self.norm(torch.tanh(linear).reshape(batch, -1)).reshape(batch, count, self.hidden)
        auxiliary = torch.tanh((hidden * self.aux_weight1).sum(-1) + self.aux_bias1)
        auxiliary = auxiliary * self.aux_weight2 + self.aux_bias2
        return hidden, auxiliary

    def export(self, gradients=False):
        def value(tensor):
            source = tensor.grad if gradients else tensor
            return torch.zeros_like(tensor) if source is None else source.detach()
        result = {}
        for index, term in enumerate(self.terms):
            prefix = term + "_"
            result[prefix + "linear_layer.weight"] = value(self.weight)[index, :, :self.actual_widths[index]].clone()
            result[prefix + "linear_layer.bias"] = value(self.bias)[index].clone()
            for name in ("weight", "bias"):
                tensor = getattr(self.norm, name)
                if tensor is not None:
                    result[prefix + "batchnorm_layer." + name] = value(tensor).reshape(-1, self.hidden)[index].clone()
            if not gradients and self.norm.track_running_stats:
                for name in ("running_mean", "running_var"):
                    result[prefix + "batchnorm_layer." + name] = getattr(self.norm, name).reshape(-1, self.hidden)[index].detach().clone()
                result[prefix + "batchnorm_layer.num_batches_tracked"] = self.norm.num_batches_tracked.detach().clone()
            for suffix, tensor in [("aux_linear_layer1.weight", self.aux_weight1),
                                    ("aux_linear_layer1.bias", self.aux_bias1),
                                    ("aux_linear_layer2.weight", self.aux_weight2),
                                    ("aux_linear_layer2.bias", self.aux_bias2)]:
                shape = (1, self.hidden) if suffix == "aux_linear_layer1.weight" else (1, 1) if suffix.endswith("weight") else (1,)
                result[prefix + suffix] = value(tensor)[index].reshape(shape).clone()
            if term in self.direct:
                genes, start = self.direct[term]
                result[prefix + "direct_gene_layer.weight"] = (genes, value(self.gene_weight)[index, start:start + len(genes)].clone())
                result[prefix + "direct_gene_layer.bias"] = value(self.gene_bias)[index, start:start + len(genes)].clone()
        return result


class PackedDrugCell(nn.Module):
    """A statically packed execution of an already initialized DrugCell model."""

    def __init__(self, reference):
        super().__init__()
        self.root, self.gene_dim, self.drug_dim = reference.root, reference.gene_dim, reference.drug_dim
        self.hidden = reference.num_hiddens_genotype
        self.drug_widths = list(reference.num_hiddens_drug)
        self.original_terms = [term for layer in reference.term_layer_list for term in layer]
        self.reference_parameter_count = sum(p.numel() for p in reference.parameters())
        self.reference_state_keys = list(reference.state_dict())
        specifications = []
        for layer in reference.term_layer_list:
            buckets = {}
            for term in layer:
                width = reference._modules[term + "_linear_layer"].in_features
                bucket = 1 << (width - 1).bit_length()
                buckets.setdefault(bucket, []).append(term)
            specifications.append(sorted(buckets.items()))
        terms = [term for layer in specifications for _, names in layer for term in names]
        self.positions = {term: index for index, term in enumerate(terms)}
        self.groups = nn.ModuleList()
        self.levels = []
        for layer in specifications:
            indices = []
            for width, names in layer:
                indices.append(len(self.groups))
                self.groups.append(TermGroup(reference, names, width, self.positions))
            self.levels.append(indices)
        self.drug_module_names = []
        for name, module in reference._modules.items():
            if name.startswith(("drug_", "final_")):
                self.add_module(name, copy.deepcopy(module))
                self.drug_module_names.append(name)
        self.train(reference.training)
        self.layout = {"format": "packed_drugcell_v1", "root": self.root,
                       "gene_dim": self.gene_dim, "drug_dim": self.drug_dim,
                       "groups": [{"terms": list(group.terms), "width": group.width,
                                   "direct": {term: [list(genes), start] for term, (genes, start) in group.direct.items()}}
                                  for group in self.groups],
                       "children": {term: list(reference.term_neighbor_map[term]) for term in self.original_terms}}

    def get_extra_state(self):
        return self.layout

    def set_extra_state(self, state):
        if state != self.layout:
            raise ValueError("Packed checkpoint belongs to a different GO graph or gene layout")

    def forward_training(self, inputs):
        genes, drug = inputs[:, :self.gene_dim], inputs[:, self.gene_dim:]
        levels, auxiliary = [], []
        for indices in self.levels:
            previous = torch.cat(levels, dim=1).flatten(1) if levels else None
            hidden = []
            for index in indices:
                states, heads = self.groups[index](genes, previous)
                hidden.append(states)
                auxiliary.append(heads)
            levels.append(torch.cat(hidden, dim=1))
        all_hidden = torch.cat(levels, dim=1)
        drug_hidden = []
        for index in range(1, len(self.drug_widths) + 1):
            drug = self._modules[f"drug_batchnorm_layer_{index}"](
                torch.tanh(self._modules[f"drug_linear_layer_{index}"](drug)))
            drug_hidden.append(drug)
            head = torch.tanh(self._modules[f"drug_aux_linear_layer1_{index}"](drug))
            auxiliary.append(self._modules[f"drug_aux_linear_layer2_{index}"](head))
        joined = torch.cat((all_hidden[:, self.positions[self.root]], drug), dim=1)
        final_hidden = self.final_batchnorm_layer(torch.tanh(self.final_linear_layer(joined)))
        final = self.final_linear_layer_output(torch.tanh(self.final_aux_linear_layer(final_hidden)))
        return final, torch.cat(auxiliary, dim=1), all_hidden, drug_hidden, final_hidden

    def forward(self, inputs):
        final, heads, states, drug_hidden, final_hidden = self.forward_training(inputs)
        aux = {term: heads[:, self.positions[term]:self.positions[term] + 1] for term in self.original_terms}
        hidden = {term: states[:, self.positions[term]] for term in self.original_terms}
        count = len(self.positions)
        for index, values in enumerate(drug_hidden, 1):
            aux[f"drug_{index}"] = heads[:, count + index - 1:count + index]
            hidden[f"drug_{index}"] = values
        aux["final"], hidden["final"] = final, final_hidden
        return aux, hidden

    def objective(self, inputs, target, auxiliary_weight=0.2):
        final, auxiliary, *_ = self.forward_training(inputs)
        loss = (final - target).square().mean()
        loss = loss + auxiliary_weight * (auxiliary - target).square().mean(0).sum()
        return final, loss

    def predict_final(self, inputs):
        return self.forward_training(inputs)[0]

    def export_upstream(self, gradients=False):
        result = {}
        for group in self.groups:
            for key, value in group.export(gradients).items():
                if isinstance(value, tuple):
                    genes, active = value
                    dense = active.new_zeros(len(genes), self.gene_dim)
                    dense[torch.arange(len(genes), device=active.device), torch.tensor(genes, device=active.device)] = active
                    value = dense
                result[key] = value
        for name in self.drug_module_names:
            module = self._modules[name]
            if gradients:
                values = {key: p.grad.detach().clone() if p.grad is not None else torch.zeros_like(p)
                          for key, p in module.named_parameters()}
            else:
                values = {key: value.detach().clone() for key, value in module.state_dict().items()}
            result.update({name + "." + key: value for key, value in values.items()})
        return result

    def statistics(self):
        return {"implementation": "level_batched_independent_GO_networks",
                "GO_terms": len(self.positions), "levels": len(self.levels), "batched_groups": len(self.groups),
                "reference_parameter_count": self.reference_parameter_count,
                "stored_parameter_count": sum(p.numel() for p in self.parameters()),
                "auxiliary_heads": len(self.positions) + len(self.drug_widths) + 1,
                "max_padding_ratio": 2, "dtype": str(next(self.parameters()).dtype),
                "checkpoint_format": "packed_state_dict; export_upstream reconstructs the original schema"}
