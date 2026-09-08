# DoG — DAG of Goals

Status: `release-v1.0`

> ## v0.9 delta (owner audited)
> The text below describes v0.2 (historical). v0.9 re-defines the judgment layer:
> - verifier shapes are exactly two: `{mode: "programmatic", script}` or `{mode: "agentic", instruction}`;
> - the contract registry, parameter allow-lists, evidence schema ids, tool allow-lists, grounding extractors, and the programmatic-subtree rule are **removed**;
> - `target` may be a directory (engine packs it into `.tar`); a composite may carry an optional whole-object assertion (same two shapes), judged after the subtree settles;
> - judge output contract: `{"verdict": "pass|fail|inconclusive", "evidence": <any JSON>}`; programmatic scripts live in the host script library.
> See [docs/architecture-0.9.md](docs/architecture-0.9.md) — that doc is normative for 0.9.

This document is the implementation contract for the Agentic CI slice of DeepSeek Harness. DoG is a verification structure, not a development structure: it defines what must be verified, how failures propagate, and how verification runs in parallel isolated workspaces. Development agents are explicitly outside DoG and interact with it only through workspace files (in) and verification reports (out).

## 1. Problem and invariants

DoG represents a non-formal root objective as a directed acyclic graph of goals. A graph contains hierarchical goal membership and explicit cross-goal dependencies. A leaf is complete only when its independently bound verifier settles with evidence; a composite is complete only when its required parent relations and restricted completion expression settle successfully. Verification is agentic by default: leaves whose condition cannot be checked by a deterministic command are verified by an isolated Verifier Agent against a Verifier Contract.

The implementation must preserve these invariants:

1. A graph is acyclic over the union of containment and dependency edges.
2. A node may be shared by multiple composite goals. No algorithm may assume one parent.
3. Failure tolerance belongs to a parent-child relation, not to the shared child. Each incoming relation is evaluated independently.
4. A verifier never accepts a path, command, verifier name, or grounding material selected by the producer of the input or by a model-authored evidence object. Grounding material is extracted by host-registered trusted extractors.
5. Every successful verification is bound to an immutable captured input, a verifier contract version, and a grounding-material digest. A later input version inherits an earlier pass only if a programmatic extractor proves the grounding material and contract are unchanged.
6. The root goal is always a hard constraint. Hard constraints are not compensable by soft-goal scores; an explicitly allowed `partial_success` remains distinct from `success`.
7. Root execution has honest terminal states, including `failure`, `infeasible`, `cancelled`, and `needs_replan`; the engine never fabricates success or waits forever for an impossible goal.
8. Boolean completion expressions are parsed and type-checked into a restricted AST. No `eval`, dynamic import, shell command, or arbitrary expression interpreter is allowed.
9. Human review is a normal terminal/control transition, not an exception hidden inside a retry loop.
10. Runtime context is diagnostic metadata, never verifier evidence. Failure to persist it may emit a bounded warning but cannot convert a failed verification into a pass or a pass into a failure.
11. Every verification execution is assumed impure. No verifier — built-in, registered, or agent-driven — is trusted to be side-effect free. Every verification runs in a mutually exclusive isolated workspace provided by the host; writes are confined to the workspace, and the only result channel is the host-captured verification record.
12. DoG does not own development work. Development agents place files inside the configured workspace root; DoG captures immutable content-addressed bytes and produces machine-readable reports. There is no merge: DoG never merges, never owns a worktree, and never accepts a parent-owned merge, now or later.
13. Incremental verification is decided only by a programmatically extracted grounding-material digest with its verifier contract version. Graph edges are never used to decide revalidation. Verifications declared non-programmatic are never incremental: every fresh artifact export re-runs them unconditionally.
14. A programmatic leaf may exist inside DoG only beside at least one non-programmatic node under the same composite. A composite whose children are all programmatic is itself fully programmatic (deterministic verifiers plus the restricted completion AST) and is rejected at compile time: such a subtree belongs to the existing CI pipeline. Fully programmatic subtrees are never expanded inside DoG; they are represented as a gate on a CI-produced workspace file instead.

## 2. Scope of v0.2

### Implemented in this plugin slice

- Parse and validate a JSON DoG graph, including the non-programmatic-subtree rule.
- Reject fully programmatic subtrees at compile time with guidance to move them to the existing CI pipeline.
- Validate containment/dependency references, duplicate IDs, acyclicity, expression references, and parent-edge semantics.
- Compile a graph into an immutable acceptance plan, including verifier contract binding and grounding extractor binding (unchanged).
- Capture content-addressed bytes of a bounded workspace-relative file.
- Run trusted verifier contracts: deterministic atomic checks and agentic Verifier Agent sessions, both inside mutually exclusive isolated workspaces.
- Extract grounding material programmatically via host-registered extractors and compare digests for incremental revalidation.
- Recompute every affected upstream composite independently for every incoming parent edge.
- Persist graph definitions, execution records, capture manifests, verification records, grounding-material digests, and append-only per-goal runtime events under the active DSH home.
- Preserve the invoking DSH tool-call ID and Agent/session ID on each run when that context exists.
- Expose model-facing tools for graph creation, validation, verification, status inspection, and agent responsibility binding.
- Register and dispose all DSH tool effects through the normal Cordis plugin lifecycle.
- Expose a read-only WebUI graph debugger over the trusted DSH Connection RPC, with a compact snapshot plus lazy per-goal runtime traces and canonical session navigation.

