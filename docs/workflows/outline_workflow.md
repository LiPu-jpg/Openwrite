# 大纲编排工作流 (Outline Workflow)

## 概述

本文档定义 OpenWrite 系统中大纲编排的标准工作流程，包括从零开始创建大纲、逐级扩展细节、修改调整、以及与 AI Agent 协作的最佳实践。

---

## 工作流类型

### 1. 新建大纲流程（从零开始）

**适用场景**：开始一部新小说，尚无任何大纲。

**流程步骤**：

```
总纲构思 → 篇纲规划 → 节纲细化 → 章纲编写
```

#### 1.1 总纲构思（MasterOutline）

**目标**：确定全书的核心框架。

**必需字段**：
- `novel_id`: 小说唯一标识
- `title`: 书名
- `core_theme`: 核心主题（一句话概括）
- `ending_direction`: 结局走向（开放式/悲剧/喜剧/反转等）
- `key_turns`: 关键转折点列表（3-7个）

**可选字段**：
- `world_premise`: 世界观前提
- `tone`: 整体基调（轻松/严肃/黑暗/热血等）
- `target_word_count`: 目标总字数

**操作方式**：
1. **CLI**: `python3 -m tools.cli init <novel_id>`
2. **Web API**: `POST /api/novel/init` 提交初始化请求
3. **Markdown**: 直接编辑 `outline.md`，从 `# 总纲：{书名}` 开始

**AI 辅助**：
- 提供核心创意 → AI 生成关键转折点建议
- 提供世界观设定 → AI 推荐合适的基调和主题

#### 1.2 篇纲规划（ArcOutline）

**目标**：将全书划分为 3-5 个大剧情弧，每个篇纲对应一个完整的矛盾-发展-收束周期。

**必需字段**：
- `arc_id`: 篇纲ID（如 `arc_001`）
- `order`: 在总纲中的排序
- `title`: 篇名
- `main_conflict`: 本篇主要矛盾
- `resolution`: 本篇收束方向

**可选字段**：
- `key_characters`: 核心人物ID列表
- `status`: TODO/WRITING/DONE

**操作方式**：
1. **Web API**: `POST /api/outline/arcs` 创建篇纲
2. **Markdown**: 在总纲下添加 `## 第N篇：{篇名}` + YAML 元数据块

**AI 辅助**：
- 根据总纲关键转折点 → AI 建议篇纲划分方案
- 根据主题和基调 → AI 生成每篇的主要矛盾

#### 1.3 节纲细化（SectionOutline）

**目标**：将每个篇纲细分为 2-4 个情节单元，每个节纲包含若干关键事件。

**必需字段**：
- `section_id`: 节纲ID（如 `sec_001`）
- `order`: 在篇纲中的排序
- `title`: 节名
- `plot_summary`: 本节情节概要

**可选字段**：
- `key_events`: 关键事件列表
- `foreshadowing_plant`: 本节埋设的伏笔ID
- `foreshadowing_recover`: 本节回收的伏笔ID

**操作方式**：
1. **Web API**: `POST /api/outline/sections` 创建节纲
2. **Markdown**: 在篇纲下添加 `### 第N节：{节名}` + YAML 元数据块

**AI 辅助**：
- 根据篇纲矛盾和收束 → AI 生成节纲划分建议
- 根据关键事件 → AI 推荐伏笔埋设点

#### 1.4 章纲编写（ChapterOutline）

**目标**：为每个节纲下的章节编写详细的写作目标和场景列表。

**必需字段**：
- `chapter_id`: 章纲ID（如 `ch_001`）
- `order`: 在节纲中的排序
- `title`: 章名
- `goals`: 本章写作目标列表

**可选字段**：
- `key_scenes`: 关键场景列表
- `emotion_arc`: 情绪弧线描述
- `involved_characters`: 涉及人物ID
- `involved_settings`: 涉及设定（地点/道具）
- `foreshadowing_refs`: 相关伏笔ID
- `target_words`: 目标字数（默认 6000）

