# Execution Guardrails

## Resource Constraints

| Item | Limit | Reason |
|---|---|---|
| `max_parallel_teammates` | 3 | 与 workflow.md 的六域评审三路并行一致 |
| `total_wall_clock_budget` | 90 min | 单章完整一轮（写作+评审+最多 2 轮修订复评）的上限 |
| `total_token_budget` | 500k tokens | 主笔 150k + 每评审员 60k + 修订匠 80k + 规划师 90k 的合计上限 |
| `max_rework_rounds` | 2 | 修订-复评回炉上限，超过即降级 D2 |
| `min_domain_score` | 6 | 聚合门使用的单域最低通过分（0-10） |
| `max_placeholder_ratio` | 0 | 硬门禁：正文中占位符/TODO 容忍度为零 |

## Behavioral Constraints

- **Leader-as-orchestrator only**：Leader 只做派发、确定性聚合（Step 5 规则）与报告汇编，不写正文、不出评审意见、不代替作者门做决定。
- **评审隔离**：三个 reviewer 互相看不到彼此结论，也看不到主笔的过程稿说明——只消费同一正文基线与各自域资产。隔离是评审价值的一部分：合并评审会让单 Agent 的写作思路污染评审结论（本蜂群要解决的失败模式之一）。
- **写审分离**：主笔 MUST NOT 自审；评审员 MUST NOT 改正文；修订匠 MUST NOT 复评。质量判定的接力棒只能单向传递。
- **资产所有权**：大纲/人物/世界观只有 goethe-planner 可写；正文基线只有 dante-writer 与修订匠（经作者门后）可写；设定级异议一律登记 `planner-return` 回流，禁止越权直改。
- **最小手术**：修订匠的每条改动必须挂接 finding；超出 finding 范围的"顺手优化"视为违规改动，作者门应拒绝。
- **HITL 不旁路**：有人值守模式下，大纲定稿与修订应用必须过 author-gate；无人值守批量模式（对应 OpenWrite conductor）可关闭作者门，但报告中必须标注 `UNATTENDED`。

## Failure Handling

### (a) Teammate failure

| Failure mode | Response |
|---|---|
| 评审员超时 | 重派 1 次（仅此 1 次）。第 2 次超时，该评审员的 2 个域标 `inconclusive`，聚合门禁止判 PASS |
| 输出不符合 Output Schema | 将 schema 内联进派发 prompt 并附"上次输出格式错误"前言重派 1 次；再错标 `[ROLE MISSING — malformed output]`，其域按 inconclusive 处理 |
| 主笔硬门禁不过（字数/占位符） | 重派 1 次并附未过项清单；再不过本章判 `FAILED`，回报作者 |
| 主笔登记 CONFLICT（设定冲突） | 本章暂停，生成 `planner-return` 转规划资产修订，修订后重派本章 |
| 修订匠 hard-block（无法最小化修复的 blocker） | 不上交半成品：标 `DELIVERED-WITH-BLOCKERS`，hard-block 逐条列给作者 |
| author-gate 悬置超时（默认 24h，可配） | 视为驳回：大纲门回 Step 1，修订门按 REJECT 处理（不应用修订） |

### (b) Input over-scale degradation

| Trigger condition | Degraded mode |
|---|---|
| 单章要求字数 > 10000 | 拆分为多章走正常流程；无法拆分则主笔加派接力写作，中间状态写入章节记忆 |
| 作品已有章节 > 30 章且上下文包超限 | canonical packet 改用章节记忆压缩态（OpenWrite bounded chapter summary），评审依据摘要 + 按需回查原文 |
| OpenWrite 技能依赖缺失（pre-flight 失败但用户选择继续） | inline-persona-only 模式：teammates 凭内联人设工作，资产读写由 Leader 代理；报告头标 `DEGRADED: no openwrite skills` |
| 无人值守批量（conductor 模式） | 作者门关闭，修订自动应用；报告中逐章标 `UNATTENDED`，事后人工抽查 |

### Escalation rules

- 两个及以上评审员同时 `[ROLE MISSING]` → 本轮评审作废重派，重派仍失败判 `FAILED`。
- `total_token_budget` 超限时：停发新派发，在途任务跑完，报告标 `INCOMPLETE: token budget exceeded`。
- `total_wall_clock_budget` 超限时：中断当前轮，输出已完成的最近一个完整轮结果，标 `INCOMPLETE: time budget exceeded`。