### Relationship to existing CI

DoG is the agentic layer on top of an existing CI pipeline, not a replacement. Existing CI carries fully programmatic verification (build, unit tests, format, lint, package-content checks). DoG carries the non-programmatic goals and gates on CI results through captured files: a programmatic leaf inside DoG either (a) checks a CI-produced fifact (e.g. `ci-report.json`) with a deterministic verifier while sharing its composite with agentic leaves, or (b) is not present in the graph at all because its whole subtree is programmatic. DoG never re-runs a pipeline that already exists.

### Out of scope; explicitly not DoG, not deferred

- Agent/session execution of development work. DoG never executes goal work; development is performed by independent agents outside DoG.
- Git worktree creation, parent-owned semantic merge, and any merge policy. DoG merges nothing and never will. Isolated verification workspaces are execution environments, not merge targets.
- Development-side parallel decomposition. It is a separate subsystem to be designed later; it will not use the DoG structure.

### Deferred; must not be faked by v0.2

- Parallel verification scheduler details (pool allocation, reuse, backpressure) beyond the isolation contract; v0.2 may run verification sequentially while keeping per-run workspace isolation.
- Event-triggered runs (watch mode: artifact commit or file change triggers `dog_run`).
- Machine-readable CI report export beyond the bounded `dog_status` response.
- Grounding extractor library breadth (renderers, XML/geometry, AST/token extractors are host-registered trusted implementations; v0.2 ships the file-content extractor).
- Verification Agent re-check / voting strategies (N independent verifications of the same goal to guard against single-point misjudgement).
- Dynamic graph planning and recursive graph construction.
- Mutating WebUI controls and streaming event transport.
- Arbitrary user-defined verifier code or shell commands.
- External shared stores and distributed workers.
- Automatic retries and degradation execution policies.

The deferred features may consume the v0.2 persisted records later, but cannot weaken their trust or version rules.

## 3. Core vocabulary

- **Goal**: a node whose desired condition is represented by a verifier and/or a composition of child outcomes.
- **Leaf goal**: a goal with no containment children. In v0.2 it must have a verifier contract binding (deterministic atomic check, agentic Verifier Agent, or a host-embedded combination).
- **Composite goal**: a goal with one or more containment children and a completion rule. v0.2 evaluates that rule only and rejects composite verifier fields rather than silently ignoring them.
- **Containment edge**: `parent contains child`; it contributes the child's outcome to the parent's completion rule.
- **Dependency edge**: `source depends_on target`; target must have settled before source is scheduled. It is a verification gate, never a development scheduling edge, and never participates in incremental revalidation.
- **Parent relation**: the semantic object formed by one containment edge. It owns tolerance, requiredness, and degradation policy for that particular parent-child use. It owns no merge policy: merge does not exist.
- **Verifier contract**: an immutable, versioned binding of a verification task to its requirement (natural-language check instructions), evidence schema, allowed tool set, and grounding declaration. It is authored by the graph/planner, never by the artifact producer.
- **Verifier Agent**: a context-isolated DSH session that executes one Verifier Contract inside an isolated workspace. It receives the contract and the captured input read-only; it produces a settlement plus evidence satisfying the evidence schema. Its context never contains the development agent's reasoning, prompts, or process.
- **Grounding material (GM)**: the minimal set of material such that, given it alone and the contract requirement, the goal can be judged. Declared as `programmatic` with a host-registered extractor (a deterministic function from the captured input to normalized GM) or as `non_programmatic`.
- **Grounding-material digest (`gmDigest`)**: a content-addressed hash of the normalized GM. It is the only key used for incremental revalidation.
- **Isolated workspace**: a mutually exclusive, host-allocated execution environment for one verification: the captured input is read-only input, the workspace is the only writable area, and the outside world is inaccessible. Workspaces are never shared, never merged, and their contents are discarded on completion.
- **Acceptance plan**: a system-compiled, immutable binding of a goal to a verifier contract version, target captured input (or the whole workspace), fixed parameters, grounding extractor, and evidence schema.
- **Captured input**: an immutable, content-addressed byte representation of the exact workspace-relative file inspected by a verifier (absent when the goal validates the whole run workspace).
- **Evidence**: verifier-produced observations satisfying the contract's evidence schema. Evidence is descriptive output, never authorization to choose what gets verified.
- **Affected upstream**: every composite reachable through reverse containment or dependency edges from a changed node; recomputation follows all paths, not one selected parent.

## 4. Graph representation

The external representation is JSON-compatible YAML if a future authoring layer wants YAML. v0.2 tools accept JSON values; no JavaScript is evaluated while parsing a graph.

