import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import * as React from 'react'
import * as JsxRuntime from 'react/jsx-runtime'

const root = fileURLToPath(new URL('..', import.meta.url))
const host = await import(`${root}lib/index.js`)
assert.equal(host.name, '@dsh-novel/studio-panel')
assert.equal(host.VENDOR_ROUTE, '/studio-panel/vendor/vditor')

const routes = []
host.apply({ inject(services, callback) {
  assert.deepEqual(services, ['webServer'])
  callback({
    effect(run) { run() },
    webServer: { register(route) { routes.push(route); return () => {} } },
  })
} })
assert.equal(routes.length, 1, 'panel host owns only packaged editor assets')
assert.deepEqual({ kind: routes[0].kind, path: routes[0].path }, { kind: 'prefix', path: host.VENDOR_ROUTE })

function capture() {
  return {
    status: 0, headers: {}, body: Buffer.alloc(0),
    writeHead(status, headers) { this.status = status; Object.assign(this.headers, headers ?? {}) },
    end(body) { this.body = Buffer.from(body ?? '') },
  }
}

{
  const css = capture()
  await routes[0].handler({ method: 'GET', url: `${host.VENDOR_ROUTE}/dist/index.css` }, css)
  assert.equal(css.status, 200)
  assert.match(css.headers['content-type'], /text\/css/)
  assert.ok(css.body.length > 1000)
  const denied = capture()
  await routes[0].handler({ method: 'POST', url: `${host.VENDOR_ROUTE}/dist/index.css` }, denied)
  assert.equal(denied.status, 405)
  const traversal = capture()
  await routes[0].handler({ method: 'GET', url: `${host.VENDOR_ROUTE}/../../package.json` }, traversal)
  assert.equal(traversal.status, 404)
}

const bundle = await readFile(`${root}lib/client.js`, 'utf8')
assert.match(bundle, /__ModuleLoader__\.load\(\{[\s\S]*id: "@dsh-novel\/studio-panel"/)
assert.ok(bundle.includes('dsh-vditor-runtime.mjs') && bundle.includes('vditorModule.exports'), 'Vditor runtime is bundled into the plugin client')
assert.ok(bundle.includes('/studio-panel/vendor/vditor') && bundle.includes('lute/lute.min.js'), 'Vditor auxiliary assets use the packaged same-origin route')
const clientFiles = (await readdir(`${root}src/client`, { recursive: true }))
  .filter(file => /\.(?:ts|tsx)$/.test(file))
const clientSource = (await Promise.all(clientFiles.map(file => readFile(`${root}src/client/${file}`, 'utf8')))).join('\n')
assert.equal(/createElement\(["']iframe["']\)|<iframe/i.test(clientSource), false, 'default client source contains no iframe')

const PLATFORM_MODULES = new Set([
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client', '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-ui-slots', '@deepseek-ai/dsh-client-web-react',
  '@deepseek-ai/dsh-client-ui-primitives', '@deepseek-ai/dsh-client-ui-attachment',
  '@deepseek-ai/dsh-client-schema-form', '@deepseek-ai/dsh-client-runtime/client',
])
for (const match of bundle.matchAll(/(?<!\.)\brequire\("([^"]+)"\)/g)) {
  assert.ok(PLATFORM_MODULES.has(match[1]), `non-platform external: ${match[1]}`)
}

let loaded = null
const fakeWindow = Object.create(globalThis)
fakeWindow.__ModuleLoader__ = { load(entry) { loaded = entry } }
globalThis.window = fakeWindow
let exports_
try {
  new Function(bundle)()
  assert.ok(loaded)
  exports_ = loaded.factory(specifier => {
    if (specifier === 'react') return React
    if (specifier === 'react/jsx-runtime') return JsxRuntime
    return {}
  })
} finally {
  delete globalThis.window
}
assert.deepEqual(exports_.inject, ['slots', 'locale', 'conversationEvents', 'workspaces', 'sessions'])

const registrations = []
const dictionaries = []
let definition = null
const fakeClientCtx = {
  effect(run) { run() },
  conversationEvents: { register(value) { definition = value; return () => {} } },
  workspaces: { marker: 'workspaces' },
  sessions: { marker: 'sessions' },
  locale: {
    register(ns, dicts) { dictionaries.push({ ns, dicts }); return () => {} },
    bind: () => key => key,
  },
  slots: {
    inject(_name, callback) {
      const produced = callback()
      if (produced !== null && typeof produced === 'object' && Symbol.iterator in produced) {
        for (const _ of produced) { /* register side effects */ }
      }
    },
    register(options, component) { registrations.push({ options, component }); return () => {} },
  },
}
exports_.apply(fakeClientCtx)
assert.equal(dictionaries.length, 1)
assert.equal(dictionaries[0].dicts.zh['view.creation'], '创作')
assert.equal(dictionaries[0].dicts.zh['view.library'], '资料')
assert.equal(dictionaries[0].dicts.zh['view.operations'], '任务')
assert.equal(definition.kind, 'dsh-novel-mutations')

const views = registrations.filter(entry => entry.options.name === 'conversation.view')
assert.deepEqual(views.map(entry => [entry.options.id, entry.options.order]), [
  ['creation', 22], ['library', 23], ['tasks', 24],
])
for (const view of views) {
  const injected = view.options.inject()
  assert.equal(typeof injected.fetchStudioApi, 'function')
  assert.equal(typeof injected.postStudioApi, 'function')
  assert.equal(typeof injected.putStudioApi, 'function')
  assert.equal(injected.workspaces?.marker, 'workspaces')
  assert.equal(injected.sessions?.marker, 'sessions')
}

assert.equal(registrations.filter(entry => entry.options.name === 'conversation.session.header.actions').length, 1)
assert.equal(registrations.filter(entry => entry.options.name === 'conversation.session.header.utilities').length, 1)
assert.equal(registrations.filter(entry => entry.options.name === 'conversation.input.left').length, 1)
assert.equal(registrations.filter(entry => entry.options.name === 'conversation.chat.turnTail').length, 1)

const toolKeys = registrations.filter(entry => entry.options.name === 'tool.call.toolview').map(entry => entry.options.key)
for (const key of ['novel_review_chapter', 'novel_status', 'novel_context_preview', 'novel_doc_write', 'novel_revision_apply', 'novel_tasks_list', 'novel_search', 'novel_asset_update', 'novel_outline_edit']) {
  assert.ok(toolKeys.includes(key), `${key} has a native tool card`)
}
assert.ok(toolKeys.length >= 30, 'common novel tools use family cards')

console.log('studio-panel smoke ok:', { views: views.length, toolCards: toolKeys.length, native: true })
