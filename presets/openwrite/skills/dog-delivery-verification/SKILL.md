---
name: dog-delivery-verification
description: 用宿主已安装的 dsh-dog（DoG / DDoG）对 OpenWrite 章节或整书做独立验证。Use when the author asks for DoG / 独立验收 / second-opinion verification before delivery, or when dog_validate, dog_create and dog_run are available and the author wants a judgment that is not the author's own review.
user-invocable: false
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# DoG 独立验收（OpenWrite → dsh-dog）

这条技能把 OpenWrite 的正文与评审证据交给宿主已安装的 `@dsh-external/dsh-dog`，
由它用独立 verifier 再判断一次。它不是 OpenWrite 六域评审的替代品，也不修改正文。

先确认工具面真的有 `dog_validate` / `dog_create` / `dog_run`。没有时不要假装跑过：
说明 dsh-dog 未安装或当前宿主不放行，回到 `novel_review_chapter` 与
`novel_export(action="preflight")` 的 OpenWrite 门禁。

> **运行环境要求**：`dsh-dog` 的 `agentic` 叶子会在当前宿主进程内启动隔离 verifier 子代理，
> 需要常驻宿主（如 `dsh web`）。在 `dsh --profile headless` 等一次性进程中退出会打断后台验证。

## 1. 收集被测对象与证据

单章：

1. `novel_outline_read` 与 `novel_status` 定位 `chapter_id`。
2. `novel_chapter_work` 读取正文 revision、评审新鲜度、本章义务。
3. `novel_review_chapter(action="versions", chapter_id=...)` 取最新评审；
   若正文 revision 与评审 revision 不一致，先重新评审，不要把旧评审当证据。
4. `novel_export(action="preflight", purpose="delivery")` 读取交付门禁和缺口。

整书：先 `novel_status`，再对每个已写章节重复上面的 2–4；不要把未写章节算进范围。

## 2. 建立不可变交付包（支持增量继承）

在**当前工作区根目录**下创建 `.openwrite/dog-handoff/<scope-id>/`（单章用章节 ID 如 `ch_001`，整书用 `book`），写入：

- 单章：写入 `manuscript.md`（逐字副本）与 `evidence.md`（outline 摘要、最新评审 revision/分数/门禁/问题、交付 preflight 缺口）。
- 整书：按已写章节分别写入 `ch_001.md`、`ch_002.md`… 与 `evidence.md`，在图中为每章建子 `composite` + 叶子（不要把全书塞进单个文件），这样后续只改某一章重跑时，未改动的章节会自动走 `inherited` 复用上次裁决，零额外模型开销。

注意：
- 用文件工具写，不要用 `novel_doc` 写项目外路径，也不要把手稿放进 `data/manuscript/`。
- **不要**把 `graph.json` 写进 `.openwrite/dog-handoff/<scope-id>/` 目录内（`root.target` 会打包捕获整个目录，把图定义放进去会污染目录摘要）。
- **同一章节/同一本书的多次修改再验收，应复用同一个 `graph.id` 与 `<scope-id>` 目录**：`dog_create` 会自动生成新 revision，未变更目标与指令的节点会 `inherited` 继承上次结果；只有**不同章节或不同作品**才使用不同的 `graph.id`。

## 3. 图模板（v0.9，带 `dependsOn` 门控）

单章示例（将 `ch_001` 替换为实际 `<scope-id>`；`target` 必须相对**会话工作区根目录**）：