```json
{
  "schemaVersion": "0.2",
  "id": "ppt-quality",
  "root": "root",
  "nodes": {
    "root": {
      "kind": "composite",
      "title": "Deliver an acceptable deck",
      "constraint": "hard",
      "completion": { "op": "all", "items": [
        { "op": "ref", "id": "file" },
        { "op": "ref", "id": "readable" },
        { "op": "ref", "id": "page3-fig2-overlap" }
      ] }
    },
    "file": {
      "kind": "leaf",
      "title": "The deck exists",
      "constraint": "hard",
      "verifier": { "id": "file.exists", "version": "1" },
      "verifierParams": { "path": "deck.pptx" }
    },
    "readable": {
      "kind": "leaf",
      "title": "The deck is readable",
      "constraint": "soft",
      "verifier": { "id": "file.non_empty", "version": "1" },
      "verifierParams": { "path": "deck.pptx" }
    },
    "page3-fig2-overlap": {
      "kind": "leaf",
      "title": "Page 3 figure 2 has no text occlusion",
      "constraint": "hard",
      "verifier": { "id": "vision.overlap", "version": "1" },
      "verifierParams": {
        "path": "deck.pptx",
        "target": "Page 3, figure 2",
        "requirement": "Detect text blocks overlapping to illegibility inside the figure"
      }
    }
  },
  "contains": [
    { "parent": "root", "child": "file", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "readable", "required": true, "failure": "tolerable" },
    { "parent": "root", "child": "page3-fig2-overlap", "required": true, "failure": "fatal" }
  ],
  "dependsOn": []
}
```

### Node fields

- `kind`: `leaf` or `composite`.
- `title`: non-empty human-readable goal statement.
- `constraint`: `hard` or `soft`. The root must be `hard`; v0.2 records non-root softness but does not invent a soft-score model.
- `completion`: restricted AST, required for composites with children.
- `verifier`: a Verifier Contract identifier and version only. It is not a module path, command, or model-supplied function.
- `verifierParams`: declarative parameters checked by the contract registry for the selected contract. Parameters are copied into the acceptance plan before execution. The graph may refer to a workspace-relative `path` (permitted only inside the workspace root) and may supply task-specific targets/requirements, but may not select a filesystem root, path, command, tool set, or verifier implementation.

A leaf cannot declare a completion expression. A composite cannot be evaluated as complete while a required dependency is unresolved. Unknown fields are rejected in strict mode to prevent hidden execution directives.

### Programmatic-subtree rule (compile-time)

A node is *programmatic* when its settlement is fully computable: a leaf whose verifier contract is deterministic (non-agentic), or a composite whose children are all programmatic (deterministic verifiers plus the restricted completion AST). DoG graphs must be *agentic at every composite*:

- a programmatic leaf is allowed only if its composite has at least one sibling that is non-programmatic;
- a composite whose children are all programmatic is itself programmatic and compilation **rejects** it, with guidance: move this subtree to the existing CI pipeline and, if DoG must gate on it, gate on a CI-produced file (e.g. `ci-report.json`) as a programmatic leaf beside an agentic sibling.

The rejection happens before any capture or run: the rule is static, and it is decided from the graph plus the contract registry, never from runtime results.

### Parent-relation fields

- `required`: whether this child reference participates in the parent's required completion contract.
- `failure`: `fatal`, `tolerable`, or `degrade`. This is interpreted only by this parent relation.
- `degradeTo`: optional approved node ID used when `failure=degrade`; it must be a sibling relation explicitly present in the graph.

There is no `merge` field. A graph that contains `merge` is rejected: merge is not part of DoG and never will be.

A shared child can therefore be fatal for one parent and tolerable for another. The child itself has no global `tolerable` flag.

Degradation applies only after the direct child settles as a failure. It never converts `needs_human` or another unresolved state into success merely because the fallback passed. If several required relations fail, any `fatal` relation dominates tolerable failures regardless of edge order. A degradation target cannot be the failed child itself.

### Dependency fields

- `source` cannot be scheduled before `target` reaches a terminal outcome allowed by the source's policy. This is a verification gate only; it does not constrain development agents and does not participate in incremental revalidation.
- `data`: optional list of named output fields to bind in a later version. v0.2 records the relation but does not execute arbitrary data expressions.
- Dependencies must not create a cycle with containment edges.

## 5. Restricted completion AST

The only legal completion operators are:

```json
{ "op": "ref", "id": "child-id" }
{ "op": "all", "items": [ /* boolean expressions */ ] }
{ "op": "any", "items": [ /* boolean expressions */ ] }
{ "op": "not", "item": /* boolean expression */ }
{ "op": "atLeast", "count": 2, "items": [ /* boolean expressions */ ] }
```

The parser enforces:

- no extra keys;
- non-empty `items` for `all`, `any`, and `atLeast`;
- integer `count` in `[1, items.length]`;
- every `ref` resolves to a containment child of the current composite;
- every expression evaluates to a boolean;
- bounded nesting and total node count from plugin configuration;
- no strings representing code, shell, paths, or JavaScript expressions.

The evaluator receives a map of already-computed child booleans. It never receives source text and never invokes an interpreter.

## 6. Acceptance and evidence trust boundary

### 6.1 Compilation

