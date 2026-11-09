# Task-wide knowledge pipeline, schema 3.0

The current task-only execution boundary is implemented by the self-contained [standalone runtime](../standalone/task_go/README.md). It accepts scientific task inputs and runs outside this project in a private filesystem. Project documents, cached experiment directories and prior agent sessions are not agent inputs. The repository-coupled v3 interfaces described below are retained as development interfaces; they are not the task-only runtime entry point.

The workflow is `task_knowledge`. The three agent roles remain Planner, Retriever and Reviewer. Shared programs independently validate materialized records, assemble knowledge, project it for the declared task and freeze the product. The complete fixed gene universe receives one shared overlay.

Leakage assessment is an independent external audit for scientific review. It is not an augmentation agent stage, an automated source-selection input, or a clearance inferred from provenance validation. Gene–gene relationships are legitimate prior knowledge under the declared experimental scope. Downstream responses, predictions and scores remain outside knowledge-selection inputs.

## Task contract and source choice

Use `configs/agent_tasks/gears_norman_v3.json`. Its `compilation` object fixes the trusted local baseline annotation file, allowed relationship/evidence types, and projection rules. The planner copies this object into `knowledge_contract`; a change requires a new task/version before retrieval and evaluation. The planner chooses source recipes and database/literature/combined routes. Source candidates do not impose an acquisition priority.

The v3 background launcher uses the task's download budget. Its database priorities and 256 MiB pilot limit are retained only for the historical v2 profile.

## Statement and evidence format

Acquisition batches store JSONL. A minimal database-derived statement is:

```json
{
  "id": "candidate:001",
  "subject_id": "HGNC:EXAMPLE",
  "subject_label": "GENE_A",
  "object_id": "LOCAL:process_1",
  "object_label": "Example process",
  "relation": "member_of_pathway",
  "polarity": "positive",
  "context": {"taxon_id": "NCBITaxon:9606", "cell_type": "unknown"},
  "evidence_class": "database_derived",
  "projection_eligible": true,
  "evidence": [{
    "source_name": "Example database",
    "source_version": "1",
    "source_uri": "urn:example:source",
    "study_id": "UNRESOLVED:ExampleDatabase",
    "locator": "line:1",
    "snapshot_path": "outputs/example/source.tsv",
    "snapshot_sha256": "sha256-of-the-materialized-file",
    "assertion_type": "database_record"
  }]
}
```

`subject_label` is the original fixed-universe gene identifier. `subject_id` retains the biological entity mapping. Object IDs have explicit namespaces or a recognized Reactome stable ID (`R-HSA-...`). GO annotation additions use `GO:...` and `annotated_to`; external concepts retain their source/local IDs. The Norman contract pins `ontology_path`; candidate GO terms must exist and use active canonical IDs in that snapshot. The compiler does not infer GO IDs from similar names.

Evidence classes are `database_derived`, `literature_extracted`, and `analysis_inferred`. Each evidence assertion is a `database_record`, `experimental_result`, `interpretation`, or `hypothesis`. All conditions, direction, isoforms and source confidence can be retained in the context/evidence fields. Task context does not establish source-specific activity. Unknown study provenance remains explicitly unresolved; neither record count nor database count establishes independent study support.

## Batch import and literature

`scripts/import_knowledge_batch.py` supports three inputs:

1. Already typed records in the format above.
2. Historical flat Reactome/hu.MAP records, plus their provenance JSON and snapshot directory. The importer retains evidence codes, confidence and original eligibility.
3. Agent-extracted literature claims plus a shared paper manifest. Each paper is cached once and can support many statements across the complete universe. A paper's mentioned genes are not assumed to exhaust the relevant functional gene set.

A paper manifest is a JSON array:

```json
[{
  "paper_id": "PMID:EXAMPLE",
  "source_name": "PubMed/PMC",
  "source_version": "saved-text-v1",
  "source_uri": "urn:example:paper",
  "study_id": "PMID:EXAMPLE",
  "text_path": "outputs/example/paper.txt",
  "text_sha256": "sha256-of-the-saved-text"
}]
```

Literature claims use the statement fields above, replacing `evidence` with:

```json
"paper_evidence": [{
  "paper_id": "PMID:EXAMPLE",
  "locator": "Results, paragraph 3",
  "quote": "An exact passage of at least twenty characters from the saved paper text.",
  "assertion_type": "experimental_result"
}]
```

