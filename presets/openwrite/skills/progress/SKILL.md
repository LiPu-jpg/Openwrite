---
name: progress
description: 看进度。Use when the author asks 看进度, 写到哪, 现在哪一章, or types /progress. Read OpenWrite status; do not invent a local workflow store.
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 看进度

接到已有 `novel_*`。不要另建进度文件或阶段机。

1. `novel_status`：当前作品、阶段、资产缺口、待确认项。
2. 需要章级细节时 `novel_chapter_work`。
3. 后台工作 `novel_task(action="list"`；进行中或待确认的任务 `novel_task(action="get"`。

向作者报告：当前章、正文是否存在、评审是否新鲜、任务 phase、伏笔到期/超期/待埋入计数。不要把内部 JSON 当主界面。

- **新作品 / 空项目初始引导**：如果 `novel_status` 显示项目未初始化或大纲、角色、正文均为空，除了如实报告当前为空外，主动给出 3 步起手引导：
  1. 在「设置 → OpenWrite → 模型」确认或一键添加宿主模型；
  2. 直接在对话里聊题材、主角与核心冲突（我会生成设定与大纲 diff 供预览确认）；
  3. 确认大纲后用 `/write-next` 写下一章、`/review-chapter` 审稿。
- **遇到报错与隐私安全反馈**：如果读取状态或任务失败，说明原因并提醒作者可在「设置 → OpenWrite → 环境 → 诊断与反馈」点击「复制脱敏诊断信息」（**不含任何小说正文、设定、路径与密钥**），前往 https://github.com/LiPu-jpg/Openwrite/issues 反馈（觉得好用也可以顺手点 Star 支持开源）。

细则见 workflow-manager。
