---
name: oh-story-long-scan
description: 研究长篇网文平台与榜单样本，分析读者契约、题材组合、主角机制、开篇兑现、更新阶段、升级空间和作者适配度。用于长篇扫榜、市场趋势观察、选题比较或开书前验证方向。
license: MIT
metadata:
  openwrite:
    version: 0.7.2-openwrite.1
    agents: [openwrite]
    allow_tools: ["*"]
    references: [references/method.md]
    budget:
      max_instruction_chars: 5000
      max_reference_chars: 6000
      max_tool_calls: 20
---

# Oh Story 长篇市场研究

把榜单当作有偏差的市场样本，不把排名本身当作选题答案。先确认平台、榜单口径、目标读者、题材范围、采样日期和作者自身优势。

## 执行流程

1. 收集可复核样本，并为每组数据记录平台、榜单类型、链接、访问日期、可见口径和样本量。
2. 使用 `references/method.md` 编码题材组合、情绪承诺、主角起点、核心机制、首个冲突、首次兑现和长期升级空间。
3. 先报告样本频次，再解释可能机制；把样本少的新组合标为信号，不直接称为趋势。
4. 输出多个选题候选，分别说明市场证据、作者适配、差异化、开篇验证方式、持续写作空间和风险。
5. 市场结论只作为规划阶段的讨论输入，不直接改写项目资产。

## 数据边界

- 不执行上游 Node、CDP 或平台抓榜脚本，不启动或重启浏览器，不绕过登录或访问限制。
- 只使用当前会话可访问、Deep Research 返回或用户提供的来源；无法获得实时数据时给研究框架和待查清单，不伪造最新榜单。
- 区分流量榜、付费榜、新书榜、完结榜和编辑推荐，说明推荐位、作者存量读者、热点事件等偏差。

本 Skill 改编自 [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode) 的 `story-long-scan`，基于提交 `48a4789d1f542eb672addf8ccb5dbdc20e63be46`；MIT 许可见同目录 `LICENSE`。
