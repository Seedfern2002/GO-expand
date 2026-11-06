# Evidence and terminology review

Input: the task card, plan, and acquisition manifests or legacy candidates.
Output: a batch review manifest for task_batch, or a record review for the legacy workflow.

For task_batch:
1. Review each source version and transformation policy: species, identifier mapping, relationship semantics, confidence filters, context handling, and projection eligibility.
2. Require deterministic validation of every processed row. Check the validation and coverage reports, provenance completeness, duplicate handling, invalid identifiers, and unresolved mappings.
3. Inspect reproducible stratified samples and flagged exceptions. Read a shared paper or database record once and reuse that evidence bundle. Preserve audit sample IDs and the sampling seed.
4. Distinguish source/policy approval plus sample auditing from full independent review of every record. Record the actual review method and audit coverage.
5. Route ambiguous statements, novel terms, conflicts, and experimental causal claims to explicit evidence review. Quarantine unresolved rows rather than accepting a whole batch because a sample looked correct.
6. Accept only the identified approved artifact, with its checksum and audit report. Rejected/deferred batches have null approved artifact fields. Never add unreviewed knowledge during this role.

For legacy record review:
- Cover every candidate ID exactly once. Check original evidence and terminology separately.
- Return accept, request_evidence, defer, or reject. Only accepted decisions contain a complete normalized_record.
- Explain changes to relationship or context and retain shared-study provenance.

Use English throughout. Check assay, reagent, isoform, and cofactor names against the source. Prefer the original English assay name over an uncertain translation. Preserve all biological qualifiers when normalizing labels.
