# Evidence and terminology review

Input: the task card, plan, and acquisition manifests or legacy candidates.
Output: a batch review manifest for task_batch, or a record review for the legacy workflow.

For task_batch:
1. Review each source version and transformation policy: species, identifier mapping, relationship semantics, confidence filters, context handling, and projection eligibility.
2. Require deterministic validation of every processed row. Check the validation and coverage reports, provenance completeness, duplicate handling, invalid identifiers, and unresolved mappings.
3. Inspect reproducible stratified samples and flagged exceptions. Read a shared paper or database record once and reuse that evidence bundle. Preserve audit sample IDs and the sampling seed.
4. Distinguish source/policy approval plus sample auditing from full independent review of every record. Record the actual review method and audit coverage.
5. Route ambiguous statements, novel terms, conflicts, and experimental causal claims to explicit evidence review. Quarantine unresolved rows and record their disposition.
6. Accept the identified approved artifact, with its checksum and audit report. Rejected/deferred batches have null approved artifact fields. Route corrected or additional claims through acquisition and review.

For legacy record review:
- Cover every candidate ID exactly once. Check original evidence and terminology separately.
- Return accept, request_evidence, defer, or reject. Only accepted decisions contain a complete normalized_record.
- Explain changes to relationship or context and retain shared-study provenance.

Check assay, reagent, isoform, and cofactor names against the source. Preserve original assay names and all biological qualifiers when normalizing labels.

For task_knowledge, independently inspect source semantics and the controller's row validation. Accepted files must be exact subsets of acquisition records; revised claims return to a new acquisition artifact. Explicitly review every accepted literature claim, recording reviewed_record_ids in its audit report. Database source-policy/sample review remains valid for bulk records. Verify complete database processing, policy-based exclusion reasons and retention of all eligible mappings. max_candidate_records applies exclusively to literature_extracted candidates; database review samples determine inspection counts. Route unexplained count-based truncation to revised acquisition. Optionally emit an equivalence JSON array with alias_id, canonical_id, relationship="equivalent", and supporting evidence; provide its path/checksum in the review, or null for both fields. Preserve related, broader/narrower and overlapping concepts as distinct entries, together with all evidence for duplicate claims and common-study provenance. Leakage assessment is external to this workflow.
