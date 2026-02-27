# OpenWrite 大纲 Markdown 格式规范 (OUTLINE_MD_SPEC)

本文档定义了 OpenWrite 系统中层级大纲的 Markdown 序列化与解析标准。该格式作为人类作者编辑与 AI Agent 自动生成的通用媒介，确保大纲在结构化数据（JSON/YAML）与人类可读文档之间无损转换。

## 1. 层级映射 (Hierarchy Mapping)

大纲采用标题级别（Heading Level）映射四级逻辑结构：

| 标题级别 | 对应模型 | 说明 |
| :--- | :--- | :--- |
| `#` (H1) | `MasterOutline` | 全书总纲（顶层规划），全局唯一。 |
| `##` (H2) | `ArcOutline` | 篇纲（大剧情弧），包含多个情节单元。 |
| `###` (H3) | `SectionOutline` | 节纲（情节单元），包含多个章节。 |
| `####` (H4) | `ChapterOutline` | 章纲（最小生成单元），对应具体的写作任务。 |

## 2. 元数据格式 (YAML Frontmatter)

每个层级紧随标题之后，可包含一个 YAML 块，用于存储该层级的结构化字段。

### 2.1 总纲 (MasterOutline - H1)
```markdown
# [书名]
---
novel_id: "novel_001"
core_theme: "核心主题描述"
ending_direction: "结局走向"
world_premise: "世界观设定概述"
tone: "整体基调"
target_word_count: 1000000
version: "1.0"
---
- 关键转折点1
- 关键转折点2
```
*注：`key_turns` 在 Markdown 中表现为 YAML 块下方的无序列表。*

### 2.2 篇纲 (ArcOutline - H2)
```markdown
## [篇名]
---
arc_id: "arc_001"
main_conflict: "主要矛盾"
resolution: "收束方向"
key_characters: ["人物A", "人物B"]
status: "TODO" # TODO/WRITING/DONE
---
```

### 2.3 节纲 (SectionOutline - H3)
```markdown
### [节名]
---
section_id: "sec_001"
plot_summary: "情节概要"
key_events: ["事件1", "事件2"]
foreshadowing_plant: ["fs_001"]
foreshadowing_recover: ["fs_002"]
status: "TODO"
---
```

### 2.4 章纲 (ChapterOutline - H4)
```markdown
#### [章名]
---
chapter_id: "ch_001"
goals: ["目标1", "目标2"]
key_scenes: ["场景1", "场景2"]
emotion_arc: "情绪起伏描述"
involved_characters: ["char_001"]
involved_settings: ["loc_001"]
foreshadowing_refs: ["fs_001"]
target_words: 6000
status: "TODO" # TODO/WRITING/REVIEW/DONE
---
```

## 3. 解析规则 (Parsing Rules)

### 3.1 标题识别
使用正则匹配标题行：
- 正则：`^(#{1,4})\s+(.+)$`
- 捕获组 1 为级别（1-4），捕获组 2 为 `title`。

### 3.2 元数据提取
- 紧跟在标题后的第一个 `---` 包围的块被解析为 YAML。
- 字段映射遵循 `tools/models/outline.py` 中的 Pydantic 定义。
- **排除项**：`compressed_summary` 字段不出现在 Markdown 中（仅存于后台存储）。

### 3.3 层级推断
- 解析器维护一个当前的上下文栈（Current Context Stack）。
- 当遇到新标题时，根据其级别自动关闭低级别节点。
- 父子关系（如 `novel_id`, `arc_id`, `section_id` 引用）在解析时根据物理嵌套位置自动推断并填充，无需在 Markdown 的 YAML 中显式书写。
- 子列表（如 `arc_ids`, `section_ids`, `chapter_ids`）在序列化时根据物理顺序生成，解析时自动推断。

### 3.4 关键转折点 (key_turns)
- 仅限 H1 层级。
- 匹配 YAML 块结束后的第一个无序列表（`- ` 或 `* `）。

## 4. 序列化规则 (Serialization Rules)

### 4.1 顺序生成
- 按照 `OutlineHierarchy` 中的 `order` 字段或列表索引顺序写入。
- 始终保持：H1 -> H2 -> H3 -> H4 的深度优先遍历顺序。

### 4.2 块生成
- 每个节点必须包含 `---` 块，即使部分字段为空。
- 自动移除自动生成的关联字段（如 `*_ids`），确保 Markdown 简洁。

## 5. 示例结构 (Example)

```markdown
# 术师手册
---
novel_id: "sorcerer_manual"
core_theme: "真理与自由"
ending_direction: "虚境崩塌，回归现实"
---
- 亚修进入虚境
- 发现干预手册的真相

## 第一卷：碎湖监狱
---
arc_id: "arc_001"
main_conflict: "从监狱死刑中生还"
status: "DONE"
---

### 越狱计划
---
section_id: "sec_001"
plot_summary: "亚修通过手册集结队友，策划历史上第一次碎湖越狱。"
status: "DONE"
---

#### 观测者亚修
---
chapter_id: "ch_001"
goals: ["建立世界观", "引入手册"]
target_words: 5000
status: "DONE"
---

#### 狱友与食谱
---
chapter_id: "ch_002"
goals: ["引入重要配角伊格拉"]
target_words: 6000
status: "DONE"
---
```

## 6. 兼容性说明 (Compatibility)

- **与 `initial.md` 的关系**：`novels/{novel_id}/initial.md` 通常是 Reader Agent 的初步输出（分维度陈述）。而本规范定义的 `outline.md` 是**层级化**的生产级文档。系统应提供从 `initial.md` 迁移到 `outline.md` 的工具。
- **与 `hierarchy.yaml` 的关系**：`outline.md` 是 `OutlineHierarchy` 模型的人类可编辑视图。在数据保存时，系统会同时更新磁盘上的结构化存储以供 Agent 快速检索。

## 7. 相关参考
- 模型定义：`tools/models/outline.py`
- 解析实现：`tools/parsers/outline_md_parser.py` (待实现)
- 序列化实现：`tools/utils/outline_md_serializer.py` (待实现)
- 测试用例：`tests/test_outline_parser.py` (待实现)
