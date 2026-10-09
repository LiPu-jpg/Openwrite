---
name: novel-creator
description: Use when writing chapters, generating drafts, or continuing the story. Triggers include "写第", "生成章节", "续写", "草稿", "创作", "write chapter".
---

# 小说创作编排

编排 **Director → Writer → 用户审核 → Stylist** 完整创作流程。在蜂群中由 dante-writer 角色执行。

## 触发

"写第X章" / "生成章节" / "续写" / "继续创作"。

## 流程

### Step 1: 解析意图

提取章节 ID（`ch_005` 或"第五章"）、创作目标、约束条件。
未指定章节时调 openwrite-mcp `get_outline` / `list_projects` 选大纲顺序中最早无正文的章纲（含面包屑与目标字数）。已有正文的章节打开或审查，不得直接覆盖。

### Step 2: 组装上下文

调 `get_context_packet(project_root, novel_id, chapter_id)` 获取 canonical packet，其分区：

- 大纲窗口（前后章衔接）与当前章戏剧位置（起/承/转/合）
- 出场角色档案（involved_characters）
- 伏笔待办（本章应推进/回收）
- 三层风格（craft 技法 / source pack 提取风格 / 本书设定约束）
- truth 三文件（current_state / ledger / relationships）
- 上下文预算（压缩策略与级别，不可删除作者意图/创作罗盘/当前章）

### Step 3: 确定戏剧位置

从大纲读取 dramatic_position 与内容焦点，理解本章在所属节中的承接关系。
示例：`▶ 本章位于: 转 ▶ 本章焦点: 主角发现真相，内心崩溃`

### Step 4: 生成节拍

节拍是章内微结构，按戏剧位置：
- **起** → 场景切入 + 悬念铺设 + 角色状态 + 衔接钩子
- **承** → 推进 + 碰撞 + (伏笔呼应) + 递进
- **转** → 升级 + 核心决策 + 后果初现
- **合** → 余波 + 变化确认 + 遗留

节拍数由字数决定（<3000 字 2-3 个；3000-5000 字 3-4 个；>5000 字 4-6 个）。

### Step 5: 生成草稿

节拍扩写为散文：情绪由作者意图+章纲+上下文决定；节奏匹配戏剧位置；应用风格档案；角色声音一致。

### Step 6: 用户审核（强制门）

输出草稿预览（章节/戏剧位置/字数/节拍数/前 500 字），等待：通过 → 润色；重写 → 带意见回 Step 4；手动编辑 → 存草稿退出。
蜂群模式下此门映射 author-gate。

### Step 7: 风格润色（可选）

按 style-system 检查：AI 痕迹、声音一致性、节奏分布（匹配戏剧位置张力）、信息倾倒。

### Step 8: 保存

`data/novels/{id}/data/manuscript/arc_001/ch_005.md`（最终版 + 初稿 + 审查记录）。

## 前置条件

| 数据 | 必须？ |
|---|---|
| 大纲（src/outline.md + hierarchy.yaml） | ✅ |
| 出场角色卡 | ✅ |
| 合成风格（data/style/composed.md） | 建议 |
| 世界观 / 伏笔 | 可选 |

## 错误处理

上下文超限自动分级压缩；角色档案缺失用简卡；生成失败重试 3 次；用户中断保存草稿。
