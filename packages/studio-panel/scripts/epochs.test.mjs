/**
 * WorkbenchStore epoch-invalidation logic tests (pure functions, no React).
 * Run: node --experimental-strip-types scripts/epochs.test.mjs
 * (Node ≥22.6 strips types; assertions via node:test to avoid new deps.)
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { nextEpochs, triggersRefresh } from '../src/client/workbench-epochs.ts'

const ZERO = {
  workspace: 0, manuscript: 0, outline: 0, assets: 0, tasks: 0,
  benchmark: 0, models: 0, dag: 0, graph: 0, research: 0, revisions: 0,
}

function bump(resource, times = 1) {
  let epochs = { ...ZERO }
  for (let i = 0; i < times; i += 1) epochs = nextEpochs(resource, epochs)
  return epochs
}

test('assets mutation increases graph epoch (derived)', () => {
  const e = bump('assets')
  assert.equal(e.assets, 1)
  assert.equal(e.graph, 1)
})

test('outline mutation increases graph epoch (derived)', () => {
  const e = bump('outline')
  assert.equal(e.outline, 1)
  assert.equal(e.graph, 1)
})

test('workspace mutation increases graph epoch (derived)', () => {
  const e = bump('workspace')
  assert.equal(e.workspace, 1)
  assert.equal(e.graph, 1)
})

test('manuscript mutation increases graph epoch (derived)', () => {
  const e = bump('manuscript')
  assert.equal(e.manuscript, 1)
  assert.equal(e.graph, 1)
})


test('tasks mutation bumps tasks (DAG view) without graph', () => {
  const e = bump('tasks')
  assert.equal(e.tasks, 1)
  assert.equal(e.graph, 0)
})

test('benchmark/models mutations do not touch graph', () => {
  for (const resource of ['benchmark', 'models', 'research', 'revisions']) {
    const e = bump(resource)
    assert.equal(e[resource], 1, resource)
    assert.equal(e.graph, 0, resource)
  }
})

test('repeated mutations accumulate and derived bumps coexist', () => {
  let e = bump('assets', 2)
  assert.equal(e.assets, 2)
  assert.equal(e.graph, 2)
  e = nextEpochs('manuscript', e)
  assert.equal(e.manuscript, 1)
  assert.equal(e.graph, 3)
})

test('SSE and polling paths behave identically (same pure function)', () => {
  // Both channels call the same invalidate() → nextEpochs; assert idempotence
  // of the pure function for a single mutation from the same snapshot.
  const sse = nextEpochs('assets', { ...ZERO })
  const polling = nextEpochs('assets', { ...ZERO })
  assert.deepEqual(sse, polling)
})

test('refresh trigger set matches workspace/manuscript/outline/tasks only', () => {
  for (const resource of ['workspace', 'manuscript', 'outline', 'tasks']) {
    assert.equal(triggersRefresh(resource), true, resource)
  }
  for (const resource of ['benchmark', 'models', 'graph', 'research', 'revisions', 'dag', 'assets']) {
    assert.equal(triggersRefresh(resource), false, resource)
  }
})
