# OpenWrite Native Framework / Review v2 Goal and Status

> Canonical project record for the cross-repository review-v2 work.
>
> Last updated: 2026-09-05 (S1-S6 accepted; native framework implementation complete)
>
> Repositories: `/Users/jiaoziang/dsh-novel` and `/Users/jiaoziang/OpenWrite`

This file is the single source of truth for the goal, architectural decisions,
current status, remaining work, verification evidence, and local credential
requirements. Future Goal runs must read this file completely, inspect both
current worktrees, and then continue the first unfinished item. Conversation
history is context only and must not override current repository evidence.

## Current request: native novel framework S1-S6 (2026-09-05)

The accepted user goal improves the OpenWrite domain core and its dsh-novel
native workbench through the staged plan in `docs/IMPROVEMENT_PLAN.md`. The
historical review-v2 and Operations records below remain evidence and must be
reused; they do not replace the S1-S6 acceptance criteria.

| Stage | Status | Current evidence / next acceptance |
|---|---|---|
| S1.1 正文保存状态机 | done | Request snapshots, serial per-document queue, captured Workspace headers, explicit manual save/offline retry/409 overwrite, stale-context/unmount barriers, cross-process project lock and request-bound core response are implemented. A source-backed Playwright scenario holds save A in flight, types B, proves autosave queues with A's returned revision, retries an offline manual request without changing its origin/content, resolves a synthetic 409 only after explicit overwrite, and checks both chapter-switch choices. Desktop and mobile each pass 7/7 with exact target-Workspace header assertions; the two real `~/my_novel` chapters retain identical revision/content before and after. |
| S1.2 本地草稿恢复 | done | IndexedDB adapter and versioned Workspace/work/chapter key implemented; unbound identity never writes a shared slot. Recovery requires an explicit preview/restore, stale base revisions enter conflict state without autosave, cleanup is exact-content guarded, and storage failure stays visible while editor text remains. Component suite 86/86 and live `~/my_novel` Playwright desktop/mobile recovery both pass without changing chapter revision/content. |
| S1.3 统一上下文计量 | done | `mixed-script-conservative-v1` is now the common manifest, generation-context, chapter-packet and inspection estimator. Reports name their rendered-text scope and wrapper inclusion, decompose prompt/section/truth estimates where wrappers are known, and represent unavailable provider usage with null values plus `reported:false`. The 1,500-Han-character case is 2,250 in both manifest and execution section accounting; focused tests 7/7 plus the related context suite 64/64 pass, and live read-only `~/my_novel` context preview exposes the new metadata. Protected-item policy and UI remain S2.2 work. |
| S2 作者控制与版本闭环 | done | **S2.1:** revision-bound history/diff/restore and server-verified selected AI edits. **S2.2:** truthful writing-packet provenance/budgets/freshness plus protected author/canon/chapter constraints. **S2.3:** entity-level mutation summaries; immutable preview/apply/reject/retry/undo plans for documents and five structured domains; redacted 30-day/100-record operation trace. **Operations closure:** benchmark runs are grouped only by complete comparison identity and expose real phases, model identity, sources, failures, usage/cost and candidate/reviewer results; research reports expose filters, exact task-result routing, provenance, source verification, failures and Markdown export, while explicitly remaining reference-only. Current source passed 106 component tests, focused backend 32/32, panel build and live `/Users/jiaoziang/my_novel` Playwright 16/16 across desktop/mobile with exact Workspace assertions and no artifact/manuscript changes. The independent Embedding contract migration is now reflected by Python tests and generated contracts; full OpenWrite is 1137 passed/31 skipped and the dsh full gate exits 0. |
| S3 正文接纳与事实一致性 | done | A durable `openwrite.manuscript-acceptance.v1` ledger now keeps completed and pending full-content SHA revisions distinct, freezes affected chapters, checks SHA before and after analysis, replays chapter facts in order, invalidates review/plans/runs immediately, excludes stale memory and manuscript annotations, preserves authored outline/foreshadowing as `needs_review`, and blocks new generation/planning until reconciliation and acknowledgement. Studio saves, revision apply, history restore, import, agent document edits, standard write and multi-agent write all enter the protocol; external changes remain read-only drift until explicitly accepted. Persistent `manuscript_reconcile` tasks expose real chapter progress. dsh adds two bridge tools plus a native CreationView status/action card for baseline, drift, pending/failed recovery and review acknowledgement. Full evidence: OpenWrite 1147 passed/31 skipped; dsh `npm run check` green with 74 bridge tools and 110 component tests. |
| S4 可恢复导入与完整迁移 | done | The durable old-manuscript workspace freezes the source, permits revision-bound split editing, resumes every stage, publishes through a recoverable whole-arc swap, and enters the S3 fact protocol. The versioned full-project archive declares every included/excluded/missing file, validates SHA/size/ZIP safety, remaps known IDs/references, archives old tasks without resuming them, and is opened from a new temporary Workspace in tests. Export preflight uses the on-disk inventory, rejects duplicate loss, separates backup from delivery, binds output to a stable revision and validates EPUB structure/body. dsh exposes the complete import/archive/export workspaces and 78 bridge tools. Final evidence: OpenWrite 1180 passed/31 skipped; dsh full `npm run check` exit 0 with 117 component tests; live `~/my_novel` delivery blockers and backup behavior rendered correctly, and a 59,010-byte EPUB had a valid mimetype/nav, six-item spine and intact bodies without changing manuscript hashes. |
| S5 原生作者工作台 | done | OpenWrite owns one canonical outline/manuscript reading order with stable document and occurrence identities, explicit planned-missing entries, bounded continuous-reading packets, revision-bound cross-volume moves, chapter work briefs, stable search locators, safe replace previews and a review→revision→rereview closure that reports resolved/retained/regressed findings. dsh presents the same contracts in the native Creation and Search workbenches. Focused backend tests passed 67/67; bridge smoke exposed 82 tools; the pre-S6 panel suite passed 135/135. Live read-only verification found 133 planned documents, six present manuscripts, 127 planned missing entries and zero blockers without changing manuscript hashes. |
| S6 场景与双序结构 | done | `openwrite.scene-structure.v1` provides stable scene IDs, Unicode anchors, reading/story-time order, references, exact-revision metadata and same/cross-chapter moves, explicit migration preview/apply/rollback and stale/ambiguous fail-closed states. Export and writing context consume only current canonical scenes; delivery blocks stale structure while backup falls back to whole prose. Studio, seven bridge tools and the native SceneWorkbench expose the domain without storing a second prose copy. OpenWrite full regression passed 1224 tests with 31 intentional skips; dsh full gate passed with 89 tools and 144 components. Live read-only preview found six chapters/six scenes and no blockers while leaving the scene sidecar absent and manuscript bytes unchanged. |

The S1.1 browser acceptance intercepts mutation requests and verifies the real
`~/my_novel` source before and after; it does not modify a real manuscript or
production gate.

## Current request: DSH plugin maintenance (2026-09-05)

The user requested research into DeepSeek Harness plugin creation/maintenance
and concrete improvements to the existing novel plugin. This is a bounded
maintenance phase, separate from the historical Operations feature roadmap.
Preserve the two dirty worktrees; do not mark M2c/M2d/M2e complete from this work.
Official sources, commands, upgrade and rollback procedures are recorded in
`docs/PLUGIN_MAINTENANCE.md`.

| Deliverable | Status | Evidence / remaining validation |
|---|---|---|
| Official research and repeatable maintenance guide | done | Official bundle/CLI/lifecycle/preset/client docs and npm version metadata checked; rc.7 remains the target, not an untested update to rc.1 |
| Consistent SDK and packaged-entry doctor | done | Root 186, bridge 18 and panel 58 DSH package entries now lock to rc.7; Cordis 4.0.1; offline doctor checks lock metadata, installed SDK, packed JS/types/patch/editor assets; eight positive/negative regression tests |
| Installation and development process lifetime | done | No model call during installation; ten isolated lifecycle tests cover fixed-tag DoG bootstrap, failed-proxy direct retry, atomic cleanup, reuse and web-only mounting; real rc.7 CLI/pnpm 9.15.9 installs and repairs profiles with exactly one mount per plugin |
| Bridge runtime boundaries | done | SSE cleanup including in-flight requests; non-2xx success envelope rejected; path-like export filenames rejected; six focused regressions pass |
| Model workbench maintenance regression | done | Initial baseline was 26 failures / 36 passes after independent Embedding migration; restored existing editing/deletion/route gates and added 9 Embedding cases; parent-run 71/71 pass |
| Unified offline gate and CI definition | done | Current `npm run check` exits 0: build, doctor, 25 maintenance tests, real CLI profile smoke, 27 preset rows/16 skills, both smokes, 14 epochs, 144 components and shared contracts. The real profile now contains bridge/panel/DoG in web and bridge only in headless; both profiles pass doctor. |

The current release is published and installed into the real user profile. The
installation and verification do not call models or modify manuscript/production
gates. The historical acceptance checklist below applies to its dated review-v2
milestones; it is not fresh proof for every current change.

## Maintenance protocol

Every Goal run must keep this file current as part of the work, not as a final
cleanup step:

1. Before making changes, read this file and both repositories' local
   instructions, then compare the status table with repository evidence.
2. After each verified milestone, update the relevant status row, next-work
   order, and verification log with exact commands, counts, and artifact paths.
3. Record failures and residual risks as explicitly as successes. Do not turn a
   focused test, build, fixture, or synthetic sample into a broader claim.
4. Never place secret values here. Record only credential references, required
   environment variable names, rotation state, and setup intent.
5. Before ending a run, leave the first unfinished action concrete enough that a
   fresh agent can continue without relying on conversation history.

## Continuation prompt

Use the following as the short prompt for a future Goal:

```text
Read /Users/jiaoziang/dsh-novel/GOAL.md completely before starting new OpenWrite
or dsh-novel work. Treat S1-S6 as the accepted baseline, preserve both dirty
worktrees and their canonical reading-order, scene, acceptance and revision
contracts, and update GOAL.md whenever new evidence changes the status. Never
read, print, persist, or commit raw credentials. Manual/live/browser QA may use
only ~/my_novel.
```

## Operating constraints

- Read and obey `/Users/jiaoziang/OpenWrite/AGENTS.md` before changing OpenWrite.
- Preserve all pre-existing dirty changes in both repositories. Do not reset,
  clean, or overwrite unrelated user work.
- Manual, live-server, and browser QA may use only `~/my_novel`.
- Automated tests may use isolated temporary projects as permitted by
  `OpenWrite/AGENTS.md`.
- Keep this work inside the DeepSeek Harness plugin architecture. OpenWrite is
  the domain backend; dsh remains the interaction shell and orchestration layer.
- Model calls must use OpenWrite model profiles and its LiteLLM-compatible
  client/gateway. Do not call the OpenRouter SDK directly.
- DoG verifies and queries materialized artifacts. It must never rerun an LLM
  chapter review.
- Do not lower thresholds, delete findings, or rewrite chapters to hide defects
  in the evaluation contract.

## Credential and provider record

Raw secrets do not belong in this file, source code, fixtures, shell history,
logs, screenshots, benchmark artifacts, or Git. Record only references and
configuration intent here.

| Provider | Credential reference | Storage | Status |
|---|---|---|---|
| OpenRouter | OpenWrite profile `credential_ref` (recommended) or legacy `LLM_API_KEY` | Machine-local OpenWrite profile credential store or process environment | User confirmed on 2026-08-25 that this is a dedicated temporary key for this work, explicitly accepted continued use until completion, and will delete it afterward; value remains intentionally unrecorded |
| Existing gateway | Per-profile `base_url`, provider, and API format | Machine-local OpenWrite model profile metadata | Reuse existing profile/gateway path; do not add a second client stack |
| DeepSeek/dsh | `DEEPSEEK_API_KEY` | Process environment or dsh credential store | Existing platform prerequisite; value is intentionally not recorded |

OpenWrite's `ModelProfileStore` keeps metadata in `model-profiles.json` and
credentials in `.model-credentials.json` outside novel projects. Credential
files are written with mode `0600`. The preferred setup is through Studio model
profiles. A profile saved with a new nonempty chat or embedding credential now
records server-generated `credential_updated_at` or
`embedding_credential_updated_at` UTC metadata. These fields are safe to read
through `GET /api/model/profiles`; they contain neither the credential nor a
derived fingerprint. Metadata-only edits preserve them, explicit credential
clearing removes them, and pre-upgrade credentials do not receive invented
timestamps. Rotation proof must require both `configured=true` and a timestamp
created by the rotation save. The legacy environment fallback is:

```text
LLM_API_KEY=<rotated secret supplied locally>
LLM_BASE_URL=<OpenAI-compatible gateway URL>
LLM_MODEL=<model id>
```

The project does not automatically load a repository `.env`; if environment
variables are used, inject them through the launching shell or a local secret
manager. Repository `.env` files are ignored only as a leak-prevention guard.

Initial low-cost benchmark candidates, still invoked through OpenWrite profiles:

- Writer `or-nemotron-super`:
  `nvidia/nemotron-3-super-120b-a12b:free`, credential reference
  `key_or-nemotron-super`.
- Writer `or-laguna-s`: `poolside/laguna-s-2.1:free`, credential reference
  `key_or_free`.
- Independent reviewer `search-local`: `deepseek-v4-flash` through the DeepSeek
  endpoint, credential reference `key_search-local`.

The two OpenRouter writer profiles have separate credential references. The
rotated OpenRouter credential must therefore be saved to both profiles before
the matrix run. Current global routes all point to `search-local`; the benchmark
must preserve that route map exactly.

