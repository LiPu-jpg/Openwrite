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
  <a href="https://github.com/LiPu-jpg/Openwrite/stargazers"><img src="https://img.shields.io/github/stars/LiPu-jpg/Openwrite?style=flat&logo=github" alt="GitHub Stars"></a>
  <a href="https://www.npmjs.com/package/dsh-openwrite"><img src="https://img.shields.io/npm/v/dsh-openwrite" alt="npm dsh-openwrite"></a>
  <a href="package.json"><img src="https://img.shields.io/badge/host%20dsh-0.2.2--rc.3-2563eb" alt="dsh 0.2.2-rc.3"></a>
  <a href="package.json"><img src="https://img.shields.io/badge/Node-%E2%89%A522.19-15803d" alt="Node >= 22.19"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache-2.0"></a>
  <a href="https://dsh-plugin.org/plugins/lipu-jpg/openwrite"><img src="https://dsh-plugin.org/badges/listed.svg" alt="Listed on dsh-plugin.org"></a>
</p>

<p align="center">
  <a href="#快速安装">快速安装</a> ·
  <a href="#开始使用">开始使用</a> ·
  <a href="#功能">功能</a> ·
  <a href="#遇到问题">遇到问题</a> ·
  <a href="#文档与开发">文档</a> ·
  <a href="https://github.com/LiPu-jpg/Openwrite/issues">反馈问题</a>
</p>

这是 [OpenWrite](https://github.com/LiPu-jpg/Openwrite/tree/native-core) 的 dsh 插件版本。
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 提供 Agent 与交互界面，OpenWrite Core 提供小说领域能力；人物、设定、大纲、正文和评审保存在本地作品目录。

长篇小说的规划、写作、审稿和改稿都在 dsh 里的三个原生工作台页签完成：**创作**（正文、批注、版本）、**资料**（人物、设定、大纲、研究）、**任务**（模型、导入导出）。适合愿意自己配置模型、在本机管理稿件的作者与工作室；不适合期待开箱即用的云端成品、或不愿提供模型 API Key 的场景。

## 快速安装

**运行要求**：dsh 宿主（精确版本见下）· Node ≥ 22.19 · macOS arm64/x64、Linux x64、Windows x64 · 首次使用会下载 uv、Python 3.12 与锁定依赖 · 真正写稿与审稿需要你自己的模型 API Key。

兼容的精确 dsh 宿主版本：

`0.1.2-rc.1` · `0.1.5-alpha.1` · `0.1.7-rc.2` · `0.2.0-rc.2` · `0.2.1-rc.2` · `0.2.1-rc.3` · `0.2.1-rc.4` · `0.2.1-rc.5` · `0.2.2-rc.1` · `0.2.2-rc.2` · `0.2.2-rc.3`

安装前先执行 `dsh --version` 核对宿主版本；安装不会自动升级 dsh。

```sh
dsh plugin --profile web add -w dsh-openwrite@latest
dsh web
```

需要固定版本或离线安装时，用 npm 的 `dsh-openwrite@<精确版本>`，或从 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/latest) 下载对应 `.tgz`；同一版本的 npm 包与 Release `.tgz` 是同一份已验收产物，包含预编译插件、编辑器资源与 Core wheel。

`@latest` 只在执行命令时解析 npm 最新发布版本，安装后不会后台自动升级，也不会替换正在运行的服务。

首次使用会下载固定版本的 uv、Python 3.12 和锁定依赖，保存在当前 dsh 的专属目录。无需预装 Python，也无需克隆仓库。目标平台为 macOS arm64/x64、Linux x64、Windows x64；各平台通过情况以发布验收报告为准。模型费用另计。

也可把这段话交给有终端权限的 Agent：

```text
请按 https://github.com/LiPu-jpg/Openwrite 的 README 和对应 Release 安装 OpenWrite。
先核对 Release 验收结果和精确 dsh 版本，再用 dsh plugin --profile web add -w dsh-openwrite@latest 安装。
如宿主不兼容，安装最后一个匹配且已验收的精确版本，不自动升级宿主。
已有本地安装先备份并迁移，保留作品、自定义预设、凭据和其他插件。
启动 dsh web，指导我在侧栏「工作区」打开或新建作品目录，并将会话预设切换为 **OpenWrite 创作**。
不要调用写作模型做安装检查，不要自动升级宿主或放宽 pnpm 构建授权。
```

具体的源码安装、升级、迁移和卸载见 [安装指南](docs/INSTALL.md)。

## 升级与回退

