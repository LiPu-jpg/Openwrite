// Smoke check for the built plugin: asserts the dsh plugin export contract
// (name / inject / apply / Config) without starting any server.
import assert from 'node:assert/strict'
import * as mod from '../lib/index.js'

assert.equal(mod.name, '@dsh-novel/openwrite-bridge', 'name export')
assert.deepEqual(mod.inject, ['tools'], 'inject export')
assert.equal(typeof mod.apply, 'function', 'apply export')
assert.ok(mod.Config, 'Config schema export')

// The Schemastery schema must validate an empty config and fill defaults.
const resolved = mod.Config({})
assert.equal(resolved.baseUrl, 'http://127.0.0.1:4567')
assert.equal(resolved.timeoutMs, 600000)
assert.equal(typeof resolved.outputDir, 'string')

// Run apply against a stub tools registry: defineTool compiles the parameter
// and output schemas at registration time, so this catches DSL misuse.
const registered = []
mod.apply({ tools: { register: (tool) => registered.push(tool) } }, resolved)
const expected = [
  // reads, then writes — the registration order in src/tools.ts
  'novel_status', 'novel_context_preview', 'novel_outline_read', 'novel_assets_list',
  'novel_search', 'novel_doc_read',
  'novel_outline_edit', 'novel_write_chapter', 'novel_review_chapter', 'novel_asset_update',
  'novel_foreshadowing', 'novel_doc_write', 'novel_focus', 'novel_export', 'novel_chat_goethe',
]
assert.deepEqual(registered.map((t) => t.name), expected, 'registered novel_* tools')
for (const tool of registered) {
  assert.ok(tool.description && tool.parameters && tool.output?.schema, `${tool.name} is fully defined`)
}

console.log('smoke ok:', { name: mod.name, inject: mod.inject, tools: registered.length, config: resolved })
