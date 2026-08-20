---
name: style-system
description: Use when user wants to initialize style, extract reusable writing signals from user-supplied text, compose a project style guide, or analyze style drift.
---

# 风格系统

## 核心原则

OpenWrite 不再内置任何参考作品风格库。  
风格来源只分三层：

```text
Layer 1: craft/                                  -> 通用技法与去模板化规则
Layer 2: data/novels/{id}/data/sources/{sid}/    -> 从用户提供文本提取出的 source pack
Layer 3: data/novels/{id}/src/**                 -> 本书确认版设定与约束
```

最终写作时，这三层会被合成为：

```text
data/novels/{id}/data/style/composed.md
```

## 目标

风格提取的目的不是“模仿某本书”，而是把用户提供文本里**可复用**的写法信号提出来，同时把**不可迁移**的作品特有信号隔离出去。

## Source Pack

每个提取源建议落到：

```text
data/novels/{novel_id}/data/sources/{source_id}/
├── source.md
├── setting_profile.md
├── style/
│   ├── summary.md
│   ├── voice.md
│   ├── language.md
│   ├── rhythm.md
│   ├── dialogue.md
│   ├── scene_templates.md
│   └── consistency.md
└── extraction/
    ├── progress.json
    ├── chunks/
    └── batch_results/
```

## 支持的动作

### 1. 风格初始化

输出：

- `data/novels/{id}/data/style/fingerprint.yaml`

### 2. 风格提取

输入必须来自用户自己提供的文本文件。

输出：

- `data/novels/{id}/data/sources/{source_id}/style/*.md`
- `data/novels/{id}/data/sources/{source_id}/setting_profile.md`
- `data/novels/{id}/data/sources/{source_id}/extraction/*`

### 3. 风格合成

读取：

- `craft/*`
- `data/novels/{id}/data/style/fingerprint.yaml`
- `data/novels/{id}/data/sources/{source_id}/style/*`
- `data/novels/{id}/src/**`

输出：

- `data/novels/{id}/data/style/composed.md`

### 4. 风格分析

读取目标文本、`composed.md`、`craft/ai_patterns.yaml`，输出偏差和改进建议。

## 提取规则

每个发现都要分成两类：

- `reusable`
  可迁移的写法、节奏、叙述距离、对话密度、结构习惯

- `source_bound`
  不应直接迁移的专名、角色口癖、专属组织、签名梗、作品特定世界规则

合成层只允许吸收 `reusable` 内容。

## 推荐格式

长期维护文档优先使用：

- `TOML front matter + Markdown 正文`

front matter 放：

- `id`
- `kind`
- `status`
- `source_type`
- `legal`
- `detail_refs`

正文放：

- summary
- reusable_signals
- source_bound_signals
- negative_rules
- promotion_notes

## 当前命令口径

- `openwrite style extract <source_id> --source <file>`
- `openwrite setting extract <source_id> --source <file>`
- `openwrite source review <source_id>`
- `openwrite source promote <source_id> --target all`
- `openwrite style synthesize`

其中 `source promote --target all` 会把：
- style 信号晋升到当前 `style_id`
- setting 提要并入 `foundation.md`
- rules / timeline / factions 按类型拆进 `src/world/*.md`

不要再使用“内置参考作品”“合成风格参考库”这类说法。
