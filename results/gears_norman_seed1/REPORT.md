# Matched GEARS GO comparison

State: complete.

The augmentation is the unchanged primary Reactome/hu.MAP attribute union used in the top-k analysis.
Training settings, split, model seed, gene order and coexpression graph are checked against the baseline.
Checkpoint selection uses validation mse_de. The table contains test metrics.

| Metric | Baseline | Augmented | Augmented - baseline | Error reduction (%) |
|---|---:|---:|---:|---:|
| mse | 0.00607279 | 0.00434051 | -0.00173228 | 28.52533954 |
| mse_de | 0.19603685 | 0.17505640 | -0.02098045 | 10.70229807 |
| pearson | 0.98279777 | 0.98763472 | 0.00483695 | — |
| pearson_de | 0.86548745 | 0.87497090 | 0.00948345 | — |

MSE metrics: lower is better. Pearson metrics: higher is better.

Baseline: `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_baseline_seed1_retry1`
Augmented: `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_augmented_seed1`
