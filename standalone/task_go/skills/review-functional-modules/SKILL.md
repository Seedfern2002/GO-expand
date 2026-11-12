---
name: review-functional-modules
description: Independently review proposed functional-module identities, complete batch expansions and typed graph placements, returning group or module verdicts with evidence-specific exceptions.
---

# Review functional modules

Assess the complete proposed batch against the scientific task, current graph and pinned source evidence. The editor's proposal and its compiled expansion are the objects of review. Apply the [shared knowledge semantics](../../references/knowledge_semantics.md); the controller embeds these conventions in the prompt.

## Examine the complete scope

Assess every supplied module's task relevance, source identity, equivalent-concept reuse, incoming and outgoing connections, relation type and full declared membership mapping. For a shared integration rule, examine its applicability to every group member and identify exceptions. The context provides definitions, source facts, expanded connections, preserved duplicate-connection receipts and member counts; complete records and memberships remain in the declared files.

Check native hierarchy against pinned source endpoints after alias resolution. Assess cross-source anchors and reuse independently from the editor's rationale. Use definitions and actual source-curated content to distinguish whole processes, narrower mechanisms, regulation and protein assemblies. Inspect both ancestors and descendants when comparing biological breadth or judging a root attachment.

Use batched read-only graph queries as needed:

```bash
python3 pipeline/graph_ops.py --concepts GO:IDENTIFIER GO:OTHER
python3 pipeline/graph_ops.py --labels "biological phrase" "another phrase" --limit 12
```

Label results support `--offset`; parent/child neighborhoods support `--neighbor-offset`. Trace uncertain mappings to the saved source records and exact locators. Preserve source confidence separately from the review verdict.

## Return independent verdicts

Give concise, evidence-specific reasons. Acceptance covers the proposed action, every incident edit and the complete membership mapping. Use the active interface supplied by the controller:

- [Group review](references/group-reviews.md) for `group_recipe` mode, covering every group with explicit module exceptions.
- [Module review](references/transactions.md) for `transaction` mode, covering every module.

The controller translates verdicts into complete module coverage, holds affected dependencies and validates the accepted transaction before committing. Deliver verdicts through the supplied schema; the controller owns graph modification and freezing.
