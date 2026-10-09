---
name: openwrite-novel-swarm
description: |
  7-role mixed-pattern novel production swarm (规划师 + 主笔 + 3 个六域评审员 + 修订匠 + 作者确认门, 6 AI teammate + 1 human gate), ported from the OpenWrite long-form fiction engine onto the openJiuwen native stack.
  Use when the user wants to plan, write, review, and revise long-form fiction with a multi-agent team instead of a single writing agent.
  Do NOT use for single short texts without review/revision loops, or for non-fiction documents.
version: "0.1"
kind: swarm-skill
roles:
  - id: goethe-planner
    kind: ai_agent
    purpose: 收敛创作意图，产出人物卡、世界观与卷/幕/节/章分层大纲，是全书唯一规划真源。
    skills: [goethe-agent, novel-manager]
    tools: [python, openwrite-mcp]
  - id: dante-writer
    kind: ai_agent
    purpose: 按大纲与设定消费 canonical context packet 撰写章节正文，不改动上游设定。
    skills: [novel-creator, text-processing]
    tools: [python, openwrite-mcp]
  - id: reviewer-canon
    kind: ai_agent
    purpose: 审查连贯与逻辑、正典与资料两域，核对 truth/ledger、世界观实体与伏笔 DAG 的一致性。
    skills: [world-query, truth-validation, foreshadowing-system]
    tools: [python, openwrite-mcp]
  - id: reviewer-drama
    kind: ai_agent
    purpose: 审查情节与承诺、节奏与场景两域，检验大纲承诺兑现、因果链与场景调度。
    skills: [novel-reviewer, dialoguequality]
    tools: [python, openwrite-mcp]
  - id: reviewer-prose
    kind: ai_agent
    purpose: 审查角色与关系、文风与表达两域，核对人物声口、关系图谱与风格指纹一致性。
    skills: [style-system, post-validation]
    tools: [python, openwrite-mcp]
  - id: revision-forge
    kind: ai_agent
    purpose: 把评审聚合判定转成结构化修订计划并最小化改稿，不做新评审、不改设定。
    skills: [text-processing]
    tools: [python, openwrite-mcp]
  - id: author-gate
    kind: human_agent
    purpose: 作者在两个确认门做决定：大纲资产包定稿前、修订计划应用前（预览 diff 后批准或驳回）。
    skills: []
    tools: []
---

# OpenWrite 长篇创作蜂群

把 OpenWrite 小说引擎的单体编排升级为 JiuwenSwarm 多智能体团队：混合模式（专精流水线 C + 并行分解 B + 主笔/评审对抗隔离 A）。它解决单 Agent 创作的两个失败模式——评审被自己的写作思路污染（盲视自己的伏笔漏洞），以及写-审-修串行拉长导致长程一致性崩溃。六域评审拓扑继承 OpenWrite 的 `review-dag-framework.v1`。

## Workflow

0. **Pre-flight: check dependencies** — 读 [dependencies.yaml](dependencies.yaml) 逐项核对。
   `required: true` 缺失 = 大概率失败；`required: false` 缺失 = 降级但仍可运行。**由用户决定**是否继续。
   所有 OpenWrite 本地技能缺失时可退回 inline-persona-only 模式（ teammates 凭内联人设工作，工具调用由 Leader 代理）。

1. **规划资产包** — Leader 派 `goethe-planner`：收敛题材与创作意图 → 人物卡 → 世界观实体 → 卷/幕/节/章分层大纲。
   质量门：大纲含 ≥1 卷、章节级叶子节点非空、人物卡 ≥1。未过门重派一次，再失败按 [bind.md](bind.md) 降级。
   通过后送 `author-gate`：作者确认或驳回大纲（驳回附意见，回 Step 1）。详见 [workflow.md](workflow.md)。

2. **章节写作** — Leader 派 `dante-writer`：按 OpenWrite canonical packet（正文基线 + 章节记忆 + 风格指纹 + 伏笔待办 + truth 状态）撰写单章。
   硬门禁：正文字数达纲、上下文基线 revision 匹配、无占位符文本。未过门重派一次。

3. **六域并行评审** — Leader 同时派 `reviewer-canon`、`reviewer-drama`、`reviewer-prose`。
   三评审互相隔离、也看不到主笔过程稿，只消费同一正文基线与各自域的资产。每域返回结构化评分 + 证据 + blocker 列表。
   门：覆盖率 = 6/6 域；缺失域按 [bind.md](bind.md) 标 `inconclusive` 重派一次。

