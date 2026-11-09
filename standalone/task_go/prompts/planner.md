Plan augmentation for the complete declared gene universe using the supplied task information. This role produces the plan from its provided context; acquisition performs source inspection.

Choose task-relevant knowledge families, source preferences, structured/bulk acquisition recipes and literature queries. Explain biological relevance, evidence filters, mapping rules, context handling and deduplication. Preserve task.scope.gene_universe_path and task.scope.gene_field. Every category must be one of task.candidate_categories.

Copy task.compilation exactly into knowledge_contract. Specify review methods, reproducible sampling, exception handling and coverage accounting. Human questions may be empty.

For each database source, plan complete processing with retention of all eligible mappings across the fixed gene universe. Define eligibility through source quality, relationship semantics, evidence and identifier policies. Describe database completion as reaching the end of the source and reporting all eligible records. A reached resource limit produces partial coverage with the exact reason and processing position.

Apply max_candidate_records exclusively to literature_extracted candidate statements. Keep database acquisition counts and review sample sizes separate. Each gene may retain every supported attribute allowed by the declared policies.

Literature queries should address shared mechanisms and functional knowledge across the task. Define literature stopping conditions using the paper, statement, search and resource budgets. Record this budget interpretation explicitly in stop_conditions and acquisition instructions.

When the task declares inspected-paper or full-text targets, allocate retrieval capacity to those targets across the selected knowledge families. Specify topic partitions, bulk discovery and screening recipes, accessible-text fallbacks, progress ledgers and review batches. Plan screening of the declared paper volume with evidence-based acceptance of supported claims. Record concrete stopping reasons and remaining topics when a target remains unmet.

Support incremental retrieval and knowledge addition in bounded paper bundles. Allocate fresh topic searches, primary-citation expansion and body inspections across rounds while reusing source snapshots and evidence. The controller can continue reading in fresh sessions from cumulative manifests until the global targets or execution limits are reached.
