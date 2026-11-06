# 首轮 Codex GO 增广实验：Norman / K562

历史流程调试记录。当前执行策略已调整为[任务级批量增广](task_wide_augmentation.md)，覆盖完整基因背景；后续 agent 交流和新产物统一使用英文。本页及原始运行文件保留首轮实验内容。

运行日期：2026-11-05。已完成三个独立 Codex 会话：规划、取证、审校，并导出一份包含 3 条记录的知识 overlay。本轮验证对象是 agent 流程及知识产物；下游效用将在图投影后评估。

## 运行结果

| 阶段 | 产物 | 模型运行时间 |
|---|---|---|
| 规划 | 选择 K562 红系分化相关调控程序；将同模块通路核对列为次级方向 | 145 秒 |
| 取证 | 3 条候选；覆盖 TP73、KLF1 两个 Norman 扰动靶点 | 222 秒 |
| 审校 | 3 条 accept，均保留实验条件；规范化细胞名称、基因名称及亚型表述 | 182 秒 |

模型均为 `gpt-6.1-sol`，CLI 为 IDE 自带的 `0.164.0-alpha.11.1`。三个阶段累计运行约 9 分 9 秒，准备、协调和归档时间另计。规划阶段继承本机推理配置，取证和审校显式使用 medium；命令、token usage、时间及会话 ID 保存在运行记录中。

原始 GEARS 元数据核对得到 102 个可用扰动靶点、3,127 个扰动图节点及 277 个可用条件。导出过程读取 H5AD 的条件／基因字段及其分类编码，没有读取表达矩阵；基因集合与现有 baseline 准备结果一致。

## 知识产物

| 记录 | 经审校的内容 | 保留的必要条件 |
|---|---|---|
| A1-C001 | TP73 参与红系分化相关程序 | TP73 亚型、K562 及过表达实验条件 |
| A1-C002 | KLF1 参与该程序的 globin 表达分支 | K562 中与 BCL11A-XL 共表达的合作条件 |
| A1-C003 | TP73 对 GATA1 表达的正调控关系 | 外源 TAp73α 与内源 TA 类实验分别描述，并保留诱导条件 |

TP73 两条记录的原始依据来自同一项研究，证据计数按研究归组。[Marqués-García et al., 2009](https://pmc.ncbi.nlm.nih.gov/articles/PMC2755837/) 支持亚型及条件限定的功能关联；[Trakarnsanga et al., 2014](https://haematologica.org/article/view/7195) 提供 KLF1 / BCL11A-XL 合作条件的依据。

三个记录均存为 `external_attribute`。本地程序模块复用同一 `LOCAL:` ID；现有 GO:0030218 已表达红系分化，词条整理将额外信息定位到实验情境、亚型及合作条件。

本地注释核对确认，KLF1 的 GEARS 原注释和当前下载的 UniProt GAF 均含 GO:0030218。TP73 的关键词核对作为覆盖检查记录保存，完整语义去重还需按关系及证据逐项处理。

Reactome 方向执行了两次同模块检索，未获得满足参与者字段要求的候选，按计划停止；该方向的覆盖状态为 `no_evidence`。ENCODE 及蛋白复合体方向留待后续计划。

## 可追溯记录

- [规划 JSON](../outputs/agents/norman_pilot_003/planner/result.json)
- [候选知识 JSON](../outputs/agents/norman_pilot_003/retriever/result.json)
- [审校 JSON](../outputs/agents/norman_pilot_003/reviewer/result.json)
- [运行汇总](../outputs/agents/norman_pilot_003/summary.json)
- [元数据](../outputs/agents/norman_pilot_003/inputs/gears_metadata.json)与[注释覆盖检查](../outputs/agents/norman_pilot_003/inputs/annotation_coverage.json)
- [overlay](../data/processed/overlays/norman_pilot_003_v1/overlay.jsonl)及[版本清单](../data/processed/overlays/norman_pilot_003_v1/manifest.json)

取证的事件日志可核对 12 次搜索查询。候选包另记录来源访问清单；CLI 事件对批量打开及失败访问的呈现不完全一致，原始日志及访问范围一并保留。

协调层提供了固定元数据、注释覆盖检查，并核对了一处实验名称：审校输出将 `benzidine` 误译为“苯胺蓝”，导出时通过[独立修订记录](../outputs/agents/norman_pilot_003/text_corrections.json)统一为英文术语。原始 agent 结果及哈希保持不变；这次运行包含明确记录的协调层校对。

[来源快照清单](../outputs/agents/norman_pilot_003/sources/manifest.json)区分原文 HTML、访问验证页面和失败下载。期刊原文 HTML 已保存；PMC 的直接下载触发验证，原文核验依据本轮 web 工具取得的正文及图注。验证页面不作为论文快照使用。

## 下一步实现重点

将亚型、合作因子、干预方式、诱导处理及时间从自由文本拆为明确字段，使程序能够判断哪些条件信息适用于任务。

随后为每条知识记录增加投影适用性判断：程序成员关系、有向调控关系及图外实体分别处理。当前 overlay 已导出，状态为 `reviewed_knowledge_overlay`，图投影状态为 `not_projected`。

KLF1 的例子可以直接检验投影是否保留知识增量：其普通功能归属已有 GO 覆盖，合作条件是本轮新增的信息。GATA1 和 BCL11A 位于当前固定图节点之外，其信息需要通过属性或情境表示接入。

任务卡、角色说明及 JSON Schema 继续作为 Codex 和后续 API 后端的共同接口。下一轮工具接口应显式保存每次查询、来源定位和结构化条件，便于比较不同后端的结果。
