---
name: world-query
description: Use when querying or maintaining novel world entities, character relationships, or the Studio relationship topology. Triggers include "世界观", "实体", "人物关系", "关系图", "拓扑", and "查询世界".
---

# 世界查询系统

把 `data/novels/{novel_id}/src/` 下的人物与世界实体文件作为唯一关系真源。Studio 拓扑和 ReAct 的 `get_world_relations` 必须调用同一个拓扑查询，不维护 `graph.yaml` 或第二套关系数据库。

## 查询

- 用 `query_world` 查询实体列表或详情。
- 用 `get_world_relations` 读取与 Studio 连续性页面同源的节点和边。
- Studio 关系拓扑支持按节点名称、ID、类型、摘要和关系文字搜索；命中节点会保留一跳相邻节点和连线作为上下文。
- ReAct 没有第二套拓扑搜索索引；需要搜索时读取 `get_world_relations` 后在同一份节点/边结果中按上述字段过滤。
- 先用 ID 定位；用户只提供名称时允许按 front matter 名称或 Markdown H1 定位。

兼容读取以下关系来源：

1. TOML front matter 中的 `[[related]]`。
2. 世界实体的 `## 关联` 列表。
3. 人物卡的 `## 关系网络`、`## 人物关系`、`## 与主角的关系`、`## 与某人的关系/羁绊`。

把“主角”解析为 `role = "主角"` 或 `tier = "主角"` 的人物。读取关系目标时清理末尾括号别名，例如 `周策（老周）` 定位到 `周策`。未找到目标时保留 unresolved 节点，不静默丢边。

## 增量修改关系

新建、更新或删除正式关系时使用 `edit_world_relation`，并固定执行两阶段确认：

1. 先以 `confirm=false` 调用，保存返回的 `base_revision`，向用户展示 diff。此步不得写文件。
2. 只有用户明确确认后，才传回同一个 `base_revision` 并设置 `confirm=true`。
3. 若返回 `relation_revision_conflict`，重新预览；不得复用旧 revision 或整文件重写。
4. 用户拒绝、犹豫或只是讨论关系时，不得确认写入。

正式修改统一写入源文件 TOML front matter：

```toml
[[related]]
target = "partner_id"
kind = "related"
note = "共同调查旧案"
```

使用 `action="upsert"` 新增或更新，使用 `action="remove"` 删除。源和目标必须是已有实体，禁止自关系。旧 Markdown 关系段落继续作为兼容只读来源；不要为了修改一条边而覆盖人物卡正文。
