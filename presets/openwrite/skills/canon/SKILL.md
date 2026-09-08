---
name: canon
description: 查设定。Use when the author asks 查设定, 人物卡, 世界观, or types /canon. Read registered assets and search; do not create a second lorebook.
---

# 查设定

接到已有 `novel_*`。人物、地点、世界观以 OpenWrite 资产为准。

1. `novel_assets_list` 列出人物/世界资产（含名称与别名）。
2. 指定实体用 `novel_asset_read`。
3. 按名称或别名找不到时 `novel_search`（scope 可 `assets`）。
4. 关系与状态漂移用 `novel_continuity`。

向作者报告规范名、别名、摘要。改设定走 `novel_structured_change_plan(change_kind="asset")`；普通讨论不得写入。
