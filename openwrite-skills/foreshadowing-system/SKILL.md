---
name: foreshadowing-system
description: Use when managing novel foreshadowing (伏笔), tracking story hooks, or checking pending reveals. Triggers include "伏笔", "埋伏笔", "待回收", "伏笔状态", "foreshadowing".
---

# 伏笔管理系统

管理小说中的伏笔和悬念，确保故事线索连贯。状态机与 DAG 规则继承 OpenWrite foreshadowing-system。

## 核心概念

**伏笔状态**：`埋伏`（已埋下待回收）/ `待收`（即将回收）/ `已收`（已回收）/ `废弃`（放弃）。
**伏笔层级**：`主线`（权重 ≥7）/ `支线` / `彩蛋`。

## 工具（openwrite-mcp）

| MCP 工具 | 说明 |
|---|---|
| `list_foreshadowing` | 列出伏笔节点，可按状态过滤；返回 DAG 健康检查 |
| `get_chapter_foreshadowing` | 指定章节关联的伏笔（本章应推进/回收的待办） |
| `update_foreshadowing_status` | 更新伏笔状态（写回伏笔 DAG） |

## 工作流

1. **写章前**：调 `get_chapter_foreshadowing(chapter_id)` 取本章伏笔待办，并入上下文。
2. **写章后**：核对正文实际推进/回收与登记是否一致；不一致即评审 blocker。
3. **状态推进**：`埋伏 → 待收 → 已收` 逐级流转，`update_foreshadowing_status` 写回；废弃需注明理由。
4. **周期检查**：`list_foreshadowing` 全量 + DAG 验证；关注超期未收（埋设章与当前章距离远超计划窗口）。

## 伏笔设计原则

1. **可识别性** — 伏笔要能被读者注意到
2. **合理性** — 回收时要有合理铺垫
3. **权重分配** — 重要伏笔高权重，主线 ≥7
4. **时机控制** — 埋设与回收之间要有足够铺垫

## DAG 规则（硬约束）

1. **无环** — 伏笔之间不能循环依赖
2. **有向** — 边从伏笔指向回收点
3. **可达** — 每个待收伏笔必须有明确回收章节
4. **登记先于回收** — 未声明的回收视为评审 finding