The importer binds paper metadata to the statement and checks every quotation and file hash. The agent is responsible for reading and extracting the biology; exact text matching alone does not validate the interpretation. Reviews and secondary papers can lead to original studies; their shared underlying study should retain the same study ID. The same DOI/PMID should use one canonical paper identity in each bundle.

```bash
.venv/bin/python scripts/import_knowledge_batch.py \
  --task configs/agent_tasks/gears_norman_v3.json \
  --records outputs/example/literature_claims.jsonl \
  --paper-manifest outputs/example/papers.json \
  --output-dir outputs/example/imported_literature \
  --batch-id literature_1 --plan-item-id planned_literature
```

Import produces normalized records, whole-universe screening, provenance, validation, coverage and a batch manifest. Screening means matching all genes against the imported evidence batch; it does not assert an exhaustive search of all literature. The stage controller recomputes actual record and gene counts and applies the task-level paper/statement budgets, independently of agent-reported totals. Invalid rows must be quarantined before publishing a batch.

## Review and assembly

Database batches support source-policy review with reproducible sampling. Every accepted literature claim needs an entry in its audit's `reviewed_record_ids`. Approved files are exact subsets of acquisition records. Claim changes require a new acquisition artifact and review.

The reviewer may publish an explicit concept-equivalence JSON array with `alias_id`, `canonical_id`, `relationship: "equivalent"`, and supporting `evidence`; its path and checksum are bound into the review. Overlap, broader/narrower relations and similar labels are not equivalence. The default is no cross-source merge without an explicit mapping.

Assembly merges statements only when subject identity, canonical object, relationship, polarity and full context match. Evidence and original record IDs are preserved. Different conditions and polarity remain distinct. Explicit assertion/negation conflicts are reported and withheld from positive attribute projection. Interpretation/hypothesis-only statements remain in the evidence layer.

## Projection and freezing

- `gene_attributes`: exports one attribute set per gene, plus the complete typed statement/evidence layer. This generic interface is available to other task consumers.
- `gears_jaccard`: additionally exports candidate and selected directed gene edges with the declared threshold and upstream `k+1` selection, including self-edge behavior and lexical source tie ordering.
- Only declared membership relationships and positive/not-applicable assertion polarity can generate attributes. Signed regulation and binding remain typed relations, without silently converting them to shared membership.
- `singleton_policy`: `retain` reproduces the original attribute union; `exclude_new` excludes newly introduced attributes found in only one universe gene while retaining original annotations.
- `context_policy`: `preserve` retains conditions without filtering; `compatible` withholds explicitly mismatched species/cell/tissue/condition evidence from projection and retains it in knowledge. Unknown/general-human evidence does not become proof of K562 activity.

After three validated agent stages, the v3 background controller runs `scripts/compile_agent_knowledge.py`. Manual compilation is also supported:

```bash
.venv-gears/bin/python scripts/compile_agent_knowledge.py \
  --run-dir outputs/agents/my_v3_run \
  --output-dir outputs/agents/my_v3_run/knowledge
```

The GEARS adapter needs NumPy, pandas and SciPy; the shared knowledge layer uses the standard library. `.venv-gears` has those dependencies. Stage preparation and execution use the existing Codex backend and versioned JSON interfaces. The background interpreter needs the optional agent dependency `jsonschema`; the Norman profile uses `.venv/bin/python` for the controller and `execution.compilation_python=.venv-gears/bin/python` for compilation.

```bash
.venv/bin/python scripts/run_agent_background.py \
  --task configs/agent_tasks/gears_norman_v3.json \
  --run-dir outputs/agents/my_v3_run --codex-bin /path/to/codex
```

The frozen directory contains task/plan snapshots, `statements.jsonl`, `evidence.jsonl`, `conflicts.jsonl`, `gene_attributes.jsonl`, validation/summary reports, optional GEARS CSVs, and `freeze_manifest.json`. The manifest hashes source snapshots, accepted records, stage decisions, checks and compiler code, together with every compiled output. It asserts provenance/structure checks, not absence of leakage. Output directories cannot be overwritten; downstream evaluation does not revise frozen knowledge.

Historical v1/v2 workflows and the committed seed-1 GEARS experiment are retained. No downstream training is started by this workflow.
