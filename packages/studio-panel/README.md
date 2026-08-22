# @dsh-novel/studio-panel

dsh web 的 client 插件，把 OpenWrite Studio 的关键界面原生融入会话 UI：

- **总览**（id `overview`，order 19）：**原生工具箱条** + 内嵌 Studio 仪表盘。工具箱补齐 Studio「工具与设置」抽屉在 dsh 侧的最后缺口——导出（md/txt/epub，经二进制安全代理下载，Content-Disposition 文件名）、同步项目、导入章节（选文件 → 预览切章计划/冲突检测 → 确认导入，支持起始章节号与强制覆盖；TXT/Markdown）。
- **正文**（id `studio`，order 20）：内嵌 Studio 章节编辑器（iframe 钉到 `#chapters`）。
- **审稿**（id `review-ws`，order 21）：内嵌 Studio 审稿工作台（iframe 钉到 `#review`）。
- **大纲**（id `outline`，order 22）：原生大纲树，**默认即可编辑（Obsidian 哲学：内容本身就是编辑器）** —— 卷/篇/节/章层级、kind 徽章、成稿状态，可折叠；标题与正文块渲染为无框 input/textarea（视觉与纯文本一致，focus 才现细边框），点击即改，失焦/回车自动提交（未变更不提交）；悬停出结构钮（+下级 / +同级 / 删），工具栏「新增卷」。全部走 `POST /api/outline/edit` 原子树编辑（revision 乐观锁；成功静默更新 revision 不重渲染——焦点与滚动位置保留；409 冲突自动刷新结构并提示重试；delete 由服务端连续重编号后续章节）。按钮可用性以线上 `editable` / `can_delete` / `child_kind` 为准（正文章节的章节号校验错误透传）。注意：章重命名会更换节点 id，紧随其后的同节点操作可能 404——错误路径自动重载结构。
- **资产**（id `assets`，order 23）：原生结构化资产库（对应 Studio 左侧导航的「资料库」，可完整替代），Obsidian 式主从布局——左侧栏（288px，独立滚动）：分段切换（角色/设定/进阶体系/参考作品/作品核心，纵向带计数）、搜索框（按名称/ID/类型/别名/标签/摘要过滤）、紧凑条目行（设定段按 asset_type 折叠分组）、底部新建/刷新按钮；右侧主区：**选中即编辑**（可编辑三类无只读卡片门，直接进 AssetEditor：front-matter 字段 + 关系增删 + 正文即 Vditor IR 实时渲染（运行时从 Studio 源 `${studioUrl}/vendor/vditor/dist/` 按需注入 <script>/<link>，不打包；主题跟随 shell 的 `body[data-ds-dark-theme]`，MutationObserver 实时切换；加载失败回退纯文本 textarea 并提示））；保存走乐观锁 `revision`，保存后留在编辑态（revision 变化触发编辑器以服务端真值重挂），409 冲突给「刷新重试」；取消=放弃本地草稿重取真值；新建为内联表单（占用主区）。参考作品段（Studio 的 deconstruct 面，**不是**资料库）与作品核心段（`documents.core` + `GET /api/document`）只读。未选中时主区显示选择提示。
- **任务**（id `tasks`，order 24）：后台任务中心 —— 状态过滤片（运行中/待确认/排队/已中断/失败/已取消/已完成）、类型徽章（写章/评审/连写/修订/风格源/参考库/导入/研究）、phase 进度信号、失败任务的错误消息；每 5s 轮询（页面隐藏时跳过，切换标签卸载即停止），只读（取消/重试留在 agent 工具）。
- **图谱**（id `graph`，order 25）：完整连续性面，分段控件切四段。**伏笔**：SVG 伏笔板按 主线/支线/彩蛋 分列、按回收章节排序（节点卡：内容截断 + 权重/回收目标/状态，title 悬浮全文；无图库，小型确定性布局），上方叠 `foreshadowing_validation.errors` 校验错误块（逐条列出，错误数同时以 ⚠ 角标挂在分段片上）。**关系图**：圆形布局，有向弦边带箭头与关系标签（未确认关系虚线，未归档节点空心），带类型过滤片（角色/势力/地点/概念/其他，多选，默认角色+势力，边只在两端点可见时渲染；可见节点 >30 隐藏边标签改悬浮 <title>，>40 节点标签截断到 6 字）。**事实账本**：`truth` 的三份 markdown 文档（当前状态/资源账本/关系矩阵，truth_manager.py TruthFiles 是纯文本不是结构化行）经 MarkdownText 渲染。**工作流**：`workflows[]` 每章流水线紧凑列表（章节号 + 当前阶段 + 各 stage 状态徽章，message 走 title 悬浮，error 单独成行）。全部只读。
- **研究**（id `research`，order 26）：深度研究报告库，主从布局——左侧报告列表（标题 + 状态·时间），右侧报告全文 MarkdownText 渲染（头部带 status/episode/时间/质量/语言标签，后两者仅在元数据提供时显示）。工具栏显示运行环境就绪态（未就绪时透传服务端 `setup_hint`）。只读（发起研究与保存 API 设置留在 Studio / agent 工具）。
- **搜索**（id `search`，order 27）：项目资料原生搜索——防抖（350ms）搜索框 + 范围下拉（all/outline/core/characters/settings/continuity/chapters/sources，即服务端 canonical scopes），结果列表显示标题、scope/category 徽章、`path:line`、snippet 内查询词高亮（`<mark>`；payload 无偏移量，用响应里的归一化 query 在客户端重匹配），有加载/空态/服务端 warning 提示。唯一的交互式（非变更）视图。
- **novel_review_chapter 评审卡**：`tool.call.toolview` 键控渲染器，把 37 维章节评审 JSON 渲染成报告卡（总分/结论横幅 + 按类别分组的问题列表 + 引用与修改建议），形状异常时回退到美化 JSON。

