# @dsh-novel/studio-panel

dsh web 的原生小说创作工作台。OpenWrite 只作为领域后端，本插件不嵌入 Studio，也不创建第二套导航或 agent 界面。

## 信息架构

- **创作**（`creation`）：canonical 章节/occurrence 导航、reading-packet 连续审读、随包 Vditor 正文编辑器和章节任务检查器。检查器汇总上下文、评审闭环、字数目标、近期修改与分期伏笔。正文在停笔 1.2 秒后自动保存；`PUT /api/document` 携带 `version` 乐观锁。409 时保留本地草稿，只允许显式重载或确认覆盖。
- **资料**（`library`）：内部导航收纳资产、大纲、原生场景结构、连续性图谱、研究与项目搜索。大纲下可只读预览并迁移旧正文场景，按阅读/故事时间双序查看，以三重 revision 保护元数据和跨章移动。
- **任务**（`tasks`）：后台任务、研究发起、导入/导出/同步。Studio 仅保留为会话头溢出菜单里的外部高级维护入口。

dsh 会话头显示当前作品、当前章节、保存状态、连接状态与活动任务数；输入框工具行显示当前章节上下文。常用 `novel_*` 工具按状态、上下文、正文、修订、任务、搜索、资料和大纲八类渲染为原生卡片。成功写操作会失效共享缓存，同一 Turn 的写操作会在 Turn 尾部汇总。

Turn 变更摘要直接处理两种服务端计划：普通正文/正典文档走
`novel_document_change_plan`，大纲、资产、创作重点、伏笔和写作目标走
`novel_structured_change_plan`。接受、拒绝、冲突重试和撤销只回传不可变 token；浏览器
不重组路径或内容，OpenWrite 在写入前重验源 revision，并写入预览阶段保存的精确结果。
搜索改单行也复用该计划：只有命中项与当前文档的稳定 identity/revision 一致才生成预览，
展示服务端 diff 后才允许确认。

## 运行时边界

浏览器数据链路由 `@dsh-novel/openwrite-bridge` 的 `NovelDomainService` 统一提供：

- `GET /studio-panel/config.json`：OpenWrite 后端地址，仅供“外部打开”出口。
- `/studio-panel/api/*`：同源 JSON/下载代理；正文、资产、大纲、场景、任务与导入操作使用受限写白名单。
- `GET /studio-panel/invalidation.json`：轻量 revision/资源键快照。
- `GET /studio-panel/events`：按 Workspace 隔离的 SSE 即时失效通知；热重载时旧连接关闭并重连。

客户端只有一个 `NovelWorkbenchStore`：缓存 workspace/tasks、当前章节、保存状态与各资源 epoch；SSE 处理即时变化，同时每 5 秒读取轻量 revision/context epoch，补充观察后台任务状态。变化时刷新对应资源；切换 Workspace 会中止旧请求并清空旧缓存。

本包 host 半边只负责提供随包编辑器静态文件：

- `/studio-panel/vendor/vditor/dist/index.css`
- `/studio-panel/vendor/vditor/dist/index.min.js`
- Vditor 的 content theme、Lute、图标与中文 i18n 文件

这些文件与 dsh 同源加载，不依赖 Studio 的浏览器资源。

## 构建与验证

```sh
npm ci
npm run build
npm run smoke
```

`smoke` 验证：Vditor 静态路由安全、bundle 无 iframe、顶层恰好三个视图、会话头/输入/Turn slots、共享 API 注入和八类工具卡。仓库级 `scripts/verify.sh` 在运行中的 dsh/OpenWrite 上验证代理、失效快照与本地 Vditor。

仓库级 `npm run check:plugin` 还覆盖锁文件/打包内容、生命周期与组件回归。模型工作台的 Chat 与 Embedding 档案独立管理，并保留未保存保护、凭据不回显和 Chat 删除预览/确认。升级说明见 [维护手册](../../docs/PLUGIN_MAINTENANCE.md)。

所有颜色使用 dsh `--dsw-*` 语义 token。布局在 900px 降为检查器抽屉，在 600px 降为章节/检查器双抽屉与横向内部导航；内容区保留底部空间，避免被 dsh composer 遮挡。
