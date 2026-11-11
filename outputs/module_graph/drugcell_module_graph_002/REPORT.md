# Graph-aware module placement timing

Status: completed.

One shared fixed-gene graph; source memberships are joined by code and module identities/edges are proposed and independently reviewed by agents.

| Batch | Modules | Added | Reused | Deferred | Editor seconds | Reviewer seconds | Total seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| module_batch_001 | 8 | 5 | 3 | 0 | 186.8 | 129.1 | 316.3 |
| module_batch_002 | 8 | 0 | 0 | 8 | 214.5 | 177.4 | 392.3 |
| module_batch_003 | 8 | 8 | 0 | 0 | 245.0 | 420.0 | 665.5 |

Added nodes by depth: {"2": 2, "3": 5, "5": 6}.
Added nodes directly attached to the common root: 0.
Observed total: 22.90 minutes for 24 modules.
Linear sequential estimate for 3000 catalog modules: 47.71 hours.
Linear estimate at observed sequential editor/reviewer throughput; source complexity and batch size affect runtime.


## DrugCell export

The consumer used the frozen reviewed edges. Export took 2.64 seconds; the published-threshold pruning pass took 1.73 seconds.
Added nodes retained after pruning: 1 / 13.
Reviewed actions: {"reuse": 3, "add": 13, "defer": 8}.
New edge relations: {"source_pathway_parent": 5, "model_aggregation": 3, "participates_in": 9, "related_to": 6}.
This pilot measures module placement using frozen scientific memberships and source snapshots. Acquisition time belongs to its source workflow. The full task gene universe is unchanged.

## Timing version and implementation checks

The measured run includes 3 interface-repair calls (4.78 minutes) and 17 failed shell calls, of which 10 arose from the nested execution boundary. These calls remain included in the reported wall time.

The final source configuration uses the verified outer execution boundary, available python/rg tool paths, explicit inspected-concept field guidance and compact module-definition references. These changes have separate preflight receipts; the timing run retains its original source snapshot.

Implementation checks: 47 standalone graph/boundary tests and 57 DrugCell tests passed. A live agent preflight completed two shell queries with zero failed commands. On the complex batch, shared definition references reduced context bytes by 49.8%, with complete evidence retained in files.
