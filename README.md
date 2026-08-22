# dsh-novel

把 [OpenWrite](https://github.com/LiPu-jpg/Openwrite) 的长篇小说创作能力接入
[DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness) 的 agent 运行时。

- **dsh** 负责 agent 编排：Goethe/Dante 双预设、技能目录、子代理委派、长上下文压缩
- **OpenWrite** 负责小说领域能力：大纲树、章节流水线、37 维评审、伏笔 DAG、正典状态
- **OpenWrite Studio** 继续担当文本编辑器与资产看板

架构与职责划分见 [DESIGN.md](DESIGN.md)。

## 组件

| 路径 | 说明 |
|---|---|
| `packages/openwrite-bridge/` | dsh 插件：62 个 `novel_*` 工具，覆盖 Studio HTTP 动作面全部端点 |
| `packages/studio-panel/` | dsh web 原生视图：总览/正文/审稿（内嵌 Studio）、大纲、资产、任务、图谱、研究、搜索 tab + 评审报告卡 |
| `presets/goethe/` | Goethe 规划 agent 预设（灵感/人物/设定/大纲收敛） |
| `presets/dante/` | Dante 写作 agent 预设（写章/评审/结算，可向 Goethe 子代理咨询） |
| `scripts/install.sh` | 构建插件、安装预设到 `~/.dsh/.agent-presets/`、插件装进 dsh profile |
| `scripts/dev.sh` | 一键启动 OpenWrite Studio + dsh web |
| `scripts/verify.sh` | 一键集成验证（服务/插件/代理路由/嵌入皮肤，13 项） |
| `conductor/` | Python 编排器：无人值守连续写章 → 37 维评审 → 低于阈值自动回炉（走 OpenWrite 后台任务系统；详见 DESIGN.md §6） |

## 快速开始

前置：Node ≥ 22.19、[uv](https://docs.astral.sh/uv/)、`DEEPSEEK_API_KEY`，
以及本地 OpenWrite 源码（默认 `/Users/jiaoziang/OpenWrite`）和一个小说项目
（默认 `~/my_novel`）。

```sh
scripts/install.sh   # 一次性安装（幂等）
scripts/dev.sh       # 启动两端服务
```

然后打开 http://127.0.0.1:3080 ，新建会话时选择 **Goethe 规划** 或
**Dante 写作** 预设。会话头部的「总览 / 正文 / 审稿 / 大纲 / 资产 / 任务 /
图谱 / 研究 / 搜索」tab 覆盖编辑、结构、设定与资料库、后台任务、伏笔与
人物关系图、深度研究与项目检索；无需直接打开 Studio。

## 工作方式

1. 在 **Goethe** 会话里收敛灵感、人物、世界观与大纲（所有写入经 OpenWrite
   修订门控，重要改动先出 diff 再确认）。
2. 切到 **Dante** 会话写正文：`novel_context_preview` 预检上下文包 →
   `novel_write_chapter` 写章 → `novel_review_chapter` 37 维评审。
   资产不齐时 Dante 会建议回 Goethe，或经 `subagent_goethe` 子代理做只读咨询。
3. 无人值守批量生产用 **conductor**（需 Studio 在跑）：
   `cd conductor && .venv/bin/python pipeline.py --chapters next --limit 3`——
   连续写章 → 37 维评审 → 低于阈值/含 blocker 自动经修订闭环回炉；
   `--review-only` / `--rework` / `--agent-guidance` 见模块 docstring 与 DESIGN.md §6。
4. 在 Studio 里精修稿件、看大纲树与资产看板，导出 MD/TXT/EPUB。

## 许可

桥接插件与预设代码沿用 OpenWrite 的 Apache-2.0；`presets/*/skills/` 下 oh-story-*
技能保留其原有 MIT 许可（见各目录 LICENSE）。
