import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { novelEffect, novelPolicyDenial } from '../lib/tool-policy.js'
import { registerNovelTools, workspaceContextFromExec } from '../lib/tools.js'
import { StudioClient, StudioError, workspaceRootsEqual } from '../lib/client.js'

test('every registered novel tool has a conservative effect; mixed actions do not inherit read access', () => {
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => { throw new Error('No API call allowed') }, { timeoutMs: 1000, outputDir: '/unused' })
  assert.equal(tools.length, 56)
  for (const tool of tools) assert.ok(['read', 'write', 'generate'].includes(novelEffect(tool.name, {})))
  assert.equal(novelEffect('novel_model_benchmark', { action: 'get' }), 'read')
  assert.equal(novelEffect('novel_model_benchmark', { action: 'run' }), 'generate')
  assert.equal(novelEffect('novel_change_plan', { action: 'document', step: 'preview' }), 'write')
  assert.equal(novelEffect('novel_change_plan', { action: 'structured', step: 'preview' }), 'write')
  assert.equal(novelEffect('novel_reference_library_action', { action: 'import' }), 'write')
  assert.equal(novelEffect('novel_unknown_future_action', { action: 'read' }), 'write')
  // An action-dispatching tool must never be classified as a whole: `reads`
  // short-circuits before `readActions`, so listing a merged family there makes
  // its destructive actions run under a read-only sandbox or plan mode.
  // `novel_model_profiles`/`novel_embedding_profiles` were listed that way by
  // mistake after the 95→56 merge.
  for (const tool of tools) {
    const dispatches = tool.parameters?.action !== undefined
    if (!dispatches) continue
    assert.equal(novelEffect(tool.name, { action: 'delete' }), 'write',
      `${tool.name} dispatches on action, so it must not be classified as a whole`)
  }
  assert.equal(novelEffect('novel_model_profiles', { action: 'delete', profile_id: 'x' }), 'write')
  assert.equal(novelEffect('novel_model_profiles', { action: 'save_routes' }), 'write')
  assert.equal(novelEffect('novel_embedding_profiles', { action: 'delete', profile_id: 'x' }), 'write')
  assert.equal(novelEffect('novel_model_profiles', { action: 'list' }), 'read')
  assert.equal(novelEffect('novel_embedding_profiles', { action: 'test' }), 'read')
  assert.equal(novelEffect('novel_write_chapter', {dry_run: true}), 'read')
  assert.equal(novelEffect('novel_write_chapter', {dry_run: 'true'}), 'generate')
  assert.equal(novelEffect('novel_manuscript_acceptance', {}), 'read')
  assert.equal(novelEffect('novel_export', { action: 'preflight' }), 'read')
  assert.equal(novelEffect('novel_export', { action: 'export' }), 'write')
  assert.equal(novelEffect('novel_task', { action: 'retry' }), 'generate')
  assert.equal(novelEffect('novel_task', { action: 'cancel' }), 'write')
  assert.equal(novelEffect('novel_task', { action: 'get', task_id: 'tsk_1' }), 'read')
  assert.equal(novelEffect('novel_writing_assets', { action: 'get' }), 'read')
  assert.equal(novelEffect('novel_writing_assets', { action: 'save' }), 'write')
  assert.equal(novelEffect('novel_manuscript_metrics', {}), 'read')
  assert.equal(novelEffect('novel_outline_audit', {}), 'read')
  assert.equal(novelEffect('novel_drift_entry', {}), 'write')
  assert.equal(novelEffect('novel_arc_reconcile', {}), 'write')
  assert.equal(novelEffect('novel_manuscript_edit_action', { action: 'drafts' }), 'read')
  assert.equal(novelEffect('novel_manuscript_edit_action', { action: 'restore_draft' }), 'write')
})

