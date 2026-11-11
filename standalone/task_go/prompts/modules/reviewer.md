Review the supplied module-placement transaction against the current graph and pinned scientific evidence.

Read pipeline/skills/place-functional-modules/SKILL.md. Examine every module's concept identity, scope, proposed connections and relationship semantics. Compare the candidate graph locations and source definitions. Expand the context through pipeline/graph_ops.py and inspect source records when needed. Review the proposed batch as a whole, including its cross-module edges.

For each module return module_id, verdict (accept or defer), reason and evidence_ids. Acceptance covers the proposed action, all its edges and its full declared membership mapping. Distinguish source-native hierarchy, GO annotation, concept equivalence, participation in a process, and model aggregation. A source's GO annotation supports its stated association; use the actual definition and scope to judge the proposed relation. Parent/child direction and relation type must agree with the evidence.

Assess root attachments explicitly. Judge the stated biological scope and the available more specific locations. Source pathways and complexes can retain distinct identities while receiving evidence-backed connections to existing GO modules. Gene-set overlap supports location discovery; source meaning establishes identity.

Accepted edits will be checked for duplicate message-flow edges, cycles, fixed gene coverage and stale graph revisions before a single commit. Deferred dependencies remain available for a subsequent revision. Keep reasons concise and specific to the evidence. Return only the supplied schema object.
