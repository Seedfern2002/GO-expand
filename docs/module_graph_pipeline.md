# Graph-aware functional module augmentation

The module-placement workflow adds explicit, reviewed structure to the task's functional graph. Source membership parsing produces a scientific module catalog; agents decide concept identity, biological scope and graph connections in coherent batches. Membership tables remain in files and are joined by code.

## Interfaces

- [Module launcher](../standalone/task_go/launch_modules.py) accepts a scientific task card, fixed genes, annotations, original functional graph, source module catalog, pinned evidence, source snapshots and processing partitions.
- [Graph context and transactions](../standalone/task_go/engine/module_graph.py) provide neighborhoods, source annotations, name/overlap retrieval candidates, revision binding, concept aliases, membership joins and model-DAG checks.
- [Graph query CLI](../standalone/task_go/graph_ops.py) supports module, concept and label queries.
- [Placement controller](../standalone/task_go/place_modules.py) runs an editor and an independent reviewer per batch, commits accepted edits and records timings.
- [Placement skill](../standalone/task_go/skills/place-functional-modules/SKILL.md) defines the Editor's graph proposal procedure; [review skill](../standalone/task_go/skills/review-functional-modules/SKILL.md) defines the independent Reviewer's assessment. Role prompts select the role and active interface.
- [Instruction loader](../standalone/task_go/engine/module_prompts.py) embeds each role's assigned skill, the shared scientific conventions and its active interface reference, with versioned instruction receipts.
- [DrugCell consumer](../scripts/export_drugcell_module_graph.py) reads the frozen reviewed graph, preserves the released ontology bytes and uses the explicitly selected model edges. It retains typed provenance and excludes associative/regulatory edges from the model hierarchy.

DrugCell experiment configuration selects this consumer through `knowledge.module_graph_product`. Initialization pins its freeze hash in `module_graph_freeze_sha256`, copies the consumer into the frozen code bundle and records the reviewed-edge projection policy. Preparation verifies the scientific task, fixed genes, original hierarchy and graph freeze before export. Existing frozen experiments retain their original projection policy.

## Graph decisions and semantics

Each module receives an `add`, `reuse` or `defer` decision. Reuse preserves its source identifier through an alias and joins its declared members to an existing biologically equivalent concept. Addition introduces a source-identified node and incident edges. Deferred modules and dependent edits retain their reasons for a subsequent revision.

Edges preserve native pathway hierarchy, ontology relations, process participation, computational aggregation or associative/regulatory meaning. `model_edge` selects message-flow edges; computational propagation through these edges is distinct from GO annotation entailment. Native hierarchy claims require matching pinned source endpoints after alias resolution. Each proposed connection has evidence identifiers and a biological rationale. Root attachment is an explicit per-module decision.

The controller checks all modules in a transaction together. It preserves the original graph, fixed gene universe and existing memberships; validates evidence references, scope of edited endpoints, model connectivity, cycles and duplicate parent-child message-flow edges; and binds the commit to the current graph revision. An independent reviewer judges biological equivalence and placement. A deferred dependency holds its affected edits.

## Scientific inputs and runtime

The graph stage receives scientific definitions, source-derived memberships, original functional structure and external evidence. Source snapshots have exact row locators and checksums. Host paths and preparation receipts remain outside the agent workspace; source files are copied under generic local names. Plans, prior agent conversations and downstream experiment results stay outside the mounted workspace.

The outer bubblewrap environment mounts the private task workspace and system/backend runtime. Scientific inputs and pipeline code have read-only mounts. The final backend configuration executes command tools inside that externally isolated environment; it checks those mounts before invoking an agent. The current graph is controller-owned and checked for alteration before commit. The final configuration has a live two-command query preflight in addition to structural and input-boundary tests.

Module context packets contain definitions, source-bound facts and compact candidate neighborhoods. Repeated copies of a module definition use a shared reference; the complete evidence remains in the pinned files. Every batch begins from the graph committed by the preceding batch.

## Roles and skills

The Planner defines task-wide biological questions, source directions and acquisition budgets through its role prompt. Acquisition skills support source integration and evidence-backed candidate publication. Graph placement and graph review use separate skills:

