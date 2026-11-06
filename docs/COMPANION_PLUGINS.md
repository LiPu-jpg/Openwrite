# 联动插件（Companion Plugins）

OpenWrite 不依赖任何联动插件：写作/审稿链路、工作台在单独安装时全部可用。
本节说明三个**可选**联动插件装上之后会发生什么、装上之前的差别，以及判定规则。

## 判定规则（重要）

联动是否生效由两部分决定，任一部份不满足都保持 OpenWrite 自己的实现：

1. **已安装**：插件出现在某个 profile 的 `dsh.profile.bundles` 里，并且其包目录真的存在于
   `<DSH_HOME>/profiles/<profile>/node_modules/`。
2. **宿主放行**：该插件自己声明的 `peerDependencies["@deepseek-ai/dsh"]` 范围覆盖当前宿主版本。
   宿主安装时用的就是这个范围，所以“声明不含当前宿主”的插件即使装了也不会被宿主加载，
   OpenWrite 不会去替它加载。

判定结果写入 `<DSH_HOME>/openwrite/companions.json`（按 profile manifest 的 mtime 做指纹缓存），
只在 profile 变动或宿主版本变化时重新推导。任何读取失败都** fail-closed**：
保持内嵌实现，不影响启动与写作。

诊断可用 `npm run doctor`（末尾的 `companion plugins` 一行）或工作台启动器里的「联动插件」区；
需要显式指定宿主版本时可用环境变量 `OPENWRITE_HOST_VERSION`（诊断与测试用）。

宿主版本解析顺序：`OPENWRITE_HOST_VERSION` → profile 内安装的 `@deepseek-ai/dsh` →
本插件已解析到的 `@deepseek-ai/dsh-*` 子包（与宿主同版本发布）→ 当前进程入口。
解析不到时按未知处理，所有联动保持关闭。

## dsh-dog（DoG 独立验收）

- OpenWrite 从 0.2.29 起不再内置 DoG 引擎、调试器或 `dog_*` 工具，也不会自动运行第三方 verifier；
  OpenWrite 自己的六域评审与交付闭环照常工作。
- 安装 `@dsh-external/dsh-dog` 且当前宿主放行时：它的 `dog_*` 工具在宿主层可见（OpenWrite 预设
  的 Agent 也能调用），工作台「联动插件」区显示安装/放行状态。预设新增非斜杠技能
  `dog-delivery-verification`：把当前章或整书的正文、最新评审与交付 preflight 证据写成
  工作区内的不可变 handoff 包和 DoG 0.9 图，再由 Agent 调 `dog_validate`/`dog_create`/`dog_run`
  做一次独立判断。技能要求先说明会产生模型调用并得到作者同意，且不直接改正文。
- **未安装**：写作、审稿、交付完全不受影响；Agent 不会声称跑过 DoG，回到 OpenWrite 门禁。
- OpenWrite 只提供 handoff 与流程，不替 dsh-dog 运行 verifier，也不把它的运行结果写进
  OpenWrite 的 `data/dog/**` 交付产物；两者是不同引擎，不能互相冒充。图形化调试器仍由
  dsh-dog 自己的面板提供，OpenWrite 不另建入口。

## dsh-ops（token 效率工具）

- 仓库：<https://github.com/T-Auto/dsh-ops>（npm 包名 `dsh-ops`，MIT）。
- 提供有界的 Native 文件工具、渐进式工具发现（`ops_discover_tools`）与诊断（`ops_status`）。
- **未安装**：预设工具面与现在完全相同。
- **已安装且宿主放行**：预设追加一行 `openwrite-ops`，调用上游
  `integration({ preset: 'openwrite', files: true, discovery: true, presentation: 'native',
  replaceOfficial: false, shell: false })`。也就是：只挂文件类常驻工具 + 渐进发现，
  **不替换官方文件工具、不发布 `ops_bash`、不改提示词策略**。卸载该插件即恢复原状。
- 工作台「联动插件」区会把同一组选项交给上游 `resolveIntegrationConfig`，显示实际解析出的
  文件工具/渐进发现/呈现方式/是否替换官方工具/shell 开关与常驻工具数；上游没有该导出时
  退回一句概述，不把“探测到”说成“已按某个具体配置挂载”。
