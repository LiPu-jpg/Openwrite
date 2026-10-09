---
name: novel-manager
description: Use when managing project settings, creating characters, updating world-building, viewing or editing the outline, or checking foreshadowing status. Triggers include "新建", "角色", "世界观", "大纲", "伏笔", "项目", "manage novel".
---

# 小说项目管理

管理角色、世界观、伏笔、大纲等项目数据。在蜂群中由 goethe-planner 角色拥有写入权。

## 单源契约

- `src/outline.md` 是大纲唯一语义真源；`data/hierarchy.yaml` 只是派生缓存，不手工维护
- H1/H2/H3/H4 投影为卷/幕/节/章；附录隔离为附录树，不混入正文层级统计
- 关系数据只在人物/实体文件的 front matter（`[[related]]`）维护，无第二套图数据库
- 结构修改一律先预览 diff、用户确认后写入；Git 存档每次自动建立

## 结构与选章

- 读结构：openwrite-mcp `get_outline` / `list_projects`（与引擎同源的树、行号、正文状态、下一章建议）
- 默认推荐大纲顺序中最早尚无正文的章纲，不按最大章节号盲猜
- 已有正文的章纲只允许打开，不得覆盖
- 删除节点会级联补位后续同类编号；会让已有正文 `ch_XXX` 换号的补位必须拒绝

## 子功能

### 角色管理

- **创建**：收集姓名/层级（主角/配角/客串）/描述/外貌/性格 → 写人物卡（`data/characters/cards/` + `src/characters/*.md`），标注首次出场与关系入口
- **查询**：按 ID 或名称定位；输出基本信息/外貌/性格/关系/时间线事件
- **更新**：增量编辑；关系修改走 world-query 的两阶段确认

### 世界观管理

- 实体（地点/组织/规则/物品）建在 `src/world/entities/*.md`，front matter 含 id/summary/tags/detail_refs/related
- 关系增删改走 front matter `[[related]]` + 预览确认

### 大纲管理

- 增删卷/幕/节/章为最小增量写回 Markdown 片段
- 每次修改携带大纲 revision；冲突时重新读取，禁止用旧 revision 写入

### 伏笔管理

见 foreshadowing-system 技能。

## 与其他技能的关系

- **novel-creator**: 消费大纲与资产写章
- **world-query**: 关系读取与修改的详细契约
- **foreshadowing-system**: 伏笔状态机
