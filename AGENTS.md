# Project agent conventions

- The project studies agent-driven, task-specific GO augmentation as a general framework across multiple biological tasks. Both rule-based integration of omics/biological databases and literature-derived augmentation are valid routes. Agent decisions may concern task interpretation, source selection, rules, orchestration, and verification; per-gene LLM editing is not a requirement.
- The research emphasis is biological effectiveness, scale, and generality across task types, with a major Nature Portfolio journal as the publication target. GEARS/virtual-cell perturbation prediction is a priority application within this broader scope.
- Author research-agent prompts and artifacts in English, letting the prompt language establish communication naturally. Omit explicit language instructions within agent prompts. User-facing discussion follows the user's language.
- Use direct, affirmative wording in user-facing discussion and agent prompts. State conclusions, evidence, and scope explicitly; minimize repeated negative contrasts such as “not X” or “不是……”.
- Provide research recommendations and next-step proposals only when the user asks for them, including in analytical documents.
- Plan augmentation for the complete task and fixed gene universe. Use one shared knowledge overlay across perturbations. Genes, modules, and papers may be processing partitions or evidence units.
- Prefer bulk source integration, reusable programs, versioned caches, and compact artifact manifests. Keep large tables and gene lists outside model context.
- Base augmentation on task descriptions, biological context, and external evidence. Freeze the knowledge product before downstream evaluation. Responses, predictions, and evaluation scores are not knowledge-selection inputs.
- Leakage assessment is an independent audit outside the augmentation agent pipeline, for scientific review. Preserve lineage for that audit; do not treat ordinary gene–gene prior knowledge as leakage or claim clearance from structural/provenance checks.
- Preserve evidence type, source version, provenance, relationship semantics, polarity, and biological conditions. Keep original GO inputs and historical run artifacts immutable.
- Do not interrupt existing compute jobs. Downstream GPU work must use an unoccupied GPU under the project's queue policy.