```json
{
  "schemaVersion": "0.9",
  "id": "openwrite-delivery-ch_001",
  "root": "root",
  "nodes": {
    "root": {
      "kind": "composite",
      "title": "OpenWrite 交付整体判断",
      "constraint": "hard",
      "target": ".openwrite/dog-handoff/ch_001/",
      "completion": { "op": "all", "items": [
        { "op": "ref", "id": "delivery-evidence" },
        { "op": "ref", "id": "continuity" },
        { "op": "ref", "id": "prose" },
        { "op": "ref", "id": "canon" }
      ] },
      "verifier": {
        "mode": "agentic",
        "instruction": "Read manuscript.md and evidence.md in the captured handoff directory. Judge whether the chapter holds together as a deliverable: continuity, prose quality, canon consistency and the claimed delivery evidence. Return pass only when the evidence supports every claim; otherwise fail with the exact gap."
      }
    },
    "delivery-evidence": {
      "kind": "leaf", "title": "交付证据", "constraint": "hard", "target": ".openwrite/dog-handoff/ch_001/evidence.md",
      "verifier": { "mode": "agentic", "instruction": "Check whether evidence.md actually supports delivery: review revision matches the manuscript, gate status is pass, and no listed preflight gap remains. Do not accept a claim that is not backed by the evidence text." }
    },
    "continuity": {
      "kind": "leaf", "title": "连续性", "constraint": "hard", "target": ".openwrite/dog-handoff/ch_001/manuscript.md",
      "verifier": { "mode": "agentic", "instruction": "Check scene-to-scene continuity in manuscript.md: who is present, where, when, what changed, and whether any action contradicts the previous scene. Cite exact lines." }
    },
    "prose": {
      "kind": "leaf", "title": "文笔", "constraint": "hard", "target": ".openwrite/dog-handoff/ch_001/manuscript.md",
      "verifier": { "mode": "agentic", "instruction": "Judge prose quality in manuscript.md: viewpoint discipline, concrete detail, dialogue that carries character, and absence of filler or repeated exposition. Cite exact lines." }
    },
    "canon": {
      "kind": "leaf", "title": "正典一致性", "constraint": "hard", "target": ".openwrite/dog-handoff/ch_001/manuscript.md",
      "verifier": { "mode": "agentic", "instruction": "Check manuscript.md against the facts in evidence.md: names, world rules, timeline and stated canon. Report any contradiction with the exact conflicting lines." }
    }
  },
  "contains": [
    { "parent": "root", "child": "delivery-evidence", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "continuity", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "prose", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "canon", "required": true, "failure": "fatal" }
  ],
  "dependsOn": [
    { "source": "continuity", "target": "delivery-evidence" },
    { "source": "prose", "target": "delivery-evidence" },
    { "source": "canon", "target": "delivery-evidence" }
  ]
}
```

`dependsOn` 会先验证 `delivery-evidence`（评审新鲜度与 preflight 无阻断），通过后再并发跑 `continuity` / `prose` / `canon`，避免证据未就绪时浪费语义评审调用。对非阻断性的软维度（如局部文风润色建议），也可按需将 `failure` 设为 `"tolerable"` 或使用 `atLeast` / `any` 组合。

## 4. 运行、等待与取消

1. `dog_validate(graph)`：先静态校验，不写文件；有 schema 错误按返回信息修。
2. `dog_create(graph)`：在**会话工作区根目录**调用，捕获不可变副本并生成 revision。
3. `dog_run(graphId)`：后台启动验证，立即返回 `runId`（`state: "running"`）。
4. `dog_wait(runId)`：
   - 当宿主启用了后台任务服务（`dsh web` 默认启用），`dog_wait` 会**立即返回 `{ jobId, state: "running" }` 并注册后台 `"dog"` job**——此时**直接结束当前回复等待宿主完成通知唤醒**，**不要**循环轮询 `dog_status`，也**绝对不要**调用 `job_output(wait: true)`。
   - 仅当返回值没有 `jobId`（无 job 服务的独立进程）时，才按提示重复调用 `dog_wait(runId)` 直到终态。
5. 若作者中途要求中止或修改了正文导致本轮作废，调用 `dog_cancel(runId, reason)` 干净中止并释放子代理。
6. 终态后可用 `dog_status(runId)` 读取完整裁决与证据，逐节点报告 `verdict` 与 `evidence`；`needs_human` 原样交给作者，不猜；根节点通过才说“DoG 独立验收通过”。

## 5. 可选：DDoG 动态质量演进（`ddog_*`）

当作者在长篇连载中反复提出新的个性化审稿要求（或希望从历史返修失败案例中自动生长验收清单）时，`dsh-dog` 还提供动态 DoG 工具（存储于 `<project>/.dsh/ddog/graph.json`，与静态 v0.9 图互相独立，切勿把 DDoG 图传给 `dog_create`）：

- `ddog_init(instruction)`：根据作者的总体验收标准建立根节点（每个项目仅一次）。
- `ddog_expand(parentId, examples, source)`：用真实返修样本（`source="production"`）或模拟样本扩展候选子维度。
- `ddog_run` / `ddog_status`：运行动态验收并按失败率/一致性阈值自动晋升或淘汰候选节点。

## 约束

- DoG 只读捕获副本；不要用 DoG 的结论直接改正文。要改稿走
  `novel_change_plan` / `novel_revision` 的预览与确认流程。
- 不把 OpenWrite 自己的 `dog_review` / `dog_delivery` 产物冒充 dsh-dog 的运行结果；
  两者不是同一个引擎。
- 不因 `dog_*` / `ddog_*` 工具存在就自动跑模型；先向作者说明将调用独立 verifier（会产生模型调用），
  得到同意再运行。