Before execution, the system/compiler—not the producer—creates an acceptance plan for every leaf:

```json
{
  "goalId": "page3-fig2-overlap",
  "verifierId": "vision.overlap",
  "verifierVersion": "1",
  
  "params": { "path": "deck.pptx", "target": "Page 3, figure 2", "requirement": "..." },
  "grounding": { "kind": "programmatic", "extractorId": "slides.page3.render", "schema": "slides.page3.render/v1" },
  "evidenceSchemaId": "vision.overlap/v1",
  "gmDigest": "sha256:..."
}
```

The workspace root, not the graph producer, anchors every `path`; the plan carries the captured input metadata. The plan is deep-frozen in memory and persisted with those fields and an explicit file scope. The system resolves the relative path, canonicalizes it, and checks it against the approved root before any capture. A path supplied in a child output or evidence object is ignored and cannot override the plan.

The grounding declaration is part of the Verifier Contract and cannot be overridden by `verifierParams` or by any model-authored object. A contract declared `non_programmatic` has no extractor and is always revalidated.

### 6.2 Snapshot lifecycle

1. The system resolves the host-bound artifact ID to its configured root and relative path.
2. It reads the bytes itself and computes a SHA-256 digest.
3. It writes or reuses immutable content-addressed bytes.
4. It runs the registered grounding extractor against those bytes and computes the GM digest.
5. The verifier reads only the captured bytes (read-only), the fixed plan parameters, and its isolated workspace.
6. The verification record stores the capture digest, verifier contract version, and GM digest.

If the live file changes after capture, the record remains valid for the old bytes but cannot be used to claim the new version passed. A new run must compile a new plan.

### 6.3 Evidence rules

- Evidence is generated by the trusted verifier implementation (deterministic check) or by the Verifier Agent under the contract's evidence schema.
- Evidence cannot select `verifierId`, path, command, extractor, or GM.
- A Verifier Agent's bare assertion is never sufficient. A settlement is one of:
  - `pass`: the agent produced evidence satisfying the evidence schema and the requirement;
  - `fail`: the agent produced evidence showing the defect;
  - `inconclusive`: no valid evidence could be produced, or the agent's confidence is below threshold. `inconclusive` is neither pass nor fail; it enters `needs_human` (or a deferred re-check policy).
- A pass requires a contract-specific result with a non-empty, schema-valid observation and the exact capture digest.
- A generic `{ "passed": true }` object is never sufficient.
- A verifier that does not inspect the captured input or cannot produce its declared observation fails closed.
- Verification records are append-only; a later record supersedes an earlier record only when it names a different run and capture digest. A record may be reused (inherited) only when the GM digest and contract version of the current plan match the record's.

Future custom verifiers require explicit registry installation and trusted code review. A graph cannot register one by naming a file, package, URL, or command.

## 7. Verifier Contract registry

Each registry entry declares:

```ts
interface VerifierContract {
  id: string
  version: string
  requirement: string              // natural-language check instructions
  paramsSchema: DeclarativeSchema  // workspace path + task-specific targets/requirements
  evidenceSchemaId: string
  allowedTools: readonly string[]  // host-registered tool IDs (render, OCR, geometry, ...)
  grounding: { kind: "programmatic", extractorId: string, schema: string }
           | { kind: "non_programmatic" }
  execute(workspace: IsolatedWorkspace, input: CapturedInput | undefined, params: unknown, agent?: VerifierAgent): Promise<Settlement>
}
```

The registry owns parameter validation, target selection, and evidence construction. Two execution kinds exist:

- **Deterministic atomic checks** (`file.exists/v1`, `file.non_empty/v1`, `file.sha256/v1`, `text.includes/v1`): trusted library functions run by the host inside the isolated workspace. They are the *programmatic* category. They may also be used by a Verifier Agent as tools, and may appear as DoG leaves only under the programmatic-subtree rule (§4): their composite must contain at least one non-programmatic sibling.
- **Agentic contracts** (`vision.overlap/v1` and similar): executed by a context-isolated Verifier Agent that receives the contract, the read-only captured input, and the allowed tool set inside an isolated workspace. They are the *non-programmatic* category. The agent cannot modify the requirement, evidence schema, tool set, extractor, or its own task.

Grounding extractors are host-registered trusted implementations, never graph-supplied. The v0.2 bundled extractor is file-content (`file.content/v1`: normalized bytes of the captured input). PPT rendering/geometry and code AST/token extractors are host-registered work items.

Isolation is mandatory for every entry. No verifier contract may declare itself side-effect free; workspaces are allocated per verification, and access outside the workspace fails closed.

## 8. Status and terminal semantics

### Node states

`pending`, `running`, `success`, `failure`, `blocked`, `needs_human`, `cancelled`, `invalidated`, `partial`, `inherited`.

`inherited` is a success-equivalent result reused from a prior run only when the current plan's GM digest and contract version match the prior verification record.

A successful leaf verification record carries the run ID, graph digest, capture digest, verifier contract version, GM digest, and bounded observation. Composite results carry their state and reason.

### Runtime context

