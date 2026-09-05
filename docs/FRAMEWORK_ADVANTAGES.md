# 七个小说框架的优势、统计与 OpenWrite 定位

核查时间：2026-09-05 02:12（Asia/Shanghai）。本报告补充 [七项目源码核查](TARGETED_NOVEL_PROJECT_REVIEW.md)；
前一份报告回答“可借鉴什么”，本文集中回答“它们强在哪里、成熟度来自什么、我们处于什么位置”。

结论先行：

1. **ainovel-cli 的优势是状态机和因果恢复**：外部改稿、事实重建、派生物失效和旧稿导入形成可恢复流程。
2. **Scriverse 的优势是作者编辑闭环**：保存竞争、AI 写入审批、行级引用和上下文计量都有直接界面。
3. **OpenFic 的优势是通用 Agent 工作台产品化**：轮次变更、跨对象回滚、Agent 配置和索引新鲜度可见。
4. **CharacterArc 的优势是桌面写作完整度**：草稿恢复、查找替换、大纲拖动、AI 变更队列和项目档案围绕人工写作组织。
5. **MuMuAINovel 的优势是网文操作具体**：伏笔到期、分析建议到重写比较、项目导入导出都直接面向章节任务。
6. **InkOS 的优势是生产 Harness 的广度和上下文治理**：统一多种入口、标准 Skills、受保护上下文、可观测 trace 与多文件提交。
7. **Casting-Workflow 的优势是轻量和可拆解**：阶段提示、多来源融合及规则检查容易理解和改造；它不是完整运行时。

OpenWrite + dsh-novel 的现有优势是：**小说领域深度、评审/交付证据、Workspace 隔离，以及基于 dsh 的 Agent 编排。**
最明显差距集中在作者日常编辑体验、任意改稿后的事实联动、可恢复导入/完整归档和公开分发。

优势不是一条线上的总分，而是不同问题上的领先实现：

| 要解决的问题 | 本轮最强参考 | 优势来自什么 | OpenWrite/dsh 的位置 |
|---|---|---|---|
| 中断后为什么能安全继续 | ainovel-cli | 冻结提交、确定性路由、checkpoint 和派生物失效 | 写章运行已有状态机；任意改稿的因果接纳仍不完整 |
| 高频写作怎样避免丢稿和误覆盖 | Scriverse、CharacterArc | 请求稿快照、保存队列、恢复稿与持久版本分层 | 已有版本基础；自动保存竞态已经复现，缺恢复入口 |
| AI 到底改了什么、怎样撤回 | OpenFic、Scriverse | 整轮实体 diff、持久审批计划、版本复核和回滚 | 后端 revision/confirmation 较强；工作台仍以工具/路径摘要为主 |
| 长篇上下文怎样守住硬约束 | InkOS | 保护项不可静默压缩、来源/预算/检索 trace | 已有分级压缩和 manifest；估算器与可视化尚未统一 |
| 伏笔和评审怎样变成今天的动作 | MuMuAINovel | 到期/超期/待埋队列，建议→保留项→重写→比较 | DAG 和六域评审更深；日常章节操作入口较弱 |
| 作品怎样迁移到新机器/新路径 | CharacterArc、OpenFic | 模块清单、依赖补齐、ID 重映射、staging 恢复 | 已有导入、资产包和导出零件；缺统一可恢复项目档案 |
| 方法怎样低成本试验和传播 | Casting-Workflow | 少量脚本、显式阶段和可读输入/输出 | 能力更完整，但 71 个工具的学习和演示成本更高 |
| 质量如何形成可审计证据 | OpenWrite + dsh | 六域评审、覆盖/阻断/新鲜度分离、双 DAG、独立 reviewer | 是应保留并产品化的本地核心优势 |

## 1. 统计口径

原始快照：[framework-stats-2026-09-05.json](research/framework-stats-2026-09-05.json)。

