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
  globalThis.fetch = async (url) => {
    seenUrl = String(url)
    return new Response('{"roots":[]}', { status: 200, headers: { 'content-type': 'application/json' } })
  }
  const res = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/assets?kind=character' }, res)
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/assets?kind=character', 'path+query forward verbatim')
  assert.equal(res.status, 200, 'status passthrough')
  assert.equal(res.headers['content-type'], 'application/json')
  assert.equal(res.body, '{"roots":[]}', 'body passthrough')

  // Multi-segment path.
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/assets/character/hero_01' }, capture())
  assert.equal(seenUrl, 'http://127.0.0.1:4567/api/assets/character/hero_01', 'multi-segment path')

  // Upstream error status/body pass through untouched.
  globalThis.fetch = async () => new Response('{"error":"nope","code":"X"}', { status: 409 })
  const conflict = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/outline' }, conflict)
  assert.equal(conflict.status, 409)
  assert.equal(conflict.body, '{"error":"nope","code":"X"}')

  // Non-GET is refused; bare prefix is 404; dead upstream is 502.
  const denied = capture()
  await proxyRoute.handler({ method: 'POST', url: '/studio-panel/api/assets' }, denied)
  assert.equal(denied.status, 405)
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
const externals = [...bundle.matchAll(/require\("([^"]+)"\)/g)].map(match => match[1])
assert.deepEqual([...new Set(externals)].sort(), ['react', 'react/jsx-runtime'], 'platform-only externals')

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
assert.equal(dictionaries[0].dicts.zh['assets.references'], '资料库（参考作品）')
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
