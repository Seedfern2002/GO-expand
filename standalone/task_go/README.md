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

--paper-cache-workspace accepts a prior task workspace containing acquisition/papers/manifest.jsonl. The launcher copies whitelisted external-paper metadata and referenced scientific texts into inputs/paper_cache/ using generic filenames. Plans, agent logs, previous screening decisions, knowledge products and downstream artifacts remain outside the imported cache. These papers receive new inspection records in the new run.
