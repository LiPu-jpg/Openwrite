# Reliability and language changes (issues #76 and #65)

This change targets the deterministic failures reported against plugin 0.2.19 / Core 5.8.9. It does not calibrate literary scores or make model reviews deterministic. Automated regression tests use isolated registries and fake model responses.

## Writing and recovery

`novel_write_chapter` now submits `chapter_write` to the durable task queue and returns `task_id` immediately. Poll `novel_task_get`. A transport error cannot prove rejection: use `novel_tasks_list(since=<ISO timestamp>)` or `novel_chapter_run_action(action="list", since=...)` before submitting again. Transport diagnostics store endpoint, timestamp and call identity, without credentials or prompt content.

If commit fails, generated prose remains recoverable. New manuscripts remain on disk with a `.uncommitted.json` sidecar; an existing manuscript is restored and the generated replacement is saved separately. The error includes `run_id_v2`, `draft_artifact`, and `draft_path`. Resume with `novel_write_chapter(chapter_id=..., run_id_v2=...)` or `resume_from_draft=true`. Recovery reuses the completed draft and facts, verifies the input revisions, and retains its original target and model provenance. Reconcile stale acceptance first when requested. `novel_task_retry` also resumes eligible drafts and completed continuous tasks with failed chapters.

`PROJECT_BUSY` defers the task and retries after two seconds. It does not consume the continuous failure budget. Cancellation is cooperative: `cancel_requested=true` means requested; `cancelled=true` means the persisted task is actually cancelled. `wait_seconds` waits up to 30 seconds; otherwise poll. In-flight model calls may finish before cancellation is observed, but cancelled runs reject late commits.

The chapter target contract is **200–50000**, with precedence **explicit argument → chapter outline → 3000**. Preview and write return `target_words_source` and the effective range, **−20% / +50%**. Resume retains the draft's target; changing it requires a fresh generation. Outline chapter metadata is validated on structural edits, document writes and change plans; volume totals have separate limits. Runs retain `model_profile`, `requested_model`, actual `model` and `provider`; differing model resolution is flagged.

## Acceptance and editing

A `STALE_ACCEPTED_REVISION` error includes the operation handle and recovery actions. Inspect the operation before choosing:

- `resume` continues an incomplete acceptance using its frozen input.
- `abandon`, with `operation_id` and `confirm=true`, releases only that operation's pending heads and retains its audit record. It does not delete or silently accept manuscript text. A real unaccepted manuscript still requires baseline/external acceptance.
- `external`, with `confirm=true`, explicitly accepts the currently observed manuscript as a new source revision. This supersedes the prior pending revision; it is a deliberate re-baseline, not a reread or a retry.

Capture rejects missing chapters. `acknowledge` supports outline, foreshadowing, canon, chapter_memory, character_state, runtime_facts, review, plan, search and downstream_chapters. It records human review of impacts; it does not repair a stale acceptance operation.

Document change plans accept **1–50 edits**. Their default response contains a bounded diff and edit summary; workspace output is opt-in. Both range endpoints must be individually unique. Exact matching preserves UTF-8 bytes and line endings; no automatic fuzzy selector is used by the public tool. `normalizations` reports any explicitly selected compatibility normalization. Apply/undo require the stored preview token **and `confirm=true`**. Revision is checked again under the project lock and written bytes are verified against the accepted preview.

Asset lists include revisions usable by asset update. `update_summary` replaces the synopsis; supplying a full structured body replaces its metadata too. A prose-only synopsis retains execution metadata. `promote` or `delete(cascade=false)` removes a container while preserving child chapters and their IDs. `get_meta`/`set_meta` accept a chapter ID and metadata fields `target_words`, `beats`, `hooks`, `characters`; `updates[]` reads/writes up to 50 chapters atomically under one outline revision.

## Review scope and history

A restricted dimension request retains the complete rubric and marks unrequested criteria inconclusive. The hard gate and the minimum manuscript structure check always run. Partial reviews, insufficient coverage and unverifiable canon cannot produce delivery `pass`. Tagged model reasoning is removed; unclosed reasoning or unstructured/preamble output is rejected before manuscript generation is accepted. Chinese and English chapter headings are supported.

Uncalibrated review scores are advisory. The review v2 response omits `production_gate_status` unless the caller explicitly enables a calibrated production gate. Legacy adapters and benchmark metadata may still carry their calibration fields. `strict` records the requested review mode; it does not turn missing canon evidence into `blocked`, add another audit pass, or guarantee higher detection. A confirmed hard violation remains blocked in every mode.

`novel_review_chapter(action="versions", chapter_id=...)` lists review snapshots. `action="compare", revision=<listed SHA>` compares that snapshot to the current review. Existing current records are archived on their next save; versions overwritten by older releases cannot be reconstructed.

The supported review scope is **chapter**, returned as `check_scope="chapter"`. Book-wide repeated sentences, recurring phrase habits, quotation-style consistency and cross-chapter template detection are outside the 37-check contract. The new structure check covers headings, preamble and reasoning contamination; it is not a complete copyediting audit.

Foreshadow overdue status is **advisory**, visible through continuity/diagnostics and chapter obligations. It does not automatically block delivery. DAG cycle checks operate only on explicitly recorded dependencies; `edges: []` means no supplied dependencies, not evidence that all narrative relationships were checked. Authors must record dependencies and decide whether to delay writing for overdue promises.

## Report coverage

| #76 item | Treatment |
|---|---|
| 1–2 | Preserve failed-commit prose; expose and resume draft handles; partial task retry |
| 3–5 | Structured outgoing errors; immediate task handle; `since`; transport/orphan diagnostics |
| 6–7 | Busy deferral without failure accounting; truthful cancellation and bounded wait |
| 8–9 | Executable acceptance recovery/abandon; distinct actual model provenance |
| 10–11 | Shared target resolver and outline validation; asymmetric length window |
| 12–15 | Unique anchors/confirmation; asset revisions; synopsis replacement; preserve children |
| 16–17 | Full rubric coverage, permanent hard/structure checks, reasoning rejection |
| 18–24 | Async write, queue retry, shared targets, ghost cleanup, run archive, compact batches, byte verification |
| 25–28 | Optional production field; inconclusive canon/coverage; explicit strict scope; review history |
| 29 | Explicit chapter scope; minimal format gate; book aggregation explicitly out of scope |
| 30 | Revision-gated field metadata, including atomic chapter batches |
| 31 | Documented advisory overdue responsibilities and explicit DAG dependency scope |
| 32 | Expanded acknowledgement domains |

## English (#65)

Choose **Settings → General → Language → English** in dsh (`locale.preference`). The panel follows the active locale. The agent persona and every skill entry point instruct the agent to answer in the author's language, including slash-command help, plans and explanations. An explicitly requested manuscript language takes precedence for creative text. Managed runtime messages are English; Studio HTTP errors include English `message`, stable `code`, `details` and `request_id`, while retaining the original diagnostic in `error`. Task phases/errors provide English text. Existing Chinese project/source content is not translated automatically.
