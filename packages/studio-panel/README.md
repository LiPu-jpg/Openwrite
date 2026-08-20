# @dsh-novel/studio-panel

dsh web 的 client 插件，把 OpenWrite Studio 的关键界面原生融入会话 UI：

- **稿件**（id `studio`，order 20）：全高度 iframe 内嵌本地 OpenWrite Studio（默认 `http://127.0.0.1:4567`）。
- **大纲**（id `outline`，order 21）：原生渲染大纲树 —— 卷/篇/节/章层级、kind 徽章、标题、摘要、成稿状态，可折叠，只读。
- **资产**（id `assets`，order 22）：角色/世界/成长体系分组卡片看板（名称、类型徽章、摘要、标签、阶段数），只读。
- **novel_review_chapter 评审卡**：`tool.call.toolview` 键控渲染器，把 37 维章节评审 JSON 渲染成报告卡（总分/结论横幅 + 按类别分组的问题列表 + 引用与修改建议），形状异常时回退到美化 JSON。

## 它是怎么被加载的

本包是一个带浏览器半边的 cordis 插件，由两部分组成：

- **Host 半边**（`src/index.ts` → `lib/index.js`）：一个最小 cordis 插件，声明 `Config` schema（Schemastery，`studioUrl` 默认 `http://127.0.0.1:4567`），并在 dsh web server 上注册两条同源路由：
  - `GET /studio-panel/config.json`：把解析后的配置发给浏览器；
  - `GET /studio-panel/api/<path...>?query`（prefix 路由）：**只读代理**，原样转发到 `${studioUrl}/api/<path...>?query`，透传上游状态码、content-type 与响应体（含错误体）；非 GET 一律 405，Studio 不可达时 502 JSON。写操作不走这里——变更全部留在 agent 工具（`@dsh-novel/openwrite-bridge`）。
  `webServer` 通过 `ctx.inject` 可选等待，因此在无 web server 的 profile（如 headless）里也能正常加载，只是不注册路由。
- **Client 半边**（`src/client/` → `lib/client.js`）：package.json 里的 `dsh.client` 块（`platform: "web"`）+ `exports["./client"]` 指向构建产物。dsh web 的 client 模块表（`ctx.clientModules`）扫描 host Loader 条目时发现该声明，把 bundle 挂到 `/plugins/@dsh-novel/studio-panel/client.js` 并注入启动图；浏览器半边用 `ctx.slots.inject('conversation.view', function* () { ... })` 等待 ui-conversation 声明槽位后逐个 yield 三个视图注册，并用 `ctx.slots.inject('tool.call.toolview', ...)` 注册评审卡（与 ui-trajectory / bash-sample 同一模式）。

安装走 profile bundle 路径（与 `@dsh-novel/openwrite-bridge` 相同）：`scripts/install.sh` 把本包 `pnpm add -w` 进 `~/.dsh/profiles/web/` 并追加到 `dsh.profile.bundles`；`cordis.patch.yml` 通过 `--patch` 叠加层或 profile 的 `dsh.bundle.patch` 把插件挂进 cordis 配置树。加载后，打开任意会话即可在头部标签栏看到「聊天 / 轨迹 / 稿件 / 大纲 / 资产」。

## 数据链路

- 大纲/资产视图：组件挂载时经 inject 面拿到 `fetchStudioApi(path)` → 同源打 `/studio-panel/api/...` → host 代理转发到 Studio。Studio 本身不发 CORS 头（`OpenWrite/tools/studio_http.py` 无任何 `Access-Control`），所以浏览器只能走这个代理，不能直连。
- 信封差异（已核对源码）：`GET /api/outline` **不带**信封，直接返回 `{ roots, counts, drafted_chapters, ... }`；`GET /api/assets` **带**成功信封 `{ ok, data: { assets: [...] }, error, request_id }`。两个视图各自按真实形状解析，字段缺失时容错为空态。
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
- **不做 Studio 健康预检**：跨源 fetch 必失败（无 CORS）。iframe 视图用 `load`/`error` 事件驱动加载态与错误兜底；跨源加载失败在部分浏览器仍触发 `load`，所以错误面板是尽力而为，始终提供「重试」与「在新标签页打开」出口。数据视图的失败则能被代理的 502 准确捕获。
- **大纲/资产/评审卡均为只读**：变更走 agent 工具（novel_outline_*、novel_asset_*、novel_revision_* 等），UI 不另开写通道。
- **无 invariant companion**：DSH 仓库内的 `./invariant` 伴侣是其仓库内部约束（有专门的脚本门禁），loader 并不要求；本仓库已有插件（openwrite-bridge）同样不带。
- 文案走 locale 命名空间 `studio-panel`（zh/en 双语），视图标签用 `label: () => t(...)` thunk，跟随活动语言。
