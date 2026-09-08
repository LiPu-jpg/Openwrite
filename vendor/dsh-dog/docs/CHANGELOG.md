# Changelog

## v1.2.0 (2026-08-24) — real parallelism & true cancellation

### dependsOn: completion gate with real-time wakeup
- A dependency is satisfied once its target reaches **any terminal state**
  (success/failure/needs_human/cancelled/invalidated/partial/inherited) —
  not only success. The waiter is released to run its own judgment.
- **No more dead `blocked` latches**: a leaf with an unfinished dependency
  stays `pending` and is **re-checked on every pump**; a fast programmatic
  sibling that settles moments later releases the waiter immediately.
- Scheduler no longer `break`s the scan when the agentic budget is full —
  it `continue`s, so programmatic leaves and freshly-released dependents are
  picked up in the same round instead of waiting for an agentic completion.
- Regression: released leaf starts **strictly before** its running siblings
  finish (test that reddens under the old batching scheduler).

### Composites run concurrently — never a serial for loop
- Mutually independent composites now run their whole-object assertions
  **concurrently** (watermark under the **same** agentic budget as leaves,
  `inFlightAgentic` shared), instead of one at a time in postorder.
- Regression: two independent groups — group B's assertion must start while
  group A's assertion is still running (serial implementation fails).

### `dog_cancel` now truly cancels
- Run-level `AbortController` is actually propagated to `executeRun` (was
  being replaced by a fresh never-aborted signal inside `enqueueBackground`).
- In-flight verifiers settle `cancelled` instead of completing their work;
  the stale **completion record can no longer overwrite a cancellation**.
- Host hook interrupts the run's live verifier subagents (`onRunCancelled`).
- Regression: cancel mid-run → record stays `cancelled`, leaf ends
  `cancelled`, never flips back to `completed`.

### UI truthfulness
- A composite's `running` state is persisted when its whole-object assertion
  starts — the panel no longer shows a stuck `pending` during a long review.

### Tests
- 41 engine/plugin tests (added: dependency wakeup order, composite
  concurrency, cancel-aborts-in-flight).

## v1.1.0 (2026-08-24) — work-anywhere + inspectability

### Capture roots follow where you work
- **Invoking session cwd is the first capture root**: `dog_create` now looks
  for `target` in the session's working directory first; the configured
  `dog.workspaceRoot` is the fallback. Working in a different project no
  longer requires touching settings — the working directory is runtime state
  and never leaks into configuration. Escape protections apply per root.
- Regression test: cwd hit → fallback root hit → honest `missing` when the
  target is absent from both.

### Timeouts & budgets
- **Verifier (agentic leaf + whole-object assertion) settlement wait: 300s → 900s (15 min)**.
- **Programmatic script execution: 300s → 900s**.
- `dog_wait` background job wait budget: 30 min → 120 min (long multi-leaf
  runs no longer get their background wait cut short). Timeout semantics
  unchanged: timeouts settle honestly `inconclusive` → `needs_human`, never a
  guessed verdict.

### Live settings (no restart)
- `maxConcurrentVerifications` is now read **per run** through a live config
  source: editing `~/.dsh/settings.yaml` takes effect on the next run without
  restarting the host process.

### Composite evidence retained
- **Whole-object assertion verdict + evidence are now recorded on the
  composite goal result** (and appended to `verifications/<runId>.jsonl`).
  Previously the merged failure carried only `whole-object assertion failed`
  and the rationale was lost — `dog_status` now surfaces the reviewer's
  reasoning like any leaf.
- Regression test: assertion failure must carry `verification.evidence`.

### Settlement text preserved
- The verbatim verifier settlement is saved to
  `~/.dsh/dog/settlements/<sha256(runId)>-<sha256(goalId)>.json` the moment it
  is read. Verifier workspaces are still reclaimed at run teardown, but "what
  happened" stays inspectable forever.

### Docs & demos
- New exhaustive agent manual: `docs/agent-guide.md` (tool surface, graph
  language, state semantics, file-level result reading, diagnostics,
  best practices, setup/run). README rewritten around the core idea
  (non-formal decomposition + independent verification) with honest
  reproducibility limits.
- `examples/` demo module: article-quality (four-dimension gate) and
  dog-smoke-multi (3-level tree + mixed kernels + dependency edge).
- headless profile is documented as *not supported* (one-shot process kills
  verifier workers — known limitation); web/tui are the supported hosts.

