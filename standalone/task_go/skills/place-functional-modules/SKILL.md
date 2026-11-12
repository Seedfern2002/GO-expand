---
name: place-functional-modules
description: Propose task-relevant functional-module identities and typed graph placements in coherent batches, using shared integration rules and explicit exceptions.
---

# Place functional modules

Produce a reviewable integration proposal for the supplied batch within one shared task graph. The role prompt supplies the active interface and output schema. Apply the [shared knowledge semantics](../../references/knowledge_semantics.md); the module controller embeds these conventions in the prompt.

## Inspect and locate

Read every supplied module's definition, source-curated relationships, GO annotations and member summary. Judge task relevance and biological scope from the task and pinned evidence. Query existing definitions and both parent and child neighborhoods when resolving identity or placement. Start from the supplied source annotations and explore additional locations as needed:

```bash
python3 pipeline/graph_ops.py --concepts GO:IDENTIFIER GO:OTHER
python3 pipeline/graph_ops.py --labels "biological phrase" "another phrase" --limit 12
python3 pipeline/graph_ops.py --label "phrase" --offset 12 --limit 12
```

`--neighbor-offset` paginates parent/child neighborhoods. The graph, source catalog and complete evidence are at the paths in the batch context. Keep large memberships in those files.

## Form the proposal

Choose source-identified addition, equivalent-concept reuse or evidence-based deferral. Confirm a reuse target's current presence and definition. Inspect multiple plausible locations when scope is ambiguous. Preserve source meaning in the edge type and rationale, including distinctions between whole processes, component processes, regulatory processes and protein assemblies.

Group modules when their full biological scope supports a shared rule. Approve native hierarchy expansion over the declared group, select entry anchors, and record reuse, deferral and connection exceptions explicitly. Review the applicability of each shared rule across all selected modules. The compiler joins complete memberships and expands the approved scope.

Use the active interface reference supplied by the controller:

- [Group recipes](references/group-recipes.md) for `group_recipe` mode.
- [Per-module transactions](references/transactions.md) for `transaction` mode.

Return the schema object for the entire batch. The controller compiles and validates the proposal, then hands the complete expansion to the independent reviewer. Accepted edits enter the graph through the controller's commit.
