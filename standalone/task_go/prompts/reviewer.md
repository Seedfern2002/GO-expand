Review the current task's acquired evidence and transformation policies. Use source-policy review and seeded stratified samples for database batches, plus deterministic checks of all published rows. Independently inspect each accepted literature claim against the saved paper passages and their experimental context.

For planner_adaptive reading, review the Planner's reading_plan and the saved reading_decision reasons, biological coverage and evidence yield. Check that body inspections address recorded information needs or complete table-level knowledge opportunities, within the full-text ceiling. Review concept reuse, new-concept definitions, equivalence proposals and evidence additions from knowledge_ops.py; pending candidates remain evidence to review. Preserve narrower concepts, source conditions and disagreements when evaluating duplicate claims.

Check complete database processing and the retention of all eligible mappings. Verify pre-filter and post-filter counts, exclusion reasons and declared source coverage. max_candidate_records applies exclusively to literature_extracted candidates. Seeded samples select records for audit inspection; approved database files retain the complete set passing the declared policies and deterministic checks. Route an unexplained count-based truncation to a revised acquisition batch.

Write an audit JSON for each batch. Include review_method, sampled_record_ids, sampling_seed, reviewed_record_ids, findings and exclusions. Every approved literature claim must appear in reviewed_record_ids, and its batch review_method must be full_record_review. Database batches may use source_policy_and_sample.

Reconcile declared literature targets with the paper-screening ledger and saved scientific text. Independently recount unique inspected papers, full texts and evidence-contributing studies using DOI/PMID/PMCID identities. Record achieved topic coverage and concrete stopping reasons. Reuse each saved paper during claim-by-claim review and keep aggregate progress in compact manifests. Paper targets govern screening effort; evidence support governs claim acceptance.

Approved files must be exact subsets of acquisition records; corrected claims need a new acquisition revision and review. Accept requires evidence_checked and a hash-bound approved file. Other decisions have null approved paths/hashes.

Equivalent concepts may be mapped only with explicit evidence. A mapping file is an array of alias_id, canonical_id, relationship="equivalent", and evidence. Provide equivalences_path/equivalences_sha256, or null for both. Overlap and broader/narrower concepts remain distinct. Preserve different contexts, negation and conflicts.

Return the complete review object.
