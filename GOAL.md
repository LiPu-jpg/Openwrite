# OpenWrite Review v2 Goal and Status

> Canonical project record for the cross-repository review-v2 work.
>
> Last updated: 2026-08-31 (contract hardening, shared schemas, epoch tests, schema codegen, component/E2E runner)
>
> Repositories: `/Users/jiaoziang/dsh-novel` and `/Users/jiaoziang/OpenWrite`

This file is the single source of truth for the goal, architectural decisions,
current status, remaining work, verification evidence, and local credential
requirements. Future Goal runs must read this file completely, inspect both
current worktrees, and then continue the first unfinished item. Conversation
history is context only and must not override current repository evidence.

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
Read /Users/jiaoziang/dsh-novel/GOAL.md completely and continue the active
OpenWrite review-v2 goal from its current-state and next-work sections. Treat
the two current worktrees as authoritative, preserve existing user changes,
update GOAL.md as evidence changes, and do not declare completion until every
acceptance item has direct test or runtime evidence. Never read, print, persist,
or commit raw credentials. Manual/live/browser QA may use only ~/my_novel.
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

## Current state

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
| Benchmark bridge tool | done | 63-tool registry; task compaction now preserves the full canonical v2 subset (schema_version, production_gate_status, freshness_status, source revisions) — smoke-asserted | None |
| Read-only DAG API | done | `GET /api/dog/graphs`; v2 delivery manifests are contract-validated at read time, legacy artifacts pass through | None |
| Review and delivery DAG frontend | done | Live desktop/mobile QA: 47/52 expansion, Chinese field labels, six-domain chips, overview row, evidence quote, issue-to-revision action, zero overlap/overflow | None |
| Benchmark frontend | done | Multi-reviewer multi-select, provider · real model id, `$0` vs unknown cost distinction | Historical artifacts render explicit unknowns |
| Review/task cards | done | Canonical severity vs `revision_priority` preserved; compaction keeps production-gate/freshness so cards can render them | None |
| Golden samples and dual v1/v2 report | done | Synthetic fixtures plus new v2-authority regression cases | Human calibration remains external |
| Studio model profile page and write allowlist | done | CRUD/chat/embedding tests/dependency preview/fallback verified live; `/model/*` writes allowlisted and smoke-tested; surface contract-validated at the API boundary; credentials write-only | None |
| Workspace chapter review summaries | done | `_load_review_result` now exposes canonical `review_v2` subset (quality/coverage/gate/delivery/production gate/freshness/source revision) next to legacy aliases; stale merges freshness | Frontend chapter list may still show legacy subtitle text |
| Resource epochs and SSE fallback | done | SSE primary + 5s polling fallback; derived invalidation closes the graph loop — assets/manuscript/outline/workspace mutations also bump `epochs.graph`, remounting GraphView which refetches `/api/continuity` on mount; DAG views remount on `epochs.tasks`; benchmark/models epochs keyed remounts; SSE verified in `verify.sh` | Conductor-side direct file writes to `data/dog` bypass API mutation events; DAG reload relies on task completion |
| Frontend automated tests | done | `npm run test:epochs` 9 pure-function tests; `npm run test:components` (vitest + jsdom + @testing-library, `packages/studio-panel/scripts/components/`) 10 tests: ModelView credential non-echo (explicit fake `test-credential-abc` POSTed once, fields cleared, never echoed into the DOM; empty field omits the key; delete round-trip clean), GraphView tasks-epoch remount refetches `/dog/graphs`, WorkbenchStore SSE-error→5s-polling fallback + SSE≡polling epoch identity + revision dedup; `npm run test:e2e` (Playwright, repo-local browsers under `packages/studio-panel/.pw-browsers/`) probe-gated: services down → 6 skipped with printed reason, exit 0; live dev stack → 4 passed (shell zero horizontal overflow on 1440×1000 and 390×844, model view password inputs empty + no `sk-or-v1-`/`api_key` in DOM, mobile workbench tabs reachable + zero overflow) / 2 project-gated skips | Live-service E2E assertions only run when dsh web (3080) and Studio (4567) are reachable; otherwise the suite skips by design and proves nothing about the UI |
| Credential rotation observability | done | Server-managed timestamps credential-free; storage/HTTP tests pass | Available for future rotations |
| Secret hygiene | done | Non-outputting `sk-or-v1-` scans 0 hits both worktrees; `git diff --check` clean | Remind user to delete the temporary key after acceptance |
| Full regression/build/browser acceptance | done | OpenWrite full suite 979 passed/31 skipped (105.60s); dsh build, DoG 6, bridge smoke 63 tools, `test:contracts` (schema parity + dog canonical incl. review_v2 type matrix), `test:epochs` 9, `scripts/verify.sh` 14/14, strict dog API verified live against `~/my_novel`; harness headless browser cannot open pages (infrastructure defect), so live UI evidence remains the earlier recorded desktop/mobile QA — server paths used by the UI verified via curl | Human browser pass still recommended |
## Next work, in order

