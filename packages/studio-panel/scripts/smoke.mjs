/**
 * studio-panel smoke: no servers, no browser. Asserts
 *  1. host apply() registers the config route and the read-only API proxy
 *     route via ctx.inject(['webServer']);
 *  2. the proxy handler forwards multi-segment paths + query strings to
 *     `${studioUrl}/api/<path...>`, passes through upstream status/body,
 *     answers 405 for non-GET and 502 when Studio is down;
 *  3. the client bundle (lib/client.js) performs the __ModuleLoader__ handoff
 *     and exports { apply, inject: ['slots', 'locale'] }.
 * Run: npm run smoke
 */
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))

// --- 1+2: host half ----------------------------------------------------------

const host = await import(`${root}lib/index.js`)
assert.equal(host.name, '@dsh-novel/studio-panel')
assert.equal(host.CONFIG_ROUTE, '/studio-panel/config.json')
assert.equal(host.API_PROXY_ROUTE, '/studio-panel/api')
assert.equal(typeof host.apply, 'function')

const config = host.Config({})
assert.equal(config.studioUrl, 'http://127.0.0.1:4567', 'schema default')

// Fake cordis ctx: capture the webServer-gated effect registrations.
const routes = []
const fakeWebCtx = {
  effect(register) { register() },
  webServer: {
    register(route) { routes.push(route); return () => {} },
  },
}
const fakeCtx = {
  inject(services, cb) {
    assert.deepEqual(services, ['webServer'])
    cb(fakeWebCtx)
  },
}
host.apply(fakeCtx, config)

assert.equal(routes.length, 2, 'two routes registered')
const [configRoute, proxyRoute] = routes
assert.deepEqual({ kind: configRoute.kind, path: configRoute.path }, { kind: 'exact', path: '/studio-panel/config.json' })
assert.deepEqual({ kind: proxyRoute.kind, path: proxyRoute.path }, { kind: 'prefix', path: '/studio-panel/api' })

// Fake req/res pair capturing status/headers/body.
function capture() {
  return {
    status: 0,
    headers: {},
    body: '',
    writeHead(status, headers) { this.status = status; Object.assign(this.headers, headers ?? {}) },
    end(body) { this.body = body ?? '' },
  }
}

// Config route: GET serves the resolved studioUrl; POST is 405.
{
  const res = capture()
  await configRoute.handler({ method: 'GET' }, res)
  assert.equal(res.status, 200)
  assert.deepEqual(JSON.parse(res.body), { studioUrl: 'http://127.0.0.1:4567' })
  const denied = capture()
  await configRoute.handler({ method: 'POST' }, denied)
  assert.equal(denied.status, 405)
}

