# GEARS 源码与接入入口

## 已完成的准备

- 官方源码位于 `third_party/GEARS/`，固定 commit 为 `f374e43e197b295016d80395d7a54ddb81cc6769`。
- 源码版本为 `cell-gears 0.1.2`，许可证为 MIT。
- 已检查 GO 图构建、缓存与模型图输入的入口。

来源记录见 [gears_source.json](../configs/gears_source.json)，恢复方式见 [third_party/README.md](../third_party/README.md)。

## GO 知识怎样进入模型

```text
gene2go_all.pkl：gene symbol → GO term set
                 ↓
gene pair 的 Jaccard similarity
                 ↓
保留 score > 0.1 的 pair
                 ↓
按 target 取 importance 最大的 k + 1 行（通常包含 self）
                 ↓
GeneSimNetwork：有向 edge_index 与 edge_weight
                 ↓
GEARS.model_initialize(G_go=..., G_go_weight=...)
```

| 入口 | 文件 | 行为 |
|---|---|---|
| `PertData.__init__` | [pertdata.py](../third_party/GEARS/gears/pertdata.py) | 下载／读取官方 `gene2go_all.pkl` |
| `PertData.set_pert_genes` | [pertdata.py](../third_party/GEARS/gears/pertdata.py) | 确定扰动图基因集合及 `node_map_pert` |
| `get_GO_edge_list` | [utils.py](../third_party/GEARS/gears/utils.py) | 用 term 集合计算 Jaccard，保留大于 0.1 的 pair |
| `make_GO` | [utils.py](../third_party/GEARS/gears/utils.py) | 从 annotation 集合生成自定义 GO 图 |
| `get_similarity_network` | [utils.py](../third_party/GEARS/gears/utils.py) | 默认读取官方预计算图，再按 target 选择邻居 |
| `GeneSimNetwork` | [utils.py](../third_party/GEARS/gears/utils.py) | 按传入 node map 转换图索引及边权 |
| `GEARS.model_initialize` | [gears.py](../third_party/GEARS/gears/gears.py) | 接受外部 `G_go`／`G_go_weight`；缺省时进入默认图构建路径 |

其中 `k` 默认是 20。文档参数把 `G_go` 描述为稀疏矩阵，但实际代码将 `GeneSimNetwork.edge_index` 这样的 PyTorch tensor 传入模型。接入时以源码实际行为为准。

## 后续随机属性实验的对象

第一轮将“属性”具体化为每个基因的 GO term 集合：随机补入原集合中没有的已有 term，观察派生图与预测结果如何变化。这样能够保持模型输入形式一致。

起步对照：

1. 原始 annotation 集合及重建图。
2. 相同基因集合、相同投影规则下，随机添加 annotation 后的图。

候选添加量和随机种子在运行前确定。可记录每基因新增 term 数、Jaccard 变化、邻居重合率、边权和连通性，再进行固定模型与划分下的训练评测。

此处的随机添加是噪声对照；任务特定 agent 增广仍从任务知识需求与外部证据出发。

## 接入时固定的细节

- 默认分支使用官方预计算的 GO 图。修改 `gene2go_all.pkl` 后，需要显式重建并传入新图，才能让修改进入模型。
- `make_GO` 的缓存路径是工作目录下的 `./data/go_essential_<data_name>.csv`。后续实验为各个 annotation 变体保存独立图产物，并显式传入图 tensor。
- 原始组和随机组使用同一份 `pert_list`、`node_map_pert`、共表达图、数据划分与训练设置。
- GEARS 自带的 gene symbol 注释和本项目已下载的 UniProt GAF 是不同输入。最初噪声对照可以从 GEARS 自带注释开始，真实 GO 快照的 ID 映射另行接入。

## 运行环境现状

已在独立 `.venv-gears/` 中安装 PyTorch 2.5.1+cu124、PyG 2.6.1，以及官方 requirements 固定的 NumPy 1.26.4、pandas 2.2.2、Scanpy 1.10.2 等依赖；已下载官方 Norman 数据及原始 GO 注释。环境与 notebook 的 `.venv/` 分别管理。baseline 的配置、CPU 准备及空闲 GPU 等待方式见 [运行说明](gears_baseline.md)。

2026-11-05 重新检查确认：宿主环境可见 8 张 NVIDIA H20-3e，每张总显存为 143,771 MiB，驱动版本为 580.126.20。默认沙箱中的 `nvidia-smi` 无法访问驱动，沙箱外查询正常。后续按单卡 GPU 方案准备训练环境，并在安装 PyTorch 后实际检查 CUDA 张量分配及训练吞吐。