Every run may carry an invocation record containing the `dog_run` tool-call ID, the invoking DSH Agent/session ID when one exists, its direct parent session ID when the invocation came from a subagent, and its timestamp. Each evaluated goal writes a bounded append-only event sequence: goal start, dependency block, verifier start/pass/fail, grounding extraction, isolated workspace allocation, composite evaluation, structured runtime error, and final settlement. Events include only operational identifiers, state, bounded reasons/errors, verifier identity, attempt number, and duration. They do not copy prompts, assistant reasoning, raw tool transcripts, artifact bytes, credentials, or verifier observations.

The debugger loads this trace only after a user selects a run and goal. A running node is therefore distinguishable from a merely pending node, and a failed node exposes the exact runtime stage and structured error category. If an invoking Agent/session ID is still known to the DSH runtime, the UI navigates through the canonical session service so the user can inspect that session's normal conversation and tool history. Ordinary sessions must still be present in the canonical session list; addressed subagents require their recorded direct parent to refresh into a healthy catalog route. The debugger closes only after the canonical session selection reports the target as current; unavailable or unconfirmed targets leave it open with an explicit error.

Runtime-event persistence is explicitly outside the acceptance boundary: trusted evidence remains the immutable `VerificationRecord` generated by the verifier contract execution. A runtime log write failure is recorded as a bounded run warning and does not alter the verification verdict.

### Root terminal states

- `success`: the restricted root completion expression is true and every required parent relation succeeds directly or through its declared degradation target.
- `partial_success`: the root is `partial` and deployment explicitly sets `allowPartialRoot`; v0.2 has no independent soft-score threshold.
- `failure`: a non-tolerable required relation fails, the root completion expression settles false under fatal policy, or partial root delivery is disabled.
- `infeasible`: the declared conditions cannot be met under available artifacts or capabilities.
- `needs_replan`: the verification contract must change (requirement, evidence schema, grounding extractor, or graph) before verification can continue. This is a contract adjustment signal, not a development-plan rework signal.
- `cancelled`: human or policy ended execution; partial records remain inspectable.

`needs_human` is an active control state, not a root success/failure claim. Human decisions may retry, edit the graph, approve a degradation allowed by the graph, or terminate. No decision is represented as an automatic pass.

## 9. Parallel scheduling, incremental revalidation, and propagation

### 9.1 Isolation and parallel scheduling

Every verification owns one mutually exclusive isolated workspace. No side-effect-free assumption is made about any verifier; a verifier may create temporary files, build caches, or render inputs — all confined to its workspace. Parallelism is therefore safe by construction: read sets are immutable captured bytes; write sets are per-workspace; nothing is shared, and nothing is merged.

### 9.1.1 Verifier worker lifecycle

An agentic verifier worker is a continuable child session bound to its goal. Its lifecycle is supervised:

- the child is created with a tool filter that denies shell execution (`bash`), so it cannot inspect or mutate the host project outside its workspace;
- its prompt declares the artifact path as the only read target, the settlement file path as the only write target, and forbids any tool call after the settlement file is written;
- as soon as the runner observes the settlement file, it interrupts the child's current turn and records a `verifier_released` lifecycle event; an interrupt failure is a bounded run warning, never a verdict change;
- a binding failure (see §12) records `verifier_bind_failed` and a bounded run warning instead of failing the verification.

### 9.1.2 Run supervision

- every running run writes a heartbeat (`updatedAt`) at a bounded interval;
- a run whose heartbeat is older than the orphan threshold is reaped on the next engine start or `dog_run`: it becomes `cancelled` with `rootState: cancelled` and the warning `orphaned: heartbeat expired (host restart or session loss)`;
- a new run supersedes any prior non-terminal run of the same graph.

The scheduler maintains readiness by dependency gates. Each ready verification claims a workspace from the pool (pool size ≤ `maxConcurrentVerifications`) and executes. A failure propagates as a result settlement; it never cancels unrelated ready nodes. Verification continues until every non-gated node has settled, maximizing the evidence collected in a run.

### 9.2 Incremental revalidation

Before scheduling a fresh run, the host:

1. runs the registered grounding extractor for every programmatic leaf against the new capture;
2. computes each GM digest;
3. for leaves whose GM digest and verifier contract version equal the prior run's record, marks the prior result `inherited` (success or failure both carry over; they are facts, not re-verifications);
4. leaves whose GM changed, and all `non_programmatic` leaves, are re-run unconditionally.

Graph edges never decide revalidation. A change to an artifact that alters no leaf's GM causes no re-run for that leaf, even though its containing composite still evaluates.

If the number of re-run leaves exceeds `revalidateThreshold` (as a configured ratio of leaves; `0` disables), the report includes an explicit warning to the development agent that the submission touched unrelated parts (e.g. a global template change re-triggering every page of a deck).

### 9.3 Propagation

A node result is immutable and may feed multiple parents. After any result changes, the engine:

1. finds every reverse containment and dependency edge reachable from the changed node;
2. evaluates each incoming parent relation with its own `required`, `failure`, and degradation policy;
3. recomputes each affected composite's completion AST from the current child-result map;
4. applies the composite's own independent verifier/policy, if any;
5. continues until a fixed point or a human/terminal boundary;
6. recomputes the root from all affected paths.

