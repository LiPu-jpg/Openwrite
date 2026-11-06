// Offline regression coverage for plugin reloads and HTTP/filesystem boundaries.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { Context, Service } from '@deepseek-ai/cordis'
import * as plugin from '../lib/index.js'
import { StudioClient } from '../lib/client.js'
import { registerNovelTools } from '../lib/tools.js'

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

class ResponseCapture extends EventEmitter {
  status = 0
  endCount = 0
  chunks = []
  writeHead(status) { this.status = status }
  write(body) {
    assert.equal(this.endCount, 0, 'never write after a response is ended')
    this.chunks.push(String(body))
  }
  end(body) {
    if (body !== undefined) this.write(body)
    this.endCount += 1
    this.emit('close')
  }
}

async function mountHost({ requestRejection = () => undefined } = {}) {
  const routes = new Map()
  class Tools extends Service {
    constructor(ctx) { super(ctx, 'tools') }
    register() {}
  }
  class WebServer extends Service {
    constructor(ctx) { super(ctx, 'webServer') }
    register(route) {
      assert.equal(routes.has(route.path), false, 'reload cannot duplicate a live route')
      routes.set(route.path, route)
      return () => { routes.delete(route.path) }
    }
  }
  class Registry extends Service {
    constructor(ctx) { super(ctx, 'workspaceRegistry') }
    get(id) { return id === 'a' || id === 'b' ? { path: `/novels/${id}` } : undefined }
  }
  const root = new Context()
  root.provide('connection', { requestRejection })
  await root.plugin(Tools)
  const webFork = await root.plugin(WebServer)
  await root.plugin(Registry)
  const fork = await root.plugin(plugin, plugin.Config({}))
  return { root, routes, fork, webFork, WebServer }
}

test('unauthenticated browser and runtime requests never reach the domain', async t => {
  t.mock.method(globalThis, 'fetch', async () => jsonResponse({ ok: true }))
  const host = await mountHost({ requestRejection: () => 401 })
  t.after(() => host.root.fiber.dispose())
  for (const [path, url] of [
    ['/studio-panel/runtime', '/studio-panel/runtime'],
    ['/studio-panel/events', '/studio-panel/events?workspace=a'],
    ['/studio-panel/api', '/studio-panel/api/workspace'],
  ]) {
    const response = new ResponseCapture()
    await host.routes.get(path).handler({ method: 'GET', url, headers: {} }, response)
    assert.equal(response.status, 401, path)
    assert.match(response.chunks.join(''), /authentication required/)
  }
  const unknown = new ResponseCapture()
  const allowed = await mountHost()
  t.after(() => allowed.root.fiber.dispose())
  await allowed.routes.get('/studio-panel/events').handler({ method: 'GET', url: '/studio-panel/events?workspace=forged' }, unknown)
  assert.equal(unknown.status, 400)
  assert.equal(JSON.parse(unknown.chunks[0]).code, 'WORKSPACE_UNKNOWN')
})

test('HTTP errors cannot be unwrapped as success or notify a mutation', async t => {
  let mutations = 0
  const client = new StudioClient({
    baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000,
    onMutation: () => { mutations += 1 },
  })
  t.mock.method(globalThis, 'fetch', async () => jsonResponse({ ok: true, data: { accepted: true } }, 503))
  for (const call of [
    () => client.getJson('/api/workspace'),
    () => client.postJson('/api/tasks', {}),
    () => client.putJson('/api/document', {}),
  ]) {
    await assert.rejects(call, error => error.status === 503 && error.code === 'HTTP_ERROR')
  }
  assert.equal(mutations, 0)
})

test('HTTP success and structured Studio errors retain their existing contracts', async t => {
  let mutations = 0
  const client = new StudioClient({
    baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000,
    onMutation: () => { mutations += 1 },
  })
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => jsonResponse({ ok: true, data: { accepted: true } }))
  assert.deepEqual(await client.postJson('/api/tasks', {}), { accepted: true })
  assert.equal(mutations, 1)
  fetchMock.mock.mockImplementation(async () => jsonResponse({ error: 'version changed', code: 'CONFLICT', details: { version: 2 } }, 409))
  await assert.rejects(() => client.putJson('/api/document', {}), error => {
    assert.equal(error.status, 409)
    assert.equal(error.code, 'CONFLICT')
    assert.deepEqual(error.details, { version: 2 })
    return true
  })
  assert.equal(mutations, 1)
})

