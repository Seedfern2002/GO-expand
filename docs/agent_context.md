# GEARS task profile for GO augmentation agents

Use English for agent communication and generated knowledge artifacts.

The project studies agent-driven task-specific GO augmentation across multiple biological tasks, with scale, generality, and biological effectiveness as its research emphasis. Database-derived rule-based integration and literature-derived augmentation are both within scope. This file describes the GEARS profile, one priority application of that framework.

## Task and scope

The task class is prediction of gene-perturbation expression responses. The current consumer is GEARS on Norman K562 CRISPRa data.

Build a shared knowledge overlay for the entire task. Human functional knowledge can be cached once and reused across datasets. K562-specific context is a separate qualifier.

The fixed perturbation graph has 3,127 genes, including 102 eligible experimental perturbation targets. All graph genes are eligible for augmentation. The target list is a reporting subset, not a selection boundary. Screen the full universe for every selected knowledge family.

The task card points to gene/condition metadata exported without expression values. Read metadata through programs and print only counts or small samples.

## Existing model inputs

GEARS uses gene-GO term sets to compute Jaccard similarity. Pair scores above 0.1 are retained, then each target selects its top k+1 entries (k=20; usually including self). A separate coexpression graph is also used.

The original annotation source is data/raw/gears/gene2go_all.pkl. The fixed GEARS checkout is f374e43e197b295016d80395d7a54ddb81cc6769.

Keep the gene universe, coexpression graph, split, and training recipe fixed when comparing knowledge variants. Freeze the knowledge overlay before downstream evaluation.

## Knowledge families and bulk processing

Consider pathway membership, protein complexes, and context-specific regulatory programs across the complete universe.

A source table can generate many gene-attribute associations through one validated transformation. Review the source and mapping policy, run checks on all rows, and audit reproducible samples. Literature-derived augmentation can independently supply task-relevant associations or context, complement source tables, or resolve evidence gaps, according to the chosen plan.

Curated pathway membership, predicted complexes, transcription-factor binding, and experimentally supported regulation have different semantics. Retain the source's evidence class and confidence.

Human membership alone does not establish activity in K562. Preserve isoforms, cofactors, experimental treatments, relationship direction, and negation.

Use existing stable concepts where appropriate. Keep external attributes in a separate namespace and explicitly measure overlap with GO. Membership attributes can enter a set-based projection; signed regulatory statements require a declared compatible representation.

## Artifact handling

The task_batch workflow returns compact manifests. Normalized tables, evidence indexes, validation reports, and coverage reports remain on disk.

The current batch contracts and stage validation are scaffolding for source connectors. A manifest is valid only when its referenced artifacts exist and match their hashes. Report a missing connector as pending rather than inventing a batch.

Keep source snapshots versioned. Reuse processed sources and evidence bundles. Do not re-open the same paper for every related gene.

Downstream responses, predictions, and evaluation metrics are not knowledge-selection inputs. Do not start training or interfere with existing compute processes.
