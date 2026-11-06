---
name: world-query
description: Use when querying or maintaining novel world entities, character relationships, or the Studio relationship topology. Triggers include "世界观", "实体", "人物关系", "关系图", "拓扑", and "查询世界".
user-invocable: false
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 世界查询系统

把 `data/novels/{novel_id}/src/` 下的人物与世界实体文件作为唯一关系真源。Studio 拓扑与 `novel_continuity` 必须调用同一份资产数据，不维护 `graph.yaml` 或第二套关系数据库。

## 查询

- 用 `novel_assets(action="list", kind="world")` / `novel_assets(action="list", kind="character")` 查询实体列表。
- 用 `novel_assets(action="read", kind="world", id=…)` 读单个实体详情。
- Studio 关系拓扑支持按节点名称、ID、类型、摘要和关系文字搜索；命中节点会保留一跳相邻节点和连线作为上下文。
- ReAct 没有第二套拓扑搜索索引；需要搜索时先 `novel_assets(action="list")` 再在同一份结果里按上述字段过滤。
- 先用 ID 定位；用户只提供名称时允许按 front matter 名称或 Markdown H1 定位。

兼容读取以下关系来源：

1. TOML front matter 中的 `[[related]]`。
2. 世界实体的 `## 关联` 列表。
3. 人物卡的 `## 关系网络`、`## 人物关系`、`## 与主角的关系`、`## 与某人的关系/羁绊`。

把“主角”解析为 `role = "主角"` 或 `tier = "主角"` 的人物。读取关系目标时清理末尾括号别名，例如 `周策（老周）` 定位到 `周策`。未找到目标时保留 unresolved 节点，不静默丢边。

## 增量修改关系

新建、更新或删除正式关系一律走变更计划的两阶段确认，不直接写文件：

1. `novel_change_plan(action="structured", change_kind="asset", step="preview", change=<一条 novel_assets 形状的变更>)`，
   保存返回的 `preview_token`，向作者展示 diff。此步不写文件。
2. 只有作者明确确认后，才 `step="apply"` 并传回同一个 `preview_token`。
3. 若返回 `DOCUMENT_CONFLICT` 或预览 token 失效，重新 preview；不得复用旧 token 或整文件重写。
4. 作者拒绝、犹豫或只是讨论关系时，不得 apply。

作者已在本轮明确授权过这条精确变更时，才可用直接兼容入口
`novel_assets(action="update", kind="character"|"world", id=…, revision=<刚才 list 得到的 revision>, data={…})`。
`revision` 必须来自刚刚一次 `novel_assets(action="list")`，否则服务端会以 409 拒绝。

正式关系写在源文件 front matter：

```toml
[[related]]
target = "partner_id"
kind = "related"
note = "共同调查旧案"
```

源和目标必须是已有实体，禁止自关系。旧 Markdown 关系段落继续作为兼容只读来源；不要为了修改一条边而覆盖人物卡正文。
