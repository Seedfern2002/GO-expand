# Norman 原始 GEARS baseline

配置：[gears_norman_baseline.json](../configs/gears_norman_baseline.json)。按作者 Fig. 2 的 recipe，采用 Norman、simulation split seed 1、15 epochs、batch size 32、hidden size 64。当前固定源码版本为 GEARS 0.1.2，作者 recipe 标注测试版本为 0.1.1。

2026-11-06 启动修复：首轮在首次 CUDA 分配前重置 allocator 峰值统计，出现 `Invalid device argument`，训练尚未开始。运行器已改为先完成 CUDA probe、同步后再重置统计。原运行和错误记录保留；重试使用 [retry1 配置](../configs/gears_norman_baseline_retry1.json)与 `outputs/gears/norman_baseline_seed1_retry1/`，复用已准备的图缓存，模型和训练参数保持相同。`outputs/gears/latest_baseline.json` 指向最新运行。

原始注释使用 GEARS 官方 `gene2go_all.pkl`，未增广。数据来源及校验和见 [gears_norman_data.json](../configs/gears_norman_data.json)。

## 运行与资源规则

先用 CPU 准备 cell graphs、split、共表达图及原始 GO 图，再等待一张没有其他计算进程的 GPU。

GPU 必须连续三次检查均无计算进程、利用率不超过 5%、空闲显存至少 16 GiB，才启动 baseline。检查间隔 30 秒。已有作业即使暂时利用率为 0%，也仍按占用处理。等待器只读取 GPU 状态，不终止、重启或修改其他进程。

```bash
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 .venv-gears/bin/python -u scripts/prepare_gears_norman.py
.venv-gears/bin/python -u scripts/wait_and_run_gears.py
```

## 查看状态与产物

运行目录：`outputs/gears/norman_baseline_seed1/`。

| 文件 | 内容 |
|---|---|
| `prepare.log`、`preparation.json` | CPU 准备日志及数据规模 |
| `queue.log`、`queue_status.json` | 等待空闲 GPU、启动与退出状态 |
| `run.log`、`status.json` | 训练和评测进度 |
| `run_config.json`、`environment.json`、`requirements.txt` | 实际配置与依赖版本 |
| `input_files.json`、`split.json`、`subgroups.json` | 输入校验和与固定划分 |
| `original_graphs.pt`、`model_summary.json` | 模型实际消费的图与模型规模 |
| `history.json`、`best_validation.json` | 逐 epoch 指标与最优验证 epoch |
| `checkpoint/` | 最优模型及其配置 |
| `test_metrics.json`、`test_per_perturbation.json` | 测试总体及逐扰动指标 |
| `test_perturbation_means.npz` | 测试扰动的预测均值与真实均值 |
| `test_deeper_analysis.json`、`test_non_dropout_analysis.json` | 官方进一步分析结果 |
| `metrics.json` | 全部训练、评测完成后的结果与耗时 |

运行器沿用上游训练循环、loss、优化器、学习率调度及 checkpoint 选择。额外包装现有评测函数，只保存其返回结果和耗时。为兼容 SciPy／pandas 的索引，在模型构造时临时使用相同表达矩阵的 dense 表示，随后恢复稀疏表示供官方图函数和分析使用。
