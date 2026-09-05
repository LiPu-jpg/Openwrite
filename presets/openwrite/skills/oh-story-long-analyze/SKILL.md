---
name: oh-story-long-analyze
description: 证据化拆解用户合法提供的长篇小说，分析开篇契约、逐章推进、剧情单元、人物关系、世界设定、情绪节奏、伏笔和表达技法。用于拆书、分析黄金开篇、建立对标报告或提炼可迁移模块。
license: MIT
metadata:
  openwrite:
    version: 0.7.2-openwrite.1
    agents: [openwrite]
    allow_tools: ["*"]
    references: [references/method.md]
    budget:
      max_instruction_chars: 5000
      max_reference_chars: 7000
      max_tool_calls: 20
---

# Oh Story 长篇拆解

把拆解视为只读、转化性的文学分析。先确认材料来源、用户有权使用的范围、章节边界和期望深度；材料不完整时标注限制，不用常识补齐原作事实。

## 执行流程

1. 先做作品概览与开篇样本，产出快速预览；除非用户明确要求完整拆解，否则在扩大到全书前停靠确认。
2. 使用 `references/method.md` 依次处理章节边界、开篇、逐章摘要、剧情聚合、人物设定、汇总报告和表达技法。
3. 每条硬事实标注可定位证据，区分原文事实、分析推断、迁移建议和待验证假设。
4. 把具体桥段抽象为功能位、情绪机制和输入输出条件，不生成可替代原作的逐章复述。
5. 数据量过大时分批推进并报告已覆盖范围、失败项和下一停靠点，不口头宣称全书完成。

## OpenWrite 边界

- 通过现有参考库保存与拆解材料，不创建上游 `拆文库/`、进度文件或自定义 Agent 目录。
- 参考作品默认不污染当前小说；候选方法进入规划讨论后仍需预览 diff 和明确确认。
- 不大段复制原文，不复制专名、独特设定、标志性场景或措辞到项目资产。
- 不执行上游提取脚本、hooks 或并行 Agent 协议；只使用当前 OpenWrite 工具。

本 Skill 改编自 [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode) 的 `story-long-analyze`，基于提交 `48a4789d1f542eb672addf8ccb5dbdc20e63be46`；MIT 许可见同目录 `LICENSE`。
