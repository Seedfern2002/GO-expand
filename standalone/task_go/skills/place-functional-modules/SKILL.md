---
name: place-functional-modules
description: Inspect a current functional graph and source evidence, then propose and review batched module identities and typed connections.
---

# Place functional modules

Use a module as the editing unit and a coherent small batch as the reasoning unit. Work on the complete task's shared graph and fixed gene universe.

## Inspect the graph and scientific evidence

The controller supplies the current graph revision, a packet of module definitions and candidate neighborhoods, source-native hierarchy facts, source GO annotations and membership summaries. Full members and source snapshots remain in inputs/. Candidate locations combine text, overlap and explicit source annotations; review their biological meaning.

Query pipeline/graph_ops.py for additional module or concept context. Its output includes existing parents, children, definitions, gene coverage and source relationships. Decisions within a batch can introduce connections among its modules. Subsequent batches receive the committed graph, including accepted additions and source aliases.

## Propose a transaction

Choose add, reuse or defer for each module. Preserve source identity and evidence. Reuse requires biological equivalence at the stated scope. An added module receives explicit incoming edges and may connect to existing descendants. Source-native hierarchy relations retain their own relationship label. GO is_a and part_of edges require matching pinned ontology facts. A complex's process participation can be recorded as participates_in. Computational grouping uses model_aggregation with its rationale. Associative and regulatory links remain typed, separate from the model hierarchy.

Each edge records its endpoints, relation, model_edge, evidence_ids and rationale. The model hierarchy has one declared root and one edge per parent-child pair. Keep source membership mappings in files. The graph importer joins memberships and recomputes coverage; evidence-only associations retain their own semantics.

## Review and commit

An independent reviewer assesses every module and its incident edits against scientific evidence and current graph context. The controller validates revision binding, provenance references, duplicate edges, model cycles and full gene coverage. It commits the accepted transaction atomically, records deferred decisions and rebuilds the context for the next batch.

The frozen product contains typed graph edges, source aliases, membership mappings, decisions, evidence lineage and timing. Consumer adapters select the declared model edges while retaining the scientific relationship metadata.
