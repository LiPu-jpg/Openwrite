/** DoG v0.9 debugger projection: snapshot/parse round-trip with new fields. */

import { writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { describe, it, expect, afterEach } from 'vitest'
import { DogEngine } from '../src/core.ts'
import { DogRepository } from '../src/storage.ts'
import { buildDogDebugSnapshot } from '../src/debug.ts'
import { parseDogDebugSnapshot } from '../src/client/snapshot.ts'
import { compositeNode, ensureScripts, graph, leafNode, mkConfig, stubAgentic, stubProgrammatic, temporaryRoot } from './helpers.ts'

const roots: string[] = []

afterEach(async () => {
  await Promise.all(roots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('v0.9 debugger snapshot', () => {
  it('projects a compiled graph and parses it back with the new verifier/target shape', async () => {
    const root = await temporaryRoot()
    roots.push(root)
    await ensureScripts(root)
    await writeFile(join(root, 'artifact.txt'), 'verified')
    const repo = new DogRepository(join(root, '.dog-store'))
    const dog = new DogEngine({
      config: mkConfig(root, join(root, 'scripts')),
      repository: repo,
      now: () => new Date('2026-08-23T00:00:00.000Z'),
      nextRunId: () => 'run-dbg',
    })
    dog.setKernels(stubProgrammatic(), stubAgentic())
    await dog.create(graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'leaf' }] }, {
        verifier: { mode: 'agentic', instruction: '整体断言' },
      }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const snapshot = await buildDogDebugSnapshot(repo)
    const parsed = parseDogDebugSnapshot(JSON.parse(JSON.stringify(snapshot)))
    expect(parsed.graphs.length).toBe(1)
    const plan = parsed.graphs[0]!.graph.acceptancePlans.leaf!
    expect(plan.verifier).toMatchObject({ mode: 'programmatic', script: 'file-non-empty' })
    expect(plan.judgment.mode).toBe('programmatic')
    expect(parsed.graphs[0]!.graph.acceptancePlans.root!.verifier).toMatchObject({ mode: 'agentic' })
  })
})
