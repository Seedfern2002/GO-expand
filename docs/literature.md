# 文献地图

整理日期：2026-11-05。此表保留第一轮检索中对项目定位最重要的原始来源；初步判断与论文事实分开记录。

2026-11-06 增补：[创新性核对](novelty_assessment.md)，记录多资源功能整合、多图扰动预测及 LLM 本体编辑的先行工作，以及与当前实现的重合。

2026-11-07 update: [GO application task landscape](go_task_landscape.md) documents pruning precedents, major-journal biological tasks, public resources, metrics and augmentation interfaces. The survey distinguishes original GO-input models from proposed consumers of independent experimental readouts.

## 应用与评价

| 文献 | 年份／载体 | 涉及主题 |
|---|---|---|
| [GEARS](https://www.nature.com/articles/s41587-023-01905-6) | 2023 在线／2024，Nature Biotechnology | GO 先验与未见扰动预测 |
| [Deep-learning-based gene perturbation effect prediction does not yet outperform simple linear baselines](https://www.nature.com/articles/s41592-025-02772-6) | 2025，Nature Methods | 简单线性基线与扰动模型比较 |
| [TxPert](https://www.nature.com/articles/s41587-026-03113-4) | 2026，Nature Biotechnology | 多知识图融合及跨情境任务 |
| [Deep learning perturbation models can outperform baselines on calibrated metrics](https://www.nature.com/articles/s41587-026-03307-w) | 2026，Nature Biotechnology | 扰动预测的校准评价指标 |
| [scGenePT](https://www.biorxiv.org/content/10.1101/2024.10.23.619972v1.full) | 2024，预印本 | GO 注释文本 embedding |
| [CellGO](https://pmc.ncbi.nlm.nih.gov/articles/PMC10790717/) | 2023 在线／2024，Briefings in Bioinformatics | 层级消费与细胞功能解释 |
| [DrugCell](https://pmc.ncbi.nlm.nih.gov/articles/PMC7737474/) | 2020，Cancer Cell | GO 层级驱动药物响应预测 |
| [SparseGO](https://pmc.ncbi.nlm.nih.gov/articles/PMC10474372/) | 2023，eBioMedicine | 高效 GO 层级模型 |
| [PET and Benchmark](https://www.nature.com/articles/s41467-024-51859-9) | 2024，Nature Communications | 独立实验与功能检索评测 |
| [JUMP genetic profiles](https://broadinstitute.github.io/jump_hub/howto/notebooks/11_retrieve_profiles.html) | 官方资源 | CRISPR／ORF 形态 profile |

## 方法与直接先行工作

| 文献 | 年份／载体 | 与增广的联系 |
|---|---|---|
| [Metascape](https://www.nature.com/articles/s41467-019-09234-6) | 2019，Nature Communications | GO、Reactome、CORUM 等功能资源整合；应用目标为功能分析 |
| [GeneMANIA](https://doi.org/10.1093/nar/gkq537) | 2010，Nucleic Acids Research | 多类生物网络整合及基因功能预测 |
| [DRAGON-AI](https://doi.org/10.1186/s13326-024-00320-3) | 2024，Journal of Biomedical Semantics | 检索增强 term 定义及逻辑组件生成 |
| [KARMA](https://arxiv.org/abs/2502.06472) | 2025，NeurIPS；2026 修订 | 文献抽取、schema 对齐、冲突处理 |
| [GeneAgent](https://www.nature.com/articles/s41592-025-02748-6) | 2025，Nature Methods | 借助数据库验证基因集解释；输出目标与编辑 ontology 不同 |
| [Evo-DKD](https://arxiv.org/abs/2507.21438) | 2025 预印本／2026 修订 | 迭代 ontology 编辑及理由验证 |
| [FlyAOC](https://arxiv.org/abs/2602.09163) | 2026；作者页面标注 NeurIPS E&D 接收 | 从文献恢复 GO 相关结构化注释的 agent benchmark |
| [The GO knowledgebase in 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC12807639/) | 2026，Nucleic Acids Research | 官方 ontology agent、GO-CAM 与知识库更新 |
| [UNICORN](https://www.nature.com/articles/srep39237) | 2016，Scientific Reports | 利用既有 GO 和分子网络提出新 term，历史版本恢复 |
| [DCell](https://pmc.ncbi.nlm.nih.gov/articles/PMC5882547/) | 2018，Nature Methods | GO／数据驱动 CliXO 层级及表型预测 |
| [PerturbAgent](https://ora.ox.ac.uk/objects/uuid%3Aee9f614d-4c1e-4a5f-b493-d0af9d03033e) | 2026，AAAI Workshop XAI4Science | 扰动分析、预测与解释的 agent 编排 |

项目定位：利用同一 agent 框架，根据不同任务的知识需求构建 task-specific GO 增广，并评价规模、多任务普适性及生物学有效性。数据库的规则化整合与文献内容增广均属于研究范围。GEARS 是重点应用之一。增广内容的选择依据是任务知识需求、生物学证据与语义一致性。agent 生成 GO term、自动 annotation 和从网络发现功能层级均已有先行工作。

## GO 处理基线

| 文献／资源 | 处理对象 | 处理方式 |
|---|---|---|
| [ParsVNN](https://pmc.ncbi.nlm.nih.gov/articles/PMC8557386/) | GO 映射出的预测网络，2021 | 任务指导剪枝 |
| [GO slim](https://geneontology.org/docs/download-ontology/) | 较粗粒度 GO 子集 | 粒度简化 |
| [GO Trimming](https://pmc.ncbi.nlm.nih.gov/articles/PMC3160396/) | 富集结果列表，2011 | 解释任务的去冗余 |
| [REVIGO](https://doi.org/10.1371/journal.pone.0021800) | 富集结果列表，2011 | 语义相似度汇总 |
| [CliXO](https://doi.org/10.1093/bioinformatics/btu282) | 从 pairwise similarity 推断层级，2014 | 数据驱动模块／层级发现 |
| [GO-CAM](https://pmc.ncbi.nlm.nih.gov/articles/PMC7012280/) | 活动、因果联系与情境，2019 | 活动及因果关系表示 |
