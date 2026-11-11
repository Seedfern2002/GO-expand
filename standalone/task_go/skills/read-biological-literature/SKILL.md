---
name: read-biological-literature
description: Search, screen and read primary biological literature in iterative task-wide bundles, extracting source-grounded GO annotations and typed mechanisms with experimental context.
---

# Read biological literature

Build a shared body of biological evidence for the task's knowledge questions. Organize discovery by mechanisms, pathways, complexes and biological context across the fixed gene universe.

## Discover and screen

Choose queries that address an open question in the plan. Use source-native bulk discovery where useful, then inspect returned titles, abstracts and study identities to choose the next reading bundle. Refine searches with terminology and relevant primary citations encountered during reading.

Read the Abstract of each paper counted as inspected. Record its task relevance, primary-study status, available text and screening decision. DOI, PMID and PMCID aliases identify one paper across sources and rounds. Reviews can support discovery and citation expansion; experimental assertions retain their primary-study evidence.

## Read for a concrete biological claim

Select Results, figure-associated text and Methods passages that resolve the association, experimental system or mechanism under consideration. State why deeper reading is useful: identifying complex components, checking direction or polarity, resolving a construct, interpreting an assay, or distinguishing a result from background discussion.

Expose the needed scientific passages through the available tools. Relate each claim to its gene identity, source-defined concept, relationship, assay, molecular form and experimental condition. A paper can support multiple claims and knowledge families; reuse the saved text and extract its supported task-relevant observations together. Broader gene membership draws on additional source evidence.

## Extract, inspect progress and continue

Prepare typed claims with exact quotations, scientific locators and source hashes. Preserve observations, interpretations and hypotheses as their declared assertion types. Check identifiers against the task's supplied ontology and mapping resources. Save publication identities and original terminology with the evidence. In task-only acquisition, hand supported claims to the add-go-knowledge procedure selected by the acquisition prompt for query, concept resolution, proposal and batch materialization.

After each paper bundle, update the reading ledger, coverage gaps and candidate counts. Reuse cached papers and previously inspected passages; return for additional body sections or supplementary material when a question requires them. In planner_adaptive mode, use the Planner's questions, initial reading volume and stopping criteria within resource ceilings. In fixed-target mode, work toward the declared inspected-paper and full-text targets. The runtime's round instructions define the active mode and its continuation interface. Report the achieved scope and concrete stopping reason.

Keep paper discovery, downloaded documents, observed abstract/body inspections and evidence-contributing studies as separate counts. The runtime's round interface defines required passages and ledger fields; use its checker before handing off a round. Keep full collections in files and return compact manifests.
