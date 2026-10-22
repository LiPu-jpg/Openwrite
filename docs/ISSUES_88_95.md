# Core 5.8.11：写作与恢复修复

插件 0.2.24 / Core 5.8.11 修复 #88–#95，已发布到 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.24) 与 [npm](https://www.npmjs.com/package/dsh-openwrite/v/0.2.24)；分发状态和完整验收见 [发布验收](RELEASE_ACCEPTANCE.md#024)。测试使用假模型和隔离目录，不调用付费模型。

| Issue | 行为 |
| --- | --- |
| #88 | 删章在项目写锁内清除验收 head、递增 revision、保存删除 operation；未完成旧 operation 不再允许 resume。 |
| #89 | 账本有 head 而文件不存在时返回 `missing` 和 `CHAPTER_FILE_MISSING` warning，不阻断事实门禁；原文恢复后自动回到 current。 |
| #90 | 结算格式错误最多重试两次，收紧提示且保留全部正文。耗尽后保存带降级标记的摘要，reconcile task 返回 `completed`、`degraded: true`。网络、认证等异常仍返回实际失败。 |
| #91 | 写作 Agent、修订、语料分析/打包与结算使用 `OW_AGENT_STREAM`（默认 1）；流式请求使用读空闲超时，保留已接收的短片段。`OW_LLM_TIMEOUT` 可覆盖超时，默认 300 秒，默认 SDK 重试一次。 |
| #92 | HTTP `POST /api/write` 提交 `chapter_write` 后立即返回 `task_id`。任务详情保留原有 `phase`，另提供 context/plan/draft/fact_extract/settle/validate/commit 的 `stage`、`run_id_v2`。后台任务保留原始工具调用追踪。锁每 15 秒更新心跳，死进程锁在下一次获取时回收。 |
| #93 | 上下文、writer 和 reviewer 共用 `chapter_word_bounds`（目标 -20%/+50%）和 `count_writing_units`。4200/5000 单位无需补写；真正超限先尝试两次唯一文本锚定修改，再允许一次整章调整。 |
| #94 | 删章派生数据移入 `data/chapter_deletions/<operation_id>/`，备份地址指向归档。未提交草稿有列表和显式恢复接口；恢复使用原 run id、逐字节复制，不生成新正文。 |
| #95 | 任务写入 `finished_at`，读端兼容旧 `completed_at` 并返回 `duration_ms`。导出预检使用阅读顺序的缺章判定；诊断默认只显示近 24 小时的历史事件，历史数量单独返回，成功任务重置失败连续计数。未知 API 路由返回 404 `ROUTE_NOT_FOUND`，方法错误返回 405 `METHOD_NOT_ALLOWED` 和 `Allow`。 |

## 草稿恢复

1. `GET /api/manuscript/drafts` 返回 chapter_id、run_id_v2、draft_path、draft_artifact、word_count、created_at、draft_revision 和 restorable。
2. `POST /api/manuscript/drafts/restore` 传入 `run_id_v2`、`confirm: true`。覆盖已有正文还必须传入当前正文的 `expected_revision`；缺失正文传空字符串。
3. 响应返回 `operation` 和 `requires_reconcile: true`。原始草稿已经写回正文；运行 acceptance reconcile 后才会宣告事实 current。恢复正文这一步不调用模型。

同步 Python 应用方法 `write_next_chapter()` 保持可用。HTTP 写作的结果通过 `/api/tasks/<task_id>` 读取，错误中的 `details` 包含已落盘草稿路径。取消或流中断也保留可发现的正文片段。

诊断支持 GET/POST `/api/diagnostics` 的 `since`（ISO 时间）与 `window_hours`；CLI 为 `openwrite diagnose --window 24 --since <ISO>`。缺章、当前设定冲突等仍存在的状态问题持续报告；时间窗口只淘汰已发生的任务、运行和传输事件。

## 验证范围

回归覆盖五轮删章/重建、缺失文件恢复、三次非 mapping 降级、原字节/CRLF 草稿恢复、取消与流中断保稿、后台进度、错误恢复路径、HTTP 404/405、过期诊断及统一字数门限。没有将真实服务商连续 20 次请求或 Windows Electron 实机验收标记为通过。

## dsh 工具入口

`novel_manuscript_edit_action(action="drafts")` 列出未提交草稿；`action="restore_draft"` 传 `run_id_v2`、`confirm: true`，覆盖已有正文时用 `revision` 传当前正文 SHA。工具将其映射到 Core 的 `expected_revision`。恢复属于本地写入操作；不会按生成任务执行。随后使用现有验收调和工具处理返回的 operation。

#86、#87 的精确宿主 `0.2.1-rc.2` 声明已经包含在 0.2.23，本版继续保留该兼容范围。

插件验证：`npm run check:plugin` 通过（构建、doctor、36 项生命周期检查、预设与双 profile、bridge/panel smoke、14 项 epoch、298 项组件）；`npm run test:managed` 23 项通过，跨仓库 contracts 通过。

核心全量 pytest：1409 passed、32 skipped；新 wheel 另做打包内容与针对性回归检查。发布版本为插件 0.2.24 / Core 5.8.11。

新 wheel 解包后隔离导入并执行针对性回归：11 passed。已合并核心 [PR #96](https://github.com/LiPu-jpg/Openwrite/pull/96) 与插件 [PR #97](https://github.com/LiPu-jpg/Openwrite/pull/97)。
