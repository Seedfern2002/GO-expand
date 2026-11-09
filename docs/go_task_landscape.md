# GO application tasks for evaluating task-specific augmentation

Survey date: 2026-11-07. Scope: primary papers and author-released code/data, emphasizing Nature Portfolio, Cancer Cell, Cell Systems and Genome Biology. The survey also retains specialist papers with particularly direct GO-selection comparisons. Task interfaces and project priorities below are our assessments; publication facts are identified separately. Literature verification is complete for the described claims; dataset execution and model reproduction remain implementation work.

The [structured candidate table](go_task_candidates.tsv) contains 22 model/resource entries with endpoint families, GO interfaces, metrics, access conditions and primary links.

The project objective is one augmentation framework that constructs task-specific knowledge products across distinct biological endpoint families. Different datasets, cancer types, consumers or train/test splits broaden a family. We count endpoint families separately from the number of models.

## Main findings

- Direct, prediction-oriented GO reduction precedents include ParsVNN and GOAE/GONN. DrugCell, DCell, SparseGO and CellGO document ontology filtering. MultiOme sparsifies a GO-derived gene network; Bioteque filters general ontology concepts.
- Strong venues provide direct GO-input consumers for drug response, mutant fitness, synthetic lethality, disease-gene prioritization, gene constraint and molecular properties. These offer several nontranscriptomic targets in addition to GEARS.
- Morphological perturbation atlases provide measured cellular phenotypes at genome scale. A GO-to-morphology predictor or retrieval interface would be our added consumer.
- GO-backed interpretation and enrichment have established benchmarks. Their evaluation labels and experimental inputs need to be described individually: an experimental gene-set retrieval benchmark and a GO-label recovery benchmark measure different quantities.

## Reduction and pruning precedents

