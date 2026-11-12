# Shared knowledge semantics

## Concept identity and evidence

Use definitions, entity type, source-curated content, molecular composition and biological scope to establish concept identity. Labels, synonyms, source cross-references and gene overlap help discover relevant concepts. Preserve distinctions in narrower mechanisms, molecular states and experimental conditions. Keep source identifiers and the evidence supporting an equivalence decision.

Maintain evidence type, source release, exact source locator, relationship semantics, polarity and biological conditions. A gene's pathway membership establishes a source-defined association; activity in a particular cell type or treatment context follows the corresponding evidence. Source membership and computationally propagated membership retain their separate meanings.

Plan one shared knowledge product across the complete scientific task and fixed gene universe. Task descriptions, biological context and external evidence determine selection. The controller freezes the product before downstream evaluation.

## Module graph relationships

Stored edges point from parent to child. Their relation and `model_edge` flag define the interpretation:

| Relation | Interpretation | Model use |
|---|---|---|
| `source_pathway_parent` | Explicit native pathway parent-to-child fact, resolved through source aliases | Eligible |
| `is_a`, `part_of` | Exact pinned ontology relationship with matching endpoints | Eligible |
| `participates_in` | The child assembly or module participates in the parent's process | Eligible |
| `model_aggregation` | Biologically explained computational grouping | Eligible |
| `related_to`, `regulates` | Typed association or regulation, with its stated scope and polarity | `model_edge=false` |

A source GO annotation supports its stated association. Definitions and source content establish equivalence, breadth and the intended edge semantics. Incoming and outgoing connections can place a new module between existing ancestors and descendants. Evaluate a root connection against the scope of the whole module and available more specific locations.

Computational gene coverage follows selected model edges. Distinguish the declared source members from additional genes reached through existing descendant modules. A model-aggregation edge preserves its computational interpretation alongside the scientific evidence.

## Review and graph ownership

An editor proposes changes; an independent reviewer assesses their biological meaning. Group-level review covers every member and expanded edge, with explicit module exceptions. The controller resolves review dependencies, checks the full transaction and commits accepted changes before the next batch starts.

Code preserves original graph nodes, edges and memberships, and validates the fixed gene universe, source references, graph revision, connectivity, model cycles and duplicate message-flow edges. Source-native edges already represented by an existing connection retain their additional evidence in the expansion receipt. Full source records and memberships remain in files.