**操作方式**：
1. **Web API**: `POST /api/outline/chapters` 创建章纲
2. **Markdown**: 在节纲下添加 `#### 第N章：{章名}` + YAML 元数据块

**AI 辅助**：
- 根据节纲情节概要 → AI 生成章节划分和目标
- 根据涉及人物和设定 → AI 推荐关键场景

---

### 2. 大纲修改流程（已有大纲）

**适用场景**：大纲已存在，需要调整结构或内容。

**流程步骤**：

```
识别修改点 → 评估影响范围 → 执行修改 → 同步更新
```

#### 2.1 识别修改点

**常见修改类型**：
- **结构调整**：增删篇/节/章，调整顺序
- **内容修改**：修改矛盾、目标、场景
- **伏笔调整**：新增/删除/移动伏笔埋设/回收点

#### 2.2 评估影响范围

**检查项**：
- 修改是否影响上下级大纲？（如修改篇纲矛盾，需同步更新节纲）
- 修改是否影响伏笔链？（如删除章节，需检查伏笔是否断裂）
- 修改是否影响人物时间线？（如调整章节顺序，需检查人物位置连续性）

#### 2.3 执行修改

**操作方式**：
1. **Web API**: 使用 `PUT /api/outline/arcs/{arc_id}` 等端点更新
2. **Markdown**: 直接编辑 `outline.md`，然后 `POST /api/outline/import` 导入

**推荐方式**：
- **小范围修改**（单个字段）：使用 Web API
- **大范围重构**（多层级调整）：导出为 Markdown → 编辑 → 重新导入

#### 2.4 同步更新

**必做检查**：
- 运行 `LoreChecker` 检查逻辑一致性
- 检查伏笔 DAG 是否有环或断裂
- 检查人物时间线是否连续

---

### 3. AI 辅助大纲生成流程

**适用场景**：希望 AI 根据创意自动生成完整大纲。

**流程步骤**：

```
提供核心创意 → AI 生成总纲 → 人工审核 → AI 扩展篇纲 → 人工审核 → AI 扩展节纲/章纲 → 最终确认
```

#### 3.1 提供核心创意

**输入内容**：
- 核心主题（一句话）
- 世界观设定（简要描述）
- 主要人物（3-5个）
- 期望的结局走向
- 目标字数

#### 3.2 AI 生成总纲

**AI 任务**：
- 根据核心创意生成 `core_theme`、`ending_direction`、`world_premise`、`tone`
- 生成 3-7 个关键转折点（`key_turns`）

**人工审核**：
- 检查关键转折点是否合理
- 检查基调是否符合预期
- 必要时手动调整

#### 3.3 AI 扩展篇纲

**AI 任务**：
- 根据关键转折点划分 3-5 个篇纲
- 为每个篇纲生成 `main_conflict` 和 `resolution`

**人工审核**：
- 检查篇纲划分是否均衡
- 检查矛盾是否有递进关系
- 必要时合并/拆分篇纲

#### 3.4 AI 扩展节纲/章纲

**AI 任务**：
- 为每个篇纲生成 2-4 个节纲
- 为每个节纲生成 3-8 个章纲
- 为每个章纲生成写作目标和关键场景

**人工审核量是否合理（根据目标字数）
- 检查场景是否有重复或遗漏
- 必要时调整章节顺序或内容

#### 3.5 最终确认

**检查清单**：
- [ ] 总纲字段完整
- [ ] 篇纲数量合理（3-5个）
- [ ] 节纲数量合理（每篇 2-4个）
- [ ] 章纲数量合理（每节 3-8个）
- [ ] 关键转折点在篇纲中有体现
- [ ] 伏笔埋设/回收点已标记
- [ ] 人物在各章节中的分布合理

---

## Markdown 大纲编辑最佳实践

### 1. 使用 outline.md 作为主文档

**优势**：
- 人类可读，易于编辑
- 支持版本控制（Git）
- 可直接在文本编辑器中查看全局结构

