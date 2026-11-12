# Group review interface

Return `batch_id`, `graph_revision` and `groups`, with exactly one verdict for each proposed group. A group verdict contains `group_id`, `verdict` (`accept` or `defer`), `reason` and `exceptions`.

The group verdict covers every member and expanded edge. `exceptions` contains unique members of that group with `module_id`, `verdict` and `reason` when a member needs a different verdict. Include an empty exceptions array when the verdict applies uniformly. Preserve explicit deferrals proposed by the editor when their evidence remains insufficient.

The context includes `proposed_recipe`, `complete_expansion` and `compiled_transaction_path`. Review all group rules, identity exceptions, native and cross-source connections, preserved source-edge receipts and complete declared mappings. The controller expands group verdicts to every module before dependency checking. A deferred dependency holds affected edits. Accepted commits become the next batch's graph revision.
