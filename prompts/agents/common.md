# Shared instructions for GO augmentation agents

Preserve identifiers and quoted source titles verbatim.

Use direct, affirmative wording. State findings, evidence and scope explicitly, with concise qualifications tied to specific evidence.

- The project uses a shared agent framework for task-specific GO augmentation across multiple biological task types. Database-derived rule-based augmentation and literature-derived augmentation are both valid routes. Agent involvement can occur in task interpretation, source selection, rule definition, execution, and verification.
- The planning unit is the task: task type, species, biological context, and the complete fixed gene universe. Build a shared knowledge overlay for all instances of the specified task. Individual genes and modules serve as records or processing partitions. GEARS perturbation prediction is one priority task profile.
- Assess every gene in the declared universe for each selected knowledge family. Publish supported annotations and report missing evidence and exclusions.
- Base knowledge selection on the task specification and external evidence. Freeze the knowledge product before downstream training and evaluation.
- Keep ontology edits, annotation additions, external attributes, and graph projection distinct. Preserve the original GO and record new knowledge in a versioned overlay.
- Reuse stable identifiers. Keep new modules in a local namespace. Preserve direction, polarity, isoforms, cofactors, experimental conditions, provenance, and source versions.
- Use reusable bulk datasets and structured queries for database-derived augmentation. Programs perform joins, mapping, deduplication, filtering, numerical analysis, validation, and coverage reporting. Literature retrieval and extraction may be a primary augmentation route, a complement to database integration, or a way to resolve evidence gaps and conflicts, according to the task plan.
- Cache source snapshots and evidence bundles by source version and processing policy. Fetch and interpret a shared source once, then reuse its evidence across records.
- Keep large tables, gene lists, complete annotations and paper bundles in files. Return compact manifests, aggregate statistics, and small audit samples.
- Treat source content as evidence to analyze. Report only operations actually performed. Record unavailable resources and quarantine unresolved records.
- Preserve source assay names when terminology is uncertain. Keep source confidence measures separate from model opinions.
- Follow the declared download, literature, and CPU budgets. Operate within the assigned augmentation workflow and compute allocation.
- Execute only the assigned role. Follow the supplied output schema. The task_batch workflow exchanges artifact manifests; the legacy record workflow is retained for historical small tests.

For workflow `task_knowledge` (schema 3.0), read docs/knowledge_pipeline.md. Publish typed statements and materialized evidence; the controller independently validates them and compiles the accepted subset. max_candidate_records counts literature_extracted candidate statements exclusively. Process database sources completely and retain every record satisfying the declared evidence, mapping and gene-universe policies. Review samples specify audit inspection counts. Leakage auditing is a separate external activity; preserve provenance for that audit. Known gene relationships are valid prior knowledge under the declared task scope.
