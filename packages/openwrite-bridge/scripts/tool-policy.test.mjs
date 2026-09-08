import test from 'node:test'
import assert from 'node:assert/strict'
import { novelEffect, novelPolicyDenial } from '../lib/tool-policy.js'
import { registerNovelTools } from '../lib/tools.js'

test('every registered novel tool has a conservative effect; mixed actions do not inherit read access', () => {
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => { throw new Error('No API call allowed') }, { timeoutMs: 1000, outputDir: '/unused' })
  assert.equal(tools.length, 90)
  for (const tool of tools) assert.ok(['read', 'write', 'generate'].includes(novelEffect(tool.name, {})))
  assert.equal(novelEffect('novel_model_benchmark', { action: 'get' }), 'read')
  assert.equal(novelEffect('novel_model_benchmark', { action: 'run' }), 'generate')
  assert.equal(novelEffect('novel_document_change_plan', { action: 'preview' }), 'write')
  assert.equal(novelEffect('novel_reference_library_action', { action: 'import' }), 'write')
  assert.equal(novelEffect('novel_unknown_future_action', { action: 'read' }), 'write')
})

test('host write policy and plan state independently gate generation and changes', () => {
  for (const mode of ['read-only', 'workspace-write']) for (const active of [true, false]) {
    const ctx = { get: name => name === 'sandboxPolicy' ? { resolve: () => ({ mode }) } : undefined }
    const agent = { ctx: { get: () => ({ get: () => ({ active }) }) }, session: {} }
    const denied = mode === 'read-only' || active
    for (const name of ['novel_doc_write', 'novel_write_chapter', 'novel_revision_apply']) {
      assert.equal(Boolean(novelPolicyDenial(ctx, { name, agent, arguments: {} })), denied)
    }
    assert.equal(novelPolicyDenial(ctx, { name: 'novel_doc_read', agent, arguments: {} }), undefined)
  }
  assert.match(novelPolicyDenial({ get: () => undefined }, { name: 'novel_doc_write', arguments: {} }), /POLICY_REQUIRED/)
  assert.match(novelPolicyDenial({ get: () => undefined }, { name: 'novel_doc_write', agent: { ctx: { get: () => undefined }, session: {} }, arguments: {} }), /READ_ONLY/)
})

test('real dsh tool registry isolates 90 tools by preset and disposes them', async () => {
  const { Context } = await import('@deepseek-ai/cordis')
  const { ToolRuntime } = await import('@deepseek-ai/dsh-tools')
  const { createScope } = await import('@deepseek-ai/dsh-scope')
  const preset = await import('../lib/preset-tools.js')
  const root = new Context()
  root.provide('systemPrompt', { tools: () => () => {}, section: () => () => {}, getSectionOrder: () => 0 })
  root.provide('novelDomain', { toolOptions: { timeoutMs: 600_000 }, clientFactory: () => () => { throw new Error('No backend calls in catalog inspection') } })
  await root.plugin(ToolRuntime)
  const writing = {}, normal = {}
  const scope = createScope(root, writing)
  try {
    await scope.ctx.plugin(preset)
    assert.equal(root.tools.schemas().filter(tool => tool.name.startsWith('novel_')).length, 0)
    assert.equal(root.tools.schemas(normal).filter(tool => tool.name.startsWith('novel_')).length, 0)
    Object.assign(writing, { ctx: scope.ctx, session: {} })
    const denied = await root.tools.execute({ callId: 'policy-denied', name: 'novel_doc_write', arguments: {}, agent: writing, signal: new AbortController().signal })
    assert.equal(denied.isError, true)
    assert.match(JSON.stringify(denied), /OPENWRITE_READ_ONLY/)
    const tools = root.tools.schemas(writing)
    assert.equal(tools.filter(tool => tool.name.startsWith('novel_')).length, 90)
    console.log(JSON.stringify({ measurement: 'native-tool-schema', tools: tools.length, utf8Bytes: Buffer.byteLength(JSON.stringify(tools)), tokenizer: 'not-measured' }))
    await scope.dispose()
    assert.equal(root.tools.schemas(writing).length, 0)
  } finally { await root.fiber.dispose() }
})