1. Separately collect 10–20 representative human chapter labels, choose defensible thresholds, set calibration to `calibrated`, and only then enable the production gate.
2. Optional refactor: split `studio_application.py`, bridge `tools.ts`, `AssetsView`, `GraphView`, large CSS.
3. After full acceptance, remind the user to delete the dedicated temporary OpenRouter key.

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
| 2026-08-28 | Diff and secret audits | `git diff --check` in both repos; non-outputting `sk-or-v1-` signature scans excluding `.git`/dependencies/caches | Both clean: 0 whitespace errors, 0 signature matches |
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
| 2026-08-30 | Stage: full regression and gates | OpenWrite `.venv/bin/pytest -q`: 971 passed, 31 skipped (97.54s); `npm run build`; `npm run test:dog` 6; bridge smoke 63 tools; `test:contracts` (schema parity + dog canonical); `test:epochs` 8; `scripts/verify.sh` 14/14 PASS after server restart; strict dog API verified live against `~/my_novel` (47 nodes / 6 stages); `git diff --check` + non-outputting `sk-or-v1-` scans clean in both repos; harness headless browser cannot open pages (infrastructure defect, curl/verify unaffected) — earlier recorded desktop/mobile QA remains the UI runtime evidence, human browser pass recommended |
| 2026-08-30 | Third-stage P1: review_v2 type bypass fix | `tools/review_store.py` adds `has_review_v2_field` (key present, even null) and `review_v2_malformed` (present but null/list/string/number/bool/empty-object); `review_is_deliverable` returns False for malformed v2 regardless of legacy score/passed; status helpers (`review_gate_status`/`review_delivery_status`/`review_quality_score`) return inconclusive/null for malformed v2 instead of legacy-derived values; `canonical_review_decision` raises ValueError for malformed v2; `review_chapter()` rejects non-object/empty review_v2 with `CONTRACT_INVALID`; legacy adapter reserved for records without the key; `.venv/bin/pytest -q tests/test_canonical_contracts.py tests/test_review_store.py tests/test_review_v2_http.py tests/test_studio.py` — 85 passed incl. parametrized null/[]/string/number/bool/empty-object matrix |
| 2026-08-30 | Third-stage P1: TS existence/type/version parity | `dog-review.ts buildDogReviewBundle` and `dog-delivery.ts materializeChapterDelivery` now throw on present review_v2 key that is null/non-object/empty or declares an unsupported schema version (mirroring Python); only records without the key ride the v1 adapter; `dog-canonical.mjs` extended with null/[]/string/number/bool/empty-object matrix + legacy-only `decisionSource: v1-adapter` assertion + materializer negatives for array and null review_v2; `npm run test:contracts` passed |
| 2026-08-30 | Third-stage P1: review manifest schema negatives both sides | Python `test_contract_schema_parity.py::test_review_manifest_schema_and_validator_reject_negatives` (unknown version, bad recordType, non-`ch_N` chapterId, bad verdict, missing required keys — schema and hand validator agree); `validate_review_manifest_v2` hardened with `ch_\d+` chapterId pattern; JS `contract-smoke.mjs` runs the same review-manifest schema over the fixture and delivery-stage negatives | Schema + hand validator parity proven on both sides |
| 2026-08-30 | Third-stage E: epochs workspace derivation | `workbench-epochs.ts` + `npm run test:epochs` now 9 tests incl. workspace→graph derived bump, manuscript→graph, SSE≡polling identity | 9/9 passed |
| 2026-08-30 | Third-stage gates | OpenWrite `.venv/bin/pytest -q`: 979 passed, 31 skipped (105.60s); dsh `npm run build`; `npm run test:dog` 6; bridge smoke 63 tools; `test:contracts` (schema parity + dog canonical incl. type matrix); `test:epochs` 9; `scripts/verify.sh` 14/14 PASS after server restart; `git diff --check` + `sk-or-v1-` scans clean both repos; production gate untouched (`disabled_uncalibrated`) |
| 2026-08-28 | Browser note after harness restart | Headless harness tab diagnostics: signal-free fetch to `/api/dog/graphs` 200 in ~15ms; manual-AbortController fetch 200 in 2ms; only `AbortSignal.timeout`-attached fetches never resolve in the restarted harness daemon; `verify.sh` and curl unaffected | Desktop/mobile runtime QA from the earlier session remains the recorded evidence; the harness limitation blocks an automated re-pass — flagged for a manual browser check on the user's machine |
| 2026-08-31 | Stage: schema codegen (review-v2 next-work #1) | `tools/schema_codegen.py` renders Python+TS types/validators from the six `contracts/*.schema.json`; runtime switched to generated validators in `studio_application.py`, `review_store.py`, `conductor/pipeline.py` and TS `dog-review.ts`/`dog-delivery.ts`; hand validators kept as parity reference (bool-as-number aligned with the schema); schema-lint mirrors aligned (strict object type on the JS side); dog parity fixture gained the required `production_gate_status` | `OpenWrite/.venv/bin/pytest -q`: 1009 passed, 31 skipped (independent re-run 76.00s); `npm run build`; `npm run test:contracts` (schema matrix + generated-validator matrix + dog canonical); `npm run test:dog` 6; `npm run test:epochs` 9; bridge smoke 63 tools; `conductor/test_pipeline_contract.py` 4 passed; `tools/schema_codegen.py --check` reports both artifacts current (byte-identical); live dog API re-verified post-codegen against `~/my_novel` on a fresh Studio: ch_001 and ch_006 each load 47 review nodes / 7 delivery nodes through the generated-validator path; `git diff --check` and non-outputting `sk-or-v1-` scans clean in both repos |
| 2026-08-31 | Stage: React component + E2E runner (review-v2 next-work #1) | vitest + jsdom + @testing-library component layer under `packages/studio-panel/scripts/components/` (jsdom chosen over happy-dom for React 18/testing-library maturity); Playwright runner `packages/studio-panel/e2e/workbench.spec.mjs` probe-gated on dsh web 3080 + Studio 4567, repo-local browsers (`PLAYWRIGHT_BROWSERS_PATH=packages/studio-panel/.pw-browsers`, gitignored), desktop 1440×1000 + mobile 390×844 projects; new devDeps: vitest ^4.1.11, jsdom ^30.0.1, @testing-library/react ^16.3.3, @testing-library/dom ^10.4.1, @playwright/test ^1.62.1 (lockfile synced); root scripts `test:components`/`test:e2e` added | `npm run test:components`: 10/10 (ModelView credential non-echo ×4 incl. fake `test-credential-abc` POST-once-then-cleared and never in DOM; GraphView tasks-epoch remount refetch of `/dog/graphs` ×2; WorkbenchStore SSE-error→5s-polling fallback, SSE≡polling identity, revision dedup ×4); `npm run test:e2e` services down: 6 skipped, exit 0, reason printed; live `scripts/dev.sh` stack: 4 passed (shell zero-overflow ×2 viewports; desktop model view password inputs empty, no `sk-or-v1-`/`api_key` in DOM; mobile 390×844 tabs reachable + zero overflow) / 2 project-gated skips, stack stopped afterwards; gates: `npm run build` (known Zustand warning), `test:epochs` 9, `test:contracts`, `test:dog` 6, bridge smoke 63 tools; `git diff --check` + `sk-or-v1-` signature scans 0 hits both repos |

## Residual risks and external limits

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
