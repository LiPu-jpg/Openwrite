---
name: style-system
description: Use when initializing writing style, extracting reusable signals from user-supplied text, composing a project style guide, or analyzing style drift. Triggers include "风格", "style", "提取风格", "风格指纹", "风格漂移".
---

# 风格系统

## 三层来源（无内置参考库）

```text
Layer 1: craft/                                通用技法与去模板化规则
Layer 2: data/novels/{id}/data/sources/{sid}/  用户文本提取的 source pack
Layer 3: data/novels/{id}/src/**               本书确认版设定与约束
```

合成产物：`data/novels/{id}/data/style/composed.md`（写作与润色的唯一风格基准）。

## 目标

把用户提供文本里**可复用**的写法信号提出来，把**不可迁移**的作品特有信号隔离出去。提取不是模仿，是信号分离。

## Source Pack 结构

`data/novels/{novel_id}/data/sources/{source_id}/`：`source.md` / `setting_profile.md` / `style/{summary,voice,language,rhythm,dialogue,scene_templates,consistency}.md` / `extraction/`（进度、分块、批次结果）。

## 动作

1. **初始化** → `data/style/fingerprint.yaml`
2. **提取**（输入必须为用户提供的文本）→ source pack 全套产物
3. **合成**（读 craft/* + fingerprint + source style/* + src/**）→ `composed.md`
4. **分析**（读目标文本 + composed.md + craft/ai_patterns.yaml）→ 偏差与改进建议

## 提取分类规则

每个发现分两类：
- `reusable` — 可迁移的写法、节奏、叙述距离、对话密度、结构习惯
- `source_bound` — 专名、角色口癖、专属组织、签名梗、作品特定规则

合成层只允许吸收 `reusable`。

## 长期文档格式

`TOML front matter + Markdown 正文`；front matter 放 id/kind/status/source_type/legal/detail_refs；正文放 summary/reusable_signals/source_bound_signals/negative_rules/promotion_notes。

## 蜂群接入

reviewer-prose 以 `composed.md` + `fingerprint.yaml` 为文风基准核对正文；写章上下文中由 `get_context_packet` 携带风格分区。
