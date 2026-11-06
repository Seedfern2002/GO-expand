# 第三方源码

## GEARS

官方仓库：<https://github.com/snap-stanford/GEARS>。

已克隆到 `third_party/GEARS/`，保留其独立 Git 历史及 MIT license，未修改上游代码。该目录不进入本项目 Git，源码来源及固定 commit 记录在 [gears_source.json](../configs/gears_source.json)。

当前固定版本：`f374e43e197b295016d80395d7a54ddb81cc6769`，源码 package version 为 `0.1.2`。

从新的项目 checkout 恢复同一源码版本：

```bash
git clone https://github.com/snap-stanford/GEARS.git third_party/GEARS
git -C third_party/GEARS checkout f374e43e197b295016d80395d7a54ddb81cc6769
```

图构建入口、依赖与随机属性对照准备见 [GEARS 接入说明](../docs/gears_setup.md)。
