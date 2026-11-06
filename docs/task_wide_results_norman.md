# Task-wide Norman augmentation: first background result

The three-stage Codex run completed on 2026-11-05 at 17:27 China time. End-to-end wall time was approximately 11 minutes 17 seconds. Both bulk batches were accepted after source-policy review, independent programmatic reconstruction, and a total of 20 sampled records. ENCODE remains pending.

Run: `outputs/agents/norman_task_background_002/`.

## Coverage and volume

Every selected bulk family screened the complete universe of 3,127 graph genes. The 102 perturbation targets were reported separately.

| Source | Validated memberships | Genes annotated | Targets annotated | Projection-eligible memberships |
|---|---:|---:|---:|---:|
| Reactome | 8,652 | 1,981 | 66 / 102 | 8,652 |
| hu.MAP | 11,206 | 2,133 | 79 / 102 | 5,072 |

The union contains 19,858 accepted membership records covering 2,676 graph genes and 93 perturbation targets. The predefined primary projection policies retain 13,724 memberships covering 2,581 genes and 91 targets. hu.MAP primary eligibility uses source confidence classes 1–3; other valid classes remain in the evidence layer.

Relations retain provenance, evidence class, mapping status, source confidence, polarity, and context. Source scope is general human; K562 activity is explicitly unknown. The output adds gene–attribute memberships and keeps their source concepts separate from GO.

## Acquisition and mapping

The actual snapshot download total was 63,828,447 bytes, approximately 60.87 MiB or 23.8% of the 256 MiB budget. The run selected the versioned Reactome 98 UniProt mapping export and a shared HGNC mapping table rather than the initially suggested small GMT route.

Ambiguous or unresolved mappings were quarantined: 2,121 Reactome source rows and 454 hu.MAP source members. Five graph-gene mappings remain unresolved. These counts describe source rows/members, not unique excluded genes.

The reviewer independently reconstructed all accepted rows and verified 35 frozen files. A subsequent coordinator hash check also matched all 35 files. Review method is `source_policy_and_sample`; sampled auditing and program checks are recorded separately from individual literature verification.

## Functional representation diagnostics

Before graph construction or top-k selection:

| Primary source | Distinct co-membership gene pairs | Also above original GO Jaccard 0.1 |
|---|---:|---:|
| Reactome | 49,353 | 9,444 |
| hu.MAP | 1,361 | 416 |

These are source co-membership diagnostics. The combined GO/attribute graph and downstream predictions have not yet been generated. Next, apply declared projection policies, measure graph changes, and compare downstream models using frozen knowledge products.

## Pending work

- ENCODE: a bounded K562 metadata probe succeeded, but no processed target-linkage resource was acquired. Regulatory integration remains pending.
- Resolve quarantined mappings through a separate versioned revision.
- Promote the run-local acquisition/integration connectors into reusable project tools after review.
- Compile approved memberships into graph inputs and run matched baselines and augmentation experiments.

## Artifacts

- [Run summary](../outputs/agents/norman_task_background_002/summary.json)
- [Acquisition ledger](../outputs/agents/norman_task_background_002/acquisition_v1/retrieval_ledger.json)
- [Approved batch manifest](../outputs/agents/norman_task_background_002/overlay_v1/manifest.json)
- [Independent reviewer validation](../outputs/agents/norman_task_background_002/reviewer/independent_validation.json)
- [Reactome records](../outputs/agents/norman_task_background_002/overlay_v1/reactome_records.jsonl)
- [hu.MAP records](../outputs/agents/norman_task_background_002/overlay_v1/humap_records.jsonl)