// Proxy route: stub the upstream fetch and assert forwarding semantics.
const realFetch = globalThis.fetch
try {
  let seenUrl = ''
  let seenOptions = {}
  globalThis.fetch = async (url, options) => {
    seenUrl = String(url)
    seenOptions = options ?? {}
    return new Response('{"roots":[]}', { status: 200, headers: { 'content-type': 'application/json' } })
  }
  const res = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/assets?kind=character' }, res)
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/assets?kind=character', 'path+query forward verbatim')
  assert.equal(res.status, 200, 'status passthrough')
  assert.equal(res.headers['content-type'], 'application/json')
  assert.equal(res.body, '{"roots":[]}', 'body passthrough')
  assert.equal(seenOptions.method ?? 'GET', 'GET', 'GET forwards as GET')

  // Multi-segment path.
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/assets/character/hero_01' }, capture())
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/assets/character/hero_01', 'multi-segment path')

  // Allowlisted write: POST /studio-panel/api/assets/update forwards method,
  // verbatim JSON body, and the Studio write header.
  const writeBody = '{"kind":"character","id":"hero_01","revision":"sha256:x","data":{"summary":"新摘要"}}'
  const writeReq = {
    method: 'POST',
    url: '/studio-panel/api/assets/update',
    async *[Symbol.asyncIterator]() { yield Buffer.from(writeBody) },
  }
  const writeRes = capture()
  await proxyRoute.handler(writeReq, writeRes)
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/assets/update')
  assert.equal(seenOptions.method, 'POST')
  assert.equal(Buffer.from(seenOptions.body).toString('utf8'), writeBody, 'body verbatim')
  assert.equal(seenOptions.headers['x-openwrite-studio'], '1', 'Studio write header injected')
  assert.equal(seenOptions.headers['content-type'], 'application/json')
  assert.equal(writeRes.status, 200, 'write status passthrough')

  // PUT on an allowlisted path also forwards.
  await proxyRoute.handler({ ...writeReq, method: 'PUT', url: '/studio-panel/api/assets' }, capture())
  assert.equal(seenOptions.method, 'PUT')

  // Upstream error status/body pass through untouched.
  globalThis.fetch = async () => new Response('{"error":"nope","code":"X"}', { status: 409 })
  const conflict = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/outline' }, conflict)
  assert.equal(conflict.status, 409)
  assert.equal(conflict.body, '{"error":"nope","code":"X"}')
  // …including on writes (the optimistic-locking conflict the editor surfaces).
  const writeConflict = capture()
  await proxyRoute.handler(writeReq, writeConflict)
  assert.equal(writeConflict.status, 409, 'write conflict passthrough')

  // Non-allowlisted write path is refused; DELETE is refused; bare prefix is 404; dead upstream is 502.
  const deniedWrite = capture()
  await proxyRoute.handler({ ...writeReq, url: '/studio-panel/api/write' }, deniedWrite)
  assert.equal(deniedWrite.status, 405, 'non-allowlisted write refused')
  assert.match(JSON.parse(deniedWrite.body).error, /not allowlisted/)
  const deniedDelete = capture()
  await proxyRoute.handler({ method: 'DELETE', url: '/studio-panel/api/assets' }, deniedDelete)
  assert.equal(deniedDelete.status, 405, 'DELETE refused')
  const bare = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api' }, bare)
  assert.equal(bare.status, 404)
  globalThis.fetch = async () => { throw new Error('connect ECONNREFUSED') }
  const down = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/outline' }, down)
  assert.equal(down.status, 502)
  assert.match(JSON.parse(down.body).error, /ECONNREFUSED/)
} finally {
  globalThis.fetch = realFetch
}

// --- 3: client bundle handoff ------------------------------------------------