Provider unavailability, rate limits, parameter incompatibility, truncation,
and empty responses are reliability results, not low quality scores.

## Goal

Build an evidence-driven, additive, explainable review and revision system with
hierarchical review and delivery DAGs, an interactive dsh visualization, and an
isolated in-framework model benchmark. The result must retain compatibility with
the 37 legacy checks while removing the old flat, subtractive scoring semantics.

The chapter-length problem is not part of this goal: `ch_006` already reached
6411 Chinese characters against a 6000 target. The remaining problem is whether
quality, review coverage, blockers, artifact freshness, and delivery readiness
are represented truthfully and can be inspected end to end.

## Review v2 contract

### Six quality domains and one hard gate

All legacy check IDs 1 through 37 must appear exactly once.

| Domain | Legacy check IDs | Weight |
|---|---|---:|
| Coherence and logic | 2, 3, 4, 5, 9, 11, 35 | 20 |
| Character and relationships | 1, 13, 14, 16, 34, 36 | 15 |
| Plot and promises | 6, 15, 24, 25, 32, 33 | 20 |
| Pacing and scenes | 7, 17, 26 | 15 |
| Prose and expression | 8, 10, 19, 20, 21, 22, 23 | 15 |
| Canon and references | 12, 18, 28, 29, 30, 31, 37 | 15 |
| Hard gate | 27 plus explicit critical/blocker findings from any domain | Not scored |

The 37 checks remain queryable `legacy_check_ids`, evidence labels, and
expandable DAG leaves. They are not 37 top-level score dimensions.

Each quality domain contains three or four criteria. Every criterion carries:

```text
earned, max, status, evidence, rationale, issues, legacy_check_ids
```

Allowed evaluation states include `evaluated`, `not_applicable`, and
`inconclusive`. Topic- or canon-dependent checks may be `not_applicable`.
Missing required context is `inconclusive`, not a zero-quality observation.

### Additive score and separate coverage

Positive points require exact, locatable manuscript evidence. Issue counts do
not subtract points.

```text
quality_score =
  sum(earned for evaluated criteria)
  / sum(max for evaluated criteria)
  * 100

coverage =
  sum(max for evaluated criteria)
  / sum(max for evaluated and inconclusive criteria)
```

`not_applicable` criteria are excluded from both denominators. `inconclusive`
criteria lower coverage without silently becoming zero quality. A blocker does
not alter `quality_score`; it independently sets `gate_status=blocked`.

Do not overload `passed`. Keep these concepts separate:

- `execution_status`
- `quality_score`
- `coverage`
- `gate_status`
- `delivery_status`

Delivery requires all of the following:

```text
quality score reaches the configured threshold
AND coverage reaches the configured threshold
AND gate status is not blocked
AND review source SHA equals the current manuscript SHA
```

Legacy `score`, `passed`, and `issue_details` remain readable through an adapter,
but review-v2 logic must not depend on their old semantics. Preserve review
severity as `critical`, `warning`, or `info`; use a separate
`revision_priority` when revision ordering needs `blocker/high/medium/low`.

## Execution design

- Run six quality-domain LLM audits concurrently plus one hard-gate audit.
- Keep normal full review near seven model calls.
- Perform aggregation, coverage, freshness, and delivery decisions in code.
- Prefer deterministic checks for word fatigue, paragraph-length distribution,
  cliche density, list-like structure, repeated phrasing, and basic formatting.
- Extract numbers, objects, times, people, and locations before asking an LLM to
  judge semantic conflicts.
- Compute context budgets from the selected profile and operation; do not apply
  one universal 32K cap.
- Adaptively split truncated work and retain compressed-field metadata,
  `finish_reason`, usage, reasoning tokens, latency, and provider errors.
- Configure `thinking` per operation/profile. Never globally disable it for
  writing or send unsupported parameters to a provider.

## DAG design

Review graph:

```text
manuscript SHA
  -> context integrity
  -> six parallel quality domains + hard gate
  -> deterministic aggregate
  -> delivery decision
```

Delivery graph:

```text
writing -> review -> revision -> application -> rereview -> closure
```

Changing the manuscript makes the previous review stale. Applying a revision
does not make a chapter ready; the changed manuscript must be reviewed again.
Prefer existing `chapter_runs_v2`, review-store, and delivery artifacts over a
second source of truth. Python conductor and TypeScript bridge contracts must
remain equivalent and acyclic.

## UI and benchmark requirements

The dsh Graph view contains Review DAG and Delivery DAG views using React Flow
and ELK. It must support chapter selection, pan/zoom/fit, node details,
all/anomaly/blocker filters, six-domain collapse, and expansion of all 37 legacy
checks. Node details expose status, score, coverage, issues, model, token usage,
latency, criteria, evidence, suggestions, context trimming, and legacy IDs.

The Operations area contains a model benchmark that:

- selects multiple writer profiles and one or more independent reviewer profiles;
- accepts chapter context, repeats, target words, and concurrency;
- creates one fixed `novel_context_preview` packet and SHA-256 hash;
- uses run-scoped profile activation without changing global routes;
- never overwrites canonical manuscript files;
- stores isolated artifacts under
  `data/novels/{novel_id}/data/benchmarks/`;
- records profile/model, context hash, prompt/rubric version, word count,
  finish reason, usage, reasoning tokens, latency, errors, and provider-reported
  actual cost;
- normalizes OpenRouter `usage.cost` and LiteLLM `response_cost`, distinguishes
  explicitly reported `$0` from unknown cost, and reports prompt/completion/
  reasoning totals plus cost coverage;
- labels any `$ / 1M tokens` value as a blended effective rate derived from the
  actual response cost, never as separate provider catalog input/output pricing;
- supports a writer-profile by reviewer-profile blind-review matrix;
- reports provider failures as reliability failures without quality scores.

## Workspace integration (2026-08-31)

Separate goal from review-v2 above: the dsh Workspace is the single workspace
identity, and every OpenWrite capability is isolated per that Workspace's
canonical root. Wire contract: `docs/WORKSPACE_CONTEXT_CONTRACT.md`; original
spec: `docs/WORKSPACE_INTEGRATION_GOAL.md`.

- OpenWrite: `tools/workspace_manager.py` routes any request carrying
  `X-OpenWrite-Workspace-Root` to a lazily-created per-root
  `StudioApplication` (own task runner, locks, services, epoch); context mode
  forbids `project/open|delete` and pins `project/init` to the context root;
  task records persist `workspace_root` (+ `workspace_id`/`session_id`/
  `context_epoch` when present) and root-mismatched records fail closed on
  recover/retry/cancel/get. No header = legacy launch-app mode (CLI intact).
  The context app is never aliased to the mutable legacy launch app, including
  when both roots are the same; nested roots are rejected in both directions.
- Bridge: every tool derives its scoped `StudioClient` from
  `exec.agent.session.header.cwd` (missing → `WORKSPACE_CONTEXT_MISSING`, no
  fallback); the browser proxy resolves only `X-Dsh-Workspace-Id` through the
  host `workspaceRegistry` (lazily, immune to plugin start order) and never
  trusts a browser-supplied path; invalidation/SSE are per-root.
- Panel: the `/project/list` switcher and relative-path creation are deleted;
  `WorkbenchStore.setContext` is the context/generation barrier (switch clears
  chapters/tasks/DAG/graph/current chapter, aborts in-flight work, rebinds
  SSE/polling to `?workspace=`); localStorage keys are workspace-suffixed; new
  works go pickDirectory → `workspace.create` → absolute-path `/project/init`
  → connect/open.
- Evidence: focused OpenWrite Workspace/Task matrix `tests/test_workspace_manager.py`
  is `10 passed` (including legacy/context launch-root isolation and symmetric
  nested-root rejection); the full-suite count from the prior run should be
  rerun before claiming a new total;
  dsh build, bridge smoke (63 tools), contracts, DoG 6, epochs 9, components
  18 all pass; live `scripts/verify.sh` 20/20; live
  `scripts/e2e-workspace-ab.sh` 24/24 (two real temp workspaces, same-name
  chapters with distinct SHA-256, per-root revision isolation, fail-closed
  negatives, auto-cleanup); live E2E 4 passed/2 project-gated skips at
  desktop 1440×1000 and mobile 390×844.
- Residuals: the browser registry lookup depends on the host
  `workspaceRegistry` service (absent → 503 fail closed); full live A/B
  coverage for review/search/DAG/benchmark and restart recovery remains a
  follow-up; one throwaway
  dsh session (`好`) on the `my_novel` workspace was created to satisfy the
  E2E session gate.

## Operations workbench phase (2026-08-31)

Separate phase from review-v2 and workspace integration: unify the Operations
workbench (tasks, models, benchmark, research) across dsh frontend, bridge,
and OpenWrite backend. Constraints: no second task source of truth, no
fabricated progress/cost/citations, credentials never echoed, review-v2's
37-check contract and production gate untouched, canonical manuscript
untouched.

### Audit problem table (evidence: three read-only sub-audits + direct reads, 2026-08-31)

Real bugs:

- P0: with SSE healthy the panel runs no periodic full sync at all; background
  task transitions emit no invalidation, so a finished task keeps rendering as
  running (`WorkbenchStore.ts:235-267`, `domain.ts:236-246`; OpenWrite task
  transitions bumped no epoch).
- P1: BenchmarkView renders missing latency as `0 ms` (`BenchmarkView.tsx:242`);
  task `error.code` dropped at parse (`TasksView.tsx:136-148`); ResearchView
  discards the `POST /tasks` response (no task link, `ResearchView.tsx:175`);
  bridge proxy does not allowlist `research/settings` or
  `tasks/{id}/confirm` (`domain.ts:13-33`).
- P2: ModelView delete without confirmation, permanent dependency block,
  `Pencil` icon for connection test; TasksView native `window.confirm`, div
  list semantics.

Contract gaps:

- P0: task DTO had no `result_ref`, no `failed_stage`, no phase order in the
  DTO, no schema_version/explicit compat; task transitions never advanced the
  per-root context epoch.
- P1: research report metadata had no task_id/model/provider/latency/word
  count/sources/failure; research settings were machine-global, not
  workspace-scoped; connection-test failures collapsed to `STUDIO_ERROR`;
  `/api/model/*` POSTs return bare (non-envelope) payloads; route save returns
  no impact; no last-test state.
- P2: task/research wire shapes had no generated schema; catalog has no
  pricing (token caps only).

Frontend usability:

- P0: TasksView is a flat row list (no summary/filters/sort/timeline/detail
  panel/confirm action/result links/persistence); ResearchView discards
  settings/model_route/dependency flags, no filters/metadata/sources/export.
- P1: ModelView is one flat form (no grouping/validation/temperature/explicit
  credential clear/route purpose labels/test states); BenchmarkView launch
  shows no context hash, progress is a bare status string; zero component
  tests for Tasks/Benchmark/Research views.

Visual:

- P1: 288px research/library sidebar has no mobile media query
  (`views.module.css:171-179`).
- P2: status chips carry color+text only (no icon); no shared summary strip /
  timeline / filter components.

Runtime-verification-pending (no static evidence, no conclusion drawn):
long-text layout, old benchmark artifact rendering, real-source report
rendering, workspace-switch selection timing, mobile ModelView operability.

### Milestones

