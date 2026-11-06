---
name: review-artifact-query
description: Query an existing hierarchical OpenWrite review-v2 artifact. Use after novel_review_chapter or when inspecting six quality domains, evidence, coverage, blockers, delivery status, or the 37 legacy checks. Never rerun model review from this skill.
user-invocable: false
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 分层评审产物查询

这个 Skill 只查询 OpenWrite 已物化的 review-v2 artifact。OpenWrite 的
`novel_review_chapter` / conductor 是评审真源；本 Skill 直接读同一批产物：
`review.json`、`context.json`、`domain-*.json`、`gate.json`、`aggregate.json` 和
`dim_01.json` … `dim_37.json`。它不调用评审模型，也不改写任何产物。

## 查询流程

1. 如果本轮还没有评审结果，先按 OpenWrite 写作流程调用 `novel_review_chapter`。
2. 从评审输出（或工具响应里的 `dog_review`）找到产物目录；`review.json` 与
   `domain-*.json`、`gate.json`、`aggregate.json`、`dim_01.json` … `dim_37.json`
   在同一目录。
3. 读取 `aggregate.json` 汇报 `qualityScore`、`coverage`、`gateStatus` 和
   `deliveryStatus`，再按需展开域、criterion、evidence、issue 和 legacy ID。
   `inconclusive` 表示覆盖不足、未请求或 artifact 不可判定，不能描述为通过。
4. 只有 OpenWrite 的审查问题才能进入 `novel_revision` 回炉闭环。应用修订后
   必须复评，再用 `delivery-artifact-query` 确认 closure 已关闭。评审的 `failure`
   只负责定位问题，不直接改正文或资产。

## 状态约定

- `qualityScore` 是有可定位正文证据的正向累加分；issue 不直接扣分。
- `coverage` 单独表达实际完成的评审范围；`inconclusive` 会降低覆盖率。
- `gateStatus=blocked` 来自 hard-gate 或 critical finding，不改写质量分。
- `deliveryStatus` 综合质量、覆盖、门禁和正文 SHA 新鲜度；它不是 `passed` 的别名。
- 37 个 leaf 是 `legacy_check_ids` 查询入口，不是 37 个顶层计分维度。

## 边界

- 只读：不调用 Studio 写入接口，不重新生成、补写或刷新评审。
- artifact 缺失或 stale 时回到 OpenWrite 流程重新评审，不要把旧结果说成最新。
- 不要把 warning 自动升级成失败；先展示 evidence，由 `gate.json` / `aggregate.json` 里的 `gateStatus` 和作者决定。
