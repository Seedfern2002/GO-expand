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

Use the importer to materialize typed records:

```bash
python3 pipeline/import_batch.py --task task.json \
  --records acquisition/typed_records.jsonl --output-dir batches/source_1 \
  --batch-id source_1 --plan-item-id PLAN_ITEM_ID
```

It writes records.jsonl, coverage.json, screening.jsonl, validation.json, provenance.json and batch.json. Use the batch.json contents in the acquisition result. Create a fresh output directory for each batch revision.

An alternative literature interface accepts a paper manifest array with paper_id, source_name, source_version, source_uri, study_id, text_path and text_sha256. Each claim then replaces evidence with paper_evidence entries containing paper_id, quote, locator and assertion_type. Supply --paper-manifest acquisition/papers.json. Use one paper identity per DOI/PMID and preserve shared-study identifiers across papers.

Knowledge assembly merges only exact subject/object/relation/polarity/context matches, retaining all evidence and original IDs. Explicit reviewed equivalence can normalize concepts. Opposing assertions remain in the knowledge layer and are excluded from positive attribute projection. Conditions and signed mechanisms remain available for consumers; only declared memberships generate attributes.