const bundle = await readFile(`${root}lib/client.js`, 'utf8')
assert.match(bundle, /__ModuleLoader__\.load\(\{[\s\S]*id: "@dsh-novel\/studio-panel"/, 'loader handoff banner')
// The purity contract: only platform-seeded externals may be require()d.
const PLATFORM_MODULES = new Set([
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client', '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-ui-slots', '@deepseek-ai/dsh-client-web-react',
  '@deepseek-ai/dsh-client-ui-primitives', '@deepseek-ai/dsh-client-ui-attachment',
  '@deepseek-ai/dsh-client-schema-form', '@deepseek-ai/dsh-client-runtime/client',
])
const externals = [...bundle.matchAll(/require\("([^"]+)"\)/g)].map(match => match[1])
for (const specifier of externals) {
  assert.ok(PLATFORM_MODULES.has(specifier), `non-platform external: ${specifier}`)
}
assert.ok(externals.includes('@deepseek-ai/dsh-client-ui-primitives'), 'MarkdownText platform import present')
// Inline-markdown normalization and field-row alignment ship in the inlined CSS.
assert.ok(bundle.includes('mdInline>div{font:inherit'), 'mdInline font normalization present')
assert.ok(bundle.includes('text-align:left'), 'left-aligned field/editor rows present')

let loaded = null
globalThis.window = { __ModuleLoader__: { load(entry) { loaded = entry } } }
try {
  // The bundle is a CJS closure factory; evaluate it with the stubbed loader.
  new Function(bundle)()
} finally {
  delete globalThis.window
}
assert.ok(loaded, 'bundle called __ModuleLoader__.load')
assert.equal(loaded.id, '@dsh-novel/studio-panel')
const exports_ = loaded.factory(() => ({}))
assert.equal(typeof exports_.apply, 'function')
assert.deepEqual(exports_.inject, ['slots', 'locale'])

// Drive apply() with a fake client ctx and capture the slot registrations.
const dictionaries = []
const registrations = []
const fakeClientCtx = {
  effect(run) { run() },
  locale: {
    register(ns, dicts) { dictionaries.push({ ns, dicts }); return () => {} },
    bind: () => (key) => key,
  },
  slots: {
    inject(name, cb) {
      const produced = cb()
      // Multiple registrations arrive as a generator yielding each disposer.
      if (produced !== null && typeof produced === 'object' && Symbol.iterator in produced) {
        for (const _ of produced) { /* drain: registering is the side effect */ }
      }
    },
    register(options, component) {
      registrations.push({ options, component })
      return () => {}
    },
  },
}
exports_.apply(fakeClientCtx)

assert.deepEqual(dictionaries.map(entry => entry.ns), ['studio-panel'])
assert.ok('zh' in dictionaries[0].dicts && 'en' in dictionaries[0].dicts)
assert.equal(dictionaries[0].dicts.zh['view.tasks'], '任务')
assert.equal(dictionaries[0].dicts.en['view.tasks'], 'Tasks')
assert.equal(dictionaries[0].dicts.zh['view.graph'], '图谱')
assert.equal(dictionaries[0].dicts.en['view.graph'], 'Graph')
assert.equal(dictionaries[0].dicts.zh['assets.references'], '参考作品')
assert.equal(dictionaries[0].dicts.en['assets.references'], 'References')
assert.equal(dictionaries[0].dicts.zh['assets.segment.core'], '作品核心')
assert.equal(dictionaries[0].dicts.en['assets.segment.core'], 'Story Core')
assert.equal(dictionaries[0].dicts.zh['assets.segment.references'], '参考作品')
assert.equal(dictionaries[0].dicts.zh['assets.detail.relations'], '关系')
// Editor/create surface keys (the 资产 tab's write UI).
assert.equal(dictionaries[0].dicts.zh['assets.edit.save'], '保存')
assert.equal(dictionaries[0].dicts.en['assets.edit.save'], 'Save')
assert.equal(dictionaries[0].dicts.zh['assets.edit.conflictRefresh'], '刷新重试')
assert.equal(dictionaries[0].dicts.zh['assets.create.open'], '新建')
assert.equal(dictionaries[0].dicts.en['assets.create.open'], 'New')
assert.equal(dictionaries[0].dicts.zh['assets.edit.derivedRelations'].includes('派生关系'), true)
assert.equal(dictionaries[0].dicts.zh['assets.edit.mode.preview'], '预览')
assert.equal(dictionaries[0].dicts.en['assets.edit.mode.preview'], 'Preview')
assert.equal(dictionaries[0].dicts.zh['assets.edit.mode.split'], '分栏')
assert.equal(dictionaries[0].dicts.en['assets.edit.mode.split'], 'Split')
assert.equal(dictionaries[0].dicts.zh['assets.selectHint'].includes('左侧'), true)
assert.equal(dictionaries[0].dicts.zh['assets.detail.index'], '索引')
assert.equal(dictionaries[0].dicts.zh['assets.list.taboos'], '忌讳')
assert.equal(dictionaries[0].dicts.en['assets.list.detail_refs'], 'Detail refs')
// Graph empty states + kind filter labels (component rendering itself needs a
// DOM/React harness — out of scope for this no-server smoke).
assert.equal(dictionaries[0].dicts.zh['graph.empty.foreshadowing'].includes('伏笔'), true)
assert.equal(dictionaries[0].dicts.zh['graph.empty.relationships'].includes('关系'), true)
assert.equal(dictionaries[0].dicts.zh['graph.kind.character'], '角色')
assert.equal(dictionaries[0].dicts.en['graph.kind.faction'], 'Factions')

const views = registrations.filter(entry => entry.options.name === 'conversation.view')
assert.deepEqual(
  views.map(entry => [entry.options.id, entry.options.order]),
  [['studio', 20], ['outline', 21], ['assets', 22], ['tasks', 23], ['graph', 24]],
  'five conversation.view tabs in order',
)
for (const view of views) assert.equal(typeof view.component, 'function')
const toolviews = registrations.filter(entry => entry.options.name === 'tool.call.toolview')
assert.deepEqual(toolviews.map(entry => entry.options.key), ['novel_review_chapter'])
// Locale label thunks resolve through the bound namespace.
assert.equal(views[3].options.label(), 'view.tasks', 'tasks label thunk reads view.tasks')

console.log('studio-panel smoke: all assertions passed')
