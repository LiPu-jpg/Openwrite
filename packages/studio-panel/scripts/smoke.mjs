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
  assert.equal(res.body.toString('utf8'), '{"roots":[]}', 'body passthrough (binary-safe bytes)')
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

  // The structural outline editor rides the same allowlist: POST
  // /studio-panel/api/outline/edit forwards the revision-guarded payload.
  const outlineBody = '{"operation":"rename","node_id":"ch_009","revision":"rev-1","title":"第9章：新标题"}'
  const outlineReq = {
    method: 'POST',
    url: '/studio-panel/api/outline/edit',
    async *[Symbol.asyncIterator]() { yield Buffer.from(outlineBody) },
  }
  const outlineRes = capture()
  await proxyRoute.handler(outlineReq, outlineRes)
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/outline/edit', 'outline edit forwarded')
  assert.equal(Buffer.from(seenOptions.body).toString('utf8'), outlineBody, 'outline body verbatim')

  // Pattern-allowlisted task lifecycle actions: POST tasks/{id}/cancel|retry.
  const taskReq = {
    method: 'POST',
    url: '/studio-panel/api/tasks/tsk_20260822023413_0d18e7bcb0/cancel',
    async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
  }
  const taskRes = capture()
  await proxyRoute.handler(taskReq, taskRes)
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/tasks/tsk_20260822023413_0d18e7bcb0/cancel', 'task cancel forwarded')
  const taskRetry = capture()
  await proxyRoute.handler({ ...taskReq, url: '/studio-panel/api/tasks/tsk_x/retry' }, taskRetry)
  assert.equal(seenUrl.endsWith('/retry'), true, 'task retry forwarded')
  // 但未列入模式的写路径依旧拒绝
  const deniedTask = capture()
  await proxyRoute.handler({ ...taskReq, url: '/studio-panel/api/tasks/tsk_x/delete' }, deniedTask)
  assert.equal(deniedTask.status, 405, 'non-pattern task write refused')

  // Upstream error status/body pass through untouched.
  globalThis.fetch = async () => new Response('{"error":"nope","code":"X"}', { status: 409 })
  const conflict = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/outline' }, conflict)
  assert.equal(conflict.status, 409)
  assert.equal(conflict.body.toString('utf8'), '{"error":"nope","code":"X"}')
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
// Vditor loads via <script> tag from the Studio origin — never bundled/required.
assert.ok(bundle.includes('/vendor/vditor/dist/index.min.js'), 'Vditor runtime URL present')
assert.ok(!externals.some(specifier => specifier.toLowerCase().includes('vditor')), 'Vditor is not a module import')

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
assert.equal(dictionaries[0].dicts.zh['view.research'], '研究')
assert.equal(dictionaries[0].dicts.en['view.research'], 'Research')
assert.equal(dictionaries[0].dicts.zh['view.search'], '搜索')
assert.equal(dictionaries[0].dicts.en['view.search'], 'Search')
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
// Body edit is Vditor IR only — the mode chips are gone, the keys with them.
assert.equal(dictionaries[0].dicts.zh['assets.edit.mode.preview'], undefined)
assert.equal(dictionaries[0].dicts.zh['assets.edit.mode.live'], undefined)
// Localized field labels + hidden-field handling.
assert.equal(dictionaries[0].dicts.zh['assets.field.tier'], '位阶')
assert.equal(dictionaries[0].dicts.en['assets.field.tier'], 'Tier')
assert.equal(dictionaries[0].dicts.zh['assets.field.current_state'], '当前状态')
assert.equal(dictionaries[0].dicts.zh['assets.edit.optional'], '选填')
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
// Graph continuity sections (伏笔校验/事实账本/工作流) + research/search keys.
assert.equal(dictionaries[0].dicts.zh['graph.truth'], '事实账本')
assert.equal(dictionaries[0].dicts.en['graph.truth'], 'Truth ledger')
assert.equal(dictionaries[0].dicts.zh['graph.workflows'], '工作流')
assert.equal(dictionaries[0].dicts.zh['graph.truth.ledger'], '资源账本')
assert.equal(dictionaries[0].dicts.en['graph.empty.workflows'], 'No active chapter workflows.')
assert.equal(dictionaries[0].dicts.zh['research.selectHint'].includes('报告'), true)
assert.equal(dictionaries[0].dicts.en['research.report.loading'], 'Loading report…')
assert.equal(dictionaries[0].dicts.zh['search.scope.chapters'], '正文')
assert.equal(dictionaries[0].dicts.en['search.scope.sources'], 'Sources')
assert.equal(dictionaries[0].dicts.zh['search.indexed'], '已索引')

const views = registrations.filter(entry => entry.options.name === 'conversation.view')
assert.deepEqual(
  views.map(entry => [entry.options.id, entry.options.order]),
  [['overview', 19], ['outline', 22], ['assets', 23], ['tasks', 24], ['graph', 25], ['research', 26], ['search', 27]],
  'ten conversation.view tabs in order (总览/正文 merged into one)',
)
// The merged 总览 tab carries the full API face (toolbox) with no hash pin;
// the review workbench keeps its '#review' pin.
const injected = Object.fromEntries(views.map(entry => [entry.options.id, entry.options.inject()]))
assert.equal(injected['overview'].view, undefined)
assert.equal(typeof injected['overview'].postStudioApi, 'function', 'overview toolbox API face')
for (const view of views) assert.equal(typeof view.component, 'function')
const toolviews = registrations.filter(entry => entry.options.name === 'tool.call.toolview')
assert.deepEqual(toolviews.map(entry => entry.options.key), ['novel_review_chapter'])
// Locale label thunks resolve through the bound namespace.
const tasksView = views.find(entry => entry.options.id === 'tasks')
assert.equal(tasksView.options.label(), 'view.tasks', 'tasks label thunk reads view.tasks')
const overviewView = views.find(entry => entry.options.id === 'overview')
assert.equal(overviewView.options.label(), 'view.writing', 'merged tab relabeled 写作')

console.log('studio-panel smoke: all assertions passed')