test('host write policy and plan state independently gate generation and changes', () => {
  for (const mode of ['read-only', 'workspace-write']) for (const active of [true, false]) {
    const ctx = { get: name => name === 'sandboxPolicy' ? { resolve: () => ({ mode }) } : undefined }
    const agent = { ctx: { get: () => ({ get: () => ({ active }) }) }, session: {} }
    const denied = mode === 'read-only' || active
    for (const name of ['novel_doc', 'novel_write_chapter', 'novel_revision']) {
      assert.equal(Boolean(novelPolicyDenial(ctx, { name, agent, arguments: {} })), denied)
    }
    assert.equal(novelPolicyDenial(ctx, { name: 'novel_doc', agent, arguments: { action: 'read' } }), undefined)
    assert.equal(Boolean(novelPolicyDenial(ctx, { name: 'novel_doc', agent, arguments: { action: 'write' } })), denied)
  }
  assert.match(novelPolicyDenial({ get: () => undefined }, { name: 'novel_doc', arguments: { action: 'write' } }), /POLICY_REQUIRED/)
  assert.match(novelPolicyDenial({ get: () => undefined }, { name: 'novel_doc', agent: { ctx: { get: () => undefined }, session: {} }, arguments: { action: 'write' } }), /READ_ONLY/)
})

test('real dsh tool registry isolates the merged tool set by preset and disposes them', async () => {
  const { Context } = await import('@deepseek-ai/cordis')
  const { ToolRuntime } = await import('@deepseek-ai/dsh-tools')
  const { createScope } = await import('@deepseek-ai/dsh-scope')
  const preset = await import('../lib/preset-tools.js')
  const root = new Context()
  let wireSchemas
  const sections = []
  root.provide('systemPrompt', { tools: provider => { wireSchemas = provider; return () => {} }, section: value => { sections.push(value); return () => {} }, getSectionOrder: () => 0 })
  root.provide('novelDomain', { toolOptions: { timeoutMs: 600_000 }, clientFactory: () => () => { throw new Error('No backend calls in catalog inspection') } })
  await root.plugin(ToolRuntime)
  const writing = {}, normal = {}
  const scope = createScope(root, writing)
  try {
    await scope.ctx.plugin(preset)
    assert.equal(root.tools.schemas().filter(tool => tool.name.startsWith('novel_')).length, 0)
    assert.equal(root.tools.schemas(normal).filter(tool => tool.name.startsWith('novel_')).length, 0)
    Object.assign(writing, { ctx: scope.ctx, session: {} })
    const denied = await root.tools.execute({ callId: 'policy-denied', name: 'novel_doc', arguments: { action: 'write' }, agent: writing, signal: new AbortController().signal })
    assert.equal(denied.isError, true)
    assert.match(JSON.stringify(denied), /OPENWRITE_READ_ONLY/)
    const tools = root.tools.schemas(writing)
    assert.equal(tools.filter(tool => tool.name.startsWith('novel_')).length, 56)
    console.log(JSON.stringify({ measurement: 'native-tool-schema', tools: tools.length, utf8Bytes: Buffer.byteLength(JSON.stringify(tools)), tokenizer: 'not-measured' }))
    root.provide('codeRuntime', { language: 'typescript' })
    const ptcAgent = {}
    const ptcScope = createScope(root, ptcAgent)
    try {
      await ptcScope.ctx.plugin(preset, { presentation: 'ptc' })
      assert.deepEqual(wireSchemas({ scope: ptcAgent }).schemas.map(tool => tool.name), ['run_code'])
      assert.equal(root.tools.schemas(writing).length, 56, 'PTC must not change another preset')
      const sdk = sections.find(value => value.name === 'tools:sdk').text({ scope: ptcAgent })
      // The merged document tool: the assertion used to name the pre-merge
      // `novel_doc_read`, which only appeared because the tool descriptions
      // still instructed the old name (fixed in the same change).
      assert.ok(sdk.includes('novel_doc'), `tools:sdk section must list the merged document tool:\n${sdk.slice(0, 400)}`)
      console.log(JSON.stringify({ measurement: 'ptc-presentation', schemaBytes: Buffer.byteLength(JSON.stringify(wireSchemas({ scope: ptcAgent }).schemas)), sdkBytes: Buffer.byteLength(sdk), tokenizer: 'not-measured' }))
    } finally { await ptcScope.dispose() }
    await scope.dispose()
    assert.equal(root.tools.schemas(writing).length, 0)
  } finally { await root.fiber.dispose() }
})

