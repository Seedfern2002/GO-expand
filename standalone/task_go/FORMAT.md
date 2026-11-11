# Statement and batch interfaces

All paths resolve within /workspace. Store large tables as JSONL. Scientific inputs are the task definition, original ontology/annotations and a fixed gene list.

retrieval_budget.max_candidate_records counts literature_extracted candidate statements exclusively. Database batches contain every record passing the declared source, evidence, mapping and gene-universe policies. Record complete source processing and filter counts in coverage reports. Review sample sizes determine audit inspection counts.

A statement has:

```json
{
  "id": "source:stable_record_id",
  "subject_id": "HGNC:identifier",
  "subject_label": "EXACT_GENE_FROM_UNIVERSE",
  "object_id": "GO:0000000",
  "object_label": "Supported concept label",
  "relation": "annotated_to",
  "polarity": "positive",
  "context": {"taxon_id": "NCBITaxon:9606", "cell_type": "unknown"},
  "evidence_class": "literature_extracted",
  "projection_eligible": true,
  "evidence": [{
    "source_name": "PubMed/PMC",
    "source_version": "saved-text-date",
    "source_uri": "https://source.example/article",
    "study_id": "PMID:identifier",
    "locator": "Results, paragraph 3",
    "snapshot_path": "acquisition/article.txt",
    "snapshot_sha256": "actual SHA256",
    "quote": "An exact source passage of at least twenty characters.",
    "assertion_type": "experimental_result"
  }]
}
```

Object IDs are namespaced; Reactome R-HSA stable IDs are accepted. Source contexts must reflect source evidence rather than automatically inheriting task conditions. GO IDs must be active canonical IDs in the supplied ontology. Use relation values from task.compilation.allowed_relations. Negative assertion polarity expresses negation of the relation; inhibition is positively asserted negatively_regulates. Interpretation/hypothesis-only claims do not enter attribute projection.

For database records, evidence_class is database_derived, assertion_type is database_record, and quote is optional. A locator such as line:123 must point to an existing line in the pinned source snapshot. Preserve source protein IDs, original evidence codes, confidence classes and transformations in additional evidence fields. For inferred relationships use analysis_inferred and explicitly describe the method and all source inputs. Structural checks validate artifact consistency; the reviewer assesses biological interpretation.

Use the importer to materialize typed records. In the query/propose addition workflow, `--records` receives the proposal's emitted `records_path`:

```bash
python3 pipeline/import_batch.py --task task.json \
  --records acquisition/proposal_001/records.jsonl --output-dir batches/source_1 \
  --batch-id source_1 --plan-item-id PLAN_ITEM_ID
```

It writes records.jsonl, coverage.json, screening.jsonl, validation.json, provenance.json and batch.json. Use the batch.json contents in the acquisition result. Create a fresh output directory for each batch revision.

An alternative literature interface accepts a paper manifest array with paper_id, source_name, source_version, source_uri, study_id, text_path and text_sha256. Each claim then replaces evidence with paper_evidence entries containing paper_id, quote, locator and assertion_type. Supply --paper-manifest acquisition/papers.json. Use one paper identity per DOI/PMID and preserve shared-study identifiers across papers.

Knowledge assembly merges only exact subject/object/relation/polarity/context matches, retaining all evidence and original IDs. Explicit reviewed equivalence can normalize concepts. Opposing assertions remain in the knowledge layer and are excluded from positive attribute projection. Conditions and signed mechanisms remain available for consumers; only declared memberships generate attributes.
## Knowledge tool interfaces

`pipeline/skills/add-go-knowledge/SKILL.md` defines the addition procedure when packaged. The CLI is `python3 pipeline/knowledge_ops.py`; the skill's `scripts/knowledge.py` wrapper exposes the same interface. `retrieval_round.knowledge_context_index` names the controller's current SQLite snapshot. `build --index NEW_INDEX` creates a fresh snapshot when needed. `query --index INDEX` accepts `--genes`, `--label`, `--concept-id`, `--limit`, `--offset` and `--output`.

`propose --index INDEX --records INPUT.jsonl --output FRESH_DIRECTORY` accepts typed records. Optional `--concepts` supplies an array of `{id, definition, kind}` entries, with `distinct_from: [{concept_id, reason}]` for matching-name distinctions. Optional `--equivalences` supplies the compiler's concept-equivalence mapping format. Outputs are `records.jsonl`, `decisions.jsonl`, `concepts.json` and `equivalence_proposals.json`; stdout provides `records_path`, `records_sha256`, `records_emitted`, `action_counts`, `decisions_path` and `review_state`. Records preserve original identities and resolution evidence in their evidence fields. Database and literature records share this interface.

## Module-graph transactions

The placement workflow receives `inputs/baseline_graph.json` (`root`, `genes`, node map, typed edges, revision, source aliases), `inputs/modules.json` (source-identified module definitions and full member lists), `inputs/placement_evidence.json` (source facts with exact locators), and `inputs/module_batches.json` (processing partitions). Source snapshots are copied under generic names in `inputs/sources/`. Preparation verifies native hierarchy endpoints and GO annotations against their declared source rows. Host paths remain in the external launch receipt.

An editor transaction has `batch_id`, `graph_revision` and one decision per module. A decision has `module_id`, `action` (`add`, `reuse`, `defer`), `target_id`, `rationale`, `inspected_concepts`, `evidence_ids` and `edges`. Added nodes retain source identity; reuse records a source-to-current-concept alias and joins memberships. Deferred modules retain their rationale with empty target/edits. Each edge has `parent`, `child`, `relation`, `model_edge`, `evidence_ids` and `rationale`.

Edge storage direction is parent to child. `source_pathway_parent` follows an explicit native source hierarchy. `is_a` and `part_of` require exact pinned hierarchy support after source-alias resolution. For `participates_in`, the child participates in the parent's biological process. `model_aggregation` denotes an explicitly reviewed computational placement. `related_to` and `regulates` have `model_edge=false`. Consumers distinguish computational gene coverage from ontology annotation entailment.

Review decisions specify `module_id`, `verdict` (`accept`, `defer`), `reason` and `evidence_ids`. Dependent edits are held when their parent/module dependency is deferred. The controller validates the complete accepted transaction against the current revision before atomic graph replacement. Context and biological evidence remain traceable through frozen input hashes and per-batch patch/review hashes.

The supplied round schema and `pipeline/prompts/retrieval_round.md` define reading decisions and inspection-ledger fields for the selected mode.

## Module group recipes

The `module_recipes` workflow accepts the same scientific input files as module placement. Its editor output contains `batch_id`, `graph_revision` and `groups`. Each group contains `group_id`, `modules`, `rationale`, `inspected_concepts`, `native_hierarchy`, `reuse`, `defer`, `anchors` and `extra_edges`.

Groups partition every supplied module exactly once. The compiler creates one decision per module, expands approved native source facts and shared anchors, resolves source aliases, joins full memberships and validates the complete patch. It records skipped source edges already represented by a resolved identity or existing model connection. Extra edges retain explicit endpoints, types, evidence and rationale.

The reviewer returns the same batch and revision identifiers plus one verdict per group. Each verdict contains `group_id`, `verdict`, `reason` and `exceptions`; exceptions contain a `module_id`, `verdict` and `reason` for a member of that group. The controller expands this to complete per-module review coverage, holds dependencies and commits the accepted patch. Recipe and expansion hashes are part of `knowledge_graph/freeze_manifest.json`.
