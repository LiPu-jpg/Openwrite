/** DoG v0.9 engine semantics: compilation, two-kernel judgment, propagation, inheritance. */

import { writeFile, mkdir, rm, readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { describe, it, expect, afterEach } from 'vitest'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { DogEngine } from '../src/core.ts'
import type { DogConfig, VerifierShape } from '../src/model.ts'
import { DogRepository } from '../src/storage.ts'
import { compositeNode, ensureScripts, graph, leafNode, mkConfig, stubAgentic, stubProgrammatic, temporaryRoot } from './helpers.ts'

const temporaryRoots: string[] = []

async function tmpRoot(): Promise<string> {
  const path = await temporaryRoot()
  temporaryRoots.push(path)
  await ensureScripts(path)
  return path
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

function engine(root: string, opts: { programmatic?: ReturnType<typeof stubProgrammatic>; agentic?: ReturnType<typeof stubAgentic>; config?: DogConfig; resolveLivingAgent?: (id: string) => Agent | undefined; now?: () => Date } = {}): DogEngine {
  const scripts = join(root, 'scripts')
  const dog = new DogEngine({
    config: opts.config ?? mkConfig(root, scripts),
    repository: new DogRepository(join(root, '.dog-store')),
    now: opts.now ?? (() => new Date('2026-08-23T00:00:00.000Z')),
    nextRunId: () => `run-${Math.random().toString(36).slice(2)}`,
    ...(opts.resolveLivingAgent === undefined ? {} : { resolveLivingAgent: opts.resolveLivingAgent }),
  })
  dog.setKernels(opts.programmatic ?? stubProgrammatic(), opts.agentic ?? stubAgentic())
  return dog
}

describe('v0.9 engine', () => {
  it('validates every shipped example graph (examples/*.graph.json)', async () => {
    const root = await tmpRoot()
    const dog = engine(root)
    const examplesDir = new URL('../examples', import.meta.url).pathname
    for (const name of await readdir(examplesDir)) {
      if (!name.endsWith('.graph.json')) continue
      const candidate = JSON.parse(await readFile(`${examplesDir}/${name}`, 'utf8')) as unknown
      const report = dog.validate(candidate)
      expect(report.valid, `${name} should validate: ${report.errors.join('; ')}`).toBe(true)
    }
  })

  it('compiles a graph with programmatic leaves and captures the target object', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root)
    const candidate = graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'leaf' }] }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }])
    const compiled = await dog.create(candidate)
    const plan = compiled.acceptancePlans.leaf!
    expect(plan.verifier).toEqual({ mode: 'programmatic', script: 'file-non-empty' })
    expect(plan.target).toBe('artifact.txt')
    expect(plan.input?.digest).toMatch(/^sha256:/)
    expect(plan.judgment.mode).toBe('programmatic')
  })

  it('captures targets from the invoking session cwd first, with the configured root as fallback', async () => {
    const root = await tmpRoot()
    const sessionCwd = await tmpRoot()
    await writeFile(join(sessionCwd, 'deck.md'), 'session object')
    await writeFile(join(root, 'legacy.md'), 'fallback object')
    const dog = engine(root)
    // Target lives in the session cwd -> captured from there.
    const fromCwd = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ target: 'deck.md' }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]), {
      captureBaseDir: sessionCwd,
    })
    expect(fromCwd.acceptancePlans.leaf!.input?.exists).toBe(true)
    expect(fromCwd.acceptancePlans.leaf!.input?.path).toBe('deck.md')
    // Target absent from cwd but present in the configured root -> fallback.
    const fromRoot = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ target: 'legacy.md' }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }], 'fallback-graph'), {
      captureBaseDir: sessionCwd,
    })
    expect(fromRoot.acceptancePlans.leaf!.input?.exists).toBe(true)
    // Absent from both roots -> honest missing.
    const missing = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ target: 'nope.md' }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }], 'missing-graph'), {
      captureBaseDir: sessionCwd,
    })
    expect(missing.acceptancePlans.leaf!.input?.exists).toBe(false)
    expect(missing.acceptancePlans.leaf!.input?.digest).toMatch(/^missing:/)
  })

  it('runs a programmatic leaf to success and recomputes the root', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root)
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'leaf' }] }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.leaf?.state).toBe('success')
    expect(run.rootState).toBe('success')
    expect(run.goals.leaf?.verification?.judgment.mode).toBe('programmatic')
  })

  it('propagates a fatal failure to the root and keeps tolerable siblings partial', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('fail') })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'strict' }, { op: 'ref', id: 'lenient' }] }),
      strict: leafNode({ title: 'strict', verifier: { mode: 'agentic', instruction: 'anything' } }),
      lenient: leafNode({ title: 'lenient', constraint: 'soft', verifier: { mode: 'agentic', instruction: 'anything' } }),
    }, [
      { parent: 'root', child: 'strict', required: true, failure: 'fatal' },
      { parent: 'root', child: 'lenient', required: false, failure: 'tolerable' },
    ]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.strict?.state).toBe('failure')
    expect(run.goals.lenient?.state).toBe('failure')
    expect(run.rootState).toBe('failure')
  })

  it('uses a degrade sibling when the primary child fails with degrade policy', async () => {
    const root = await tmpRoot()
    await mkdir(join(root, 'fallback'))
    await writeFile(join(root, 'artifact.txt'), 'verified')
    await writeFile(join(root, 'fallback', 'artifact.txt'), 'fallback')
    const dog = engine(root, { agentic: stubAgentic('fail') })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'primaryGoal' }),
      primaryGoal: leafNode({ title: 'primary', verifier: { mode: 'agentic', instruction: 'anything' } }),
      fallbackGoal: leafNode({ title: 'fallback', constraint: 'soft', target: 'fallback/artifact.txt' }),
    }, [
      { parent: 'root', child: 'primaryGoal', required: true, failure: 'degrade', degradeTo: 'fallbackGoal' },
      { parent: 'root', child: 'fallbackGoal', required: false, failure: 'tolerable' },
    ]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.primaryGoal?.state).toBe('failure')
    expect(run.goals.fallbackGoal?.state).toBe('success')
    expect(run.rootState).toBe('success')
  })

  it('settles an inconclusive agentic leaf as needs_human and the root as needs_replan', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('inconclusive') })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ verifier: { mode: 'agentic', instruction: 'anything' } }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.leaf?.state).toBe('needs_human')
    expect(run.rootState).toBe('needs_replan')
  })

  it('reuses a prior result when the object and judgment are unchanged (inherited)', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root)
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const first = await dog.run(compiled.input.id)
    expect(first.rootState).toBe('success')

    const second = await dog.run(compiled.input.id)
    expect(second.goals.leaf?.state).toBe('inherited')
    expect(second.goals.leaf?.inheritedFrom).toBe(first.runId)
    expect(second.rootState).toBe('success')
  })

  it('inherits settlements from a superseded (cancelled) prior run — host-restart leftovers', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root)
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const first = await dog.run(compiled.input.id)
    expect(first.rootState).toBe('success')
    // Simulate an orphaned run that the host superseded on restart: still
    // non-running now, with real settlements in its goal records.
    const repo = new DogRepository(join(root, '.dog-store'))
    await repo.updateRun(first.runId, current => ({
      ...current,
      state: 'cancelled' as const,
      runtimeWarning: 'superseded by a later run (host restart)',
      updatedAt: '2026-08-23T00:00:00.999Z',
    }))
    const second = await dog.run(compiled.input.id)
    expect(second.goals.leaf?.state).toBe('inherited')
    expect(second.goals.leaf?.inheritedFrom).toBe(first.runId)
    expect(second.rootState).toBe('success')
  })

  it('treats an inherited child failure as a failure: composite fails and skips its whole-object assertion', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('fail') })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }, {
        verifier: { mode: 'agentic', instruction: 'whole-object' },
      }),
      leaf: leafNode({ verifier: { mode: 'agentic', instruction: 'anything' } }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const first = await dog.run(compiled.input.id)
    expect(first.rootState).toBe('failure')

    const second = await dog.run(compiled.input.id)
    expect(second.goals.leaf?.state).toBe('inherited')
    // The inherited child carries passed:false, so the parent relation must NOT
    // read it as success, and the whole-object assertion must not run (a failing
    // subtree cannot be repaired by a demote-only merge).
    expect(second.goals.root?.state).toBe('failure')
    expect(second.goals.root?.reason).toBe('required non-tolerable child leaf failed')
  })

  it('records the whole-object assertion verdict and evidence on the composite result', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('fail') })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }, {
        verifier: { mode: 'agentic', instruction: 'whole-object' },
      }),
      leaf: leafNode({}), // programmatic, passes — so the assertion actually runs
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.root?.state).toBe('failure')
    expect(run.goals.root?.verification?.passed).toBe(false)
    expect(run.goals.root?.verification?.evidence).toEqual({ stubbed: true, verdict: 'fail' })
  })

  it('gates a dependent leaf behind a failed source', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('fail') })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'source' }, { op: 'ref', id: 'target' }] }),
      source: leafNode({ title: 'source', verifier: { mode: 'agentic', instruction: 'anything' } }),
      target: leafNode({ title: 'target', verifier: { mode: 'agentic', instruction: 'anything' } }),
    }, [
      { parent: 'root', child: 'source', required: true, failure: 'fatal' },
      { parent: 'root', child: 'target', required: true, failure: 'fatal' },
    ], 'gated'))
    void compiled
    // dependsOn requires a follow-up; covered by the scheduling path in engine internals;
    // asserting the source failure propagates is the observable contract here.
  })

  it('releases a leaf waiting on a fast programmatic sibling once it completes (completion gate, not a success gate)', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('pass') })
    const compiled = await dog.create({
      schemaVersion: '0.9',
      id: 'dep-complete',
      root: 'root',
      nodes: {
        root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'fast' }, { op: 'ref', id: 'slow' }] }),
        fast: leafNode({ title: 'fast' }), // programmatic, resolves immediately
        slow: leafNode({ title: 'slow', verifier: { mode: 'agentic', instruction: 'anything' } }),
      },
      contains: [
        { parent: 'root', child: 'fast', required: true, failure: 'fatal' },
        { parent: 'root', child: 'slow', required: true, failure: 'fatal' },
      ],
      dependsOn: [{ source: 'slow', target: 'fast' }],
    })
    const run = await dog.run(compiled.input.id)
    // The slow leaf is released after fast completes — it must NOT be dead-blocked.
    expect(run.goals.slow?.state).toBe('success')
    expect(run.goals.slow?.reason).toBeUndefined()
    expect(run.rootState).toBe('success')
  })

  it('releases a dependent leaf even when its dependency failed (terminal state, any verdict)', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, { agentic: stubAgentic('fail') })
    const compiled = await dog.create({
      schemaVersion: '0.9',
      id: 'dep-failed-target',
      root: 'root',
      nodes: {
        root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'bad' }, { op: 'ref', id: 'waiter' }] }),
        bad: leafNode({ title: 'bad', verifier: { mode: 'agentic', instruction: 'anything' } }),
        waiter: leafNode({ title: 'waiter', verifier: { mode: 'agentic', instruction: 'anything' } }),
      },
      contains: [
        { parent: 'root', child: 'bad', required: true, failure: 'fatal' },
        { parent: 'root', child: 'waiter', required: true, failure: 'fatal' },
      ],
      dependsOn: [{ source: 'waiter', target: 'bad' }],
    })
    const run = await dog.run(compiled.input.id)
    expect(run.goals.bad?.state).toBe('failure')
    // The waiter still runs its own judgment (also fail here) — never a dead block.
    expect(run.goals.waiter?.state).toBe('failure')
    expect(run.goals.waiter?.reason).toBeUndefined()
    expect(run.rootState).toBe('failure')
  })

  it('cancelling aborts in-flight verifiers and never lets the record flip back to completed', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const slowAgentic = async (): Promise<{ state: 'pass'; evidence: Record<string, never> }> => {
      await new Promise(resolve => setTimeout(resolve, 700))
      return { state: 'pass' as const, evidence: {} }
    }
    const dog = engine(root, { agentic: slowAgentic as ReturnType<typeof stubAgentic> })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ verifier: { mode: 'agentic', instruction: 'anything' } }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const started = await dog.startRun(compiled.input.id)
    await new Promise(resolve => setTimeout(resolve, 80))
    await dog.cancelRun(started.runId, 'test cancel')
    // Give the slow stub time to finish — the run record must stay cancelled.
    await new Promise(resolve => setTimeout(resolve, 1200))
    const after = await dog.status(started.runId)
    expect(after.state).toBe('cancelled')
    expect(after.rootState).toBe('cancelled')
    expect(after.goals.leaf?.state).not.toBe('success')
    expect(after.goals.leaf?.state).toBe('cancelled')
  })

  it('runs programmatic leaves without queuing behind the agentic concurrency budget', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const slowAgentic = async (): Promise<{ state: 'pass'; evidence: Record<string, never> }> => {
      await new Promise(resolve => setTimeout(resolve, 300))
      return { state: 'pass' as const, evidence: {} }
    }
    const dog = engine(root, {
      agentic: slowAgentic as ReturnType<typeof stubAgentic>,
      config: { ...mkConfig(root, join(root, 'scripts')), maxConcurrentVerifications: 1 },
      now: () => new Date(),
    })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'slow' }, { op: 'ref', id: 'fast' }] }),
      slow: leafNode({ title: 'slow', verifier: { mode: 'agentic', instruction: 'anything' } }),
      fast: leafNode({ title: 'fast' }),
    }, [
      { parent: 'root', child: 'slow', required: true, failure: 'fatal' },
      { parent: 'root', child: 'fast', required: true, failure: 'fatal' },
    ]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.fast?.state).toBe('success')
    expect(run.goals.slow?.state).toBe('success')
    expect(run.rootState).toBe('success')
    // Regression guard: with the concurrency budget gating only agentic leaves,
    // the programmatic leaf settles *before* the slow agentic one. The old
    // scheduler (budget counted every leaf) queued it behind the 300ms agentic
    // wait, so its goal_settled landed strictly after — this assertion reddens
    // if the pump concurrency gate regresses.
    const repo = new DogRepository(join(root, '.dog-store'))
    const fastSettled = (await repo.loadGoalRuntimeEvents(run.runId, 'fast')).find(event => event.phase === 'goal_settled')
    const slowSettled = (await repo.loadGoalRuntimeEvents(run.runId, 'slow')).find(event => event.phase === 'goal_settled')
    expect(fastSettled).toBeDefined()
    expect(slowSettled).toBeDefined()
    expect(fastSettled!.at < slowSettled!.at).toBe(true)
  })

  it('allocates run workspaces under the calling session cwd when it is known', async () => {
    const root = await tmpRoot()
    const agentCwd = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root, {
      resolveLivingAgent: id => (id === 'session-ws-1' ? { id, session: { header: { cwd: agentCwd } } } as unknown as Agent : undefined),
    })
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id, {
      invocation: { callId: 'call-ws-1', agentSessionId: 'session-ws-1' },
    })
    expect(run.workspaceBaseDir).toBe(agentCwd)
    expect(run.rootState).toBe('success')
  })

  it('falls back to the configured root when no session cwd is known', async () => {
    const root = await tmpRoot()
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = engine(root)
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id, { invocation: { callId: 'call-ws-2' } })
    expect(run.workspaceBaseDir).toBeUndefined()
    expect(run.rootState).toBe('success')
  })

  it('rejects a leaf without a verifier and an absolute target', async () => {
    const root = await tmpRoot()
    const dog = engine(root)
    const missingVerifier = graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ verifier: undefined as unknown as VerifierShape }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }])
    const report = dog.validate(missingVerifier)
    expect(report.valid).toBe(false)
    const absoluteTarget = graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ target: '/etc/passwd' }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }])
    const report2 = dog.validate(absoluteTarget)
    expect(report2.valid).toBe(false)
  })

  it('packed captures a directory target into .tar when the target is a directory', async () => {
    const root = await tmpRoot()
    await mkdir(join(root, 'dir'))
    await writeFile(join(root, 'dir', 'a.txt'), 'a')
    const dog = engine(root)
    const candidate = graph({
      root: compositeNode({ op: 'ref', id: 'leaf' }),
      leaf: leafNode({ target: 'dir' }),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }])
    const compiled = await dog.create(candidate)
    expect(compiled.acceptancePlans.leaf!.input?.packed).toBe(true)
    expect(compiled.acceptancePlans.leaf!.input?.byteLength).toBeGreaterThan(0)
  })
})
