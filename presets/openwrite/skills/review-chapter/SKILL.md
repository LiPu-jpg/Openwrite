---
name: review-chapter
description: 审这一章。Use when the author asks 审这一章, 审查, 检查逻辑, or types /review-chapter. Run six-domain novel_review_chapter; do not rerun review from DoG.
---

# 审这一章

接到已有 `novel_*`。正式评审是六域累加；37 项只作展开查询。
网文项目（`form: web_novel`）另附钩子 / 黄金三章 / 追读力可选准则，不计分。

1. `novel_outline_read` 与 `novel_status` 确认章节。
2. `novel_chapter_work` 读取正文 revision、评审新鲜度、本章伏笔义务。
3. 尚无正文则提示先写章，不要空审。评审 stale 时先复评。
4. `novel_review_chapter` 跑六域评审。
5. 向作者报告质量分、覆盖率、门禁、交付状态，以及带正文证据的问题。

作者要改稿时转到 /revise-span。查询已物化评审图用 dog-review-query，不要让 DoG 再调模型。细则见 novel-reviewer。
