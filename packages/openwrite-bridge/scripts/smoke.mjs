// Smoke check for the built plugin: asserts the dsh plugin export contract
// (name / inject / apply / Config) without starting any server.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context, Service } from '@deepseek-ai/cordis'
import * as mod from '../lib/index.js'
import { materializeChapterDelivery } from '../lib/dog-delivery.js'
import { materializeCompletedDogTaskReview } from '../lib/dog-review.js'

assert.equal(mod.name, '@dsh-novel/openwrite-bridge', 'name export')
assert.deepEqual(mod.inject, ['tools'], 'inject export')
assert.equal(typeof mod.apply, 'function', 'apply export')
assert.ok(mod.Config, 'Config schema export')

// The Schemastery schema must validate an empty config and fill defaults.
const resolved = mod.Config({})
assert.equal(resolved.baseUrl, 'http://127.0.0.1:4567')
assert.equal(resolved.timeoutMs, 600000)
assert.equal(typeof resolved.outputDir, 'string')

const registered = []
const routes = []
class ToolsService extends Service {
  constructor(ctx) { super(ctx, 'tools') }
  register(tool) { registered.push(tool) }
}
class WebServerService extends Service {
  constructor(ctx) { super(ctx, 'webServer') }
  register(route) { routes.push(route); return () => {} }
}
const root = new Context()
await root.plugin(ToolsService)
await root.plugin(WebServerService)
await root.plugin(mod, resolved)
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

assert.deepEqual(routes.map(route => [route.kind, route.path]), [
  ['exact', '/studio-panel/config.json'],
  ['prefix', '/studio-panel/api'],
  ['exact', '/studio-panel/invalidation.json'],
  ['exact', '/studio-panel/events'],
], 'domain service owns config, API and invalidation routes')

function capture() {
  const listeners = {}
  return {
    status: 0, headers: {}, body: '', chunks: [],
    writeHead(status, headers) { this.status = status; Object.assign(this.headers, headers ?? {}) },
    write(body) { this.chunks.push(String(body)) },
    end(body) { if (body !== undefined) this.body = Buffer.from(body).toString('utf8') },
    on(event, listener) { listeners[event] = listener },
  }
}

const configRoute = routes.find(route => route.path === '/studio-panel/config.json')
const configResponse = capture()
await configRoute.handler({ method: 'GET' }, configResponse)
assert.equal(configResponse.status, 200)
assert.deepEqual(JSON.parse(configResponse.body), { studioUrl: resolved.baseUrl })

const invalidationRoute = routes.find(route => route.path === '/studio-panel/invalidation.json')
const initialInvalidation = capture()
await invalidationRoute.handler({ method: 'GET' }, initialInvalidation)
assert.deepEqual(JSON.parse(initialInvalidation.body), { revision: 0, resource: 'workspace', path: '' })
assert.equal(Number(initialInvalidation.headers['content-length']), Buffer.byteLength(initialInvalidation.body))

const eventsRoute = routes.find(route => route.path === '/studio-panel/events')
const eventResponse = capture()
await eventsRoute.handler({ method: 'GET' }, eventResponse)
assert.equal(eventResponse.status, 200)
assert.match(eventResponse.headers['content-type'], /text\/event-stream/)
assert.match(eventResponse.chunks.join(''), /event: ready/)

const proxyRoute = routes.find(route => route.path === '/studio-panel/api')
const originalFetch = globalThis.fetch
globalThis.fetch = async () => new Response(JSON.stringify({ ok: true }), {
  status: 200,
  headers: { 'content-type': 'application/json' },
})
try {
  const mutationResponse = capture()
  await proxyRoute.handler({
    method: 'PUT',
    url: '/studio-panel/api/document',
    async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
  }, mutationResponse)
  assert.equal(mutationResponse.status, 200)
  assert.equal(Number(mutationResponse.headers['content-length']), Buffer.byteLength(mutationResponse.body))
} finally {
  globalThis.fetch = originalFetch
}
const changedInvalidation = capture()
await invalidationRoute.handler({ method: 'GET' }, changedInvalidation)
assert.deepEqual(JSON.parse(changedInvalidation.body), {
  revision: 1,
  resource: 'manuscript',
  path: '/api/document',
})
assert.match(eventResponse.chunks.join(''), /event: invalidate/)

const dogWorkspace = await mkdtemp(join(tmpdir(), 'dsh-novel-dog-smoke-'))
try {
  const dogReview = await materializeCompletedDogTaskReview({
    task: {
      type: 'chapter_review', status: 'completed', chapter_id: 'ch_009',
      result: {
        passed: false, score: 81, dimensions: [1, 2], summary: 'fixture',
        issue_details: [
          { id: 'issue-1', dimension: 1, severity: 'critical', description: 'OOC' },
          { id: 'issue-general', dimension: null, severity: 'warning', description: 'unmapped' },
        ],
      },
    },
  }, {
    project: { root: dogWorkspace }, snapshot: { novel_id: 'smoke-book' },
  })
  assert.equal(dogReview.status, 'ready')
  const graph = JSON.parse(await readFile(dogReview.graphPath, 'utf8'))
  assert.equal(Object.keys(graph.nodes).length, 38)
  assert.equal(JSON.parse(await readFile(join(dogWorkspace, 'data/novels/smoke-book/data/dog/reviews/ch_009/dim_01.json'), 'utf8')).verdict, 'fail')
  assert.equal(JSON.parse(await readFile(join(dogWorkspace, 'data/novels/smoke-book/data/dog/reviews/ch_009/dim_03.json'), 'utf8')).verdict, 'inconclusive')
  const manifest = JSON.parse(await readFile(join(dogWorkspace, 'data/novels/smoke-book/data/dog/reviews/ch_009/review.json'), 'utf8'))
  assert.equal(manifest.issueCount, 2)
  assert.equal(manifest.unmappedIssueCount, 1)
  assert.equal(await materializeCompletedDogTaskReview({ task: { type: 'chapter_write', status: 'completed' } }, {}), undefined)

  const manuscript = join(dogWorkspace, 'data/novels/smoke-book/data/manuscript/arc_001/ch_009.md')
  await mkdir(join(dogWorkspace, 'data/novels/smoke-book/data/manuscript/arc_001'), { recursive: true })
  await writeFile(manuscript, '# 第九章\n\n正文', 'utf8')
  const revision = `sha256:${createHash('sha256').update(await readFile(manuscript)).digest('hex')}`
  await mkdir(join(dogWorkspace, 'data/novels/smoke-book/data/reviews'), { recursive: true })
  await writeFile(join(dogWorkspace, 'data/novels/smoke-book/data/reviews/ch_009.json'), JSON.stringify({
    score: 90, passed: true, source_revision: revision, issue_details: [],
  }), 'utf8')
  const delivery = await materializeChapterDelivery({
    project: { root: dogWorkspace }, snapshot: { novel_id: 'smoke-book' },
  }, 'ch_009', 70)
  assert.equal(delivery.readyForDelivery, true)
  const deliveryGraph = JSON.parse(await readFile(delivery.graphPath, 'utf8'))
  assert.deepEqual(deliveryGraph.dependsOn.map(edge => `${edge.source}->${edge.target}`), [
    'review->manuscript', 'revision->review', 'closure->revision',
  ])
} finally {
  await rm(dogWorkspace, { recursive: true, force: true })
}

await root.fiber.dispose()

console.log('smoke ok:', { name: mod.name, inject: mod.inject, tools: registered.length, config: resolved })
