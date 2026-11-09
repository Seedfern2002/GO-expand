Execute the task-wide plan within the private workspace. The task inputs are in inputs/. Store acquired source snapshots, paper texts, programs and evidence under acquisition/. Store batch files and screening reports under batches/.

Use bulk sources and shared paper bundles. Read each paper once and extract all supported task-relevant associations. Use standard-library Python programs and the provided importer: python3 pipeline/import_batch.py. Save originals with hashes and reproducible source locators. Resolve source identifiers against the fixed gene universe; map aliases only with explicit evidence. Quarantine unresolved/unsupported rows.

For declared literature targets, use batch metadata discovery, stable paper identities and reusable acquisition programs. Maintain a deduplicated paper-screening ledger with topic, DOI/PMID/PMCID, access scope, inspected scientific sections, screening decision and evidence yield. Distinguish discovered papers, downloaded documents, inspected abstracts, inspected full texts and papers supporting accepted claims. Continue across topic partitions until the inspected-paper and full-text targets are met, or document the reached resource limit or exhausted relevant accessible pool. Update compact progress summaries after each paper bundle.

Extract supported functional annotations and pathway/complex memberships together with typed regulatory mechanisms. Reuse one saved paper across all supported task-relevant claims. Keep large tables, complete batches and repeated paper text in files; use compact manifests, targeted passages and small examples in tool output.

Use pipeline/fetch.py for downloads so aggregate downloaded bytes are counted. Use system Python, its standard library and the available system tools. Network evidence can also be discovered through web search; record the task-wide query/open counts and source inventory.

Process every selected database source to completion and publish all records satisfying the declared source, evidence, mapping and gene-universe policies. Retain each gene's full eligible attribute set. max_candidate_records counts literature_extracted candidates exclusively. Review sampling governs audit inspection. Report database counts before and after each eligibility filter, with explicit exclusion reasons. A reached resource limit requires partial coverage, its reason and the last processed position.

Published batches contain validated records. Each batch screens the complete gene universe against its imported evidence; mark unmatched genes as lacking a match in that source. Record all planned directions as covered, partial, no_evidence or pending. Unknown study provenance is UNRESOLVED:<source>. Literal text support is required for literature claims. Preserve database_record, experimental_result, interpretation and hypothesis separately.

Return paths/checksums and coverage manifests in schema 3.0 for artifacts saved and checked inside /workspace.
