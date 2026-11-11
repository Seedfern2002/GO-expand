You design a compact, evidence-backed integration recipe for a complete batch of functional modules in one shared task graph.

Decide each module's task relevance, concept identity and biological placement. Read every supplied module definition and its source GO annotations. Group modules when their shared semantics support a common integration rule, and record identity and placement exceptions explicitly. Gene memberships remain in files and are joined by the compiler.

The context includes every batch module, source facts and existing source-annotated concepts. Explore additional graph locations with batched, read-only queries:

python3 pipeline/graph_ops.py --concepts GO:IDENTIFIER GO:OTHER
python3 pipeline/graph_ops.py --labels "biological phrase" "another phrase" --limit 12
python3 pipeline/graph_ops.py --label "phrase" --offset 12 --limit 12

Queries expose definitions and parent/child neighborhoods. Follow both ancestors and descendants to resolve scope. The complete graph is graph/current.json; source definitions and evidence remain in inputs/modules.json, inputs/placement_evidence.json and inputs/sources/. Source GO identifiers absent from the current graph remain evidence references. Choose graph anchors from the current graph or declared added targets.

Return groups that partition all supplied module identifiers exactly once. Each group has:
- group_id, modules, rationale and inspected_concepts. State the biological scope and task relevance; list inspected current graph nodes and declared new targets.
- native_hierarchy: a boolean approving expansion of all pinned source_pathway_parent facts whose endpoints are active in this group or already aliased in the graph. The compiler resolves source aliases and preserves existing message-flow connections once, recording matching native facts in the expansion receipt.
- reuse: exceptions with module_id, target_id and rationale. Reuse requires biological equivalence at the stated scope and an existing non-root graph target. Confirm its presence and definition.
- defer: exceptions with module_id and reason. These receive empty edits.
- anchors: shared incoming connections, each with parent, modules (the explicit subset receiving this connection), relation, model_edge and rationale. The compiler expands one connection per selected module and attaches its declared source evidence. Select supported entry points into a native subtree. Distinguish a whole process from a component or regulation of that process.
- extra_edges: individually chosen incoming or outgoing connections, each with parent, child, relation, model_edge, evidence_ids and rationale. These can bridge to existing descendant modules or preserve typed associative links.

Every active module defaults to addition with its source identifier and full declared membership. The reuse and defer arrays capture all exceptions. Rationale strings must contain at least 25 characters. All arrays are present, including empty arrays. Every edge touches an active module in its group. List each model connection once across the recipe.

Graph direction is parent to child. source_pathway_parent retains native pathway hierarchy. is_a and part_of require exact pinned ontology facts. For participates_in the child participates in the parent's process; preserve the distinction between a protein assembly and a process. model_aggregation states the biological justification for a computational connection. related_to and regulates use model_edge=false. Keep one connected acyclic model hierarchy, preserving original structure and the complete task gene universe. Root placement needs a scope-specific rationale.

The compiler expands the full recipe and validates the transaction. An independent reviewer receives every module and expanded edge, with per-module exception verdicts. Return only the supplied schema object.
