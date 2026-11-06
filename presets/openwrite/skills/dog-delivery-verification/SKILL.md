---
name: dog-delivery-verification
description: 用宿主已安装的 dsh-dog（DoG）对 OpenWrite 章节或整书做独立验证。Use when the author asks for DoG / 独立验收 / second-opinion verification before delivery, or when dog_validate, dog_create and dog_run are available and the author wants a judgment that is not the author's own review.
user-invocable: false
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# DoG 独立验收（OpenWrite → dsh-dog）

这条技能把 OpenWrite 的正文与评审证据交给宿主已安装的 `@dsh-external/dsh-dog`，
由它用独立 verifier 再判断一次。它不是 OpenWrite 六域评审的替代品，也不修改正文。

先确认工具面真的有 `dog_validate` / `dog_create` / `dog_run`。没有时不要假装跑过：
说明 dsh-dog 未安装或当前宿主不放行，回到 `novel_review_chapter` 与
`novel_export(action="preflight")` 的 OpenWrite 门禁。

## 1. 收集被测对象与证据

单章：

1. `novel_outline_read` 与 `novel_status` 定位 `chapter_id`。
2. `novel_chapter_work` 读取正文 revision、评审新鲜度、本章义务。
3. `novel_review_chapter(action="versions", chapter_id=...)` 取最新评审；
   若正文 revision 与评审 revision 不一致，先重新评审，不要把旧评审当证据。
4. `novel_export(action="preflight", purpose="delivery")` 读取交付门禁和缺口。

整书：先 `novel_status`，再对每个已写章节重复上面的 2–4；不要把未写章节算进范围。

## 2. 建立不可变交付包

在**当前工作区根目录**下创建 `.openwrite/dog-handoff/<handoff-id>/`（示例用 `1`），写入：

- `manuscript.md`：被测正文的逐字副本（单章就是该章；整书按章节分隔）。
- `evidence.md`：outline 摘要、最新评审的 revision/分数/门禁/问题、交付 preflight 缺口。
- `graph.json`：下面的 0.9 图。`target` 必须是相对**会话工作区根目录**的路径，不是相对 handoff 目录；
  root 指向 handoff 目录（dog 会把目录打包捕获），叶子分别指向其中的 `manuscript.md` / `evidence.md`。

用文件工具写，不要用 `novel_doc` 写项目外路径。`handoff-id` 用时间戳或短随机串，
保留目录供审计；不要把它放进 `data/manuscript/`。

## 3. 图模板

```json
{
  "schemaVersion": "0.9",
  "id": "openwrite-delivery-1",
  "root": "root",
  "nodes": {
    "root": {
      "kind": "composite",
      "title": "OpenWrite 交付整体判断",
      "constraint": "hard",
      "target": ".openwrite/dog-handoff/1/",
      "completion": { "op": "all", "items": [
        { "op": "ref", "id": "continuity" },
        { "op": "ref", "id": "prose" },
        { "op": "ref", "id": "canon" },
        { "op": "ref", "id": "delivery-evidence" }
      ] },
      "verifier": {
        "mode": "agentic",
        "instruction": "Read manuscript.md and evidence.md in the captured handoff directory. Judge whether the chapter(s) hold together as a deliverable: continuity, prose quality, canon consistency and the claimed delivery evidence. Return pass only when the evidence supports every claim; otherwise fail with the exact gap."
      }
    },
    "continuity": {
      "kind": "leaf", "title": "连续性", "constraint": "hard", "target": ".openwrite/dog-handoff/1/manuscript.md",
      "verifier": { "mode": "agentic", "instruction": "Check scene-to-scene continuity in manuscript.md: who is present, where, when, what changed, and whether any action contradicts the previous scene. Cite exact lines." }
    },
    "prose": {
      "kind": "leaf", "title": "文笔", "constraint": "hard", "target": ".openwrite/dog-handoff/1/manuscript.md",
      "verifier": { "mode": "agentic", "instruction": "Judge prose quality in manuscript.md: viewpoint discipline, concrete detail, dialogue that carries character, and absence of filler or repeated exposition. Cite exact lines." }
    },
    "canon": {
      "kind": "leaf", "title": "正典一致性", "constraint": "hard", "target": ".openwrite/dog-handoff/1/manuscript.md",
      "verifier": { "mode": "agentic", "instruction": "Check manuscript.md against the facts in evidence.md: names, world rules, timeline and stated canon. Report any contradiction with the exact conflicting lines." }
    },
    "delivery-evidence": {
      "kind": "leaf", "title": "交付证据", "constraint": "hard", "target": ".openwrite/dog-handoff/1/evidence.md",
      "verifier": { "mode": "agentic", "instruction": "Check whether evidence.md actually supports delivery: review revision matches the manuscript, gate status is pass, and no listed preflight gap remains. Do not accept a claim that is not backed by the evidence text." }
    }
  },
  "contains": [
    { "parent": "root", "child": "continuity", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "prose", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "canon", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "delivery-evidence", "required": true, "failure": "fatal" }
  ],
  "dependsOn": []
}
```

每次 handoff 必须把示例里的 `1` 同时替换成同一个唯一值（graph.id 与所有 target），
否则第二次 `dog_create` 会和上一张图撞 id。`dog_create` 在**会话工作区根目录**调用；
上面的 target 已经带上 `.openwrite/dog-handoff/1/`，不需要先 cd 进 handoff 目录。
如果只验单章，删掉整书范围描述即可，不要为了凑节点加空 verifier。

## 4. 运行与报告

1. `dog_validate(graph)`：先只校验，不运行；有 schema 错误按返回信息修。
2. `dog_create(graph)`：捕获不可变副本，记下 graphId。
3. `dog_run(graphId)`，然后 `dog_wait` 或轮询 `dog_status`，直到终态。
4. 逐节点报告 verdict 与 evidence；`needs_human` 原样交给作者，不猜。
5. 根节点通过才说“DoG 独立验收通过”。任何 fatal / needs_human 都必须说明具体子目标。

## 约束

- DoG 只读捕获副本；不要用 DoG 的结论直接改正文。要改稿走
  `novel_change_plan` / `novel_revision` 的预览与确认流程。
- 不把 OpenWrite 自己的 `dog_review` / `dog_delivery` 产物冒充 dsh-dog 的运行结果；
  两者不是同一个引擎。
- 不因 `dog_*` 工具存在就自动跑模型；先向作者说明将调用独立 verifier（会产生模型调用），
  得到同意再运行。