- 升级前完全退出 dsh 与 Desktop（含托盘），并备份 profile；安装完成后重启宿主并刷新浏览器页面。
- `@latest` 不会自动替换正在运行的服务，升级前先停机。
- 需要复现或回退时安装精确版本：`dsh-openwrite@<精确版本>` 与 GitHub Release 的同名 `.tgz` 为同一份已验收产物。
- 宿主的原生升级保护补丁尚未进入正式宿主，插件侧的停机升级工具不等于宿主原生安装命令已有保护。
- 若旧客户端在 0.2 宿主上激活失败，桌面端可能触发 profile 恢复。恢复后：关闭桌面端并备份当前 profile，从自己的 `cordis.patch.yml.bak-*` 备份恢复 patch，同时恢复原 `package.json` 的 `dsh.profile.bundles` 列表。安装包和作品目录通常仍在；不要用出厂模板覆盖其他插件配置。也不要靠给旧子包授权来代替升级——`dsh-openwrite` 的版本豁免不覆盖 `@dsh-novel/studio-panel@<ver>`。
- 卸载：停止 dsh 后执行 `dsh plugin --profile web remove -w dsh-openwrite`。作品、配置、凭据和会话默认保留。

细节见 [更新与回退](docs/INSTALL.md#更新与回退) 和 [离线升级和损坏修复](docs/ISSUES_98_100.md#离线升级和损坏修复)，目录选择问题见 [Windows Desktop 目录选择](docs/INSTALL.md#windows-desktop-目录选择)。

## 遇到问题

- 界面「设置 → OpenWrite → 环境 → 诊断与反馈」支持一键**复制脱敏诊断信息**或**去 GitHub 反馈问题（自动带入环境信息）**，绝不包含任何小说正文、大纲、角色设定、本地作品路径或 API 密钥。
- 体检安装状态：解包后执行 `node package/scripts/maintenance.mjs doctor --profile web`，只读检查标准包登记、旧包残留与环境状态，不打印凭据、不调用模型。
- 工作台起不来、预设挂载失败这类问题多与宿主版本和 profile 状态有关，见 [dsh 0.2 客户端兼容排查](docs/INSTALL.md#dsh-02-客户端兼容排查)。
- 反馈时请附上宿主版本、系统与架构、Release 版本、安装阶段和脱敏后的错误信息；不要提交 API Key、浏览器登录 URL 或作品全文。如果觉得 OpenWrite 对你的创作有帮助，也欢迎在 GitHub 点一颗 Star 支持我们。

## 开始使用

1. 执行 `dsh web`，打开它给出的浏览器地址，在左侧「工作区」中添加或打开作品目录，并在会话顶部或输入框下方的预设选择器中切换为 **OpenWrite 创作**（可在「设置 → OpenWrite」查看环境状态、常用指令与提交脱敏反馈）。
2. 会话绑定作品目录并切到 **OpenWrite 创作** 后，点击 **创作** 即可打开工作台，无需先发消息。对话模型在 dsh 中配置；小说生成与评审模型在「任务 → 模型」配置。
3. 和 Agent 讨论题材、人物与大纲，确认后再开始写章。已有旧稿可通过「任务 → 导入与导出」接入。

| 日常操作 | 入口 |
|---|---|
| 看进度、继续写作 | `/progress`、`/write-next` |
| 审稿、修改选段 | `/review-chapter`、`/revise-span` |
| 查伏笔、设定与写法记忆 | `/foreshadow`、`/canon`、`/learn` |
| 导出成稿 | `/export-book` 或「任务 → 导入与导出」 |

已有会话不会自动切换预设。详细操作与工作区规则见 [使用流程](docs/WORKFLOWS.md)，预设自带的完整技能清单见 [`presets/openwrite/skills/`](presets/openwrite/skills)。

**界面语言**：面板已内置中文与英文词典，跟随 dsh 语言设置。切换方法：Settings → General → Language → English（选择后存为 `locale.preference`）。Agent 的 persona 和所有技能入口要求用作者的对话语言回复；运行环境与任务状态提供英文，Studio 报错附带英文说明和稳定错误码。已有作品内容不会自动翻译，正文按作者指定的语言生成。

## 配置模型

安装和环境健康检查不需要模型 API Key，也不会调用写作模型。与 Agent 对话、生成章节和审稿需要可用的模型配置；使用收费服务商时会产生 API 费用。

- **对话模型**：在 dsh 宿主中配置，用于 OpenWrite 创作会话。
- **小说生成、评审与测试模型**：在「任务 → 模型」添加服务商，按服务商提供的信息填写模型名、接口地址和 API Key。不要把密钥粘贴到对话、作品正文或 Git 仓库。
- **作品目录**：选择自己的本地目录；后端端口与 Python 环境由插件管理，无需手动配置。
- **研究检索**：托管运行时默认走宿主的搜索与抓取能力，不需要第三方 Key；也可在「OpenWrite → 设置 → 搜索」切换提供方并记住 Key，单个作品在研究页覆盖。检索质量 `quality` 只接受 `advisory` / `balanced` / `strict`，其他值会在启动子进程前被拒绝。
- **OpenCode Go**：工作台可直接读取本机官方 CLI 的有效凭据和工作区信息，不必手工复制会过期的 Console 令牌，详见 [OpenCode Go 接入](docs/OPENCODE_GO.md)。

作品、凭据和配置保存在本机；只有调用你配置的模型服务商时，请求才会离开本机。

旧开发安装的全局模型配置不会自动迁入受管理环境，迁移步骤见 [安装指南](docs/INSTALL.md)。模型连通性测试可能实际调用服务商，应与不调用模型的环境健康检查区分。

DeepResearch 是可选依赖，首次使用需在其 integration 目录执行 `pnpm install --frozen-lockfile`；不启用时研究能力不受影响。

## 示例：从大纲开始一部新小说

在 dsh 侧栏「工作区」中添加一个空目录并新建会话，将预设切换为 **OpenWrite 创作** 后在工作台中完成项目初始化。可发送：

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
| **联动插件** | 与 dsh-our-free-model、dsh-ops、dsh-dog 协作：切换写作与评审模型、挂载有界文件工具、交付验证。均为可选项，未安装时行为不变。 |

「创作 / 资料 / 任务」是三个主要工作台。OpenWrite Studio 作为领域后端运行，日常操作在 dsh 中完成。联动插件的接入方式见 [联动插件说明](docs/COMPANION_PLUGINS.md)。

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
| [发布验收](docs/RELEASE_ACCEPTANCE.md) | 各版本的平台验收结果与校验值 |
| [DSH STORE 接入](docs/DSH_STORE.md) | 商城所需的预览版兼容性与安装限制 |
| [维护手册](docs/PLUGIN_MAINTENANCE.md) · [架构设计](DESIGN.md) | 版本、插件契约、安装维护和跨仓库职责 |

```text
packages/openwrite-bridge/   小说工具与后端桥接
packages/studio-panel/       dsh 原生工作台
presets/openwrite/          OpenWrite 创作预设与技能
scripts/                   安装、启动与检查
conductor/                 连续写章、评审与修订编排
```

开发检查：`npm run check:plugin`；跨仓库契约检查：`npm run check`。
小说核心位于同仓库的 [`native-core` 分支](https://github.com/LiPu-jpg/Openwrite/tree/native-core)，与本分支分别维护。工程进度与验证记录保留在 [GOAL.md](GOAL.md)。

## 版本与兼容性

逐版变更记录不在本文件里：

- **[CHANGELOG.md](CHANGELOG.md)** —— 每个版本修了什么、根因是什么、验收怎么做的。
- **[GitHub Releases](https://github.com/LiPu-jpg/Openwrite/releases/latest)** —— 发布产物、SHA-256 校验值与验收报告。
- **[npm 版本列表](https://www.npmjs.com/package/dsh-openwrite?activeTab=versions)** —— 已发布的 npm 版本。

精确的宿主兼容版本以 `package.json` 的 `dsh.compatibility` 为准：宿主在安装前读取的是包里的 `@deepseek-ai/dsh-*` peer 范围，`dsh.compatibility` 只是展示元数据。本 README 上方列出的宿主列表与它一致。

## 许可与来源

项目采用 [Apache-2.0](LICENSE)。`oh-story-*` 技能和随包编辑器保留各自目录中的原有许可证。
Logo 基于 OpenWrite `native-core` 分支，已调整深浅主题配色；基于 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)，图谱验证可选装第三方 [dsh-dog](https://github.com/Fun10165/dsh-dog)（内置引擎已移除）。

生态目录：[dsh-TUI](https://github.com/ccch1mneyyy/dsh-TUI) · [社区插件市场](https://dshtui.com/plugins/)。OpenWrite 面向 DeepSeek Harness 的 `web` 与 `desktop` profile，使用 `dsh web` 打开创作工作台；尚未验证 dsh-TUI 界面兼容性。

## Language / 语言

In dsh, choose **Settings → General → Language → English** (`locale.preference`).
The OpenWrite panel follows the host language. The writing agent and slash-command
help follow your conversation language; manuscripts, outlines and assets retain
their existing language. You can say "Please write and review this novel in English."
The bundled Chinese skill files are procedural instructions, not an output-language
restriction. Runtime setup messages use English. Backend failures include stable
`code`, English `message`, `request_id`, and the original diagnostic text.

在 dsh 的 **设置 → 通用 → 语言 → English** 切换面板语言。Agent 的回复和命令帮助跟随
当前对话语言；正文与资产遵循作品已有语言，除非作者要求翻译。

任务恢复、编辑确认及审稿职责范围见 [可靠性修复说明](docs/ISSUE_76_REPAIRS.md)。
