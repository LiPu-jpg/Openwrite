import test from 'node:test'
import assert from 'node:assert/strict'
import { registerNovelTools } from '../lib/tools.js'

function tools() {
  const registered = []
  const client = {
    postJson: async () => ({ ok: true }),
    getJson: async () => ({ ok: true }),
  }
  registerNovelTools(
    { tools: { register: tool => registered.push(tool) } },
    () => client,
    { timeoutMs: 1000, outputDir: '/unused' },
  )
  return registered
}

const exec = { signal: new AbortController().signal, callId: 'arguments' }

test('an undeclared argument is refused instead of silently dropped', async () => {
  // The tool used to answer "ok" for an action it never implemented, so a
  // model typo looked like a successful call.
  const tool = tools().find(t => t.name === 'novel_manuscript_acceptance')

  await assert.rejects(
    () => tool.execute({ action: 'noop' }, exec),
    error => {
      assert.match(error.message, /additionalProperties: false/)
      assert.match(error.message, /action/)
      return true
    },
  )
})

test('every declared parameter still passes the schema check', async () => {
  const tool = tools().find(t => t.name === 'novel_assets')

  assert.equal(tool.parameters.additionalProperties, false)
  assert.equal(tool.parameters.type, 'object')
  assert.ok(tool.parameters.properties.id)
})

test('the asset id requirement is visible in the schema the model reads', async () => {
  const tool = tools().find(t => t.name === 'novel_assets')

  assert.match(tool.parameters.properties.id.description, /required for read\/create\/update/)
  assert.match(tool.parameters.properties.id.description, /A-Za-z0-9/)
})

test('a missing asset id says what a valid one looks like', async () => {
  // The bare "id is required" message left the model guessing the format and
  // retrying with the same wrong shape.
  const tool = tools().find(t => t.name === 'novel_assets')

  await assert.rejects(
    () => tool.execute({ action: 'create', kind: 'character' }, exec),
    error => {
      assert.match(error.message, /id is required for novel_assets\(action="create"\)/)
      assert.match(error.message, /A-Za-z0-9/)
      return true
    },
  )
})

test('a malformed asset id names the accepted shape', async () => {
  const tool = tools().find(t => t.name === 'novel_assets')

  await assert.rejects(
    () => tool.execute({ action: 'create', kind: 'character', id: '夏洛克' }, exec),
    error => {
      assert.match(error.message, /invalid asset id/)
      assert.match(error.message, /A-Za-z0-9/)
      return true
    },
  )
})

test('the schema description and the runtime error quote the same id shape', async () => {
  // The schema description is a literal (the doc generator requires one) and
  // the error message is built from a constant, so the two can drift. Tie them
  // together here: the model reads the description, then the error.
  const tool = tools().find(t => t.name === 'novel_assets')
  const shape = tool.parameters.properties.id.description.match(/\[A-Za-z0-9\]\[A-Za-z0-9_.-\]\{0,79\}/)?.[0]

  assert.ok(shape, 'the id description must state the accepted shape')

  await assert.rejects(
    () => tool.execute({ action: 'create', kind: 'character' }, exec),
    error => {
      assert.ok(error.message.includes(shape), `error must quote ${shape}: ${error.message}`)
      return true
    },
  )
})

test('an import prepare without arc_id falls back to the current arc', async () => {
  const calls = []
  const registered = []
  const client = {
    postJson: async (path, body) => { calls.push({ path, body }); return { ok: true } },
    getJson: async () => ({ ok: true }),
  }
  registerNovelTools(
    { tools: { register: tool => registered.push(tool) } },
    () => client,
    { timeoutMs: 1000, outputDir: '/unused' },
  )
  const tool = registered.find(t => t.name === 'novel_manuscript_import_action')

  await tool.execute({ action: 'prepare', content: '第一章正文' }, exec)

  assert.equal(calls.length, 1)
  assert.equal(calls[0].path, '/api/manuscript-imports/prepare')
  assert.equal(calls[0].body.arc_id, undefined)
})

test('the outline metadata contract names every writable field', async () => {
  const tool = tools().find(t => t.name === 'novel_outline_edit')

  for (const field of [
    'dramatic_position', 'content_focus', 'goals', 'target_words', 'word_budget',
    'characters', 'settings', 'emotional_arc', 'beats', 'hooks', 'promise',
    'payoff_of', 'function',
  ]) {
    assert.ok(
      tool.parameters.properties.metadata.description.includes(field),
      `${field} must be named in the metadata description`,
    )
  }
})

test('the metadata description says what shape each field takes', async () => {
  // "Use target_words, beats, hooks or characters" never said whether a list
  // field wanted a string or an array, and the two fields disagreed.
  const tool = tools().find(t => t.name === 'novel_outline_edit')
  const description = tool.parameters.properties.metadata.description

  assert.match(description, /array of strings/)
  assert.match(description, /comma-separated string/)
  assert.match(description, /take a number/)
})

test('an empty chapter id is the project-level operation, not a malformed one', async () => {
  const calls = []
  const registered = []
  const client = {
    postJson: async (path, body) => { calls.push({ path, body }); return { ok: true } },
    getJson: async () => ({ ok: true }),
  }
  registerNovelTools(
    { tools: { register: tool => registered.push(tool) } },
    () => client,
    { timeoutMs: 1000, outputDir: '/unused' },
  )
  const tool = registered.find(t => t.name === 'novel_manuscript_acceptance_reconcile')

  await tool.execute({ action: 'external', chapter_id: '', confirm: true }, exec)

  assert.equal(calls.length, 1)
  assert.equal(calls[0].path, '/api/manuscript/acceptance/external')
  // The server resolves an absent chapter id to the project-level operation.
  assert.equal(calls[0].body.chapter_id, undefined)
})

test('a malformed chapter id is still refused', async () => {
  const tool = tools().find(t => t.name === 'novel_manuscript_acceptance_reconcile')

  await assert.rejects(
    () => tool.execute({ action: 'external', chapter_id: 'ch_x', confirm: true }, exec),
    error => {
      assert.match(error.message, /chapter_id must match ch_<digits>/)
      return true
    },
  )
})
