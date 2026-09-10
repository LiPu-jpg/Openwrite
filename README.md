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
  <a href="package.json"><img src="https://img.shields.io/badge/dsh-0.1.2--rc.1-2563eb" alt="dsh 0.1.2-rc.1"></a>
  <a href="package.json"><img src="https://img.shields.io/badge/Node-%E2%89%A522.19-15803d" alt="Node >= 22.19"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-0f766e" alt="Apache-2.0"></a>
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

## 快速安装

**0.2.8 标准插件包**兼容 dsh **0.1.2-rc.1**。可下载版本、三平台验收结果和 SHA-256 以 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.8) 附件为准；验收方法见 [发布验收](docs/RELEASE_ACCEPTANCE.md)。默认使用 npm `latest` 渠道；商城所需的精确预览版兼容性、验证范围和安装限制见 [DSH STORE 接入](docs/DSH_STORE.md)。

已有匹配版本 dsh 的用户执行：

```sh
dsh plugin --profile web add -w dsh-openwrite@0.2.8
dsh web
```

[npm 包](https://www.npmjs.com/package/dsh-openwrite)与 [v0.2.8 Release 预编译包](https://github.com/LiPu-jpg/Openwrite/releases/download/v0.2.8/dsh-openwrite-0.2.8.tgz) 是同一份产物。无需在安装时编译源码；也可将命令中的 `dsh-openwrite@0.2.8` 换成该 Release 下载地址。

也可把这段话交给有终端权限的 Agent：

```text
请按 https://github.com/LiPu-jpg/Openwrite 的 README 和对应 Release 安装 OpenWrite。
先核对 Release 验收结果和精确 dsh 版本，再安装对应版本的 npm 包或校验 SHA-256 后安装 Release .tgz。
已有本地安装先备份并迁移，保留作品、自定义预设、凭据和其他插件。
启动 dsh web，指导我点击 OpenWrite、准备环境并选择自己的作品。
不要调用写作模型做安装检查，不要自动升级宿主或放宽 pnpm 构建授权。
```

首次使用会下载固定版本的 uv、Python 3.12 和锁定依赖，保存在当前 dsh 的专属目录。无需预装 Python，也无需克隆两个分支。目标平台为 macOS arm64/x64、Linux x64、Windows x64；各平台通过情况以发布验收报告为准。模型费用另计。

具体的源码安装、升级、迁移和卸载见 [安装指南](docs/INSTALL.md)。

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
