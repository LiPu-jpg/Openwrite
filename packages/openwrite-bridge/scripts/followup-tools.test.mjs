import test from 'node:test'
import assert from 'node:assert/strict'
import { registerNovelTools } from '../lib/tools.js'

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
