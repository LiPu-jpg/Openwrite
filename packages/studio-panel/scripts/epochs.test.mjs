/**
 * WorkbenchStore epoch-invalidation logic tests (pure functions, no React).
 * Run: node --experimental-strip-types scripts/epochs.test.mjs
 * (Node ≥22.6 strips types; assertions via node:test to avoid new deps.)
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { nextEpochs, terminalTransitionResources, triggersRefresh } from '../src/client/workbench-epochs.ts'

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

function taskList(tasks) {
  return { data: { tasks } }
}

test('terminalTransitionResources: newly terminal research task bumps research', () => {
  const before = taskList([{ task_id: 'tsk_1', type: 'research', status: 'running' }])
  const after = taskList([{ task_id: 'tsk_1', type: 'research', status: 'completed' }])
  assert.deepEqual(terminalTransitionResources(before, after), ['research'])
})

test('terminalTransitionResources: benchmark and review tasks map to their views', () => {
  const before = taskList([
    { task_id: 'tsk_b', type: 'model_benchmark', status: 'running' },
    { task_id: 'tsk_r', type: 'chapter_review', status: 'awaiting_confirmation' },
    { task_id: 'tsk_w', type: 'chapter_write', status: 'running' },
    { task_id: 'tsk_s', type: 'revision_selection', status: 'pending' },
    { task_id: 'tsk_f', type: 'revision_from_review', status: 'running' },
  ])
  const after = taskList([
    { task_id: 'tsk_b', type: 'model_benchmark', status: 'failed' },
    { task_id: 'tsk_r', type: 'chapter_review', status: 'completed' },
    { task_id: 'tsk_w', type: 'chapter_write', status: 'cancelled' },
    { task_id: 'tsk_s', type: 'revision_selection', status: 'interrupted' },
    { task_id: 'tsk_f', type: 'revision_from_review', status: 'completed' },
  ])
  const resources = terminalTransitionResources(before, after)
  assert.deepEqual([...resources].sort(), ['benchmark', 'dag'])
})

test('terminalTransitionResources: no transition yields nothing', () => {
  const before = taskList([
    { task_id: 'tsk_1', type: 'research', status: 'completed' },
    { task_id: 'tsk_2', type: 'model_benchmark', status: 'running' },
  ])
  // Terminal → terminal and non-terminal → non-terminal are not transitions.
  const after = taskList([
    { task_id: 'tsk_1', type: 'research', status: 'completed' },
    { task_id: 'tsk_2', type: 'model_benchmark', status: 'running' },
  ])
  assert.deepEqual(terminalTransitionResources(before, after), [])
  assert.deepEqual(
    terminalTransitionResources(
      taskList([{ task_id: 'tsk_2', type: 'manuscript_import', status: 'running' }]),
      taskList([{ task_id: 'tsk_2', type: 'manuscript_import', status: 'completed' }]),
    ),
    ['manuscript'],
  )
  assert.deepEqual(
    terminalTransitionResources(
      taskList([{ task_id: 'tsk_3', type: 'project_restore', status: 'running' }]),
      taskList([{ task_id: 'tsk_3', type: 'project_restore', status: 'completed' }]),
    ),
    ['workspace'],
  )
  // Unknown task types carry no typed resource.
  const unknown = taskList([{ task_id: 'tsk_4', type: 'future_task', status: 'completed' }])
  assert.deepEqual(terminalTransitionResources(taskList([{ task_id: 'tsk_4', type: 'future_task', status: 'running' }]), unknown), [])
})

test('terminalTransitionResources: tasks absent from the previous payload are not transitions', () => {
  // Initial loads / window re-entries stay quiet: we never observed them running.
  assert.deepEqual(
    terminalTransitionResources(taskList([]), taskList([{ task_id: 'tsk_1', type: 'research', status: 'completed' }])),
    [],
  )
  assert.deepEqual(
    terminalTransitionResources(null, taskList([{ task_id: 'tsk_1', type: 'research', status: 'completed' }])),
    [],
  )
})

test('terminalTransitionResources: malformed payloads yield [] and never throw', () => {
  const good = taskList([{ task_id: 'tsk_1', type: 'research', status: 'running' }])
  for (const garbage of [null, undefined, 42, 'tasks', [], { data: null }, { data: { tasks: 'nope' } }, { tasks: [] }]) {
    assert.deepEqual(terminalTransitionResources(garbage, good), [])
    assert.deepEqual(terminalTransitionResources(good, garbage), [])
  }
  // Malformed entries are skipped, valid ones still diff.
  const mixed = taskList([null, 7, { task_id: 'tsk_1' }, { task_id: 'tsk_1', type: 'research', status: 'completed' }])
  assert.deepEqual(terminalTransitionResources(good, mixed), ['research'])
})
