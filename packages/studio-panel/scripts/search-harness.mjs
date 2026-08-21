/**
 * Logic-level harness for SearchView: mounts the REAL bundle component with
 * react-dom/client against a minimal DOM shim, drives a typing sequence, and
 * asserts the debounced fetch fires and results render. Run: node scripts/search-harness.mjs
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)

/* --- minimal DOM shim (enough for react-dom 18 on this simple tree) --- */

let expandoSeed = 0

class FakeNode {
  constructor() {
    this.childNodes = []
    this.parentNode = null
    this.ownerDocument = null
  }
  get firstChild() { return this.childNodes[0] ?? null }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] ?? null }
  get nextSibling() {
    if (this.parentNode === null) return null
    const siblings = this.parentNode.childNodes
    const index = siblings.indexOf(this)
    return siblings[index + 1] ?? null
  }
  get previousSibling() {
    if (this.parentNode === null) return null
    const siblings = this.parentNode.childNodes
    const index = siblings.indexOf(this)
    return siblings[index - 1] ?? null
  }
  appendChild(node) {
    node.parentNode?.removeChild(node)
    node.parentNode = this
    node.ownerDocument = this.ownerDocument
    this.childNodes.push(node)
    return node
  }
  insertBefore(node, before) {
    node.parentNode?.removeChild(node)
    node.parentNode = this
    node.ownerDocument = this.ownerDocument
    const index = before === null ? -1 : this.childNodes.indexOf(before)
    if (index === -1) this.childNodes.push(node)
    else this.childNodes.splice(index, 0, node)
    return node
  }
  removeChild(node) {
    const index = this.childNodes.indexOf(node)
    if (index !== -1) this.childNodes.splice(index, 1)
    node.parentNode = null
    return node
  }
  get textContent() {
    return this.childNodes.map(child => child.textContent).join('')
  }
  set textContent(value) {
    this.childNodes = []
    if (value !== '') this.appendChild(this.ownerDocument.createTextNode(value))
  }
  cloneNode() { throw new Error('cloneNode not implemented') }
  contains(node) {
    for (let current = node; current !== null; current = current.parentNode) {
      if (current === this) return true
    }
    return false
  }
}

class FakeText extends FakeNode {
  constructor(text) {
    super()
    this.nodeType = 3
    this.nodeValue = text
  }
  get textContent() { return this.nodeValue }
  set textContent(value) { this.nodeValue = value }
  get data() { return this.nodeValue }
  set data(value) { this.nodeValue = value }
}

class FakeComment extends FakeNode {
  constructor(text) {
    super()
    this.nodeType = 8
    this.nodeValue = text
  }
  get textContent() { return '' }
  set textContent(_) { /* comments hold no text content */ }
}

class FakeElement extends FakeNode {
  constructor(tag) {
    super()
    this.nodeType = 1
    this.tagName = tag.toUpperCase()
    this.nodeName = this.tagName
    this.localName = tag.toLowerCase()
    this.attributes = {}
    this.style = {}
    this.className = ''
    this.value = ''
    this.innerHTML = ''
    this.listeners = {}
    this.dataset = {}
    this.selected = false
    this.defaultSelected = false
    this.expando = `exp${expandoSeed++}`
  }
  get options() {
    return this.childNodes.filter(child => child.tagName === 'OPTION')
  }
  setAttribute(name, value) { this.attributes[name] = String(value) }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null }
  removeAttribute(name) { delete this.attributes[name] }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn) }
  removeEventListener(type, fn) {
    const list = this.listeners[type]
    if (list) this.listeners[type] = list.filter(item => item !== fn)
  }
  dispatchEvent() { return true }
  focus() {}
  blur() {}
  get firstChild() { return this.childNodes[0] ?? null }
}

const documentShim = {
  nodeType: 9,
  createElement: (tag) => {
    const el = new FakeElement(tag)
    el.ownerDocument = documentShim
    return el
  },
  createElementNS: (_ns, tag) => {
    const el = new FakeElement(tag)
    el.ownerDocument = documentShim
    return el
  },
  createTextNode: (text) => {
    const node = new FakeText(text)
    node.ownerDocument = documentShim
    return node
  },
  createComment: (text) => {
    const node = new FakeComment(text)
    node.ownerDocument = documentShim
    return node
  },
  addEventListener() {},
  removeEventListener() {},
  querySelector() { return null },
  querySelectorAll() { return [] },
  body: null,
  head: null,
  documentElement: null,
  hidden: false,
  visibilityState: 'visible',
  defaultView: null,
}
documentShim.body = documentShim.createElement('body')
documentShim.head = documentShim.createElement('head')
documentShim.documentElement = documentShim.createElement('html')

