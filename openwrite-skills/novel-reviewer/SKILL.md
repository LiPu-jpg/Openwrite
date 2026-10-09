---
name: novel-reviewer
description: Use when checking chapter logic consistency, polishing style, finding plot holes, or running the six-domain review. Triggers include "检查", "润色", "逻辑", "伏笔漏洞", "审查", "review chapter".
---

# 小说审查（六域）

OpenWrite 标准章节审稿（`openwrite.standard-chapter-review` v1.0.0）的技能面。完整审查编排六域；轻量场景可按域单独调用。

## 评审蓝图（权威拓扑）

用 openwrite-mcp `get_review_framework` 获取 47 节点蓝图（节点、依赖、评分准则、修订号）。
六域划分（每域含 legacy 检查项与加法评分准则）：

| 域 | 负责评审员（蜂群） | 关注点 |
|---|---|---|
| 连贯与逻辑 | reviewer-canon | 时间线、因果链、知识边界 |
| 正典与资料 | reviewer-canon | truth/ledger、世界观实体、伏笔 DAG |
| 情节与承诺 | reviewer-drama | 章级承诺兑现、新承诺登记 |
| 节奏与场景 | reviewer-drama | 场景功能、信息释放、钩子 |
| 角色与关系 | reviewer-prose | 对话声口、关系图谱 |
| 文风与表达 | reviewer-prose | 风格指纹偏差、AI 痕迹 |

前置节点：上下文完整性（正文版本与评审基线校验）；后置：硬门禁（不混分）+ 聚合交付判定。

## 逻辑检查清单

- 时间线一致性（事件顺序、天数）
- 角色状态变异：获得物品/使用技能/移动位置/生命状态/境界
- 伏笔回收状态：待回收是否超期、回收是否合理
- 世界观规则是否违反设定
- 每个 finding 附正文引文 + 设定条目 id（证据可溯源）

## 风格检查清单

- AI 痕迹（套路词库见 post-validation 技能；等长段落变异系数、套话密度、公式化转折、列表式结构）
- 声音一致性（叙述者与角色声音融合）
- 信息倾倒、节奏分布、对话风格

## 输入获取

| 需求 | 来源 |
|---|---|
| 章节正文 | `data/novels/{id}/data/manuscript/arc_*/ch_*.md` |
| 全量上下文 | openwrite-mcp `get_context_packet` |
| 事实裁判 | `get_truth` + `get_chapter_foreshadowing` |
| 风格基准 | `data/novels/{id}/data/style/composed.md` |
| 评审蓝图 | `get_review_framework` |

## 输出格式（per-domain）

```markdown
### <域名>
- score: <0-10>
- findings:
  - [severity: blocker|major|minor] <问题> — 证据：<正文引文 + 条目 id>
- not_checked: <项或"无">
```

## 审查模式

| 模式 | 严格度 |
|---|---|
| 宽松 | 仅 blocker 阻塞 |
| 标准 | blocker + major 阻塞（默认） |
| 严格 | 警告也阻塞 |

## 纪律

- 未检查的项显式标 `not_checked`，不假装覆盖
- 评审不修改正文；修订走 revision-forge + 作者确认门
- 润色基于已合成的 `composed.md`，不重新组装风格
