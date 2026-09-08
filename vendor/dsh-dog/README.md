# @dsh-external/dsh-dog

**DAG of Goals (DoG)** — turn a *non-formal* goal ("make a high-quality deck", "write a truly good article") into a DAG of independently verifiable subgoals, and let each subgoal be judged by its **own isolated verifier** before anything counts as done.

> Protocol `schemaVersion` `0.9` · product **v1.2.0 stable** · [Changelog](docs/CHANGELOG.md) · [Spec](SPEC.md) · [Architecture 0.9](docs/architecture-0.9.md)

> **v1.1**: capture roots follow the invoking session cwd (configured `workspaceRoot` is the fallback); verifier/programmatic timeouts 15 min; agentic concurrency reads live settings per-run (no restart); whole-object assertions record their verdict + evidence on the composite; verifier settlement text is preserved in `~/.dsh/dog/settlements/`.

> **v1.2**: dependsOn is a completion gate with real-time wakeup (no dead `blocked` latches); composites run their whole-object assertions concurrently (watermark under the shared agentic budget) instead of a serial loop; `dog_cancel` truly aborts — run-level signal, in-flight verifiers settle `cancelled`, live subagents are interrupted, and a cancellation is never overwritten by a completion record; composite `running` state persists so the UI stays truthful; 41 tests.

---

## The core idea (why DoG)

A goal like "write a genuinely good article" has **no single, formal pass/fail rule** — nobody can run a command that returns "good". Deciding it requires judgment. DoG makes that decidable by structure, not by pretending it is a formula:

1. **Decompose the non-formal goal into subgoals that can each be reviewed.** Each subgoal is still allowed to be *semantic* ("this paragraph has a claim and evidence") — the point is that it can be *reviewed separately*.
2. **Every subgoal gets its own verifier, and the verifier is not the author.**
   - **Agentic kernel** — an isolated subagent with the instruction as its only judgment standard: it reads the object, decides what evidence it needs, gathers it, and answers `{"verdict": "pass|fail|inconclusive", "evidence": …}`. It is context-isolated from the producer, so it cannot inherit the producer's blindspots.
   - **Programmatic kernel** — a host-registered script in the library (`~/.dsh/dog/scripts/`) for the few checks that genuinely are precise rules (file exists, phrase blacklist, count thresholds). Script name may omit the `.js` extension.
   - **A subtree must never be entirely programmatic** — if a whole branch can be decided by rules, it does not belong in a DAG-of-Goals; DoG exists for the judgment parts.
3. **Composition, failure propagation, and the human backstop.**
   - Composites combine children (`all` / `any` / `atLeast` / `not`) and may carry their **own whole-object assertion** — "each dimension passed, but as a whole article it still doesn't hold together" — judged after the subtree settles; the assertion can only *demote*, never promote.
   - Failures propagate upwards until a node that tolerates them (`fatal` / `tolerable` / `degrade`); a `fatal` reaches the root, and **the root is never allowed to fail silently** — it surfaces to a human with the exact failing subgoal and its evidence.
   - Anything the verifier cannot decide honestly settles `needs_human` (never guessed).
4. **Every verdict is evidence-bound; reproducibility is kernel-specific.**
   - `dog_create` captures immutable, content-addressed copies of the target (files; directories are packed into `.tar`), so verification runs against the exact bytes reviewed — not the later live file.
   - Each verdict records the judgment anchor (object digest + instruction hash / script identity), the `verdict`, and its evidence — so *what was decided, and on what basis* is always reconstructable.
   - **Programmatic kernels are deterministic** (same script + same bytes → same verdict). **Agentic kernels are independent judgments, not formulas**: the same instruction against the same object *may* differ across model versions/temperatures. For reproducibility-critical checks use the programmatic kernel, or treat the agentic verdict as advisory and (for high-stakes goals) keep `needs_human`/human review in the loop. DoG *anchors* the judgment — it does not promise model stability.
   - Re-running an unchanged graph (object + judgment anchor identical) reuses prior settlements (`inherited`), so iterations cost tokens only for what actually changed.
5. **True parallelism, real isolation.** Watermark scheduling (a finished verifier immediately frees its slot), programmatic leaves run unqueued, the agentic budget bounds only model-backed work, and each verifier works in its own isolated workspace that stays alive until the run settles.

**What DoG is not**: a todo list, a CI runner, or a checklist of scripted rules. It is the *judgment* layer — the part of "is this done?" that previously had no structure and therefore got done (or skipped) by vibes.