const windowShim = {
  document: documentShim,
  navigator: { userAgent: 'search-harness' },
  HTMLElement: FakeElement,
  HTMLIFrameElement: class FakeIFrame extends FakeElement {},
  HTMLInputElement: FakeElement,
  Node: FakeNode,
  Element: FakeElement,
  addEventListener() {},
  removeEventListener() {},
  setTimeout,
  clearTimeout,
  queueMicrotask,
  requestAnimationFrame: (fn) => setTimeout(fn, 0),
  cancelAnimationFrame: clearTimeout,
  getComputedStyle: () => ({}),
}
documentShim.defaultView = windowShim
documentShim.activeElement = null
documentShim.hasFocus = () => false

globalThis.window = windowShim
globalThis.document = documentShim
Object.defineProperty(globalThis, 'navigator', { value: windowShim.navigator, configurable: true })
globalThis.HTMLElement = FakeElement
globalThis.HTMLIFrameElement = windowShim.HTMLIFrameElement
globalThis.HTMLInputElement = FakeElement
globalThis.HTMLTextAreaElement = FakeElement
globalThis.HTMLSelectElement = FakeElement
globalThis.Node = FakeNode
globalThis.Element = FakeElement
globalThis.getComputedStyle = windowShim.getComputedStyle
globalThis.requestAnimationFrame = windowShim.requestAnimationFrame
globalThis.cancelAnimationFrame = windowShim.cancelAnimationFrame
globalThis.IS_REACT_ACT_ENVIRONMENT = true

/* --- mount the real component from the built bundle --- */

const React = require('react')
const { act } = React
const { createRoot } = require('react-dom/client')

// Extract SearchView from the CJS bundle by reusing the smoke loader handoff.
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('..', import.meta.url))
const bundle = await readFile(`${root}lib/client.js`, 'utf8')
let loaded = null
const moduleLoaderWindow = { __ModuleLoader__: { load(entry) { loaded = entry } } }
// The bundle checks window.__ModuleLoader__; hand it our loader while keeping the DOM shim.
windowShim.__ModuleLoader__ = moduleLoaderWindow.__ModuleLoader__
new Function('window', 'document', 'navigator', bundle)(windowShim, documentShim, windowShim.navigator)
assert.ok(loaded, 'bundle handoff captured')

// Drive apply() with a fake ctx and capture the search view registration.
const registrations = []
const fakeCtx = {
  effect(run) { run() },
  locale: { register() { return () => {} }, bind: () => (key) => key },
  slots: {
    inject(_name, cb) {
      const produced = cb()
      if (produced !== null && typeof produced === 'object' && Symbol.iterator in produced) {
        for (const _ of produced) { /* drain */ }
      }
    },
    register(options, component) { registrations.push({ options, component }); return () => {} },
  },
}
const exports_ = loaded.factory((specifier) => {
  if (specifier === 'react') return React
  if (specifier === 'react/jsx-runtime') return require('react/jsx-runtime')
  return {}
})
exports_.apply(fakeCtx)
const searchEntry = registrations.find(entry => entry.options.name === 'conversation.view' && entry.options.id === 'search')
assert.ok(searchEntry, 'search view registered')
const SearchView = searchEntry.component
const injected = searchEntry.options.inject()
assert.equal(typeof injected.fetchStudioApi, 'function')

/* --- the flow: type a query, wait out the debounce, expect results --- */