There is no single `getParent()` operation. Failure settlement and scheduling are decoupled: propagation is about results; scheduling is about maximizing completed verification.

## 10. Lifecycle

The full DoG lifecycle is below. In v0.2, coverage review and human review are external control points; the plugin compiles, selects, verifies, recomputes, and reports rather than pretending to run an autonomous reviewer.

1. `draft`: the human project owner states the non-formal objective and acceptance criteria. A planning agent (orchestrator) decomposes that into a graph of verification goals; it does not develop, does not verify, and does not run CI. The graph is durable: it changes only when the human owner's objective changes.
2. `coverage_review`: an independent, context-isolated reviewer checks that the root objective, hard constraints, required artifacts, and obvious failure modes are represented. It may reject the draft; it cannot silently add goals.
3. `confirm`: the human owner accepts the reviewed graph. From this point the graph is a fixed verification standard; the developer cannot modify it, and CI cannot redefine it.
4. `compile`: validate graph, resolve trusted Verifier Contract IDs, capture workspace-relative files, bind grounding extractors, and assign a graph revision.
5. `capture`: consume the developer's submitted file as immutable content-addressed bytes at the DoG work boundary — the only input channel from the development side.
6. `revalidate_select`: extract grounding material, compare GM digests, and partition leaves into re-run set and inherited set.
7. `verify`: schedule verifier contracts (deterministic or agentic) in isolated workspaces, bounded by the concurrency limit.
8. `recompute`: propagate results along every affected upstream path.
9. `human_review`: pause on root hard failure, uncertainty (`inconclusive`), coverage rejection, budget anomaly, or policy-required review.
10. `report`: package the terminal state, evidence summaries, inherited results, and threshold warnings into a machine-readable report for the development agent or external CI.
11. `terminal`: persist an honest root terminal state and report evidence.

The developer's tool surface is limited to `dog_run` and `dog_status`. It has no `dog_create`/`dog_validate`: whoever may edit the graph defines what counts as passing, so graph authors must never be input producers.

Coverage review and Verifier Agents use context-isolated sessions. The isolated reviewer receives the original objective, the candidate graph, and explicit review rules—not the producer's private reasoning or self-authored test instructions. The Verifier Agent receives only the contract and the immutable capture—never the development agent's reasoning.

Development agents are not scheduled by DoG. They consume reports (e.g. via `dog_bind_agent` responsibility/subscription binding) and submit new files; failure notification is a report, not a command.

## 11. Persistence

By default the plugin stores under `$DSH_HOME/dog/` (the directory name is configurable):

- `graphs/<graph-digest>.json`: immutable compiled graph revisions and acceptance plans;
- `graph-index/<host-safe-graph-key>.json`: latest-revision lookup for a graph ID; the indexed digest must be a lower-case SHA-256 value before it is used as a filename;
- `runs/<host-safe-run-key>.json`: execution state, terminal result, and per-leaf GM digests;
- `artifacts/<digest-key>.bin|json`: immutable captured bytes and manifest;
- `verifications/<host-safe-run-key>.jsonl`: append-only trusted verifier results (capture digest + contract version + GM digest);
- `runtime-events/<run-key>-<goal-key>.jsonl`: append-only diagnostic activity and structured errors, sharded per goal so lazy inspection never scans another goal's events.

Writes use temporary files plus atomic rename for captures and append-only records for event streams. Records contain schema versions and never contain credentials, prompts, raw transcripts, or captured bytes outside the content-addressed store. A status read returns metadata and bounded error/evidence fields; it does not dump arbitrary session context.

Every exchange payload in this spec (graph input, run record, verification record, runtime event, CI report) has a machine-readable JSON Schema declared under `schemas/schema-0.2/*.schema.json` (draft 2020-12). These are the normative shapes: any payload that does not validate against its declared schema is rejected before it is parsed or persisted. Runtime date-time fields use the standard `format: "date-time"` and require format-aware validators (e.g. ajv-formats); structure validation is format-independent. Graph-level semantic rules that JSON Schema cannot express (reference resolution, acyclicity, programmatic-subtree rejection, verifier contract existence) remain compiler-enforced per §4.

## 12. DSH plugin surface in v0.2

Package: `@dsh-external/dsh-dog`.

The host plugin registers these model-facing tools through `ctx.tools`:

- `dog_validate`: parse and statically validate a graph without writing it.
- `dog_create`: validate, compile, resolve only workspace-relative paths, capture those files, bind grounding extractors, and persist a graph revision.
- `dog_run`: start the Agentic CI cycle for one graph and return **immediately** with the initial `running` record. The cycle (revalidate-select, parallel verification in isolated workspaces, recompute) executes in the background on the engine's process-level queue with its own abort signal; caller session stop or tool abort does not cancel it. The report is obtained by polling `dog_status`.
- `dog_status`: return a bounded graph/run status and verification evidence as a CI-consumable report.
- `dog_wait`: poll one run **instantly** (never blocks, therefore can never be interrupted by host input injection). Automation calls it repeatedly until the returned state is terminal; every poll keeps the calling session and process alive, which is what keeps the verifier workers this run spawned from being released.
- `dog_cancel`: mark a running run and its verifier workers cancelled with a bounded reason; partial records remain inspectable.
- `dog_bind_agent`: bind a DSH Agent session's responsibility/subscription to one goal in an existing DoG run (notification on failure; never scheduling of execution).
- `dog_delegate_agent`: start a durable continuable DSH Agent bound to one goal; the child remains directly interactive after its first turn. The role is orchestrator, verifier, or reviewer.

