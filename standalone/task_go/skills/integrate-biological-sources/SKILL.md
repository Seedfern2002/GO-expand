---
name: integrate-biological-sources
description: Integrate biological database snapshots into task-wide GO knowledge batches using source-aware mappings, typed relationships and reproducible bulk transformations.
---

# Integrate biological sources

Produce a reusable evidence transformation for a selected biological source and the complete task gene universe. Source choice follows the plan's biological questions and evidence requirements.

## Establish the source meaning

Inspect the source documentation, version and representative records. Determine what membership or association actually means, which species and molecular entities it covers, and how identifiers, confidence, experimental evidence and biological context are encoded. Resolve direct versus inherited pathway memberships, predicted versus experimental complexes, and functional annotation versus physical interaction when those distinctions apply.

Prefer a documented bulk export or structured query that preserves the required semantics. Pin its URI, release and checksum. A broad organism-level resource supplies organism-level evidence; cell-specific activity assignments require evidence for that context.

## Build and verify the transformation

Develop one reusable program for the source. Check a small representative slice against the raw records, then process the complete source under the declared policies. Preserve original protein identifiers, mapping decisions, source evidence codes, study identities and exact row locators. Keep one-to-many or unresolved identifier cases traceable.

Map the complete fixed gene universe and retain every eligible association. Report source totals, counts after each filter, exclusions, supported genes and unmatched genes. The literature candidate budget and review sample sizes govern their declared activities; database output size follows eligible source content.

Validate counts and mappings against the saved source. For source hierarchies, retain the expansion rule and hierarchy snapshot so direct and inherited associations remain reconstructible. Reuse the program and cache across processing partitions.

## Publish

In task-only acquisition, hand normalized source records to the add-go-knowledge procedure selected by the acquisition prompt for existing-knowledge queries, concept resolution and candidate proposals. Materialize its emitted records using `pipeline/import_batch.py`; `pipeline/FORMAT.md` defines the record and importer interfaces. The repository adapter provides `scripts/import_knowledge_batch.py` for its `task_knowledge` workflow.

Publish complete validated batches with compact manifests. A resource ceiling produces partial coverage with the last processed position. Preserve failed or ambiguous records and their reasons alongside the accepted transformation output.

When the workflow supplies a module graph stage, prepare source module definitions, complete fixed-universe memberships, native hierarchy rows and explicit cross-resource annotations as separate scientific inputs. Hand these inputs to the Editor using place-functional-modules. Its code-expanded proposal receives independent review through review-functional-modules before the controller commits accepted edges. Keep source evidence and membership records available to that stage.
