# DeepSeek Harness 小说插件：建立、验证与维护

核查日期：2026-09-05。本轮针对插件工程维护；原评审 v2、横评和研究工作台的后续功能仍见 [GOAL.md](../GOAL.md)。

## 1. 版本基线与资料来源

本项目当前支持 **DSH 0.1.0-rc.7 / Cordis 4.0.1 / Node ≥22.19.0**。
三个 package manifest 固定直接 DSH 依赖及 peers，并用 `overrides` 固定传递依赖；
三个 `package-lock.json` 一起维护。安装与 profile smoke 使用 pnpm 9.15.9 验证。
初查时根 CLI 是 rc.7，但 185 个 DSH 传递包是 rc.8；
bridge 也有 15 个 rc.8 包，只有 panel 已统一。只看 `dsh --version` 不足以证明兼容。

研究时官方 npm CLI `latest`/`next` 为 **0.1.2-rc.1**，官方 master 为 **0.1.3-alpha.1**
（核查 commit `d347e703908d0406b7a7ef80e3a0e594d86b2215`）。这两个版本未纳入本项目的兼容承诺。
上游处于 developer preview，各包的发布标签并不齐步，升级必须按目标版本的实际依赖图核实。
来源：[官方仓库](https://github.com/deepseek-ai/deepseek-harness)、
[CLI npm 元数据](https://registry.npmjs.org/@deepseek-ai%2Fdsh/latest)。

核心资料：

| 维护问题 | 官方一手资料 | 本项目对应位置 |
|---|---|---|
| Bundle 与安装顺序 | [打包/安装教程](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md) | 两包的 `package.json`、`cordis.patch.yml` |
| 命令行与更新 | [CLI 参考](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md) | `scripts/install.sh` |
| 服务和资源撤销 | [Cordis 生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cordis-tutorial/02-lifecycle-and-effects.md) | bridge `src/domain.ts` |
| 配置 schema | [配置教程](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/config.md) | bridge `src/index.ts` |
| Agent 预设 | [预设契约](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-presets/README.md) | `presets/openwrite/` |
| Web 构建与扩展槽 | [客户端模块](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/modules/README.md)、[Slots](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-slots/README.md) | panel `tsdown.config.ts`、`src/client/index.ts` |

master 链接用于追踪演进；rc.7 的具体行为还需对照已安装包源码。本轮直接核实了
`@deepseek-ai/dsh/lib/plugin-*.js`：官方 CLI 在 pnpm 成功后按实际依赖重新登记 bundles。

## 2. 如何建立一个可维护的小说扩展

本仓库保留三个边界：OpenWrite 实现领域行为；bridge 注册工具并代理 HTTP；panel 展示数据。
添加能力时先定义后端响应和错误码，再补 bridge 工具/写白名单/失效资源，最后接 UI 和预设。
已有 90 个 `novel_*` 工具。正文、阅读顺序、场景、评审、任务和导出始终按 session Workspace root 隔离；
缺少身份时必须报错。具体协议见 [Workspace 契约](WORKSPACE_CONTEXT_CONTRACT.md)。

一个 DSH Bundle 至少需要以下结构：

```text
package.json        # main/types/exports/files + dsh.bundle.patch
cordis.patch.yml    # 以包名插入带稳定 id 的插件行
src/index.ts        # 导出 name、apply，以及必要的 inject/Config
lib/                # 构建后的入口与声明
```

本项目的 `dsh.bundle.patch` 指向 `./cordis.patch.yml`。包必须携带补丁、JS、声明及静态资源；
开发目录能运行不代表打包后完整。`npm run doctor` 用真实 `npm pack --dry-run` 清单验证这些文件。
两个包目前均为 `private: true`，本轮交付方式仍是本地安装。

工具通过 `ctx.tools.register` 注册。外部 SSE、HTTP 响应、计时器等必须属于创建它们的
Cordis scope，使用 `ctx.effect` 提供撤销操作；异步工作结束前检查 scope 是否仍存活。
目前 bridge 的 SSE 和正在读取 epoch 的快照会在卸载/替换 webServer 时关闭与取消。
测试必须覆盖重复挂载和请求未完成时卸载，不能只测首次加载。

Web 包另外声明 `dsh.client.platform: web`、`exports["./client"]`，通过
`window.__ModuleLoader__.load` 加载浏览器 bundle。沿用本仓库平台模块白名单与 purity gate；
跨插件服务用依赖注入协作。上游 0.1.2-rc.1 的额外共享模块已有 `dsh.client.external`
声明要求，迁移时需重新检查旧 `dsh-client-runtime/client` 的处理。

预设是独立的完整 agent composition。只在 host 装一次 bridge；不要在 agent 预设重复注册领域服务。
技能随 `presets/openwrite/skills` 安装，统一使用“六域累加评审，保留 37 项展开查询”。
预设副本不会自动跟随源码变化；修改后重新安装并重启 profile，再用新会话验证。

### Operation trace 与隐私边界

每次 dsh 领域写调用携带 session、根调用、工具调用和工具名；OpenWrite 将它与 request、
上下文 packet revision/来源/预算、模型调用用量以及领域 mutation summary 关联。用
`novel_trace_list` 查看最近记录，回合变更卡也会显示 trace 文件入口。

Trace 文件位于作品的 `data/traces/`，最多保留 100 条且最长 30 天。它只保存哈希、长度、
revision、来源路径、预算、模型/提供方、finish reason、usage 和脱敏后的领域实体字段。
作者提示、上下文正文、模型输出、chain-of-thought、API key/credential/token，以及 mutation
before/after 原值均不落盘。凭据字段连哈希也不保存，避免形成可枚举指纹。修改 trace 契约时，
必须保留这些否定断言测试，并核对 `openwrite.operation-trace.v1` 的 retention/privacy 字段。

## 3. 安装、更新与本地启动

```sh
# 前置：Node >=22.19、npm、pnpm、rsync；启动后端另需 uv 和 OpenWrite 源码
bash scripts/install.sh
npm run doctor -- --profiles

# 源码默认位于相邻 ../OpenWrite；QA 小说固定使用 ~/my_novel
OPENWRITE_DIR=/path/to/OpenWrite bash scripts/dev.sh --project "$HOME/my_novel"
```

安装器先对三个锁文件执行 `npm ci` 并构建，再复制预设和挂载插件。
web/headless 初始化均用 `--dump-config`，不调用模型；任一步失败会返回非零状态。
挂载使用官方 `dsh plugin --profile … add -w <绝对路径>`，每次执行都能修复
“依赖已有但 bundle 未登记/本地链接失效”的状态。`-w` 适配 rc.7 的 pnpm workspace 转发。
重复运行会同步本项目生成的 OpenWrite 预设；Goethe/Dante 迁移备份写入唯一目录
`$DSH_HOME/.agent-presets-legacy/<name>.XXXXXXXX/preset`，保留之前的备份。

自定义 `DSH_HOME` 时，安装、doctor、启动三步必须使用相同值。
DoG 默认从 `Fun10165/dsh-dog` 的固定 `v1.2.0` 标签自动安装到
`$DSH_HOME/extensions/dsh-dog`；已有目录会复用。`DSH_DOG_DIR` 可指向开发工作树，
`DSH_DOG_AUTO_INSTALL=0` 可明确跳过。已有 `dog:` 设置保留原值；v1.2 会以调用会话的
Workspace 为捕获根，静态 `workspaceRoot` 只是缺少会话上下文时的兜底。
安装不会重启已有 dsh 进程，更新后需要退出原进程再启动。

开发 supervisor 只管理自己创建的 Studio/dsh 进程组：端口占用拒绝启动，
Studio 健康检查限时 30 秒，任一子进程退出或收到 Ctrl-C/SIGTERM 时清理两端及其后代。
不要把 `dev.sh` 与后台常驻 daemon 同时绑定到同一端口。
若自定义 `STUDIO_PORT`，还需在 dsh 的 bridge 配置中把 `baseUrl` 指向该端口。
覆盖配置时注意后层替换整个行的 `config`，保留所需 timeout/outputDir 设置。

## 4. 验证分层

```sh
# 已安装依赖后，本仓库自包含验证：不需要密钥、小说或启动真实服务
npm run check:plugin

# 加上相邻 OpenWrite 的共享 schema/fixture 验证
OPENWRITE_ROOT=/path/to/OpenWrite npm run check

# 仅查版本/打包完整性；加 --profiles 才读取本机两个 profile 的包登记
npm run doctor

# 需要已有 .venv：Python/TS DoG 产物一致性
npm run test:dog
```

`check:plugin` 包含构建、版本/打包 doctor、安装/退出/热重载回归、预设模块及技能解析、
两个插件 smoke、epoch 测试与 React 组件测试。`test:maintenance` 可单独重跑工程维护测试，
但要先构建 bridge。`test:profiles` 还用真实 rc.7 CLI 和 pnpm `--offline` 在临时目录
安装本地链接、验证 web/headless 组合及漏登记修复；不会启动 Agent 或修改本机 profile。
GitHub Actions `plugin-check.yml` 在 Ubuntu/Node 24 上执行这一自包含门禁；
依赖安装需要网络，测试不调用在线模型。工作流是否通过以实际 CI run 为准。

运行中系统的验收另行执行：

```sh
bash scripts/verify.sh
npm run test:e2e
```

这两项不是离线门禁。`verify.sh` 可能将 `~/my_novel` 登记到 dsh Workspace；
E2E 依赖服务与浏览器，跳过不算通过。前端 smoke 也不能替代真实浏览器布局验收。
不应为让门禁通过而删测试、降质量阈值或把 provider 错误记成低质量分。

## 5. 升级与回退流程

1. 记录当前三个 manifest/lockfiles、profile 自定义 patch、预设自定义内容及现有测试结果。
   保留可恢复副本，不覆写未提交工作。
2. 查看目标版本的实际 npm 包和官方发布记录，逐项比较工具 API、Workspace/session、
   Cordis、客户端模块表、Slot props 与 preset composition；不要批量使用 `@latest`。
3. 在隔离 checkout 修改直接依赖、peers 与 overrides，生成并审查三个锁文件。
   `doctor` 会拒绝混版、宽松直接版本和缺失 override；新增传递包也要纳入检查。
4. 用 `npm ci` 重建，先过 `check:plugin`、跨仓库 contracts，再进行真实 profile 和
   `~/my_novel` 的只读浏览器验收。打包分发时从构建产物生成 tarball，再从包中验证入口。
5. 确认后重新安装并重启。失败时恢复旧版源码与对应锁文件、重新 `npm ci`/build/安装、
   恢复必要的预设副本并重启；不要删除小说或复用新版本的不兼容状态来掩盖失败。

本轮未升级到 0.1.2，也未修改本机 profile 或发布插件。下一次升级须补该版本的运行时证据。
