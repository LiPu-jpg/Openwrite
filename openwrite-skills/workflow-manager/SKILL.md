---
name: workflow-manager
description: Use when user wants to check writing progress, manage workflow stages, or resume interrupted tasks. Triggers include "工作流", "进度", "阶段", "写作流程".
---

# 工作流管理系统

章节写作流程的阶段状态机与中断恢复纪律。蜂群编排下各阶段由 SwarmFlow 角色流转，本技能定义阶段的语义与完成标准。

## 阶段状态机

```
context_assembly → writing → review → user_confirm → styling → compression → 完成
```

| 阶段 | 语义 | 完成标准 | 对应工具/角色 |
|------|------|----------|----------------|
| `context_assembly` | 组装上下文 | 上下文包齐备：大纲、真相、伏笔待办、上文、风格 | `get_context_packet` |
| `writing` | 生成草稿 | 草稿落盘，字数达标 | dante-writer |
| `review` | 审查 | 三评审完成，findings 分级 | `get_review_framework` + reviewers |
| `user_confirm` | 用户确认 | 人工门放行（author-gate） | 人类 |
| `styling` | 风格润色 | 润色稿通过风格规则检查 | revision-forge / style-system |
| `compression` | 压缩归档 | 章摘要与伏笔状态写回 | 引擎（MCP 写路径） |

**阶段状态**：`pending` / `running` / `completed` / `failed` / `skipped`。

## 流转规则

1. 阶段必须按序推进；`failed` 阶段原地重试，不得跳段
2. `review` 出现 blocker 时不得进入 `user_confirm`，回到 `writing` 修订
3. `user_confirm` 被否决时回到 `writing`；`skipped` 仅允许人工显式标记
4. **中断恢复**：重新进入会话先查各章阶段位，从最早未完成的 `pending`/`failed` 阶段继续，不重跑 `completed` 阶段

## 查询进度

单章进度与全项目进度经 openwrite-mcp 读取：`get_outline`（章级 drafting 状态）+ `list_foreshadowing`（伏笔推进）+ `get_chapter_foreshadowing`（章待办）。引擎持久化的工作流台账属写路径，第三期接入 MCP 后提供 `get_workflow_status`/`advance_workflow`。

## 与其他系统的关系

- 上下文组装 → `get_context_packet`
- 审查 → `get_review_framework` + 三评审 + post-validation
- 归档压缩 → text-processing 压缩纪律（引擎侧摘要维护）
