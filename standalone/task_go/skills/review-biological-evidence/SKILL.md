---
name: review-biological-evidence
description: Review database-derived and literature-derived GO augmentation claims for biological meaning, experimental support, provenance and task-wide coverage, producing actionable batch decisions.
---

# Review biological evidence

Determine which acquired assertions are supported at their stated biological scope. Bind each finding to records and source locations so the acquisition role can make a precise revision when needed.

## Inspect evidence at the appropriate unit

For database batches, review the source release and transformation policy, inspect deterministic validation of all rows, and draw reproducible stratified samples covering relevant identifiers, evidence classes, relationship types and flagged exceptions. Verify complete source processing, source-defined membership, mapping rules and policy-based exclusions.

For literature batches, inspect every accepted claim against saved scientific passages and experimental context. Read shared papers once and assess their claims together. Compare the source's entity, intervention, observation and interpretation with the proposed gene, relation, polarity and qualifiers. Abstract evidence supports the scope actually reported there; inspect scientific-body passages when resolving details that require them.

Prioritize specific biological questions: whether an assayed construct represents the named gene product, whether an interaction supports complex membership, whether an observed change supports the stated direction, and whether a condition applies to the evidence or to the concept itself. Preserve source confidence separately from reviewer judgment.

## Resolve terminology and disagreements

Use existing GO definitions, source-native identifiers and explicit equivalence evidence to assess proposed concept mappings. Check entity type, composition, molecular state and experimental qualifiers. Record broader/narrower relationships and genuine differences as such. Identical gene-carrier sets and similar names are candidate-discovery evidence; source meaning establishes identity.

The current equivalence interface represents reviewed concept equivalence through `alias_id`, `canonical_id`, `relationship="equivalent"` and supporting `evidence`. Task-projection-only similarities and unresolved composition discrepancies retain their scope in findings. Preserve distinct contexts, opposing assertions and source disagreements in the knowledge product.

## Make a review decision

For every batch, save the review method, inspected record IDs, sampling seed where applicable, findings and exclusions. An accepted file is a checked, checksum-bound subset of acquired records. Modified claims enter a fresh acquisition revision; deferred and rejected batches retain their reasons and null approved artifact fields.

Recount paper and full-text inspections from stable publication identities and saved passages, and reconcile database processing and topic coverage with the manifests. Distinguish structural validation results from scientific evidence judgments. Deliver the supplied review schema and explicit unresolved questions that affect the current knowledge product.
