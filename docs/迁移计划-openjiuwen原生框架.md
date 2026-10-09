# OpenWrite → openJiuwen 原生框架迁移计划

> 目标：不再保留 dsh 插件形态，把 OpenWrite 的全部能力逐步迁入 openJiuwen 原生框架
> （Agent Core / JiuwenSwarm），最终以 openJiuwen 标准形态交付与参赛。

## 架构总览（迁移后）

```
┌──────────────── openJiuwen 原生运行时（JiuwenSwarm）────────────────┐
│  工作台：WorkSwarm / Web / TUI（替代 dsh + studio-panel）            │
│  蜂群：openwrite-novel-swarm（Leader + 6 teammate，已交付）          │
│  编排：Swarmflow（scripts/workflow.py，已交付）                      │
│  技能：OpenWrite 12 子技能 → Skills 规范改写（已完成，见第二期）     │
│  工具：openwrite-mcp（MCP server，25 个领域工具，读 8 + 写 17）      │
│         └─ 桥接 OpenWrite native-core 引擎（6.4 万行，保留不改）      │
└──────────────────────────────────────────────────────────────────────┘
```

关键决策：**引擎本体（native-core 6.4 万行）不重写**，以 MCP 工具面包裹其权威
Python 模块（ChapterAssemblerV2 / ForeshadowingDAGManager / TruthFilesManager /
review_dag_framework）， Agent 通过原生 MCP 调用——这是 openJiuwen 官方扩展
机制（config.mcp.servers），也是最符合"全部迁移到原生框架"语义的形态：
框架、技能、编排、工具全部原生，仅领域引擎作为被治理的外部能力。

## 模块对照表