## 它是怎么被加载的

本包是一个带浏览器半边的 cordis 插件，由两部分组成：

- **Host 半边**（`src/index.ts` → `lib/index.js`）：一个最小 cordis 插件，声明 `Config` schema（Schemastery，`studioUrl` 默认 `http://127.0.0.1:4567`），并在 dsh web server 上注册两条同源路由：
  - `GET /studio-panel/config.json`：把解析后的配置发给浏览器；
  - `GET /studio-panel/api/<path...>?query`（prefix 路由）：代理到 `${studioUrl}/api/<path...>?query`，透传上游状态码、content-type 与响应体（含错误体）；Studio 不可达时 502 JSON。**写通道带白名单**：仅 `assets`、`assets/update`、`assets/package/import`、`outline/edit`、`sync`、`import/preview`、`import` 七个路径接受 POST/PUT（转发方法与 JSON body 原文，注入 Studio 写操作必需的 `X-OpenWrite-Studio: 1` 头）；其余路径保持 GET-only（405）。正文变更仍留在 agent 工具（`@dsh-novel/openwrite-bridge`）；UI 可写资产域与大纲结构域。
  `webServer` 通过 `ctx.inject` 可选等待，因此在无 web server 的 profile（如 headless）里也能正常加载，只是不注册路由。
- **Client 半边**（`src/client/` → `lib/client.js`）：package.json 里的 `dsh.client` 块（`platform: "web"`）+ `exports["./client"]` 指向构建产物。dsh web 的 client 模块表（`ctx.clientModules`）扫描 host Loader 条目时发现该声明，把 bundle 挂到 `/plugins/@dsh-novel/studio-panel/client.js` 并注入启动图；浏览器半边用 `ctx.slots.inject('conversation.view', function* () { ... })` 等待 ui-conversation 声明槽位后逐个 yield 四个视图注册，并用 `ctx.slots.inject('tool.call.toolview', ...)` 注册评审卡（与 ui-trajectory / bash-sample 同一模式）。

