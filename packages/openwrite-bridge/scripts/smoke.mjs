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
  'novel_foreshadowing', 'novel_doc_write', 'novel_focus', 'novel_export',
  // assets: create / read / packages
  'novel_asset_read', 'novel_asset_create', 'novel_assets_package_export',
  'novel_assets_package_preview', 'novel_assets_package_import',
  // revisions
  'novel_revisions_list', 'novel_revision_get', 'novel_revision_create_selection',
  'novel_revision_create_from_review', 'novel_revision_apply', 'novel_revision_reject',
  'novel_revision_regenerate',
  // background tasks
  'novel_tasks_list', 'novel_task_get', 'novel_task_create', 'novel_task_cancel',
  'novel_task_retry', 'novel_task_confirm', 'novel_multi_write',
  // project lifecycle
  'novel_project_init', 'novel_project_open', 'novel_project_delete',
  // chapters, documents, import, sync
  'novel_chapter_delete', 'novel_doc_create', 'novel_import_preview', 'novel_import',
  'novel_sync', 'novel_writing_targets',
  // continuity & diagnostics
  'novel_continuity', 'novel_diagnostics',
  // planning: chapter runs, rolling plans, forecasts, manuscript editing
  'novel_chapter_run_action', 'novel_rolling_plan_action', 'novel_narrative_forecast_action',
  'novel_manuscript_edit_action',
  // style sources, reference library, runtime skills, rules
  'novel_source_action', 'novel_reference_library_action', 'novel_runtime_skill_action',
  'novel_rule_action',
  // deep research
  'novel_research_status', 'novel_research_report', 'novel_research_settings_save',
  // model configuration
  'novel_model_profiles', 'novel_model_configure', 'novel_model_test',
  'novel_model_embedding_test', 'novel_model_profile_save', 'novel_model_profile_delete',
  'novel_model_routes_save',
]
assert.deepEqual(registered.map((t) => t.name), expected, 'registered novel_* tools')
for (const tool of registered) {
  assert.ok(tool.description && tool.parameters && tool.output?.schema, `${tool.name} is fully defined`)
}

console.log('smoke ok:', { name: mod.name, inject: mod.inject, tools: registered.length, config: resolved })
