# Codex 驱动的任务级 GO 增广

项目内 agent 的提示词、进度消息、阶段交接、知识定义及审校说明统一使用英文。用户文档保留中文；agent 使用简短的英文 [task context](agent_context.md)。

框架以任务类型为规划单位，根据不同生物学任务的需求构建适配的 GO 增广。数据库规则化整合与文献内容增广均属于实现路径，研究重点是规模、多任务普适性及生物学有效性。

GEARS / Norman 是当前重点任务 profile：构建一份适用于所有扰动的共享知识 overlay，所有 3,127 个图基因参与筛查，102 个可用扰动靶点单独统计覆盖率。每类知识通过对应的数据源及处理规则覆盖整个基因背景。

任务范围、性能分析及优化设计见 [任务级增广](task_wide_augmentation.md)。

## 文件和接口

| 内容 | 位置 |
|---|---|
| 英文任务卡 | `configs/agent_tasks/gears_norman.json` |
| 英文角色提示词 | `prompts/agents/` |
| task_batch 输出格式 v2 | `schemas/agents/batch/` |
| 历史逐记录输出格式 v1 | `schemas/agents/` |
| 阶段准备 | `scripts/prepare_agent_stage.py` |
| Codex 执行和产物检查 | `scripts/run_agent_stage.py` |
| 固定基因／条件元数据导出 | `scripts/export_gears_metadata.py` |
| 历史逐记录 overlay 导出 | `scripts/export_agent_overlay.py` |

task_batch 的规划产物是数据源及转换规则；取证产物是批量文件、证据索引和统计报告的清单；审校产物是来源／规则审核、抽样结果和通过审核的文件清单。大规模关联表保存在磁盘上。

当前已实现这些接口的准备和校验。实际数据源连接器、缓存执行器及批量 overlay 编译器是接下来的实现内容；旧版逐记录导出器保留用于历史实验。

## 准备任务级规划

从已有 H5AD 导出元数据时，使用包含 h5py 的 GEARS 环境：

```bash
.venv-gears/bin/python scripts/export_gears_metadata.py \
  --output data/processed/gears/norman_metadata.json
```

该快照已生成，含条件、基因背景和原始注释。已有文件使用新路径重新导出，以保留版本。

准备规划阶段：

```bash
python3 scripts/prepare_agent_stage.py \
  --stage planner \
  --task configs/agent_tasks/gears_norman.json \
  --run-dir outputs/agents/norman_task_001 \
  --codex-bin /home/yxcheng/.vscode-server/extensions/openai.chatgpt-26.1021.22027-linux-x64/bin/linux-x86_64/codex
```

任务卡选择 task_batch、medium 推理设置及 workspace-write，用于受预算约束的数据处理。模型依次取命令行参数、任务卡和本机配置。可执行文件路径来自当前 IDE 安装，其他环境按本机路径调整。

准备脚本保存原始输入快照和哈希，将 JSON 输入紧凑化，并将输出 schema 通过 CLI 参数提供。人工在 IDE 中执行时，先读取生成目录中的 `prompt.md` 和 `schema.json`。

IDE 指令示例：

```text
Read outputs/agents/norman_task_001/planner/prompt.md and schema.json.
Execute the planner role in English.
Save the final JSON to result.json in the same directory.
```

执行准备好的 CLI 阶段：

```bash
.venv/bin/python scripts/run_agent_stage.py \
  --stage-dir outputs/agents/norman_task_001/planner
```

Codex 非交互参数见 [OpenAI 官方说明](https://learn.chatgpt.com/docs/non-interactive-mode)。当前使用 IDE 自带的 CLI；PATH 中旧 Snap 版及首次模型失败记录见历史 pilot。

## 交接及校验

准备取证时传入 `--plan`，准备审校时另传入 `--candidates`；三阶段使用相同任务 ID。每个阶段独立运行，原始结果保持不变，修订或补证使用新目录。人工可以修改知识类别和来源策略，另存计划后传入下一阶段。

执行器检查 schema、任务 ID、完整的计划／批次覆盖、工作区文件和校验和。批次统计需满足：

- `coverage_report`：`universe_size`、`genes_screened`、`genes_annotated`、`record_count`。
- `validation_report`：`validated_rows`、`failed_rows`；所有行均需计入检查。
- 实际物化的批次需筛查完整基因背景；无证据、缺失工具和未完成方向在计划项 coverage 中记录。
- 审校指定实际使用的 `review_method`，审核报告与决定一致；accept 必须对应存在且哈希匹配的文件。

这些检查验证文件交接及处理报告。领域正确性由数据源语义审核、程序检查和明确记录的证据抽查共同评价。数据源连接器还需实现对应的逐行语义检查。

运行保存 `execution.json`、`events.jsonl`、`stderr.log` 和 `result.json`。依赖为 `pip install -e '.[agent]'`；当前 `.venv` 已具备。

## 历史实验及 API 接入

[首轮单模块 pilot](agent_pilot_norman.md)保留作为流程调试记录，其范围及耗时单独记录。当前任务卡已切换到任务级增广；历史输入、会话及 overlay 的内容和哈希保持原样。

Codex 和后续 API 后端共用英文任务卡、角色职责、输出 schema 及文件清单。源数据处理和缓存尽量由同一组程序实现，切换后端时比较规划、证据质量和工具行为。

模型预测与评测分数用于评价冻结后的知识产物。任务级的知识类别、筛选规则和证据决策仍由任务说明及外部生物学证据决定。
