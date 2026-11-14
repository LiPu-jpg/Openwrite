import assert from 'node:assert/strict'
import { readdir, readFile, mkdtemp, rm } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { apply as installReleasePreset } from '../../../plugin.mjs'
import * as React from 'react'
import * as JsxRuntime from 'react/jsx-runtime'
import { normalizeMinimapProperties } from './react-flow-properties.mjs'

const root = fileURLToPath(new URL('..', import.meta.url))
const host = await import(new URL('../lib/index.js', import.meta.url).href)
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
assert.equal(bundle.includes('--xy-minimap-mask-'), false, 'minimap CSS and JS use the same overlay property names')
for (const property of ['background-color', 'stroke-color', 'stroke-width']) {
  assert.ok(bundle.includes(`--xy-minimap-overlay-${property}-default:`), `${property} CSS definition`)
  assert.ok(bundle.includes(`var(--xy-minimap-overlay-${property}-props`), `${property} CSS reference`)
  assert.ok(bundle.includes(`"--xy-minimap-overlay-${property}-props":`), `${property} JS reference`)
}
assert.equal(normalizeMinimapProperties('maskColor sk-example --other-mask-color'), 'maskColor sk-example --other-mask-color', 'only scoped CSS properties may be renamed')
assert.match(bundle, /__ModuleLoader__\.load\(\{[\s\S]*id: "@dsh-novel\/studio-panel"/)
assert.ok(bundle.includes('dsh-vditor-runtime.mjs') && bundle.includes('vditorModule.exports'), 'Vditor runtime is bundled into the plugin client')
assert.ok(bundle.includes('/studio-panel/vendor/vditor') && bundle.includes('lute/lute.min.js'), 'Vditor auxiliary assets use the packaged same-origin route')
// The turn-tail change summary is a single flex row. Without wrapping it, the
// row squeezes its Chinese labels down to one character per line, because CJK
// text has no break opportunities to shrink against.
// The CSS Modules hash is derived from the file path, so it differs per
// checkout directory and may carry a `-`; the pattern must not assume word
// characters only, or the assertion passes on one machine and fails on another.
assert.match(bundle, /[\w-]+_turnSummary\{[^}]*flex-wrap:wrap/, 'turn summary row must wrap')
assert.match(bundle, /[\w-]+_turnSummaryLabel,\.[\w-]+_turnMutationLabel\{[^}]*white-space:nowrap/, 'turn summary labels must not break per character')
assert.ok(bundle.includes('turnMutationLabel'), 'the path-less mutation label must carry the nowrap class')
const clientFiles = (await readdir(`${root}src/client`, { recursive: true }))
  .filter(file => /\.(?:ts|tsx)$/.test(file))
const clientSource = (await Promise.all(clientFiles.map(file => readFile(`${root}src/client/${file}`, 'utf8')))).join('\n')
assert.equal(/createElement\(["']iframe["']\)|<iframe/i.test(clientSource), false, 'default client source contains no iframe')

const PLATFORM_MODULES = new Set([
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client', '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-ui-slots', '@deepseek-ai/dsh-client-web-react',
  '@deepseek-ai/dsh-client-ui-primitives', '@deepseek-ai/dsh-client-ui-attachment',
  '@deepseek-ai/dsh-client-schema-form',
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
assert.deepEqual(exports_.inject, ['slots', 'locale', 'uiConversation', 'workspaces', 'sessions', 'uiWorkspace', 'remote', 'remote.agentPresets'])

const registrations = []
const dictionaries = []
let definition = null
function effect(run) {
  const disposers = []
  const dispose = () => { for (const stop of disposers.splice(0).reverse()) stop() }
  try {
    const result = run()
    if (typeof result === 'function') disposers.push(result)
    else if (result?.[Symbol.iterator]) {
      for (const stop of result) if (typeof stop === 'function') disposers.push(stop)
    }
    return dispose
  } catch (error) { dispose(); throw error }
}
const sessionListeners = new Set()
let sessionSnapshot = { ids: ['writing'], byId: { writing: { retainedBy: { mainView: 1 }, blank: false, projectionValues: { agentPreset: 'openwrite-0.2.0' } } }, phase: 'ready', projectionsBySession: {} }
const fakeClientCtx = {
  effect,
  uiConversation: { views: { register: () => () => {} }, events: { register(value) { definition = value; return () => {} } } },
  uiWorkspace: {},
  remote: { agentPresets: {} },
  workspaces: { marker: 'workspaces' },
  sessions: { marker: 'sessions', list: {
    subscribe: listener => { sessionListeners.add(listener); return () => sessionListeners.delete(listener) },
    getSnapshot: () => sessionSnapshot,
  } },
  locale: {
    register(ns, dicts) { dictionaries.push({ ns, dicts }); return () => {} },
    bind: () => key => key,
  },
  slots: {
    spec() { return { kind: 'chain' } },
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
const primaryListeners = [...sessionListeners]
assert.equal(dictionaries.length, 1)
assert.equal(dictionaries[0].dicts.zh['view.creation'], '创作')
assert.equal(dictionaries[0].dicts.zh['view.library'], '资料')
assert.equal(dictionaries[0].dicts.zh['view.operations'], '任务')
assert.equal(definition.kind, 'dsh-novel-mutations')

const views = registrations.filter(entry => entry.options.name === 'conversation.view')
assert.deepEqual(views.map(entry => [entry.options.id, entry.options.order]), [
  ['openwrite.creation', 22], ['openwrite.library', 23], ['openwrite.tasks', 24],
])
for (const view of views) {
  const injected = view.options.inject()
  assert.equal(typeof injected.fetchStudioApi, 'function')
  assert.equal(typeof injected.postStudioApi, 'function')
  assert.equal(typeof injected.putStudioApi, 'function')
  assert.equal(typeof injected.workspaces?.create, 'function')
  assert.equal(injected.sessions?.marker, 'sessions')
}

assert.equal(registrations.filter(entry => entry.options.name === 'conversation.session.header.actions').length, 1)
assert.equal(registrations.filter(entry => entry.options.name === 'conversation.session.header.utilities').length, 1)
assert.equal(registrations.filter(entry => entry.options.name === 'conversation.input.left').length, 1)
assert.equal(registrations.filter(entry => entry.options.name === 'conversation.chat.turnTail').length, 1)

const toolKeys = registrations.filter(entry => entry.options.name === 'tool.call.toolview').map(entry => entry.options.key)
for (const key of ['novel_review_chapter', 'novel_status', 'novel_context_preview', 'novel_doc', 'novel_revision', 'novel_task', 'novel_search', 'novel_assets', 'novel_outline_edit']) {
  assert.ok(toolKeys.includes(key), `${key} has a native tool card`)
}
assert.ok(toolKeys.length >= 30, 'common novel tools use family cards')

// The 0.2 turn-tail slot is a list. It requires an id and supplies owner
// props directly; the component must perform the old chain selection itself.
const listRegistrations = []
exports_.apply({ ...fakeClientCtx, slots: {
  ...fakeClientCtx.slots,
  spec: () => ({ kind: 'list' }),
  register(options, component) {
    if (options.name === 'conversation.chat.turnTail') {
      assert.equal(options.id, 'openwrite.mutation-summary')
      assert.equal(options.select, undefined)
    }
    listRegistrations.push({ options, component })
    return () => {}
  },
} })
assert.equal(listRegistrations.filter(entry => entry.options.name === 'conversation.chat.turnTail').length, 1)

// A failure after earlier tool cards registered must unwind those cards,
// remain contained, and leave the launcher/workbench registrations usable.
const failures = []
const previousError = console.error
const activeTools = new Set()
let delayedMount
console.error = (...args) => failures.push(args)
try {
  const failingSlots = {
    ...fakeClientCtx.slots,
    register(options) {
      if (options.key === 'novel_doc') throw new Error('changed tool slot contract')
      if (options.name === 'tool.call.toolview') activeTools.add(options.key)
      return () => activeTools.delete(options.key)
    },
  }
  assert.doesNotThrow(() => exports_.apply({ ...fakeClientCtx, slots: failingSlots }))
  assert.equal(activeTools.size, 0, 'tool registration failure rolls back earlier cards')
  assert.match(String(failures[0][0]), /UI contribution disabled: tool.call.toolview/)
  exports_.apply({ ...fakeClientCtx, slots: {
    ...failingSlots,
    inject(name, callback) {
      if (name === 'tool.call.toolview') { delayedMount = callback; return () => {} }
      return fakeClientCtx.slots.inject(name, callback)
    },
  } })
  assert.doesNotThrow(() => delayedMount(), 'late declarations contain setup errors too')
  assert.equal(activeTools.size, 0)
} finally { console.error = previousError }

// Exercise the workspace connection helper against the preset actually installed
// by the root package, and verify the bottom-left sidebar launcher is gone.
const presetHome = await mkdtemp(join(tmpdir(), 'openwrite-launch-smoke-'))
const previousHome = process.env.DSH_HOME
const presetDisposers = []
process.env.DSH_HOME = presetHome
try {
  await installReleasePreset({ inject() {}, effect: factory => presetDisposers.push(factory()) })
  assert.equal(registrations.some(entry => entry.options.id === 'openwrite.launch' || entry.options.name === 'sidebar.footer.action'), false, 'bottom-left launcher must be removed')
  const calls = []
  fakeClientCtx.uiWorkspace.connectWorkspace = async workspaceId => {
    calls.push(['connect', workspaceId])
    return 'launch-session'
  }
  // The panel prefers the stable id and falls back to the release identity;
  // the release directory on disk is what the fallback must resolve against.
  fakeClientCtx.remote.agentPresets.select = async (sessionId, presetId) => {
    assert.equal(sessionId, 'launch-session')
    const installedVersion = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url))).version
    const releaseId = `openwrite-${installedVersion.replace(/[^a-z0-9-]/g, '-')}`
    const resolvedId = presetId === 'openwrite' ? releaseId : presetId
    const marker = JSON.parse(await readFile(join(presetHome, '.agent-presets', resolvedId, '.openwrite-managed.json')))
    assert.equal(marker.version, installedVersion)
    calls.push(['preset', presetId])
    return { ok: true }
  }
  fakeClientCtx.uiWorkspace.openSession = target => {
    calls.push(['open', target])
    sessionSnapshot = { ids: [target], byId: {
      [target]: { retainedBy: { mainView: 1 }, projectionValues: { agentPreset: 'openwrite' } },
    } }
  }
  fakeClientCtx.uiConversation.binding = id => ({ activate: target => calls.push(['activate', id, target]) })
  const workspaceServices = views[0].options.inject().workspaces
  assert.equal(await workspaceServices.connectWorkspace('launch-workspace'), 'launch-session')
  workspaceServices.openSession('launch-session')
  assert.deepEqual(calls.map(call => call[0]), ['connect', 'preset', 'open', 'activate'])
  assert.deepEqual(calls[0], ['connect', 'launch-workspace'])
  assert.deepEqual(calls[3], ['activate', 'launch-session', 'openwrite.creation'])

  // Native workspace + preset selection updates the blank session's preset without
  // openSession(); activate the workbench once so tabs appear before a first turn.
  const blankCalls = []
  fakeClientCtx.uiConversation.binding = id => ({ activate: target => blankCalls.push([id, target]) })
  sessionSnapshot = { ids: ['native-blank'], byId: {
    'native-blank': { retainedBy: { mainView: 1 }, blank: true, projectionValues: { agentPreset: 'openwrite' } },
  }, phase: 'ready', projectionsBySession: {} }
  for (const listener of primaryListeners) listener()
  for (const listener of primaryListeners) listener()
  assert.deepEqual(blankCalls, [['native-blank', 'openwrite.creation']])

  // Issue #79: exercise the shipped shared picker injected into every workbench
  // and workspace-binding flow.
  const picker = workspaceServices.pickDirectory
  for (const view of views) assert.equal(view.options.inject().workspaces.pickDirectory, picker)
  const newWork = registrations.find(entry => entry.options.name === 'conversation.input.left')
  assert.equal(newWork.options.inject().workspaces.pickDirectory, picker)
  const previousDesktopPicker = Object.getOwnPropertyDescriptor(globalThis, '__DSH_DESKTOP_PICK_DIRECTORY__')
  const unavailable = Object.assign(new Error('directoryPicker.pick needs the native capability; the composed picker serves "browse"'), { code: 'directory-picker/unavailable' })
  const windowsPath = String.raw`A:\AI\中文作品`
  let nativeCalls = 0
  let desktopCalls = 0
  let nativeResult = '/native/workspace'
  let desktopResult = windowsPath
  let nativeFailure
  let desktopFailure
  fakeClientCtx.uiWorkspace.pickDirectory = async () => {
    nativeCalls++
    if (nativeFailure) throw nativeFailure
    return nativeResult
  }
  const desktopPick = async () => {
    desktopCalls++
    if (desktopFailure) throw desktopFailure
    return desktopResult
  }
  globalThis.__DSH_DESKTOP_PICK_DIRECTORY__ = desktopPick
  try {
    assert.equal(await picker(), '/native/workspace')
    assert.equal(desktopCalls, 0, 'working native picker is preferred')
    nativeResult = null
    assert.equal(await picker(), null)
    assert.equal(desktopCalls, 0, 'native cancellation must not open another dialog')

    nativeFailure = unavailable
    assert.equal(await picker(), windowsPath, 'workbench flows fall back to desktop picker when native picker is unavailable')
    assert.equal(desktopCalls, 1)

    desktopResult = null
    assert.equal(await picker(), null)

    delete globalThis.__DSH_DESKTOP_PICK_DIRECTORY__
    await assert.rejects(picker(), error => error === unavailable)
    globalThis.__DSH_DESKTOP_PICK_DIRECTORY__ = 'not a capability'
    await assert.rejects(picker(), error => error === unavailable)
    globalThis.__DSH_DESKTOP_PICK_DIRECTORY__ = desktopPick
    desktopFailure = new Error('desktop dialog failed')
    await assert.rejects(picker(), error => error === desktopFailure)
  } finally {
    if (previousDesktopPicker) Object.defineProperty(globalThis, '__DSH_DESKTOP_PICK_DIRECTORY__', previousDesktopPicker)
    else delete globalThis.__DSH_DESKTOP_PICK_DIRECTORY__
  }
} finally {
  for (const dispose of presetDisposers) await dispose()
  if (previousHome === undefined) delete process.env.DSH_HOME
  else process.env.DSH_HOME = previousHome
  await rm(presetHome, { recursive: true, force: true })
}

console.log('studio-panel smoke ok:', { views: views.length, toolCards: toolKeys.length, native: true })
