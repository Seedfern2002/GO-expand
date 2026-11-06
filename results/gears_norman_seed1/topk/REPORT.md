# GEARS top-k neighborhood changes

## Input and projection

- Universe: 3,127 fixed GEARS graph genes; 102 perturbation targets.
- Added attributes: 13,724 approved primary memberships from the task-wide run (Reactome and hu.MAP confidence classes 1–3).
- Projection: equal-weight set union with the original GEARS GO annotations, using a separate external namespace. Original terms and all genes are retained. No additional ontology propagation or singleton filtering.
- Similarity: Jaccard; retain scores strictly greater than 0.1.
- GEARS setting: k=20. Source code selects k+1 rows per target, usually including self. Changes below exclude self edges.
- Tie handling: upstream pandas nlargest keep-first with the same source order and CSV parsing.

## Results

| Scope | Genes | Changed neighbor sets | Unchanged | Changed percent |
|---|---:|---:|---:|---:|
| All graph genes | 3,127 | 3,053 | 74 | 97.63% |
| Perturbation targets | 102 | 99 | 3 | 97.06% |

Changed means at least one nonself neighbor was added or removed. An additional 27 genes retained their neighbor set but changed its order; one was a perturbation target.

Mean additions per gene: 4.10. Mean removals per gene: 5.60.

Nonself directed edges: 57,875 before, 53,194 after; 12,822 edges added and 17,503 removed. Attribute union can change both intersections and denominators, and the fixed 0.1 threshold can remove neighbors.

Of 546 genes with no directly added attributes, 536 changed neighbors through altered similarities to other genes.

## Checks

All original candidate gene pairs and scores matched the original-GO cache. Reconstructed selected edges matched all 60,993 edges in the trained baseline's original_graphs.pt; weights matched within float32 storage precision.

Nine original targets did not retain their self row because of tied scores. Strict top-20 selection after removing self rows gave the same changed-gene counts: 3,053 overall and 99 perturbation targets.

CPU computation time: 9.06 seconds. No model training was performed in this analysis.

## Files

- summary.json: parameters, source hashes, validation and aggregate results.
- per_gene_changes.tsv: per-gene set/ranking changes and edge counts.
- neighborhoods.jsonl: ranked neighbors, scores, additions and removals.
- changed_genes.json: changed gene names.
- original_selected_edges.csv and augmented_selected_edges.csv: directed edges including self.
- strict_nonself_top20_changes.tsv: strict nonself top-20 result.