| Role or operation | Procedure |
|---|---|
| Database integration | [integrate-biological-sources](../standalone/task_go/skills/integrate-biological-sources/SKILL.md) |
| Literature reading | [read-biological-literature](../standalone/task_go/skills/read-biological-literature/SKILL.md) |
| Candidate knowledge publication | [add-go-knowledge](../standalone/task_go/skills/add-go-knowledge/SKILL.md) |
| Acquired-claim review | [review-biological-evidence](../standalone/task_go/skills/review-biological-evidence/SKILL.md) |
| Module Editor | [place-functional-modules](../standalone/task_go/skills/place-functional-modules/SKILL.md) |
| Module Reviewer | [review-functional-modules](../standalone/task_go/skills/review-functional-modules/SKILL.md) |

The skills share [concept, evidence and graph relationship conventions](../standalone/task_go/references/knowledge_semantics.md). Each module-agent invocation embeds its assigned skill and the one active interface reference: group recipe/review for `module_recipes`, or per-module transaction/review for `module_placement`. This makes the method directly available in the first prompt. The role prompts stay focused on role, batch and output responsibilities.

Each graph batch follows Editor proposal, deterministic expansion and validation, independent Reviewer assessment, dependency filtering, and controller commit. The next batch receives the committed graph. Group verdicts cover all members and edges, with explicit module exceptions. Final freezing follows all batch commits.

Per-invocation `instruction_manifest.json` records the role, active interface, assigned skill, resource checksums and executed prompt checksum. The launch receipt records the selected role-resource mapping. `knowledge_graph/instructions.json` collects verified invocation receipts and is hashed in the graph freeze manifest alongside the graph and validation artifacts.

## DrugCell timing pilot

The pilot uses the released 2,086-node DrugCell graph and the complete 3,008-gene universe. Its 3,000-module scientific catalog comes from a frozen membership product and pinned external sources. Three processing batches contain eight modules each: DNA repair pathways, cell-cycle pathways and protein assemblies. The experiment measures graph placement and review; source acquisition belongs to the parent scientific workflow.

- [Pilot plan](../outputs/module_graph/drugcell_module_graph_002/PLAN.md)
- [Scientific input lineage](../outputs/module_graph/drugcell_module_graph_002/scientific_input_lineage.json)
- [Timing and exported-graph report](../outputs/module_graph/drugcell_module_graph_002/REPORT.md)
- [Implementation checks](../outputs/module_graph/drugcell_module_graph_002/implementation_checks.json)

The run freezes its pipeline snapshot, prompts, input hashes and per-stage event logs. The first prototype records are retained separately. The timing snapshot includes its interface-repair calls and tool retries. Subsequent context compaction and runtime preflight are recorded separately; they preserve the timing run's original evidence and logs.

Frozen graph export and the DrugCell pruning pass run after the pilot completes. They produce structural counts and elapsed times. Downstream training is a separate invocation.

## Group recipes and code expansion

The optional `--workflow module_recipes` path lets the editor choose coherent module groups, concept reuse, source-native hierarchy expansion, shared incoming anchors and individual connection or deferral exceptions. Groups partition the entire supplied processing batch. Each active module defaults to a source-identified addition with its complete declared membership; reuse and deferral are explicit exceptions.

The [recipe compiler](../standalone/task_go/engine/module_recipes.py) expands only those approved scopes. Each native edge comes from an exact pinned source fact. Aliases resolve reused concepts; existing model connections remain unique and their additional source evidence is retained in the expansion receipt. Shared anchors expand to the explicitly listed modules. The complete expanded patch passes the original transactional graph checks.

The independent reviewer receives every module definition, all expanded edges, preserved connection receipts and complete membership counts. Group verdicts cover every member; module exceptions can hold an individual placement. Review coverage is expanded deterministically to every module before dependency checking and commit. The frozen product pins the recipe and expansion receipt alongside accepted edits and review output.

Recipe context deduplicates shared evidence and source-annotated graph definitions. Paginated label queries, multi-concept queries and parent/child neighborhood offsets let agents explore the original graph. All input graph locations remain queryable. Large membership lists and complete source records stay in files.

