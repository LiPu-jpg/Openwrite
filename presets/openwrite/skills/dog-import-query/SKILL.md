---
name: dog-import-query
description: Query a smart-import DoG graph after a novel has been split into chapters. Use to inspect import completeness, AI precheck errors, and pending outline/asset/canonical setup.
---

# 拆书导入 DoG 验收

`conductor/smart_import.py` 完成导入后会生成 `dog-graph.json`。这张图只验收导入
结果，不负责写入章节、资产或大纲。

## 工作流

1. 从导入输出中找到 `data/novels/{id}/data/dog/imports/{IMPORT_ID}/dog-graph.json`。
2. 依次调用 `dog_validate`、`dog_create`、`dog_run`、`dog_wait`，直到终态。
3. 用 `dog_status` 查看 `manifest` 和每个 `chapter-ch_*` 节点的 evidence。
4. 根节点通过后，读取 manifest 的 `construction.nextActions`，再调用规划和资产工具建立大纲、角色、世界观、进度和正典事件。
5. 资产/大纲建立完成后重新运行 `novel_review_chapter`，再用 `dog-review-query`
   查询六域评审和 37 个 legacy leaf。

## 约束

- DoG 失败只说明导入文件缺失、为空或 manifest 不一致；不要直接修改正文。
- `status=partial|failed` 表示导入中途出错；先读取 manifest 的 `error` 和已完成的章节，再修复或重试导入。
- `aiCheck.status=failed` 要如实报告，不能当成“无问题”。
- `construction` 中的 `pending` 是后续建模待办，不是导入失败。
- 不要让 DoG verifier 再调用 Studio 导入接口或重新读取原始整本小说。
