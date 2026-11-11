# Standalone task-specific GO augmentation

This directory is a self-contained, standard-library Python application. It can be copied out of its containing repository and run independently. It does not import repository modules or read repository documentation.

Inputs are a scientific task card, a fixed gene universe, original functional annotations, and an optional ontology snapshot. The launcher accepts only declared task fields. Gene metadata is reduced to identifiers; annotation inputs are restricted to that universe. The launcher copies those inputs into a new private workspace using generic filenames. Runtime/model settings are separate from the scientific task.

The Linux Codex backend uses bubblewrap to expose only system libraries, this workspace, the selected executable and an isolated runtime home. The existing login file is mounted for the backend. Project directories, user session histories, user configuration, model weights, predictions and prior experiment reports are not mounted. Planner shell/web tools are disabled. Each stage starts a new ephemeral session; acquisition/review can use tools only against the isolated filesystem and external sources. The launch receipt stays outside the agent workspace.

```bash
python3 launch.py --task task.json --genes genes.json --gene-field genes \
  --annotations annotations.json --ontology go.obo \
  --run-dir /tmp/task-go-runs/example --codex-bin /path/to/codex \
  --model MODEL_NAME --reasoning-effort medium
```

The scientific task fields are task_id, task_description, organism, biological_context, candidate_categories, knowledge_requirements, retrieval_budget, projection_policy, and optional source_candidates. Biological context contains only cell_type, tissue, perturbation and condition. The launcher generates task-local input paths, compilation policy and initial knowledge summaries. JSON annotation mappings are portable; pickle input is accepted only as a trusted local import format and is converted before entering the runtime.

The max_candidate_records budget applies exclusively to literature_extracted candidate statements. Database sources are processed completely, retaining all mappings that satisfy the declared evidence and identifier policies across the fixed gene universe. Review sample sizes govern audit inspection. The task card records this interpretation in retrieval_budget.record_budget_scope; all roles receive the same budget rule.

