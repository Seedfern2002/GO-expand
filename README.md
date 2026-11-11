# Task-specific Gene Ontology augmentation

研究问题：如何利用 agent 根据不同生物学任务的知识需求，构建 task-specific 的 GO 增广，并在多种任务上验证这一方法的普适性与生物学有效性？

这里的 enrichment 指知识增广；统计意义的 GO enrichment analysis 是评测应用之一。

## 项目定位

项目以 Nature 系列大子刊为投稿目标，重点是规模、多任务普适性和生物学有效性。相同 agent 框架根据不同任务形成各自适配的 GO 增广。

增广可以通过组学数据库或其他生物数据库的规则化整合实现，也可以通过相关文献内容实现，两条路径均属于研究范围。agent 可以参与任务理解、知识需求判断、来源选择、规则制定、执行组织和证据审核。

GEARS 是重点应用之一。虚拟细胞与扰动预测的研究热度使其成为当前重点实验场景，项目整体覆盖多种使用 GO 的生物学任务。

## Task-specific 的含义

任务类型决定增广的知识重点。例如，扰动预测可以侧重通路、调控关系和功能模块；药物响应预测可以侧重药物靶点及其相关过程。agent 根据任务说明规划检索和知识整合，并依据外部生物学证据及关系语义选择增广内容。

流程为：**任务说明 → 知识需求 → 外部证据检索与整合 → GO 增广产物冻结 → 下游训练与评测**。下游预测结果和评测分数仅用于评价增广效果，不作为 agent 选择、修改或筛选增广内容的信号。

## 从这里开始

1. [Notebook 图形概览](notebooks/01_go_overview.ipynb)：真实 GO 的结构、证据、覆盖及基因相似度；[运行说明](notebooks/README.md)。
2. [理解 GO：从知识表示到任务输入](docs/go_foundations.md)：本体、注释、关系、证据、传播、相似度与增广。
3. [动手探索](docs/walkthrough.md)：离线示例，以及真实 OBO/GAF 文件的检查方式。
4. [文献地图](docs/literature.md)：应用、方法、直接先行工作及基线。
5. [评测设计](docs/evaluation.md)：主任务、跨任务迁移和生物学发现。
6. [真实数据快照](docs/data_snapshot.md)：已下载的 GO 本体、人类注释及检查结果。
7. [GEARS 接入说明](docs/gears_setup.md)：已拉取的官方源码、GO 图入口及随机属性对照准备。
8. [GEARS baseline](docs/gears_baseline.md)：论文设置、原始数据、CPU 准备和空闲 GPU 排队规则。
9. [Codex 增广实验](docs/agent_system.md)：英文 agent、任务级批量产物及阶段准备／执行入口。
10. [任务级增广与效率](docs/task_wide_augmentation.md)：完整基因背景、批量处理、证据缓存及审核策略。
11. [历史单模块 pilot](docs/agent_pilot_norman.md)：首轮三个 Codex 会话及调试产物。
12. [后台测试](docs/background_jobs.md)：脱离 session 的任务级实验、进度心跳及结果查看方式。
13. [任务级增广结果](docs/task_wide_results_norman.md)：完整背景筛查、两类批量知识、覆盖率及审核产物。
14. [GEARS 原始／增广对比快照](results/gears_norman_seed1/README.md)：pipeline 改造前的代码版本对应结果、精确增广记录、训练配置和来源校验和。当前 split seed 1 下，MSE 降低 28.53%，top-20 DE MSE 降低 10.70%。
15. [v3 knowledge pipeline](docs/knowledge_pipeline.md)：数据库／论文证据批量导入、声明归并、独立校验、任务投影及冻结；泄露审计位于 pipeline 外部。
16. [独立 task-only pipeline](standalone/task_go/README.md)：可复制出项目运行，只导入任务信息和原始知识；私有文件系统隔离项目文档、历史运行和旧会话。
17. [DrugCell 初始化](docs/drugcell_setup.md)：以作者裁剪后的 GO 为共同起点，准备完整药物响应数据、固定五折划分、增广转换接口及 CPU 检查。

## 运行

Python 3.10+；当前探索工具仅依赖标准库，可直接在仓库根目录执行：

```bash
PYTHONPATH=src python3 -m go_enrichment summary examples/toy.obo
PYTHONPATH=src python3 -m go_enrichment term examples/toy.obo DEMO:0002
PYTHONPATH=src python3 examples/similarity_demo.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

需要安装命令行入口时：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/go-explore summary examples/toy.obo
```

## 目录

```text
docs/                 GO 基础、阅读清单与评测方案
notebooks/            已运行的真实数据图形概览与运行说明
third_party/          外部源码；GEARS 独立 checkout 的版本记录
src/go_enrichment/    OBO 探索、GAF 记录读取及相似度小工具
examples/             合成教学数据与可运行示例
tests/                关系传播、标识符及注释读取的语义测试
configs/              数据版本、训练设置和 agent 任务卡
prompts/agents/       规划、取证、审校角色提示词
schemas/agents/       与调用后端独立的阶段输出格式
data/raw/             官方原始数据（不进入 Git）
data/processed/       派生注释、图及特征（不进入 Git）
outputs/              实验结果（不进入 Git）
results/              纳入版本控制的精简实验快照与来源清单
```

## 研究约定

- 分别记录 ontology、gene-product annotations 和派生 gene–gene 图的修改。
- 官方发布文件作为不可变输入；增广保存在独立 overlay 中，并保留证据与编辑历史。
- 每类任务按预先定义的知识需求生成适配增广；增广产物在下游训练与评测前冻结，迁移实验直接复用该产物。
- 每次实验记录 ontology/annotation 版本、标识符映射、关系集合、证据筛选和数据划分。
- 数据准备阶段填写 [数据清单模板](configs/data_manifest.example.json)。

当前已提供文档、探索工具、图形 notebook、GO `2026-07-26` 本体与匹配的人类注释数据，以及 GEARS 官方源码。GO 来源、SHA256 和文件头版本保存在 [数据清单](configs/data_manifest.human.2026-07-26.json) 中；GEARS commit 记录在 [源码清单](configs/gears_source.json)。Codex 流程支持三阶段后台编排；v3 提供数据库／论文证据导入、独立记录校验、声明归并、任务投影和冻结。API 后端尚未实现。