test('Cordis unload ends all SSE responses; reload restores isolated streams', async t => {
  t.mock.method(globalThis, 'fetch', async () => jsonResponse({ context_epoch: 1 }))
  const host = await mountHost()
  t.after(() => host.root.fiber.dispose())
  const oldDomain = host.root.novelDomain
  const a = new ResponseCapture()
  const b = new ResponseCapture()
  const events = host.routes.get('/studio-panel/events')
  await events.handler({ method: 'GET', url: '/studio-panel/events?workspace=a' }, a)
  await events.handler({ method: 'GET', url: '/studio-panel/events?workspace=b' }, b)
  oldDomain.notifyMutation('/api/document', { workspaceRoot: '/novels/a' })
  assert.equal(a.chunks.length, 2)
  assert.equal(b.chunks.length, 1, 'workspace B does not receive A mutations')
  await host.fork.dispose()
  assert.equal(a.endCount, 1)
  assert.equal(b.endCount, 1)
  assert.equal(oldDomain.streams.size, 0)
  assert.equal(host.routes.size, 0)
  oldDomain.notifyMutation('/api/document', { workspaceRoot: '/novels/a' })
  // A disposed stream must not receive further mutations, and must be closed
  // with an explicit 503 naming the reload. Ending it with no status and no
  // body made Node drop the later writeHead/end, so the browser saw an empty
  // 200 and pollInvalidation threw on .json() — flipping the panel offline on a
  // mere plugin reload.
  assert.equal(a.chunks.length, 3, 'disposed streams cannot receive later mutations')
  assert.equal(a.status, 503)
  assert.match(a.chunks[2] ?? '', /NOVEL_DOMAIN_DISPOSED/)

  await host.root.plugin(plugin, plugin.Config({}))
  assert.equal(host.routes.size, 5)
  const fresh = new ResponseCapture()
  await host.routes.get('/studio-panel/events').handler({ method: 'GET', url: '/studio-panel/events?workspace=a' }, fresh)
  host.root.novelDomain.notifyMutation('/api/document', { workspaceRoot: '/novels/a' })
  assert.equal(fresh.chunks.length, 2)
  assert.equal(a.chunks.length, 3, 'the disposed stream stays closed with its shutdown notice')
})

test('webServer dependency replacement also closes the old injection scope', async t => {
  t.mock.method(globalThis, 'fetch', async () => jsonResponse({ context_epoch: 1 }))
  const host = await mountHost()
  t.after(() => host.root.fiber.dispose())
  const domain = host.root.novelDomain
  const old = new ResponseCapture()
  await host.routes.get('/studio-panel/events').handler({ method: 'GET', url: '/studio-panel/events?workspace=a' }, old)
  await host.webFork.dispose()
  assert.equal(old.endCount, 1)
  assert.equal(domain.streams.size, 0)
  assert.equal(host.routes.size, 0)
  await host.root.plugin(host.WebServer)
  assert.equal(host.routes.size, 5)
  const fresh = new ResponseCapture()
  await host.routes.get('/studio-panel/events').handler({ method: 'GET', url: '/studio-panel/events?workspace=a' }, fresh)
  assert.equal(fresh.chunks.length, 1)
  assert.equal(domain.streams.size, 1)
})