- Stars、forks、watchers 来自 GitHub 仓库页面嵌入的 `sidebarAbout`，是会变化的关注指标，不是质量分。
- 源码统计使用 `git ls-files --cached --others --exclude-standard`；外部项目固定到表中 SHA，OpenWrite/dsh-novel 使用当前未提交工作树及所列 HEAD。
- “跟踪代码文件”包括 `py/go/ts/tsx/js/jsx/vue/mjs/cjs/rs/java/kt/kts/svelte`，包含测试；行数包含空行及仓库跟踪的生成式代码。
- “测试文件”按路径/文件名启发式识别；“用例”是 Python `test_*`、Go `Test*`、JS/TS `it/test`、Rust `#[test]` 的静态正则近似。
  没有运行这些测试；0 表示按此口径未找到，不证明项目完全没有其他形式的验证。

| 项目 | Stars | Forks | 跟踪代码文件（含测试） | 代码行（含测试） | 测试文件 | 近似测试声明 |
|---|---:|---:|---:|---:|---:|---:|
| [Casting-Workflow](https://github.com/dama-cyber/Casting-Workflow) | 577 | 107 | 6 | 1,610 | 0 | 0 |
| [ainovel-cli](https://github.com/voocel/ainovel-cli) | 1,919 | 398 | 323 | 73,339 | 119 | 785 |
| [Scriverse](https://github.com/musnows/Scriverse) | 192 | 38 | 480 | 157,084 | 285 | 1,461 |
| [OpenFic](https://github.com/syrizelink/OpenFic) | 993 | 112 | 1,168 | 233,610 | 198 | 1,694 |
| [CharacterArc](https://github.com/uu201/character-arc) | 548 | 82 | 348 | 111,242 | 39 | 143 |
| [MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel) | 2,956 | 577 | 259 | 108,229 | 0 | 0 |
| [InkOS](https://github.com/Narcooo/inkos) | 9,421 | 1,761 | 787 | 175,623 | 308 | 2,634 |
| [OpenWrite](https://github.com/LiPu-jpg/Openwrite) | 685 | 113 | 450 | 171,117 | 137 | 1,840 |
| [dsh-Openwrite](https://github.com/LiPu-jpg/dsh-Openwrite) | 0 | 0 | 85 | 23,731 | 14 | 121 |

可以从数字得到的有限结论：

- InkOS 的社区关注度显著领先，MuMuAINovel 和 ainovel-cli 次之。它们在安装入口、截图/文档、Web/桌面/TUI 等展示上更容易让新用户理解产品。
- OpenFic 的代码面最大；InkOS 的静态测试声明最多。规模也可能来自功能面、技术栈、重复代码或生成文件，不能据此判定架构更好。
- OpenWrite 与 dsh-novel 合计约 **535 个跟踪代码文件、194,848 行、151 个测试文件、约 1,961 个测试声明**。
  在这组项目中不是“小脚本”，其工程和测试体量已经接近大型项目；两个仓库合计与单仓库数字不能作严格排名。
- Casting-Workflow 的关注度远高于代码体量，说明简单、可理解的工作流也有传播价值；其缺失模板和语料使“关注”不能转化为可复现完整性。
- MuMuAINovel 在本口径下没有匹配测试文件，但它的产品功能有真实代码入口；只能记录自动化证据可见度较弱，不能推导运行质量。
- dsh-novel 是拆出的插件仓库，当前社区数字几乎没有形成。可靠性完成后，需要明确兼容版本、安装演示、功能截图、样例流程和发布记录。

## 2. 功能成熟度矩阵

这不是总分表：

- **●**：在固定源码中找到实现、数据契约和调用入口；没有运行验证。
- **◐**：有组成部分，但存在已确认边界，或没有形成统一作者流程。
- **—**：在本轮明确核查范围未找到对应实现；不等于全仓库绝对不存在。
- **?**：本轮没有足够源码证据，不作判断。

### 引擎、状态和长篇一致性

| 项目 | 可恢复流程/检查点 | 上下文治理 | 任意改稿后事实联动 | 质量审阅与交付证据 |
|---|:---:|:---:|:---:|:---:|
| Casting-Workflow | ◐ | ◐ | — | ◐ |
| ainovel-cli | ● | ◐ | ● | ◐ |
| Scriverse | ◐ | ◐ | ? | ◐ |
| OpenFic | ● | ● | ◐ | ? |
| CharacterArc | ◐ | ? | ? | ? |
| MuMuAINovel | ◐ | ● | ◐ | ◐ |
| InkOS | ● | ● | ◐ | ● |
| OpenWrite + dsh | ● | ◐ | ◐ | ● |

这里的关键不是填满圆点：

- OpenWrite 对框架内写章已经有 Chapter Run V2、状态结算、异常回滚；缺的是**任意手工/外部改稿的统一接纳链路**。
- OpenWrite 已有分级压缩和 context manifest；“◐”来自 token 估算不一致、极端路径可能裁剪核心内容、dsh 面板未完整展示实际来源与压缩结果。
- OpenWrite 的六域累加评审、覆盖率、硬门禁、review/delivery DAG 和独立 reviewer 横评，是本组对照中证据结构最完整的能力之一。
- InkOS 的正文编辑会归档旧稿、替换正文并让运行状态进入待重审，但本轮没有找到等同 ainovel-cli 的 accepted-SHA、事实重算和跨章派生级联，因此“任意改稿后事实联动”只记为“◐”。
- InkOS 的圆点表示所读源码覆盖面广；尚未运行其端到端故障恢复或验证长篇质量，不能变成“总体更好”的结论。

### 作者工作台和作品可携带性

| 项目 | 草稿/保存保护 | AI 变更 diff/采用 | 可恢复旧稿导入 | 完整项目档案 | 小说专用操作界面 |
|---|:---:|:---:|:---:|:---:|:---:|
| Casting-Workflow | — | — | — | — | — |
| ainovel-cli | ? | ◐ | ● | ◐ | ◐ |
| Scriverse | ● | ● | ? | ? | ● |
| OpenFic | ◐ | ● | ? | ? | ● |
| CharacterArc | ● | ● | ? | ● | ● |
| MuMuAINovel | ◐ | ● | ◐ | ◐ | ● |
| InkOS | ◐ | ● | ? | ? | ● |
| OpenWrite + dsh | ◐ | ◐ | ◐ | ◐ | ◐ |

OpenWrite/dsh 的“◐”有明确含义：很多后端组件已经存在，但作者入口尚未闭合。
自动保存一项还存在已复现的竞态，不能用已有编辑器界面抵消；修复优先级仍为 P0。

## 3. 每个外部框架最真实的优势

### Casting-Workflow：可理解、可修改、低进入成本

优势来自小而直接：阶段映射、前序输出发现、提示组装、来源融合和规则扫描都能在少量 Python 文件中读完。
对于验证新的创作方法，它比搭建完整 Agent runtime 更快；不同来源并列呈现，也比直接混成一个“风格向量”更容易让作者检查。
[阶段映射](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/run_pipeline.py#L40)、
[来源融合](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/tools/fusion.py#L162)

适合我们学习：把复杂能力做成可读的阶段卡和明确输入/输出，不让 71 个工具成为用户需要理解的菜单。
其模板/语料缺失、字符截断和抽样原创检查决定了它只能作为方法原型，不能替代 OpenWrite 的来源隔离、版本和评审体系。

### ainovel-cli：把“为什么能继续”写进状态机

它的优势不是 Agent 数量，而是确定性路由、冻结提交、checkpoint stop guard 和派生工件因果。
恢复时沿用第一次保存的请求内容；外部正文改动基于 accepted SHA 发现，事实重建后明确失效摘要、审阅与后续计划。
旧稿导入也拥有源快照、分章、逐章事实、综合和发布的阶段工件。
[路由](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/flow/router.go#L90)、
[改稿接纳](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/revision/service.go#L112)、
[导入状态](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/host/imp/state.go#L25)

路由的价值还有可穷举性：其静态测试枚举 5,000 多种状态组合，guard 阻止没有必要工件时提前结束，并检测连续
无进展。运行事件记录 agent、深度、重试、usage/cache；诊断导出主动去掉正文、Prompt 和 thought，eval runner
可以隔离比较 prompt variant、成本与工具调用。
[状态穷举](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/flow/router_exhaustive_test.go#L211)、
[脱敏诊断](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/diag/export.go#L14)、
[实验运行器](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/eval/runner.go#L17)

适合我们学习：为 Chapter Run V2 增加所有正文入口的事实基线和依赖传播；让导入沿相同恢复协议运行。
还应把现有 benchmark 扩展为可复现的 prompt variant 实验。其流程较刚性，单文件原子写仍有跨文件硬杀窗口，
导入仅限空书 TXT/Markdown，评测 judge 仍有规划项。

### Scriverse：作者看得到每次保存和 AI 写入发生了什么

它直接处理编辑器最难的日常边界：在途保存时固定 draft，继续输入后自动排队；响应回来核对作品和章节身份。
AI 写入是带 before/after、目标版本、确认/拒绝/撤销的计划，稳定行 ID 帮助批注在编辑后重新定位。
上下文计量还分解 system、functions、skills、input、output 和 remaining。
[保存状态机](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/public/app.js#L6757-L6843)、
[AI 计划](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/ai-write-plans.ts#L2021-L2157)、
[行身份](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/public/chapter-line-id-tracker.js#L87-L150)

这套审批不只是前端弹窗：服务端用状态条件更新抢占执行权，再复核确认者、工具权限和对象版本，最后在 SQLite
事务内执行；重复确认不会重复写，部分更新还能生成一条新的待确认撤销计划。分析任务还可保存逐轮模型请求、响应、
工具调用、token 来源类型和脱敏 request trace，适合定位“用了什么上下文才得到这次结果”。
[执行前复核](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/ai-write-plans.ts#L2018-L2155)、
[调用 trace](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/ai.ts#L10215-L10305)

适合我们学习：先把现有 OpenWrite revision/version/context manifest 变成作者闭环。
边界是官方浏览器外仍可不传 `expectedVersionNo`，远程 MCP 工具也不经过同一审批链；其大型 `app.js`/`ai.ts`
表明功能集中度较高，借鉴状态不变量比移植代码结构更合适。

### OpenFic：通用 Agent 工作台已经产品化

OpenFic 把一次 Agent 轮次影响的章节、笔记、人物和世界条目汇总成真实 diff，并能恢复到某条用户消息前。
检索明确暴露 fresh/stale/needs_rebuild/no_index；哈希、Embedding 模型/维度和分块版本决定索引是否可信。
Agent 定义可组合 prompt、模型、工具类别、skills 和委派对象，适合不同工作方式而不重写前端。
[变更面板](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/frontend/src/features/assistant/components/agent/agent-changes.tsx)、
[恢复服务](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/agent_runtime/revisions.py#L843-L1225)、
[索引新鲜度](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/agent_runtime/tools/impls/chapter/search_chapters.py#L159-L365)

它在普通写作面也有值得学的闭环：本地工作副本与远端稿按时间戳决定恢复，保存捕获请求时稿件；多章节/笔记标签
可拖排、锁定并加入对话上下文。TXT、Markdown、ZIP 导入先预览卷章结构再显示流式进度；桌面备份按文件记录
大小和 SHA-256，恢复先进入 staging，失败尝试 rollback 副本。
[工作副本决策](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/frontend/src/features/writing/lib/writing-working-copy.ts#L23-L80)、
[导入向导](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/frontend/src/features/projects/components/import-dialog.tsx#L163-L242)、
[备份清单](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/desktop/src/main/backup-manifest.ts#L7-L78)

适合我们学习：将 TurnMutationSummary 从工具/路径提升为真实变更与恢复入口，并把已有索引 revision 展示给作者。
dsh 已经承担通用 Agent runtime；本地无需复制 OpenFic 的运行时。其轮次回滚未见“实体仍等于本轮写后版本”的
前置校验，稿件导入也不等于完整项目迁移；百万字性能没有公开基准，本轮未实测。

### CharacterArc：人工写作为中心的桌面完整度

它把草稿恢复、查找替换、大纲多选/跨卷移动、AI 待应用变更和项目归档放在同一桌面产品里。
`.carc` 档案实际携带正文、版本、人物关系、大纲、工作流文档、AI 记录和参考文本；可选导入还处理依赖和 ID 重映射。
[草稿恢复](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/renderer/src/components/chapterWorkspace/SimpleChapterEditor.vue#L37-L96)、
[变更队列](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/electron/main/ai/runtime-v2/staged-changes-store.ts#L305-L374)、
[项目档案](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/electron/main/archive/project-archive.ts#L535-L574)

它把崩溃恢复稿与正式章节版本分成两层：前者按章节留在本机并在切章/卸载前刷新，后者由作者保存、比较并确认恢复。
AI 变更也逐项接受、拒绝、绑定目标和重试，适合让作者知道“恢复未保存输入”和“回到一个正式版本”是两件事。
[历史版本比较](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/renderer/src/components/chapterWorkspace/ChapterVersionDialog.vue#L24-L86)、
[变更审阅界面](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/renderer/src/components/assistantV2/StagedChangesView.vue#L188-L327)

适合我们学习：AI 能力必须落回普通编辑、搜索、移动、恢复和迁移任务。
它的批量变更允许部分成功，项目导入也分阶段执行；缺失参考文件会跳过，macOS 包未公证。“可打包”不能直接
等同于原子事务、无损备份或全平台稳定。

### MuMuAINovel：网文作者任务被做成具体操作

MuMu 的优势是领域动作可见：本章必须回收、已经超期、近期参考和待埋入伏笔分别展示；
评审建议可以勾选，加入自定义要求/保留元素，生成后并排或统一 diff 再应用。
项目 JSON 导入先验证并显示选项，形成比“上传一个文件”更明确的入口。
[伏笔上下文](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/backend/app/services/foreshadow_service.py#L713-L800)、
[重写输入](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/frontend/src/components/ChapterRegenerationModal.tsx#L64-L105)、
[内容比较](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/frontend/src/components/ChapterContentComparison.tsx#L156-L186)

导入端还会在创建新项目之前校验版本和必填项、统计模块，随后在数据库事务中重建实体映射；Docker Compose
提供 PostgreSQL 依赖健康检查、持久卷和应用健康检查。这使它更接近可自托管的多人 Web 服务形态。
[导入事务](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/backend/app/services/import_export_service.py#L689-L867)、
[部署定义](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/docker-compose.yml#L1-L24)

适合我们学习：从“拥有伏笔 DAG/六域评审”推进到“这一章现在该处理哪一项”。
其伏笔服务会把异常吞成空列表，局部重写应用未校验源版本，项目导出默认省略部分数据且历史限 100 条；
这些边界不应复制，Web/PostgreSQL 部署形态也不适合直接移入本地插件。

### InkOS：统一 Harness、上下文治理和多形态入口

InkOS 把 Studio Chat、TUI、CLI 与生产 worker 收敛到同一个工具循环；标准 `SKILL.md` 提供专业规则，
确定性工具仍管理权限、确认和落盘。上下文将作者意图、当前焦点、硬状态和活跃伏笔列为保护项；
保护项超预算就停止，不用压缩它们换取一次模型调用。trace 保存来源、理由、预算、压缩和检索候选。
正文、状态与伏笔通过暂存/备份/替换的文件集提交，代码含故障回滚路径。
[上下文保护](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/agents/composer.ts#L160-L218)、
[trace 契约](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/models/input-governance.ts#L90)、
[文件集提交](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/utils/atomic-file-set.ts)

它还有一个容易忽略的恢复边界：会话以 schema 化 JSONL 串行追加，恢复时只重放属于 `request_committed` 的消息；
已经完成的工具活动会变成不可执行摘要，避免恢复聊天时再次触发工具副作用。
[会话转录](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/interaction/session-transcript.ts#L53)、
[恢复规则](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/interaction/session-transcript-restore.ts#L343)

适合我们学习：定义硬约束并全链保护，提供同一领域内核的清晰入口和 trace。
OpenWrite/dsh 已有 dsh Harness 和领域工具，无需更换 Agent runtime；所读多文件 helper 没有 fsync/持久 journal，
外层索引与审计也分步保存，会话提交更不等于领域数据提交，不能称为整个业务的断电一致事务。

## 4. OpenWrite/dsh 自己已经更强的地方

### 领域评审与交付证据

六个质量域保留 37 项查询，质量、覆盖率、阻断、评审新鲜度和交付状态分离；Review DAG 与 Delivery DAG
能追踪证据、修订和复评。横评在隔离作品沙箱运行 writer × independent reviewer，保留上下文 hash、真实 token/费用和失败来源。
这是比“生成后给一个分数”更严谨的基础。
[当前契约与证据](../GOAL.md)、[bridge 领域工具](../packages/openwrite-bridge/src/tools.ts)

### 长篇领域资产和来源隔离

OpenWrite 已有四级大纲、角色/世界/正典、伏笔 DAG、状态结算、分级上下文压缩、来源分析、
风格综合、参考资料采用预览及非正典多分支推演。外部框架的单点亮点应接入这些现有对象，不另建第二套状态。
[ContextBuilder](../../OpenWrite/tools/context_builder.py)、[参考资料库](../../OpenWrite/tools/reference_library.py)、
[剧情推演](../../OpenWrite/tools/narrative_forecast.py)

### Workspace 隔离与 dsh 编排

每个 dsh Workspace 映射独立 OpenWrite 应用实例，任务、锁、revision、SSE 和浏览器状态按 canonical root 隔离；
浏览器不直接提供路径。dsh 已提供会话、技能、子代理、长期上下文和工具执行，因此领域插件可以保持薄桥接。
[Workspace 契约](WORKSPACE_CONTEXT_CONTRACT.md)、[架构设计](../DESIGN.md)

### 工程验证基础

现有两仓库已经有生成契约、schema parity、Python/TypeScript DoG 一致性、组件、epoch、生命周期、
临时 profile 安装以及真实服务/E2E 分层。静态数量不能证明测试正确，但说明完善工作可以在已有门禁上迭代。
[插件维护手册](PLUGIN_MAINTENANCE.md)、[验证日志](../GOAL.md)

## 5. 调研对实施优先级的修正

这次深入比较后，[完善计划](IMPROVEMENT_PLAN.md) 的顺序仍成立，但每项借鉴来源更明确：

| 优先级 | 应落实的优势 | 主要参考 | 本地交付 |
|---|---|---|---|
| P0 | 保存快照、队列、文档身份、草稿恢复 | Scriverse、CharacterArc | 修复已复现竞态；刷新/离线/切 Workspace 可恢复 |
| P1 | 受保护上下文、真实预算和来源 trace | InkOS、OpenFic、Scriverse | 统一 token 估算；保护硬约束；展示来源/压缩/索引状态 |
| P1 | AI 变更的真实 diff、逐项采用和历史 | Scriverse、OpenFic、CharacterArc、MuMu | 版本历史、修订比较、轮次变更；服务端保证选择内容 |
| P1 | 改稿接纳、因果失效和恢复 | ainovel-cli、InkOS | 覆盖手工/Agent/历史/外部编辑；摘要、评审、计划不再悄悄过期 |
| P2 | 可恢复导入和完整项目档案 | ainovel-cli、CharacterArc | 导入工作区、版本化 manifest、新路径恢复验证 |
| P2 | 章节任务导向的日常工作台 | MuMu、CharacterArc | 到期伏笔、搜索回跳、排序、连续审读、目标统计 |
| P3 | 场景实体与阅读/时间双序 | 前次 StoryLine/Plot Bunni 对照 | 稳定 scene ID、迁移、引用与导出顺序 |
| 可靠性稳定后 | 公开分发和社区入口 | InkOS、MuMu、OpenFic | 成对版本说明、一键安装演示、截图、示例项目、发布/升级记录 |

产品定位建议：**用 dsh 提供通用 Agent 能力，用 OpenWrite 提供可验证的小说领域状态，用工作台把复杂能力变成作者动作。**
核心竞争力应是“长篇能持续修改并解释影响”，而不仅是一次生成更多字或罗列更多工具。

## 6. 不能由本轮统计回答的问题

- 哪个项目写出的小说更好：需要同一提示、同一模型、盲评、长篇连续性与人工标签；Stars、测试数量和 README 都不能回答。
- 哪个项目运行最稳定：需要实际安装、故障注入、强杀/恢复、跨平台和长文本测试；本轮只读源码。
- 哪种上下文策略成本最低：需要固定模型 tokenizer、相同材料与调用遥测；当前只能比较算法和可观测性。
- 哪个许可证适合具体复用：本报告记录快照，不代替对目标代码、依赖和分发方式的逐项审查。

因此本报告使用实现/部分/未确认矩阵，没有给主观总分。下一步开发仍从可确定验收的保存、计量和版本闭环开始。
