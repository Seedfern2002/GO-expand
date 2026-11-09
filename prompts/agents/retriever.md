# Evidence acquisition and integration

Input: a task card and a selected task-wide plan.
Output: batch manifests for task_batch, or candidate records for the legacy record workflow.

1. Execute the task's chosen database, literature, or combined augmentation route. Acquire each approved source snapshot or literature evidence bundle once. Use bulk downloads, local indexes, structured queries, and grouped paper retrieval as appropriate.
2. Use reusable programs to map identifiers, expand source-defined memberships, apply declared filters, preserve context, and deduplicate evidence. Screen the complete gene universe.
3. Record source release, URI, checksum, transformation version, mapping decisions, and row-level source locators. Preserve database-derived, literature-extracted, and analysis-inferred evidence as distinct classes.
4. Store normalized records, provenance, validation reports, and coverage reports outside the LLM context. Preserve source-level evidence once and refer to it from the rows.
5. Report how many universe genes were screened, annotated, excluded, ambiguous, and unsupported. The complete fixed gene universe is eligible; also report perturbation-target coverage.
6. Literature-derived augmentation can be a primary route or complement database integration. Group retrieval by the plan's biological knowledge needs, shared pathways, complexes, mechanisms, or sources; reuse evidence bundles across supported associations.
7. For task_batch, return paths, hashes, source versions, and plan-item coverage. Counts must come from program-generated reports; store row records in files.
8. If a required connector is unavailable, identify it and return partial/pending coverage. Report artifacts and processing steps after creation and verification.

Keep official GO and existing task baseline inputs immutable. Organize acquisition across the full task universe and reuse common processing and evidence.

For task_knowledge, use scripts/import_knowledge_batch.py for typed records, legacy membership sources, or paper bundles. Process database sources completely and retain every mapping passing the declared evidence, identifier and gene-universe policies. Record source totals, filter counts and exclusion reasons. max_candidate_records counts literature_extracted candidates exclusively; review sampling controls audit inspection. Report reached resource limits with partial coverage and the last processed position. Cache each paper once; extract supported task-relevant statements within the literature budget, with exact quotations, original source conditions and study identifiers. Distinguish experimental results, interpretation and hypothesis. Resolve existing GO identifiers when supported; treat mentioned genes as the scope of the paper's reported observations and use additional evidence for broader membership. Unknown study provenance uses UNRESOLVED:<source>. Publish rows passing shared validation and save excluded records separately.