安装走 profile bundle 路径（与 `@dsh-novel/openwrite-bridge` 相同）：`scripts/install.sh` 把本包 `pnpm add -w` 进 `~/.dsh/profiles/web/` 并追加到 `dsh.profile.bundles`；`cordis.patch.yml` 通过 `--patch` 叠加层或 profile 的 `dsh.bundle.patch` 把插件挂进 cordis 配置树。加载后，打开任意会话即可在头部标签栏看到「聊天 / 轨迹 / 总览 / 正文 / 审稿 / 大纲 / 资产 / 任务 / 图谱 / 研究 / 搜索」。

## 数据链路

- 大纲/资产/任务/图谱/研究/搜索视图：组件挂载时经 inject 面拿到 `{ fetchStudioApi, postStudioApi }` → 同源打 `/studio-panel/api/...` → host 代理转发到 Studio。Studio 本身不发 CORS 头（`OpenWrite/tools/studio_http.py` 无任何 `Access-Control`），所以浏览器只能走这个代理，不能直连。
- 资产编辑契约（`structured_assets.py` create/update + `studio_application.py`）：更新 `POST /api/assets/update { kind, id, revision, data, body_markdown? }`——**乐观锁字段名是 `revision`**（详情的 `sha256:...` 指纹），过期即 409 `ASSET_CONFLICT`（`PROJECT_BUSY` 也归 409），编辑器据此显示冲突横幅 + 刷新重试（编辑器按 revision 作 React key 重挂，草稿诚实重建）。`data` 服务端按 `CHARACTER_FIELDS`/`WORLD_FIELDS` 白名单过滤合并；关系经 `data.related`（字符串或 `{target, kind, note}`）编辑——注意 relation_view 里 incoming/annotation 来源的关系是派生数据，**不能**回写，编辑器只编辑 front-matter 里的 `related` 原文。新建 `POST /api/assets { kind, id, data }`：id 必填且须匹配 `[A-Za-z0-9][A-Za-z0-9_.-]{0,79}`；progression 另需 `kind ∈ ability/rank/cultivation/career/reputation/curse/custom` 与非空 `stages: [{id, name}]`。
- 信封差异（已核对源码）：`GET /api/outline`、`GET /api/continuity`、`GET /api/workspace`、`GET /api/document`、`GET /api/search` **不带**信封，直接返回数据对象；`GET /api/assets`、`GET /api/assets/{kind}/{id}`、`GET /api/tasks`、`GET /api/research`、`GET /api/research/reports/{id}` **带**成功信封 `{ ok, data: { ... }, error, request_id }`。各视图按真实形状解析，字段缺失时容错为空态。
- 资产详情（`structured_assets.py` read + `world_query.py` get_asset_relation_view）：`data` 为 `{kind, id, name, data: <front-matter/YAML 字典>, body_markdown, path, revision}`；仅 character/world 附带 `relation_view: {confirmed, registered, suggested, incoming, counts}`，关系项为 `{target, name, kind, note, origin(canonical/annotation), direction, resolved}`。progression 详情无 relation_view。列表型白名单字段（character 的 `taboos`/`detail_refs`，world 的 `detail_refs`）在读视图归入「索引」区逐行渲染，在编辑器里是每行一条的 textarea，保存时按行拆回数组（对齐 Studio assets.js 的行连接语义）。
- **Markdown 渲染**：资产详情 `body_markdown`、作品核心正文、评审卡的 summary/quote/suggestion，以及资产卡片摘要、参考作品/作品核心标题，一律走平台种子模块 `@deepseek-ai/dsh-client-ui-primitives` 的 `MarkdownText`（GFM + KaTeX，禁 raw HTML），不再 pre-wrap 裸文本。短文本场景（卡片摘要/标题）套 `.mdInline` 把块元素内联化，保住两行 line-clamp 与紧凑卡片布局。该模块在 PLATFORM_MODULES 内，purity 门禁允许其作为 external。
- 图谱形状（`novel_service.py` continuity()）：`foreshadowing.nodes` 只含**待回收**节点（status 埋伏/待收，weight≥1），字段 `{id, content, weight(1-10), layer(主线/支线/彩蛋), status, created_at, target_arc/target_section/target_chapter, tags}`；**DAG 的边不在响应里**（存储模型有 edges，但 continuity 端点不暴露）——渲染器做了防御性消费（若未来端点加上 `foreshadowing.edges` 会画带箭头的连线），当前只画分层节点板。`foreshadowing_validation: {valid, errors}` 的错误数显示在工具栏。`relationship_graph` 含 `{nodes: [{id, label, kind(character/faction/place/concept/unknown), type, status, unresolved}], edges: [{id, source, target, label, confirmed, ...}], truncated}`（服务端上限 120 节点/240 边）。`truth` 是三份 markdown 文档（`{current_state, ledger, relationships}` 字符串，truth_manager.py TruthFiles），不是结构化实体行——账本段按文档渲染。`workflows[]` 为 `{chapter_id, current_stage, error, stages: [{name, status(pending/running/completed/failed/skipped), message}]}`。
- 研究形状（`studio_http.py` + `research_service.py`）：`GET /api/research` 带信封，`data` 为 `{available, setup_hint, settings, reports: [{id, title, status, episode_id, created_at, path, bytes, metrics}], model_route}`；报告全文 `GET /api/research/reports/{id}`（id 须匹配 `[A-Za-z0-9][A-Za-z0-9_-]{0,100}`）带信封，`data` 为 `{id, metadata, content}`。
- 搜索形状（`project_search.py` ProjectSearchIndex.search）：`GET /api/search?q=&scope=&limit=` **不带**信封，返回 `{query, scope, scope_label, results: [{path, title, line, heading, snippet, scope, scope_label, category, category_label, score, retrieval, excerpt}], indexed, engine(lightrag/literal-fallback/none), warning, warning_code, ...}`；scope 的 canonical 值（library_catalog.py CANONICAL_SEARCH_SCOPES）为 all/outline/core/characters/settings/continuity/chapters/sources（旧值 story/world/assets 有服务端别名映射）。limit 服务端夹在 1–50。
- **命名纠正**：Studio 左导航「资料库」= 结构化资产库（作品核心/角色/设定），即本 tab 主体；`operations.reference_library` 那组数据是**参考作品**（Studio 的 `data-view="deconstruct"` 参考库面），分段控件与 locale 均已正名（zh 参考作品 / en References）。参考库无独立 GET 路由：`/api/reference-library` 是 **POST-only** 动作分发器（Studio 自己的前端连 `status` 读取都走 POST）。只读列表经 `GET /api/workspace` → `operations.reference_library` 获得，条目为 `{record: {source_id, title, intent(reference/continuation/canon/migration), total_chars, updated_at}, structure: {status(awaiting_confirmation/confirmed)}, analysis: {status, complete}, assets}`。注意：每条的「采用状态」不在列表里（采用信息在项目级 `project_style_surface`），视图显示结构确认态与分析完成态代替。
- 作品核心**可 GET**：`GET /api/workspace` → `documents.core[]`（`{path, title, subtitle/category_label, category, ...}`，`library_catalog.py` describe_document 产物），正文经 `GET /api/document?path=<p>`（无信封，`{path, title, content, version, revision, ...}`）。
- 任务形状（`task_store.py` TaskStore.create + `studio_application.py` task_surface）：`data.tasks[]` 的 id 字段是 **`task_id`**（不是 `id`）；`status` ∈ pending/running/awaiting_confirmation/completed/failed/cancelled/interrupted；**没有数值型 progress 字段**——`phase`（queued/reading/preparing/model/validating/committing/complete）就是进度信号；失败时 `error` 是 `{ code, message, recoverable }` 对象。`data.counts` 给各状态计数，用于渲染过滤片。
- 评审卡：工具结果文本（`renderJson` 的 JSON）解析为 `{ result: { passed, score, issues: <数量 int>, summary, issue_details: [...] }, workspace }`。注意 `issues` 是**问题计数**而非数组（数组在 `issue_details`）；`score` 是 0-100 单一总分（由 severity 计数推导），**没有**按维度的分数表——维度只标注在每条问题上（`dimension: int|null`）。解析失败或字段缺失时回退为原始 JSON 展示。