test('workspace context fails closed for missing, relative, and unknown roots', async () => {
  const exec = header => workspaceContextFromExec({ name: 'novel_doc_read', callId: 'c1', agent: { session: { header } } })
  assert.throws(() => exec({}), error => error.code === 'WORKSPACE_CONTEXT_MISSING')
  assert.throws(() => exec({ cwd: '' }), error => error.code === 'WORKSPACE_CONTEXT_MISSING')
  assert.throws(() => exec({ cwd: 'relative/path' }), error => error.code === 'WORKSPACE_ROOT_INVALID' && error.details.reason === 'not_absolute')
  assert.throws(() => exec({ cwd: '/definitely-not-an-openwrite-workspace-root' }), error => error.code === 'WORKSPACE_ROOT_INVALID' && error.details.reason === 'not_found')
})

test('stale revision is returned as CONFLICT and does not look like success', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'openwrite-policy-ws-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ error: 'revision changed', code: 'CONFLICT' }), {
    status: 409, headers: { 'content-type': 'application/json' },
  }))
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: workspace })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { timeoutMs: 1_000, outputDir: join(workspace, 'out') })
  const exec = { signal: new AbortController().signal, name: 'novel_outline_edit', callId: 'c1', agent: { session: { header: { cwd: workspace } } } }
  await assert.rejects(
    () => tools.find(tool => tool.name === 'novel_outline_edit').execute({ operation: 'rename', revision: 'stale-rev' }, exec),
    error => error instanceof StudioError && error.status === 409 && error.code === 'CONFLICT',
  )
})

test('saved drafts can be listed and explicitly restored through the existing editing tool', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'openwrite-drafts-ws-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, init = {}) => {
    requests.push({ path: new URL(url).pathname, method: init.method, body: init.body && JSON.parse(init.body) })
    return new Response(JSON.stringify({ ok: true, data: { drafts: [], requires_reconcile: true } }), {
      status: 200, headers: { 'content-type': 'application/json' },
    })
  })
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: workspace })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { timeoutMs: 1_000, outputDir: join(workspace, 'out') })
  const tool = tools.find(tool => tool.name === 'novel_manuscript_edit_action')
  const exec = { signal: new AbortController().signal, name: tool.name, callId: 'drafts', agent: { session: { header: { cwd: workspace } } } }
  await tool.execute({ action: 'drafts' }, exec)
  await tool.execute({ action: 'restore_draft', run_id_v2: 'runv2_saved', revision: 'sha256:current', confirm: true }, exec)
  assert.equal(requests[0].path, '/api/manuscript/drafts')
  assert.equal(requests[0].method, 'GET')
  assert.deepEqual(requests[1], { path: '/api/manuscript/drafts/restore', method: 'POST', body: {
    run_id_v2: 'runv2_saved', expected_revision: 'sha256:current', confirm: true,
  } })
})

test('root identity handles Windows casing and rejects a successful response from another project', async t => {
  assert.equal(workspaceRootsEqual('C:\\Books\\小说', 'c:/books/小说/', 'win32'), true)
  assert.equal(workspaceRootsEqual('C:\\Books\\A', 'C:\\Books\\B', 'win32'), false)
  const workspace = await mkdtemp(join(tmpdir(), 'openwrite-identity-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ private: 'another project' }), {
    headers: { 'X-OpenWrite-Project-Path': encodeURIComponent(workspace + '-other'), 'content-type': 'application/json' },
  }))
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: workspace })
  await assert.rejects(() => client.getJson('/status'), error => error instanceof StudioError && error.code === 'WORKSPACE_CONTEXT_MISMATCH')
})

