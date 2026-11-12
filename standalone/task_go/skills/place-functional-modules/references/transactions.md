# Per-module transaction interface

Return `batch_id`, `graph_revision` and exactly one decision for each supplied module. Each decision contains `module_id`, `action` (`add`, `reuse` or `defer`), `target_id`, `rationale`, `inspected_concepts`, `evidence_ids` and `edges`.

An addition uses its source `module_id` as the target. Reuse selects a biologically equivalent existing non-root concept and retains the source identifier as an alias. A deferred decision has an empty target and empty edges, together with its reason.

List inspected nodes from the current graph and declared added targets. Confirm reuse targets through the supplied context or a concept query. Source GO annotations outside the current graph remain evidence references.

Each edge has `parent`, `child`, `relation`, `model_edge`, `evidence_ids` and `rationale`; it touches its decision target. Native hierarchy and ontology claims require matching pinned source facts after alias resolution. Incoming and outgoing edges can connect new modules to existing ancestors and descendants or to other modules in this batch.

Rationales contain at least 25 characters. Keep each model connection unique across the batch, preserve original structure and maintain a connected acyclic model hierarchy. The controller validates the complete transaction before independent biological review.