All tool arguments cross a model boundary and are validated. Model-authored graphs may reference only workspace-relative `path` values inside the configured workspace root; they cannot supply roots, absolute paths, commands, tool sets, or verifier implementations. The tools do not spawn shell commands.

Verifier binding semantics: a verifier worker is bound to its goal as role `verifier`. A binding failure is recorded as `verifier_bind_failed` plus a bounded run warning; it never blocks the verification verdict, and the run remains inspectable without the worker link.

The plugin exports `name`, `Config`, `inject`, and `apply` according to the DSH loader contract. `apply` registers effects with disposers and fails loudly for invalid configuration or missing required services.

The web profile registers a client bundle in the shipped `shell.overlay` slot and a trusted-host channel on the shared DSH Connection RPC. The compact `snapshot` endpoint returns a schema-validated projection of persisted graph revisions and runs; the lazy `goal-runtime` endpoint returns one bounded per-goal trace only after node selection. Neither endpoint returns captured bytes, prompts, raw session transcripts, or credentials. The client polls the compact snapshot, renders containment and dependency edges, exposes node contracts, live runtime activity, structured failure reasons, and trusted verifier evidence, and can ask the canonical DSH sessions service to open the invoking session. It is intentionally read-only: graph mutation and execution remain model/CLI-side.

## 13. Configuration

The initial deployment configuration is declarative:

```yaml workspaceRoot: /approved/workspace   # verifier inputs are confined to this tree
storageDirectory: "dog"   # relative to DSH_HOME
maxGraphNodes: 256
maxExpressionNodes: 512
maxExpressionDepth: 64
maxSandboxBytes: 67108864
allowPartialRoot: false
maxConcurrentVerifications: 1   # isolated workspace pool size; >1 enables parallel scheduling
revalidateThreshold: 0.3        # ratio of leaves re-run before warning the developer; 0 disables
gmDigestAlgo: "sha256"
subagentProvider: "spawn"       # provider that establishes verifier/delegate child sessions
subagentMaxDepth: 3             # delegation-depth cap for those children
```

`workspaceRoot` is host-authored configuration, validated at plugin load, and is the only source of target paths. No model-authored graph can override it with absolute or escaping paths. A future permission integration may add user approval for new roots; v0.2 rejects them.

In the running DSH installation this configuration is supplied by the user-level settings namespace `dog:` (`~/.dsh/settings.yaml`), shared by every profile that loads the plugin; profile patches never carry `dsh-dog` configuration. The plugin remains operable when no settings service is attached, falling back to its composition entry defaults.

## 14. Security and failure policy

- Reject traversal, absolute paths outside approved roots, symlink escapes, duplicate IDs or dependency edges, cycles, self-degradation, unknown verifier IDs, malformed schemas, oversized captures, fully programmatic subtrees, and any `merge` field.
- Never use `eval`, `new Function`, dynamic imports from graph data, or shell interpolation.
- Isolated workspaces are mandatory for every verification; out-of-workspace access fails closed.
- Redact credentials from errors and persisted evidence.
- Treat all model-authored graph fields, executor output, and evidence as untrusted data.
- On storage or capture mismatch, fail closed and require a new run.
- On a cost or timeout anomaly, enter `needs_human`; do not silently lower verification standards.
- A Verifier Agent may not be granted tools outside the contract's `allowedTools`; tool grants are host-registered, not model-supplied.

## 15. Explicitly deferred design decisions

The following remain open until a benchmark or real DSH integration supplies evidence:

- scheduler policy details (workspace pool sizing, allocation and reuse);
- event-triggered watch mode;
- CI report export format beyond the bounded status response;
- grounding extractor library breadth (renderers, XML/geometry, code AST);
- Verifier Agent re-check / voting calibration against hallucinated evidence;
- mutating WebUI controls, streaming transport, and very-large-graph virtualization;
- dynamic planning and graph migration;
- GitHub template repository format.

Development-side parallel decomposition is explicitly NOT DoG and will not appear here.

## 16. Worked example: deck quality gate

Task: produce `deck.pptx` for a 10-page demo. Acceptance stated by the human owner: every page readable, no text occlusion, no truncation, information complete.

### 16.1 Roles and ownership

| Role | Side | Input | Output |
|---|---|---|---|
| Human project owner | outside | — | non-formal objective + acceptance criteria |
| Planning agent (orchestrator) | CI side, once | objective + material + contract catalog | graph JSON (via `dog_create`) |
| Coverage reviewer | CI side, once | objective + graph + review rules (isolated) | approve / reject |
| Development agent | outside | objective, CI reports | file at the workspace path; `dog_run` / `dog_status` calls |
| Verifier Agent | CI side, per run | contract + captured input (isolated, allowed tools only) | pass / fail / inconclusive + evidence |
| DoG runner (host) | CI side | captured input | run records + machine-readable report |