### Tests
- 35 engine/plugin tests (added: cwd-first capture roots, whole-object
  evidence retention; existing suite maintained green).

## v1.0.0 (2026-08-23) — stable

DAG of Goals (dsh-dog) reaches 1.0 after the v0.9 judgment-layer rework and a
full end-to-end hardening pass against live web/headless runs. Protocol
`schemaVersion` stays `0.9`; this entry tracks product version 1.0.0.

### Setup & configuration
- **workspaceRoot settings race fixed**: the engine now re-reads the live
  settings scope at construction instead of freezing the registration-time
  snapshot (schema default `dog/workspace` could win when the settings file
  loaded asynchronously, making every capture resolve against a missing root).
- **Programmatic script names resolve without `.js`** (`resolveScriptPath`):
  `"script": "slop-phrases"` resolves `slop-phrases.js` in the library.
- **Script library, docs**: `~/.dsh/dog/scripts/` shipped with
  `slop-phrases.js`, `file-non-empty.js`.

### Judgment protocol
- **Settlement contract unified**: verifier subagents are told to write
  `{"verdict": "pass|fail|inconclusive", "evidence": …}` and `parseSettlementFile`
  reads exactly that (pre-0.9 `settlement`/`observation` still accepted as
  fallback). Previously the prompt and parser disagreed, so every agentic
  verdict settled `inconclusive` → `needs_human`.
- **Whole-object assertion events report the real verdict** (pass/fail/
  inconclusive) instead of an unconditional `verifier_passed`.

### Scheduling & composition
- **True watermark parallelism**: any finished verifier immediately refills
  its slot; the old wave barrier (wait for the whole batch, then start the
  next) is gone.
- **Programmatic leaves are unqueued**: the concurrency budget gates only
  agentic (model-backed) verifiers; script-based leaves run as soon as their
  dependencies are satisfied.
- **`relationTruth` honors inherited results**: an inherited `failure` is a
  failure (`verification.passed` drives the truth value), an inherited
  `needs_human` is `needs_human`; dependency gates use `succeededState`.
- **Whole-object assertions skip when the subtree already failed** (a
  demote-only merge cannot repair it — no wasted agentic review).
- **`dependsOn` semantics documented and drawn correctly**: `source` depends on
  `target`; the UI arrow runs target → source.

### Persistence & life-cycle
- **Leaf settlements persist immediately** (`saveProgress` on `goal_settled`)
  instead of leaving the goal column `running` until the composite phase.
- **Verifier workspaces outlive their verifier**: released at run teardown
  (`releaseAll`), so late settlement writes are still read (generous 15s grace
  window); also fixes the never-released composite-assertion workspace leak.
- **Orphan recovery at host boot**: any persisted run left `running` by a dead
  host is cancelled immediately (run level *and* goal level); its settled
  leaves remain inheritable by the next run of the same graph.
- **Inheritance source broadened** to any non-running prior run (completed,
  cancelled, failed), so restarted hosts resume leveraging prior settlements;
  the half-dead `resumeRun` path was removed in favor of inheritance.

### UI (debugger)
- `RUNTIME_PHASES` gains `verifier_released` (was breaking goal-trace parsing
  → "Context unavailable").
- Snapshot parses `passed: null` (legitimate for unsettled/inconclusive) and
  filters pre-0.9 graphs out of the panel (they poisoned the whole snapshot).

### Tests
- 33 engine/plugin tests, including regression guards for: watermark
  parallelism (temporal ordering), programmatic unqueued execution,
  inherited-failure propagation, skipped assertions on failed subtrees,
  inheritance from cancelled prior runs, and settlement protocol.

### Known limitation (honest disclosure)
- Agentic leaves are **single-shot**: one isolated verifier per judgment, no
  re-check or voting against single-judge blind spots (the v0.2-deferred
  calibration item remains unimplemented). Removing the evidence schema also
  removed structural comparability, so "reproducible" holds strictly for
  programmatic kernels; agentic verdicts are anchored (object + instruction
  hash) but not model-stable. Use programmatic kernels for deterministic
  gates and treat agentic verdicts as evidence plus (high-stakes → human
  confirmation is in the loop via `needs_human`).

The judgment-model statement (two kernels; no registry, no parameter
allow-lists, no evidence schema ids) is carried from v0.9; see
[docs/architecture-0.9.md](docs/architecture-0.9.md).
