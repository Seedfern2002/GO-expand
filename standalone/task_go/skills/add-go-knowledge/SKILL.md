---
name: add-go-knowledge
description: Query existing gene attributes and concept identities, then publish evidence-preserving candidate GO-overlay additions or additional support for existing assertions.
---

# Add GO knowledge

Turn supported database or literature observations into a reviewable knowledge increment for the current task. Follow this sequence: query existing knowledge, resolve concepts, propose candidate records, then import the emitted records for review. This skill defines the addition procedure; pipeline/FORMAT.md defines record fields and importer arguments. The task and Planner determine acquisition scope and reading budgets.

This acquisition skill publishes candidate assertions and concept-resolution evidence. Apply the concept identity and evidence conventions in [shared knowledge semantics](../../references/knowledge_semantics.md). When a module graph stage is supplied, pass module definitions, complete source memberships and pinned relationships to its Editor. The place-functional-modules skill governs that stage's graph proposal; its independent Reviewer uses review-functional-modules.

## Look up existing knowledge

Use `retrieval_round.knowledge_context_index` when supplied by the controller. For a workspace without a supplied index, first create a fresh one with `python3 pipeline/knowledge_ops.py build --index acquisition/knowledge_context.sqlite`. In a prepared task workspace:

```bash
python3 pipeline/skills/add-go-knowledge/scripts/knowledge.py query --index INDEX --genes GENE --label "concept phrase"
python3 pipeline/skills/add-go-knowledge/scripts/knowledge.py query --index INDEX --concept-id GO:IDENTIFIER
```

Replace INDEX and identifiers with the supplied task values. Query the genes and candidate concepts before choosing an addition. Results expose existing attributes, incoming/outgoing typed relationships, concept definitions, EXACT synonyms, ontology edges and review state. `--limit` and `--offset` paginate large results; `--output` saves complete query pages for selective inspection. Pending assertions are candidate evidence whose approval remains open.

## Resolve the proposed increment

Reuse an existing concept when its definition, type and biological scope match. Preserve narrower compositions, molecular states and conditions explicitly. A new local concept supplies `id`, `definition` and `kind` in a concept-metadata array. When an existing name/EXACT synonym matches, supply `distinct_from` entries with `concept_id` and an evidence-grounded `reason` for the distinction. Exact labels identify review candidates; source meaning determines equivalence.

Explicit concept-level equivalence proposals use `alias_id`, `canonical_id`, `relationship="equivalent"`, `evidence` and optional `scope="concept"`. The tool preserves the original identifier and resolution evidence. Task-projection similarities retain their scoped findings. These decisions are reviewed with the resulting claims.

## Publish and hand off

Prepare typed records using `pipeline/FORMAT.md`, then run:

```bash
python3 pipeline/skills/add-go-knowledge/scripts/knowledge.py propose --index INDEX --records acquisition/claims.jsonl --output acquisition/proposal_001
```

Use `--concepts` and `--equivalences` for the relevant metadata files. The tool checks source evidence, queries existing assertions and emits fresh candidate records with action receipts. Identical evidence is recorded as already supported; additional evidence and distinct contexts are retained. Successful proposals update this round's index as candidates so later papers can reuse their concepts.

For a nonempty proposal, pass its emitted `records_path` to `pipeline/import_batch.py --records` and use a fresh batch directory. The raw input claims are the proposal input; the importer consumes the proposal output. Keep proposal receipts and concept-resolution evidence available to the Reviewer. When `records_emitted` is zero, retain the action receipt and continue. Publish materialized batches before handing off the round so their records enter the next round's rebuilt index. The Reviewer approves source-grounded subsets; the compiler creates the final frozen overlay. Original GO inputs and prior batches stay immutable.