The developer cannot build or edit the graph: its tool surface is `dog_run` + `dog_status` only.

### 16.2 Sequence

1. `draft`: owner states the objective; planning agent decomposes it. Leaves include `renderable` (deterministic `render.probe`, GM = rendered bytes of all pages), `page3-fig2-overlap` (agentic `vision.overlap`, GM = page-3 layout boxes + screenshot), `page7-truncation` (agentic `vision.truncation`, GM = page-7 render), `brand-consistency` (agentic `vision.brand`, declared `non_programmatic`). `page3-fig2-overlap` and `page7-truncation` depend on `renderable` (verification gate). Compilation is legal because every composite (root, page composites) has at least one non-programmatic child: `renderable` is programmatic but coexists with agentic siblings under the same parent. The conventional programmatic checks (unit tests, lint, bundle size) are not in the graph: they run in the existing CI pipeline and are gated by a programmatic leaf on a CI-produced file beside the agentic leaves.
2. `coverage_review` → approved; `confirm` → owner accepts; `compile` → `dog_create` fixes the contract set and the input scope.
3. Developer places `deck.pptx` inside the workspace root and calls `dog_run` (both required to trigger CI).
4. `capture` takes immutable bytes; `revalidate_select` finds no history in run 1 → all leaves re-run; `brand-consistency` always re-runs.
5. `verify`: `renderable` runs first in an isolated workspace; once it settles, the gated leaf Verifier Agents run in parallel, each in its own workspace, each receiving only the contract and the read-only captured input.
6. Run 1 result: `renderable` pass, `page7-truncation` pass, `page3-fig2-overlap` fail (evidence: title box intersects figure 2 by 14%, OCR confirms covered text), `brand-consistency` inconclusive → `needs_human`. Failure settles upstream (`page3`, then `root`) while unrelated leaves keep running — failure settlement never cancels scheduling of unrelated nodes.
7. `report` returns `dog_run` summary (`runId`, `rootState: failure`, failed/inconclusive lists) and `dog_status` full evidence (screenshot reference, geometry, OCR text) to the developer.
8. Developer fixes only page 3, re-submits, calls `dog_run`. Run 2 `revalidate_select` recomputes GM: only `page3-*` changed → others `inherited` (zero Verifier Agent cost), `page3-fig2-overlap` re-runs and passes → `rootState: success`.
9. Alternative scenario: the developer changes the global theme to fix page 3 — every page GM changes, 20/20 re-run exceeds `revalidateThreshold`, and the report warns: "this submission re-runs all pages; revert the template change if the fix is page-3-only."
10. Objective change later → the owner and planning agent re-draft a new graph; the old revision is a fixed historical standard and its records keep their meaning.

Changes to this document must be committed separately from implementation changes when possible. The commit history is the record of which parts of the design changed because the implementation exposed an unrealistic assumption.

## 17. Runtime semantics (v0.2 deltas from real operations)

Implementation-verified behavior not visible in the earlier sections, recorded so the contract and code stop drifting:

- **Heartbeat is liveness-only.** The engine heartbeat updates only `updatedAt` under the repository mutation lock. It never rewrites goals/records from the in-memory copy: host-written artifacts (`bindAgent` session records, run annotations) must not be overwritten by a save that never saw them.
- **Orphan recovery, not cancellation.** On startup the engine resumes runs whose heartbeat expired rather than cancelling them: terminal leaves are kept, interrupted leaves are rescheduled, and the invoker is re-resolved through the live Agent registry. A run whose invoker is no longer live settles agentic leaves as `needs_human` and records an explicit `runtimeWarning` naming the cause (one-shot host processes release their verifier workers).
- **`revalidateThreshold` counts inherited-eligible leaves only.** Agentic leaves always re-run by design; they are excluded from the re-trigger ratio so a graph that mixes one inherited programmatic leaf with agentic leaves does not warn on every submission.
- **`bindAgent` accepts an unrooted policy** for verifier workers spawned from a recovered run (no live parent SessionId): the worker is still registered to its goal so the UI can show "related agents" while the parent-authority check applies to human-provided bindings.
- **Verifier workers are released quietly.** After settlement the runner uses the official quiet release (`drainContinuableChildren`) rather than an interrupting stop; interrupting a settled-but-released child emits parent notices that interrupt a parent turn blocked in a long tool.
- **Verifier evidence uses a fixed skeleton** (`inspected`, `required_elements`, `geometry`, `overlap_evidence`, `conclusion`) so cross-run observations are comparable and the front end can render them structurally.
- **Storage is cross-process safe.** Repository mutations take a short per-record file lock (pid+timestamp, stale-expiry) so two engine instances (e.g. a resident web process and a one-shot headless process) sharing one `$DSH_HOME/dog/` cannot interleave read-modify-write cycles. Orchestration still recommends a single resident engine for production.
