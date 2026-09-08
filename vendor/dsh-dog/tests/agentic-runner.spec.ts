/** DoG v0.9 agentic kernel contract: identity, instruction delivery, verdict mapping. */

import { writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { describe, it, expect, afterEach } from 'vitest'
import { DogEngine } from '../src/core.ts'
import type { DogConfig } from '../src/model.ts'
import { DogRepository } from '../src/storage.ts'
import { compositeNode, ensureScripts, graph, leafNode, mkConfig, temporaryRoot } from './helpers.ts'

const roots: string[] = []

afterEach(async () => {
  await Promise.all(roots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

async function setup(verdict: 'pass' | 'fail' = 'pass'): Promise<{ root: string; dog: DogEngine; seenInstructions: string[] }> {
  const root = await temporaryRoot()
  roots.push(root)
  await ensureScripts(root)
  await writeFile(join(root, 'artifact.txt'), 'verified')
  const config: DogConfig = mkConfig(root, join(root, 'scripts'))
  const repository = new DogRepository(join(root, '.dog-store'))
  const seenInstructions: string[] = []
  const dog = new DogEngine({
    config,
    repository,
    now: () => new Date('2026-08-23T00:00:00.000Z'),
    nextRunId: () => `run-${Math.random().toString(36).slice(2)}`,
  })
  dog.setKernels(
    async () => ({ state: 'pass' as const, evidence: { stub: 'programmatic' } }),
    async instruction => {
      seenInstructions.push(instruction)
      return { state: verdict as 'pass' | 'fail', evidence: { fromRunner: true, verdict } }
    },
  )
  return { root, dog, seenInstructions }
}

describe('v0.9 agentic kernel', () => {
  it('delivers the leaf instruction verbatim and maps a pass verdict to success', async () => {
    const { dog, seenInstructions } = await setup('pass')
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'audit' }),
      audit: leafNode({ verifier: { mode: 'agentic', instruction: '检查模板腔,自己想怎么做' } }),
    }, [{ parent: 'root', child: 'audit', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id)
    expect(run.rootState).toBe('success')
    expect(seenInstructions).toEqual(['检查模板腔,自己想怎么做'])
    expect(run.goals.audit?.verification?.evidence).toMatchObject({ fromRunner: true })
  })

  it('maps a fail verdict to failure with free-form evidence preserved', async () => {
    const { dog } = await setup('fail')
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'ref', id: 'audit' }),
      audit: leafNode({ verifier: { mode: 'agentic', instruction: '检查' } }),
    }, [{ parent: 'root', child: 'audit', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id)
    console.log('DBG_RUN', JSON.stringify(run.goals))
    expect(run.goals.audit?.state).toBe('failure')
    expect(run.rootState).toBe('failure')
    expect(run.goals.audit?.verification?.judgment).toEqual({ mode: 'agentic', instructionHash: expect.stringMatching(/^sha256:/) })
  })

  it('supports composite whole-object assertions after the subtree settles', async () => {
    const { dog, seenInstructions } = await setup('fail')
    const compiled = await dog.create(graph({
      root: compositeNode({ op: 'all', items: [{ op: 'ref', id: 'leaf' }] }, {
        title: 'whole', constraint: 'hard',
        verifier: { mode: 'agentic', instruction: '整体断言:检查是否协调一致' },
      }),
      leaf: leafNode({}),
    }, [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }]))
    const run = await dog.run(compiled.input.id)
    expect(run.goals.leaf?.state).toBe('success')
    expect(run.goals.root?.state).toBe('failure')
    expect(seenInstructions).toContain('整体断言:检查是否协调一致')
  })
})