| # | Scope | Status | Evidence |
|---|---|---|---|
| M1a | OpenWrite task DTO/phase/result_ref/epoch + task-surface schema | done | `tests/test_task_surface.py` 10 passed; parity + workspace_manager 64 passed; full suite 1043 passed/31 skipped; codegen `--check` clean; ruff clean on touched files |
| M1b | OpenWrite research metadata/settings/research-surface schema | done | focused 74 passed; full suite re-verified 1054 passed/31 skipped in 83.06s; codegen `--check` clean |
| M1c | OpenWrite model envelopes/test taxonomy/route impact/benchmark progress + panel minimal wiring | done | backend full suite parent-re-verified 1102 passed/31 skipped in 109.95s; dsh build/contracts/components 37/epochs 9/dog 6/bridge smoke/verify.sh 19 all pass; codegen `--check` clean; old ~/my_novel artifacts validate read-only; both diff checks + secret scans clean |
| M2a | 任务中心工作台化（bridge allowlist + epoch 链路 + TasksView 重构） | done | Bridge allowlist/epoch chain from part1; TasksView now has summary counts, status/type/chapter/keyword filters, sort, real phase/unit progress, detail events/metadata, result links, confirm/cancel/retry actions, responsive task cards and timeline; `npm run test:components` 43/43, `npm run build`, `test:epochs` 14/14, contracts, DoG 6, bridge smoke 64 all pass; Playwright live run 4 passed / 2 project-gated skips (desktop 1440x1000 + mobile 390x844), with zero horizontal overflow and credential-free DOM; task-page screenshots inspected at both viewports; `git diff --check` and non-outputting secret scans clean |
| M2b | 模型管理页面工作台化 | done | ModelView 重构为分组工作台：列表（label/provider/model/配置状态/chat+embedding 测试状态+延迟（缺失显示 `—`)/error_code/used_by_routes chips，选中/新建/刷新/空/加载/错误态）、六段分组表单（基本信息/API 连接/生成参数含 temperature+timeout/Embedding 含 base_url/凭据/路由用途）、必填+正数+温度范围校验、表单与 routes 分离 dirty 保护（切换/新建/刷新不静默丢弃，连接测试和其他 reload 保留编辑）、busy 期间禁用冲突操作、编辑时 id 锁定、删除保持 delete-preview→确认两步（used_by_routes/would-fail/blocking/resulting_routes 全展示，fallback 变更重 preview，阻塞时确认禁用，无 window.confirm）、routes 区显示业务用途标签+当前 profile provider/model/配置状态/能力并消费服务端 impact（parseRouteImpact 兼容嵌套 model_profiles.routes 真实 HTTP 形状）；dto 新增 temperature/timeout_seconds/embedding_base_url；remember 文案明确为本次保存的新凭据；中英文 locale 平价；Pencil→MessageSquare 图标修正 | 证据见 verification log 2026-09-01 M2b 行 |
| M2c | 横评结果视图完善 | done | Read-time comparison keys preserve old artifacts without rewriting them; the result view groups only matching context/prompt/rubric/mode/manifest/strategy/estimator/revisions and shows explicit incomplete legacy identity, real phases, configured/actual model identity, sources, errors, tri-state usage/cost and independent evaluations. `test_model_benchmark.py` 13/13, component/E2E evidence below. |
| M2d | 研究工作台重构 | done | Full research DTO normalization preserves prompt/timestamps and maps legacy complete/completed to succeeded; filters, exact task-result report deep links, provenance, safe source links, failure details, Markdown export, reference-only boundary and scoped mobile master-detail layout are implemented. Historical nulls remain unavailable rather than fabricated. `test_research_service.py` 19/19, component/E2E evidence below. |
| M2e | 桌面/移动 E2E + 全门禁终验 | done | Current-source live Playwright is 16/16 with no skips. Independent Embedding fixtures/tests and model-profile contract parity were migrated to the separate top-level profile collection; full OpenWrite is 1137 passed/31 skipped and `npm run check` exits 0. |
| M3 | frontend foundation + TasksView + component tests | todo | |
| M4 | ModelView + component tests | todo | |
| M5 | BenchmarkView + ResearchView + component tests | done | Full component suite 106/106; focused Benchmark/Research/Tasks deep-link suite 14/14; panel build passes. |
| M6 | E2E + full gates + final report | done | S1-S6 are implemented and recorded below. OpenWrite full regression is 1224 passed/31 skipped; dsh full gate exits 0 with 89 tools and 144 component tests; live canonical-workspace API and browser checks preserve all six manuscript hashes. |

## Current state

### Agent composition migration (2026-08-31)

Goethe and Dante are being merged into one `OpenWrite 创作` preset. The host
profile still mounts `openwrite-bridge` exactly once; the unified preset keeps
the planning, writing, review, revision, research, and benchmark workflows in
one session. The old preset source directories remain as migration references,
but `scripts/install.sh` installs only `presets/openwrite/` and removes the two
generated legacy copies from `~/.dsh/.agent-presets/`. The bridge keeps its 63
typed implementations for API/UI compatibility; tool-catalog reduction is a
separate follow-up and must preserve existing smoke contracts. The current
bridge surface contains 89 typed tools after the accepted S1-S6 additions.

Status values: `done` means implementation exists with focused automated test
evidence; `partial` means implementation exists but required coverage or runtime
proof is incomplete; `todo` means a named deliverable is still missing;
`external` requires user or provider action.

| Area | Status | Current evidence | Remaining proof/work |
|---|---|---|---|
| Review-v2 rubric and additive contract | done | Rubric/store/canonical validators; delivery now requires `freshness_status == "current"` — stale AND unknown (missing current SHA) are non-deliverable, incomplete v2 records are never deliverable; three-case freshness test passes | Human calibration remains external |
| Contract rejection policy at boundaries | done | Version policy hardened: unknown AND missing `schema_version` rejected (`CONTRACT_INVALID`) in `review_chapter()` (v2), `benchmark_run()` (v1), and both dog manifests; new `read_json()` rejects corrupt JSON, non-object roots (`[]`/`null`/text/number), and empty objects — only a missing file is tolerated; graph JSON itself validates typed `nodes`/`contains`/`dependsOn`; negative matrix test (`test_dog_graph_http_rejects_non_object_artifact_shapes`) covers 2 dirs × 3 files × 4 bad shapes; unknown review-manifest and benchmark-version negatives pass; live `~/my_novel` artifacts verified against the strict path (47 review nodes / 6 stages) | Keep enum lists synchronized when versions bump |
| Shared machine-readable schema | done | Six JSON Schemas under `OpenWrite/contracts/` are the source of truth; `tools/schema_codegen.py` (stdlib only) renders `tools/contracts_generated.py` (TypedDicts + `validate_*`, ValueError surfaced as `CONTRACT_INVALID`) and bridge `src/contracts-generated.ts` (interfaces + validators throwing `CONTRACT_INVALID: ...`); generated validators are the runtime path in `studio_application.py` (4 call sites), `review_store.py`, and `conductor/pipeline.py`, and in the TS materializers `dog-review.ts`/`dog-delivery.ts` after the version probe; hand-written `canonical_contracts.py` retained as parity reference — 60 parity tests (`test_contract_schema_parity.py`) prove schema/hand/generated verdicts agree on the valid fixture plus the unknown-version/bad-enum/bad-range/bad-type/credential-leak/non-object-root matrix; `npm run test:contracts` runs the same matrix against the generated TS validators; byte-identical regeneration asserted in pytest and via `tools/schema_codegen.py --check` | Keep enum lists synchronized when versions bump (regenerate via `tools/schema_codegen.py`) |
| Canonical OpenWrite decision consumed by conductor | done | `conductor/pipeline.py` validates required v2 fields and gates solely on `delivery_status`; `conductor/test_pipeline_contract.py` 4 passed including dog-manifest v2-authority case | None |
| DoG/bridge rule isolation | done | DoG modules are model-free materializers/presentation transformers (docstrings state the role); legacy score/passed/severity recalculation isolated into named `legacy_*` adapters in both languages; manifests record `decisionSource: v2 | v1-adapter`; deterministic JS/Python regressions prove v2 wins over conflicting legacy fields and unknown v2 versions throw | Strict pure-verifier refactors remain optional |
| Seven-call review execution and profile-aware context | done | Reviewer provenance and pipeline/client tests assert seven audit calls and operation-specific profiles | Live provider run and truncation telemetry inspection |
| Python and TypeScript hierarchical review DAG | done | 47-node graph with parity tests and live `ch_006` loading (47 nodes/52 edges expanded) | None |
| Six-stage delivery DAG | done | Python/TypeScript implementations, stale-review tests, live `ch_006` artifacts | None |
| Programmatic-only DoG verification | done | `npm run test:dog` 6 passed; DoG reads materialized artifacts only | None |
| Benchmark service and isolated artifact contract | done | Framework mode snapshots per candidate, invokes public write/review entrypoints, preserves provider actual cost with free-vs-unknown provenance; `benchmark_run()` now validates v1 artifacts at the read boundary | None |
| Benchmark bridge tool | done | 89-tool registry; task compaction preserves the full canonical v2 subset and the accepted reading-order, chapter-work, scene, import/archive and trace surfaces — smoke-asserted | None |
| Read-only DAG API | done | `GET /api/dog/graphs`; v2 delivery manifests are contract-validated at read time, legacy artifacts pass through | None |
| Review and delivery DAG frontend | done | Live desktop/mobile QA: 47/52 expansion, Chinese field labels, six-domain chips, overview row, evidence quote, issue-to-revision action, zero overlap/overflow | None |
| Benchmark frontend | done | Multi-reviewer multi-select, provider · real model id, `$0` vs unknown cost distinction | Historical artifacts render explicit unknowns |
| Review/task cards | done | Canonical severity vs `revision_priority` preserved; compaction keeps production-gate/freshness so cards can render them | None |
| Golden samples and dual v1/v2 report | done | Synthetic fixtures plus new v2-authority regression cases | Human calibration remains external |
| Studio model profile page and write allowlist | done | CRUD/chat/embedding tests/dependency preview/fallback verified live; `/model/*` writes allowlisted and smoke-tested; surface contract-validated at the API boundary; credentials write-only | None |
| Workspace chapter review summaries | done | `_load_review_result` now exposes canonical `review_v2` subset (quality/coverage/gate/delivery/production gate/freshness/source revision) next to legacy aliases; stale merges freshness | Frontend chapter list may still show legacy subtitle text |
| Resource epochs and SSE fallback | done | SSE primary + 5s polling fallback; derived invalidation closes the graph loop — assets/manuscript/outline/workspace mutations also bump `epochs.graph`, remounting GraphView which refetches `/api/continuity` on mount; DAG views remount on `epochs.tasks`; benchmark/models epochs keyed remounts; SSE verified in `verify.sh` | Conductor-side direct file writes to `data/dog` bypass API mutation events; DAG reload relies on task completion |
| Frontend automated tests | done | Current `npm run test:epochs` passes 14/14 and `npm run test:components` passes 144/144 across 16 files, including Workspace barriers, save/recovery, result workbenches, canonical chapter navigation, safe search replace and SceneWorkbench dual-order/CAS behavior. Live `npm run test:e2e` passes 16/16 across desktop 1440×1000 and mobile 390×844; it verifies secret non-echo, no horizontal overflow, immutable live manuscripts, context/history, save queue/conflict barriers and isolated recovery drafts. | The E2E file remains service-gated; a skipped run is not live UI evidence. The final recorded run used the current services and had no skips. |
| Credential rotation observability | done | Server-managed timestamps credential-free; storage/HTTP tests pass | Available for future rotations |
| Secret hygiene | done | Non-outputting scans for contiguous OpenRouter credential signatures report zero matching files in both worktrees; `git diff --check` is clean | Delete the dedicated temporary key after acceptance |
| Full regression/build/browser acceptance | done | OpenWrite full suite 1224 passed/31 skipped; dsh `npm run check` exits 0 with 24 maintenance tests, 89 bridge tools, 14 epochs, 144 components and contract parity; `scripts/verify.sh` passes 19/19; live Playwright passes 16/16 and the SceneWorkbench read-only visual probe passes against `~/my_novel` | Human calibration remains external; existing tsdown deprecation/Zustand CJS warnings are non-fatal |
## Next work, in order

0. S1-S6 are accepted. Preserve the canonical reading-order, scene-structure,
   acceptance and revision contracts when adding future author features.
1. Collect 10–20 representative human chapter labels before enabling the
   production gate; this remains an external editorial calibration task.
2. Delete the dedicated temporary OpenRouter key now that implementation and
   acceptance are complete.

## Verification log

Append dated evidence here; do not replace successful entries with unsupported
claims. A passing build is not browser-runtime proof, and a focused test is not
a full-suite result.

