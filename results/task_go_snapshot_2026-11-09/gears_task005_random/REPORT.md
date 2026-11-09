# Matched GEARS graph experiments

State: complete.

Test metrics from the model selected by minimum validation MSE_DE in each run.
All runs use split seed 1, model seed 0 and the same 15-epoch training recipe.

| Run | State | MSE ↓ | MSE_DE ↓ | Pearson ↑ | Pearson_DE ↑ |
|---|---|---:|---:|---:|---:|
| Original GO | complete | 0.00607279 | 0.19603685 | 0.98279777 | 0.86548745 |
| Literature-expanded GO (task005) | complete | 0.00430260 | 0.19248076 | 0.98764493 | 0.87016158 |
| Random GO graph (seed 0) | complete | 0.00699059 | 0.23546000 | 0.97948340 | 0.83201023 |

Original GO: `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_baseline_seed1_retry1`
Literature-expanded GO (task005): `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_task005_seed1`
Random GO graph (seed 0): `/home/yxcheng/project/GO_enrichment/outputs/gears/norman_random_go_seed1`
