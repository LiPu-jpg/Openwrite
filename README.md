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
  <a href="package.json"><img src="https://img.shields.io/badge/dsh-0.1.0--rc.7-2563eb" alt="dsh 0.1.0-rc.7"></a>
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

**已有 dsh？把下面这段话复制给有终端权限的 Agent，让它完成安装。**

```text
请帮我安装 dsh-Openwrite：
https://github.com/LiPu-jpg/Openwrite

先读取 main 分支的 docs/INSTALL.md，实际完成安装和检查。
补齐依赖，安装插件、OpenWrite 创作预设和默认 DoG。
main 放在 ~/novel-tools/dsh-Openwrite，
native-core 放在相邻的 OpenWrite 目录。
复用已有的正确安装、dsh 配置和作品；没有作品时创建 ~/my_novel。
完成 doctor 检查并启动，指导我在作品 Workspace 新建创作会话。
密钥由我在本机设置中填写，安装验收不调用写作模型。
如需重启当前 dsh，先完成其余步骤，再告诉我重启命令。
最后给出安装位置、作品位置、检查结果和浏览器地址。
```

**手动安装或还没有 dsh**：按 [安装指南](docs/INSTALL.md) 操作。安装器会安装仓库锁定的 dsh CLI；支持 macOS / Linux，Windows 使用 WSL2。需要 Git、Node ≥ 22.19、npm、pnpm、rsync 和 uv。

安装默认包含创作预设、90 个小说工具、原生工作台和 DoG 图谱。首次安装需要下载依赖；日常模型调用按所选服务商计费。

## 开始使用

1. 启动后打开 [本地工作台](http://127.0.0.1:3080)，把小说目录添加为 dsh Workspace。
2. 在该 Workspace 新建会话，选择 **OpenWrite 创作**。对话模型在 dsh 中配置；小说生成与评审模型在「任务 → 模型」配置。
3. 和 Agent 讨论题材、人物与大纲，确认后再开始写章。已有旧稿可通过「任务 → 导入与导出」接入。

| 日常操作 | 入口 |
|---|---|
| 看进度、继续写作 | `/progress`、`/write-next` |
| 审稿、修改选段 | `/review-chapter`、`/revise-span` |
| 查伏笔、设定与写法记忆 | `/foreshadow`、`/canon`、`/learn` |
| 导出成稿 | `/export-book` 或「任务 → 导入与导出」 |

已有会话不会自动切换预设。详细操作与工作区规则见 [使用流程](docs/WORKFLOWS.md)。

## 功能

| 工作环节 | 可以做什么 |
|---|---|
| **规划与资料** | 在同一创作会话中整理灵感、人物、世界观、分层大纲与伏笔，维护作品设定。 |
| **正文创作** | 章节导航、连续审读、正文编辑、自动保存、版本保护与场景结构管理。 |
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
