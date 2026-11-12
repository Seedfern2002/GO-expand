# Group recipe interface

Return `batch_id`, `graph_revision` and `groups`. Groups partition every supplied module identifier exactly once. Each group contains all of these fields:

- `group_id`, `modules`, `rationale`, `inspected_concepts`: identify the group, state task relevance and biological scope, and list inspected current graph nodes or declared added targets. Source GO identifiers absent from the graph remain evidence references.
- `native_hierarchy`: approve expansion of every pinned `source_pathway_parent` fact whose endpoints are active in this group or already aliased in the graph. The compiler resolves aliases, keeps existing model connections once and records the supporting native facts.
- `reuse`: exceptions with `module_id`, existing non-root `target_id`, and a rationale establishing equivalence.
- `defer`: exceptions with `module_id` and an evidence-specific `reason`.
- `anchors`: shared incoming connections with `parent`, explicit `modules`, `relation`, `model_edge` and `rationale`. Select the supported entry points of a native subtree. The compiler attaches each selected module's source evidence.
- `extra_edges`: individual incoming or outgoing connections with `parent`, `child`, `relation`, `model_edge`, `evidence_ids` and `rationale`. These can bridge to existing descendants or retain associative links.

Every active module defaults to addition with its source identifier and complete declared membership. Reuse and defer arrays capture identity exceptions. Include every array, including empty arrays. Rationale strings contain at least 25 characters.

Each edge touches an active module in its group. List each model connection once across the recipe. Select anchors from the current graph or declared added targets. Preserve original structure and one connected acyclic model hierarchy. The compiler produces a full per-module transaction, and the reviewer receives all definitions, expanded connections, preserved connection receipts and membership counts.
