---
name: dog-review-query
description: Query an existing OpenWrite 37-dimension chapter review through dsh-dog. Use after novel_review_chapter or when the user asks to inspect review dimensions, evidence, inheritance, or the DoG graph. Do not run another 37-dimension model review.
---

# 37 维审查 DoG 查询

这个 Skill 只查询已经由 OpenWrite 生成的 37 维审查结果。OpenWrite 的
`novel_review_chapter` / conductor 是审查真源；DoG 负责把结果拆成 37 个可追踪
目标、保存证据、聚合状态和复用未变化的维度。

## 工作流

1. 如果本轮还没有评审结果，先按 Dante 正常流程调用 `novel_review_chapter`。
2. 找到评审输出目录中的 `dog-graph.json`。conductor 会在输出中打印 manifest
   路径；graph 与 `review.json`、`dim_01.json` … `dim_37.json` 在同一目录。
3. 读取 graph 后依次调用 `dog_validate`、`dog_create`、`dog_run`、`dog_wait`。
   `dog_run` 后必须等到终态，不能提前总结。
4. 用 `dog_status` 汇报根状态和每个维度的 evidence。`inherited` 表示对象和
   判据未变，复用了上一轮结果；`needs_human` 表示本次只审查了部分维度或
   verifier 无法判定，不能描述为通过。
5. 只有 OpenWrite 的审查问题才能进入 `novel_revisions_*` 回炉闭环。应用修订后
   必须复评，再用 `dog-delivery-query` 确认 `closure.closed`。DoG 的 `failure`
   只负责定位问题，不直接改正文或资产。

## 维度状态约定

- `pass`：该维度没有 critical/blocker 问题。
- `fail`：该维度至少有一个 critical/blocker 问题。
- `inconclusive`：该维度没有包含在本次部分审查中，或验证脚本无法读取记录。
- 根节点的 agentic whole-object assertion 只检查分数、总体 verdict、维度数量和
  各维度 verdict 是否自洽，不重新阅读正文。

## 边界

- 不要用 DoG verifier 直接调用 Studio 写入接口。
- 不要把 warning 自动升级成失败；先展示 evidence，由 `review_gate` 和作者决定。
- dsh-dog 的 agentic verifier 需要常驻 web/tui 会话；headless 导入流程不适合
  运行 `dog_run`。