test('dispose aborts pending epoch reads and prevents late ready/snapshot responses', async t => {
  const pending = []
  // Deliberately ignore abort until resolved: the late-response barrier must
  // hold even when a transport completes after its lifetime was cancelled.
  t.mock.method(globalThis, 'fetch', (_url, init) => new Promise(resolve => { pending.push({ resolve, signal: init.signal }) }))
  const host = await mountHost()
  t.after(() => host.root.fiber.dispose())
  const domain = host.root.novelDomain
  const events = host.routes.get('/studio-panel/events')
  const snapshot = host.routes.get('/studio-panel/invalidation.json')
  const streamResponse = new ResponseCapture()
  const snapshotResponse = new ResponseCapture()
  const inFlight = [
    events.handler({ method: 'GET', url: '/studio-panel/events?workspace=a' }, streamResponse),
    snapshot.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=a' }, snapshotResponse),
  ]
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(pending.length, 2)
  await host.fork.dispose()
  assert.equal(domain.streams.size, 0)
  for (const response of [streamResponse, snapshotResponse]) assert.equal(response.endCount, 1)
  for (const request of pending) {
    assert.equal(request.signal.aborted, true)
    request.resolve(jsonResponse({ context_epoch: 3 }))
  }
  await Promise.all(inFlight)
  // Both were answered by the dispose cleanup with an explicit 503 naming the
  // reload. Ending them with no status and no body made Node drop the later
  // writeHead/end, so the browser saw an empty 200 and pollInvalidation threw
  // on .json() — flipping the panel offline on a mere plugin reload. The
  // suspended handlers must not add a second status of their own.
  for (const response of [streamResponse, snapshotResponse]) {
    assert.equal(response.status, 503)
    assert.deepEqual(response.chunks, ['{"error":"novel-domain is reloading","code":"NOVEL_DOMAIN_DISPOSED"}'])
  }
  assert.equal(domain.streams.size, 0)
  const stale = new ResponseCapture()
  await events.handler({ method: 'GET', url: '/studio-panel/events?workspace=a' }, stale)
  assert.equal(stale.status, 503)
  assert.equal(JSON.parse(stale.chunks[0]).code, 'NOVEL_DOMAIN_DISPOSED')
  assert.equal(pending.length, 2, 'stale handlers cannot start new upstream requests')
})

test('both export tools reject paths and preserve normal Unicode filenames inside their workspace', async t => {
  const outputDir = await mkdtemp(join(tmpdir(), 'dsh-novel-export-test-'))
  t.after(() => rm(outputDir, { recursive: true, force: true }))
  let filename = ''
  t.mock.method(globalThis, 'fetch', async () => new Response('export fixture', {
    headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` },
  }))
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: '/novels/a' })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { outputDir, timeoutMs: 1_000 })
  const names = [['novel_export', { action: 'export' }], ['novel_assets_package', { action: 'export' }]]
  const exec = { signal: new AbortController().signal }
  const invalid = ['../escape.md', 'nested/export.md', '..\\escape.md', '/tmp/export.md', 'C:\\temp\\export.md', 'C:export.md', '\\\\server\\share\\export.md', '.', '..', ' ', 'bad\u0000.md', 'bad\n.md']
  for (const [name, args] of names) {
    const tool = tools.find(tool => tool.name === name)
    for (filename of invalid) {
      await assert.rejects(() => tool.execute(args, exec), error => {
        assert.equal(error.code, 'INVALID_EXPORT_FILENAME', `${name}: ${JSON.stringify(filename)}`)
        assert.equal(error.status, 502)
        assert.deepEqual(error.details, { reason: 'not_basename' })
        return true
      })
    }
  }
  assert.deepEqual(await readdir(outputDir), [], 'invalid names cannot create directories or files')
  const bucket = createHash('sha256').update('/novels/a').digest('hex').slice(0, 12)
  for (const [name, args] of names) {
    filename = name === 'novel_export' ? '小说·第一卷.md' : '人物设定.owasset.zip'
    const result = await tools.find(tool => tool.name === name).execute(args, exec)
    assert.equal(result.path, join(outputDir, bucket, filename))
    assert.equal(result.filename, filename)
    assert.equal(await readFile(result.path, 'utf8'), 'export fixture')
  }
  filename = 'export.bin'
  for (const [name, fallback] of [['novel_export', 'novel.md'], ['novel_assets_package', 'assets.owasset.zip']]) {
    const result = await tools.find(tool => tool.name === name).execute({ action: 'export' }, exec)
    assert.equal(result.path, join(outputDir, bucket, fallback))
  }

  filename = 'delivery.epub'
  const exportRequests = []
  t.mock.restoreAll()
  t.mock.method(globalThis, 'fetch', async input => {
    exportRequests.push(String(input))
    return new Response('export fixture', {
      headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` },
    })
  })
  await tools.find(tool => tool.name === 'novel_export').execute({
    action: 'export', format: 'epub', purpose: 'delivery', preflight_revision: 'pf_current_123',
  }, exec)
  const requestUrl = new URL(exportRequests[0])
  assert.equal(requestUrl.pathname, '/api/export')
  assert.equal(requestUrl.searchParams.get('format'), 'epub')
  assert.equal(requestUrl.searchParams.get('purpose'), 'delivery')
  assert.equal(requestUrl.searchParams.get('preflight_revision'), 'pf_current_123')
})