- 上游声明的宿主范围是 `>=0.2.0-rc.2 <0.2.2-0`，因此 0.1.x 宿主上不会挂载（上游 peer 也不允许）。
- 安装：`dsh plugin --profile web add dsh-ops`（或按该仓库说明使用其安装入口）。

> 上游文档中的 `preset` id 必须精确匹配 OpenWrite 的稳定预设 id `openwrite`；本插件传入的就是这个值。
> 挂载前还会真的 import 一次 `dsh-ops/integration` 并用上面这组选项构建集成：npm 上的 `0.4.4`
> 还没有这个导出（`0.5.0-alpha` 起才提供），探测会报「does not expose dsh-ops/integration」并不挂载，
> 避免一次导入失败把整个预设组合拖垮。

**宿主怎么判定兼容性（重要，曾判错）**：宿主读插件的 `engines.dsh`（没有则退回
`peerDependencies` 里的 `@deepseek-ai/dsh` 与 `@deepseek-ai/dsh-*`），用
`semver.satisfies(version, range, { includePrerelease: true })` 匹配。这个 `includePrerelease`
放宽了 npm 的规则，因此 `0.2.1-rc.5` **满足** `>=0.2.0-rc.2 <0.2.2-0`。

`companions.mjs` 曾按 npm 安装期的严格规则实现，于是比宿主更保守：在 `0.2.1-rc.5` 上把
`dsh-ops` 与 `dsh-our-free-model` 报成「已安装但宿主不放行」，而宿主实际两个都加载了
（读 `window.__DSH_BOOT__.entries` 实测确认）。已改为与宿主同一语义，并用一条测试把
`satisfiesRange` 与 semver 的 `includePrerelease` 结果逐组合钉住。

因此 `dsh-ops` 的宿主范围 `>=0.2.0-rc.2 <0.2.2-0` 覆盖全部 `0.2.x` 宿主，0.1.x 上不挂载
（上游 peer 也不允许）。上游若放宽或收紧声明，无需改代码，探测自动跟随。

> 上游文档中的 `preset` id 必须精确匹配 OpenWrite 的稳定预设 id `openwrite`；本插件传入的就是这个值。
> 挂载前还会真的 import 一次 `dsh-ops/integration` 并用上面这组选项构建集成：npm 上的 `0.4.4`
> 还没有这个导出（`0.5.0-alpha` 起才提供），探测会报「does not expose dsh-ops/integration」并不挂载，
> 避免一次导入失败把整个预设组合拖垮。

## dsh-our-free-model（免密钥模型车道）

- 仓库：<https://github.com/Ebony-Vinyl/dsh-our-free-model>（npm 包名
  `@ebony-vinyl/dsh-our-free-model`，MIT；请勿安装 npm 上同名裸包）。
- 装上后宿主模型选择器会出现免费车道，无需登录/Key。
- **未安装**：OpenWrite 只在工作台「联动插件」区给出一句安装提示。
- **已安装**：同样只在「联动插件」区显示状态（版本、是否被当前宿主放行）。
- 该插件 2.7.4 声明的宿主范围是 `^0.1.2-rc.1 || ^0.1.7-rc.2 || ^0.2.0-rc.1`，
  因此 `0.2.1-rc.*` 宿主上它自己也不会被宿主加载，联动区会如实显示「已安装但当前宿主不兼容」。
- **注意**：OpenWrite 的写作/审稿调用走 OpenWrite Core（Studio 后端）自己的模型配置，
  不经过宿主 llm 服务。因此装上它**不会自动**成为 OpenWrite 的模型。
