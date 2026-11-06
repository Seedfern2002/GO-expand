# Planner

Input: a task card and compact task context.
Output: a task-wide augmentation plan in the supplied schema.

1. Identify the knowledge families needed for the task and what its current GO inputs already represent. The framework spans multiple task types; GEARS is one consumer profile.
2. Choose source and transformation policies that apply to the complete declared gene universe. Do not narrow the run to one perturbation, a few selected genes, or one biological program.
3. For each selected family, specify bulk resources or structured queries, identifier mapping, evidence filters, context handling, deduplication, and graph-consumption rules.
4. Separate reusable human knowledge from cell-context-specific evidence. General human membership does not by itself establish activity in K562.
5. Select database integration, literature-derived augmentation, or their combination according to task knowledge needs. Use programmatic processing for complete source tables and shared evidence bundles for literature. Apply a task-level budget to the selected routes.
6. Specify source/policy review, deterministic validation of all rows, and reproducible stratified audit samples. Individual experimental claims and novel concepts require explicit evidence review.
7. Define coverage against all graph genes and separately report perturbation-target coverage. Attribute counts or downstream score changes are not stopping criteria for knowledge selection.
8. Human questions concern knowledge families, source policies, or unresolved biological semantics. They may be empty.
9. Every augmentation category must exactly match one of task.candidate_categories. Put cross-family evidence review and other workflow helpers in audit_policy.exception_routing, not in augmentations.

For task_batch, return processing recipes and audit policy, not a list of hand-curated gene relations. Keep explanations concise. The executor will produce the tables and coverage statistics.
