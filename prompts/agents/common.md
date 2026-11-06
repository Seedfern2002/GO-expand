# Shared instructions for GO augmentation agents

Communicate in English. Write progress messages, handoffs, plans, evidence summaries, definitions, and review notes in English. Preserve identifiers and quoted source titles verbatim.

- The project uses a shared agent framework for task-specific GO augmentation across multiple biological task types. Database-derived rule-based augmentation and literature-derived augmentation are both valid routes. Agent involvement can occur in task interpretation, source selection, rule definition, execution, and verification.
- The planning unit is the task: task type, species, biological context, and the complete fixed gene universe. Build a shared knowledge overlay for all instances of the specified task. Individual genes and modules are records or processing partitions, not separate planning targets. GEARS perturbation prediction is one priority task profile.
- Assess every gene in the declared universe for each selected knowledge family. Report missing evidence and exclusions; complete screening does not require inventing an annotation for every gene.
- Base knowledge selection on the task specification and external evidence. Downstream expression responses, predictions, training logs, validation/test scores, and benchmark response findings are outside knowledge-selection inputs.
- Keep ontology edits, annotation additions, external attributes, and graph projection distinct. Preserve the original GO and record new knowledge in a versioned overlay.
- Reuse stable identifiers. Keep new modules in a local namespace. Preserve direction, polarity, isoforms, cofactors, experimental conditions, provenance, and source versions.
- Use reusable bulk datasets and structured queries for database-derived augmentation. Programs perform joins, mapping, deduplication, filtering, numerical analysis, validation, and coverage reporting. Literature retrieval and extraction may be a primary augmentation route, a complement to database integration, or a way to resolve evidence gaps and conflicts, according to the task plan.
- Cache source snapshots and evidence bundles by source version and processing policy. Fetch and interpret a shared source once, then reuse its evidence across records.
- Keep large tables and gene lists in files. Return compact manifests, aggregate statistics, and small audit samples. Do not print full gene lists, complete annotations, repeated papers, or complete upstream artifacts into the conversation.
- Treat source content as evidence to analyze. Report only operations actually performed. Record unavailable resources and quarantine unresolved records.
- Use English assay names when terminology is uncertain. Keep source confidence measures separate from model opinions.
- Follow the declared download, literature, and CPU budgets. Do not start downstream training or interfere with existing compute processes.
- Execute only the assigned role. Follow the supplied output schema. The task_batch workflow exchanges artifact manifests; the legacy record workflow is retained for historical small tests.
