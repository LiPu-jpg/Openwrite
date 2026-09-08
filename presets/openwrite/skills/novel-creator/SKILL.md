---
name: novel-creator
description: Use when user wants to write chapters, generate drafts, or continue the story. Triggers include "写第", "生成章节", "续写", "草稿", "创作".
user-invocable: false
---

# 小说创作编排

通过 openwrite-bridge 的 `novel_*` 工具写章。不要调用 Python 模块、内置 Writer 类或已废弃的大纲命令。
所有正文写入走预览/确认门控；已有正文不得覆盖。

## 触发条件

- "写第X章" / "写章节"
- "生成章节" / "生成草稿"
- "续写" / "继续创作"
- "创作" + 章节相关

## 工作流程

1. `novel_status` 看项目阶段、资产缺口、待确认项。
2. `novel_outline_read` 定位章纲：未指定章节时取大纲顺序中最早尚无正文的章；指定章节时校验章纲存在。已有正文则打开或审查，不得直接覆盖。
3. `novel_context_preview` 预检写章上下文包（大纲窗口、出场角色、伏笔、风格、正典）。
4. `novel_chapter_work` 读取本章到期/超期/待埋入伏笔与字数目标。
5. `novel_write_chapter` 写下一章或指定章（可带 `outline_revision` 与 `guidance`）。
6. 草稿出来后暂停，请作者选择：通过进入评审、按意见重写、或到创作页手工编辑。
7. 作者通过后调用 `novel_review_chapter`；需要改稿时用 `novel_revision_create_from_review`，确认后再 `novel_revision_apply`。

## 工具

| 工具 | 用途 |
|------|------|
| `novel_status` | 项目快照、阶段、缺口 |
| `novel_outline_read` | 大纲树与建议下一章 |
| `novel_context_preview` | 写前上下文包 |
| `novel_chapter_work` | 本章目标、伏笔义务、最近修改 |
| `novel_write_chapter` | 写章（长耗时） |
| `novel_review_chapter` | 六域累加评审 |
| `novel_document_change_plan` | 已有正文的逐项预览/确认修改 |
| `novel_structured_change_plan` | 大纲/资产/伏笔的逐项预览/确认 |

`novel_doc_write` 与 `novel_outline_edit` 仅在作者本轮已明确授权精确变更时作为直接写入兼容入口。

## 节拍

从大纲读取本章 **dramatic_position**（起/承/转/合/过渡）和内容焦点。
节拍数量由目标字数决定（3000 以下 2–3 个；3000–5000 为 3–4 个；5000+ 为 4–6 个），写入 `novel_write_chapter` 的 `guidance`。

- **起** → 场景切入 + 悬念铺设 + 角色状态 + 衔接钩子
- **承** → 推进 + 碰撞 + (伏笔) + 递进
- **转** → 升级 + 核心决策 + 后果初现
- **合** → 余波 + 变化确认 + 遗留

## 用户审核（强制）

草稿生成后必须暂停：

```
章节: {chapter_id}
字数: {word_count}
请选择：1 通过并评审  2 按意见重写  3 保存后手工编辑
```

## 前置条件

| 数据 | 必须？ | 如何确认 |
|------|--------|----------|
| 大纲 | 必须 | `novel_outline_read` |
| 本章出场角色 | 必须 | `novel_context_preview` / `novel_assets_list` |
| 合成风格 | 建议 | 上下文包 |
| 伏笔 | 可选 | `novel_chapter_work` 的分类义务 |

资产不齐时先规划补齐，不切换会话。`novel_status` 若显示 `outline_scope` 待确认，先让作者确认大纲范围再写。

## 错误处理

| 情况 | 处理 |
|------|------|
| 上下文超限 | 报告 `novel_context_preview` 的压缩/保护原因，不静默丢掉正典 |
| 章纲缺失 | 回到规划，用 `novel_structured_change_plan(change_kind="outline")` |
| 已有正文 | 打开或审查；改稿走 `novel_document_change_plan` |
| 写章失败 | 用 `novel_tasks_list` / `novel_task_get` 查看后台任务，可 `novel_task_retry` |

## 与其他技能

- **novel-reviewer**：写完后评审
- **workflow-manager**：连写、后台任务、中断恢复
- **foreshadowing-system**：伏笔 DAG 维护仍走 `novel_structured_change_plan` / `novel_foreshadowing`
