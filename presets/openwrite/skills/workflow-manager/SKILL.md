---
name: workflow-manager
description: Use when user wants to check writing progress, manage workflow stages, or resume interrupted tasks. Triggers include "工作流", "进度", "阶段", "写作流程".
user-invocable: false
---

# 工作流管理

跟踪写章 → 评审 → 修订 → 应用 → 复评 → 交付。全部状态来自 OpenWrite 任务与章节工作简报，不要虚构本地阶段机，也不要调用已废弃的工作流命令。

## 作者可见阶段

1. 上下文预检 — `novel_context_preview`
2. 写章 — `novel_write_chapter` 或后台 `novel_task_create(type=chapter_write)` / `novel_multi_write`
3. 评审 — `novel_review_chapter` 或 `novel_task_create(type=chapter_review)`
4. 作者确认修订 — `novel_revisions_list` → apply / reject
5. 复评与交付 — 应用后复评；交付图为 writing → review → revision → application → rereview → closure

## 工具

| 工具 | 用途 |
|------|------|
| `novel_status` | 全书阶段、缺口、待确认项 |
| `novel_chapter_work` | 单章正文/评审 revision、目标、伏笔义务、最近修改 |
| `novel_tasks_list` | 后台任务列表 |
| `novel_task_get` | 轮询任务 phase 与 result |
| `novel_task_create` | 提交 chapter_write / chapter_review / revision_from_review / research |
| `novel_task_cancel` / `novel_task_retry` / `novel_task_confirm` | 取消、可恢复重试、确认继续 |
| `novel_multi_write` | 按大纲连续写章 |
| `novel_chapter_run_action` | Chapter Run V2 干预 |
| `novel_write_chapter` | 同步写一章（长耗时；编排优先走任务） |
| `novel_review_chapter` | 同步评审一章 |

长操作优先走任务系统，避免 HTTP 超时把服务端写锁做成孤儿任务。

## 用法

### 看进度

用户问「现在写到哪」：

1. `novel_status`
2. 需要章级细节时 `novel_chapter_work`（chapter_id）
3. 进行中的后台工作 `novel_tasks_list`

向作者报告：当前章、正文是否存在、评审是否新鲜、任务 phase、伏笔到期/超期/待埋入计数。不要输出内部 JSON 当主界面。

### 开始写下一章

1. `novel_outline_read` 确认建议章纲
2. `novel_context_preview`
3. `novel_task_create(type=chapter_write)` 或 `novel_write_chapter`
4. `novel_task_get` 直到完成或需要确认

### 中断恢复

会话中断后：

1. `novel_tasks_list` 找 running / failed / awaiting_confirmation
2. recoverable 失败用 `novel_task_retry`；需要作者拍板用 `novel_task_confirm`
3. 不要对已有正文再次 `novel_write_chapter`（服务端会 409）；回炉走 `revision_from_review` → regenerate → apply → 复评

### 连写

`novel_multi_write` 按大纲推进；每章仍要评审。低质量、低覆盖或含 blocker 时进入修订闭环，不要跳过门禁强行交付。

## 状态怎么说

| 观察 | 对作者说 |
|------|----------|
| 任务 `running` | 正在写/审，给任务 id 与 phase |
| `awaiting_confirmation` | 需要确认才能继续 |
| `failed` 且 recoverable | 可重试，说明错误码 |
| 评审 `stale` | 正文已变，必须复评 |
| 交付未 closure | 应用修订后还没复评通过 |

## 与其他技能

- **novel-creator**：单章创作编排
- **novel-reviewer**：评审与修订提案
- **dog-delivery-query**：查询已物化交付图
