---
name: dog-delivery-query
description: Query a chapter delivery DoG graph across manuscript, review, revision application, and re-review closure. Use after writing or reviewing a chapter, after revision actions, or when the user asks whether a chapter is truly ready to deliver.
---

# 章节交付 DoG 查询

章节写作、评审和修订工具会生成：

`data/novels/{id}/data/dog/deliveries/{chapter}/dog-graph.json`

这张图查询六个阶段：`writing → review → revision → application → rereview → closure`。
它不替代 OpenWrite 的写章、六域累加评审或修订服务。

## 查询流程

1. 从最近一次 `novel_write_chapter`、`novel_review_chapter`、`novel_revision_*`
   或 `novel_task_get` 结果的 `dog_delivery.graphPath` 找到图；conductor 输出使用
   `dog_delivery_graph_path`。
2. 依次调用 `dog_validate`、`dog_create`、`dog_run`、`dog_wait`，等待终态。
3. 用 `dog_status` 读取 `review`、`revision` 和 `closure` evidence，再决定领域动作。
4. 修订应用后必须重新调用 `novel_review_chapter`；只有复评对应当前正文 SHA 且门禁通过，
   `closure` 才能成为 `closed`。

## 状态解释

- `review.missing`：正文存在但尚未评审。
- `closure.review_failed`：当前正文已评审但未通过门禁，进入修订闭环。
- `revision.proposal_pending`：提案已生成，等待作者确认应用或驳回。
- `revision.applied_requires_rereview`：修订已写入正文，但不能视为问题已解决。
- `closure.rereview_required`：必须对修订后的正文重新跑六域评审。
- `closure.closed`：当前正文的最新评审通过，可以交付。

## 约束

- DoG 只查询 canonical manuscript/review/revision 文件，不直接修改它们。
- 不因提案状态为 `applied` 就宣称问题关闭；必须以当前正文 SHA 对应的复评为准。
- `needs_human` 是等待评审、确认或复评，不得描述成成功。
- 应用或驳回修订仍遵守 OpenWrite 创作 Agent 的用户确认边界。
