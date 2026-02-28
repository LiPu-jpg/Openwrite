---
name: writing
version: 1.0.0
description: |
  This skill should be used when the user wants to generate or rewrite chapter content.
  Triggers include "写章节", "生成章节", "续写", "重写", "草稿".
trigger: /write
triggers:
  - "写章节"
  - "生成章节"
  - "写第"
  - "生成第"
  - "续写"
  - "重写"
  - "草稿"
  - "润色"
requires:
  - read_file
  - write_file
  - query_outline
  - query_characters
  - query_style
allowed-tools:
  - Bash(python:*)
  - Read
  - Write
---

# 章节写作功能

生成和润色小说章节内容。

## 功能概述

写作流程（Pipeline V2）：
1. **Director**: 组装上下文（大纲、角色、伏笔、世界观、风格）
2. **Writer (Librarian)**: 根据节拍生成草稿
3. **Reviewer (LoreChecker)**: 逻辑一致性检查
4. **User Review**: 人工审核
5. **Stylist**: 风格润色（可选）

## 节拍系统

章节写作基于**节拍（Beats）**：
- 每个节拍是一个剧情点
- 节拍由规则引擎生成，LLM 扩写为散文
- 节拍模板可在 `templates/beat_templates.yaml` 中自定义

### 节拍结构

```
ch_001 开场：承接上章尾声，{protagonist}面对{situation}
ch_001 发展1：{protagonist}采取行动推进目标，遭遇{obstacle}
ch_001 发展2：引入新信息/角色互动
ch_001 伏笔：自然融入伏笔元素
ch_001 高潮：核心冲突升级
ch_001 收束：冲突收束，制造悬念
```

## 使用方式

### 生成章节
用户说"写第X章"：
1. 加载章节大纲和上下文
2. 生成节拍列表
3. 扩写为草稿
4. 逻辑检查
5. 等待用户审核
6. 可选：风格润色

### 续写
用户说"续写"：
- 基于当前最新章节继续写作
- 自动确定章节编号

### 重写
用户说"重写第X章"：
- 加载已有草稿
- 根据用户反馈或检查结果重写

## 风格应用

写作时使用 `query_style` 获取作品专属风格：
- 共享技法（去AI味、套路、对话格式）
- 作品专属风格指纹

## 工作流

- `workflows/chapter_writing.yaml`: 完整章节写作流程

## 提示词

- `prompts/generate_chapter.md`: 生成草稿
- `prompts/rewrite_chapter.md`: 重写草稿

## 模板

- `templates/beat_templates.yaml`: 节拍模板
- `templates/section_markers.yaml`: 段落标记

## 数据格式

草稿存储在 `data/novels/{novel_id}/manuscript/` 目录：

```
manuscript/
├── arc_001/
│   ├── ch_001.md          # 最终版本
│   ├── ch_001_draft.md    # 初稿
│   └── ch_001_review.yaml # 审查记录
```
