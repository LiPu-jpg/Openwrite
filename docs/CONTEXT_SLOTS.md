# 写手上下文槽位参考

本表对应候选 Core 5.8.20，来源提交 `9611c654e5d77bcb5968105a7adfa8e9b4f9624a`。由捆绑 wheel 的 SECTION_SOURCES、保护规则和 shares 生成，共 20 个来源条目，包含兼容别名；不是每次写作都会装满这些槽位。

## 看本章实际用了什么

先用 `novel_context_preview {"chapter":"ch_001","include_agent_payload":true}`；要看所选 writer 档案、guidance 与 target_words 的最终输入，使用 `novel_write_chapter {"chapter_id":"ch_001","dry_run":true}`。这些预览不发起写作模型请求。

`context_manifest.items` 提供实际槽位、来源指纹、字符数、估算 token、保护/压缩状态；`documents` 列出 character/setting/style 每份文档原始与装配字符数、compressed/excluded。`missing_items` 与 `excluded_items` 解释缺失/排除。来源目录是候选来源，不能把目录中所有文件都当成实际已送给模型的文档。

## 预算怎样分配

没有固定的每槽字符上限。先按模型上下文窗、输出预留和安全余量计算输入预算；未超预算保持原文。受保护硬约束先占预算，装不下就明确失败；不会静默删掉它们。其余容量换算为字符后，按以下 shares 归一化分配（这不是整窗百分比）：

| 配额组 | 默认权重 |
| --- | --- |
| historical_outline | 0.08 |
| current_outline | 0.08 |
| previous_chapter | 0.18 |
| protagonist_state | 0.04 |
| characters | 0.13 |
| settings | 0.08 |
| style | 0.12 |

style 权重可用 novel_config.yaml 的 context_style_share 调整，限制在 0.01–0.5。风格容量还会优先保留最多 4000 字符的已有风格（不超过可选总容量的一半），其余组随剩余容量缩放。最终仍检查 token 总量。

多文档按各自容量占比分配；同优先级按名称排序，剩余字符依次补给。设置/角色通常截取开头，上一章正文保留结尾；配额为零的文档排除。风格优先顺序见下表。目录表里的 level 是来源层级，不是逐层删除顺序。

## 来源、选择和消费者

| 槽位 | 层级 | 作品根目录内来源 | 预算 | 选择/压缩规则 | 谁读 |
| --- | --- | --- | --- | --- | --- |
| `author_intent` | 3 | `src/story/author_intent.md` | 受保护，不截断 | 作者意图；完整保留硬约束 | 章节装配/兼容输入 → writer；manifest 展示 |
| `creative_focus` | 1 | `src/story/current_focus.md` | 受保护，不截断 | 创作罗盘；完整保留硬约束 | 章节装配/兼容输入 → writer；manifest 展示 |
| `story_background` | 3 | `src/story/background.md`、`src/story/foundation.md` | 受保护，不截断 | 兼容别名；有 core_documents 时 manifest 隐藏重复项 | 章节装配/兼容输入 → writer；manifest 展示 |
| `core_documents` | 3 | `src/story/background.md`、`src/story/foundation.md` | 受保护，不截断 | 故事背景与基础正典；完整保留 | 章节装配/兼容输入 → writer；manifest 展示 |
| `historical_arc_summaries` | 4 | `src/outline.md` | historical_outline | 已结束篇摘要；按摘要文档分配，截取开头 | 章节装配/兼容输入 → writer；manifest 展示 |
| `current_arc_sections` | 2 | `src/outline.md` | current_outline | 当前篇各节摘要；按摘要文档分配，截取开头 | 章节装配/兼容输入 → writer；manifest 展示 |
| `chapter_requirements` | 0 | `src/outline.md` | 受保护，不截断 | 当前章目标、节拍、悬念、章节承诺 promise/payoff_of 与登记的扩展字段；完整保留 | 章节装配/兼容输入 → writer；manifest 展示 |
| `scene_context` | 0 | `data/story_structure/scenes.json` | 受保护，不截断 | 仅当前正文版本匹配的场景结构；过期时排除并诊断 | ContextBuilder → writer；manifest 展示 |
| `previous_chapter_content` | 0 | `data/manuscript/` | previous_chapter | 默认上一章全文；可选 tail/有效 summary；预算压力下保留结尾 | 章节装配/兼容输入 → writer；manifest 展示 |
| `character_states` | 1 | `data/manuscript/`、`src/outline.md` | 由 ContextBuilder/检索预算决定 | ContextBuilder 提取本章涉及人物的行内状态；受该装配器预算约束 | ContextBuilder → writer；manifest 展示 |
| `semantic_references` | 4 | `data/manuscript/`、`data/sources/` | 由 ContextBuilder/检索预算决定 | ContextBuilder 语义检索的远距离正文/资料；需可用的独立 Embedding 档案；受检索与装配预算约束 | ContextBuilder → writer；manifest 展示 |
| `protagonist_state` | 1 | `data/world/current_state.md` | protagonist_state | 本章涉及人物的当前状态；可选区按配额截取 | 章节装配/兼容输入 → writer；manifest 展示 |
| `current_state` | 3 | `data/world/current_state.md` | 受保护，不截断 | 兼容连续性字段；有 continuity_documents 时隐藏重复项 | 章节装配/兼容输入 → writer；manifest 展示 |
| `ledger` | 3 | `data/world/ledger.md` | 受保护，不截断 | 兼容粒子台账；有 continuity_documents 时隐藏重复项 | 章节装配/兼容输入 → writer；manifest 展示 |
| `relationships` | 3 | `data/world/relationships.md` | 受保护，不截断 | 兼容人物关系；有 continuity_documents 时隐藏重复项 | 章节装配/兼容输入 → writer；manifest 展示 |
| `character_documents` | 2 | `src/characters/` | characters | 只选本章涉及人物；按文档容量分配、保留开头 | 章节装配/兼容输入 → writer；manifest 展示 |
| `concept_documents` | 2 | `src/world/` | settings | setting_documents 的兼容别名；不重复计算 | 章节装配/兼容输入 → writer；manifest 展示 |
| `setting_documents` | 2 | `src/world/`、`src/progression/` | settings | 世界规则/术语/时间线 + 本章涉及实体 + 全部 YAML 进阶体系；按文档容量分配、保留开头 | 章节装配/兼容输入 → writer；manifest 展示 |
| `continuity_documents` | 3 | `data/world/`、`data/foreshadowing/` | 受保护，不截断 | 运行态正典 current_state/ledger/relationships；完整保留 | 章节装配/兼容输入 → writer；manifest 展示 |
| `style_documents` | 3 | `data/style/`、`craft/` | style | 作品风格与 craft；优先 work.composed/manifest/fingerprint/craft，再按文档容量分配 | 章节装配/兼容输入 → writer；manifest 展示 |

## 渐进摘要与进阶体系

`progressive_compressor` 是较早的分节/分篇摘要组件：节摘要目标约 800 字符，篇摘要目标约 2000 字符，优先首尾、关键词和事件，降低对话优先级并在句子边界截断。它不是上表 ChapterAssemblerV2 的逐槽预算器；不要把旧组件的目标长度当成当前每槽固定预算。

作者在资产页创建的进阶体系保存于 `src/progression/<id>.yaml`。本候选实际加载 .yaml/.yml 为 `setting_documents[progression.<id>]`，经过同一设置预算进入 writer，并出现在逐文档用量里；即使没有 world/ 目录也可加载。文件存在不保证预算不足时完整送达，写前应核对预览。

工具参数与修改方式见 [工具参考](TOOLS.md)。
