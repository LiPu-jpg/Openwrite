import test from 'node:test'
import assert from 'node:assert/strict'
import { registerNovelTools } from '../lib/tools.js'

test('selection revisions forward the exact source version without changing offsets', async () => {
  const calls = [], tools = []
  const client = {postJson: async (path, body) => {calls.push({path, body}); return {ok: true}}}
  registerNovelTools({tools: {register: tool => tools.push(tool)}}, () => client, {timeoutMs: 1000, outputDir: '/unused'})
  const body = {chapter_id: 'ch_001', start: 7, end: 12, original_text: '选中\r\n文', expected_document_revision: 'sha256:current'}
  await tools.find(t => t.name === 'novel_revision_create_selection').execute(body, {signal: new AbortController().signal, callId: 'selection-version'})
  assert.deepEqual(calls, [{path: '/api/revisions/selection', body}])
})

test('review fixes retain an explicit selection cap and both versions', async () => {
  const calls = [], tools = []
  const client = {postJson: async (path, body) => {calls.push({path, body}); return {ok: true}}, getJson: async () => {throw Error('no fixture')}}
  registerNovelTools({tools: {register: tool => tools.push(tool)}}, () => client, {timeoutMs: 1000, outputDir: '/unused'})
  const body = {chapter_id: 'ch_001', issue_ids: ['issue-second'], selection: {start: 8, end: 12, original_text: '密信还在'},
    expected_document_revision: 'sha256:current', expected_review_revision: 'sha256:review'}
  await tools.find(t => t.name === 'novel_revision_create_from_review').execute(body, {signal: new AbortController().signal, callId: 'bounded-review'})
  assert.deepEqual(calls, [{path: '/api/revisions/from-review', body}])
})

test('write dry-run and archived history cross the tool boundary without losing options', async () => {
  const calls = []
  const tools = []
  const client = {postJson: async (path, body) => {calls.push({path, body}); return {ok: true}}}
  registerNovelTools({tools: {register: tool => tools.push(tool)}}, () => client, {timeoutMs: 1000, outputDir: '/unused'})
  const exec = {signal: new AbortController().signal, callId: 'followup-options'}
  await tools.find(t => t.name === 'novel_write_chapter').execute({dry_run: true, target_words: 2000, guidance: '雨停开门。', chapter_id: 'ch_001'}, exec)
  assert.deepEqual(calls.shift(), {path: '/api/write', body: {dry_run: true, target_words: 2000, guidance: '雨停开门。', chapter_id: 'ch_001'}})
  await tools.find(t => t.name === 'novel_write_chapter').execute({chapter_id: 'ch_001'}, exec)
  assert.equal(calls.shift().path, '/api/tasks')
  await tools.find(t => t.name === 'novel_chapter_run_action').execute({action: 'list', include_archived: true, chapter_id: 'ch_001'}, exec)
  assert.deepEqual(calls.shift(), {path: '/api/chapter-runs-v2', body: {action: 'list', include_archived: true, chapter_id: 'ch_001'}})
})

test('review forwards explicit scope to Studio', async () => {
  const calls = []
  const tools = []
  const client = {postJson: async (path, body) => {calls.push({path, body}); return {}}, getJson: async () => {throw new Error('no project fixture')}}
  registerNovelTools({tools: {register: tool => tools.push(tool)}}, () => client, {timeoutMs: 1000, outputDir: '/unused'})
  const tool = tools.find(t => t.name === 'novel_review_chapter')
  await tool.execute({chapter_id: 'ch_001', depth: 'quick'}, {signal: new AbortController().signal, callId: 'review-quick'})
  assert.equal(calls[0].path, '/api/review')
  assert.equal(calls[0].body.depth, 'quick')
  await tool.execute({chapter_id: 'ch_001', domains: ['canon', 'prose']}, {signal: new AbortController().signal, callId: 'review-domains'})
  assert.deepEqual(calls[1].body.domains, ['canon', 'prose'])
})