## 配置

在 patch 层覆盖（后写的同 id 行覆盖先写的）：

```yaml
- insert:
    - id: studio-panel
      name: '@dsh-novel/studio-panel'
      config:
        studioUrl: 'http://127.0.0.1:4567'   # 改成你的 Studio 地址
```

配置链路：host 插件的 `Config` schema 解析出 `studioUrl` → 同源路由 `/studio-panel/config.json` → client 注册时注入的 `resolveStudioUrl()` 回调 → 组件挂载时拉取。路由不可用（如 headless profile）时回退到 bundle 内置的默认值 `http://127.0.0.1:4567`。代理路由复用同一个已解析值。

## 构建与冒烟

```sh
npm install
npm run build   # rm -rf lib && tsc -p tsconfig.json && tsdown
npm run smoke   # node scripts/smoke.mjs（无服务器：路由注册/转发语义 + bundle 交接断言）
```

- `tsc` 只产类型声明到 `lib/types/`（`.d.ts`）；
- `tsdown`（`tsdown.config.ts`，DSH 共享 client preset 的园外复刻）产 `lib/index.js`（node 半边）与 `lib/client.js` + sourcemap（浏览器半边，`window.__ModuleLoader__.load` 闭包工厂格式）；
- `smoke` 断言：host `apply` 注册 config + proxy 两条路由；代理的路径/查询串转发、状态与错误体透传、405/404/502 语义；client bundle 只 `require("react")` 与 `require("react/jsx-runtime")`（平台种子模块），且完成 `__ModuleLoader__` 交接并导出 `apply`/`inject`。

