# dsh-novel

把 [OpenWrite](https://github.com/LiPu-jpg/Openwrite) 的长篇小说创作能力接入
[DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness) 的 agent 运行时。

- **dsh** 负责 agent 编排：Goethe/Dante 双预设、技能目录、子代理委派、长上下文压缩
- **OpenWrite** 负责小说领域能力：大纲树、章节流水线、37 维评审、伏笔 DAG、正典状态
- **OpenWrite Studio** 只提供无界面的小说领域 HTTP 后端；dsh 是唯一交互壳与编辑工作台

架构与职责划分见 [DESIGN.md](DESIGN.md)。

## 组件

| 路径 | 说明 |
|---|---|
| `packages/openwrite-bridge/` | dsh 插件：62 个 `novel_*` 工具，覆盖 Studio HTTP 动作面全部端点 |
| `packages/studio-panel/` | dsh web 原生工作台：创作 / 资料 / 任务，含正文编辑器、共享状态与工具卡 |
| `presets/goethe/` | Goethe 规划 agent 预设（灵感/人物/设定/大纲收敛） |
| `presets/dante/` | Dante 写作 agent 预设（写章/评审/结算，可向 Goethe 子代理咨询） |
| `scripts/install.sh` | 构建插件、安装预设到 `~/.dsh/.agent-presets/`、插件装进 dsh profile |
| `scripts/dev.sh` | 一键启动 OpenWrite Studio + dsh web |
| `scripts/verify.sh` | 一键集成验证（服务、领域代理、失效快照、本地编辑器资源、无 iframe） |
| `conductor/` | Python 编排器：无人值守连续写章 → 37 维评审 → 低于阈值自动回炉（走 OpenWrite 后台任务系统；详见 DESIGN.md §6） |

## 快速开始

前置：Node ≥ 22.19、[uv](https://docs.astral.sh/uv/)、`DEEPSEEK_API_KEY`，
以及本地 OpenWrite 源码（默认 `/Users/jiaoziang/OpenWrite`）和一个小说项目
（默认 `~/my_novel`）。

```sh
scripts/install.sh   # 一次性安装（幂等）
scripts/dev.sh       # 启动两端服务
```

如需启用 37 维 DoG 查询，先准备朋友的 `dsh-dog` 工作树，再执行
`DSH_DOG_DIR=/path/to/dsh-dog scripts/install.sh`；它只安装 web profile，
并不会把 dsh-dog 源码复制进本项目。
安装脚本会先构建该工作树，再挂载插件。
安装时会把 `dog.workspaceRoot` 写入 `~/.dsh/settings.yaml`；默认是本项目根目录，
也可用 `DSH_DOG_WORKSPACE_ROOT=/path/to/novel scripts/install.sh` 指定。已有 `dog:`
配置不会被覆盖，切换项目时需手动修改该字段并重启 dsh。

然后打开 http://127.0.0.1:3080 ，新建会话时选择 **Goethe 规划** 或
**Dante 写作** 预设。会话头部只增加「创作 / 资料 / 任务」三个工作流 tab；
正文编辑、大纲、资产、图谱、研究、搜索与后台任务全部在 dsh 原生界面完成。

## 工作方式

1. 在 **Goethe** 会话里收敛灵感、人物、世界观与大纲（所有写入经 OpenWrite
   修订门控，重要改动先出 diff 再确认）。
2. 切到 **Dante** 会话写正文：`novel_context_preview` 预检上下文包 →
   `novel_write_chapter` 写章 → `novel_review_chapter` 37 维评审。
   每次评审同时生成 `data/novels/{id}/data/dog/reviews/{chapter}/dog-graph.json`；
   通过 `novel_task_create(type=chapter_review)` 启动的后台评审，也会在
   `novel_task_get` 读到完成态时生成同样的图；
   在 web 会话中把该 graph 交给 `dog_create` / `dog_run`，即可按 37 个维度查询
   证据、失败原因和继承状态。DoG 只查询已生成的评审结果，不重复跑 37 维模型审查。
   写章、评审和 `novel_revision_*` 操作还会维护
   `data/novels/{id}/data/dog/deliveries/{chapter}/dog-graph.json`：它把正文、
   当前评审、修订应用和复评关闭串成章节交付总图；修订应用后必须复评通过才算交付。
   DoG 的 `workspaceRoot` 需要指向 OpenWrite 项目根目录。
   资产不齐时 Dante 会建议回 Goethe，或经 `subagent_goethe` 子代理做只读咨询。
   拆书导入则先执行 `conductor/smart_import.py`，对输出的
   `data/novels/{id}/data/dog/imports/{IMPORT_ID}/dog-graph.json` 做 DoG 验收；
   验收通过后再由 Goethe 建立大纲、角色、世界观、进度和正典事件，最后重新跑 37 维审查。
3. 无人值守批量生产用 **conductor**（需 Studio 在跑）：
   `cd conductor && .venv/bin/python pipeline.py --chapters next --limit 3`——
   连续写章 → 37 维评审 → 低于阈值/含 blocker 自动经修订闭环回炉；
   `--review-only` / `--rework` / `--agent-guidance` 见模块 docstring 与 DESIGN.md §6。
4. 在「创作」中精修稿件并处理审稿/修订，在「资料」维护正典，在「任务」导入、
   同步或导出 MD/TXT/EPUB。Studio 只作为头部溢出菜单中的高级维护出口。

## 许可

桥接插件与预设代码沿用 OpenWrite 的 Apache-2.0；`presets/*/skills/` 下 oh-story-*
技能保留其原有 MIT 许可（见各目录 LICENSE）。
