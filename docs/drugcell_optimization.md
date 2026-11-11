# Packed DrugCell execution

The active optimized experiment is
[`comparison_002_packed`](../outputs/drugcell/comparison_002_packed/REPORT.md).
The user requested stopping the original experiment; its checkpoints, histories
and last report remain under `comparison_001`. Both optimized arms restart from
model seed 0 with the same frozen inputs and 300-epoch protocol.

`scripts/run_drugcell_comparison_optimized.py` reserves an idle GPU, checks both
full ontologies on CUDA, then starts training while holding the same reservation.
The bundle and both ontology hashes were matched before launch. CUDA receipts
are stored in `comparison_002_packed/preflight/` and `cuda_preflight.json`.

The optimized runtime preserves DrugCell's fixed GO graph, per-subsystem width,
independent parameters, BatchNorm channels, auxiliary heads, ordered batches,
FP32 arithmetic policy and Adam settings. Existing experiment snapshots and
running training processes retain their original implementation.

## Implementation

`scripts/drugcell_packed.py` groups terms by GO level and power-of-two input-width
bucket. Each group uses batched matrix multiplication and a BatchNorm channel
block for each term. Child features follow the released hierarchy and child
ordering. Each term keeps its own auxiliary head. Input padding has zero-valued
features and fixed zero-effect connections.

The direct-gene layer has one allowed input per output row. The packed model
stores those active weights and biases, retaining their original initialization.
Off-mask weights and Adam states stay structurally zero in the released model,
so their dense storage and repeated gradient masking are omitted. A packed
checkpoint can be exported to the original model schema with `export_upstream()`.

`scripts/run_drugcell_optimized.py` is a separate, versioned training entry point.
It accumulates training predictions and logging values on the device and transfers
them at epoch boundaries. Auxiliary losses are computed together, with the same
per-head weighting. Validation Pearson selects a single best checkpoint; the
selected model is evaluated on the held-out test fold afterward.

| Ontology | Terms | Batched groups | Released stored parameters | Packed stored parameters |
|---|---:|---:|---:|---:|
| Pruned baseline | 2,086 | 33 | 180,536,461 | 1,175,698 |
| Frozen augmentation | 8,693 | 56 | 238,089,175 | 2,339,183 |

These storage counts describe execution representations of the same masked
networks. Each term retains six hidden channels. Parameter packing and batched
reductions can change FP32 rounding; numerical comparisons use declared
tolerances and both experimental arms use the same implementation.

## Verification

Tests cover FP64/FP32 forward values, input and parameter gradients, three Adam
updates, independent BatchNorm statistics, compact checkpoint reload and original
checkpoint export. A training-loop regression verifies validation checkpoint
selection and deferred test evaluation.

Full baseline and augmented models also pass training/evaluation smoke checks
against frozen source/data manifests. Their receipts are under
`outputs/drugcell/optimization_001/cpu_smoke_baseline_v2/` and
`outputs/drugcell/optimization_001/cpu_smoke_augmented/`. Smoke checks explicitly
use 256 observations per partition, batch size 32 and three epochs.

The benchmark compares the prior `masked_gather` implementation with packed
execution on the same frozen ontology, initialization, training batch and Adam
settings. It verifies every parameter gradient and reconstructed state after
one Adam update, using `atol=1e-6, rtol=1e-4`; prediction and loss checks are
recorded separately. Full-ontology CPU checks passed for both arms.

At batch size 128, two measured steps after warmup on two CPU threads:

| Ontology | Prior seconds/step | Packed seconds/step | Speedup |
|---|---:|---:|---:|
| Baseline | 2.334 | 0.189 | 12.34× |
| Augmented | 7.696 | 0.650 | 11.83× |

These are CPU measurements excluding model construction, checkpoint I/O and test
evaluation. GPU measurements use a separate reserved-idle GPU and the training
batch size of 5,000. Benchmark receipts and source hashes are retained alongside
the results.

## Commands

Run the packed model with the existing frozen inputs and a fresh output directory:

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv-gears/bin/python -m unittest discover -s tests -p 'test_drugcell_packed.py' -v

.venv-gears/bin/python scripts/run_drugcell_optimized.py \
  --config outputs/drugcell/comparison_001/config.json --fold 0 \
  --ontology outputs/drugcell/comparison_001/baseline/drugcell_ont.txt \
  --output outputs/drugcell/packed_baseline_fold0 --device cuda
```

The CUDA command is a worker entry point; its caller acquires an unoccupied GPU
through the shared queue and holds the reservation until the worker exits.

Prepare a small portable benchmark bundle, then queue GPU measurements:

```bash
.venv-gears/bin/python scripts/benchmark_drugcell_optimized.py \
  --prepare-config outputs/drugcell/comparison_001/config.json \
  --bundle outputs/drugcell/optimization_benchmark_bundle --batch-size 5000

.venv-gears/bin/python scripts/benchmark_drugcell_optimized.py \
  --bundle outputs/drugcell/optimization_benchmark_bundle \
  --output outputs/drugcell/optimization_gpu_baseline \
  --arm baseline --batch-size 5000 --device cuda --queue
```

Use `--arm augmented` for the second frozen ontology. The bundle contains pinned
code, both frozen ontologies, the gene map, fixed training observations and SHA256
checksums. Credentials remain outside source code and experiment artifacts.