注意：所有 `@deepseek-ai/dsh-*` 依赖通过 package.json 的 `overrides` 钉在 `0.1.0-rc.7`（与已安装的 `@deepseek-ai/dsh@0.1.0-rc.7` 对齐）。上游包的 `^0.1.0-rc.7` peer 范围会把 rc.8 拉进来造成 ERESOLVE 冲突，因此必须全量钉版；升级 dsh 时同步整表。

## 设计决定与限制

- **iframe 不加 `sandbox`**：Studio 是受信任的本地第一方应用，需要自身源下的 localStorage/cookie、表单提交、导出下载和可能的 window.open；即使 `allow-scripts allow-same-origin` 也会破坏下载/弹窗，沙箱化本地开发工具没有收益。保留了 `allow="clipboard-read; clipboard-write"`。
- **代理二进制安全透传**：上游响应按 arrayBuffer 原样转发（epub 是 zip），content-type/content-disposition 原样携带；代理超时放宽到 60s（epub 构建与导入是重操作）。
- **不做 Studio 健康预检**：跨源 fetch 必失败（无 CORS）。iframe 视图用 `load`/`error` 事件驱动加载态与错误兜底；跨源加载失败在部分浏览器仍触发 `load`，所以错误面板是尽力而为，始终提供「重试」与「在新标签页打开」出口。数据视图的失败则能被代理的 502 准确捕获。
- **任务/图谱/研究/搜索/评审卡均为只读**：变更走 agent 工具（novel_revision_*、novel_task_* 等），UI 不另开写通道（搜索 tab 只发 GET）。任务视图特意不提供取消/重试按钮。**可写域两处**：资产 tab（角色/设定/进阶体系，走 assets 白名单路径）与大纲 tab（rename/update_summary/add_child/add_after/delete 五个原子操作，走 outline/edit；内容级批量改写仍建议走 agent 的 novel_outline_edit 分批流）。
- **无 invariant companion**：DSH 仓库内的 `./invariant` 伴侣是其仓库内部约束（有专门的脚本门禁），loader 并不要求；本仓库已有插件（openwrite-bridge）同样不带。
- 文案走 locale 命名空间 `studio-panel`（zh/en 双语），视图标签用 `label: () => t(...)` thunk，跟随活动语言。
