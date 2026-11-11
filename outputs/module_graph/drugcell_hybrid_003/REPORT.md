# Graph-aware module placement timing

Status: completed.

One shared fixed-gene graph; source memberships are joined by code and module identities/edges are proposed and independently reviewed by agents.

| Batch | Modules | Added | Reused | Deferred | Editor seconds | Reviewer seconds | Total seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid_batch_001 | 24 | 19 | 3 | 2 | 107.2 | 63.0 | 170.6 |

Added nodes by depth: {"1": 1, "2": 5, "3": 6, "5": 7}.
Added nodes directly attached to the common root: 1.
Observed total: 2.84 minutes for 24 modules.
Linear sequential estimate for 3000 catalog modules: 5.92 hours.
Linear estimate at observed sequential editor/reviewer throughput; source complexity and batch size affect runtime.


## DrugCell export

The consumer used the frozen reviewed edges. Export took 2.68 seconds; the published-threshold pruning pass took 1.80 seconds.
Added nodes retained after pruning: 5 / 19.
Reviewed actions: {"reuse": 3, "add": 19, "defer": 2}.
New edge relations: {"source_pathway_parent": 11, "model_aggregation": 7, "related_to": 1, "participates_in": 8}.
This pilot measures module placement using frozen scientific memberships and source snapshots. Acquisition time belongs to its source workflow. The full task gene universe is unchanged.


## Matched-input efficiency comparison

The task card, original graph, complete gene universe, source catalog, pinned evidence, processing module set and model/reasoning settings match the earlier pilot.

| Measurement | Earlier per-module transactions | Group recipe + code expansion |
|---|---:|---:|
| Placement wall time (minutes) | 22.90 | 2.84 |
| Agent invocations | 9 | 2 |
| Shell commands | 101 | 15 |
| Failed shell commands | 17 | 0 |
| Context bytes | 425579 | 86252 |
| Added / reused / deferred | 13 / 3 / 8 | 19 / 3 / 2 |

Observed speedup: 8.05x; wall time reduction: 87.6%.
Observed combined change in group recipes, batch size, compact context and execution configuration; single runs of the same 24 source modules. Independent biological ground-truth accuracy is outside this timing measurement.

The recipe and complete expansion are frozen with the accepted patch and independent review. Reviewer verdicts describe review outcomes; the table reports timing and graph retention.
