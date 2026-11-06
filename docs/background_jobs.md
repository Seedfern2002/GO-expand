# 后台任务级增广测试

使用独立进程会话运行任务，标准输入关闭，日志直接写入磁盘。关闭当前 Codex 对话后，后台监督进程继续执行规划、批量取证和独立审校。

```bash
.venv/bin/python scripts/run_agent_background.py \
  --run-dir outputs/agents/norman_task_background_001 \
  --codex-bin /home/yxcheng/.vscode-server/extensions/openai.chatgpt-26.1021.22027-linux-x64/bin/linux-x86_64/codex
```

运行目录必须是新的目录。后台任务保存英文任务快照、上下文和基因背景，并核对执行代码及提示词版本。各阶段使用独立 Codex 会话。后台流程使用 [Codex 自动审批模式](https://learn.chatgpt.com/docs/cli/reference)，在 workspace-write 边界内执行，处理需要审批的动作时由自动审查判断。

后台测试允许在本次运行目录内实现和执行缺少的数据源连接器，优先处理 Reactome 与 hu.MAP 的完整来源表；其他知识方向记录实际覆盖状态。全部新产物保存在运行目录，原始 GO、baseline 和共享代码保持原样。

本轮不运行训练；进程环境屏蔽 GPU，数值库线程数设为 2，下载预算为 256 MiB，每次阶段执行默认最多运行 30 分钟。模型执行成功但产物校验失败时，保留原始输出到 attempts，反馈错误并自动修复重试一次。超时只终止该任务新建的阶段进程组。

## 查看进度

- `outputs/agents/latest_background.json`：最近启动的后台任务路径及 PID。
- 运行目录的 `status.json`：阶段、心跳、监督进程 PID、当前子进程 PID、完成或失败状态；每 15 秒更新心跳。
- `job.log`：总体进度。
- `planner.log`、`retriever.log`、`reviewer.log`：每阶段执行结果。
- 各阶段目录的 `events.jsonl`、`stderr.log`、`result.json`：详细记录。
- `summary.json`、`REPORT.md`：最终覆盖率、批准的批次路径、耗时及 token 用量。

例如：

```bash
cat outputs/agents/latest_background.json
cat outputs/agents/norman_task_background_001/status.json
tail -f outputs/agents/norman_task_background_001/job.log
```

完成状态区分 `completed`、`completed_with_gaps` 和 `completed_without_approved_batches`；失败保存为 `failed` 并记录具体阶段及原因。此测试交付审核后的知识批次，图投影和下游训练分别执行。
