---
name: write-next
description: 写下一章。Use when the author asks 写下一章, 续写, 生成章节, or types /write-next. Preview context then call novel_write_chapter; never overwrite existing prose.
---

# 写下一章

接到已有 `novel_*`。已有正文不得覆盖。

1. `novel_status` 看阶段与待确认项；`outline_scope` 待确认时先让作者确认大纲范围。
2. `novel_outline_read` 定位章纲：未指定则取大纲顺序中最早尚无正文的章。
3. `novel_context_preview` 预检上下文包。
4. `novel_chapter_work` 读取本章到期/超期/待埋入伏笔与字数目标。
5. `novel_write_chapter` 写下一章或指定章。
6. 草稿出来后暂停，请作者选择：通过进入评审、按意见重写、或到创作页手工编辑。

资产不齐时先规划补齐，不切换会话。节拍与审核口令见 novel-creator。
