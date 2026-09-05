# 开源小说工具对照与 dsh-Openwrite 改进清单

核查日期：2026-09-05。对象为当前 `dsh-novel` 与相邻 `OpenWrite` 工作树。

项目归属（用户确认）：[OpenWrite Core](https://github.com/LiPu-jpg/Openwrite/tree/native-core) 是本团队自己的核心项目，
当前 `dsh-novel` 是其 DeepSeek Harness 插件版本。本文以两仓库共同构成的产品能力为基线；
OpenWrite 已有而 dsh 面板尚未接入的能力，归为插件接入/交互缺口，不计为核心能力缺失。

后续按用户指定的 Casting-Workflow、ainovel-cli、Scriverse、OpenFic、CharacterArc、MuMuAINovel 和 InkOS
进行了固定提交的源码核查，见 [七项目专项对照](TARGETED_NOVEL_PROJECT_REVIEW.md)。其中补充了改稿后的事实联动、
导入恢复、上下文保护以及 token 估算不一致的证据，扩展了本报告侧重界面的结论。

**结论：先保证稿件可靠保存，再把已有领域能力做成作者能直接使用的操作。**
当前项目已有章节流水线、正典、评审与修订、上下文清单、版本快照、字数目标和导出能力。
本轮发现的主要差距是保存正确性、版本恢复入口、场景组织、上下文透明度，以及整书交付体验。
继续增加模型或工具数量并不能直接解决这些问题。

本报告按传统写作软件、AI 辅助写作、编辑器插件选择代表项目，不作“最流行”排名。
外部功能依据作者仓库和官方文档确认；本地结论依据源码审计，其中自动保存问题另有真实回调复现。
未安装这些产品、运行跨产品写作质量评测、调用模型或修改真实稿件。
下列改进均为待实施建议，不代表功能已交付。

## 1. 代表项目：学什么，以及不能误认为什么

| 项目 | 许可、维护与产品边界 | 已确认的设计及值得借鉴之处 |
|---|---|---|
| **novelWriter** | GPLv3；[26.1.2](https://github.com/saga-soft/novelWriter/releases/tag/v26.1.2) 于 2026-07-25 发布，8 月仍有提交。[仓库与许可](https://github.com/saga-soft/novelWriter) | `@pov`、在场 `@char`、提及 `@mention` 分开；稿件构建可以筛选、预览、保存配置并生成多种格式。适合学习有明确语义的人物引用，以及可重复的导出配置。[引用手册](https://novelwriter.io/docs/usage/tags_and_references.html)、[稿件构建](https://novelwriter.io/docs/user_interface/manuscript.html) |
| **Manuskript** | GPLv3 或后续版本；[0.17.0](https://github.com/olivierkes/manuskript/releases/tag/0.17.0) 于 2025-06-30 发布，develop 在 2026-09-01 仍有打包修复。不能仅因发行间隔较长判断停更。[仓库](https://github.com/olivierkes/manuskript) | 从一句话发展到摘要、人物与情节；编辑侧栏展示 POV、状态、目标、故事线；历史可比较和恢复。最适合补我们的章节历史界面。[官网](https://www.theologeek.ch/manuskript/)、[侧栏手册](https://github.com/olivierkes/manuskript/wiki/Overview-of-Manuskript-Right-Sidebar) |
| **bibisco Community Edition** | 公开 CE 仓库为 GPLv3；最近可见源码提交为 2024-09 的 4.0.0，官网产品已发布 [5.1.3（2026-08-12）](https://bibisco.com/docs/bibisco-5-release-notes/)。这两条版本线不能混同。[CE 仓库](https://github.com/andreafeccomandi/bibisco) | 人物访谈与叙事结构分开组织。产品的全书连续阅读、双击回到场景编辑值得研究，但连续阅读、时间线、EPUB 等属于 Supporters 功能，不能宣传为免费 CE 已有能力。[连续阅读介绍](https://bibisco.com/blog/whats-new-in-bibisco-novel-writing-software-3-0/)、[版本差异](https://bibisco.com/docs/differences-between-community-and-supporters-editions/) |
| **AI_NovelGenerator** | AGPLv3；仓库可见 2026-08 更新。README 中 2026-03 的重写版本说明仍称初步框架、功能尚未就绪，不应把重写计划当作交付。[作者仓库](https://github.com/YILING0013/AI_NovelGenerator) | 设置与蓝图、多阶段写章、状态与伏笔追踪、知识库检索、一致性检查集中在 GUI 流程。可学创建作品到章节定稿的引导；我们的后端已有相近能力，不宜再造一套 RAG。上述是功能说明，不是长篇文学质量的实验证据。 |
| **SillyTavern** | AGPLv3；仓库在 2026-08 仍有维护。定位主要是聊天与角色扮演前端，不是完整成书系统。[仓库](https://github.com/SillyTavern/SillyTavern)、[官方文档](https://docs.sillytavern.app/) | World Info 有关键词/向量触发、注入位置、优先级和 token 预算。可学“为什么选中这条设定、放在哪里、为什么被预算排除”的控制方式。其文档也说明注入不保证模型遵守设定；中文不宜照搬英文整词匹配。[World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/) |
| **Novel Word Count（Obsidian 插件）** | MIT；[5.0.0](https://github.com/isaaclyman/novel-word-count-obsidian/releases/tag/5.0.0) 于 2026-08-03 发布。[作者仓库](https://github.com/isaaclyman/novel-word-count-obsidian) | 单篇目标向目录汇总，可排除设定笔记，结合 CJK 字符与空格分词计数。可学章节、卷、全书进度；v5 默认减少计数缓存写入。其文件树接入依赖未正式保证的宿主接口，有兼容性局限。[目标设置](https://github.com/isaaclyman/novel-word-count-obsidian#setting-goals)、[接口限制](https://github.com/isaaclyman/novel-word-count-obsidian#safety) |
| **Word Sprint（Obsidian 插件）** | MIT；最近可见发布 [0.3.2](https://github.com/kinabalu/obsidian-word-sprint/releases/tag/0.3.2) 为 2025-08-18，不能称近期持续活跃。[作者仓库](https://github.com/kinabalu/obsidian-word-sprint) | 把一次写作冲刺记录为新增、删除、净增、速度、停笔时间。可学“修稿也算劳动”的统计；多人模式仍列为 Coming Soon，中文计数本轮未实测。[功能说明](https://github.com/kinabalu/obsidian-word-sprint#features) |
| **StoryLine（Obsidian 插件）** | MIT；[1.10.64](https://github.com/PixeroJan/obsidian-storyline/releases/tag/1.10.64) 于 2026-09-01 发布。[作者仓库](https://github.com/PixeroJan/obsidian-storyline) | 场景卡片、情节网格、阅读顺序与时间顺序、按角色/地点/故事线分泳道；批量调整时间先展示预览。适合学习非线性小说组织。手册对 `sequence` 的定义有冲突，字段契约不能直接照搬；Flesch 可读性只适用英语。[手册](https://github.com/PixeroJan/obsidian-storyline/blob/main/HELP.md) |

Obsidian **宿主本身不开源**，这里研究的是各自有许可证的开源插件。[宿主官方说明](https://github.com/obsidianmd/obsidian-releases#about-this-repo)

补充案例：

- **Plot Bunni**：MIT 的较小项目，不作为主流程度的证据。按幕、章、场景组织，并把前文和关联概念用于场景上下文；支持项目 JSON 与正文导出。可学场景、设定、写作操作之间的直接联系，但浏览器本地存储本身不等于经过验证的备份恢复机制。[作者仓库](https://github.com/MangoLion/plotbunni)
- **EPUBCheck**：BSD-3-Clause，由 DAISY 代表 W3C 维护的 EPUB 合规检查器；当前 README 标明 5.3.0。可作为导出后的格式检查，和小说内容预检配合。格式有效不证明文学质量或每种阅读器的排版效果。[官方仓库](https://github.com/w3c/epubcheck)

## 2. 公开源码不等于相同的复用条件

**Longform** 很值得研究场景索引与导出工作流：重排场景改变项目组织信息；编译按“逐场景处理 → 合并 → 全稿处理”执行，可保存配置。
但当前许可证是带用途限制的自定义 **FAFO 0.2**，不能标成 MIT；维护者在 2026-02-24 公开表示无时间继续维护并寻求接手者。
因此单列为交互参考，不放进上表同类开源复用候选。
[编译文档](https://github.com/kevboh/longform/blob/main/docs/COMPILE.md)、[实际许可证](https://github.com/kevboh/longform/blob/main/LICENSE.md)、[维护交接声明](https://github.com/kevboh/longform/issues/327)

**Long-Novel-GPT** 的大纲到章节到正文、导入与提示词查看也可作为流程参考；本轮未在其仓库根目录确认到明确的许可证文件，不能因为源码可读就假设可自由复用。
[作者仓库](https://github.com/MaoXiaoYuZ/Long-Novel-GPT)

本轮只分析设计，没有复制上游代码。以后引入代码或依赖时，应核对具体版本和文件的许可证。

## 3. 本地不足：区分缺少界面与缺少能力

以下优先级按稿件可靠性、作者控制能力和实施依赖排序，不代表工期估算。

### P0：自动保存可能将未提交的草稿标为已保存

位置：[CreationView.tsx](../packages/studio-panel/src/client/CreationView.tsx)，`save`（核查时第 265 行）与 `updateDraft`；
[VditorBody.tsx](../packages/studio-panel/src/client/VditorBody.tsx) 关闭了编辑器自身缓存。

现有 `save` 发送 `draftRef.current` 后，等待响应，再次读取已经可能变化的 `draftRef.current`，
把它写入 `savedContentRef` 并无条件清除 dirty。后端版本检查不能补救从未收到的正文。

本轮直接提取真实源码回调，在 Node VM 中延迟 PUT、输入新稿，再触发实际定时回调，确定性得到：

```text
开始保存 A → 等待 PUT 响应 → 作者输入 B → A 的响应成功
实际发送正文：         ["A"]
界面草稿：             B
savedContentRef：      B
dirty：                false
最终界面状态：         saved
触发定时器及再次保存后：仍只有 1 个请求
```

这证明 B 未提交却被视为已保存，后续保存会跳过；退出/切章时依赖 dirty 的提示也会失效。
证明范围是**真实源码回调执行**，不是 React、Vditor、浏览器完整交互测试。
复现脚本：[autosave-race-repro.mjs](research/autosave-race-repro.mjs)，使用 Node 24 从仓库根目录运行：

```sh
node docs/research/autosave-race-repro.mjs
```

建议：在发送时冻结正文与文档身份；只确认服务器实际接收的那份内容。
输入发生在请求期间时保留 dirty，并基于新的服务器版本继续提交；迟到响应不能改写另一章节/Workspace 的状态。
本地草稿恢复可作为额外保护，不能替代修正保存状态机。

验收：延迟 A 请求期间输入 B，A 成功后 B 仍待保存并最终提交；重复点击保存、版本冲突、失败重试、切章、切 Workspace、刷新恢复均不把未提交文本标成 saved。

### P1：章节历史与恢复应接入创作面板

**已有能力**：OpenWrite 的 `ManuscriptVersionStore` 有列表、快照、加载、带 revision 检查的恢复；恢复前先创建快照。
bridge 的 `novel_manuscript_edit_action` 暴露 7 类版本/批注操作。
**缺口**：dsh 创作检查栏主要展示修订提案 JSON，没有面向作者的历史时间线、差异比较与恢复流程。
“修订建议”与“过去保存过的正文版本”应明确分开。

证据：[manuscript_editing.py](../../OpenWrite/tools/manuscript_editing.py)、[bridge tools.ts](../packages/openwrite-bridge/src/tools.ts)、[CreationView.tsx](../packages/studio-panel/src/client/CreationView.tsx)。
旧 Studio 的 [revisions.js](../../OpenWrite/tools/studio_assets/js/revisions.js) 已有界面实现可参考；仍按项目约定由 dsh 提供交互壳。

借鉴 Manuskript。验收：可命名快照、比较两个版本、预览恢复差异、确认后恢复；拒绝基于旧 revision 的恢复，并能找回恢复前版本。实现时补齐 panel 需要的受控路由，不只添加按钮。

### P1：展示生成上下文的组成与来源

**已有能力**：章节上下文包、人物状态、语义召回；`build_context_manifest` 已记录层级、来源、大小估算与 revision。
**缺口**：dsh 加载 `/context` 后主要保留 `markdown`，未将结构化清单作为可操作的来源检查器展示。
现有部分来源只定位到目录，不能声称已经实现逐条证据溯源。

证据：[context_manifest.py](../../OpenWrite/tools/context_manifest.py)、[novel_service.py](../../OpenWrite/tools/novel_service.py)、[CreationView.tsx](../packages/studio-panel/src/client/CreationView.tsx)。

借鉴 SillyTavern 的预算与注入控制、novelWriter 的引用语义。
验收：生成前可查看正典/人物状态/召回片段、来源链接、token 估算、缺失项、压缩/排除原因和包版本；改动设定后能比较上下文变化。
显示“人物在场、被提及、担任 POV”的不同语义；正典约束不应被当作随机召回的普通参考。
先接已有清单，只有真实缺失的字段才扩展后端。

### P2：场景需要稳定身份与独立的阅读/时间顺序

**已有能力**：大纲有总纲、卷、节、章，章节可有目标、人物、地点、情绪和 beats。
**结构缺口**：章是最小节点；beats 是文本列表，并非可持久引用的场景实体。
大纲工具禁止在章下新增子节点；当前 dsh 大纲操作也不含完整重排流程。

证据：[models/outline.py](../../OpenWrite/models/outline.py)、[outline_tree.py](../../OpenWrite/tools/outline_tree.py)、[OutlineView.tsx](../packages/studio-panel/src/client/OutlineView.tsx)。

借鉴 StoryLine、novelWriter 与 Plot Bunni。
建议最小场景字段：稳定 ID、所属章、阅读序号、故事时间/区间、POV、在场人物、地点、状态、摘要、正文定位。
`reading_order` 与 `story_time` 必须分别定义；插叙/倒叙不能靠修改时间去迁就章节顺序。

验收：重排、跨章移动、拆分/合并后正文与引用完整；导出遵循阅读顺序，时间线遵循故事时间；旧章节数据有可恢复迁移路径。
这是领域模型变更，需同步 OpenWrite、共享契约、bridge 和 panel，不能仅做前端卡片排序。

### P2：导出前预检与可验证的全项目备份

**已有能力**：MD/TXT/EPUB 导出、批注剥离、部分 XHTML 校验；`.owasset.zip` 可归档选定资产与依赖并带校验信息。
**缺口**：缺少统一的成稿预检与可保存导出配置；选定资产包也不等于包含正文、结构、历史、评审和项目配置的完整作品备份。
当前稿件收集遇到重复章节 ID 会选取其中一个，应改为明确报告，避免作者误以为全部内容已导出。
任务存储绑定 Workspace root，换目录后不能假设旧任务可直接续跑。

证据：[novel_workspace.py](../../OpenWrite/tools/novel_workspace.py)、[epub_export.py](../../OpenWrite/tools/epub_export.py)、[asset_package.py](../../OpenWrite/tools/asset_package.py)、[task_store.py](../../OpenWrite/tools/task_store.py)、[OperationsView.tsx](../packages/studio-panel/src/client/OperationsView.tsx)。

借鉴 novelWriter 的稿件构建、bibisco 的备份恢复和 EPUBCheck。
验收分两条：

- 成稿导出先预览章节顺序、缺失/重复/空章节、字数、元数据和评审新鲜度；保存导出配置；EPUB 额外运行 EPUBCheck 并展示报告。草稿/备份导出与正式交付分开，不能因评审未通过而阻止备份。
- 全项目归档有版本化 manifest、校验和、包含/排除清单与外部资源说明；在新目录恢复并核对正文、结构、历史、评审一致；排除凭据，明确旧任务归档/迁移策略。以实际恢复测试证明备份有效。

### P2：先显示已有字数目标，再增加写作会话统计

**已有能力**：全书/章节目标及持久化校验；bridge 有 `novel_writing_targets`。
**缺口**：dsh 编辑页未完整呈现目标控制与当前进度；未发现独立的每日目标/冲刺会话记录。

证据：[writing_targets.py](../../OpenWrite/tools/writing_targets.py)、[studio_application.py](../../OpenWrite/tools/studio_application.py)、[tools.ts](../packages/openwrite-bridge/src/tools.ts)、[HeaderChrome.tsx](../packages/studio-panel/src/client/HeaderChrome.tsx)。

借鉴 Novel Word Count 与 Word Sprint。
验收：先把已有目标读写接入面板，再按章/卷/书汇总，排除设定笔记；明确中文字符、英文词、标点及 Markdown 的计数口径。
冲刺记录新增/删除/净增、开始/暂停/结束，刷新后可恢复；AI 生成与人工输入仅在有明确事件依据时分开统计，不凭净增字数猜测来源。

### P3：从搜索结果直接回到原文，并提供连续审读

**已有能力**：跨文件搜索、代码侧替换与差异能力；旧 Studio 已有若干查找快捷键。
**缺口**：dsh `SearchView` 每次请求固定 20 条结果，主要是短片段展示，缺少完整的跳转选区/替换工作流。
当前新面板未完整接线快捷操作；本轮没有验证宿主或 Vditor 自带快捷键，不能断言“完全没有快捷键”。

证据：[SearchView.tsx](../packages/studio-panel/src/client/SearchView.tsx)、[tool_runtime.py](../../OpenWrite/tools/agent/tool_runtime.py)、[旧 Studio application.js](../../OpenWrite/tools/studio_assets/js/application.js)。

借鉴 bibisco 的连续阅读与回跳编辑。
验收：点击命中项定位当前正确版本的原文；查找有范围、大小写/整词选项；替换先展示数量与 diff，并结合 revision 与恢复能力。
整章/整书连续阅读可展示现有评审和批注，点击段落能回到对应章与选区；中文查找不强依赖英文整词规则。

## 4. 建议实施顺序与维护方式

1. **稿件可靠性**：修复自动保存竞态，补覆盖请求期间输入与切换文档的回归；接入已有历史比较/恢复。
2. **作者可控的 AI**：展示上下文清单、来源与预算；把创建作品、准备上下文、写章、审阅、修订的现有流程串成清晰入口。
3. **长篇组织与交付**：明确场景契约及迁移，再做阅读/时间双序；补导出预检、完整备份和异地路径恢复验证。
4. **日常写作体验**：呈现已有目标，增加冲刺统计、搜索回跳和连续阅读。

每项沿用“OpenWrite 领域实现 → 共享契约与 bridge → dsh 面板 → 针对风险的验证”，
不新增平行的正文、版本、状态或模型调用存储。
工程安装与升级门禁继续参考 [插件维护手册](PLUGIN_MAINTENANCE.md)；本报告不改变既有评审与交付标准。

不优先照搬：没有质量证据的一键超长生成宣传、已有能力的第二套 RAG、把英文可读性公式用于中文、
仅凭随机注入维持正典，以及无法验证恢复结果的“自动备份成功”提示。

## 5. 核查记录与复核入口

- 项目资料来自上列作者仓库、许可证、发布记录及官方手册。版本日期只代表本轮可见状态，不代表长期维护保证。
- Manuskript 的侧栏 Wiki 较旧；bibisco 当前产品与公开 CE 源码不同步；Longform 正在维护交接。借鉴前需按实际目标版本复核。
- 本地只进行了源码审计和自动保存回调复现。没有跨产品安装试用、生成质量排名、真实浏览器验收或生产稿件读写。
- 本轮新增报告及审计复现脚本，README 增加入口；未实施上述生产功能或修复。自动保存复现脚本断言的是当前缺陷，修复时应改为要求 B 被提交的防回归用例，不能将“缺陷复现成功”当作产品通过。
- 下一项具体工作：从 `CreationView.save` 的请求快照、串行提交与文档身份隔离入手修复 P0，再进行 React 与真实浏览器的连续输入验收。
