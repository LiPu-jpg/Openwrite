# @dsh-novel/studio-panel

dsh web 的 client 插件：在会话头部视图标签栏增加一个「稿件」标签页，内容是一个全高度 iframe，内嵌本地 OpenWrite Studio（默认 `http://127.0.0.1:4567`）。

## 它是怎么被加载的

本包是一个带浏览器半边的 cordis 插件，由两部分组成：

- **Host 半边**（`src/index.ts` → `lib/index.js`）：一个最小 cordis 插件，声明 `Config` schema（Schemastery，`studioUrl` 默认 `http://127.0.0.1:4567`），并在 dsh web server 上注册同源路由 `GET /studio-panel/config.json` 把解析后的配置发给浏览器。`webServer` 通过 `ctx.inject` 可选等待，因此在无 web server 的 profile（如 headless）里也能正常加载，只是不注册路由。
- **Client 半边**（`src/client/` → `lib/client.js`）：package.json 里的 `dsh.client` 块（`platform: "web"`）+ `exports["./client"]` 指向构建产物。dsh web 的 client 模块表（`ctx.clientModules`）扫描 host Loader 条目时发现该声明，把 bundle 挂到 `/plugins/@dsh-novel/studio-panel/client.js` 并注入启动图；浏览器半边用 `ctx.slots.inject('conversation.view', ...)` 等待 ui-conversation 声明槽位后注册视图标签（与 ui-trajectory 同一模式）。

安装走 profile bundle 路径（与 `@dsh-novel/openwrite-bridge` 相同）：`scripts/install.sh` 把本包 `pnpm add -w` 进 `~/.dsh/profiles/web/` 并追加到 `dsh.profile.bundles`；`cordis.patch.yml` 通过 `--patch` 叠加层或 profile 的 `dsh.bundle.patch` 把插件挂进 cordis 配置树。加载后，打开任意会话即可在头部标签栏看到「聊天 / 轨迹 / 稿件」中的**稿件**页。

## 配置

在 patch 层覆盖（后写的同 id 行覆盖先写的）：

```yaml
- insert:
    - id: studio-panel
      name: '@dsh-novel/studio-panel'
      config:
        studioUrl: 'http://127.0.0.1:4567'   # 改成你的 Studio 地址
```

配置链路：host 插件的 `Config` schema 解析出 `studioUrl` → 同源路由 `/studio-panel/config.json` → client 注册时注入的 `resolveStudioUrl()` 回调 → 组件挂载时拉取。路由不可用（如 headless profile）时回退到 bundle 内置的默认值 `http://127.0.0.1:4567`。

## 构建

```sh
npm install
npm run build   # rm -rf lib && tsc -p tsconfig.json && tsdown
```

- `tsc` 只产类型声明到 `lib/types/`（`.d.ts`）；
- `tsdown`（`tsdown.config.ts`，DSH 共享 client preset 的园外复刻）产 `lib/index.js`（node 半边）与 `lib/client.js` + sourcemap（浏览器半边，`window.__ModuleLoader__.load` 闭包工厂格式）。

注意：所有 `@deepseek-ai/dsh-*` 依赖通过 package.json 的 `overrides` 钉在 `0.1.0-rc.7`（与已安装的 `@deepseek-ai/dsh@0.1.0-rc.7` 对齐）。上游包的 `^0.1.0-rc.7` peer 范围会把 rc.8 拉进来造成 ERESOLVE 冲突，因此必须全量钉版；升级 dsh 时同步整表。

## 设计决定与限制

- **iframe 不加 `sandbox`**：Studio 是受信任的本地第一方应用，需要自身源下的 localStorage/cookie、表单提交、导出下载和可能的 window.open；即使 `allow-scripts allow-same-origin` 也会破坏下载/弹窗，沙箱化本地开发工具没有收益。保留了 `allow="clipboard-read; clipboard-write"`。
- **不做 Studio 健康预检**：`OpenWrite/tools/studio_http.py` 不发送任何 CORS 头，从 dsh 页面源跨源 fetch `/api/health` 必然失败。面板直接渲染 iframe，用 `load`/`error` 事件驱动加载态与错误兜底；跨源加载失败在部分浏览器仍触发 `load`，所以错误面板是尽力而为，始终提供「重试」与「在新标签页打开」出口。
- **无 invariant companion**：DSH 仓库内的 `./invariant` 伴侣是其仓库内部约束（有专门的脚本门禁），loader 并不要求；本仓库已有插件（openwrite-bridge）同样不带。
- 视图标签文案走 locale 命名空间 `studio-panel`（zh「稿件」/ en「Manuscript」），注册时用 `label: () => t('view.studio')` thunk，跟随活动语言。