test('project archive download stays inside its workspace bucket and uses the exact archive route', async t => {
  const outputDir = await mkdtemp(join(tmpdir(), 'dsh-novel-archive-test-'))
  t.after(() => rm(outputDir, { recursive: true, force: true }))
  const requests = []
  let filename = '完整作品.owarchive.zip'
  t.mock.method(globalThis, 'fetch', async input => {
    requests.push(String(input))
    return new Response('archive fixture', {
      headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` },
    })
  })
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: '/novels/a' })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { outputDir, timeoutMs: 1_000 })
  const tool = tools.find(item => item.name === 'novel_project')
  const archiveId = 'owa_0123456789abcdef01234567'
  const downloadArgs = { action: 'download', archive_id: archiveId }
  const result = await tool.execute(downloadArgs, { signal: new AbortController().signal })
  const bucket = createHash('sha256').update('/novels/a').digest('hex').slice(0, 12)
  assert.equal(result.path, join(outputDir, bucket, filename))
  assert.equal(await readFile(result.path, 'utf8'), 'archive fixture')
  assert.equal(new URL(requests[0]).pathname, `/api/project-archives/${archiveId}/download`)

  filename = '../escape.zip'
  await assert.rejects(() => tool.execute(downloadArgs, { signal: new AbortController().signal }), error => error.code === 'INVALID_EXPORT_FILENAME')
  await assert.rejects(() => tool.execute({ action: 'download', archive_id: '../bad' }, { signal: new AbortController().signal }), /archive_id must match/)
})

test('misconfiguration fails at startup, not at the first request', async t => {
  // Drive the real apply() through the plugin factory so the startup guard runs.
  const { apply } = await import('../lib/index.js')
  const root = new Context()
  root.provide('connection', { requestRejection: () => undefined })
  await root.plugin(class extends Service { constructor(ctx) { super(ctx, 'tools') } register() {} })
  await root.plugin(class extends Service { constructor(ctx) { super(ctx, 'webServer') } register() {} })
  const fakeCtx = { ...root, effect: () => {}, inject: () => {} }
  t.after(() => root.fiber.dispose())
  const base = { mode: 'external', baseUrl: 'http://127.0.0.1:1', authToken: 't', timeoutMs: 1000, outputDir: '/tmp/ow-x' }
  assert.throws(() => apply(fakeCtx, { ...base, timeoutMs: 0 }), /timeoutMs must be a positive number/)
  assert.throws(() => apply(fakeCtx, { ...base, timeoutMs: -1 }), /timeoutMs must be a positive number/)
  assert.throws(() => apply(fakeCtx, { ...base, baseUrl: 'not-a-url' }), /baseUrl must be an http\(s\) URL/)
  assert.throws(() => apply(fakeCtx, { ...base, baseUrl: 'ftp://127.0.0.1' }), /baseUrl must be an http\(s\) URL/)
  // A token is ignored in managed mode — that contradiction must be reported
  // rather than silently dropped.
  assert.throws(() => apply(fakeCtx, { ...base, mode: 'managed', authToken: 't', artifacts: '/nonexistent-artifacts' }),
    /authToken is ignored in managed mode/)
  // A tokenless external server is legitimate, so there is no authToken rule.
  apply(fakeCtx, { ...base, authToken: undefined })
  t.after(() => rm('/tmp/ow-x', { recursive: true, force: true }))
})

test('the config route declares managed mode and the configured URL', async t => {
  const host = await mountHost()
  t.after(() => host.root.fiber.dispose())
  const capture = new ResponseCapture()
  await host.routes.get('/studio-panel/config.json').handler({ method: 'GET', url: '/studio-panel/config.json' }, capture)
  const payload = JSON.parse(capture.chunks.join(''))
  // The route must say which mode it is in: `studioUrl` alone is the configured
  // default (often the never-bound 127.0.0.1:4567), not the managed backend.
  assert.equal(payload.managed, false)
  assert.equal(payload.studioUrl, 'http://127.0.0.1:4567')
})

test('both export tools reject paths and preserve normal Unicode filenames inside their workspace', async t => {
  const outputDir = await mkdtemp(join(tmpdir(), 'dsh-novel-export-test-'))
  t.after(() => rm(outputDir, { recursive: true, force: true }))
  let filename = ''
  t.mock.method(globalThis, 'fetch', async () => new Response('export fixture', {
    headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` },
  }))
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: '/novels/a' })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { outputDir, timeoutMs: 1_000 })
  const names = [['novel_export', { action: 'export' }], ['novel_assets_package', { action: 'export' }]]
  const exec = { signal: new AbortController().signal }
  const invalid = ['../escape.md', 'nested/export.md', '..\\escape.md', '/tmp/export.md', 'C:\\temp\\export.md', 'C:export.md', '\\\\server\\share\\export.md', '.', '..', ' ', 'bad\u0000.md', 'bad\n.md']
  for (const [name, args] of names) {
    const tool = tools.find(tool => tool.name === name)
    for (filename of invalid) {
      await assert.rejects(() => tool.execute(args, exec), error => {
        assert.equal(error.code, 'INVALID_EXPORT_FILENAME', `${name}: ${JSON.stringify(filename)}`)
        assert.equal(error.status, 502)
        assert.deepEqual(error.details, { reason: 'not_basename' })
        return true
      })
    }
  }
  assert.deepEqual(await readdir(outputDir), [], 'invalid names cannot create directories or files')
  const bucket = createHash('sha256').update('/novels/a').digest('hex').slice(0, 12)
  for (const [name, args] of names) {
    filename = name === 'novel_export' ? '小说·第一卷.md' : '人物设定.owasset.zip'
    const result = await tools.find(tool => tool.name === name).execute(args, exec)
    assert.equal(result.path, join(outputDir, bucket, filename))
    assert.equal(result.filename, filename)
    assert.equal(await readFile(result.path, 'utf8'), 'export fixture')
  }
  filename = 'export.bin'
  for (const [name, fallback] of [['novel_export', 'novel.md'], ['novel_assets_package', 'assets.owasset.zip']]) {
    const result = await tools.find(tool => tool.name === name).execute({ action: 'export' }, exec)
    assert.equal(result.path, join(outputDir, bucket, fallback))
  }

  filename = 'delivery.epub'
  const exportRequests = []
  t.mock.restoreAll()
  t.mock.method(globalThis, 'fetch', async input => {
    exportRequests.push(String(input))
    return new Response('export fixture', {
      headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` },
    })
  })
  await tools.find(tool => tool.name === 'novel_export').execute({
    action: 'export', format: 'epub', purpose: 'delivery', preflight_revision: 'pf_current_123',
  }, exec)
  const requestUrl = new URL(exportRequests[0])
  assert.equal(requestUrl.pathname, '/api/export')
  assert.equal(requestUrl.searchParams.get('format'), 'epub')
  assert.equal(requestUrl.searchParams.get('purpose'), 'delivery')
  assert.equal(requestUrl.searchParams.get('preflight_revision'), 'pf_current_123')
})

test('project archive download stays inside its workspace bucket and uses the exact archive route', async t => {
  const outputDir = await mkdtemp(join(tmpdir(), 'dsh-novel-archive-test-'))
  t.after(() => rm(outputDir, { recursive: true, force: true }))
  const requests = []
  let filename = '完整作品.owarchive.zip'
  t.mock.method(globalThis, 'fetch', async input => {
    requests.push(String(input))
    return new Response('archive fixture', {
      headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}` },
    })
  })
  const client = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1_000 }).scoped({ workspaceRoot: '/novels/a' })
  const tools = []
  registerNovelTools({ tools: { register: tool => tools.push(tool) } }, () => client, { outputDir, timeoutMs: 1_000 })
  const tool = tools.find(item => item.name === 'novel_project')
  const archiveId = 'owa_0123456789abcdef01234567'
  const downloadArgs = { action: 'download', archive_id: archiveId }
  const result = await tool.execute(downloadArgs, { signal: new AbortController().signal })
  const bucket = createHash('sha256').update('/novels/a').digest('hex').slice(0, 12)
  assert.equal(result.path, join(outputDir, bucket, filename))
  assert.equal(await readFile(result.path, 'utf8'), 'archive fixture')
  assert.equal(new URL(requests[0]).pathname, `/api/project-archives/${archiveId}/download`)

  filename = '../escape.zip'
  await assert.rejects(() => tool.execute(downloadArgs, { signal: new AbortController().signal }), error => error.code === 'INVALID_EXPORT_FILENAME')
  await assert.rejects(() => tool.execute({ action: 'download', archive_id: '../bad' }, { signal: new AbortController().signal }), /archive_id must match/)
})