4. **聚合判定** — Leader 按确定性规则聚合（不写作文本）：blocker 数、各域质量分、覆盖率。
   规则见 [workflow.md](workflow.md) § Step 4。通过 → Step 6；不通过 → Step 5。

5. **修订与复评** — Leader 派 `revision-forge` 生成结构化修订计划（逐条挂接评审证据）→ 送 `author-gate` 预览 diff 并批准 → 应用修订 → 只对未过域重派评审。
   回炉上限 2 轮，仍不过则降级为带 blocker 的人工交付（见 [bind.md](bind.md)）。

6. **交付结算** — Leader 产出章节交付报告：正文版本、六域评分与证据、门禁记录、修订历史、伏笔/正典回写清单。

7. **写回引擎（可选，经 openwrite-mcp）** — 需要把蜂群产物落成 OpenWrite 真书时，Leader 经 MCP 工具链执行：
   `create_project` 建书 → `save_foundation_draft`/`promote_foundation`（两阶段门）→
   `save_outline_draft`/`promote_outline`（两阶段门 + revision 重验）→ 人物卡写入
   `src/characters/` → `save_external_chapter` 入库 → `manuscript_status` →
   `accept_manuscript`（指纹门，confirm 两阶段）→ `resume_acceptance` 事实重建 →
   `acknowledge_impacts` 作者复核 → 后续章节可交引擎 `write_chapter`/`review_chapter` 原生续写 →
   `export_book` 出 EPUB。写路径工具缺失时跳过本步，交付物为纯文本报告（降级见 bind.md）。
   完整实录见 docs/创意提交材料.md「旗舰 DEMO《夜班便利店》」。

## Roles

| id | Purpose | When dispatched | Input | Key dependencies | Role file |
|---|---|---|---|---|---|
| goethe-planner | 规划全书资产包 | 每部作品开始时，或被驳回回炉时 | 创作意图、题材约束 | goethe-agent / novel-manager / python | [roles/goethe-planner.md](roles/goethe-planner.md) |
| dante-writer | 撰写章节正文 | 大纲确认后，每章一次 | 大纲资产包、canonical context packet | novel-creator / text-processing / python | [roles/dante-writer.md](roles/dante-writer.md) |
| reviewer-canon | 连贯逻辑 + 正典资料双域评审 | 每章成稿后，与另两评审并行 | 正文基线、truth/ledger、世界观、伏笔 DAG | world-query / truth-validation / foreshadowing-system / python | [roles/reviewer-canon.md](roles/reviewer-canon.md) |
| reviewer-drama | 情节承诺 + 节奏场景双域评审 | 每章成稿后，与另两评审并行 | 正文基线、大纲承诺、场景结构 | novel-reviewer / dialoguequality / python | [roles/reviewer-drama.md](roles/reviewer-drama.md) |
| reviewer-prose | 角色关系 + 文风表达双域评审 | 每章成稿后，与另两评审并行 | 正文基线、人物卡、风格指纹 | style-system / post-validation / python | [roles/reviewer-prose.md](roles/reviewer-prose.md) |
| revision-forge | 修订计划生成与应用 | 聚合判定不通过时 | 聚合判定、评审证据、正文基线 | text-processing / python | [roles/revision-forge.md](roles/revision-forge.md) |
| author-gate | 作者确认门（HITL） | 大纲定稿前、修订应用前 | 待确认资产 + diff 预览 | 无 | [roles/author-gate.md](roles/author-gate.md) |

> 每次派发 teammate 前，读对应 role 文件并提取 `## Inline Persona for Teammate` 一节，原样粘贴进派发 prompt。
> 多数宿主框架不会自动为 teammate 加载 role 文件。

## Files

| File | What it contains | When to read |
|---|---|---|
| [workflow.md](workflow.md) | Mermaid 拓扑、逐步协议、聚合规则、交付报告格式 | 首次派发前——完整执行手册 |
| [bind.md](bind.md) | 资源上限、行为约束、失败处理与降级模式 | 触限、失败处理或需要降级规则时 |
| [roles/*.md](roles/) | 各角色身份、成功标准、输出 schema、Inline Persona | 派发每个 teammate 前——提取 Inline Persona |
| [dependencies.yaml](dependencies.yaml) | 运行所需外部技能与工具 | **启动时**——核对依赖、上报缺失、用户决定 go/no-go |
| [scripts/workflow.py](scripts/workflow.py) | 可执行 SwarmFlow 编排脚本 | SwarmFlow 执行模式下作为编排真源 |
