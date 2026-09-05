#!/usr/bin/env node
/**
 * Audit reproduction of the current CreationView autosave defect.
 *
 * Run from any directory with Node 24:
 *   node /Users/jiaoziang/dsh-novel/docs/research/autosave-race-repro.mjs
 *
 * This deliberately asserts that the BUG is present: draft B is never sent,
 * yet is marked saved when draft A's delayed PUT succeeds. Once production
 * code is fixed, convert this into a regression test expecting B to remain
 * dirty and eventually be submitted; do not retain these inverted assertions
 * as a correctness gate.
 *
 * The actual save/updateDraft callbacks and JSON parsing helpers are extracted
 * from CreationView.tsx. Only React bindings, refs, timers, state and HTTP are
 * stubbed. No model, network, browser, service or real manuscript is accessed.
 * This proves callback behavior, not full React/Vditor/browser integration.
 */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import { fileURLToPath } from 'node:url'
import { createContext, runInContext } from 'node:vm'

const sourceFile = fileURLToPath(new URL('../../packages/studio-panel/src/client/CreationView.tsx', import.meta.url))
const source = await readFile(sourceFile, 'utf8')
const start = source.indexOf('  const save = useCallback(')
const end = source.indexOf('  const chooseChapter = ', start)
const helpersStart = source.indexOf('function record(')
const helpersEnd = source.indexOf('function chapterId(', helpersStart)
assert.ok(start >= 0 && end > start && helpersStart >= 0 && helpersEnd > helpersStart,
  'CreationView source structure changed; review this audit extractor before running it again')
const callbacks = source.slice(start, end)
const helpers = source.slice(helpersStart, helpersEnd)
const code = stripTypeScriptTypes(
  `${helpers}\n${callbacks}\nglobalThis.save = save; globalThis.updateDraft = updateDraft;`,
  { mode: 'strip' },
)

const requests = []
const statuses = []
const invalidations = []
const timers = new Map()
let timerId = 0
let resolvePut
let clientDocument
let visibleDraft = 'A'
const draftRef = { current: 'A' }
const dirtyRef = { current: true }
const savedContentRef = { current: 'previous' }
const scope = {
  document_: {
    path: 'data/manuscript/ch_001.md', title: 'audit fixture',
    content: 'previous', version: 'v1', revision: 'r1',
  },
  dirtyRef, draftRef, savedContentRef,
  saveTimerRef: { current: null },
  useCallback: callback => callback,
  window: {
    clearTimeout: id => { timers.delete(id) },
    setTimeout: (callback, ms) => {
      const id = ++timerId
      timers.set(id, { callback, ms })
      return id
    },
  },
  workbenchStore: {
    setEditorStatus: (...args) => { statuses.push(args) },
    invalidate: resource => { invalidations.push(resource) },
  },
  putStudioApi: (path, body) => {
    requests.push({ path, body: structuredClone(body) })
    return new Promise(resolve => { resolvePut = resolve })
  },
  setDocument: value => { clientDocument = value },
  setDraft: value => { visibleDraft = value },
  StudioApiError: class StudioApiError extends Error {},
  t: key => key,
}
createContext(scope)
runInContext(code, scope, { filename: 'CreationView-extracted-autosave.js' })

// 1. Submit A and leave the actual save callback suspended inside its PUT.
const pendingA = scope.save()
assert.equal(requests.length, 1)
assert.equal(requests[0].body.content, 'A')
assert.equal(typeof resolvePut, 'function')

// 2. Type B through the actual input callback while A is still pending.
scope.updateDraft('B')
assert.equal(dirtyRef.current, true)
assert.equal(timers.size, 1)
assert.equal([...timers.values()][0].ms, 1_200)

// 3. The server acknowledges only A. These assertions document the defect.
resolvePut({ ...scope.document_, content: 'A', version: 'v2', revision: 'r2' })
await pendingA
assert.equal(visibleDraft, 'B')
assert.equal(savedContentRef.current, 'B', 'BUG: B was incorrectly recorded as saved')
assert.equal(clientDocument.content, 'B', 'BUG: the client claims the server saved B')
assert.equal(dirtyRef.current, false, 'BUG: an unsent edit lost its dirty flag')
assert.equal(statuses.at(-1)[0], 'saved', 'BUG: the author sees an incorrect saved status')

// 4. Fire B's real scheduled callback, then explicitly request another save.
const [scheduledId, timer] = [...timers.entries()][0]
timers.delete(scheduledId)
timer.callback()
await Promise.resolve()
await scope.save()
assert.deepEqual(requests.map(request => request.body.content), ['A'],
  'BUG: B remains unsent even after its autosave timer and another save call')

console.log(JSON.stringify({
  result: 'DEFECT REPRODUCED: B was never sent, but is marked saved and is not retried.',
  sourceFile,
  callbackLines: [source.slice(0, start).split('\n').length, source.slice(0, end).split('\n').length - 1],
  callbackSha256: createHash('sha256').update(callbacks).digest('hex'),
  node: process.version,
  actualCallbacksExecuted: ['save', 'updateDraft'],
  requestContents: requests.map(request => request.body.content),
  serverResponseContent: 'A',
  visibleDraft,
  reportedSavedContent: savedContentRef.current,
  clientDocumentContent: clientDocument.content,
  dirty: dirtyRef.current,
  finalStatus: statuses.at(-1)[0],
  requestCountAfterActualTimerAndExplicitSave: requests.length,
  statusSequence: statuses.map(status => status[0]),
  invalidations,
  proofScope: 'Deterministic execution of extracted source callbacks with stubs; no React/Vditor/browser interaction was tested.',
  maintenanceNote: 'This is a defect reproduction, not a passing correctness gate. After fixing production code, convert it into a regression test expecting B to be preserved and submitted.',
}, null, 2))
