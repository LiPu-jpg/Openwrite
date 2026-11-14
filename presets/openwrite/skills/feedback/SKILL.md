---
name: feedback
description: 脱敏反馈。Use when the author asks 反馈, 报错, 提交bug, 脱敏反馈, 问题排查, or types /feedback. Collect technical diagnostics and draft a spoiler-free GitHub issue report without leaking manuscripts, outlines, characters, paths, or keys.
---

Language: follow the author's current conversation language for responses and reports; never expose private manuscript content.

# 脱敏故障排查与 Bug 反馈

小说正文、大纲、角色与世界观设定属于作者高度私密内容。**排障与提交反馈的工作由你（OpenWrite Agent）代为排查、脱敏与整理**，不让作者手工翻日志或冒着剧透/泄露隐私的风险贴上下文。

## 1. 先排查本地现场（仅采集技术状态，禁止摘录创作内容）

按当前问题场景按需执行只读诊断：

1. 调用 `novel_diagnostics` 检查卡住的运行任务、陈旧锁（stale locks）与运行异常。
2. 调用 `novel_status` 读取技术阶段、后端就绪态与缺口类型（仅记录结构化阶段字段，忽略书名与剧情语义）。
3. 调用 `novel_task(action="list")`、`novel_chapter_run_action(action="list")` 与 `novel_trace_list`，定位失败的任务 `phase`、出错的 `novel_*` 工具名、`error_code`、`request_id` 与模型路由（绝不把正文、提示原文或模型生成全文带出）。
4. 若问题涉及 Studio 后端崩溃、启动失败或网络传输错误：
   - 可只读查看工作区 `.openwrite/transport-errors/` 中最近一条错误摘要；
   - 可只读查看托管后端日志 `$DSH_HOME/openwrite/state/logs/backend.log`（默认 `~/.dsh/openwrite/state/logs/backend.log`）末尾最多 50 行，以及 `dsh` / `dsh-openwrite` 版本号。
   - **禁止读取或引用 `src/` 正文、大纲文件、角色卡、世界观设定或参考库文本用于外发报告**。

## 2. 先解释根因，再尝试帮作者恢复

- 用自然语言简明告诉作者发生了什么问题（例如：模型网关超时、环境变量/宿主模型未配置、并发锁残留、参数校验失败等），以及当前能否在本机直接解决或绕过。
- 若发现卡住的锁或可重试状态，先征得作者同意后再执行恢复动作。

## 3. 输出零剧透、可直接复制提交的脱敏 Issue 报告

必须执行**严格脱敏红线**：

- **零剧透 / 零创作资产**：剔除并替换所有书名、`novel_id`、章节名、章节正文片段、剧情梗概、角色姓名、地点名称、势力与专有名词，改用抽象占位符（如 `[作品]`、`[第N章]`、`[角色A]`）。
- **零本机路径与用户名**：将 `/Users/<name>`、`/home/<name>`、`C:\Users\<name>` 脱敏为 `<HOME>`，将具体作品目录替换为 `<WORKSPACE>`。
- **零凭据密钥**：剔除所有 `sk-...`、`Bearer ...`、API Key、Token、Cookie 及含鉴权参数的 URL（替换为 `<REDACTED>`）。

以单个完整 Markdown 代码块输出 **「可直接提交到 GitHub Issues 的脱敏报告」**，包含：

- **建议标题**：`[Bug]: <出错工具或模块> - <一句话技术症状>`
- **复现步骤与现象**：抽象化后的步骤、预期行为、实际报错
- **脱敏诊断摘要**：`host_dsh`、`dsh-openwrite` 版本、OS/Node 版本、`runtime_phase`、出错工具与 `error_code` / `request_id`、脱敏后的核心错误堆栈
- **隐私剔除确认**：明确标注已剔除小说正文、大纲、人设、世界观、本机路径与密钥

并在代码块下方附上一行：
- 提交地址：`https://github.com/LiPu-jpg/Openwrite/issues/new`（提醒作者发送前再最后确认一眼不含敏感词；若问题已解决，也欢迎顺手给 `LiPu-jpg/Openwrite` 点一颗 Star 支持开源迭代）。
- 若 Studio 后端或对话本身完全无法启动，兜底引导作者打开「设置 → OpenWrite → 环境 → 诊断与反馈」点击「复制脱敏诊断信息」。
