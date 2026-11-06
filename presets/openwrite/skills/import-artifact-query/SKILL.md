---
name: import-artifact-query
description: Query a smart-import record after a novel has been split into chapters. Use to inspect import completeness, AI precheck errors, and pending outline/asset/canonical setup.
user-invocable: false
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 拆书导入结果查询

`conductor/smart_import.py` 完成导入后会写出记录：
`data/novels/{id}/data/dog/imports/{IMPORT_ID}/dog-graph.json`，
以及同目录的 manifest。这份记录只描述导入结果，不负责写入章节、资产或大纲。

## 工作流

1. 从导入输出找到 `data/novels/{id}/data/dog/imports/{IMPORT_ID}/`，读 manifest。
2. 按 manifest 的 `status` 汇报导入完整性：`partial|failed` 表示导入中途出错，
   先读 `error` 和已完成的章节，再修复或重试导入。
3. 读 `aiCheck.status`：`failed` 要如实报告，不能当成“无问题”。
4. 根节点通过后，读 manifest 的 `construction.nextActions`，再调用规划和资产工具
   建立大纲、角色、世界观、进度和正典事件。
5. 资产/大纲建立完成后重新调用 `novel_review_chapter`，再用 `review-artifact-query`
   查询六域评审和 37 个 legacy leaf。

## 约束

- 只读导入记录，不直接修改正文。
- `construction` 中的 `pending` 是后续建模待办，不是导入失败。
- 不要让任何验证步骤再调用 Studio 导入接口或重新读取原始整本小说。