The matched-input timing experiment processes the same 24 source modules in one batch, using the same task, graph, 3,008 genes, catalog, evidence and model/reasoning settings. Its host-side collector compares observed time, invocation counts, tool calls, context bytes and review outcomes with the frozen earlier run. This measures the combined effect of group recipes, larger batches, compact context and the corrected execution configuration. The comparison artifacts stay outside the task-only agent workspace.

- [Timing experiment plan](../outputs/module_graph/drugcell_hybrid_003/PLAN.md)
- [Timing and graph export report](../outputs/module_graph/drugcell_hybrid_003/REPORT.md)
- [Live collection status](../outputs/module_graph/drugcell_hybrid_003/status.json)

## Role-specific skill live test

The role-specific skill test processes the same 24 modules in one batch, with identical scientific inputs and model/reasoning settings. Its editor and reviewer execute in separate ephemeral sessions. The frozen graph includes verified instruction receipts for both skills, shared scientific conventions and active interface references.

The observed run took 220.04 seconds, compared with 170.61 seconds for the preceding group-recipe run. Both used two agent sessions. The current run produced 20 additions, two reuses and two deferrals; seven added nodes survived the same DrugCell pruning pass. Module action and target agreed in 23 of 24 cases. The current proposal retains the narrower APC/C-mediated regulatory pathway as a separate source node and preserves the Cell Cycle parent through pruning. Detailed timing, decisions and projection counts are recorded in the report.

- [Live test report](../outputs/module_graph/drugcell_skills_004/REPORT.md)
- [Verified skill receipts and structure checks](../outputs/module_graph/drugcell_skills_004/live_skill_checks.json)
- [Module decision comparison](../outputs/module_graph/drugcell_skills_004/module_decision_comparison.tsv)

## Complete GO database run before pruning

The complete-GO experiment starts from all 23,974 active Biological Process terms in GO release 2026-07-26, including 13,409 terms with zero current measured-gene coverage. Positive human UniProt GO annotations and a pinned HGNC crosswalk map 2,984 of the 3,008 measured genes. The graph keeps the full measured universe and marks its coverage policy as `allow_unannotated`. GO `is_a` and `part_of` form model edges; other supplied GO relationships retain their typed scientific meaning.

All 2,999 eligible database modules are processed in 125 batches. The catalog is rebuilt from database-derived Reactome and Complex Portal records, with each membership checked against its raw source row and identifier crosswalk. Complete source processing and exact provenance are recorded in the database lineage. The literature-acquisition budget is zero. Partitioning covers every module once and orders native parents ahead of their children.

Committed batches have per-batch timing receipts and can be replay-verified on resume. Failed attempts retain separate artifacts and use a bounded retry budget. The final graph freeze also publishes its reviewed computational memberships in the scientific knowledge format consumed by the evaluation scheduler.

Both the unaugmented complete GO and frozen augmented graph receive the same DrugCell pruning after augmentation completes. Separate identifier-bound projections select each model's annotated genes from the original mutation matrix. This supports different model gene counts while retaining the same measured feature source, cell and drug identifiers, response rows and grouped folds. The paired control is trained from the complete-GO pruning product; the released DrugCell baseline is retained as a historical reference.

The detached evaluation queue verifies both freezes, prepares the ontologies and gene projections, checks both CPU model paths, then schedules five folds per arm with 300 epochs and validation-Pearson checkpoint selection. Up to five jobs use stably unoccupied GPUs under the shared lock policy.

- [Full-GO source manifest](../outputs/module_graph/drugcell_full_go_base_006/full_go_manifest.json)
- [Database-only lineage](../outputs/module_graph/drugcell_full_go_database_006/database_lineage.json)
- [Live full-workflow report](../outputs/module_graph/drugcell_full_go_database_006/REPORT.md)
- [Evaluation protocol](../outputs/drugcell/evaluation_006_full_go_database/PLAN.md)
- [Live evaluation queue](../outputs/drugcell/evaluation_006_full_go_database/status.json)
