---
name: truth-validation
description: Use when validating story consistency, checking plot holes, or verifying state changes against the runtime truth files. Triggers include "验证", "一致性", "检查逻辑", "状态冲突", "truth".
---

# 真相文件验证系统

验证真相文件与章节内容的一致性。真相文件是运行态状态投影（非设定真源）：

- `data/world/current_state.md` — 世界当前状态
- `data/world/ledger.md` — 资源账本
- `data/world/relationships.md` — 角色关系矩阵

## 工具（openwrite-mcp）

| MCP 工具 | 说明 |
|---|---|
| `get_truth` | 读取三份真相文件的当前内容 |
| `get_chapter_foreshadowing` | 伏笔状态（验证的关联输入） |

## 验证问题类型

| 严重程度 | 类型 | 说明 |
|---|---|---|
| critical | 状态矛盾 | 章节内容与真相文件矛盾 |
| critical | 时间悖论 | 时间线矛盾 |
| warning | 叙事缺失 | 状态变化没有叙事支持 |
| warning | 伏笔异常 | 伏笔未回收就消失 |
| info | 回溯编辑 | 状态变化暗示发生在前章 |

## 验证流程

1. `get_truth` 取当前状态基线；对比本章正文陈述的事实（位置、资源、关系、时间）
2. 逐项核对状态变化是否有叙事支撑；无支撑记"叙事缺失"
3. 核对伏笔：待回收是否回收、已埋伏笔是否呼应、有无未声明回收
4. 输出按严重程度分级，每条附正文引文 + 真相文件条目

## 常见问题及修复

- **状态矛盾**：先确认是否穿越/传送类情节；是则更新真相文件，否则修复正文
- **时间悖论**：补过渡段落说明时间流逝，或修正天数
- **叙事缺失**：补修炼/突破场景，或回退真相文件状态

## 验证时机

写完章节后、审查章节前、重大剧情转折前、发现逻辑问题时。验证不修改任何文件——修复走修订流程。