**操作流程**：
1. 导出当前大纲：`GET /api/outline/export` → 保存为 `outline.md`
2. 在文本编辑器中编辑 `outline.md`
3. 导入更新后的大纲：`POST /api/outline/import` 提交文件内容

### 2. 保持 YAML 元数据完整

**必需字段**：
- 每个层级的 `*_id` 和 `order` 字段必须存在
- `novel_id` 在总纲中必须存在

**可选字段**：
- 空值字段可以省略（解析器会使用默认值）
- 但建议保留关键字段（如 `status`）以便追踪进度

### 3. 使用注释标记待办事项

**示例**：
```markdown
#### 第三章：初遇

---
chapter_id: ch_003
order: 3
goals:
  - 主角与女主初次见面
  - 埋设伏笔：神秘信物
status: TODO
---

<!-- TODO: 补充关键场景细节 -->
<!-- TODO: 确认女主人物设定 -->
```

---

## 与其他系统的协作

### 1. 与人物系统协作

**关联点**：
- `ChapterOutline.involved_characters` 引用人物ID
- 修改章节顺序时，需同步更新人物时间线

**操作建议**：
- 在章纲中明确标记涉及人物
- 使用 `CharacterStateManager` 追踪人物状态变更

### 2. 与伏笔系统协作

**关联点**：
- `SectionOutline.foreshadowing_plant` 标记埋设点
- `SectionOutline.foreshadowing_recover` 标记回收点
- `ChapterOutline.foreshadowing_refs` 引用相关伏笔

**操作建议**：
- 在节纲层级规划伏笔埋设/回收
- 在章纲层级标记具体涉及的伏笔
- 定期运行伏笔 DAG无断裂

### 3. 与世界观系统协作

**关联点**：
- `ChapterOutline.involved_settings` 引用世界观实体（地点/道具）
- `MasterOutline.world_premise` 定义世界观前提

**操作建议**：
- 在总纲中明确世界观核心规则
- 在章纲中标记涉及的地点和道具
- 使用 `WorldGraphManager` 检查世界观一致性

---

## 常见问题

### Q1: 如何调整章节顺序？

**方法 1（推荐）**：
1. 导出 `outline.md`
2. 在 Markdown 中调整章节位置
3. 修改 `order` 字段（保持连续）
4. 重新导入

**方法 2**：
- 使用 Web API 逐个更新 `order` 字段

### Q2: 如何删除一个篇纲？

**步骤**：
1. 检查该篇下是否有节纲/章纲
2. 如有，先删除所有子节点（或移动到其他篇）
3. 使用 `DELETE /api/outline/arcs/{arc_id}` 删除篇纲
4. 更新总纲的 `arc_ids` 列表

### Q3: 如何合并两个节纲？

**步骤**：
1. 将节纲 B 的章纲移动到节纲 A（修改 `section_id`）
2. 合并节纲 B 的 `key_events` 到节纲 A3. 删除节纲 B
4. 更新篇纲的 `section_ids` 列表

### Q4: Markdown 导入失败怎么办？

**常见原因**：
- YAML 语法错误（缩进、引号）
- 缺少必需字段（`*_id`、`order`）
- 标题格式不符合规范

**排查方法**：
1. 检查错误信息中的行号
2. 使用 YAML 在线验证器检查语法
3. 对比 `docs/OUTLINE_MD_SPEC.md` 中的示例

---

## 附录：CLI 命令速查

```bash
# 初始化新小说
python3 -m tools.cli init <novel_id>

# 查看大纲层级
python3 -m tools.cli outline show <novel_id>

# 导出大纲为 Markdown（需实现）
python3 -m tools.cli outline export <novel_id> -o outline.md

# 导入 Markdown 大纲（需实现）
python3 -m tools.cli outline import <novel_id> -f outline.md
```

---

##档

- [Markdown 大纲格式规范](../OUTLINE_MD_SPEC.md)
- [风格系统工作流](./style_workflow.md)
- [伏笔系统使用指南](../../README.md#伏笔系统)