test('unlocked document writes and half-specified restores are rejected before any request', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'openwrite-guards-ws-'))
  t.after(() => rm(workspace, { recursive: true, force: true }))
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, init = {}) => {
    requests.push({ path: new URL(url).pathname, method: init.method })
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: workspace })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { timeoutMs: 1_000, outputDir: join(workspace, 'out') })
  const byName = new Map(tools.map(tool => [tool.name, tool]))
  const exec = { signal: new AbortController().signal, name: 'guards', callId: 'guards', agent: { session: { header: { cwd: workspace } } } }

  // The server CAS-checks a document only when `version` is present, so omitting
  // it is an unlocked last-write-wins overwrite. `force` is the explicit bypass.
  await assert.rejects(() => byName.get('novel_doc').execute({ action: 'write', path: 'a.md', content: 'x' }, exec),
    /version is required for novel_doc\(action="write"\)/)
  await byName.get('novel_doc').execute({ action: 'write', path: 'a.md', content: 'x', force: true }, exec)
  assert.equal(requests.at(-1)?.path, '/api/document')

  // A blank expected_revision does not mean "no guard": the server computes
  // `expected = ""` for an absent chapter, so `'' != ''` is false and the check
  // is silently satisfied. `confirm: false` only guarantees CONFIRMATION_REQUIRED.
  await assert.rejects(() => byName.get('novel_manuscript_edit_action').execute(
    { action: 'restore_draft', run_id_v2: 'r1' }, exec), /revision is required for novel_manuscript_edit_action/)
  await assert.rejects(() => byName.get('novel_manuscript_edit_action').execute(
    { action: 'restore_draft', run_id_v2: 'r1', revision: 'sha256:x' }, exec), /confirm: true is required/)

  // An empty quote selects content[0:0], which trivially matches, so the server
  // would persist a junk annotation and consume the chapter revision.
  await assert.rejects(() => byName.get('novel_manuscript_edit_action').execute(
    { action: 'annotate', chapter_id: 'ch_0001', revision: 'r' }, exec), /quote is required/)
  await assert.rejects(() => byName.get('novel_manuscript_edit_action').execute(
    { action: 'annotate', chapter_id: 'ch_0001', revision: 'r', quote: 'q' }, exec), /note is required/)
})

test('a local-writing action is never marked concurrency-safe', async () => {
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => { throw new Error('No API call allowed') }, { timeoutMs: 1000, outputDir: '/unused' })
  // `export` writes a non-atomic file to a fixed name; two concurrent exports
  // return the same path and truncate each other. Only the server-side
  // read-only `preview` may be marked safe.
  const package_ = tools.find(tool => tool.name === 'novel_assets_package')
  assert.equal(package_.isConcurrencySafe({ action: 'export' }), false)
  assert.equal(package_.isConcurrencySafe({ action: 'preview' }), true)
  const exportTool = tools.find(tool => tool.name === 'novel_export')
  assert.equal(exportTool.isConcurrencySafe({ action: 'export' }), false)
})

test('a timeout is distinguishable from an unreachable backend, and an oversize download is refused', async t => {
  const server = createServer((req, res) => {
    if (req.url === '/api/slow') { setTimeout(() => { res.writeHead(200, { 'content-type': 'application/json' }); res.end('{"ok":true}') }, 400); return }
    if (req.url === '/api/big') { res.writeHead(200, { 'content-length': String(300 * 1024 * 1024) }); res.end('x'); return }
    res.writeHead(404, { 'content-type': 'application/json' }); res.end('{"error":"nope"}')
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  const port = typeof address === 'object' && address !== null ? address.port : 0
  const base = `http://127.0.0.1:${port}`
  t.after(() => server.close())

  // Both are ambiguous about whether the server applied a write, but only the
  // timeout carries that meaning; collapsing them makes an agent retry blind.
  const timedOut = await new StudioClient({ baseUrl: base, timeoutMs: 100 })
    .getJson('/api/slow', {}, undefined).catch(cause => cause)
  assert.equal(timedOut.code, 'REQUEST_TIMEOUT')

  // A declared oversize download must be refused, not buffered into the host.
  const tooLarge = await new StudioClient({ baseUrl: base, timeoutMs: 5_000 })
    .download('/api/big', {}, undefined).catch(cause => cause)
  assert.equal(tooLarge.code, 'DOWNLOAD_TOO_LARGE')
  assert.equal(tooLarge.status, 502)
})

test('a vanished workspace root is a 400, not a transport failure', async t => {
  const workspace = await mkdtemp(join(tmpdir(), 'openwrite-root-ws-'))
  const header = encodeURIComponent(workspace)
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ ok: true }), {
    status: 200, headers: { 'X-OpenWrite-Project-Path': header, 'content-type': 'application/json' },
  }))
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 })
    .scoped({ workspaceRoot: join(workspace, 'does-not-exist') })
  const error = await client.getJson('/status', {}, undefined).catch(cause => cause)
  assert.ok(error instanceof StudioError)
  // Previously realpathSync's ENOENT was rewritten to NETWORK_ERROR, which also
  // wrote a diagnostic blaming the transport.
  assert.equal(error.code, 'WORKSPACE_ROOT_INVALID')
  assert.equal(error.status, 400)
})
