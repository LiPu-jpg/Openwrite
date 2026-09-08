---
name: revise-span
description: 改这段。Use when the author asks 改这段, 扩写, 缩写, 去 AI 味, 按审稿改, or types /revise-span. Stage revision hunks; never PUT the manuscript.
---

# 改这段

接到已有 `novel_*`。改稿只走修订提案，不直接整章覆盖。

1. 选区扩写/缩写/去 AI 味：`novel_revision_create_selection`。
2. 按审稿改：`novel_revision_create_from_review`（带 issue 与期望 revision）。
3. 展示 before/after；作者确认后 `novel_revision_apply`（可带 `selected_hunk_ids`）。
4. 提案 `source_revision` 与当前正文不一致时拒绝覆盖，改为 `novel_revision_regenerate` 或重新预览。
5. 应用后必须 `novel_review_chapter` 复评。

手工/润色类正文预览用 `novel_document_change_plan`。没有当前评审时，按审稿改失败闭合。细则见 novel-reviewer。