### Known limits (v1.0)

- **Agentic judgments are single-shot** — one isolated verifier subagent per leaf, no re-check, no voting. The evidence schema was deliberately removed in favor of "any JSON", which also removed the basis for structural comparison; the v0.2-deferred "re-check/voting against single-judge blind spots" is **not implemented**.
- **Inheritance anchors, it does not re-verify**: an unchanged agentic leaf reuses its previous verdict — drift in model behavior is invisible until the anchor changes.
- **Where it lands**: anything that must be *deterministically* reproducible belongs in a programmatic script; anything *judgment-based* is best reviewed as evidence plus, for high-stakes goals, human confirmation.

---

## The graph (schemaVersion 0.9)

```jsonc
{
  "schemaVersion": "0.9",
  "id": "article-quality",
  "root": "root",
  "nodes": {
    "root": { "kind": "composite", "constraint": "hard", "target": "article.md",
              "completion": { "op": "all", "items": [ { "op": "ref", "id": "no-slop" } ] },
              "verifier": { "mode": "agentic", "instruction": "Overall assertion…" } },
    "no-slop": { "kind": "leaf", "constraint": "hard", "target": "article.md",
                 "verifier": { "mode": "agentic", "instruction": "Check for AI-slop…" } }
  },
  "contains":  [ { "parent": "root", "child": "no-slop", "required": true, "failure": "fatal" } ],
  "dependsOn": []   // e.g. [ { "source": "b", "target": "a" } ] = b depends on a (a runs first)
}
```

- Two node kinds: **leaf** (one verifier) and **composite** (children combination + optional whole-object assertion).
- Exact field reference and full examples: [`docs/skills/dog-v02-agentic-ci/SKILL.md`](docs/skills/dog-v02-agentic-ci/SKILL.md).
- Ready-to-run demos: [`examples/`](examples/README.md) — `article-quality.graph.json` (four-dimension article gate) and `dog-smoke-multi.graph.json` (3-level tree + mixed agentic/programmatic + dependency edge).

## Quick start

```sh
pnpm install
pnpm run check

# Install the plugin onto the profiles that should expose DoG:
dsh plugin --profile web add "$PWD"
dsh plugin --profile headless add "$PWD"
```

Configure **once, user-level**, in `~/.dsh/settings.yaml` under `dog:` (shared by every profile; agents must never edit it):

```yaml
dog:
  workspaceRoot: /absolute/path/to/your/workspace   # capture source root
  scriptsDirectory: dog/scripts                     # relative to $DSH_HOME, or absolute
  storageDirectory: dog                             # ~/.dsh/dog (graphs, runs, artifacts)
```

> Orphan runs left by a host restart are cancelled automatically at boot; their settled leaves stay inheritable by the next run.

Start the harness and use the model-facing tools — `dog_validate` → `dog_create` → `dog_run` → `dog_wait`/`dog_status`:

```sh
dsh web            # web UI: graph debugger panel + tools
dsh --profile headless "Create a DoG for article.md, run it, then read its status."
```

The **DoG debugger** panel shows immutable graph revisions, run history, containment/dependency edges (arrow = execution order), failure propagation, per-goal runtime traces, and verifier evidence — read-only, never exposing artifact bytes.

## Agentic CI skill

The end-user skill (how-to for agents writing and running graphs) is [`docs/skills/dog-v02-agentic-ci/SKILL.md`](docs/skills/dog-v02-agentic-ci/SKILL.md) — the single source of truth. The per-user copy must be re-synced after every change:

```sh
cp docs/skills/dog-v02-agentic-ci/SKILL.md ~/.dsh/skills/dog-v02-agentic-ci/SKILL.md
```

## Repository layout

- [`src/`](src) — plugin: `graph.ts` (schema/validation), `core.ts` (engine: capture, scheduling, propagation, inheritance), `verifiers.ts` (two kernels), `storage.ts` (content-addressed store), `debug.ts` + `client/` (debugger UI), `tools.ts` (model-facing tools).
- [`schemas/`](schemas/schema-0.2) — JSON schemas (graph/run/verification/runtime-event/report).
- [`docs/`](docs) — `architecture-0.9.md` (normative 0.9 design), `CHANGELOG.md`, `skills/`.
- [`examples/`](examples/README.md) — copy-paste demo graphs.

## License

BSD-3-Clause.
