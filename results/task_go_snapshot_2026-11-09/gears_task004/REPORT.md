# Matched GEARS GO comparison

State: complete.

Augmentation: Frozen k562_task_only_004 gene_attributes product with original GO and accepted GO/external memberships, using the matched GEARS Jaccard graph.
Training settings, split, model seed, gene order and coexpression graph are checked against the baseline.
Checkpoint selection uses validation mse_de. The table contains test metrics.

| Metric | Baseline | Augmented | Augmented - baseline | Error reduction (%) |
|---|---:|---:|---:|---:|
| mse | 0.00607279 | 0.00405861 | -0.00201418 | 33.16729057 |
| mse_de | 0.19603685 | 0.18285038 | -0.01318647 | 6.72652615 |
| pearson | 0.98279777 | 0.98813758 | 0.00533981 | — |
| pearson_de | 0.86548745 | 0.87129810 | 0.00581065 | — |

MSE metrics: lower is better. Pearson metrics: higher is better.

Baseline: `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_baseline_seed1_retry1`
Augmented: `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_task004_seed1`