| Date | Scope | Evidence | Result |
|---|---|---|---|
| 2026-08-25 | Secret-pattern safety check | Git-tracked and full worktree searches in both repositories, excluding `.git` and dependencies | No OpenRouter key pattern found |
| 2026-08-25 | Current review/profile/benchmark/pipeline focused tests | `OpenWrite/.venv/bin/pytest -q tests/test_review_rubric.py tests/test_review_store.py tests/test_model_benchmark.py tests/test_model_profiles.py tests/test_llm_client.py tests/test_deep_pipeline.py tests/test_prompt_contract_repairs.py` | 81 passed in 1.25s |
| 2026-08-25 | Current Python/TypeScript DoG contract | `npm run test:dog` | 5 passed |
| 2026-08-25 | Current dsh frontend and bridge build | `npm run build` | Passed; non-fatal Zustand CJS `import.meta` warnings remain and browser proof is pending |
| 2026-08-25 | DAG and benchmark HTTP contracts | `OpenWrite/.venv/bin/pytest -q tests/test_review_v2_http.py` | 3 passed; graph failure paths and benchmark task lifecycle covered |
| 2026-08-25 | Synthetic review-v2 golden contracts | `OpenWrite/.venv/bin/pytest -q tests/test_review_v2_golden.py` | 2 passed; synthetic fixtures are not human calibration |
| 2026-08-25 | dsh bridge contract smoke | Bridge build and `packages/openwrite-bridge/scripts/smoke.mjs` | Passed; 63 tools, benchmark proxy, v2 compaction, 47-node review graph, and six-stage delivery graph covered |
| 2026-08-25 | Full OpenWrite regression suite, first run | Complete `pytest` suite | 923 passed, 31 skipped, 2 failed: task-scoped thinking-mode persistence and legacy `passed=false` delivery fallback |
| 2026-08-25 | Previously failing regressions | Focused model-profile, legacy review adapter, and Studio pipeline tests | 5 passed in 1.22s; legacy critical remains blocked, explicit `passed=false` revises, and task-scoped thinking modes survive profile resolution |
| 2026-08-25 | Full OpenWrite regression suite after fixes | `.venv/bin/pytest -q` | 927 passed, 31 skipped in 90.35s |
| 2026-08-25 | Documentation and runtime-skill migration | Cross-repository stale-term searches plus `quick_validate.py` for `dog-review-query`, `dog-delivery-query`, and `dog-import-query` | Six-domain/37-leaf and six-stage wording aligned; all three skills valid |
| 2026-08-25 | Cross-language legacy review compatibility | `npm run test:dog` and bridge smoke after updating Python/TypeScript review and delivery adapters | 6 DoG tests passed; 63-tool smoke passed; explicit legacy `passed=false` remains revise/review_failed even with score 90 |
| 2026-08-25 | Live materialized DAG API | Studio on `127.0.0.1:4567`, `~/my_novel`, `GET /api/dog/graphs?chapter=ch_001` | 47 review nodes and 7 delivery nodes loaded; direct artifact inspection found zero agentic nodes in both graphs |
| 2026-08-25 | Desktop DAG browser QA | 1440×1000 React Flow runtime, node geometry, filters, selection, structured details | Review collapse 10/15, expansion 47/52, blocker 5/5; delivery 7/6; zero node overlaps and zero document overflow |
| 2026-08-25 | Mobile DAG and benchmark browser QA | 390×844 responsive runtime with pan/zoom, structured detail, profiles/controls and empty states | 47 checks and six delivery stages remained accessible; readable default zoom, zero node overlaps/document overflow; five configured profile metadata entries shown without secrets |
| 2026-08-25 | Browser visual artifacts | `review-dag-desktop-final.png`, `review-dag-desktop-expanded-final.png`, `review-dag-detail-desktop-final.png`, `delivery-dag-desktop-final.png`, corresponding mobile DAG images, and benchmark desktop/mobile images under the thread visualization directory | All expected 1440×1000 or 390×844; RGB standard deviations 16.01–23.78 prove nonblank captures |
| 2026-08-25 | Browser runtime fixes | Bundled production environment define, injected official React Flow CSS, real dependency edges, layout refit, readable zoom, structured details | No console errors in the established final tab; raw JSON detail rendering removed |
| 2026-08-25 | Uncalibrated production safety | Focused rubric/golden/pipeline tests after adding calibration state and disabled production gate | 43 passed; uncalibrated enable attempts raise, advisory delivery status is not production approval |
| 2026-08-25 | Final full regression and integration | OpenWrite `.venv/bin/pytest -q`; `npm run build`; `npm run test:dog`; bridge smoke; `scripts/verify.sh` | 928 passed/31 skipped in 98.84s; build passed with known non-fatal Zustand warning; 6 DoG tests, 63 tools, and 14 live integration checks passed |
| 2026-08-25 | Final hygiene | Both `git diff --check` runs and non-outputting OpenRouter signature scans excluding dependencies/build output | Passed; no matching credential signature in either worktree |
| 2026-08-25 | Fresh-tab and review-task browser QA | New in-app browser tab opened `http://127.0.0.1:3080/`; task page loaded 100 records; a completed review task was expanded | Loaded fully within five seconds with no console errors; severity and revision priority remained separate, ten issue rows were visible, and the document had no overflow; screenshot `review-task-card-desktop-final.png` |
| 2026-08-25 | Safe credential-rotation observability | `.venv/bin/pytest -q tests/test_model_profiles.py tests/test_review_v2_http.py`; Ruff check and format check on the three touched Python files | 26 passed in 4.08s; profile storage and real HTTP route expose only server-generated update timestamps, preserve/clear them correctly, do not invent legacy timestamps, and never serialize test credential values |
| 2026-08-25 | Live credential-free benchmark preflight | Restarted Studio from the current OpenWrite source against `~/my_novel`; queried only selected non-secret fields from `GET /api/model/profiles` | Health passed; five profiles are configured but all update timestamps are absent as expected for pre-upgrade credentials. Planned writers are `or-laguna-s` and `or-nemotron-super`, independent reviewer is `search-local`, and all global routes remain on `search-local`. No provider call was made |
| 2026-08-25 | Post-observability regression | Focused profile/HTTP tests, 99-test Studio/LLM/pipeline/benchmark set, then full `.venv/bin/pytest -q` | Focused 26 and combined 99 passed. First full run exposed one test-isolation error caused by selecting a legacy default profile by list position; the test now clears legacy env state and selects by profile ID. Final full run passed: 932 passed, 31 skipped in 90.56s |
| 2026-08-25 | Temporary credential risk decision | User clarified that the configured OpenRouter key was created exclusively for this work, explicitly authorized continued use until completion, and intends to delete it afterward | Rotation is no longer a precondition for the matrix. The implementation must still never read, print, artifact, or commit the raw value |
| 2026-08-25 | Real two-writer x independent-reviewer benchmark matrix | `bench_20260824204903_a7e597ceb3.json` and `bench_20260824210328_a4a58730e4.json` under `~/my_novel/data/novels/mujianzhe/data/benchmarks/`; writers `or-laguna-s` and `or-nemotron-super`, reviewer `search-local`, `ch_006`, target 6000, repeats 1, concurrency 2, identical context hash `sha256:05b0072c801973eb56271539000fc60adcad7b8e683bc81c795ffa9438789bd4` | Run 1: Laguna failed `MODEL_OUTPUT_TRUNCATED`; Nemotron 5173 words; review partial, score 73.33, coverage 15%, 14 calls. Run 2: Laguna failed `CHAPTER_LENGTH_OUT_OF_RANGE`; Nemotron 6953 words; review completed, score 85, coverage 100%, gate pass, delivery pass, 7 calls, zero reasoning tokens. Provider failures are reliability results, not quality scores |
| 2026-08-25 | Reviewer thinking-mode diagnostic | Existing `search-local` profile metadata was updated safely to `{"thinking_modes":{"review":"disabled"}}`; no credential or route changed | Reviewer coverage improved from 15%/14 calls to 100%/7 calls; writing profiles were not globally changed |
| 2026-08-25 | Populated benchmark browser QA | Current dsh build and Studio on `127.0.0.1:4567`, dsh on `127.0.0.1:3080`, `~/my_novel`; desktop 1440x1000 and mobile 390x844 | Both candidates and all material statuses visible; controlled table scrolling at mobile widths; zero document overflow and section overlaps. Screenshots: `benchmark-populated-desktop-final.png`, `benchmark-populated-mobile-results-final.png`, `benchmark-populated-mobile-status-final.png` under `/Users/jiaoziang/.codex/visualizations/2026/08/24/01a034c8-13f3-7732-90b4-7b3245cdf25f/` |
| 2026-08-25 | Production-gate display clarification | Added credential-free `production_gate_status` to new benchmark evaluation records; UI separates quality gate, delivery advice, and production gate, with old artifacts rendered as `未记录（非生产批准）` | Prevents advisory `pass` from being mistaken for calibrated production approval; 2 benchmark tests passed and frontend build passed |
| 2026-08-25 | Final current-source regression and hygiene | OpenWrite `.venv/bin/pytest -q`; dsh `npm run build`, `npm run test:dog`, bridge smoke, `scripts/verify.sh`; both `git diff --check`; route/manuscript hash comparison; benchmark artifact field/mode checks; non-outputting secret scans | OpenWrite 932 passed/31 skipped in 71.20s; 6 DoG tests, 63-tool smoke, 14 integration checks, build, diff checks, route/hash preservation, artifact checks, and secret scans passed |
| 2026-08-25 | Real-framework benchmark backend milestone | `OpenWrite/.venv/bin/pytest -q tests/test_model_benchmark.py tests/test_review_v2_http.py`; Ruff on benchmark, writer, pipeline, and tests | 7 passed. Default framework mode creates one full novel sandbox per candidate, enters public write/review pipelines with run-scoped profiles, records workspace and Chapter Run V2 evidence, and leaves the source manuscript/routes unchanged; direct creative execution remains explicit diagnostic mode only |
| 2026-08-25 | Framework live-run prerequisites | `tools/project_search.py`, `pyproject.toml`, `uv.lock`, focused benchmark/project-search/deep-pipeline/HTTP tests | Serialized LightRAG sync entrypoints to avoid process-global asyncio lock deadlock across candidate loops; activated the production search profile inside candidate runs; added `httpx[socks]`/`socksio` required by the configured local proxy. Focused matrices passed: 31 and 23 tests |
| 2026-08-25 | Real 6000-word framework matrix | `bench_20260825123758_04c8941b62`, `ch_007`, writers `or-laguna-s`/`or-nemotron-super`, reviewer `search-local`, concurrency 2, context `sha256:7d84a55f83962472255a0503db5eb73dab46f9f804a30267f3adba4debbb9b2b` | Laguna timed out after 301.8s. Nemotron produced about 9284 Chinese characters, entered the production length rewrite, then truncated. Both Run V2 manifests completed `context`/`plan`, failed `draft`, never committed, received no evaluation and no score |
| 2026-08-25 | Real 3000-word framework matrix | Task `tsk_20260825124717_45308bf271`, artifact `bench_20260825124721_9230320624.json`, `ch_007`, same writers/reviewer, concurrency 2, context `sha256:0c1ad5f6cb59698c3d672ed7931b44021ed3b9c0fcc9e70fc9e250b837ebaecb` | Laguna timed out after 301.75s. Nemotron produced a 2550-character draft that passed length validation, but its production state-settlement response truncated while still inside Run V2 `draft`. Both candidates failed reliability before `commit`; production review correctly had zero jobs and no quality scores |
| 2026-08-25 | Framework failure provenance | Failure responses now expose credential-free `code` and `run_id_v2`; benchmark failures preserve public entrypoint, stage statuses, failed stage, stage error code and commit/review evidence; old framework artifacts use an execution-mode-aware UI fallback | Focused benchmark/deep-pipeline/HTTP suite: 31 passed; direct benchmark/production-entrypoint suite: 8 passed; Ruff check and format check passed. Provider error text is intentionally not serialized |
| 2026-08-25 | Framework isolation and canonical preservation | Direct workspace/manuscript/profile inspection after live runs | Exactly two complete candidate workspaces per matrix; copied projects contain no nested source `data/benchmarks`; neither candidate created `ch_007`; canonical project still has only six chapters with all six pre-run SHA-256 hashes unchanged; all eight global routes still equal `search-local` |
| 2026-08-25 | Final framework UI runtime QA | Current dsh build at `127.0.0.1:3080`; latest failed `ch_007` run selected at default viewport and 390×844 | Default selector is `真实写作框架`; both candidates show `execute_write_chapter`; independent review is empty because neither committed; mobile document overflow is 0 and candidate results remain accessible through controlled table scrolling |
| 2026-08-25 | Final framework regression and hygiene | OpenWrite full pytest; dsh build, DoG tests, bridge smoke and `scripts/verify.sh`; both `git diff --check`; focused Ruff check/format; non-outputting credential scans | Final current-state run: OpenWrite 939 passed/31 skipped in 87.75s; build passed with known Zustand warnings; 6 DoG tests, 63-tool smoke, 14 integration checks, diff checks, formatting and secret scans passed |
| 2026-08-25 | Current-source service restart | Restarted `npm run dev` after the final backend/UI edits; checked `127.0.0.1:4567/api/health` and `127.0.0.1:3080` without proxy | Both endpoints healthy; no benchmark task remains running, and the live backend now uses the failure-provenance implementation |
| 2026-08-25 | Actual usage and cost contract | OpenWrite full pytest; focused client/benchmark/writer/reviewer tests; dsh build, DoG tests, 63-tool bridge smoke and `scripts/verify.sh`; desktop and 390×844 browser inspection; current-source service restart | 944 passed/31 skipped; final Responses-detail normalization then passed the 48-test focused suite. OpenRouter `usage.cost` and LiteLLM hidden `response_cost` normalize to `cost_usd`; explicit `$0` remains distinct from unknown, multi-call completeness is retained, historical artifacts render `—`, desktop has no console errors, mobile document overflow is zero, both wide tables use controlled horizontal scrolling, and ports 4567/3080 are healthy after restart |
| 2026-08-28 | Versioned cross-language contracts | `OpenWrite/.venv/bin/pytest -q tests/test_canonical_contracts.py tests/test_review_rubric.py tests/test_review_store.py tests/test_llm_client.py tests/test_model_benchmark.py tests/test_review_v2_http.py`; `dsh-novel/npm run test:contracts` | 71 Python tests passed; JavaScript golden fixture smoke passed at `OpenWrite/tests/fixtures/contracts/canonical_v2.json`; no secret fields in fixture |
| 2026-08-28 | Canonical decision and provider cost corrections | Focused OpenWrite tests above; `.venv/bin/python -m py_compile tools/canonical_contracts.py tools/review_store.py tools/novel_service.py`; `.venv/bin/python -m py_compile conductor/pipeline.py` | OpenWrite persists review-v2 source/freshness metadata and returns it through the service; conductor uses only v2 `delivery_status`; provider `cost`/`response_cost` takes precedence over stale `cost_usd`; focused tests passed |
| 2026-08-28 | Studio model page, bridge allowlist, and SSE | `dsh-novel/npm run build`; `npm --prefix packages/openwrite-bridge run smoke`; `npm run test:contracts` | Panel build passed with existing non-fatal Zustand CJS `import.meta` warning; 63-tool bridge smoke passed including `/model/routes` write allowlist and SSE invalidation; contract smoke passed |
| 2026-08-28 | Full regression after canonical/cost/model work | OpenWrite `.venv/bin/pytest -q` | 949 passed, 31 skipped in 118.55s |
| 2026-08-28 | Conductor canonical decision contract | `/Users/jiaoziang/OpenWrite/.venv/bin/python -m pytest -q conductor/test_pipeline_contract.py` | 3 passed; legacy-only and incomplete-v2 reviews rejected with `REVIEW_V2_REQUIRED`/`INVALID_REVIEW_V2` |
| 2026-08-28 | Model profile HTTP CRUD/fallback | `.venv/bin/pytest -q tests/test_review_v2_http.py` (includes new CRUD test) | 4 passed; create/routes/delete with fallback verified credential-free |
| 2026-08-28 | Final dsh build, DoG, smoke, contracts, integration | `npm run build`; `npm run test:dog`; bridge smoke; `npm run test:contracts`; `bash scripts/verify.sh` | Build passed (known Zustand warning); 6 DoG tests; 63-tool smoke; contract smoke; verify.sh 14/14 PASS |
| 2026-08-28 | Desktop browser QA (1440×1000) | Live dsh at 127.0.0.1:3080 against `~/my_novel` | Models page CRUD controls/test buttons/routes/fallback rendered, password inputs empty, no `api_key`/`sk-` markers in DOM; benchmark multi-reviewer listbox and provider · model identities shown; relationship graph 21/92 · 2/140 default, search filters to 1, all-kinds 92/92 · 140/140 with 0 overlapping node rects; node detail (type/status/description/source link/neighbors), edge detail (edge type/origin/confirmed/source→target); filter persistence in localStorage; Review DAG overview (freshness/quality/coverage/gate/delivery), six Chinese domain chips, expansion 47 nodes/52 edges, evidence quote, issue-to-revision button; zero document overflow |
| 2026-08-28 | Mobile browser QA (390×844) | Live dsh same session | Models page and Review DAG fully operable, overview row visible, 10 nodes/15 edges collapsed, document scrollWidth 390 = clientWidth (zero overflow) |
| 2026-08-28 | Diff and secret audits | `git diff --check` in both repos; non-outputting `OpenRouter key signature ` signature scans excluding `.git`/dependencies/caches | Both clean: 0 whitespace errors, 0 signature matches |
| 2026-08-28 | Post-audit P0 fix: freshness-unknown delivery | `OpenWrite/.venv/bin/pytest -q tests/test_canonical_contracts.py tests/test_review_store.py` (includes new current/old/missing-SHA and incomplete-v2 cases); `review_is_deliverable` now requires `freshness_status == "current"`; `_record_review_lifecycle` passes the current manuscript SHA | 12 passed; stale AND unknown freshness are non-deliverable |
| 2026-08-28 | Post-audit P1 fixes: contract/DoG/epochs/compaction/summaries | Delivery `recordType` unified to `chapter-delivery` in fixture + validator; runtime validators added to `model_profiles()`, `review_chapter()` v2, `benchmark_run()` v1, `dog_graphs()` v2 delivery; legacy recalc isolated into named `legacy_*` adapters (py+ts) with `decisionSource` provenance; `GraphView` keyed on `epochs.graph`, DAG views keyed on `epochs.tasks`; compaction preserves full canonical v2 subset; `_load_review_result` exposes v2 statuses | OpenWrite full suite: 951 passed, 31 skipped in 85.40s |
| 2026-08-28 | Second-audit P1: contract rejection policy | Unknown/missing `schema_version` now rejected in `review_chapter()` (v2), `benchmark_run()` (v1), and both dog manifests via new `versioned()` gate in `dog_graphs()`; corrupt artifact JSON raises `CONTRACT_INVALID` (absent files still tolerated); validators deepened (benchmark status enum + array types, delivery stage recordType/verdict/status, new `validate_review_manifest_v2`); `.venv/bin/pytest -q tests/test_review_v2_http.py tests/test_canonical_contracts.py tests/test_review_store.py tests/test_studio.py` — 7 dog HTTP tests include corrupt-artifact, unknown-review-manifest-version, and unknown-benchmark-version negatives; `.venv/bin/pytest -q` full suite: 953 passed, 31 skipped in 100.12s |
| 2026-08-28 | Second-audit P1: TS DoG version gate | `buildDogReviewBundle` and `materializeChapterDelivery` throw on present-but-unknown `review_v2.schema_version` (e.g. `openwrite.review.v999` with conflicting legacy fields); `scripts/dog-canonical.mjs` negative case added; `npm run test:contracts` and `npm run test:dog` (parity fixture updated to declare the real v2 version) pass |
| 2026-08-28 | Second-audit P1: graph invalidation loop | `WorkbenchStore.invalidate` derives `epochs.graph` from assets/manuscript/outline/workspace mutations so GraphView remounts and refetches `/api/continuity`; panel build passed |
| 2026-08-28 | Second-audit P2: role/docs | DoG module docstrings rewritten as "model-free materializer/presentation transformer"; GOAL rows corrected: DoG role, rejection policy, new `Shared machine-readable schema` todo row, frontend automated tests kept `partial`; Next-work list gains schema-single-source and component/E2E runner items |
| 2026-08-28 | Post-audit dsh gates | `npm run build`; `npm run test:dog`; bridge smoke; `npm run test:contracts` (now includes `scripts/dog-canonical.mjs` v2-authority regression); `bash scripts/verify.sh`; `conductor/test_pipeline_contract.py` via OpenWrite venv | Build passed (known Zustand warning); 6 DoG tests; 63-tool smoke; contract + dog-canonical ok; verify.sh 14/14 PASS; conductor contract tests 4 passed |
| 2026-08-30 | Stage: DoG artifact rejection matrix (A) | `tools/studio_application.py` `read_json` now rejects corrupt JSON, non-object roots (`[]`/`null`/string/number), and empty objects — only FileNotFoundError yields absent; graph JSON validates typed `nodes`/`contains`/`dependsOn`; `.venv/bin/pytest -q tests/test_review_v2_http.py` — 8 passed incl. `test_dog_graph_http_rejects_non_object_artifact_shapes` (2 dirs × 3 files × 4 shapes) and unknown review-manifest version | 8 passed; live `~/my_novel` artifacts pass the strict path (47 review nodes / 6 delivery stages via restarted server) |
| 2026-08-30 | Stage: TS bridge error strategy (B) | `dog-delivery.ts` `readJson` mirrors Python: ENOENT → absent, corrupt/non-object/empty → throw; review absent still materializes `missing`, present-but-unknown/missing `review_v2.schema_version` throws; `dog-canonical.mjs` extended with absent-review and 5 negative materializer cases on a temp fixture tree | `npm --prefix packages/openwrite-bridge run test:contracts` passed; `npm run test:dog` 6 passed |
| 2026-08-30 | Stage: shared machine-readable schemas (D) | Six schemas added under `OpenWrite/contracts/`; Python linter `tools/schema_lint.py` + 17 parity tests `test_contract_schema_parity.py`; JS mirror `schema-lint.mjs` runs the identical fixture matrix in `test:contracts`; both sides agree on valid fixture + unknown-version/bad-enum/bad-range/bad-type/credential-leak negatives | Status recorded as `partial` — no codegen yet; hand-written validators remain the runtime path |
| 2026-08-30 | Stage: epoch invalidation tests (E) | Pure module `workbench-epochs.ts` extracted from `WorkbenchStore`; `npm run test:epochs` (Node strip-types + node:test) — 8 tests: assets/manuscript/outline mutations derive graph bumps, tasks bumps DAG epoch only, benchmark/models/research/revisions never touch graph, SSE and polling channels produce identical epochs, refresh trigger set correct | 8/8 passed; panel build passed |
| 2026-08-30 | Stage: full regression and gates | OpenWrite `.venv/bin/pytest -q`: 971 passed, 31 skipped (97.54s); `npm run build`; `npm run test:dog` 6; bridge smoke 63 tools; `test:contracts` (schema parity + dog canonical); `test:epochs` 8; `scripts/verify.sh` 14/14 PASS after server restart; strict dog API verified live against `~/my_novel` (47 nodes / 6 stages); `git diff --check` + non-outputting `OpenRouter key signature ` scans clean in both repos; harness headless browser cannot open pages (infrastructure defect, curl/verify unaffected) — earlier recorded desktop/mobile QA remains the UI runtime evidence, human browser pass recommended |
| 2026-08-30 | Third-stage P1: review_v2 type bypass fix | `tools/review_store.py` adds `has_review_v2_field` (key present, even null) and `review_v2_malformed` (present but null/list/string/number/bool/empty-object); `review_is_deliverable` returns False for malformed v2 regardless of legacy score/passed; status helpers (`review_gate_status`/`review_delivery_status`/`review_quality_score`) return inconclusive/null for malformed v2 instead of legacy-derived values; `canonical_review_decision` raises ValueError for malformed v2; `review_chapter()` rejects non-object/empty review_v2 with `CONTRACT_INVALID`; legacy adapter reserved for records without the key; `.venv/bin/pytest -q tests/test_canonical_contracts.py tests/test_review_store.py tests/test_review_v2_http.py tests/test_studio.py` — 85 passed incl. parametrized null/[]/string/number/bool/empty-object matrix |
| 2026-08-30 | Third-stage P1: TS existence/type/version parity | `dog-review.ts buildDogReviewBundle` and `dog-delivery.ts materializeChapterDelivery` now throw on present review_v2 key that is null/non-object/empty or declares an unsupported schema version (mirroring Python); only records without the key ride the v1 adapter; `dog-canonical.mjs` extended with null/[]/string/number/bool/empty-object matrix + legacy-only `decisionSource: v1-adapter` assertion + materializer negatives for array and null review_v2; `npm run test:contracts` passed |
| 2026-08-30 | Third-stage P1: review manifest schema negatives both sides | Python `test_contract_schema_parity.py::test_review_manifest_schema_and_validator_reject_negatives` (unknown version, bad recordType, non-`ch_N` chapterId, bad verdict, missing required keys — schema and hand validator agree); `validate_review_manifest_v2` hardened with `ch_\d+` chapterId pattern; JS `contract-smoke.mjs` runs the same review-manifest schema over the fixture and delivery-stage negatives | Schema + hand validator parity proven on both sides |
| 2026-08-30 | Third-stage E: epochs workspace derivation | `workbench-epochs.ts` + `npm run test:epochs` now 9 tests incl. workspace→graph derived bump, manuscript→graph, SSE≡polling identity | 9/9 passed |
| 2026-08-30 | Third-stage gates | OpenWrite `.venv/bin/pytest -q`: 979 passed, 31 skipped (105.60s); dsh `npm run build`; `npm run test:dog` 6; bridge smoke 63 tools; `test:contracts` (schema parity + dog canonical incl. type matrix); `test:epochs` 9; `scripts/verify.sh` 14/14 PASS after server restart; `git diff --check` + `OpenRouter key signature ` scans clean both repos; production gate untouched (`disabled_uncalibrated`) |
| 2026-08-28 | Browser note after harness restart | Headless harness tab diagnostics: signal-free fetch to `/api/dog/graphs` 200 in ~15ms; manual-AbortController fetch 200 in 2ms; only `AbortSignal.timeout`-attached fetches never resolve in the restarted harness daemon; `verify.sh` and curl unaffected | Desktop/mobile runtime QA from the earlier session remains the recorded evidence; the harness limitation blocks an automated re-pass — flagged for a manual browser check on the user's machine |
| 2026-08-31 | Stage: schema codegen (review-v2 next-work #1) | `tools/schema_codegen.py` renders Python+TS types/validators from the six `contracts/*.schema.json`; runtime switched to generated validators in `studio_application.py`, `review_store.py`, `conductor/pipeline.py` and TS `dog-review.ts`/`dog-delivery.ts`; hand validators kept as parity reference (bool-as-number aligned with the schema); schema-lint mirrors aligned (strict object type on the JS side); dog parity fixture gained the required `production_gate_status` | `OpenWrite/.venv/bin/pytest -q`: 1009 passed, 31 skipped (independent re-run 76.00s); `npm run build`; `npm run test:contracts` (schema matrix + generated-validator matrix + dog canonical); `npm run test:dog` 6; `npm run test:epochs` 9; bridge smoke 63 tools; `conductor/test_pipeline_contract.py` 4 passed; `tools/schema_codegen.py --check` reports both artifacts current (byte-identical); live dog API re-verified post-codegen against `~/my_novel` on a fresh Studio: ch_001 and ch_006 each load 47 review nodes / 7 delivery nodes through the generated-validator path; `git diff --check` and non-outputting `OpenRouter key signature ` scans clean in both repos |
| 2026-08-31 | Stage: React component + E2E runner (review-v2 next-work #1) | vitest + jsdom + @testing-library component layer under `packages/studio-panel/scripts/components/` (jsdom chosen over happy-dom for React 18/testing-library maturity); Playwright runner `packages/studio-panel/e2e/workbench.spec.mjs` probe-gated on dsh web 3080 + Studio 4567, repo-local browsers (`PLAYWRIGHT_BROWSERS_PATH=packages/studio-panel/.pw-browsers`, gitignored), desktop 1440×1000 + mobile 390×844 projects; new devDeps: vitest ^4.1.11, jsdom ^30.0.1, @testing-library/react ^16.3.3, @testing-library/dom ^10.4.1, @playwright/test ^1.62.1 (lockfile synced); root scripts `test:components`/`test:e2e` added | `npm run test:components`: 10/10 (ModelView credential non-echo ×4 incl. fake `test-credential-abc` POST-once-then-cleared and never in DOM; GraphView tasks-epoch remount refetch of `/dog/graphs` ×2; WorkbenchStore SSE-error→5s-polling fallback, SSE≡polling identity, revision dedup ×4); `npm run test:e2e` services down: 6 skipped, exit 0, reason printed; live `scripts/dev.sh` stack: 4 passed (shell zero-overflow ×2 viewports; desktop model view password inputs empty, no `OpenRouter key signature `/`api_key` in DOM; mobile 390×844 tabs reachable + zero overflow) / 2 project-gated skips, stack stopped afterwards; gates: `npm run build` (known Zustand warning), `test:epochs` 9, `test:contracts`, `test:dog` 6, bridge smoke 63 tools; `git diff --check` + `OpenRouter key signature ` signature scans 0 hits both repos |

| 2026-08-31 | Post-audit P1: review_v2 persistence boundary and atomicity | `NovelApplicationService.review_chapter()` now validates any present `review_v2` before `ReviewStore.save()`; `StudioApplication.review_chapter()` uses key-presence semantics and maps `CONTRACT_INVALID` to HTTP 400; TS DoG materializers use `Object.hasOwn()` for the same presence rule; Python Studio regression covers null/array/string/number/bool/empty-object and asserts no review artifact is written; TS canonical regression covers the same non-object cases and asserts malformed reviews never overwrite an existing delivery artifact | OpenWrite full suite: 1015 passed, 31 skipped; dsh build, `npm run test:contracts`, `npm run test:dog` (6), `npm run test:epochs` (9), `npm run test:components` (10), `npm run test:e2e` (6 probe-gated skips, exit 0), `schema_codegen.py --check`, and both `git diff --check` passed |
| 2026-08-31 | Workspace isolation integration (docs/WORKSPACE_CONTEXT_CONTRACT.md) | OpenWrite `tools/workspace_manager.py` per-root routing + task origin pinning; bridge scoped clients from `exec.agent.session.header.cwd` + registry-resolved browser proxy; panel context/generation barrier, native workspace onboarding, namespaced localStorage | OpenWrite `.venv/bin/pytest -q`: 1024 passed, 31 skipped (incl. new tests/test_workspace_manager.py 9); dsh `npm run build`, bridge smoke (63 tools), `test:contracts`, `test:dog` 6, `test:epochs` 9, `test:components` 18 all pass; live `scripts/verify.sh` 20/20; live `scripts/e2e-workspace-ab.sh` 24/24 with distinct on-disk SHA-256 per root and per-root revision isolation; live `npm run test:e2e` 4 passed/2 project-gated skips (desktop 1440x1000 + mobile 390x844); both `git diff --check` clean; production gate untouched (`disabled_uncalibrated`) |
| 2026-08-31 | Post-release UX fix: actionable workspace chip | `WorkspaceContextChip` was read-only, leaving bound-but-uninitialized workspaces with no reachable init path; the chip is now a button when action is needed: unbound session -> popover driving pickDirectory/create/connect/open, uninitialized workspace -> inline init form pinned to the canonical path (shared `initWorkspaceProject` helper, also used by OperationsView); actionable chips get cursor/hover consistent with other header buttons | `npm run build`, `npm run test:components` 20/20 (incl. 2 new popover tests), `test:epochs` 9, live stack: initialized workspace renders a read-only chip, `scripts/verify.sh` 20/20 |
| 2026-08-31 | Operations M1b: research backend | Report metadata enriched at archive time: `task_id` (wired from the task handler through `ResearchService.run`), `model_profile` {id,label,model,provider}, `search_provider`, measured `latency_ms`, real `word_count`, `usage`/`cost_usd` with explicit `reported` booleans (absent=null, never fabricated), credential-free `failure` {code,message} for failed episodes; structured `sources` extracted from the real per-episode `evidence-index.json` (`globalEvidenceIndex`: citationId/title/url/sourceTier, `cited` derived from `[C<n>]` markers in the report body) — no fabricated citations, `sources_status` ok/unavailable; `normalize_report_metadata` maps old 7-key metadata to the full DTO with explicit nulls; research settings now workspace-scoped (`StudioResearchSettingsStore.for_workspace`, non-secret fields per workspace file, API key stays machine-global, global fallback for pre-scoping users); `GET /api/research` carries `schema_version: openwrite.research-surface.v1` validated by the generated validator (8th schema) | focused research+parity 74 passed; full suite re-verified by parent: 1054 passed/31 skipped in 83.06s; `schema_codegen.py --check` both artifacts current; ruff clean on touched files |
| 2026-08-31 | Operations M1c baseline verification | Worktree evidence checked directly (not trusted from reports): M1a task schema_version/normalize/result_ref/on_change present in `task_store.py`; M1b normalize_report_metadata/for_workspace/research-surface validation present; 8 schemas in `contracts/`; TS validators `validateTaskSurfaceV1`/`validateResearchSurfaceV1` generated; codegen `--check` clean; full pytest re-run | 1054 passed, 31 skipped in 83.06s |
| 2026-08-31 | Operations M1a: task DTO + epoch | Task records persist `schema_version: openwrite.task.v1`; explicit `normalize_task_record` compat layer marks legacy records `openwrite.task.v0` (conservative phase mapping: only completed→complete, else null — never invented); DTO gains `phase_index`, `progress` (always null), `result_ref` (read-time derivation per type), error gains `failed_stage`; surface gains `schema_version`/`phase_order` validated by generated `validate_task_surface_v1` at the HTTP boundary; task transitions bump the per-root context epoch via an exception-safe `on_change` listener wired in `WorkspaceManager.app_for` (legacy mode unaffected); new `contracts/task-surface-v1.schema.json` (7th schema) with credential-disallowed guard, codegen re-rendered both languages | `tests/test_task_surface.py` 10 passed; parity + workspace_manager focused 64 passed; full suite 1043 passed/31 skipped in 108.92s; `schema_codegen.py --check` clean; ruff clean on touched files; zero existing tests modified |
| 2026-09-01 | Operations M1c backend: model contracts | Envelope flip for POST /api/model, /model/test, /model/embedding/test, /model/profiles, /model/profiles/delete, /model/routes, /research/settings (+ new /model/profiles/delete-preview); profile entries gain `schema_version`/`capabilities`/`used_by_routes`/credential-free `last_test`+`last_embedding_test` (server-managed, null=untested); shared connection-test taxonomy `tools/llm/test_errors.py` (14 kinds, structured signals beat message matching, codes MODEL_TEST_<KIND>, recoverable only for transient kinds, raw provider text only in redacted logs); delete-preview is strictly read-only with blocking codes (IN_USE/LAST_PROFILE/FALLBACK_INVALID/FALLBACK_UNCONFIGURED); `save_routes` atomic validate-then-swap under lock with `impact` payload; benchmark tasks report real units via `TaskContext.report_progress` (generation total = writers×repeats, review total = committed candidates×reviewers — provider failures honestly shrink it), task-surface `progress` relaxed to null|{completed_units,total_units,ratio,unit_kind}; run artifacts gain optional `task_id`/`started_at`, summary `latency_ms_total` (null when none) + `failed_candidates`; 9th schema model-connection-test-v1; benchmark schema pins usage/cost/latency null-vs-zero semantics | focused 6-file 154 passed (25 new connection-test + parity 62); full suite 1102 passed/31 skipped in 112s (+48 vs baseline); codegen `--check` clean both languages; all 5 real ~/my_novel benchmark artifacts validate read-only against the extended schema; ruff clean on owned files; subagent interruption recovered (quota 403 → resumed, zero work loss) |
| 2026-09-01 | Operations M2a part1: bridge allowlist + epoch chain | Bridge allowlist completed (`tasks/{id}/confirm` + `research/settings`; non-allowlisted siblings still 405); `invalidation.json` and SSE `ready` merge upstream per-root `context_epoch` from GET /api/workspace/context (optional field, omitted on any failure, 5s cap, no bridge polling loop); WorkbenchStore two-layer sync: always-on 5s invalidation poll (observes background task transitions → P0 fixed) + SSE instant layer, both through consumeMutation, SSE≡polling identity cross-tested; pure `terminalTransitionResources` bumps research/benchmark/dag epochs only for newly-terminal typed tasks; OpenWrite tests-only gap-fill: HTTP confirm lifecycle, unknown-id 404 matrix, foreign-root mutation 404/409, error DTO structure; noted deviation: malformed (non-`tsk_`) task ids 404 as STATIC_ASSET_NOT_FOUND/ROUTE_NOT_FOUND (fail-closed, asserted as-is) | Parent re-verified: `test:components` 39/39, `test:epochs` 14/14, OpenWrite focused 39 passed; agent-reported full suite 1106 passed/31 skipped (+4), bridge smoke/contracts/dog/build green, both `git diff --check` clean |
| 2026-09-01 | Operations M1c frontend wiring + dsh gates | dto.ts extended (profile capabilities/used_by_routes/last_test, parsers for connection-test/delete-preview/route-impact/task-progress/result-ref, envelope+bare tolerant); ModelView consumes envelopes, shows untested/ok/failed+error_code markers, delete is now two-step delete-preview→confirm with server-side fallback_candidates; BenchmarkView `0 ms`→`—` latency fix, real progress units + phase in toolbar, result_ref auto-opens run detail; bridge compactTaskList passes through schema_version/phase_index/progress/result_ref/started_at/completed_at (+error.failed_stage); smoke asserts the pass-through and enveloped /api/model/routes; component tests 20→37 (dto 11, benchmark 3, model-view +3 incl. blocked-preview-never-deletes) | Parent re-verified independently: `npm run test:components` 37/37; bridge smoke exit 0; `test:contracts` ok; `test:dog` 6 ok; `test:epochs` 9 ok; build exit 0 (known Zustand warning); verify.sh 19/19 live (stack started then stopped by the agent); both `git diff --check` exit 0; `OpenRouter key signature <alnum>` scans 0 hits both repos; codegen `--check` both artifacts current |
| 2026-09-01 | Operations M2a: task console | TasksView rebuilt around the existing task DTO: summary counts, status/type/chapter/keyword filters, newest/oldest sort, real phase and unit progress (null remains “unknown”), task detail with event history and credential-free metadata, result_ref navigation to benchmark/research/chapter, confirm/cancel/retry actions with guarded availability, and responsive cards/timeline; OperationsView wires benchmark/research navigation; added `tasks-view.test.tsx` | `npm run build`; `npm run test:components` 43/43 (independent rerun); `npm run test:epochs` 14/14; `npm run test:contracts`; `npm run test:dog` 6; bridge smoke 64 tools; live `scripts/verify.sh` 19/19; live `npm run test:e2e` 4 passed / 2 project-gated skips (desktop 1440x1000 + mobile 390x844), zero horizontal overflow and credential-free DOM; task-page screenshots inspected at both viewports; `git diff --check` and non-outputting secret scans clean |
| 2026-09-01 | Operations M2b: model workbench | ModelView rebuilt from flat form to grouped workbench (see milestone table); added separate form/routes dirty tracking so connection tests, refreshes, profile saves, and other reloads cannot overwrite edits; explicit discard guard covers profile and route changes; successful refresh clears stale load errors; remember label now describes per-save semantics; tests written before implementation: model-view.test.tsx 7→25 (credential non-echo ×4 kept; M1c surface ×3 kept; new: grouping, create/edit save, validation, unsaved switch/create/refresh, connection-test edit preservation, route-edit preservation across profile reload, test states, latency `—`, delete preview/confirm/fallback, routes impact, loading/error/empty, long identifiers, busy actions); dto.test.ts 12→14; E2E extended: desktop asserts group headings + New-profile id editable + passwords stay empty + zero overflow at 1440×1000; mobile navigates into the model segment at 390×844 | `npm run build` (known Zustand warning); `npm run test:components` 62/62; `npm run test:epochs` 14/14; `npm run test:contracts`; `npm run test:dog` 6; live stack: `npm run test:e2e` 4 passed / 2 project-gated skips; `scripts/verify.sh` 19/19; OpenWrite focused `pytest tests/test_model_profiles.py test_model_connection_test.py test_model_catalog.py test_model_benchmark.py test_studio_tasks.py` 78 passed (backend untouched); both `git diff --check` clean; non-outputting secret scans 0 hits both worktrees; `test-credential-abc` exists only in model-view.test.tsx; canonical manuscript and production gate untouched |
| 2026-09-01 | Operations M2c: independent Embedding surface | Chat profile metadata no longer contains embedding provider/model/base URL/dimension/token/key/test fields. `ModelProfileStore` persists top-level `embedding_profiles` plus `active_embedding_profile_id`; added independent save/select/delete/resolve methods and `/api/model/embedding*` endpoints. LightRAG now resolves the active Embedding profile independently of the Chat route. Model workbench has separate Chat and Embedding tabs, credential-free status/test markers, and independent CRUD actions; bridge allowlist/tools updated | `npm run build` passed; Python modules compile; full legacy pytest/component suite requires test fixture updates for the intentionally breaking schema and was not claimed green; production gate untouched; no keys read or printed |

| 2026-09-05 | DSH plugin maintenance: initial evidence | Official repository/npm docs and installed CLI inspected; component baseline run before maintenance edits | Root CLI rc.7 mixed with 185 rc.8 packages, bridge mixed with 15 rc.8 packages; build passed; components 26 failed/36 passed following the independent Embedding migration. Initial in-place npm override lock update stalled in conflicting override resolution; it was stopped and the root lock regenerated in an isolated temporary directory from the pinned manifest, then installed with npm ci |
| 2026-09-05 | DSH plugin maintenance: final parent verification | `npm run check` (log `/tmp/dsh-novel-maintenance-final.log`); `git diff --check`; shell/Node syntax checks; CI YAML parse/gate assertion | Exit 0. DSH rc.7 lock+installed parity: root 186/bridge 18/panel 58; doctor 9 checks and 8 negative/positive tests; lifecycle 9 + bridge boundary 6 = 23 maintenance tests total; real CLI web/headless offline local-link installation, composed row counts and missing-bundle repair pass; preset 27 rows/16 skills resolve; bridge smoke 69 tools; panel smoke passes; epochs 14/14; components 71/71; shared schema fixture + generated validator + DoG canonical contract smoke pass. Existing non-fatal tsdown deprecation/Zustand CJS warnings remain. No model calls, real-profile install, live-server/browser run, remote CI run or OpenWrite full pytest performed; manuscript, backend and production gates unchanged by this phase |
| 2026-09-05 | Native framework S1.1 save state, focused implementation | Added failing-first regressions for delayed A→B queueing, Workspace switch with same path, offline retry, explicit conflict overwrite, unmount response disposal, captured request headers, cross-process project-lock participation and response binding. `CreationView` now snapshots content/document/context, serializes writes, retains dirty text, pins headers, exposes manual retry/overwrite and drops stale/unmounted results. OpenWrite generates the response from the atomic write snapshot and uses `ProjectWriteLock` for CAS/write. | Panel `npm --prefix packages/studio-panel run build` passes with the existing tsdown/Zustand warnings; component suite 77/77; OpenWrite focused `uv run pytest tests/test_studio.py -q -k document_write` 3/3; touched-file import ordering and both `git diff --check` pass. A broader `tests/test_studio.py` run was attempted: 65 passed/1 failed in the independent-Embedding local-profile test (`MODEL_CREDENTIAL_MISSING`); this is outside the document-write path but remains an open regression. Live browser acceptance was not run and S1.1 remains `partial`. |
| 2026-09-05 | Native framework S1.2 local-draft recovery | Added a versioned IndexedDB adapter, Workspace/work/chapter identity, exact-content cleanup, explicit matching/stale-base recovery UI and unavailable-storage state. Failing-first component cases cover refresh-style load, same-path Workspace isolation, stale base, unbound identity, newer draft during an older save and storage failure. Live E2E seeds the browser database for the exact dsh Workspace mapped to `/Users/jiaoziang/my_novel`, previews then dismisses the recovery, and proves the selected chapter's server revision/content are unchanged. | `npm --prefix packages/studio-panel run test:components` 86/86; panel build passes with existing tsdown/Zustand warnings; live `npm run test:e2e` 8/8 on desktop 1440×1000 and mobile 390×844 with no skips; `scripts/verify.sh` 18/18; both repository `git diff --check` commands pass. S1.2 is `done`; S1.1 still requires its write-race browser acceptance. |
| 2026-09-05 | Native framework S1.3 unified context measurement | Moved the mixed-script estimator into a shared module and reused it in context manifests, `GenerationContext`, chapter-packet budgets and agent-message inspection. Manifest and execution reports state measured text scope/wrapper policy; known prompt wrappers are decomposed, unknown wrappers remain null, and unavailable provider usage stays `{reported:false, ...:null}`. | Failing-first `tests/test_context_estimation.py` moved from 6 failures to 7/7 passed; Chinese 1,500 chars are 2,250 tokens in manifest, generation section and chapter packet; English/mixed parity passes; related context/manifest/inspector selection 64/64; focused Ruff E/F/I and OpenWrite `git diff --check` pass. A broader related run was 83 passed/2 failed in independent project-search refresh/scope assertions due existing semantic-index results. After a source restart, read-only `/api/context?chapter_id=ch_007` against `/Users/jiaoziang/my_novel` returned 11 manifest items, estimator metadata, section total 46,350, wrapper null and actual usage null/reported false. |
| 2026-09-05 | Native framework S2.1 history/revision focused implementation | Added coalesced autosave and durable manual-save history; GET version list/compare plus confirmed locked restore; structured panel history, restore preview and proposal cards; server-composed selected hunks with exact client-text verification and under-lock proposal reload; review/delivery freshness propagation; result-aware turn mutation summaries with history IDs. Core Studio also labels manual versus automatic saves. Bridge now allowlists the exact manuscript/revision actions and exposes compare in the manuscript tool. | Failing-first hunk/lock regressions moved from 3 failures to green. OpenWrite `tests/test_revision_service.py tests/test_manuscript_editing.py tests/test_review_store.py` 27/27; `tests/test_studio.py -k 'not local_embedding_probe_does_not_require_a_key'` 67/67 with the known independent Embedding case explicitly deselected; panel component suite 91/91 including save-origin, structured history/selective apply and turn result-state cases; panel and bridge builds pass; bridge smoke passes at 69 tools; focused Ruff E/F/I (existing long-line baseline ignored) and both `git diff --check` pass. No canonical manuscript write or live browser action was used for this focused batch, so S2 remains `partial`. |
| 2026-09-05 | Native framework S2.1 live read-only acceptance | Added a source-backed E2E that pins the exact dsh Workspace for `/Users/jiaoziang/my_novel`, opens the author history/revision inspector, verifies structured headings instead of raw proposal/version JSON, checks version compare when history exists (or the explicit empty state), checks viewport overflow, and compares the selected chapter revision/content before and after. The first full run exposed a mobile drawer setup defect (9 passed/1 failed); the test was corrected to open the mobile inspector through its actual control. | Targeted history E2E then passed 2/2; fresh full `npm run test:e2e` passed 10/10 with no skips at desktop 1440×1000 and mobile 390×844. The selected canonical chapter revision and content were unchanged. S2.1 is done; S2 remains partial for S2.2/S2.3. |
| 2026-09-05 | Native framework S2.2 protected context and truthful inspection | Added a common protected-context invariant across generation and chapter assembly. Author intent, creative focus, core control/canon documents, continuity truth and full current-chapter requirements retain exact rendered values through compression; only optional/derived context can be compressed or excluded. If protected content alone exceeds the request budget, the service returns `PROTECTED_CONTEXT_OVER_BUDGET` with required/available/over-by counts, affected sources and actionable adjustments, and the generator is never called. The manifest now reports every selected source with snippet, selection reason, status, protection reason, source revision and compression reason; it also reports packet/source revisions, missing/excluded material, current/stale comparison, request budget, explicitly unavailable provider actual usage, a separate unavailable dsh-session budget, and current/refreshed/unavailable semantic-index state. The native Studio and dsh Creation inspector render the structured packet and open real source paths. | Failing-first and focused OpenWrite context/Studio selection passed 75/75; final related backend regression passed 169/169 with one unrelated local embedding probe deliberately deselected. Panel component suite passed 96/96, including old-manifest stale detection, protected-budget failure/source links, and simultaneous chapter/Workspace source-plus-budget switching. `npm run build` and 69-tool bridge smoke passed; focused Ruff E/F/I passed; both repository `git diff --check` commands passed. Fresh live E2E against exact `/Users/jiaoziang/my_novel` passed 12/12 with no skips on desktop/mobile and left selected manuscript revision/content unchanged. Live packet `309ff3a03be313af` had source revision `0d47cd22d0e8a557`, 14 items, five protected sections, no missing items, 54,522 estimated tokens within a 91,200 request budget, a separate unavailable dsh-session budget and current retrieval index; a request carrying a bogus prior source revision correctly reported the predecessor stale while the newly built packet remained current. S2.2 is done. |
| 2026-09-05 | Native framework S2.3 entity-level mutation summary foundation | Added `openwrite.mutation-summary.v1`, a bounded domain result envelope carrying entity kind/id/path, field, exact small before/after values, source/result revisions and committed execution status. Oversized values omit the exact value and carry an explicitly truncated 480-character preview, rendered length and SHA-256. Studio emits the contract for document create/update (including manuscript and canon), chapter generation, selected AI revision application, history restore, character/world asset fields, outline edits, foreshadowing nodes, creative focus and project writing targets. The dsh turn-tail event parser retains these results and renders an expandable per-field before/after view with revision provenance; its existing success/partial/failure/committed-refresh-failure semantics remain intact. | Failing-first Studio coverage grew to a seven-domain mutation test and passed. `tests/test_mutation_summary.py` 2/2 verifies exact small values, missing values and honest long-value truncation; affected OpenWrite regression (`test_studio`, `test_revision_service`, `test_manuscript_editing`, `test_novel_service`, independent local embedding probe deselected) passed 97/97, for 99/99 total. Focused Ruff E/F/I passed. Panel turn-summary test is 4/4 and full component suite is 97/97; panel build and 69-tool bridge smoke pass. Both repository `git diff --check` commands pass. This is a partial S2.3 milestone: staged per-item decisions, retry/undo and trace are still required. |
| 2026-09-05 | Native framework S2 document change plans and redacted operation trace | Extended the existing OpenWrite document preview-token mechanism into a server-owned lifecycle: preview/apply/reject/retry/undo, immutable one-time schema-v2 tokens, exact source and predicted-result revision revalidation, and safe undo against the committed result. The bridge exposes one independent edit per `novel_document_change_plan` call and the native dsh turn card renders accept/reject/retry/undo controls without resending paths or replacement text. Added `openwrite.operation-trace.v1`: bridge requests stamp dsh session, root call, tool call and tool name; OpenWrite associates those with request id, packet/source revisions, source paths, budgets, LLM prompt/response digests, provider/model/finish/usage and a value-free domain mutation summary. `novel_trace_list` is the read surface and turn cards link the project-local trace file. Retention is enforced at 30 days/100 records. Tests assert raw prompts, context, model output, chain-of-thought, credentials and mutation before/after values do not appear in trace files; credential fields are omitted before hashing. | OpenWrite combined affected regression passed 154/154 with one unrelated local embedding probe deselected, including a full simulated dsh write request linking context packet → OpenWrite LLM adapter → committed manuscript mutation. Panel components passed 98/98, targeted turn-card tests 5/5, root build passed with existing tsdown/Zustand warnings, preset smoke passed 27 rows/16 skills, and bridge build/smoke passed with 71 tools. Focused Ruff E/F/I and both repository `git diff --check` commands passed. This completes the document-plan and trace foundation; S2 remains partial because direct structured mutation tools and historical M2c/M2d acceptance still require closure. |
| 2026-09-05 | Native framework S1.1 live save acceptance and history-load isolation | The canonical-workspace Playwright setup now seeds the exact dsh session before application startup and rejects every Studio API request whose Workspace header differs from the `/Users/jiaoziang/my_novel` mapping. Its save scenario holds manual A in flight, types B, proves automatic B is serialized with A's returned version, retries an aborted manual request with identical content/version/origin, requires explicit overwrite after 409, and exercises both chapter-switch choices. Creation history now loads independently of expensive context/RAG; a component regression leaves the context request permanently pending while history compare/selective-apply remains usable. | Current-source desktop full project passed 7/7 and mobile full project passed 7/7 with no skips; the real selected and alternate chapters had identical revision/content before and after. `npm --prefix packages/studio-panel run build` passed with existing warnings, and focused `creation-view.test.tsx` passed 17/17. S1.1 is now done. |
| 2026-09-05 | Native framework S2 structured change plans | Added `/api/structured/change-plan` and `novel_structured_change_plan` for one outline, asset, creative-focus, foreshadowing or writing-target proposal. Domain-specific preview code validates and serializes the exact canonical result without writing. Project-local immutable 24-character tokens contain source/result fingerprints and exact content; apply/undo reload the token under the cross-process project lock, recheck the source, atomically write the stored result, consume the token and issue a result-bound undo token. Reject, semantic retry, tamper detection, unsafe-undo conflict, post-write sync/checkpoint, committed-refresh failure reporting and redacted operation trace are covered. Direct tools remain explicit-authorized compatibility entries. The native turn card routes each plan type to its own endpoint and invalidates affected resources. | Failing-first five-domain lifecycle tests and HTTP trace passed; focused domain regression 14/14. Affected OpenWrite regression passed 124/124 with one known independent local-Embedding test deselected. Full panel components passed 99/99; targeted turn-card tests 6/6; root build passed with existing tsdown/Zustand warnings; preset smoke passed 27 rows/16 skills; bridge build/smoke passed with 72 tools. Focused Ruff E/F/I (existing E501 baseline ignored) and both repository `git diff --check` commands passed. S2 remains partial only for M2c/M2d acceptance. |
| 2026-09-05 | Native framework S2 Operations result workbenches | Benchmark artifacts gain a derived, stable comparison identity over context/prompt/rubric/mode/manifest strategy+schema/estimator/packet+source revisions; legacy omissions stay null/incomplete and files are not rewritten. BenchmarkView groups comparable runs and exposes real phases, provenance, configured/actual models, sources, failures, zero-vs-unreported usage/cost, outputs and independent evaluations. Research normalization preserves prompt and completion time, maps legacy complete/completed to succeeded, and ResearchView adds keyword/status/source filters, exact task-result deep links, Workspace route metadata, provenance, failures, safe source verification, Markdown export, a reference-only boundary and scoped mobile layout. Tasks now navigate with `{view,id}` so result links open the immutable requested artifact even outside the newest list. | Failing-first backend and component cases moved to green. OpenWrite benchmark/research 32/32; panel focused results 14/14, full components 106/106 and build pass. Fresh live stack against exact `/Users/jiaoziang/my_novel`: targeted desktop/mobile 2/2 and full Playwright 16/16 with no skips; historical domain payloads and canonical manuscript content/revisions were unchanged, and both viewports had no horizontal overflow. S2 is done. |
| 2026-09-05 | Independent Embedding migration and repository baseline closure | Migrated Python expectations from Chat-embedded vector settings to independent `embedding_profiles`; added isolated cloud/local resolution and server-owned credential/test metadata assertions; aligned the model-profile schema route enum and regenerated Python/TypeScript contracts. Updated semantic-search regressions to check stale-content removal and scope isolation rather than assuming vector search returns no similar document. Benchmark HTTP fixtures now author a real planned chapter, so the project-readiness guard remains exercised instead of being bypassed. | Affected failing set moved from 9 failures to 9/9 passed. Full OpenWrite `uv run pytest -q` passed 1137/1137 with 31 intentional skips in 114.42s. The immediately preceding dsh `npm run check` passed all builds, doctor, 23 maintenance tests, profile/preset smoke, 72-tool bridge smoke, Studio smoke, 14 epochs, 106 components and contracts. M2e is done; S3 is the next implementation stage. |
| 2026-09-05 | Native framework S3 manuscript acceptance and fact consistency | Added the durable `openwrite.manuscript-acceptance.v1` operation/state/fact store with frozen full documents, completed-vs-pending SHA heads, conservative downstream capture, immediate review/rolling-plan/Chapter-Run invalidation, pre/post-analysis revision checks, per-chapter persisted fact artifacts, ordered runtime replay, character-index rebuild, authored outline/foreshadowing review acknowledgement and idempotent resume. Legacy projects require an explicit baseline; external edits remain drift until confirmed. Chapter memory and manuscript character annotations require a current accepted source SHA, while write generation and rolling planning fail closed. Studio save, revision, history restore, import, Agent edits and both write pipelines use the same gateway. Persistent reconcile tasks, four confirmation-safe HTTP routes, two bridge tools and a native CreationView status/action card expose the lifecycle. | Failing-first core tests cover legacy baseline, source changes during analysis, frozen retry, stale propagation, external edits and rapid superseding saves. Final OpenWrite `uv run pytest -q`: 1147 passed, 31 skipped in 101.39s. Final dsh `npm run check` exited 0: builds, doctor, 23 maintenance tests, profile/preset smoke, 74-tool bridge smoke, native panel smoke, 14 epoch tests, 110 component tests and generated/canonical contract checks. Existing non-fatal tsdown/Zustand CJS warnings remain. No model call or canonical manuscript mutation was used for S3 verification. |
| 2026-09-05 | Native framework S4 export preflight core | Added `openwrite.export-preflight.v1` over the real on-disk manuscript inventory. It reports numeric/path order, every duplicate path, sequence gaps, empty prose, per-chapter and book units, metadata, S3 acceptance state, current/stale/missing/not-approved reviews, backup warnings and stricter delivery blockers. Duplicate IDs block all exports before the legacy chapter map can discard one. Preflight revisions protect delayed downloads from changed inputs; generated output is hashed and EPUB receives the existing EPUB 3 structural validation plus explicit ToC/body inspection. Studio exposes the envelope through `GET /api/export/preflight`; `/api/export` accepts purpose and revision. The bridge adds `novel_export_preflight`, extends `novel_export`, and the native Operations transfer panel renders the full gate with conflict refresh. | Failing-first `tests/test_export_preflight.py` covers duplicates, gaps, empty chapters, backup versus delivery, review staleness, revision conflict, HTTP and post-generation EPUB inspection. Focused export/workspace/service regression: 27/27 passed; focused Ruff format/check passed. dsh bridge build/smoke/runtime lifecycle/contracts, panel build/smoke and 113/113 component tests passed; dsh diff check passed. Live EPUB human inspection, staged import and archive/restore remain, so S4 stays in progress. |
| 2026-09-05 | Native framework S4 resumable import and portable archive core | Added `openwrite.manuscript-import.v1`: immutable source snapshot, stage input/output fingerprints and attempts, editable split revision, explicit structure confirmation, duplicate-ID rejection, operation-root staging, recoverable whole-arc swap, S3 acceptance/reconciliation, ordered fact-backed synthesis with coverage/runtime revision, latest-first credential-free summaries and safe pre-publish discard. Added `openwrite.novel-archive.v1`: preflight revision, versioned manifest, per-file SHA/size/category, explicit includes/excludes/missing/reference inventory, credential/cache/lock/export exclusions, deterministic safe ZIP, tamper/Zip Slip limits, atomic cross-path restore, optional novel-ID and known-reference remap, explicit unresolved-reference warnings, and old task archival without resume. Studio/HTTP add resumable import list/detail/prepare/edit/confirm/run/discard, archive preflight/create/list/detail/download, restore preview/confirmed task, file-unit progress and archive task result references; relative/current-project restore targets are rejected. | Core import tests 6/6 and archive tests 9/9 passed. Combined import/archive/Studio transfer/export/task-surface/schema-parity run passed 100/100; focused Ruff and Python compile checks passed. Full current OpenWrite `uv run pytest -q` passed 1172/1172 with 31 intentional skips in 117.99s; schema-codegen check and repository diff check passed. The restore test opens the newly restored temporary Workspace and proves remapped config/path plus manuscript byte identity. dsh import/archive UI and live human migration inspection remain before S4 acceptance. |
| 2026-09-05 | Native framework S4 final acceptance | Closed three audit classes: restored import journals rebind every operation path to the restored root; delivery checks block project-level `baseline_required`/`needs_review`; export now stages under the project lock, rechecks preflight before a no-clobber hard-link commit, preserves concurrent destinations and recoverable `.previous` files, and treats post-commit cleanup as best effort. The dsh native transfer workspace adds resumable import structure editing, archive inventory/download/restore preview, ID/reference policy and task no-resume status. Live preflight then exposed nested LightRAG indexes, debug logs and benchmark sandbox Workspaces in the package; these rebuildable artifacts are now excluded while benchmark result JSON and foreshadowing history remain portable. | `uv run pytest -q`: **1180 passed, 31 skipped** in 97.62s before the final cache rule; the amended archive suite is 10/10 and the combined export/import/archive suite is 29/29, with focused Ruff, schema codegen check and both `git diff --check` green. dsh `npm run check` exited 0: 24 maintenance tests, 78 bridge tools, 56 tool cards, 14 epoch tests and 117 component tests. Live browser on `/Users/jiaoziang/my_novel` showed delivery blockers (`baseline_required`, missing author, reviews not approved), backup warnings without blockers, empty resumable-import/archive lists and the archive surface. A live EPUB backup was 59,010 bytes, ZIP-clean, `application/epub+zip`, one nav, six spine chapters and seven XHTML files; manuscript hashes were byte-identical before/after. Corrected archive preflight reports 1,309 files/23,506,405 bytes with no required omissions, zero nested benchmark Workspaces and zero novel `.openwrite` files; automated restore creates, opens and byte-verifies an isolated new-path Workspace. |

| 2026-09-05 | Native framework S5 canonical author workbench | Added canonical reading/document order with stable document and occurrence IDs, explicit planned-missing entries, revision-bound same/cross-volume moves, 20-document continuous-reading windows, chapter work briefs, stable search locators and safe replace previews, plus review→revision→rereview closure with resolved/retained/regressed findings. Studio routes are isolated by canonical A/B Workspace roots; dsh consumes the contracts in Creation and Search. | OpenWrite focused reading/work-brief/search/review/revision/workspace tests passed 67/67; bridge build/smoke passed with 82 tools; the pre-S6 panel suite passed 135/135. Live read-only `mujianzhe` projection returned 133 documents, six present and 127 planned missing with zero blockers, and left all six manuscript hashes unchanged. S5 is done. |
| 2026-09-05 | Native framework S6 stable scene structure and downstream integration | Added `openwrite.scene-structure.v1`, Unicode codepoint anchors, stable scene identity, canonical reading and story-time orders, character/location/event references, explicit migration preview/apply/rollback, exact CAS metadata and same/cross-chapter moves. Current scenes drive context and Markdown/TXT/EPUB order; stale/ambiguous structures are excluded from prompts, block delivery, and make backup export fall back to whole prose. Studio exposes seven scene routes; bridge exposes seven scene tools; SceneWorkbench renders all states, issues, dual order, references, migration, rollback and three-revision moves. | Scene core 13/13; combined S6 scene/export/context/Studio regression 110/110; full OpenWrite `.venv/bin/pytest -q` **1224 passed, 31 skipped** in 132.08s. Full dsh `npm run check` exited 0 with 24 maintenance tests, 89 tools, 14 epochs, 144 components and canonical/generated contract parity. Schema codegen check, focused Ruff E/F/I and both diff checks passed. S6 is done. |
| 2026-09-05 | S1-S6 live final acceptance and hygiene | Current launchd Studio plus current dsh web were exercised only against `/Users/jiaoziang/my_novel`. `scripts/verify.sh` passed all 19 proxy/context/SSE/static checks after its cold-read deadline was raised for the 861 KB Workspace snapshot. Read-only APIs returned a 20-chapter packet, a revision-bound chapter brief, absent scene surface and an applicable six-chapter/six-scene migration preview with no blockers. A headless visual pass opened Library→Outline→native SceneWorkbench, showed absent state and the read-only preview with zero scene writes or horizontal overflow. Full Playwright passed 16/16 across 1440×1000 and 390×844 after the browser read deadline was aligned with measured large-project cold reads. | All six canonical manuscript files remained byte-identical; no `scenes.json` sidecar was created. Non-outputting OpenRouter-signature scans and both `git diff --check` commands passed. The only remaining required action is external: delete the temporary OpenRouter key; human calibration is still required before enabling the production gate. |
| 2026-09-05 | Public release gate and dsh-Openwrite rebrand | Product-facing repository, README, root npm package, conductor metadata and doctor output use `dsh-Openwrite`; stable `@dsh-novel/*` package scopes, Schema versions and browser storage keys remain unchanged for compatibility. OpenWrite README links the paired plugin repository. | dsh `npm run check` exited 0 with 90 bridge tools, 24 maintenance tests, 14 epoch tests, 144 component tests and shared contract parity. OpenWrite `.venv/bin/pytest -q` completed with **1235 passed, 31 skipped** in 148.77s. JSON parsing, both `git diff --check` runs and a high-confidence secret scan passed; reported scan candidates were dependency identifiers or explicit test fixtures. User authorized publication to the GitHub repositories. |
| 2026-09-05 | Automatic DoG installation and live profile activation | `scripts/install.sh` now bootstraps the pinned `Fun10165/dsh-dog v1.2.0` (`ac64806d97872ce4c58b6d22ce96f74a29477b9f`) into `$DSH_HOME/extensions/dsh-dog`, validates its package identity, builds and mounts it only in web, reuses valid installs, supports an explicit worktree/opt-out, cleans partial clones and retries without Git HTTP(S) proxy after a proxy failure. Session Workspace is the dynamic graph root; the written `dog.workspaceRoot` remains a fallback. | Ten isolated lifecycle tests pass, including failed-proxy retry and idempotent reuse; the full gate passes with 25 maintenance tests, 90 bridge tools, 144 components, 14 epochs and canonical/DoG contract parity. A real isolated upstream-tag installation and profile doctor passed. The real user profile doctor also passed: web has bridge/panel/DoG and headless has bridge only. Restarted dsh web serves the DoG and Studio panel client assets with HTTP 200. No model or manuscript mutation was used. |

## Residual risks and external limits

- M2b client-side numeric validation only enforces positive/0–2 ranges; the
  stricter backend bounds (context ≥ 12000, output ≥ 256, timeout ≤ 1800,
  output < context) still arrive as `INVALID_MODEL_PROFILE` error notices —
  intentional single source of truth, but the form does not pre-compute them.
  The routes impact line persists until the next routes save; a profile CRUD
  reload does not clear it. Form and route edits are now preserved across
  connection-test/background reloads; explicit refresh/navigation requires an
  explicit discard choice.
- The dedicated temporary OpenRouter key appeared in an earlier conversation.
  The user explicitly accepts that short-term risk for this work and intends to
  delete the key afterward. It remains forbidden to read, print, artifact, or
  commit the value. The real framework matrices finished; free-model availability,
  rate limits, truncation, reasoning-token reporting, latency, and cost remain
  provider-dependent reliability concerns rather than manuscript quality scores.
- Human calibration does not exist yet. The 70 quality and 80% coverage defaults
  are advisory only; the production gate is explicitly disabled and cannot be
  enabled while calibration status is `uncalibrated`.
- The Studio log recorded remote LiteLLM price-map timeout/local fallback and a
  failed optional Hugging Face embedding download during search. Neither affected
  DAG/benchmark API QA, but both are provider/network reliability signals.
- Zustand still emits a non-fatal CJS `import.meta` build warning. A later fresh
  in-app-browser tab loaded the application fully within five seconds with no
  console errors, so the earlier transient `Loading plugins...` observation is
  no longer an active residual.

## Final acceptance checklist

- [x] All legacy IDs 1-37 are retained exactly once.
- [x] Every positive point has locatable manuscript evidence.
- [x] N/A, inconclusive, quality, coverage, blocker, and delivery semantics are distinct.
- [x] Normal full review uses about seven model calls.
- [x] DoG never reruns LLM review work.
- [x] Old artifacts remain readable and manuscript edits make reviews stale.
- [x] Python and TypeScript graph/artifact contracts have parity tests.
- [x] Benchmark runs are profile-backed, isolated, blind-reviewed, and credential-free.
- [x] Review and delivery DAGs are interactive and verified on desktop and mobile.
- [x] Golden samples and dual v1/v2 calibration outputs exist.
- [x] Final thresholds are either supported by 10-20 real human labels or clearly
      remain uncalibrated with the production switch disabled.
- [x] Full tests, builds, live QA, documentation, and secret scans pass.
- [x] The final report names external provider limits and all residual risks.
- [x] User explicitly authorized the dedicated temporary OpenRouter key for this
      work and deferred deletion until final acceptance.
- [x] A real two-writer × independent-reviewer free-model matrix has been
      recorded without changing global routes or canonical manuscript files.
- [x] Post-audit corrections: freshness-unknown delivery fix, delivery recordType
      unification, DoG/bridge legacy adapters isolated with decisionSource,
      graph/dag epoch remounts wired, canonical compaction completeness, and
      workspace v2 summaries — each with regression tests or live QA evidence.

Do not mark the Goal complete by checking boxes from intent or file presence.
Each box requires direct current-state evidence recorded in the verification log.
