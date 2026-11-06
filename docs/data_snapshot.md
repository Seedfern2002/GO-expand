# 真实 GO 数据快照

下载日期：2026-11-05。文件来自 GO 官方站点，保存在本地 `data/raw/go/2026-07-26/`。

## 文件与版本

| 文件 | 含义 | 文件大小 |
|---|---|---|
| [go-basic.obo](../data/raw/go/2026-07-26/go-basic.obo) | GO 本体，文件头 `releases/2026-07-26` | 32,227,785 bytes |
| [HUMAN-uniprot.gaf.gz](../data/raw/go/2026-07-26/HUMAN-uniprot.gaf.gz) | 人类 UniProt 标识符注释，GAF 2.2 | 12,109,254 bytes |

注释文件由 UniProt 生成，文件头日期为 `2026-07-28 19:42`；其 `go-version` 指向 GO `2026-07-26`，与下载的本体匹配。这里区分 ontology 版本与注释生成日期。

实际下载端点为 [GO 本体](https://current.geneontology.org/ontology/go-basic.obo) 和 [人类注释](https://current.geneontology.org/annotations/gaf/HUMAN-uniprot.gaf.gz)。本次日期归档端点返回 HTTP 404，因此从官方 `current` 获取文件，再用文件头和 SHA256 固定本地快照。未来重新访问 current 可能获取不同版本。

来源、大小、校验和及版本完整记录在 [数据清单](../configs/data_manifest.human.2026-07-26.json)。原始数据和生成结果不进入 Git；数据清单与本文可版本管理。

## 本地统计

以下数字由本项目完整读取下载文件后计算。

| 本体统计 | 数量 |
|---|---:|
| Active terms | 38,092 |
| Biological Process | 23,974 |
| Molecular Function | 10,041 |
| Cellular Component | 4,077 |
| Obsolete terms，单独保留 | 10,248 |
| Active term 的 `is_a` 边 | 57,456 |
| Active term 的 `part_of` 边 | 6,270 |
| Active term 的 `regulates` 边 | 2,820 |
| Active term 的 `positively_regulates` 边 | 2,475 |
| Active term 的 `negatively_regulates` 边 | 2,475 |

| 注释统计 | 数量 |
|---|---:|
| 原始 GAF 记录 | 910,476 |
| 正注释记录 | 908,979 |
| NOT 记录 | 1,497 |
| 不同 DB Object ID | 38,902 |
| 去重后的正 object–term pair | 337,029 |
| 带 annotation extension 的记录 | 45,896 |
| 带 gene product form ID 的记录 | 862,694 |
| 指向未知 term 的记录 | 0 |
| 指向 obsolete term 的记录 | 0 |

记录数保留了不同证据、来源及情境；pair 数仅按 DB Object ID 和 term 去重。DB Object ID 数尚未转换为 HGNC／Ensembl gene 数。所有记录的主 taxon 均为 `taxon:9606`。统计未做证据过滤、注释传播或基因层面的聚合。

已完整读取 gzip 流并通过 CRC 检查，全部 GAF 记录可由现有工具解析。各 aspect、evidence code 和注释关系的详细分布见 [summary.json](../outputs/go/2026-07-26/summary.json)。

## 从真实例子开始

查看线粒体 term 的定义、关系与归并祖先：

```bash
PYTHONPATH=src python3 -m go_enrichment term data/raw/go/2026-07-26/go-basic.obo GO:0005739
```

查看 TP53 对应 UniProt 条目的注释：

```bash
PYTHONPATH=src python3 -m go_enrichment annotations data/raw/go/2026-07-26/HUMAN-uniprot.gaf.gz --object-id UniProtKB:P04637 --taxon taxon:9606
```

已另存这个条目的 1,068 条记录到 [TP53.annotations.jsonl](../outputs/go/2026-07-26/TP53.annotations.jsonl)，便于查看同一基因产物的多种功能、证据与情境。
