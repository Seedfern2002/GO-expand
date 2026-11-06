# GO 图形探索

打开 [01_go_overview.ipynb](01_go_overview.ipynb)，选择项目 `.venv/bin/python` 或 `Python (GO enrichment)` kernel，再运行全部单元格。当前项目环境已安装并配置。

Notebook 已保存真实数据运行后的图表与表格，打开即可阅读。重新运行将核对数据 SHA256，并从 OBO/GAF 重算全部图表。

## 内容

1. BP／MF／CC 概念规模和关系类型。
2. `is_a` 层级深度与多 parent 结构。
3. DNA repair 附近有类型、有方向的局部图。
4. 人类注释的证据类别及代码分布。
5. 每个 DB Object ID 的功能注释覆盖分布。
6. TP53 的注释、证据与功能表。
7. 一组基因产物在直接／传播后注释上的 Jaccard 热图与邻居排名。

第 0 节可以修改示例 UniProt ID、相似度所用 aspect、证据代码和局部图中心，再运行全部单元格。图形保存为 PNG 和 SVG，统计表保存为 CSV：

```text
outputs/notebooks/01_go_overview/
```

HTML 阅读版：[01_go_overview.html](../outputs/notebooks/01_go_overview/01_go_overview.html)。

## 环境与启动

在仓库根目录启动 JupyterLab：

```bash
.venv/bin/jupyter lab notebooks/01_go_overview.ipynb
```

在新环境中安装：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[notebook]'
.venv/bin/python -m ipykernel install --prefix .venv --name go-enrichment --display-name 'Python (GO enrichment)'
```

命令行重新执行并保存输出：

```bash
.venv/bin/jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=240 notebooks/01_go_overview.ipynb
```

执行后的 notebook 导出 HTML：

```bash
.venv/bin/jupyter nbconvert --to html --output-dir outputs/notebooks/01_go_overview notebooks/01_go_overview.ipynb
```

## 数据解释

覆盖分布以 GAF 中出现的 DB Object ID 为分母；后续接入基因 ID 映射时再统计 gene-level 覆盖。原始记录、去重关联、否定记录分别计数。相似度采用明确的 aspect／relation／evidence 策略，沿 `is_a` 和 `part_of` 传播并移除根 term。

相似度面板用于理解表示构造，未开展 GO 增广或下游模型训练。任务特定增广仍按项目约定，从任务知识需求与外部证据出发。
