---
name: oh-story-deslop
description: 诊断并精修网络小说中的机械 AI 读感，包括重复解释、句式过度齐整、对话同声、抽象判断、万能身体反应、空泛氛围和无功能金句。用于去 AI 味、自然化润色或在保留作者声音的前提下压缩文本。
license: MIT
metadata:
  openwrite:
    version: 0.7.2-openwrite.1
    agents: [dante, reviewer]
    allow_tools: ["*"]
    references: [references/method.md]
    budget:
      max_instruction_chars: 5000
      max_reference_chars: 6000
      max_tool_calls: 20
---

# Oh Story 去 AI 味

把 AI 味视为读感和叙事功能问题，不把词表命中当作错误。先确认用户要扫描、局部示范还是全文精修；默认先报告问题和样例，不擅自覆盖正文。

## 执行流程

1. 读取作者意图、人物声音、题材气质和当前段落功能，建立必须保留的内容。
2. 使用 `references/method.md` 扫描重复解释、句式齐整、对话同声、抽象判断和装饰性表达。
3. 按对读感的影响分级，优先修改高频且无功能的模式，不追求把所有句子变得不同。
4. 用最小改动恢复动作、选择、潜台词和节奏；结构或事实问题转交 `@oh-story-review`，不在润色中暗改。
5. 输出修改统计和少量前后对照；用户明确要求全文精修时才给完整候选稿。

## OpenWrite 边界

- 不改变事实、视角、人物动机、信息顺序、结局或已确认人物声音。需要改变时先作为建议提交。
- 不运行上游检查、标点归一化或禁词脚本；不创建豁免词文件。
- 正文写入继续遵守 OpenWrite workflow 与确认边界，只使用当前 Agent 已有工具。

本 Skill 改编自 [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode) 的 `story-deslop`，基于提交 `48a4789d1f542eb672addf8ccb5dbdc20e63be46`；MIT 许可见同目录 `LICENSE`。