Outputs under workspace/ include task.json, inputs/manifest.json, stages/*/{prompt.md,events.jsonl,result.json,execution.json}, and the final knowledge/ freeze. All agent prompts and artifacts are English. Failed runs preserve their status and logs. Completed products are immutable. The pipeline emits typed statements and per-gene attributes; downstream model integration and evaluation are separate consumers. Leakage auditing is external.

`--prepare-only` produces an inspectable task workspace without starting a model. No process outside this newly launched run is stopped or modified.

Multi-round acquisition is enabled with --retrieval-rounds 60 --papers-per-round 50 --full-texts-per-round 30. Each round starts a fresh acquisition session, publishes incremental batches and returns a paper-inspection ledger with source-bound passages and cumulative usage. The controller checks the passages against saved text and command-tool returns, deduplicates DOI/PMID/PMCID identities, merges active batches and continues toward the task's global reading targets. Three consecutive rounds without reading progress or valid results stop with an explicit gap status. Reading targets, resource ceilings and the maximum number of rounds determine controller termination. Search and source counters are reported by acquisition and checked against recorded lower bounds; download bytes and candidate files receive independent checks. Final evidence review and compilation follow the acquisition rounds.

Progress is available in rounds/progress.json; round prompts and events are under rounds/retriever_NNN/. rounds/active_candidates.json and rounds/paper_inspections.jsonl hold the cumulative working knowledge and reading ledger. Each round can preview its interface using pipeline/check_round.py.

## Planner-directed reading and knowledge additions

Set `retrieval_budget.reading_mode` to `planner_adaptive`. The example task card is `configs/agent_tasks/perturbation_task_only_adaptive.json` in the containing repository. Its paper, body-reading and download budgets are resource ceilings. The Planner chooses `reading_plan.initial_papers`, `batch_size`, `max_full_text_papers`, `topic_questions` and `stop_criteria` within those ceilings. The launcher defaults to 60 retrieval rounds for this mode. Existing task cards retain fixed-target behavior.

Each retrieval round is one fresh conversation handling a coherent small batch of papers. Abstracts provide the initial scientific evidence. Body sections and supplementary tables are read for explicit information needs, including large-scale screens, complex composition and functional atlases. Each full-text inspection records `body_reading_request` with `abstract_assessment`, `question` and `reason_code`. The reading ledger records the actual passages inspected.

Every round returns `reading_decision`: `decision`, `reason`, `stop_code`, `next_batch_size` and `unresolved_questions`. A coverage stop requires the initial reading volume and resolved questions; an exhausted candidate pool is recorded as a coverage gap. Resource ceilings, the round limit and stalled-round handling also bound execution. These are recorded scientific judgments plus controller checks; topic completeness is assessed by the agents and final Reviewer.

The controller builds `rounds/knowledge_context_NNN.sqlite` from the original annotation/ontology inputs and cumulative candidate batches. The focused `skills/add-go-knowledge/SKILL.md` provides tools to query gene attributes, incoming/outgoing typed links, definitions, EXACT synonyms, ontology edges and candidate/reviewed state. Querying names produces identity candidates for biological review. New concepts require definitions and types; matching names require an explicit distinction or concept reuse.

`knowledge_ops.py propose` produces candidate records and an action ledger: reuse an assertion with additional evidence, add a contextual assertion, add an association, propose a concept, or record identical evidence as already supported. It updates the current round index for subsequent papers. The next round reconstructs its index from published batches, so publish emitted records through `import_batch.py`. The Reviewer approves evidence and identity resolutions; compilation freezes the resulting product. See `FORMAT.md` for the record interface.

--paper-cache-workspace accepts a prior task workspace containing acquisition/papers/manifest.jsonl. The launcher copies whitelisted external-paper metadata and referenced scientific texts into inputs/paper_cache/ using generic filenames. Plans, agent logs, previous screening decisions, knowledge products and downstream artifacts remain outside the imported cache. These papers receive new inspection records in the new run.

## Graph-aware module placement

`launch_modules.py` accepts the same scientific task inputs plus an original functional graph, a source module catalog, pinned placement evidence, processing batches and a source-file manifest. Modules are editing units within one shared fixed-gene graph. A coherent batch is inspected jointly; subsequent batches read the committed graph revision.

```bash
python3 launch_modules.py --task task.json --genes genes.json \
  --annotations annotations.json --ontology go.obo --graph baseline_graph.json \
  --modules modules.json --evidence placement_evidence.json \
  --batches module_batches.json --sources sources.json \
  --run-dir /path/to/new_run --codex-bin /path/to/codex --model MODEL_NAME
```

`pipeline/graph_ops.py` queries current graph neighborhoods, module definitions, source-native relationships, source GO annotations and candidate locations. Retrieval candidates use source annotations, labels and gene-set overlap. The editor chooses concept reuse, addition or deferral and proposes typed, evidence-bound edges. An independent reviewer decides every module before the controller validates and commits the accepted transaction. Native pathway hierarchy, ontology relations, process participation, model aggregation and associative/regulatory links retain distinct labels.

The launcher uses the outer task-only bubblewrap environment as the execution boundary and mounts `inputs/` and `pipeline/` read-only. Codex command tools execute within that externally isolated environment. The controller checks input hashes and the current graph revision before each commit. It validates fixed gene coverage, connected model hierarchy, cycles, duplicate message-flow edges, evidence references and review dependencies. Original graph rows remain in the resulting product.

`batches/BATCH/` contains context packets, prompts, event logs, review decisions, accepted patches and validation receipts. `graph/current.json` is the current shared graph. `timing.json` and `REPORT.md` report editor/reviewer wall times and observed throughput. `knowledge_graph/` contains the frozen typed graph and lineage manifest. A processing pilot identifies its modules and remaining catalog size explicitly; its timing estimate assumes the measured batch size, source mix and sequential editor/reviewer workflow.

## Group recipe execution

`launch_modules.py --workflow module_recipes` runs agent-selected integration groups followed by deterministic native-hierarchy and membership expansion. The launcher's scientific inputs are identical to module placement: task, fixed genes, annotations, original graph, source catalog, evidence, source snapshots and processing batches. The editor chooses group scope, shared anchors, concept reuse and individual exceptions. The independent reviewer sees the full expansion and can issue per-module exceptions to its group verdicts.

`graph_ops.py --concepts GO:ID GO:OTHER` retrieves multiple definitions and neighborhoods in one query. `--labels "phrase" "other phrase"` supports multiple literal label searches; `--offset` paginates matches and `--neighbor-offset` paginates parent/child neighborhoods. Source-annotated concepts in the initial packet are entry points for further graph exploration.

The workspace saves recipes, compiled transactions, expansion receipts, complete review coverage and execution accounting. Frozen graph manifests include recipe and expansion hashes. `efficiency.json` records invocation counts, tool calls, context bytes and stage timings. These counters describe the graph integration stage; source acquisition remains a separate measurement.
