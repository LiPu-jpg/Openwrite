---
name: oh-story-long-write
description: 规划和创作长篇网络小说，覆盖选题定位、读者契约、人物与世界设定、卷纲细纲、单章写作、日更续写和结构修订。用于开书、补纲、写指定章节、续写或回炉长篇正文。
license: MIT
metadata:
  openwrite:
    version: 0.7.2-openwrite.1
    agents: [goethe, dante]
    allow_tools: ["*"]
    references: [references/method.md]
    budget:
      max_instruction_chars: 5000
      max_reference_chars: 7000
      max_tool_calls: 20
---

# Oh Story 长篇写作

先读取当前作品状态和用户本轮目标，再选择开书、补纲、写指定章、续写或修订。裸调用时只诊断所处阶段并给出下一步，不自动生成正文。

## 执行流程

1. 明确本轮交付范围和停靠点。用户没有指定正文数量时最多处理一章；只要求规划时停在候选或大纲交付。
2. 让 Goethe 处理读者契约、人物、世界、关系、全书阶段、卷纲和细纲；让 Dante 根据已确认资产写正文或做局部修订。
3. 使用 `references/method.md` 检查情绪承诺、主角代理权、冲突升级、剧情单元和章末钩子。
4. 写章前只召回不知道就会写错的资料：当前细纲、最近正文、出场人物状态、相关规则、伏笔和当前关注点。
5. 写完检查事实连续性、角色选择、信息变化、情绪结算和章节状态；结构问题优先于句子润色。

## OpenWrite 边界

- 把 `src/` 视为确认版真源，把 `data/` 视为正文、运行态和派生数据。不要创建上游的 `设定/`、`对标/`、`拆文库/` 或追踪文件结构。
- 对大纲、人物、世界、关系等正式资产先提交候选和 diff，只在用户本轮明确确认后写入。
- 缺少可写细纲、章节编号冲突或需要改变已确认设定时停止正文，转回 Goethe 讨论。
- 只使用当前 Agent 已有工具；不执行上游 hooks、脚本或安装流程。

本 Skill 改编自 [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode) 的 `story-long-write`，基于提交 `48a4789d1f542eb672addf8ccb5dbdc20e63be46`；MIT 许可见同目录 `LICENSE`。
