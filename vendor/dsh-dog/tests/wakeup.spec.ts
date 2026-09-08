import { writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { describe, it, expect, afterEach } from 'vitest'
import { DogEngine } from '../src/core.ts'
import { DogRepository } from '../src/storage.ts'
import { compositeNode, ensureScripts, leafNode, mkConfig, stubProgrammatic, temporaryRoot } from './helpers.ts'

const roots: string[] = []
afterEach(async () => { await Promise.all(roots.splice(0).map(p => rm(p, { recursive: true, force: true }))) })

function makeEngine(root: string, opts: { delayMs?: number } = {}): DogEngine {
  const dog = new DogEngine({
    config: { ...mkConfig(root, join(root, 'scripts')), maxConcurrentVerifications: 8 },
    repository: new DogRepository(join(root, '.dog-store')),
    now: () => new Date(),
  })
  const agentic = async (): Promise<{ state: 'pass'; evidence: Record<string, never> }> => {
    await new Promise(resolve => setTimeout(resolve, opts.delayMs ?? 120))
    return { state: 'pass' as const, evidence: {} }
  }
  dog.setKernels(stubProgrammatic(), agentic as never)
  return dog
}

describe('dependency wakeup', () => {
  it('starts a released leaf as soon as its dependency completes, while siblings are still running', async () => {
    const root = await temporaryRoot(); roots.push(root)
    await ensureScripts(root)
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = makeEngine(root, { delayMs: 350 })
    const compiled = await dog.create({
      schemaVersion: '0.9',
      id: 'wakeup',
      root: 'root',
      nodes: {
        root: compositeNode({
          op: 'all', items: [
            { op: 'ref', id: 'dep' }, { op: 'ref', id: 'a1' }, { op: 'ref', id: 'a2' },
            { op: 'ref', id: 'a3' }, { op: 'ref', id: 'a4' }, { op: 'ref', id: 'a5' },
          ],
        }),
        dep: leafNode({ title: 'dep' }), // programmatic, instant
        a1: leafNode({ title: 'a1', verifier: { mode: 'agentic', instruction: 'x' } }),
        a2: leafNode({ title: 'a2', verifier: { mode: 'agentic', instruction: 'x' } }),
        a3: leafNode({ title: 'a3', verifier: { mode: 'agentic', instruction: 'x' } }),
        a4: leafNode({ title: 'a4', verifier: { mode: 'agentic', instruction: 'x' } }),
        a5: leafNode({ title: 'a5', verifier: { mode: 'agentic', instruction: 'x' } }),
      },
      contains: [
        { parent: 'root', child: 'dep', required: true, failure: 'fatal' },
        { parent: 'root', child: 'a1', required: true, failure: 'fatal' },
        { parent: 'root', child: 'a2', required: true, failure: 'fatal' },
        { parent: 'root', child: 'a3', required: true, failure: 'fatal' },
        { parent: 'root', child: 'a4', required: true, failure: 'fatal' },
        { parent: 'root', child: 'a5', required: true, failure: 'fatal' },
      ],
      dependsOn: [{ source: 'a1', target: 'dep' }],
    })
    const run = await dog.run(compiled.input.id)
    const repo = new DogRepository(join(root, '.dog-store'))
    const a1Events = await repo.loadGoalRuntimeEvents(run.runId, 'a1')
    const a2Events = await repo.loadGoalRuntimeEvents(run.runId, 'a2')
    const started = (es: readonly { phase: string; at: string }[], phase: string): string | undefined =>
      es.find(e => e.phase === phase)?.at
    // dep completes instantly; a1 (depending on it) must start WHILE a2..a5
    // are still running — strictly before a2's goal_settled. A wave scheduler
    // would start a1 only after the whole first batch settled -> fails here.
    const a1Start = started(a1Events, 'verifier_started')
    const a2Done = started(a2Events, 'goal_settled')
    expect(a1Start).toBeDefined()
    expect(a2Done).toBeDefined()
    expect(a1Start! < a2Done!).toBe(true)
    expect(run.goals.a1?.state).toBe('success')
    expect(run.goals.dep?.state).toBe('success')
    expect(run.rootState).toBe('success')
  })

  it('runs mutually independent composite assertions concurrently (not a serial for loop)', async () => {
    const root = await temporaryRoot(); roots.push(root)
    await ensureScripts(root)
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const dog = makeEngine(root, { delayMs: 350 })
    const compiled = await dog.create({
      schemaVersion: '0.9',
      id: 'composite-parallel',
      root: 'root',
      nodes: {
        root: compositeNode({
          op: 'all', items: [
            { op: 'ref', id: 'g-a' }, { op: 'ref', id: 'g-b' },
          ],
        }),
        'g-a': compositeNode({ op: 'ref', id: 'la' }, {
          title: 'g-a',
          verifier: { mode: 'agentic', instruction: 'whole-a' },
        }),
        'g-b': compositeNode({ op: 'ref', id: 'lb' }, {
          title: 'g-b',
          verifier: { mode: 'agentic', instruction: 'whole-b' },
        }),
        la: leafNode({ title: 'la', verifier: { mode: 'agentic', instruction: 'x' } }),
        lb: leafNode({ title: 'lb', verifier: { mode: 'agentic', instruction: 'x' } }),
      },
      contains: [
        { parent: 'root', child: 'g-a', required: true, failure: 'fatal' },
        { parent: 'root', child: 'g-b', required: true, failure: 'fatal' },
        { parent: 'g-a', child: 'la', required: true, failure: 'fatal' },
        { parent: 'g-b', child: 'lb', required: true, failure: 'fatal' },
      ],
      dependsOn: [],
    })
    const run = await dog.run(compiled.input.id)
    const repo = new DogRepository(join(root, '.dog-store'))
    const gaEvents = await repo.loadGoalRuntimeEvents(run.runId, 'g-a')
    const gbEvents = await repo.loadGoalRuntimeEvents(run.runId, 'g-b')
    const started = (es: readonly { phase: string; at: string }[], phase: string): string | undefined =>
      es.find(e => e.phase === phase)?.at
    // Both whole-object assertions must start while the other is still
    // running: g-b's verifier_started < g-a's goal_settled (serial would fail).
    const gaStart = started(gaEvents, 'verifier_started')
    const gbStart = started(gbEvents, 'verifier_started')
    const gaDone = started(gaEvents, 'goal_settled')
    expect(gaStart).toBeDefined()
    expect(gbStart).toBeDefined()
    expect(gaDone).toBeDefined()
    expect(gbStart! < gaDone!).toBe(true)
    expect(run.rootState).toBe('success')
  })
})
