---
name: progress
description: 看进度。Use when the author asks 看进度, 写到哪, 现在哪一章, or types /progress. Read OpenWrite status; do not invent a local workflow store.
---

# 看进度

接到已有 `novel_*`。不要另建进度文件或阶段机。

1. `novel_status`：当前作品、阶段、资产缺口、待确认项。
2. 需要章级细节时 `novel_chapter_work`。
3. 后台工作 `novel_tasks_list`；进行中或待确认的任务 `novel_task_get`。

向作者报告：当前章、正文是否存在、评审是否新鲜、任务 phase、伏笔到期/超期/待埋入计数。不要把内部 JSON 当主界面。

细则见 workflow-manager。