| Work | Venue/year | Processing object | What the publication establishes | Task for an augmentation comparison |
|---|---|---|---|---|
| [ParsVNN](https://academic.oup.com/nargab/article/3/4/lqab097/6412605) | NAR Genomics and Bioinformatics, 2021 | Learned pruning of gene–subsystem and subsystem–subsystem connectivity in a GO-derived VNN | Cancer-specific sparse models improve drug-response prediction in four of five cancer settings; one is statistically comparable | Cancer-specific drug-response regression |
| [GOAE/GONN](https://link.springer.com/article/10.1186/s12859-019-2769-6) | BMC Bioinformatics, 2019 | GO term selection by hierarchy level, gene-set redundancy and expression diversity | Explicit term-selection comparison improves clustering metrics | scRNA-seq representation, clustering and retrieval |
| [DrugCell](https://doi.org/10.1016/j.ccell.2020.09.014) | Cancer Cell, 2020 | GO-BP term coverage, parent–child redundancy and hierarchy depth | Defines a filtered GO predictive architecture; the effect of filtering alone is not isolated | Drug response and combination follow-up |
| [DCell](https://www.nature.com/articles/nmeth.4627) | Nature Methods, 2018 | Evidence filtering, small terms and terms redundant with children | Uses a filtered hierarchy to predict mutant phenotypes and compares alternative ontologies | Yeast growth and genetic interactions |
| [SparseGO](https://pmc.ncbi.nlm.nih.gov/articles/PMC10474372/) | eBioMedicine, 2023 | Hierarchy filtering and sparse neural implementation | Efficient GO-based drug prediction under several generalization settings | Drug response; mechanism-of-action classification |
| [MultiOme](https://www.nature.com/articles/s41467-021-26674-1) | Nature Communications, 2021 | Backbone extraction from GO-derived similarity graphs; relevant multiplex-layer selection | Layer selection improves disease-gene retrieval; the GO-backbone intervention is a preprocessing component | Rare-disease gene prioritization |
| [Bioteque](https://www.nature.com/articles/s41467-022-33026-0) | Nature Communications, 2022 | Ontology propagation, identifier mapping and removal of overly general concepts | Provides reusable descriptors and multiple biological applications | Interactome assessment and drug-related prediction |
| [CellGO](https://doi.org/10.1093/bib/bbad417) | Briefings in Bioinformatics, 2024 | Species-specific GO filtering and subtree models | GO-constrained models classify cells and characterize functional programs | Cell labels and context-specific functional interpretation |

ParsVNN's venue is **NAR Genomics and Bioinformatics**. Its abbreviation should remain distinct from Nucleic Acids Research. SparseGO's sparsity includes efficient matrix implementation. GO Trimming and REVIGO reduce enrichment-result redundancy and belong to the interpretation baseline family.

## Direct GO-input tasks with biological targets

### Drug response: DrugCell, ParsVNN and SparseGO

**Publication facts.** DrugCell uses GO-BP connectivity in its genotype branch and compound fingerprints in a drug branch. CTRPv2/GDSC supply 509,294 measured pairs across 1,235 cell lines and 684 compounds. It selects 3,008 input genes and builds 2,086 subsystems after coverage, redundancy and depth filtering. Original evaluation uses five-fold pair-level splits and Spearman correlation. Code: [idekerlab/DrugCell](https://github.com/idekerlab/DrugCell). [Primary paper](https://doi.org/10.1016/j.ccell.2020.09.014).

ParsVNN uses cancer-specific response data to prune that hierarchy. Its five cancer settings use an 80/20 pair split and training-only five-fold tuning; the main metric is Pearson correlation against measured dose-response AUC. Code: [EJIUB/ParsVNN](https://github.com/EJIUB/ParsVNN). [Primary paper](https://academic.oup.com/nargab/article/3/4/lqab097/6412605).

SparseGO extends the practical evaluation to held-out cell lines and compounds, with external PRISM evaluation. Its ontology text file explicitly represents term–term and gene–term links. Mechanism-of-action classification provides a related pharmacology endpoint. Code/data: [KatynaSada/SparseGO](https://github.com/KatynaSada/SparseGO). [Primary paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10474372/).

**Project interface.** Freeze an augmented gene–term map and hierarchy, then build each fixed consumer on that input. Preserve the mutation/expression universe, drug branch, response labels and split definitions. Original-GO, original filtering/pruning, augmented-GO and augmented-then-pruned variants answer different comparisons. These models and cancer subsets constitute one drug-response family, with separate generalization axes.

**Assessment.** High priority: a strong biological venue, direct pruning comparators and public model interfaces coexist here. New ontology nodes change model capacity, so architecture size and knowledge content need separate controls.

### Mutant fitness and genetic interaction: DCell and Ontotype

**Publication facts.** [DCell, Nature Methods 2018](https://www.nature.com/articles/nmeth.4627), builds a VNN directly from GO or CliXO and predicts yeast growth/genetic-interaction phenotypes. The filtered GO has 2,526 subsystems. Small and child-redundant terms are removed, and IGI-supported information is excluded for the interaction evaluation. Original implementation uses Torch7. Code/data: [idekerlab/DCell](https://github.com/idekerlab/DCell/).

[Ontotype, Cell Systems 2016](https://doi.org/10.1016/j.cels.2016.02.003), propagates disrupted genes through GO and uses subsystem counts in random-forest regression. It includes experimental follow-up on 2,503 new double knockouts. Code: [michaelkyu/ontotype](https://github.com/michaelkyu/ontotype).

**Project interface.** Replace the frozen yeast annotation/DAG input; retain genotype and measured growth/interaction targets. Record correlations and negative-interaction precision–recall using the original task protocol. The related [Costanzo Science 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC5661885/) interaction map provides a large experimental resource, available through [TheCellMap](http://thecellmap.org/costanzo2016/) and [Dryad](https://doi.org/10.5061/dryad.4291s).

**Assessment.** High biological value: a different organism and a direct fitness readout. Ontotype gives a comparatively simple consumer; DCell adds an architecture-level consumer. Exact archived split files and runtime compatibility need to be pinned during implementation.

### Human synthetic lethality: BioPathNet and a dedicated benchmark

**Publication facts.** [BioPathNet, Nature Biomedical Engineering 2026](https://www.nature.com/articles/s41551-025-01598-z), includes synthetic-lethality prediction from SynLethDB/KR4SL. Its background graph explicitly contains GO-BP/MF/CC associations. The final paper evaluates transductive and gene-inductive settings, using MRR and Hits@1/3/10. Code/download scripts: [emyyue/BioPathNet](https://github.com/emyyue/BioPathNet). GO is part of the background knowledge; SL pairs are the supervised target.

The [Nature Communications 2024 SL benchmark](https://www.nature.com/articles/s41467-024-52900-7) evaluates 12 methods with different gene/pair splits and negative-sampling settings. Classification metrics are AUROC, AUPR and F1; ranking metrics are NDCG@K, Recall@K and Precision@K. Use its [2025 author correction](https://doi.org/10.1038/s41467-025-56368-x) with the updated article.

**Project interface.** Replace or extend the GO background relations while retaining SL labels, background non-GO relations, model and splits. Compare observed interaction labels separately from computationally generated labels when assembling the external evaluation.

**Assessment.** High priority: major-journal precedent, explicit GO input and cancer-relevant pairwise biology. It evaluates a distinct output from transcriptional response.

### Rare-disease gene ranking: MultiOme

**Publication facts.** [MultiOme, Nature Communications 2021](https://www.nature.com/articles/s41467-021-26674-1), constructs GO-BP/MF gene networks from Resnik/BMA semantic similarity, removes root-only matches and applies disparity filtering. The multiplex has 46 layers. Relevant-layer selection improves median disease-retrieval AUROC from 0.86 to 0.90. Evaluation includes ten-fold disease-gene retrieval and a 139-patient cohort; the reported top-five statistic uses 131 evaluable cases. Code/networks: [menchelab/MultiOme](https://github.com/menchelab/MultiOme). Patient-level GPAP data have controlled access.

**Project interface.** Recompute only GO-derived layers from frozen augmented annotations/DAG; keep other layers and propagation fixed. Original AUROC and causal-gene ranks are appropriate reproduction outputs; Hits@K/MRR can be additional declared ranking summaries.

**Assessment.** High priority for broadening biology beyond cell assays. Public disease-gene retrieval is the accessible starting task; patient validation has a separate access requirement. The paper supports task-specific network selection, while its reported gain does not isolate GO pruning alone.

### Human gene constraint and phenotypic gene prioritization: GeneBayes

**Publication facts.** [GeneBayes, Nature Genetics 2024](https://www.nature.com/articles/s41588-024-01820-9), combines population-genetic likelihoods with learned priors from gene features, including GO. Evaluations include held-out-gene likelihood/correlation, cell-essentiality and developmental-disorder gene precision–recall. Code and released feature/likelihood files: [tkzeng/GeneBayes](https://github.com/tkzeng/GeneBayes). The paper's correlation-based feature pruning is used for interpretation; its purpose and reported evidence differ from prediction-directed ontology pruning.

**Project interface.** Replace the GO feature block while preserving non-GO features, likelihood model and evaluation labels. Assess the GO-only block and the full-feature model separately to expose its contribution. Posterior constraint scores and external phenotype labels provide complementary readouts.

**Assessment.** High priority for task diversity and venue quality; moderate implementation effort because the consumer is a feature model rather than a gene GNN. Availability of processed features/likelihoods enables a different workflow from rebuilding population-variant processing.

### Molecular-property prediction: LitGene

**Publication facts.** [LitGene, Nature Communications, accepted manuscript published 16 October 2026](https://www.nature.com/articles/s41467-026-78454-4), uses gene–GO triplets for contrastive representation learning. Its eight endpoints include solubility, two chromatin-state classifications, dosage sensitivity, localization, conservation and two TF-property classifications. They are separate evaluations from GO/KEGG retrieval. Code: [vinash85/LitGene](https://github.com/vinash85/LitGene); [archive](https://doi.org/10.5281/zenodo.22047782); [checkpoint](https://huggingface.co/tumorailab/LitGene_ContrastiveLearning/tree/main). One linked training-data endpoint returned authorization-required status during this survey; archive access needs reconciliation.

**Project interface.** Rebuild contrastive triplets from augmented GO and rerun that stage before matched downstream classification/regression. Keep gene-summary text, endpoint labels and splits fixed.

**Assessment.** A promising recent extension with several biological properties. Contrastive retraining and data-access verification are prerequisites for a clean comparison.

### Single-cell tasks and graph transfer: scLong

**Publication facts.** [scLong, Nature Communications 2026](https://www.nature.com/articles/s41467-026-69102-y), encodes a GO-Jaccard gene graph using a GCN, making its input representation closely related to GEARS. Its evaluations span genetic/chemical perturbation, cancer drug response, GRN inference and batch integration. GO-removal/random-GO ablations are reported for perturbation, GRN and integration. Code and task folders: [BaiDing1234/scLong](https://github.com/BaiDing1234/scLong).

**Project interface.** Supply an augmented gene graph to the GO encoder, with an explicitly matched adaptation protocol. GO enters pretraining, so checkpoint/graph compatibility and the amount of retraining are part of the comparison. Use task-specific metrics such as perturbation errors, GRN precision–recall and batch/biological conservation scores.

**Assessment.** Strong cross-consumer extension and several endpoint options. Its billion-parameter backbone makes implementation and compute substantially larger than the current GEARS experiment. Several scLong consumers on one perturbation dataset count as cross-model evidence within that task.

### Cell type/state annotation: specialist GO-native consumers

[CellGO, Briefings in Bioinformatics 2024](https://doi.org/10.1093/bib/bbad417), uses filtered GO subtrees for cell-label prediction and functional interpretation across 71 single-cell datasets. [scGO, Briefings in Bioinformatics 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC11737892/), directly uses gene–GO sparse masks with TF information for cell-type/state applications. Code: [cellgopy](https://github.com/FduZhuLab/cellgopy), [scGO](https://github.com/yulab2021/scGO). Accuracy, F1 and AUROC are relevant to their classification protocols. A frozen mask can be exchanged while expression inputs, TF data and splits remain fixed. Their specialist venues accompany a particularly direct technical interface.

[GOAE/GONN, BMC Bioinformatics 2019](https://link.springer.com/article/10.1186/s12859-019-2769-6), provides an explicit term-selection comparison: 1,486 terms reduce to 854 using overlap/diversity filters, with ARI/NMI comparisons and cell-retrieval MAP. The displayed GOAE before/after settings also change optimization parameters; the GONN comparison is the cleaner fixed-setting term-selection example. A release repository was not identified on the article page.

## Independent experimental readouts with a proposed GO consumer

### Morphology: MorphMap, PERISCOPE and chemical–genetic matching

**Publication facts.** [MorphMap, Nature Methods 2025](https://www.nature.com/articles/s41592-025-02753-9), profiles under/overexpression for 15,243 human genes. Processed profiles and [analysis code](https://github.com/jump-cellpainting/2025_Chandrasekaran_NatureMethods_MorphMap) are public. Its analyses use phenotype similarities and functional-neighbor retrieval, including mAP against several annotation resources.

[PERISCOPE, Nature Methods 2025](https://www.nature.com/articles/s41592-024-02537-7), provides genome-wide HeLa/A549 perturbation morphology and over 30 million assigned cell images. Profiles are in Cell Painting Gallery cpg0021-periscope; [code](https://github.com/broadinstitute/2022_PERISCOPE) is public. These papers use GO mainly for interpretation/reference rather than as their predictive input.

[CPJUMP1, Nature Methods 2024](https://www.nature.com/articles/s41592-024-02241-6), benchmarks matched chemical, CRISPR and ORF perturbations using AP/mAP and fraction retrieved. [Benchmark code](https://github.com/jump-cellpainting/2024_Chandrasekaran_NatureMethods/tree/6ba3fcd1495d9e844e4607373a568641981ffcd8/benchmark) is public.

**Project interface—inference.** Use frozen GO features to predict held-out morphology profiles, rank phenotype-similar genes or support held-out chemical–genetic matching. Score against measured profiles/matches. Public processed profiles allow evaluation without retraining an image encoder. Recovery of imported CORUM/GO memberships is a separate annotation-recovery quantity.

**Assessment.** High-value independent phenotype family; the consumer and split/metric protocol require explicit definition by this project. MorphMap and PERISCOPE broaden cell and assay contexts within this family.

## Functional relevance, interpretation and enrichment

### GeneWalk

[GeneWalk, Genome Biology 2021](https://link.springer.com/article/10.1186/s13059-021-02264-8), ranks context-relevant gene functions using a network with GO annotations and term relations. Qki-deficient oligodendrocytes and JQ1-treated cells supply evaluation contexts; relevant gene–GO pairs were curated from experiment publications. AUROC and per-gene rank agreement are reported. Code: [churchmanlab/genewalk](https://github.com/churchmanlab/genewalk). A frozen GO network is a direct exchangeable input. This measures context-specific functional relevance, with publication-derived GO relevance labels.

### Gene-set interpretation: GeneAgent and GSAI

[GeneAgent, Nature Methods 2025](https://www.nature.com/articles/s41592-025-02748-6), verifies gene-set interpretations through domain databases. Benchmarks include GO, MSigDB, NeST and article-derived gene sets; semantic/text and expert assessments are reported. [Code/data](https://github.com/ncbi-nlp/GeneAgent) are public. The underlying GO-backed source is a possible augmentation interface for a fixed interpreter; the role and provenance of each test-set label should be retained.

[Evaluation of large language models for discovery of gene set function, Nature Methods 2024](https://www.nature.com/articles/s41592-024-02525-x), includes GO name recovery and interpretation of omics-derived gene sets, with independent review of supporting statements. [Code](https://github.com/idekerlab/llm_evaluation_for_gene_set_interpretation) is public. GO-name recovery and biological verification of omics explanations supply different evaluation outputs.

**Assessment.** Useful explanation endpoints for an augmented knowledge base. A fixed evaluator and fixed biological evidence targets help separate improved source knowledge from changes to the interpreter itself.

### PET/Benchmark

[PET and Benchmark, Nature Communications 2024](https://www.nature.com/articles/s41467-024-51859-9), compares experimental gene sets across contexts, such as a TF-bound set in K562 against its counterpart in HepG2. The public Benchmark uses approximately 1,000 ENCODE-derived experiments; outputs include correct-target rank, P@10/AP@10, null FDR and robustness to gene replacement. [Code](https://github.com/hedgehug/Benchmark) and [Figshare release](https://doi.org/10.6084/m9.figshare.c.7252324) are public.

**Project interface—inference.** Evaluate GO-based gene-set representations against the fixed experimental cross-context matches, or exchange a GO GMT library in a separately specified enrichment task. The core published Benchmark matches experimental sets, so its target construction should be preserved when describing an adapter.

## Additional high-venue applications and access considerations

- [Bioteque, Nature Communications 2022](https://www.nature.com/articles/s41467-022-33026-0): GO-related KG descriptors can be exchanged before downstream consumers. The published resource includes interactome assessment, drug response and repurposing; exact metapath dependence on the changed GO relations must be checked per endpoint. [Resource and processing scripts](https://bioteque.irbbarcelona.org).
- [Machine learning in Alzheimer's disease genetics, Nature Communications 2025](https://www.nature.com/articles/s41467-025-61650-z): a GenNet branch explicitly uses SNP-to-gene mapping followed by GO hierarchy. The task is case/control prediction in 41,686 participants. AUROC and repeated train/test splits are reported. [GenNet code](https://github.com/ArnovanHilten/GenNet) is public; EADB genotypes require application. The best reported overall AUC belongs to gradient boosting, so it should not be attributed to the GO network.
- [Causal modelling of gene effects from regulators to programs to traits, Nature, online 2025 / volume 2026](https://www.nature.com/articles/s41586-025-09866-3): GO supports functional annotation/enrichment of programs linking Perturb-seq and human blood traits. Core programs arise from cNMF. An augmented-GO evaluation would address program interpretation and external biological consistency, with an added project protocol.
- [OntoVAE, Bioinformatics 2023](https://doi.org/10.1093/bioinformatics/btad387): GO-constrained latent activities and decoder connectivity; public [code](https://github.com/hdsu-bioquant/OntoVAE_manuscript) and [models/data](https://figshare.com/projects/OntoVAE_Ontology_guided_VAE_manuscript/146727). A useful hierarchy consumer, with the original paper's prediction protocol requiring closer task definition.
- [OntoWAS, PLOS Computational Biology 2021](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1009373): GO features for natural-yeast genotype–trait inference and 36 growth conditions. [Code](https://github.com/hidentanaka/OntoWAS). This provides a simpler feature-based extension within the fitness/trait family.

## Project assessment: a broad biological portfolio

For the requested publication-oriented task search, the strongest initial portfolio spans these endpoint families:

| Family | Representative consumer/resource | Main output | Distinct contribution |
|---|---|---|---|
| Transcriptional perturbation | GEARS; scLong as another consumer | Expression changes and perturbation identity | Existing priority task |
| Pharmacology | DrugCell/ParsVNN/SparseGO | Drug response; related combination/MoA outputs | Direct pruning comparison and treatment relevance |
| Fitness/genetic interaction | DCell/Ontotype; BioPathNet for human SL | Growth and signed/pairwise interaction effects | Different readout and cross-species scope |
| Disease-gene prioritization | MultiOme | Known causal-gene rank | Human disease interpretation |
| Evolutionary constraint | GeneBayes | Held-out likelihood and phenotype-associated gene ranking | Population-genetic target and non-neural consumer |
| Morphology | MorphMap/PERISCOPE/CPJUMP1 | Measured phenotype prediction/retrieval | Orthogonal assay modality |
| Functional explanation | GeneWalk/PET/GeneAgent | Context relevance, experimental-set retrieval and supported interpretation | Knowledge utility and interpretability |
| Molecular properties | LitGene | Dosage sensitivity, solubility and other properties | Additional targets after contrastive/data interface validation |

Prioritization is our assessment of biological breadth, directness of the GO interface, venue and practical access. DrugCell/ParsVNN, BioPathNet and the public MultiOme task have particularly direct replacement interfaces. GeneBayes adds a different mathematical consumer. Morphology adds an independent modality with a newly defined consumer. scLong and LitGene broaden architecture coverage with larger adaptation requirements.

## Comparison structure supported by this literature

Use the same biological data, labels, splits and consumer when comparing knowledge products:

1. The publication's original GO input and preprocessing.
2. The publication's applicable reduction/pruning method.
3. A frozen task-specific augmented input with the original consumer.
4. Augmentation followed by the same reduction/pruning method.
5. Size/degree/capacity-matched random controls appropriate to the consumer.

The augmentation stage uses task descriptions, context and external evidence. Evaluation scores remain evaluation outputs. Source-lineage and endpoint-overlap assessment are handled by the project's separate scientific audit.

Three adapter types are needed: gene–gene similarity graphs, gene–term feature/mask tables, and ontology DAGs. Typed relation KGs add a fourth interface for BioPathNet. Existing flat GEARS attributes directly support only part of this landscape; each hierarchy/semantic consumer needs its own frozen projection with preserved relation meaning.

Evidence reporting should distinguish independent biological endpoint families, multiple consumers within a family, multiple datasets/contexts, and knowledge-recovery endpoints. This supports a precise scale/generalization claim while preserving the original papers' experimental definitions.
