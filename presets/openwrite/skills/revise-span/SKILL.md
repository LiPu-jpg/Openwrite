---
name: revise-span
description: 改这段。Use when the author asks 改这段, 扩写, 缩写, 去 AI 味, 按审稿改, or types /revise-span. Stage revision hunks; never PUT the manuscript.
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 改这段

接到已有 `novel_*`。改稿只走修订提案，不直接整章覆盖。

1. 选区扩写/缩写/去 AI 味：`novel_revision(action="create", source="selection"`。
2. 按审稿改：`novel_revision(action="create", source="review"`（带 issue 与期望 revision）。
3. 展示 before/after；作者确认后 `novel_revision(action="apply"`（可带 `selected_hunk_ids`）。
4. 提案的 `source_revision` 与当前正文不一致时拒绝覆盖，改为 `novel_revision(action="regenerate", proposal_id=…)`；仍不匹配就用 `novel_revision(action="create", source="review"/"selection", …)` 生成新提案。该工具没有「重新预览」这一步。
5. 应用后必须 `novel_review_chapter` 复评。

手工/润色类正文预览用 `novel_change_plan(action="document"`。没有当前评审时，按审稿改失败闭合。细则见 novel-reviewer。
