---
name: outline
version: 1.0.0
description: |
  This skill should be used when the user wants to create, modify, or query 
  the novel outline. Triggers include "创建大纲", "修改大纲", "查看大纲",
  "outline", "大纲结构", "章节规划".
trigger: /outline
triggers:
  - "创建大纲"
  - "新建大纲"
  - "修改大纲"
  - "调整大纲"
  - "查看大纲"
  - "大纲结构"
  - "大纲内容"
  - "章节规划"
  - "outline"
requires:
  - read_file
  - write_file
  - yaml_parse
allowed-tools:
  - Bash(python:*)
  - Read
  - Write
---

# 大纲编辑功能

管理四级大纲（总纲→篇纲→节纲→章纲）的创建、修改和查询。

## 功能概述

大纲系统采用四级层次结构：
1. **总纲 (Master)**: 全书核心框架、主题、结局方向
2. **篇纲 (Arc)**: 大剧情弧，每个篇章有独立的矛盾-发展-收束周期
3. **节纲 (Section)**: 情节单元，包含一组相关的关键事件
4. **章纲 (Chapter)**: 具体写作任务，每章 5k-8k 字

## 使用方式

### 创建大纲
用户说"创建大纲"或"新建大纲"，启动创建工作流：
1. 确定总纲（书名、主题、结局、关键转折点）
2. 规划篇纲（3-5 个大剧情弧）
3. 细化节纲（每篇 2-4 节）
4. 编写章纲（每节 3-8 章）

### 修改大纲
用户说"修改大纲"，启动修改工作流：
1. 选择要修改的层级（总纲/篇纲/节纲/章纲）
2. 定位具体节点
3. 执行修改
4. 检查一致性

### 查询大纲
用户说"查看大纲"或"大纲结构"，直接返回：
- 当前大纲层级结构
- 指定层级的详细内容
- 统计信息（总字数、章节数等）

## 工作流

- `workflows/create.yaml`: 从零创建四级大纲
- `workflows/modify.yaml`: 修改现有大纲

## 提示词

- `prompts/generate_master.md`: 生成总纲
- `prompts/generate_arc.md`: 生成篇纲
- `prompts/generate_section.md`: 生成节纲
- `prompts/generate_chapter_outline.md`: 生成章纲

## 工具

- `tools/parser.py`: Markdown → OutlineHierarchy
- `tools/serializer.py`: OutlineHierarchy → Markdown
- `tools/validator.py`: 大纲验证

## 数据格式

大纲数据存储在 `data/novels/{novel_id}/outline/` 目录：

```
outline/
├── hierarchy.yaml      # 完整层级结构（机器可读）
├── outline.md          # Markdown 格式（人类可读）
└── notes.md            # 大纲注意事项
```

## 与其他功能的关联

- **角色**: 章纲中引用 involved_characters
- **伏笔**: 章纲中引用 foreshadowing_refs
- **世界观**: 章纲中引用 involved_settings
- **写作**: 写作时根据章纲 goals 生成内容
