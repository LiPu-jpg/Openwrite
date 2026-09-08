---
name: novel-reviewer
description: Use when user wants to check logic consistency, polish style, find plot holes, or review existing chapters. Triggers include "检查", "润色", "逻辑", "伏笔漏洞", "审查".
---

# 小说审查润色

通过 openwrite-bridge 的 `novel_*` 工具评审与修订。不要调用 Python 审查类或本地 33 维脚本。
正式评审是六域累加：质量分、覆盖率、硬门禁、交付状态分开判断；37 项只作展开查询。

## 触发条件

- "检查逻辑" / "逻辑检查"
- "润色" / "润色风格"
- "找伏笔漏洞" / "伏笔检查"
- "审查章节" / "审查"
- "风格问题"

## 工作流程

1. `novel_outline_read` 与 `novel_status` 确认章节与项目阶段。
2. `novel_chapter_work` 读取正文 revision、已有评审新鲜度、本章伏笔义务。
3. `novel_review_framework` 需要时查看六域与 37 项映射。
4. `novel_review_chapter` 对已有正文跑六域评审（可传 `chapter_id` 或稿件路径）。
5. 向作者报告质量分、覆盖率、门禁、交付状态，以及带正文证据的问题。
6. 作者要改稿：`novel_revision_create_from_review`（或选区 `novel_revision_create_selection`）→ 展示 before/after → 确认后 `novel_revision_apply`。
7. 应用后必须 `novel_review_chapter` 复评；正文 SHA 变了旧评审即 stale。
8. 润色类局部修改走 `novel_document_change_plan` 预览/确认，不直接整章覆盖。

## 工具

| 工具 | 用途 |
|------|------|
| `novel_review_framework` | 六域 / 37 项框架 |
| `novel_review_chapter` | 正式评审（长耗时） |
| `novel_chapter_work` | 评审新鲜度、闭合结果、伏笔 |
| `novel_revision_create_from_review` | 从问题生成修订提案 |
| `novel_revision_create_selection` | 从选区生成修订 |
| `novel_revisions_list` / `novel_revision_get` | 查看提案 |
| `novel_revision_apply` / `novel_revision_reject` / `novel_revision_regenerate` | 应用、驳回、重生成 |
| `novel_document_change_plan` | 手工/润色类正文预览确认 |
| `novel_continuity` | 连续性、关系、未回收伏笔 |

## 六域（计分）与硬门禁

| 域 | 权重 | 关注 |
|---|---:|------|
| 连贯与逻辑 | 20 | 时间线、因果、信息传播 |
| 人物与关系 | 15 | 动机、声音、关系 |
| 情节与承诺 | 20 | 伏笔、支线、情感账单 |
| 节奏与场景 | 15 | 章内节奏、场景完成度 |
| 文笔与表达 | 15 | AI 痕迹、信息倾倒、句式 |
| 正典与引用 | 15 | 设定、专名、前文事实 |
| 硬门禁 | 不计分 | 严重 blocker；只改 `gate_status` |

问题不扣质量分。`inconclusive` 降低覆盖率。交付要求：质量与覆盖达阈值、门禁未阻断、评审源 SHA 等于当前正文 SHA。

## 报告给作者看的结构

```
章节 / 字数 / 评审 revision
质量分 · 覆盖率 · 门禁 · 交付
证据条目（原文定位 + 建议）
本章伏笔：到期 / 超期 / 待埋入（来自 novel_chapter_work）
下一步：生成修订 / 驳回 / 复评
```

定位不唯一时标记失效，不要把错误原文高亮成证据。过期评审必须先复评。

## 错误处理

| 情况 | 处理 |
|------|------|
| 尚无正文 | 提示先写章，不要空审 |
| 评审 stale | 先 `novel_review_chapter`，禁止对旧问题直接 apply |
| 提案源 revision 不匹配 | `novel_revision_regenerate` 或重新预览 |
| 后台任务进行中 | `novel_task_get` 轮询，不要重复提交 |

## 与其他技能

- **novel-creator**：写章后进入本技能
- **dog-review-query** / **dog-delivery-query**：查询已物化评审/交付图，不重新调用模型
- **truth-validation**：正典与事实核对
