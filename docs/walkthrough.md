# 动手探索 GO

想先看图形概览，可以打开 [01_go_overview.ipynb](../notebooks/01_go_overview.ipynb)。里面保存了真实数据的运行结果；选择项目 `.venv/bin/python` kernel 后可重新运行。[Notebook 运行说明](../notebooks/README.md)介绍了环境和可修改参数。

在仓库根目录运行以下命令。示例使用 `DEMO:` ID；所有 term、关系和基因都是教学构造，不代表真实实验结果。

## 查看本体

```bash
PYTHONPATH=src python3 -m go_enrichment summary examples/toy.obo
PYTHONPATH=src python3 -m go_enrichment term examples/toy.obo DEMO:0002
PYTHONPATH=src python3 -m go_enrichment term examples/toy.obo DEMO:0003
```

观察以下内容：

1. 5 个 active term 和 1 个 obsolete term 被分别统计。
2. `DEMO:0002` 有一条 `regulates DEMO:0001` 边，但其正注释归并祖先只有 `DEMO:0000`。
3. `DEMO:0003` 同时沿 `is_a` 与 `part_of` 到达不同祖先；GO 不是一棵单亲树。
4. 使用 `DEMO:0009` 查询会解析到 `DEMO:0003`；查询 obsolete term 会显示替代提示，不自动改写。

## 看一次增广怎样影响相似度

```bash
PYTHONPATH=src python3 examples/similarity_demo.py
```

示例从相似度集合中去掉教学根节点：

```text
A 的集合 = {repair}
B 的集合 = {checkpoint}
原始 Jaccard = 0

为 B 补入 repair 注释后：
B 的集合 = {checkpoint, repair}
增广后 Jaccard = 1/2
```

这解释了补注释影响 GEARS 类图的入口。这里尚未判断这条新注释是否正确；真实实验中，知识证据验证和下游评价会分别给出答案。

还可以尝试：为 A 加入一个 B 没有的新功能，观察 Jaccard 的分母变化。

## 换成真实数据

已经下载好 GO `2026-07-26` 的本体及匹配的人类 GAF 2.2 注释，位于 `data/raw/go/2026-07-26/`。来源、版本及 SHA256 见 [数据清单](../configs/data_manifest.human.2026-07-26.json)，统计见 [真实数据快照](data_snapshot.md)。

直接运行：

```bash
PYTHONPATH=src python3 -m go_enrichment summary data/raw/go/2026-07-26/go-basic.obo
PYTHONPATH=src python3 -m go_enrichment term data/raw/go/2026-07-26/go-basic.obo GO:0005739
```

该 GO ID 是 mitochondrion；展示的定义和边以下载版本为准。

查看某个基因产物的注释时，使用真实文件中的数据库命名空间和 accession，例如：

```bash
PYTHONPATH=src python3 -m go_enrichment annotations data/raw/go/2026-07-26/HUMAN-uniprot.gaf.gz --object-id UniProtKB:P04637 --taxon taxon:9606
```

按证据过滤的例子：

```bash
PYTHONPATH=src python3 -m go_enrichment annotations data/raw/go/2026-07-26/HUMAN-uniprot.gaf.gz --object-id UniProtKB:P04637 --evidence IDA IMP IGI
```

输出是 JSON lines，保留 NOT、关系、证据、引用、extension 和产物形式。这一步是读取与筛选记录；尚未按 isoform、关系或情境做 gene-level 聚合。过滤参数中的 IDA/IMP/IGI 只是一组示例，不代表所有实验代码。

以后新增物种或版本时，从 [GO ontology 下载页](https://geneontology.org/docs/download-ontology/) 与 [annotation 下载页](https://geneontology.org/docs/download-go-annotations/) 选择匹配的数据，分别存放在独立目录，并填写新的数据清单。

## 工具边界与下一步

当前 OBO reader 提取 term、alt ID、类型边、obsolete 提示等基础字段，不实现完整 OBO/OWL 语义、逻辑推理或全库一致性检查。GAF reader 接受 2.2，进行字段数和关系结构检查，不等同于官方验证器。两者支持 gzip。

已完成各 aspect 和证据分布、否定记录、term ID 对应关系的检查。接下来分析标识符映射覆盖、直接／传播后注释量、低覆盖基因，以及不同关系策略下 gene–gene 图的变化，随后接入 GEARS。
