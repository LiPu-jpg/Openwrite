---
name: world-query
description: Use when querying or maintaining novel world entities, character relationships, or the relationship topology. Triggers include "世界观", "实体", "人物关系", "关系图", "查询世界", "world building".
---

# 世界查询系统

把 `data/novels/{novel_id}/src/` 下的人物与世界实体文件作为唯一关系真源。不维护第二套关系数据库或 graph 缓存。

## 读取

优先用 openwrite-mcp 的 `get_context_packet` 获取已组装的世界与人物分区；需要单查时直接读源文件：

- `src/characters/*.md` — 人物卡（front matter 索引 + 正文）
- `src/world/entities/*.md` — 世界观实体
- 先用 ID 定位；用户只给名称时按 front matter 名称或 Markdown H1 定位
- 兼容三种关系来源：front matter `[[related]]`、实体文件的 `## 关联` 段、人物卡的关系段落
- 把"主角"解析为 `role = "主角"` 或 `tier = "主角"` 的人物
- 关系目标清理末尾括号别名（`周策（老周）` → `周策`）；未找到目标保留 unresolved，不静默丢边

## 增量修改关系（两阶段确认）

1. 先产出 diff 预览（不写入），向用户展示
2. 用户明确确认后才写入源文件 front matter：

```toml
[[related]]
target = "partner_id"
kind = "related"
note = "共同调查旧案"
```

3. 用户拒绝、犹豫或只是讨论时，不得写入
4. 源和目标必须是已有实体，禁止自关系；不为改一条边而覆盖人物卡正文

## 输出纪律

查询结果标注来源文件与行号，供评审证据引用（reviewer-canon 的 finding 证据格式依赖此约定）。
