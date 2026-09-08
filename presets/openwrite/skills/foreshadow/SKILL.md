---
name: foreshadow
description: 查伏笔。Use when the author asks 查伏笔, 待回收, 超期伏笔, or types /foreshadow. Read chapter obligations and continuity; do not keep a second foreshadow store.
---

# 查伏笔

接到已有 `novel_*`。伏笔真源是 OpenWrite DAG 与章节工作简报。

1. `novel_status` 看全书待办。
2. 当前章用 `novel_chapter_work`：到期 `must_resolve`、超期 `overdue`、待埋入 `to_plant`。
3. 全书未回收与漂移用 `novel_continuity`。

向作者报告分类清单，不要输出内部 JSON 当主界面。写入走 `novel_structured_change_plan(change_kind="foreshadowing")`；仅在作者本轮已授权精确变更时才用 `novel_foreshadowing`。
