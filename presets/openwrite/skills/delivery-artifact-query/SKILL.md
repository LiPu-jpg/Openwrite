---
name: delivery-artifact-query
description: Query a chapter delivery record across manuscript, review, revision application, and re-review closure. Use after writing or reviewing a chapter, after revision actions, or when the user asks whether a chapter is truly ready to deliver.
user-invocable: false
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 章节交付状态查询

章节写作、评审和修订工具会直接返回交付状态，并把同一份记录落盘：
`data/novels/{id}/data/dog/deliveries/{chapter}/dog-graph.json`。
它覆盖六个阶段：`writing → review → revision → application → rereview → closure`。
它不替代 OpenWrite 的写章、六域累加评审或修订服务。

## 查询流程

1. 从最近一次 `novel_write_chapter`、`novel_review_chapter`、`novel_revision`
   或 `novel_task(action="get")` 结果里的 `dog_delivery` 读状态；需要完整阶段明细时再读
   上面的 `dog-graph.json`（`stages` 里有每一阶段的 verdict 与 evidence）。
2. 按 `closure` 的状态给结论（见下表），不要自行推断。
3. 修订应用后必须重新调用 `novel_review_chapter`；只有复评对应当前正文 SHA 且门禁通过，
   `closure` 才能成为 `closed`。

## 状态解释

- `review.missing`：正文存在但尚未评审。
- `closure.review_failed`：当前正文已评审但未通过门禁，进入修订闭环。
- `revision.proposal_pending`：提案已生成，等待作者确认应用或驳回。
- `revision.applied_requires_rereview`：修订已写入正文，但不能视为问题已解决。
- `closure.rereview_required`：必须对修订后的正文重新跑六域评审。
- `closure.closed`：当前正文的最新评审通过，可以交付。

`readyForDelivery=true` 等价于「当前正文 SHA 的最新复评通过且门禁通过」，
可以直接作为交付结论；为 `false` 时说明上面某一项未满足。

## 约束

- 只查询 canonical manuscript/review/revision 文件，不直接修改它们。
- 不因提案状态为 `applied` 就宣称问题关闭；必须以当前正文 SHA 对应的复评为准。
- 记录缺失时回到 OpenWrite 流程重新评审，不要把上一次的结论说成最新。