- 「联动插件」区在检测到本地转发已开启时提供一个「写入 OpenWrite 模型配置」按钮：
  它读取该插件的 `/api/our-free-model/clients`（同一 origin），把 `base_url`/`api_key`/模型名
  写成一条 id 为 `our-free-model` 的 OpenWrite 模型 profile。写入走 Studio 的
  `POST /studio-panel/api/model/profiles`，与「任务 → 模型」页面同一条路由，由 Core 校验。
  已存在同 id profile 时会先要求确认，并**保留作者调过的参数**（温度、上下文窗口、超时等），
  只更新网关地址、模型与密钥；`remember_api_key` 沿用作者原来的选择，不默认代为持久化密钥。
  该路由由第三方插件提供，其鉴权行为不在本插件控制范围内（见下「安全假设」）。
  未开启本地转发时，按钮不出现，只提示去该插件的设置页打开。
  接入动作现在会同时处理**任务路由**：读取全局模型库的 `routes`，显示“当前全局路由”，
  默认勾选“同时把写作/评审切到该模型”。确认后先写 profile，再把 `chapter_write` 与 `review`
  两个键切到 `our-free-model`；规划、检索、研究等其余路由原样保留。已存在 profile 或路由
  将变化时都会二次确认；若 profile 写入成功而路由写入失败，提示会明确说“配置已写入、路由
  切换失败”，不会把部分成功报成整体成功。
  这里写的是**全局**路由；若当前作品在 `novel_config.yaml` 里单独设置了 `model_routes`，
  作品设置优先，按钮不会覆盖它。网关地址若自带 `/v1`，写入前会规范化，避免 `/v1/v1`。

## 工作台里的「联动插件」区

「设置 → OpenWrite → 宿主」页的「联动插件」区展示三行状态：dsh-dog、dsh-ops、dsh-our-free-model（启动器底部入口复用同一份状态），
各自说明“已接入 / 已安装但宿主不兼容（原因）/ 未安装（装上会怎样）”。
状态数据来自 `/studio-panel/companions`（由本插件在宿主进程内探测，与其它
`/studio-panel/*` 路由一样受宿主浏览器鉴权保护）；ops 行还会带上解析后的挂载计划。

该区域**不是**纯只读：免费模型的「写入 OpenWrite 模型配置」按钮会写一条模型 profile，
并可同时把全局写作/评审路由切到它（语义见上一节）。除此之外它不修改任何配置。

## 安全假设（需定期复核）

- `/studio-panel/companions` 的响应含宿主版本与联动插件清单，已按其它 `/studio-panel/*`
  路由加同一道浏览器鉴权；无鉴权的本地请求会拿到 401/503 而不是数据。
- `/api/our-free-model/clients` 由第三方插件提供，本插件假设它与 Studio 路由一样受宿主
  浏览器鉴权保护。该假设未被本插件验证，升级该插件后应重新确认；响应里的密钥只用于写入
  模型 profile，不进入日志、诊断或错误信息。

## 维护约定

- 联动判定逻辑集中在根目录 `companions.mjs`（无第三方依赖，自带所需 semver 子集），
  单测在 `scripts/companions.test.mjs`；ops 适配在 `presets/openwrite/ops-integration.mjs`；
  DoG 交付验收流程在 `presets/openwrite/skills/dog-delivery-verification/SKILL.md`。
- 三个联动插件都保持“可选、fail-closed”：探测/导入失败只影响对应联动，不影响写作与启动。
- 任何联动插件都不要变成硬依赖：探测失败、范围不匹配、包缺失都必须回到 OpenWrite 自己的实现。

## 真实宿主验证记录（2026-10-31，macOS arm64 / Node v24.15，0 次模型调用）

| 场景 | 宿主 | 结果 |
| --- | --- | --- |
| 无联动插件（DoG 已移除） | `0.2.1-rc.3` / `0.2.1-rc.5` | 客户端验收全项通过；预设选择器只有 1 条 OpenWrite；工具面不再含 `dog_*` |
| dsh-ops `0.5.0-alpha3`（有 `./integration`） | `0.2.0-rc.2` | 探测为可用；客户端验收通过 |
| dsh-ops `0.4.4`（无 `./integration`） | `0.2.0-rc.2` | 探测报「does not expose dsh-ops/integration」并不挂载；预设组合不受影响，验收通过 |
| dsh-our-free-model `2.7.4` | `0.2.0-rc.2`（安装） | 安装后该插件自身的客户端引导未在本环境完成（其启动期网关探测），宿主本身无激活错误；OpenWrite 侧仅探测与展示，未参与该路径 |

未覆盖：三系统 CI、Windows/Ubuntu 实机、真实手机、真实付费模型、以及「ops 工具出现在真实 Agent 工具目录」
（本验收环境不发起 Agent 轮次，预设组合不会挂载；该链路由单测证明行已按精确 preset id 插入）。