const fetchCalls = []
const realFetch = globalThis.fetch
const LIVE_BASE = process.env.LIVE_PROXY ?? ''
/** Mirror of the component constant, for settle timing. */
const DEBOUNCE_MS = 350
let failNextFetch = false
globalThis.fetch = LIVE_BASE !== ''
  ? (url, options) => {
    // Live mode: forward the relative proxy URL to the running dsh web server.
    fetchCalls.push(String(url))
    return realFetch(`${LIVE_BASE}${String(url)}`, options)
  }
  : async (url) => {
    fetchCalls.push(String(url))
    if (failNextFetch) {
      failNextFetch = false
      return new Response('{"error":"studio down"}', { status: 502, headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({
      query: '伶舟', scope: 'all', scope_label: '全部资料',
      results: [{
        path: 'data/manuscript/ch_0001.md', title: '第一章', line: 12, heading: '夜航',
        snippet: '伶舟 提灯走过长街', scope: 'chapters', scope_label: '正文',
        category: 'chapter', category_label: '章节', score: 3, retrieval: ['literal'], excerpt: '',
      }],
      indexed: 42, engine: 'literal-fallback', warning: '', warning_code: '',
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }

const container = documentShim.createElement('div')
const reactRoot = createRoot(container)
const t = (key) => key

/** Poll until the condition holds (render flush per tick) or the budget runs out. */
async function waitFor(condition, label, budgetMs = 8_000) {
  const deadline = Date.now() + budgetMs
  for (;;) {
    await act(async () => {})
    if (condition()) return
    if (Date.now() > deadline) assert.fail(`waitFor timed out: ${label}`)
    await new Promise(resolve => setTimeout(resolve, 50))
  }
}

/** Wait past the debounce window, then until the fetch settles and renders. */
async function settle(label, expectedCalls = fetchCalls.length + 1) {
  await new Promise(resolve => setTimeout(resolve, DEBOUNCE_MS + 150))
  await waitFor(() => fetchCalls.length >= expectedCalls, `${label}: fetch fired`)
  // The stub resolves immediately; live mode may take real time.
  await waitFor(
    () => !container.textContent.includes('loading'),
    `${label}: loading cleared`,
  )
}

/** Find the first element by tag under a node. */
function findByTag(node, tag) {
  if (node.tagName === tag) return node
  for (const child of node.childNodes ?? []) {
    const found = child.nodeType === 1 ? findByTag(child, tag) : null
    if (found !== null) return found
  }
  return null
}

/** Find a button whose text matches. */
function findButton(node, text) {
  if (node.tagName === 'BUTTON' && node.textContent === text) return node
  for (const child of node.childNodes ?? []) {
    const found = child.nodeType === 1 ? findButton(child, text) : null
    if (found !== null) return found
  }
  return null
}

/** React props expando key on a shim element. */
function reactPropsOf(node) {
  const key = Object.keys(node).find(name => name.startsWith('__reactProps$'))
  assert.ok(key, 'react props attached')
  return node[key]
}

await act(async () => {
  reactRoot.render(React.createElement(React.StrictMode, null,
    React.createElement(SearchView, { ...injected, t })))
})

// Initially idle: the hint key renders, no fetch fired.
assert.equal(fetchCalls.length, 0, 'no fetch before typing')
assert.ok(container.textContent.includes('search.hint'), 'idle hint visible')

const input = findByTag(container, 'INPUT')
assert.ok(input, 'search input mounted')

// Type: set the node's value (what the browser would do) then invoke the
// React-attached onChange prop with the node as event target.
await act(async () => {
  input.value = '伶舟'
  reactPropsOf(input).onChange({ target: input })
})

// Inside the debounce window: loading shown, no fetch yet.
assert.ok(container.textContent.includes('loading'), 'loading state visible while debouncing')
assert.equal(fetchCalls.length, 0, 'debounce holds the fetch')

await settle('first search')

assert.equal(fetchCalls.length, 1, `exactly one fetch fired, got ${fetchCalls.length}`)
assert.ok(fetchCalls[0].includes('/studio-panel/api/search?'), 'proxy search URL')
assert.ok(fetchCalls[0].includes('q=%E4%BC%B6%E8%88%9F'), 'query encoded')
assert.ok(fetchCalls[0].includes('scope=all'), 'scope forwarded')
if (LIVE_BASE !== '') {
  assert.ok(container.textContent.includes('伶舟'), 'live result content rendered')
} else {
  assert.ok(container.textContent.includes('第一章'), 'result title rendered')
  assert.ok(container.textContent.includes('data/manuscript/ch_0001.md:12'), 'path:line rendered')
}
assert.ok(!container.textContent.includes('loading'), 'loading state cleared')

// Type a second char: a new debounce cycle fires exactly one more fetch.
await act(async () => {
  input.value = '伶舟夜'
  reactPropsOf(input).onChange({ target: input })
})
await settle('second search')
assert.equal(fetchCalls.length, 2, 'second debounced fetch fired')

// Error → retry flow: stub mode only (needs a controllable failure).
if (LIVE_BASE === '') {
  failNextFetch = true
  await act(async () => {
    input.value = '伶舟夜航'
    reactPropsOf(input).onChange({ target: input })
  })
  await settle('failing search')
  assert.equal(fetchCalls.length, 3, 'third fetch fired')
  assert.ok(container.textContent.includes('studio down'), 'error message rendered')
  const retry = findButton(container, 'retry')
  assert.ok(retry, 'retry button rendered in the error state')
  await act(async () => { reactPropsOf(retry).onClick() })
  await settle('retry search')
  assert.equal(fetchCalls.length, 4, 'retry refired the fetch')
  assert.ok(container.textContent.includes('第一章'), 'results render after retry')
}

// Clear the input: back to idle, no further fetch.
const callsBeforeClear = fetchCalls.length
await act(async () => {
  input.value = ''
  reactPropsOf(input).onChange({ target: input })
})
await new Promise(resolve => setTimeout(resolve, DEBOUNCE_MS + 200))
await act(async () => {})
assert.equal(fetchCalls.length, callsBeforeClear, 'clearing the query fires no fetch')
assert.ok(container.textContent.includes('search.hint'), 'back to idle hint')

globalThis.fetch = realFetch
console.log('search harness: SearchView debounce → fetch → render flow passed')
