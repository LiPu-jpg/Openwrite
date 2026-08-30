---
name: dog-review-query
description: Query an existing hierarchical OpenWrite review-v2 artifact through dsh-dog. Use after novel_review_chapter or when inspecting six quality domains, evidence, coverage, blockers, delivery status, or the 37 legacy checks. Never rerun model review from DoG.
---

# 分层评审 DoG 查询

这个 Skill 只查询 OpenWrite 已物化的 review-v2 artifact。OpenWrite 的
`novel_review_chapter` / conductor 是评审真源；DoG 读取 47 节点分层图：上下文、
六个质量域、硬门禁、确定性聚合和 37 个兼容查询 leaf。DoG 不调用评审模型。

## 工作流

1. 如果本轮还没有评审结果，先按 Dante 正常流程调用 `novel_review_chapter`。
2. 找到评审输出目录中的 `dog-graph.json`。graph 与 `review.json`、`context.json`、
   `domain-*.json`、`gate.json`、`aggregate.json` 和 `dim_01.json` …
   `dim_37.json` 在同一目录。
3. 读取 graph 后依次调用 `dog_validate`、`dog_create`、`dog_run`、`dog_wait`。
   所有节点均使用 programmatic `review-record` verifier；`dog_run` 后必须等到终态。
4. 用 `dog_status` 分别汇报 `qualityScore`、`coverage`、`gateStatus` 和
   `deliveryStatus`，再按需展开域、criterion、evidence、issue 和 legacy ID。
   `inconclusive` 表示覆盖不足、未请求或 artifact 不可判定，不能描述为通过。
5. 只有 OpenWrite 的审查问题才能进入 `novel_revisions_*` 回炉闭环。应用修订后
   必须复评，再用 `dog-delivery-query` 确认 `closure.closed`。DoG 的 `failure`
   只负责定位问题，不直接改正文或资产。

## 状态约定

- `qualityScore` 是有可定位正文证据的正向累加分；issue 不直接扣分。
- `coverage` 单独表达实际完成的评审范围；`inconclusive` 会降低覆盖率。
- `gateStatus=blocked` 来自 hard-gate 或 critical finding，不改写质量分。
- `deliveryStatus` 综合质量、覆盖、门禁和正文 SHA 新鲜度；它不是 `passed` 的别名。
- 37 个 leaf 是 `legacy_check_ids` 查询入口，不是 37 个顶层计分维度。

## 边界

- 不要用 DoG verifier 直接调用 Studio 写入接口。
- 不要把 warning 自动升级成失败；先展示 evidence，由 `review_gate` 和作者决定。
- 不要用 `dog_run` 生成、补写或刷新评审；artifact 缺失或 stale 时回到 OpenWrite 流程。
