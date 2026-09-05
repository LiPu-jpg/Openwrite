# 用户指定的七个小说项目：源码核查与改进建议

核查日期：2026-09-05。承接 [通用小说工具调研](OPEN_SOURCE_NOVEL_AUDIT.md)，本轮只研究用户指定的七个仓库，并对照当前 dsh-novel / OpenWrite 工作树。

项目归属（用户确认）：[OpenWrite Core](https://github.com/LiPu-jpg/Openwrite/tree/native-core) 是本团队自己的核心项目；
`dsh-novel` 是 OpenWrite 的 DeepSeek Harness 插件版本，两者共同构成此次完善对象。
下文七个仓库是外部参考，OpenWrite 是自有基线。评估时区分“核心已有、插件尚未接入”和“核心本身需要增强”。

| 改进落点 | 对应职责与本轮实例 |
|---|---|
| OpenWrite 核心 | 小说领域数据与业务规则：统一 token 估算、上下文约束保护、正文事实接纳、导入恢复与项目归档 |
| dsh-novel bridge / 预设 | 将核心能力接入 dsh 工具与创作流程：请求/响应契约、revision、Workspace 隔离、失效通知与领域动作暴露 |
| dsh-novel 工作台 | 作者操作：自动保存竞态修复、版本/diff/恢复入口、上下文检查、伏笔到期清单与编辑导航 |

实现可跨两仓库配合，领域能力仍维护在 OpenWrite 中；工作台未展示某能力，不代表 OpenWrite 没有该能力。

**结论：优先参考 Scriverse 的保存与变更审阅、ainovel-cli 的改稿接纳与导入恢复、InkOS 的上下文保护。**
OpenFic、CharacterArc、MuMuAINovel 分别补充轮次回滚、项目档案和伏笔/修订工作台的具体设计。
Casting-Workflow 可参考阶段组织，但其公开资源不足以直接完成 README 所描述的全流程。

本轮修正前一轮“主要是界面差距”的判断：界面仍是明显短板，但还要核验正文改动后的事实联动、
长任务半完成恢复和不可裁剪的创作约束。这些涉及业务契约，不能只靠增加面板解决。

证据等级：以下“已实现”指找到实际源码及调用入口；七个仓库均已浏览并在临时目录浅克隆。
没有安装依赖、执行上游程序、运行上游测试或调用模型，不能据此给出生成质量排名或稳定性保证。
本地对照以未提交工作树为准，不把旧 README 或当前 Git HEAD 当作全部现状。

## 1. 固定核查快照

日期统一按北京时间列出；版本取源码包元数据或提交记录，不等同于已验证的发行包。

| 项目 | 固定提交 / 日期 | 许可与形态 | 当前状态的实际含义 |
|---|---|---|---|
| Casting-Workflow | [`2e1eae2026c546ee6ab0235ead8dfb00def12e60`](https://github.com/dama-cyber/Casting-Workflow/tree/2e1eae2026c546ee6ab0235ead8dfb00def12e60) / 06-23 | README 声明 MIT，树中未见独立 LICENSE；Python 提示组装脚本 | 公开树跟踪 11 个文件，缺少调用所需的阶段模板和所述语料，不是完整自动写作应用 |
| ainovel-cli | [`47df100f25ab7e6460db526cacb38329b6c36549`](https://github.com/voocel/ainovel-cli/commit/47df100f25ab7e6460db526cacb38329b6c36549) / 09-04 | [Apache-2.0](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/LICENSE)；Go TUI / headless | 本轮为主分支快照；确定性引擎、角色工具与持久工件均有实现，最新提交修复骨架弧读取 |
| Scriverse / 叙界 | [`e5ddeced886a5a38aa543fe6c807346b72d84f41`](https://github.com/musnows/Scriverse/commit/e5ddeced886a5a38aa543fe6c807346b72d84f41) / 09-04 | 当前 [AGPL-3.0-only](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/package.json)；Node / Express / SQLite / Web，另有 CLI 和 Docker | main 包版本 1.0.1；README 仍称 MVP、数据结构可能变化，不能以版本号推断接口稳定 |
| OpenFic | [`809a071e34ed651e5177f31ac1b8a461a589edab`](https://github.com/syrizelink/OpenFic/commit/809a071e34ed651e5177f31ac1b8a461a589edab) / 09-04 | [Apache-2.0](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/LICENSE)；FastAPI / React，另有 Electron 构建 | [0.11.0，Python 元数据仍为 Alpha](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/pyproject.toml)；有桌面配置不等于各平台安装已验收 |
| CharacterArc | [`1a81dca0af259f8912cdc745f15848dc8c6ca876`](https://github.com/uu201/character-arc/commit/1a81dca0af259f8912cdc745f15848dc8c6ca876) / 08-31 | [MIT](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/LICENSE)；Electron / Vue / SQLite | [1.18.5](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/package.json)，近期有缺陷修复；桌面写作与档案管理是主要参考面 |
| MuMuAINovel | [`600be7038539e4dd0568b63e6e534fdcfaf91687`](https://github.com/xiamuceer-j/MuMuAINovel/commit/600be7038539e4dd0568b63e6e534fdcfaf91687) / 08-31 | [GPL-3.0](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/LICENSE)；FastAPI / React / PostgreSQL 部署 | 此提交更新 1.5.5；README 的 TODO 区有大量已勾选项，须按代码而非标题判断完成度 |
| InkOS | [`091048383f411eb99948a8764f42b6fd13006f9b`](https://github.com/Narcooo/inkos/commit/091048383f411eb99948a8764f42b6fd13006f9b) / 08-26 | [AGPL-3.0-only、1.8.0](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/package.json)；TypeScript monorepo，Studio / TUI / CLI | 已有 pi-agent、领域流水线与多种创作形态；本轮聚焦长篇和工程边界，不评价其他形态的生成效果 |

上述许可按本次快照记录。本轮没有复制上游代码；引入具体实现前仍需按目标文件和版本核对复用条件。

## 2. 七个项目分别值得学什么

### Casting-Workflow：阶段契约与多来源比较，不能照搬其质量承诺

- `run_pipeline.py` 将阶段映射到模板与前序文件，并组装提示后交由用户手动调用 LLM。可学每阶段的输入/输出展示，但它没有模型 API 执行器，也没有基于内容版本的过期检测。[阶段定义](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/run_pipeline.py#L40)
- `fusion.py` 并列展示多个来源的特征，提示模型归纳共性和独有设定；适合借鉴“共同技法 / 来源差异 / 不应迁移的设定”界面。所谓公约数由模型判断，代码本身没有计算语义交集。[来源组装](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/tools/fusion.py#L162)
- 当前公开 `prompt/` 只有映射文档，所需模板缺失会直接退出；前序文本与语料分别截取前 2,000 / 3,000 字符。其原创审计是抽样子串比对，不能证明“100% 原创”，也不是外部检测服务的接入。[缺失模板处理](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/run_pipeline.py#L419)、[截取逻辑](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/run_pipeline.py#L164)、[审计实现](https://github.com/dama-cyber/Casting-Workflow/blob/2e1eae2026c546ee6ab0235ead8dfb00def12e60/tools/audit.py#L61)

本地已有 source analysis、reference-library、风格综合与确认采用。保留这些边界，优先增强来源比较和采用预览，不能退回原文片段拼接。

### ainovel-cli：最值得深入学习改稿后的事实接纳与可恢复导入

- 正文提交先固定提交意图、规范化参数和正文快照；恢复沿用首次固定的内容。路由函数根据状态决定下一步，执行与判断分开。可用来审视本地 Chapter Run V2 的重放与半提交窗口。[提交实现](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/tools/commit_chapter.go#L212)、[路由](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/flow/router.go#L90)
- 用已接纳的正文 SHA 扫描磁盘改动；分析后再次检查 SHA，再接纳修改、重建事实投影、使高层摘要和审阅失效，并给后续规划反馈。这比“正文保存成功”更接近长篇连续性所需的完整业务流程。[扫描](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/revision/scan.go#L22)、[接纳服务](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/revision/service.go#L112)
- 旧稿导入单独经过源快照、语义切分、确认、逐章事实、全书综合、发布，步骤绑定输入指纹；未完成发布阻止正常创作消费半成品。当前只导入空书、支持 TXT/Markdown，不能当作任意作品合并器。[导入状态机](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/internal/host/imp/state.go#L25)

边界：单文件原子写不等于所有动作都是跨文件事务，架构文档也承认部分硬杀/并发输入窗口。
评测文档中的 `--judge`、`--no-judge` 和人工评审层仍属规划；不要据此认定其评审已强于本地独立 reviewer 横评。
[架构边界](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/docs/architecture.md#L370)、[评测规划](https://github.com/voocel/ainovel-cli/blob/47df100f25ab7e6460db526cacb38329b6c36549/docs/evaluation-system.md#L379)

### Scriverse：保存状态机、可审阅写入和稳定正文引用

- `persistChapter` 固定本次 draft、等待在途请求、响应后核对作品/章节身份，只把该快照记为已保存；若当前输入不同则再次排队。它直接提供了本地 autosave 缺陷的设计参考，但本轮未运行该应用，不能保证它所有边界均无缺陷。[保存实现](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/public/app.js#L6757-L6843)
- AI 写入先成为有 before/after 的计划；执行前重新检查目标版本和权限，批量操作进入数据库事务。确认、拒绝、撤销有实际界面接线，适合把本地修订 JSON 变成操作流程。[计划执行](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/ai-write-plans.ts#L2021-L2157)、[界面](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/public/app.js#L3275-L3346)
- 稳定行 ID 随编辑调和，批注按身份映射；另有插空行和重复行删除测试。可学评审证据在修稿后怎样重定位；不应把行号或字符串命中当作永久可靠定位。[行身份](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/public/chapter-line-id-tracker.js#L87-L150)、[测试源码](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/tests/unit/chapter-line-id-tracker.test.ts)

其上下文计量 UI 分开 system、tools、skills、input、output 与 remaining，也可借鉴。
当前浏览器 `app.js` 约 2.1 万行、`ai.ts` 约 1.7 万行；宜提取设计不变量，保持本地模块边界，避免整块移植。
[计量展示](https://github.com/musnows/Scriverse/blob/e5ddeced886a5a38aa543fe6c807346b72d84f41/src/public/ai-context-meter.js)

### OpenFic：把每轮 AI 的实际改动与索引状态交给作者检查

- 变更面板覆盖章、笔记、世界条目与人物，提供行级/并排 diff；可回滚到用户消息前。后端不仅恢复业务快照，也处理会话附件、压缩记录和子运行检查点边界。[变更面板](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/frontend/src/features/assistant/components/agent/agent-changes.tsx)、[回滚服务](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/agent_runtime/revisions.py#L843-L1225)
- 检索显式区分 fresh、stale、needs_rebuild、no_index；正文哈希、Embedding 模型/维度和分块版本参与判断。无索引/需重建不能强行查询；stale 默认拒绝，可以明确 force。值得学的是作者看得懂的状态与修复方式。[查询策略](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/agent_runtime/tools/impls/chapter/search_chapters.py#L159-L365)
- 分块优先保留段落，再用中英文句界切分；上下文组装与会话压缩单独成模块。这有助于把来源、正文定位与压缩结果显示清楚。[分块器](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/retrieval/internal/indexing/chunking.py)、[上下文组装](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/agent_runtime/context/build_context.py)

边界：本轮没有验证“百万字级”检索表现；本地存储也不代表离线，除了模型调用还有默认开启、可关闭的错误遥测。
本地已有检索索引、源 revision、失效与自动同步机制，不应重建第二套 RAG 或把 OpenFic 的 Agent runtime 搬进 OpenWrite。
[遥测配置](https://github.com/syrizelink/OpenFic/blob/809a071e34ed651e5177f31ac1b8a461a589edab/backend/app/telemetry.py#L20-L53)

### CharacterArc：写作恢复、待应用变更和可携带项目档案

- 编辑器按章节保存本地恢复快照，和持久正文比较后提供恢复；有查找、前后跳转、单次/全部替换。另有大纲多选跨卷移动。这里证明的是大纲排序，不能直接推断为完整场景模型。[草稿恢复](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/renderer/src/components/chapterWorkspace/SimpleChapterEditor.vue#L37-L96)、[排序核心](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/renderer/src/features/workspace/outlineReorder.ts)
- AI 待写入变更有接受/拒绝/提交状态；只写入已接受项，失败保留重试；UI 区分部分失败与“写入成功、刷新失败”。可补本地作者控制感与真实状态反馈。[变更队列](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/electron/main/ai/runtime-v2/staged-changes-store.ts#L305-L374)、[界面反馈](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/renderer/src/components/assistantV2/GlobalAssistantV2Panel.vue#L157-L173)
- `.carc` 档案打包正文、版本、角色关系、大纲、工作流文档、AI 记录和参考文本；导入可选择模块，补依赖并重映射 ID。比纯正文导出更接近项目迁移。[归档实现](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/electron/main/archive/project-archive.ts#L535-L574)、[导入依赖](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/electron/main/archive/project-archive.ts#L658-L666)

边界：归档代码遇到缺失参考原文会跳过，不能用“导出成功”证明全部资源已备份；本地实现应明确列出缺项。
其测试脚本包含 Windows shell 写法，macOS 文档说明未公证；存在打包脚本不代表跨平台验证已完成。
[包脚本](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/package.json)、[macOS 说明](https://github.com/uu201/character-arc/blob/1a81dca0af259f8912cdc745f15848dc8c6ca876/README.md#L215-L225)

### MuMuAINovel：把评审建议与伏笔管理连接到当前章节

- 伏笔上下文分为本章到期、超期、近期参考和待埋入，工作台提供计数与提示。本地已有伏笔 DAG 和目标章节，差距在“本章要处理什么”的直接操作入口。[上下文构造](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/backend/app/services/foreshadow_service.py#L713-L800)、[工作台](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/frontend/src/pages/Foreshadows.tsx#L547-L560)
- 从分析结果勾选修改建议、补自定义要求和保留元素，再生成并对比应用。这正适合连接本地六域评审与修订服务。[修改输入](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/frontend/src/components/ChapterRegenerationModal.tsx#L64-L105)、[比较界面](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/frontend/src/components/ChapterContentComparison.tsx#L156-L186)
- 项目 JSON 导入有验证与独立项目恢复入口。可学导入前的内容统计、错误和警告，但默认不含历史/记忆/分析，历史选中后仍最多导出 100 条，不能称无损全库备份。[默认选项](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/backend/app/schemas/import_export.py#L7-L13)、[历史限制](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/backend/app/services/import_export_service.py#L420-L427)

不要照搬其局部重写提交保护：所读接口只检查偏移范围后拼接当前正文，未检查生成所依据的源版本。
本地应保留 revision 与原文匹配检查。其 Docker 构建删除 lockfile 后运行 npm install，也不宜沿用为可重复构建策略。
[局部应用接口](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/backend/app/api/chapters.py#L5210-L5228)、[构建定义](https://github.com/xiamuceer-j/MuMuAINovel/blob/600be7038539e4dd0568b63e6e534fdcfaf91687/Dockerfile#L23-L27)

### InkOS：保护创作约束，记录上下文来源与提交边界

- Composer 将上下文分为受保护与可压缩内容；当作者意图、当前焦点、硬状态、活跃伏笔等保护项本身超预算时明确报错，不继续压缩这些项。trace 保存来源、理由、预算、压缩与检索候选，适合借鉴为可检查的创作输入契约。[预算处理](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/agents/composer.ts#L160-L218)、[保护源定义](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/utils/context-assembly.ts#L126-L151)、[trace 模型](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/models/input-governance.ts#L90)
- 记忆、资料和 skill 参考共用可重建的 SQLite FTS5/BM25 投影；源文件保持权威，段落有位置，中文分词考虑相邻汉字组合。可学统一来源和索引可重建性，不意味着词法检索应替代本地所有语义检索。[检索内核](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/retrieval/local-search.ts)
- Writer 把正文、状态、伏笔及相关结构化文件组装为一次文件集提交；辅助函数先暂存、备份再替换，错误时回滚，测试源中有第二次替换失败的故障注入。[Writer 提交](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/agents/writer.ts#L663-L723)、[文件集实现](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/utils/atomic-file-set.ts)、[故障测试](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/__tests__/atomic-file-set.test.ts#L56)

边界：上述是某个文件集的异常回滚，外层索引/快照还分步持久化；不能直接等同于整个业务的崩溃一致事务。
本轮未运行故障测试，也未验证强杀/断电恢复。多种作品形态和 pi-agent 的采用本身不证明长篇质量优于现有框架。
[外层持久化](https://github.com/Narcooo/inkos/blob/091048383f411eb99948a8764f42b6fd13006f9b/packages/core/src/pipeline/chapter-persistence.ts)

## 3. 对照本地：保留哪些能力，具体补哪里

| 能力 | 当前已经有 | 待补或待核验的真实差距 |
|---|---|---|
| 写章/恢复/评审 | [Chapter Run V2](../../OpenWrite/tools/chapter_run_v2.py)、[章节 pipeline](../../OpenWrite/tools/chapter_pipeline.py) 有阶段、输入版本、产物和异常回滚；本地还有独立 reviewer、DoG 证据 | 借 ainovel-cli / InkOS 核验冻结提交内容、半提交恢复、重复执行与跨文件一致性；不新增第二个 Agent 引擎 |
| 正文保存 | [CreationView](../packages/studio-panel/src/client/CreationView.tsx) 有自动保存和冲突状态 | 前轮已复现请求期间新输入被误标 saved；优先参考 Scriverse 的请求快照/排队，再加 CharacterArc 式恢复入口 |
| 正文改动后的事实 | [版本存储](../../OpenWrite/tools/manuscript_editing.py)、[修订服务](../../OpenWrite/tools/revision_service.py)、[源同步](../../OpenWrite/tools/source_sync.py) 已有版本/失效处理 | 未发现覆盖任意外部正文变更、事实接纳、跨章派生物失效和续写检查的完整等价链路；须进一步核验所有正文写入口 |
| AI 改动审阅 | [TurnMutationSummary](../packages/studio-panel/src/client/TurnMutationSummary.tsx) 已汇总工具与目标路径；后端已有修订/确认 | 增加真实 before/after、源 revision、逐项采用和历史入口；轮次回滚必须处理后续修改冲突，不只是撤回聊天消息 |
| 上下文/检索 | [ContextBuilder](../../OpenWrite/tools/context_builder.py)、[manifest](../../OpenWrite/tools/context_manifest.py)、[project_search](../../OpenWrite/tools/project_search.py) 已有压缩、来源、索引同步和内容版本 | 统一估算器，定义不能静默裁剪的约束；展示来源、压缩、过期与索引刷新状态，不再造 RAG |
| 旧稿导入/拆书 | [novel_workspace](../../OpenWrite/tools/novel_workspace.py)、[source_analysis](../../OpenWrite/tools/source_analysis.py)、[reference_library](../../OpenWrite/tools/reference_library.py) 已有切分/分析/采用；bridge 有导入和回填 | 将已有步骤连接成带源快照、确认、逐步恢复和发布状态的完整导入工作区，尤其覆盖非规范标题与中断 |
| 剧情和伏笔 | [narrative_forecast](../../OpenWrite/tools/narrative_forecast.py) 已有非正典分支与过期判断；[GraphView](../packages/studio-panel/src/client/GraphView.tsx) 已有伏笔看板 | 增加本章到期/超期的直接行动入口和上下文去向，避免重复创建 DAG 或分支模型 |
| 迁移与备份 | 稿件导出和 [asset_package](../../OpenWrite/tools/asset_package.py) 已有 | 学 CharacterArc 的全项目清单、模块依赖与 ID 映射，并明确缺失文件、历史范围、任务迁移与恢复验证 |

### 新确认的本地实现问题：上下文 token 估算不一致

`tools/context_manifest.py` 的 `build_context_manifest` 用 `len(rendered) / 1.5`。
`models/context_package.py` 的 `estimate_text_tokens` 对中文用 `字数 × 1.5`，英文/其他字符用 `× 0.25`。
本轮用实际函数处理同一份 1,500 个“中”字，得到：

```text
字符数                 1500
manifest 估计 tokens   1000
写作预算估计 tokens    2250
```

这是两个估算函数口径不一致的确定性证据，不是某个模型真实 tokenizer 的测量结果。
若面板直接展示清单数字，会和写作预算判断产生误解；应统一公共估算器、标明估算口径和渲染开销。
[预算估算器](../../OpenWrite/models/context_package.py)、[清单估算](../../OpenWrite/tools/context_manifest.py)

另一个需要明确的业务策略：当前 `ContextBuilder._force_fit` 在持续超预算时会裁剪 world rules、core documents，
之后甚至裁剪 author intent / creative focus。代码说明极小自定义预算的最后清空分支通常不会由公共最小 12K 配置触发。
不能据此声称日常输入必然丢失约束；但应定义哪些条目禁止自动裁剪，保护项超限时给出明确原因和可选处理，
避免仅以“符合 token 上限”作为输入有效的标准。此处是源码路径确认，尚未运行完整生成路径。
[本地压缩策略](../../OpenWrite/tools/context_builder.py)

## 4. 建议落地顺序与验收条件

1. **保存正确性与恢复（先做）**：冻结请求的稿件、文档身份和版本；串行保存并排队新输入。延迟保存期间继续输入、失败重试、切章/Workspace、关闭恢复均不误报 saved；迟到响应不污染新文档。
2. **上下文计量与保护**：manifest 和执行预算对相同渲染文本使用同一估算器；展示 system/tools/skills/正文等预算组成。不可裁剪项内容和 revision 可检查，超限返回可操作原因；预算压缩不能静默移除必要正典。
3. **改稿接纳与事实联动**：以已接纳正文 SHA 为基线检测改动；生成事实差异后再次检查 SHA；确认接纳后使依赖摘要/评审/计划失效；影响未处理时，续写明确提示或按既有规则阻断。手工保存、Agent 编辑、历史恢复、外部编辑器写入都应覆盖。
4. **变更与修订工作台**：在现有轮次摘要上接入 before/after、源版本、修改原因、逐项采用、失败重试与历史。恢复/回滚先展示范围，拒绝覆盖之后产生的新修改；状态区分未写入、写入成功、刷新失败。
5. **导入与项目归档**：已有导入/分析/回填步骤共用一次导入 manifest，源变更可精确失效；半发布不被当作完成作品。归档预览包含与缺失项，在新路径恢复后验证正文、结构、历史与评审，不以生成 ZIP/JSON 为验收终点。
6. **章节导向的日常操作**：伏笔到期/超期清单、稳定证据回跳、跨卷排序、查找替换；场景实体仍按前报告的领域模型建议单独设计，不从大纲拖放推断其已经具备。

上述顺序是设计建议，没有自动更改当前项目的写入权限、评审阈值、正典采用规则或目标状态。
沿用 OpenWrite 作为领域后端、dsh 作为唯一交互壳和 Agent 编排层，避免新建平行状态存储。

## 5. 本轮交付与验证边界

- 交付此报告，固定七个仓库的 SHA 与源码链接；更新通用调研和 README 的入口。
- 父代理复核了 Scriverse 保存实现、OpenFic 索引状态及 InkOS 上下文/文件集提交的关键代码。
- 本地通过实际纯函数复现 token 估算差异；使用合成字符串，没有访问真实稿件、调用模型或写入 OpenWrite 数据。
- 前轮自动保存缺陷仍待修复，复现入口为 [autosave-race-repro.mjs](research/autosave-race-repro.mjs)。本轮未修改生产代码，未将上游存在测试文件说成测试已通过。
- 首个可执行开发任务仍是修复 `CreationView.save`；随后统一上下文估算，定义约束保护，再实现正文事实接纳联动。
