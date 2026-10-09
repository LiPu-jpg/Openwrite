---
name: dialoguequality
description: Use when analyzing dialogue style, extracting speech patterns, comparing character voices, or detecting AI-sounding dialogue. Triggers include "对话", "口头禅", "角色声音", "对白", "AI味对话", "dialogue".
---

# 对话质量系统

分析角色对白、提取说话习惯、检查角色声音区分度、识别 AI 味对话。

## 数据来源（按序）

1. `data/manuscript/arc_*/ch_*.md` — 实际章节正文
2. `src/characters/*.md` — 角色单源文档
3. `data/style/composed.md` — 作品风格约束
4. `src/outline.md` 或 openwrite-mcp `get_context_packet` — 本章戏剧位置与目标

不要只盯着几行对白下结论；完整判断结合整章 packet。

## 指纹指标

- `avg_sentence_length` — 句长偏短还是偏长
- `question_ratio` — 疑问句比例
- `common_bigrams` — 高频词组
- `speech_patterns` — 口头禅、重复习惯、语气特征

## AI 味对白模式（重点查）

- **过度礼貌**：熟人反复"请/劳烦/阁下"，说话像公文
- **解释性对话**：A 向 B 解释 B 本就知道的事；台词承担"给读者讲设定"任务
- **完美逻辑**：每句都有正面回应，没有打断、沉默、敷衍、转移话题
- **套路表达**："受教了""所言极是""我很生气""嘴角微微上扬""眼中闪过一丝"
- **角色同声化**：句长接近、用词层次相同、身份背景不反映在对白里

## 工作流

1. 从正文抽取该角色全部台词（标注段落定位）
2. 计算指纹指标，与人物卡对照（身份、性格、教育、职业是否一致）
3. 对照 `composed.md` 与章节戏剧位置
4. 输出：角色声音评价 → 问题清单（带定位）→ 修改建议（改写示例）

## 输出格式

```text
对话检查结果：ch_006 / 林月

1. 角色声音
- 句长偏短，命令句比例高，符合控制型表达
2. 问题
- 第3段解释性对话；第6段礼貌度偏高
3. 修改建议
- 删完整解释，改一句结论+一个动作
```

## 注意

- 指纹看"说话习惯"，整章审查看"对白在章内是否成立"
- 改对白必须结合人物文档与戏剧位置，不孤立改句子
