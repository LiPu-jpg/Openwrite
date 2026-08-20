---
name: oh-story-review
description: 对网络小说大纲、章节或短篇成稿做证据化商业审稿，按事实连续性、因果、人物选择、读者契约、节奏、信息、对话和表达分级问题。用于章节验收、整稿诊断、投稿前审查或生成优先修订清单。
license: MIT
metadata:
  openwrite:
    version: 0.7.2-openwrite.1
    agents: [reviewer, dante]
    allow_tools: ["*"]
    references: [references/method.md]
    budget:
      max_instruction_chars: 5000
      max_reference_chars: 6000
      max_tool_calls: 20
---

# Oh Story 商业审稿

先确认审查对象、范围、目标读者和用户要“只诊断”还是“诊断后给修改稿”。默认只输出审查报告，不直接改动正文。

## 执行流程

1. 读取当前项目已确认资产、相关正文和审稿范围，先做缺失资料与冲突预检。
2. 使用 `references/method.md` 按阻断、严重、一般、润色四级检查，不让文风偏好掩盖事实或结构问题。
3. 每条发现给出位置或引文、问题、读者影响、证据和最小修复方向；证据不足时标记“需补充”。
4. 汇总最高优先级问题、可保留优点、建议修订顺序和仍需作者裁定的取舍。
5. 只有用户明确要求修改时才生成候选稿；涉及正式正文提交时继续走 OpenWrite workflow。

## OpenWrite 边界

- 以当前 `src/` 和已提交正文为事实基线，不把审稿偏好写成新设定。
- 不执行上游多 Agent、脚本或自动改稿协议；使用 OpenWrite 现有 Reviewer 和当前工具权限。
- 不因检查 AI 味而机械删除词语；表达层问题可转交 `@oh-story-deslop`。

本 Skill 改编自 [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode) 的 `story-review`，基于提交 `48a4789d1f542eb672addf8ccb5dbdc20e63be46`；MIT 许可见同目录 `LICENSE`。
