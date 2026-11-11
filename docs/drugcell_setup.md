# DrugCell: augmentation on the released pruned GO

The separate packed runtime and numerical/performance checks are documented in
[DrugCell execution optimization](drugcell_optimization.md). Existing running
experiments keep their frozen code.

Initialized on 2026-11-09. The comparison is **released pruned GO versus that same pruned GO plus a frozen task-specific overlay**. Both arms use the fixed 3,008-gene universe, mutation features, compound fingerprints, response measurements, split assignments and training settings.

## Source and data

The [official DrugCell implementation](https://github.com/idekerlab/DrugCell) is checked out at `third_party/DrugCell`, commit `c507e1d821fac0201e42f831a1d772e7ef42b00e`. The source remains unchanged. Provenance and file hashes are in [drugcell_source.json](../configs/drugcell_source.json). The model and task were published in [Cancer Cell, 2020](https://doi.org/10.1016/j.ccell.2020.09.014).

The complete [official response table](https://drugcell.ucsd.edu/downloads/drugcell_all.txt) is downloaded to `data/raw/drugcell/v1/drugcell_all.txt`: 509,294 measurements, 484,325 distinct cell–drug pairs and 59,517,087 bytes. All response identifiers resolve to the released feature maps. The released maps contain 1,225 cells and 684 drugs; the response table covers 1,224 cells. The paper reports 1,235 cells; the manifests preserve these quantities separately. Repository example splits contain 10,000/1,000/1,000 observations and supply the CPU smoke batch.

The released pruned ontology contains:

| Object | Count |
|---|---:|
| Fixed genes | 3,008 |
| GO-BP terms | 2,086 |
| Parent–child edges | 3,167 |
| Direct gene–term memberships | 59,753 |
| Memberships after hierarchy propagation | 156,257 |

The root is `GO:0008150`; the hierarchy has six levels. `data/processed/drugcell/pruned_go/` stores a byte-identical ontology copy, gene list, direct annotations, propagated annotations, hierarchy and hashes. The released result of pruning is the experimental starting point.

## Matched evaluation inputs

`data/processed/drugcell/v1/` contains validated input manifests and five folds under `splits/fold_0` through `splits/fold_4`. Files are `train.tsv`, `validation.tsv` and `test.tsv`.

Each fold has 382,460 training pairs, 5,000 validation pairs and 96,865 test pairs. All measurements of a pair share a partition. The 24,969 additional measurements of repeated pairs are retained, so row counts vary slightly between folds. Every pair occurs in exactly one test fold. These are deterministic project-generated splits with seed 0; the exact published fold assignments are unavailable in the complete-table release.

The experiment contract is [drugcell_comparison.json](../configs/drugcell_comparison.json). Primary evaluation is test Spearman, with Pearson, MSE/RMSE and per-drug Spearman as additional summaries. Checkpoint selection uses validation data. Released defaults are hidden width 6 per GO term, drug widths 100/50/6, final width 6, batch size 5,000, Adam at 0.001 and up to 300 epochs.

The paper describes validation stopping; its exact patience rule is unspecified. Released training code runs the requested epochs and ranks checkpoints by validation Pearson. It saves every epoch; a full training runner needs bounded checkpoint retention. Each added term also adds an auxiliary head to the original `final MSE + 0.2 × sum(auxiliary MSE)` objective. Model parameters and head counts belong in the comparison record.

## Task-only augmentation and export

The scientific task card is [drug_response_task_only.json](../configs/agent_tasks/drug_response_task_only.json). It covers cancer-cell drug response across the full gene universe. The planner selects knowledge sources and evidence policies from this context. The prepared private workspace is `/tmp/task-go-runs/drug_response_task_only_001/workspace`.

Agent inputs comprise the scientific task, gene identifiers, the 156,257 propagated baseline memberships and the versioned GO OBO snapshot. Hierarchy propagation tells acquisition which functional knowledge is already represented. Raw response values, feature matrices, dataset folds and experiment reports stay in the evaluation workspace.

[drugcell_ontology.py](../scripts/drugcell_ontology.py) converts a frozen `gene_attributes.jsonl` product to the DrugCell ontology format:

- Preserve every original ontology row and gene identifier.
- Add memberships with novelty measured against hierarchy propagation. A membership already represented through a child has one inherited contribution.
- Place selected new GO-BP terms through compressed authoritative `is_a` paths to retained ancestors. The exporter inserts the selected terms and their connections.
- Place external modules through an explicit parent-map file. `edge_provenance.jsonl` distinguishes computational aggregation from GO `is_a` ancestry.
- Record excluded memberships and reasons, input hashes, term/edge counts and byte-preservation checks. Validate the connected DAG and nonempty gene coverage.

An external parent map has the form `{"EXTERNAL:R-HSA-123": ["GO:0007165"]}`. Its entries describe the actual placement chosen for each module. New term IDs follow the released model's module-naming constraints; incompatible IDs appear in the projection exclusions.

## Reproduction commands

Restore the pinned source and download the response table, using the source manifest's SHA256 to verify the download:

```bash
git clone https://github.com/idekerlab/DrugCell.git third_party/DrugCell
git -C third_party/DrugCell checkout c507e1d821fac0201e42f831a1d772e7ef42b00e
mkdir -p data/raw/drugcell/v1
curl --fail --location --output data/raw/drugcell/v1/drugcell_all.txt https://drugcell.ucsd.edu/downloads/drugcell_all.txt
```

Preparation commands require fresh output directories:

```bash
python3 scripts/prepare_drugcell_data.py
python3 scripts/drugcell_ontology.py prepare \
  --ontology third_party/DrugCell/data/drugcell_ont.txt \
  --gene-map third_party/DrugCell/data/gene2ind.txt \
  --output data/processed/drugcell/pruned_go
```

Prepare an isolated augmentation workspace with the task inputs:

```bash
python3 standalone/task_go/launch.py \
  --task configs/agent_tasks/drug_response_task_only.json \
  --genes data/processed/drugcell/pruned_go/genes.json \
  --annotations data/processed/drugcell/pruned_go/propagated_annotations.json \
  --ontology data/raw/go/2026-07-26/go-basic.obo \
  --run-dir /tmp/task-go-runs/drug_response_task_only_001 \
  --codex-bin /home/yxcheng/.vscode-server/extensions/openai.chatgpt-26.1021.22027-linux-x64/bin/linux-x86_64/codex \
  --model gpt-6.1-sol \
  --reasoning-effort medium --stage-timeout-seconds 43200 \
  --retrieval-rounds 6 --papers-per-round 50 --full-texts-per-round 30 \
  --prepare-only
```

The current environment reuses `.venv-gears` with verified versions in [drugcell_environment.json](../configs/drugcell_environment.json); package requirements are in [drugcell_requirements.txt](../configs/drugcell_requirements.txt). CPU verification:

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  .venv-gears/bin/python scripts/check_drugcell_runtime.py \
  --output outputs/drugcell/initialization/cpu_smoke.json
```

The executed check passed on the original 180,536,461-parameter model: forward pass, one masked-gradient Adam update, finite gradients, preserved masks and evaluation forward pass. The final verified receipt is `outputs/drugcell/initialization/cpu_smoke_verified.json`.

After knowledge compilation, export an augmented ontology to a fresh directory:

```bash
python3 scripts/drugcell_ontology.py augment \
  --ontology data/processed/drugcell/pruned_go/drugcell_ont.txt \
  --gene-map third_party/DrugCell/data/gene2ind.txt \
  --attributes /path/to/frozen/knowledge/gene_attributes.jsonl \
  --obo data/raw/go/2026-07-26/go-basic.obo \
  --output outputs/drugcell/augmentation_001
```

Add `--parents /path/to/parent_map.json` for external modules. GPU execution follows the shared project idle-GPU reservation policy.

## Executing the five-fold comparison

The task-only augmentation was launched on 2026-11-09 in `/tmp/task-go-runs/drug_response_task_only_001/workspace`. Its reviewed scientific inputs are preserved in `stages/planner/task.input.json` and `stages/planner/prompt.md`. The runtime permits up to six retrieval rounds, with cumulative targets of 100 primary papers and 60 full-text inspections. The controller stops when its targets are met or a declared stopping condition is reached.

The detached supervisor is running under `outputs/drugcell/comparison_001/`. It manages five baseline runs and five augmented runs, each using up to 300 epochs and model seed 0. Augmented runs become eligible after the knowledge product is frozen, copied with all referenced evidence inputs, and converted to a validated DrugCell hierarchy. Every run uses the copied data and split manifests as its fixed checksum contract.

- [Live comparison report](../outputs/drugcell/comparison_001/REPORT.md)
- [Supervisor status](../outputs/drugcell/comparison_001/run_status.json)
- [Frozen experiment configuration](../outputs/drugcell/comparison_001/config.json)
- [Code/input manifest](../outputs/drugcell/comparison_001/experiment_manifest.json)

The shared training implementation preserves the released model, all parameter tensors, masked initialization, optimizer and auxiliary loss. Its `masked_gather` forward computes the single allowed gene contribution in each masked input-layer row directly. Forward/gradient/Adam equivalence tests cover this optimization; both comparison arms use it. Each run retains its best validation-Pearson checkpoint and evaluates that checkpoint on the held-out test partition. Reports distinguish fold averages, paired fold changes and pooled held-out predictions.

External evidence-backed modules attach to the existing common root using an explicit computational-aggregation map. GO-BP additions use authoritative compressed `is_a` ancestry. The projection preserves the frozen knowledge product and records external identifier aliases, edge semantics, inherited membership overlaps and exclusions separately.

The supervisor allows at most two concurrent training runs and uses the shared project GPU reservations. Its launch receipt and log are `launch.json` and `supervisor.log`. An existing supervisor can be resumed with its frozen code:

```bash
python3 outputs/drugcell/comparison_001/code/run_drugcell_comparison.py \
  --resume --output outputs/drugcell/comparison_001 --max-concurrent 2
```

The supervisor lock admits one controller, and resumed controllers monitor already running children. Individual runs contain `progress.json`, `training_metrics.jsonl`, `best.pt`, `metrics.json`, `per_drug_metrics.tsv` and `predictions.tsv.gz` as their stages finish.
