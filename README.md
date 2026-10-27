<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
    <img src="assets/logo-light.svg" width="312" alt="OpenWrite">
  </picture>
</p>

<h1 align="center">dsh-Openwrite</h1>
<p align="center">在 DeepSeek Harness 中规划、写作、审稿和管理长篇小说。</p>

<p align="center">
  <a href="package.json"><img src="https://img.shields.io/badge/dsh-0.2.1--rc.3-2563eb" alt="dsh 0.2.1-rc.3"></a>
  <a href="package.json"><img src="https://img.shields.io/badge/Node-%E2%89%A522.19-15803d" alt="Node >= 22.19"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache-2.0"></a>
  <a href="https://dsh-plugin.org/plugins/lipu-jpg/openwrite"><img src="https://dsh-plugin.org/badges/listed.svg" alt="Listed on dsh-plugin.org"></a>
</p>

<p align="center">
  <a href="#快速安装">快速安装</a> ·
  <a href="#开始使用">开始使用</a> ·
  <a href="#功能">功能</a> ·
  <a href="#文档与开发">文档</a> ·
  <a href="https://github.com/LiPu-jpg/Openwrite/issues">反馈问题</a>
</p>

这是 [OpenWrite](https://github.com/LiPu-jpg/Openwrite/tree/native-core) 的 dsh 插件版本。
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 提供 Agent 与交互界面，OpenWrite Core 提供小说领域能力；人物、设定、大纲、正文和评审保存在本地作品目录。

## 开发中：0.2.28（未发布）

Core 5.8.20 候选继续修复正文最后输入漏存、审稿修订越过选区，以及真实 Markdown 编辑器格式转换导致的选区拒绝，见 [正文编辑与审稿补修](docs/EDITOR_SAFETY_REPAIRS.md)。前轮修复见 [选区与升级补修](docs/SELECTION_UPGRADE_REPAIRS.md)。宿主正式发布与 Android/Termux 真机两项继续跟踪，本轮不发布；下面的 npm/GitHub 安装入口仍为已发布的 0.2.27。

## 0.2.27

工作台新增 OpenCode Go Console 认证，捆绑 Core 5.8.16，自动读取本机官方 CLI 的有效凭据和工作区信息；不必手工复制会过期的 Console 令牌。评审首次调用遵守模型输出预算，补充旧会话永久别名和跨平台回归。真实工作台连接测试、流式写作及 Go 安全评审已通过。见 [OpenCode Go 接入](docs/OPENCODE_GO.md) 和 [旧报告复核与待办](docs/CLOSED_ISSUE_FOLLOWUPS.md)。正式发行状态、各平台验收和安装包校验值见 [发布验收](docs/RELEASE_ACCEPTANCE.md)。

[GitHub 0.2.27](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.27) 与 [npm 0.2.27](https://www.npmjs.com/package/dsh-openwrite/v/0.2.27) 均已发布，`@latest` 已更新到 0.2.27。两处公开下载包均与 CI 验收包逐字节一致，可使用下方安装命令获取本次修复。

## 0.2.26 更新

本版捆绑 Core **5.8.14**，包含旧会话恢复、精确 DSH `0.2.1-rc.3` 兼容、
Android/ARM 外部 Studio 诊断，以及连载写作可靠性、完整上下文预览和 Embedding 配置修复。
详见 [#105–#113 修复说明](docs/ISSUES_105_113.md)、[连载报告修复](docs/ISSUE_109_REPAIRS.md)
及 [OpenCode Go 配置及适配](docs/OPENCODE_GO.md)。

## 快速安装

**0.2.27 标准插件包**兼容精确 dsh 版本 **0.1.2-rc.1 / 0.1.5-alpha.1 / 0.2.0-rc.2 / 0.2.1-rc.2 / 0.2.1-rc.3**。五个版本均已完成 Web 工作台渲染与 DoG 数据读取验证，Windows Electron 桌面端启动/恢复链路尚未实机复测。可下载版本、各平台验收结果和 SHA-256 以 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/latest) 附件为准；验收方法见 [发布验收](docs/RELEASE_ACCEPTANCE.md)。商城所需的精确预览版兼容性、验证范围和安装限制见 [DSH STORE 接入](docs/DSH_STORE.md)。

正式发行状态以 [npm 版本列表](https://www.npmjs.com/package/dsh-openwrite?activeTab=versions) 和 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/latest) 为准。以下是 0.2.27 精确版本的安装命令；发布时两处使用同一份验收产物：

```sh
dsh plugin --profile web add -w https://github.com/LiPu-jpg/Openwrite/releases/download/v0.2.27/dsh-openwrite-0.2.27.tgz
dsh web
```

已有匹配版本 dsh 的用户执行：

```sh
dsh plugin --profile web add -w dsh-openwrite@latest
dsh web
```

`@latest` 在执行安装或升级命令时选择 npm 最新发布版本，不会自动替换正在运行的服务。无需在安装时编译源码。升级前停止 dsh，并核对目标版本的宿主兼容说明。需要复现或回退时，使用 `dsh-openwrite@0.2.8` 等精确版本；对应版本的 [npm 包](https://www.npmjs.com/package/dsh-openwrite)与 [Release 预编译包](https://github.com/LiPu-jpg/Openwrite/releases) 为同一份已验收产物。

也可把这段话交给有终端权限的 Agent：

```text
请按 https://github.com/LiPu-jpg/Openwrite 的 README 和对应 Release 安装 OpenWrite。
先核对 Release 验收结果和精确 dsh 版本，再用 dsh plugin --profile web add -w dsh-openwrite@latest 安装。
如宿主不兼容，安装最后一个匹配且已验收的精确版本，不自动升级宿主。
已有本地安装先备份并迁移，保留作品、自定义预设、凭据和其他插件。
启动 dsh web，指导我点击 OpenWrite、准备环境并选择自己的作品。
不要调用写作模型做安装检查，不要自动升级宿主或放宽 pnpm 构建授权。
```

首次使用会下载固定版本的 uv、Python 3.12 和锁定依赖，保存在当前 dsh 的专属目录。无需预装 Python，也无需克隆两个分支。目标平台为 macOS arm64/x64、Linux x64、Windows x64；各平台通过情况以发布验收报告为准。模型费用另计。

具体的源码安装、升级、迁移和卸载见 [安装指南](docs/INSTALL.md)。

### dsh 0.2 桌面端升级

`0.2.27`（Core 5.8.16）包含 Go 工作台认证、评审输出预算及后台重试补漏，并保留 #105–#113 与 #103/#104 的既有修复；原始场景仍待验证的条目见 [#123](https://github.com/LiPu-jpg/Openwrite/issues/123)。升级前完全退出 dsh/桌面客户端；安装后重新启动并刷新浏览器。原有作品、凭据和会话继续保留，历史版本预设用于恢复旧会话。受限平台使用外部 Studio，OpenCode Go 的服务商使用范围和配置要求见上述文档。

`0.2.25`（Core 5.8.12）已在 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.25) 与 [npm](https://www.npmjs.com/package/dsh-openwrite/v/0.2.25) 发布，新增连载体检、分段续写、共享术语/范本、章组审计和漂移裁决，并修复验收与任务可观测性。范围、离线升级工具及宿主侧限制见 [#98–#100 实现说明](docs/ISSUES_98_100.md)，完整验收见 [发布验收](docs/RELEASE_ACCEPTANCE.md#025)。

`0.2.24`（Core 5.8.11）修复 [#88–#95](docs/ISSUES_88_95.md)：删章验收账本、结算降级、长文本流式生成、后台写章进度、统一字数门限、草稿发现与恢复及诊断/路由语义。[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.24) 与 [npm](https://www.npmjs.com/package/dsh-openwrite/v/0.2.24) 均已发布，完整验收见 [发布验收](docs/RELEASE_ACCEPTANCE.md#024)。升级后停止并重新启动 dsh，再刷新浏览器页面。

`0.2.23` 修复 [#83](https://github.com/LiPu-jpg/Openwrite/issues/83)/[#84](https://github.com/LiPu-jpg/Openwrite/issues/84)/[#85](https://github.com/LiPu-jpg/Openwrite/issues/85)：根包与全部内嵌子包的兼容声明加入精确宿主 `0.2.1-rc.2`，安装和激活不再被宿主版本闸门拒绝，无需版本豁免或手工编辑 `compatibility.json`。已在 `0.2.1-rc.2` 完成 Web 客户端验收（启动、OpenWrite 入口、工作台三页签、DoG 面板与其他插件共存），`0.1.2-rc.1`、`0.2.0-rc.2` 回归通过；Windows Electron 桌面端未实机复测。该版本完整验收见 [发布验收](docs/RELEASE_ACCEPTANCE.md#023)。升级后停止并重新启动 dsh，再刷新浏览器页面。

`0.2.21` 修复 [#79](https://github.com/LiPu-jpg/Openwrite/issues/79) 的 Windows Desktop 目录选择：宿主接口失败后使用桌面提供的系统文件夹对话框，覆盖侧栏进入与工作台内目录选择。Core 保持 5.8.10。排查与手填路径方式见 [安装指南](docs/INSTALL.md#windows-desktop-目录选择)。

`0.2.20` 捆绑 Core 5.8.10，修复 [#76](https://github.com/LiPu-jpg/Openwrite/issues/76) 的草稿恢复、任务状态、编辑和审稿契约，并补充 [#65](https://github.com/LiPu-jpg/Openwrite/issues/65) 的英文使用支持。行为与范围见 [修复说明](docs/ISSUE_76_REPAIRS.md)。正式可下载版本以 npm `latest` 和 GitHub Release 为准。

`0.2.19` 候选包修复两个加载/工具问题：部分安装下「OpenWrite 创作」预设从列表消失、DoG 工具不可用（dsh-dog 宿主包解析失败，[#74](https://github.com/LiPu-jpg/Openwrite/issues/74)），以及 `novel_*` 工具的对象/数组参数在模型输出 JSON 字符串时预览失败、`data` 字段丢失（[#75](https://github.com/LiPu-jpg/Openwrite/issues/75)）。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，再刷新浏览器页面。

`0.2.18` 候选包修正 `auto:cheapest`（Core 5.8.9）：零价模型不再参与比价，自动落到付费低价模型上。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，再刷新浏览器页面。

`0.2.17` 候选包新增自动选模（Core 5.8.8）：模型档案的模型名写成 `auto:cheapest` 会自动选用服务商价格目录中总价最低且满足上下文/输出要求的模型（目录缓存一小时，价格变动自动跟随），写成 `auto:popular`（OpenRouter）则由官方 `openrouter/auto` 按社区用量自动选模型。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，再刷新浏览器页面。

`0.2.16` 候选包补漏 [#64](https://github.com/LiPu-jpg/Openwrite/issues/64)/[#67](https://github.com/LiPu-jpg/Openwrite/issues/67)：字数精简重试耗尽后保稿时，`length_out_of_range`/`length_warning` 标记与校验问题现在随草稿产物持久化（Core 5.8.7），导出/审阅侧可追溯。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，再刷新浏览器页面。

`0.2.15` 候选包修复 [#63](https://github.com/LiPu-jpg/Openwrite/issues/63)/[#66](https://github.com/LiPu-jpg/Openwrite/issues/66)（Windows 残留 `project.lock` 永久阻断写作，报错 `[WinError 87]`；Core 5.8.6 自动清理死进程残留锁并带上下文报错）、[#64](https://github.com/LiPu-jpg/Openwrite/issues/64)/[#67](https://github.com/LiPu-jpg/Openwrite/issues/67)（`continuous_write` 单章失败即整队终止、`max_failures` 失效、字数超限丢弃初稿；现在按容错上限续跑并保留超长稿）、[#68](https://github.com/LiPu-jpg/Openwrite/issues/68)（横评进行中详情接口恒 400）和 [#69](https://github.com/LiPu-jpg/Openwrite/issues/69)（推理模型评审输出预算被锁死 4096 导致评审全灭）。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，使桥接服务端加载新代码，再刷新浏览器页面。

`0.2.14` 候选包修复 [#60](https://github.com/LiPu-jpg/Openwrite/issues/60) 和 [#61](https://github.com/LiPu-jpg/Openwrite/issues/61)：系统代理下 `NO_PROXY` 含 `[::1]` 不再让所有模型连接测试误报"服务商拒绝了请求"（桥接层消毒 + Core 5.8.5 归类为本地配置错误）；Embedding 连接测试的依赖预热、硬超时与收尾兜底，加上桥接层的健康探活与 stderr 落盘，不再出现"后端活着但不服务、只能重启 dsh"的僵尸态。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，使桥接服务端加载新代码，再刷新浏览器页面。

`0.2.13` 修复 [#57](https://github.com/LiPu-jpg/Openwrite/issues/57) 的创作页刷新循环：批注与版本读取不再作为写操作通知刷新，Core 的只读请求也不再增加工作区变更序号。正式可下载版本以 npm `latest` 和 GitHub Release 为准。升级后需停止并重新启动 dsh，使桥接服务端加载新代码，再刷新浏览器页面。

`0.2.12` 进一步修复 [#50](https://github.com/LiPu-jpg/Openwrite/issues/50)、[#51](https://github.com/LiPu-jpg/Openwrite/issues/51)、[#52](https://github.com/LiPu-jpg/Openwrite/issues/52) 的预设注册、导航、工作台挂载和 DoG 接口。连续审读按内容修订刷新，避免轮询闪烁（[#54](https://github.com/LiPu-jpg/Openwrite/issues/54)）。

`0.2.11` 修复 [#45](https://github.com/LiPu-jpg/Openwrite/issues/45)，适配精确宿主版本 `0.2.0-rc.2`：工作台兼容新的 turn-tail list 槽位，DoG 调试面板使用新的 `sessionStatus`；根包和所有子包的兼容声明同步更新。已验证 0.2.0-rc.2 的 Web 客户端启动、OpenWrite 入口、DoG 面板及其他插件共存；Windows Electron 桌面端恢复链路尚未实机复测。

**`dsh-openwrite@0.2.10` 不包含这项修复，请升级到 `0.2.23` 或更高的已验收版本。** 不要通过给旧子包授权来代替升级：`dsh-openwrite` 的版本豁免不会覆盖 `@dsh-novel/studio-panel@<ver>` 和 `@dsh-external/dsh-dog@<ver>`，而旧客户端在 0.2 宿主上激活失败可能触发桌面端的 profile 恢复。

若已发生恢复，先关闭桌面端并备份当前 profile，再从自己的 `cordis.patch.yml.bak-*` 备份恢复 patch，同时恢复原 `package.json` 的 `dsh.profile.bundles` 列表。安装包和作品目录通常仍在；不要用出厂模板覆盖其他插件配置。详细排查见 [安装指南](docs/INSTALL.md#dsh-02-客户端兼容排查)。

## 开始使用

1. 执行 `dsh web`，打开它给出的浏览器地址，点击侧栏 **OpenWrite**。等待环境就绪后，选择作品目录。
2. 入口自动建立 **OpenWrite 创作** 会话；点击 **创作** 即可打开工作台，无需先发消息。对话模型在 dsh 中配置；小说生成与评审模型在「任务 → 模型」配置。
3. 和 Agent 讨论题材、人物与大纲，确认后再开始写章。已有旧稿可通过「任务 → 导入与导出」接入。

| 日常操作 | 入口 |
|---|---|
| 看进度、继续写作 | `/progress`、`/write-next` |
| 审稿、修改选段 | `/review-chapter`、`/revise-span` |
| 查伏笔、设定与写法记忆 | `/foreshadow`、`/canon`、`/learn` |
| 导出成稿 | `/export-book` 或「任务 → 导入与导出」 |

已有会话不会自动切换预设。详细操作与工作区规则见 [使用流程](docs/WORKFLOWS.md)。

**界面语言**：面板已内置中文与英文词典，跟随 dsh 语言设置。切换方法：Settings → General → Language → English（选择后存为 `locale.preference`）。Agent 的 persona 和所有技能入口要求用作者的对话语言回复；运行环境与任务状态提供英文，Studio 报错附带英文说明和稳定错误码。已有作品内容不会自动翻译，正文按作者指定的语言生成。

## 配置模型

安装和环境健康检查不需要模型 API Key，也不会调用写作模型。与 Agent 对话、生成章节和审稿需要可用的模型配置；使用收费服务商时会产生 API 费用。

- **对话模型**：在 dsh 宿主中配置，用于 OpenWrite 创作会话。
- **小说生成、评审与测试模型**：在「任务 → 模型」添加服务商，按服务商提供的信息填写模型名、接口地址和 API Key。不要把密钥粘贴到对话、作品正文或 Git 仓库。
- **作品目录**：选择自己的本地目录；后端端口与 Python 环境由插件管理，无需手动配置。

旧开发安装的全局模型配置不会自动迁入受管理环境，迁移步骤见 [安装指南](docs/INSTALL.md)。模型连通性测试可能实际调用服务商，应与不调用模型的环境健康检查区分。

## 示例：从大纲开始一部新小说

打开 OpenWrite，选择一个空的作品目录并完成初始化，然后进入 **OpenWrite 创作** 会话。可发送：

```text
请先帮我规划一部短篇悬疑小说：主角是一位修复旧照片的摄影师。
先提出人物、核心谜题和五章大纲，等我确认后再生成正文。
```

确认大纲后使用 `/write-next` 开始写章，在「创作」中编辑正文或添加选区批注；使用 `/review-chapter` 审稿，在应用修订前查看差异。生成与评审会使用前面配置的模型。成稿通过 `/export-book` 或「任务 → 导入与导出」导出。

## 功能

| 工作环节 | 可以做什么 |
|---|---|
| **规划与资料** | 在同一创作会话中整理灵感、人物、世界观、分层大纲与伏笔，维护作品设定。 |
| **正文创作** | 章节导航、连续审读、正文编辑、选区批注与着色、内部状态/关系标记、自动保存、版本保护与场景结构管理。 |
| **审稿与修订** | 六域评审、问题定位、修订差异和复评；通过 DAG 查看流程、依赖及证据。 |
| **模型测试** | 测章节写作或指定范围的大纲设计，多模型独立生成与交叉评审，查看质量、可靠性和费用；候选保存在隔离副本。 |
| **研究与检索** | 检索作品资料与参考库，管理研究报告、正典和写作记忆。 |
| **导入与成书** | 旧稿导入、作品迁移、完整备份，以及 Markdown / TXT / EPUB 导出。 |

「创作 / 资料 / 任务」是三个主要工作台。OpenWrite Studio 在本版本中作为领域后端运行，日常操作在 dsh 中完成。

## 文档与开发

| 文档 | 内容 |
|---|---|
| [安装指南](docs/INSTALL.md) | Agent 安装步骤、手动安装、模型配置、升级和排错 |
| [使用流程](docs/WORKFLOWS.md) | Workspace、规划、写章、审稿、修订、导入导出 |
| [工具参考](docs/TOOLS.md) | 全部 novel_* 工具的作用、操作影响、必填与可选参数 |
| [写手上下文槽位](docs/CONTEXT_SLOTS.md) | 来源文件、选择规则、动态预算、压缩与逐文档用量 |
| [模型测试](docs/BENCHMARK_TASKS.md) | 章节选择、大纲范围、任务 DAG 和结果解读 |
| [审稿 DAG](docs/REVIEW_DAG_FRAMEWORK.md) | 标准评审框架与证据结构 |
| [工程说明](docs/DEVELOPMENT.md) | 组件职责、维护命令、调研和改进记录 |
| [维护手册](docs/PLUGIN_MAINTENANCE.md) · [架构设计](DESIGN.md) | 版本、插件契约、安装维护和跨仓库职责 |

```text
packages/openwrite-bridge/   小说工具与后端桥接
packages/studio-panel/       dsh 原生工作台
presets/openwrite/          OpenWrite 创作预设与技能
scripts/                   安装、启动、检查与 DoG 适配
conductor/                 连续写章、评审与修订编排
```

开发检查：`npm run check:plugin`；跨仓库契约检查：`npm run check`。
小说核心位于同仓库的 [`native-core` 分支](https://github.com/LiPu-jpg/Openwrite/tree/native-core)，与本分支分别维护。工程进度与验证记录保留在 [GOAL.md](GOAL.md)。

## 许可与来源

项目采用 [Apache-2.0](LICENSE)。`oh-story-*` 技能和随包编辑器保留各自目录中的原有许可证。
Logo 基于 OpenWrite `native-core` 分支，已调整深浅主题配色；基于 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)，图谱集成使用 [dsh-dog](https://github.com/Fun10165/dsh-dog)。

生态目录：[dsh-TUI](https://github.com/ccch1mneyyy/dsh-TUI) · [社区插件市场](https://dshtui.com/plugins/)。OpenWrite 当前面向 DeepSeek Harness 的 `web` profile，使用 `dsh web` 打开创作工作台；尚未验证 dsh-TUI 界面兼容性。

## Language / 语言

In dsh, choose **Settings → General → Language → English** (`locale.preference`).
The OpenWrite panel follows the host language. The writing agent and slash-command
help follow your conversation language; manuscripts, outlines and assets retain
their existing language. You can say “Please write and review this novel in English.”
The bundled Chinese skill files are procedural instructions, not an output-language
restriction. Runtime setup messages use English. Backend failures include stable
`code`, English `message`, `request_id`, and the original diagnostic text.

在 dsh 的 **设置 → 通用 → 语言 → English** 切换面板语言。Agent 的回复和命令帮助跟随
当前对话语言；正文与资产遵循作品已有语言，除非作者要求翻译。

任务恢复、编辑确认及审稿职责范围见 [可靠性修复说明](docs/ISSUE_76_REPAIRS.md)。
