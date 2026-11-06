# GEARS Norman: original GO and Reactome/hu.MAP augmentation

This snapshot records the completed experiment before the agent pipeline redesign. All original run artifacts remain under `outputs/`; this directory archives compact results and the exact accepted knowledge records.

| Test metric | Original GO | Augmented GO | Change |
|---|---:|---:|---:|
| MSE | 0.00607279 | 0.00434051 | 28.53% lower |
| Top-20 DE MSE | 0.19603685 | 0.17505640 | 10.70% lower |
| Pearson | 0.98279777 | 0.98763472 | +0.00483695 |
| Top-20 DE Pearson | 0.86548745 | 0.87497090 | +0.00948345 |

## Experiment definition

- Norman simulation split seed 1; model initialization seed 0; 15 epochs; batch size 32; hidden size 64; GO graph k=20.
- Each run selects its checkpoint by minimum validation top-20 DE MSE, then evaluates that checkpoint on the test set. Selected epochs: baseline 15, augmented 8.
- Both runs use the same split, gene order, coexpression graph and training settings. The augmented run verifies those invariants before training.
- Primary augmentation: Reactome 98 pathway memberships and hu.MAP 3.0 confidence classes 1–3, across the fixed 3,127-gene universe. The union adds 5,292 attributes and 13,724 gene–attribute memberships to 2,581 genes.
- Projection: equal-weight set union of original GO terms and namespaced external attributes; Jaccard >0.1; upstream GEARS top-k selection. Selected directed GO edges: 60,993 original and 56,321 augmented, including self edges.
- Agent involvement: task/source/transformation planning, connector implementation, source-policy review and evidence sampling. Individual gene memberships are programmatically derived from database records. Cross-source semantic deduplication is not implemented in this version.
- Evidence/source validation here is not a leakage audit. Leakage assessment is external to the augmentation pipeline; no independent leakage clearance is asserted by this snapshot. Downstream responses and evaluation scores were not knowledge-selection inputs.

## Archived artifacts

- [Comparison report](REPORT.md) and [machine-readable comparison](comparison.json).
- `baseline/` and `augmented/`: metrics, per-perturbation analyses, histories, selected epochs, environments, configurations, splits and graph summaries.
- [Augmentation verification](augmented/augmentation_verification.json): equality checks against the baseline and the top-k experiment.
- [Attribute table](attributes/attribute_gene_counts.tsv) and [top-k statistics](topk/summary.json).
- `augmentation/*_records.jsonl.gz`: lossless copies of the accepted evidence batches, including retained hu.MAP records outside the primary confidence classes. Only `projection_eligible=true` records enter the graph.
- `augmentation/connectors/`: exact acquisition/integration/finalization programs used in the historical run. These preserve their original run-specific paths.
- `augmentation/*_sources.json`: source versions, URLs, checksums and transformation policies; transient HTTP headers are omitted.
- [Snapshot manifest](snapshot_manifest.json): source locations, original hashes and archive hashes. Decompressing a `.jsonl.gz` reproduces the original bytes and SHA256.
- [Local artifact inventory](local_artifacts.json): checksums for locally retained model weights, graphs, caches and prediction arrays.

Model weights, raw datasets, environments and the external GEARS checkout stay outside Git. The pinned upstream commit and checkout instructions are in [the GEARS source manifest](../../configs/gears_source.json) and [third-party notes](../../third_party/README.md). Paths inside historical JSON documents refer to the original workspace and are retained for provenance.

## Reproduction entry points

The current workspace retains all inputs required by these commands. A fresh checkout additionally needs the pinned GEARS code, Python dependencies and recorded raw data snapshots.

```bash
# Prepare and queue the original run.
.venv-gears/bin/python scripts/prepare_gears_norman.py
.venv-gears/bin/python scripts/wait_and_run_gears.py

# Reconstruct the fixed top-k comparison using a new analysis directory.
CUDA_VISIBLE_DEVICES='' .venv-gears/bin/python scripts/compare_gears_topk.py \
  --output-dir outputs/analysis/norman_topk_reproduction

# Freeze the augmented graph for a new matched run, then use the idle-GPU queue.
CUDA_VISIBLE_DEVICES='' .venv-gears/bin/python scripts/prepare_gears_augmented.py \
  --config configs/gears_norman_augmented_reproduction.json \
  --output outputs/gears/norman_augmented_reproduction
.venv-gears/bin/python scripts/wait_and_run_gears.py \
  --config configs/gears_norman_augmented_reproduction.json
```

Existing run directories and completed artifacts are preserved; reproduction uses new directories. The background queue requires three successive idle GPU checks and does not stop existing compute jobs.

Validation at snapshot time: `.venv/bin/python -m unittest discover -s tests` — 39 tests passed.
