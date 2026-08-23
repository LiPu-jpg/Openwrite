# @dsh-novel/studio-panel

dsh web 的原生小说创作工作台。OpenWrite 只作为领域后端，本插件不嵌入 Studio，也不创建第二套导航或 agent 界面。

## 信息架构

- **创作**（`creation`）：章节导航、随包 Vditor 正文编辑器、上下文/审稿/修订检查器。正文在停笔 1.2 秒后自动保存；`PUT /api/document` 携带 `version` 乐观锁。409 时保留本地草稿，只允许显式重载或确认覆盖。
- **资料**（`library`）：内部导航收纳资产、大纲、连续性图谱、研究与项目搜索。大纲默认仅展开当前章节路径，摘要在选中节点后显示。
- **任务**（`tasks`）：后台任务、研究发起、导入/导出/同步。Studio 仅保留为会话头溢出菜单里的外部高级维护入口。

dsh 会话头显示当前作品、当前章节、保存状态、连接状态与活动任务数；输入框工具行显示当前章节上下文。常用 `novel_*` 工具按状态、上下文、正文、修订、任务、搜索、资料和大纲八类渲染为原生卡片。成功写操作会失效共享缓存，同一 Turn 的写操作会在 Turn 尾部汇总。

## 运行时边界

浏览器数据链路由 `@dsh-novel/openwrite-bridge` 的 `NovelDomainService` 统一提供：

- `GET /studio-panel/config.json`：OpenWrite 后端地址，仅供“外部打开”出口。
- `/studio-panel/api/*`：同源 JSON/下载代理；正文、资产、大纲、任务与导入操作使用受限写白名单。
- `GET /studio-panel/invalidation.json`：轻量 revision/资源键快照。
- `GET /studio-panel/events`：为其他客户端保留的 SSE 兼容出口。

客户端只有一个 `NovelWorkbenchStore`：缓存 workspace/tasks、当前章节、保存状态与各资源 epoch；每 1.5 秒只读取轻量 revision，变化时刷新对应资源，并每 15 秒做一次兜底全量同步。agent 工具、浏览器写入和后台任务的变化会在 2 秒内反映到相关视图。

本包 host 半边只负责提供随包编辑器静态文件：

- `/studio-panel/vendor/vditor/dist/index.css`
- `/studio-panel/vendor/vditor/dist/index.min.js`
- Vditor 的 content theme、Lute、图标与中文 i18n 文件

这些文件与 dsh 同源加载，不依赖 Studio 的浏览器资源。

## 构建与验证

```sh
npm install
npm run build
npm run smoke
```

`smoke` 验证：Vditor 静态路由安全、bundle 无 iframe、顶层恰好三个视图、会话头/输入/Turn slots、共享 API 注入和八类工具卡。仓库级 `scripts/verify.sh` 在运行中的 dsh/OpenWrite 上验证代理、失效快照与本地 Vditor。

所有颜色使用 dsh `--dsw-*` 语义 token。布局在 900px 降为检查器抽屉，在 600px 降为章节/检查器双抽屉与横向内部导航；内容区保留底部空间，避免被 dsh composer 遮挡。