| OpenWrite 模块（native-core） | openJiuwen 原生形态 | 状态 |
|---|---|---|
| Goethe/Dante 编排（conductor/pipeline.py） | Swarm Skill 角色 + Swarmflow 脚本 | ✅ 已交付 |
| 六域评审 DAG（review_dag_framework.py） | `get_review_framework` MCP 工具 + 评审员内联 rubric | ✅ 本期 |
| canonical packet（chapter_assembler.py） | `get_context_packet` MCP 工具 | ✅ 本期 |
| 伏笔 DAG（foreshadowing_manager.py） | `list/update/get_chapter_foreshadowing` MCP 工具 | ✅ 本期 |
| truth 文件（truth_manager.py） | `get_truth` MCP 工具（写操作走状态结算，下下期） | ✅ 本期（读） |
| 分层大纲（outline_tree.py） | `get_outline` / `list_projects` MCP 工具 | ✅ 本期 |
| 12 个子技能（skills/*） | Skills 规范（SKILL.md）逐一改写 | ✅ 第二期（12/12 已装 workspace） |
| 风格指纹（style_*.py） | style-system 技能；指纹经 `get_context_packet` 分区携带 | ✅ 第二期（独立工具并入 packet） |
| 章节记忆/压缩（chapter_memory, progressive_compressor） | text-processing 技能（压缩纪律 L1–L4）；引擎 ChapterMemoryStore 随写路径自动维护，压缩由 packet 组装触发，风格指纹经 style_documents 分区携带 | ✅ 第二期（openJiuwen LTM 为可选增强，非缺口） |
| 章节写作/修订（chapter_pipeline, revision_service） | `write_chapter`/`save_external_chapter` MCP 工具 + 引擎托管运行时（litellm 已装 venv） | ✅ 第三期 |
| 六域评审执行（review 工具链，含 LLM） | `review_chapter` MCP 工具（引擎 review_v2 + canon 门） | ✅ 第三期 |
| EPUB/导出（epub_export.py） | `export_book` MCP 工具（含 validate_epub 校验） | ✅ 第三期 |
| dsh 插件壳（openwrite-bridge, studio-panel） | 废弃：交付物纯 JiuwenSwarm 形态，不再依赖 dsh | ✅ 第三期（随交付废弃） |
| 确认门控（修订门、diff 预览） | author-gate + `accept_manuscript`/`resume_acceptance`/`acknowledge_impacts` 两阶段指纹门 | ✅ 第三期 |

## 分期

**第一期（本期，已完成）**：领域工具 MCP 化
- openwrite-mcp 8 工具：list_projects / get_outline / get_context_packet /
  get_review_framework / list_foreshadowing / update_foreshadowing_status /
  get_truth / get_chapter_foreshadowing
- 已注册进 jiuwenswarm config.mcp.servers
- 已对 demo_short 示范作品完成真实数据验证（大纲 1 卷 1 幕 1 节 3 章、
  下一章推荐 ch_001、canonical packet 15272 字符、47 节点评审蓝图）
- ~~待办：把 openwrite-novel-swarm 的 dependencies.yaml/角色声明切换到 MCP 工具依赖~~
  （已完成，见第二期末项；运行注意：FastMCP Client 按脚本路径自启子进程时不继承
  调用方 env，须以注册表显式传 env——config.mcp.servers 已按此配置）

**第二期（已完成，2026-10-08）**：知识资产迁移
- 12 个子技能按 Skills 规范改写完成，输出至 `openwrite-skills/<name>/SKILL.md`，
  全部安装进 `~/.jiuwenswarm/agent/workspace/skills/`；改写口径：frontmatter 保留
  原名与触发词，正文压缩至 40–70 行，工具引用统一改为 openwrite-mcp 工具名，
  状态机/阈值/分级表等领域真知识全部保留，写路径操作标注"第三期接入"
- text-processing 写入 tiered-hierarchical-v2 四级压缩表与三级压缩比（5:1/15:1/50:1）；
  workflow-manager 写入六阶段状态机与中断恢复纪律；goethe-agent 写入 patch 纪律、
  风格三模式与输出口径
- 蜂群角色提示词与 MCP 对齐：reviewer-canon 评审前先取 `get_review_framework`
  （47 节点蓝图，topology_locked）/`get_truth`/`get_chapter_foreshadowing`；
  dante-writer 动笔前先取 `get_context_packet`/`get_chapter_foreshadowing`/`get_outline`；
  goethe-planner 续作前先取 `list_projects`/`get_outline`/`get_context_packet`；
  快照与 MCP 实时数据冲突时以 MCP 为准
- **规划写路径补齐（2026-10-08 查缺补漏）**：新增 `create_project`（init_project
  脚手架）、`save_foundation_draft`/`promote_foundation`（设定两阶段门）、
  `save_outline_draft`/`promote_outline`（大纲两阶段门，revision 重验）、
  `stage_outline_edits`（分批补丁暂存）——蜂群规划产物可完整写回引擎成为真书
- **运行时修复**：引擎内部使用 `asyncio.run`，MCP 运行时持有事件循环冲突；
  `resume_acceptance`/`write_chapter`/`review_chapter` 三个 LLM 工具改经
  `asyncio.to_thread` 在独立线程执行
- **workflow.py 批量产章节号参数化**：`derive_chapter_inputs(asset_pack, chapter_number)`
  支持 1-200 章锚点提取，`chapter_number` 入参驱动批量无人值守
- **旗舰 DEMO《夜班便利店》**（demo-night-shift）：蜂群规划 → create_project →
  设定/大纲两阶段门 → 蜂群 ch_001 入库 → 指纹门确认 → 事实重建（8 域 current）→
  复核 → 引擎原生续写 ch_002（30.6s，完美承接蜂群正文：备忘录/3号冰柜伏笔全接上）
  → 双章 current → EPUB 校验通过。引擎与蜂群同写一个故事的完整闭环
- demo-works（demo_novel）已复原为纯净 demo_short 模板，专作引擎能力测试床
- 验证：官方 swarmskill-creator 校验器 0 error（1 个既有 warning）；
  桩件端到端 18/18 断言通过；MCP 真实客户端握手 + 蓝图/伏笔调用通过

**第三期（已完成，2026-10-08）**：执行面迁移与工作台替换
- openwrite-mcp 写路径 8 工具全部落地并实测：`save_external_chapter`（蜂群成稿入库，
  自动启动接纳）、`manuscript_status`、`accept_manuscript`（两阶段指纹门）、
  `resume_acceptance`（引擎托管事实重建）、`acknowledge_impacts`（作者复核）、
  `write_chapter`/`review_chapter`（引擎原生写审）、`export_book`（EPUB+校验）
- 引擎托管运行时跑通：venv 补装 litellm（阿里云镜像，需 --no-cache-dir 规避坏缓存）
- 确认门全链路实录（demo_novel）：蜂群 ch_001 写入 → CONFIRMATION_REQUIRED 两阶段
  → 事实重建 10 影响域 8 current + 2 needs_review → 复核确认 → ch_002 引擎原生写章
  （自动接纳 completed）→ 双章 EPUB 导出校验通过
- 真实模型蜂群端到端（DeepSeek）：5 次调用 / 约 30 秒，六域 7–9 分直达交付；
  对抗实录：主笔换主角被三评审抓出 7 blocker、修订匠拒硬改
- **全运行时整跑**：jiuwenswarm 真实网关 + agent server 对话驱动，Agent 自主调用
  openwrite-mcp 工具（项目进度 + 47 节点蓝图）并正确复述；运行时实测加载 12 个
  改写技能。关键排障：模型 env 必须写入 `~/.jiuwenswarm/config/.env`（常驻网关启动
  时读取；出厂占位值导致"模型未正确配置"），shell export 对常驻进程无效
- dsh 壳随交付废弃：最终形态为纯 JiuwenSwarm（蜂群 + Skills + SwarmFlow + MCP），
  工作台由 JiuwenSwarm Web/TUI 承担

**全部三期完成。OpenWrite → openJiuwen 原生框架迁移收官。**

## 风险与对策

| 风险 | 对策 |
|---|---|
| 引擎写操作（正文/评审）直接暴露有越权风险 | 写工具逐一对接引擎既有确认门（change_plan + revision 重验），不绕门 |
| MCP 大 payload（packet 15k 字符）挤占 teammate 上下文 | 评审员只取所需分区；必要时增加 packet 分区工具 |
| 引擎对运行环境的要求（uv 托管运行时） | 本期只读路径已验证无需托管运行时；写路径第三期先跑通托管启动 |
