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
import { buildDogReviewBundle, materializeCompletedDogTaskReview } from '../lib/dog-review.js'

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
  'novel_model_profiles', 'novel_model_benchmark', 'novel_model_configure', 'novel_model_test',
  'novel_model_embedding_test', 'novel_model_profile_save', 'novel_model_profile_delete',
  'novel_model_routes_save',
]
assert.deepEqual(registered.map((t) => t.name), expected, 'registered novel_* tools')
for (const tool of registered) {
  assert.ok(tool.description && tool.parameters && tool.output?.schema, `${tool.name} is fully defined`)
}

const benchmarkTool = registered.find(tool => tool.name === 'novel_model_benchmark')
assert.ok(benchmarkTool, 'benchmark tool is registered')
const benchmarkRequests = []
const benchmarkFetch = globalThis.fetch
globalThis.fetch = async (input, init = {}) => {
  benchmarkRequests.push({ url: String(input), init })
  return new Response(JSON.stringify({ ok: true, data: { accepted: true } }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}
try {
  const exec = { signal: new AbortController().signal }
  assert.deepEqual(await benchmarkTool.execute({ action: 'list', limit: 7 }, exec), { accepted: true })
  assert.deepEqual(await benchmarkTool.execute({ action: 'get', run_id: 'bench_test_001' }, exec), { accepted: true })
  assert.deepEqual(await benchmarkTool.execute({
    action: 'run', chapter_id: 'ch_003', writer_profile_ids: ['writer-a', 'writer-b'],
    reviewer_profile_ids: ['critic'], execution_mode: 'framework', repeats: 2,
    target_words: 2400, concurrency: 2,
  }, exec), { accepted: true })
  await assert.rejects(() => benchmarkTool.execute({ action: 'get' }, exec), /run_id is required/)
  await assert.rejects(() => benchmarkTool.execute({ action: 'run', reviewer_profile_ids: ['critic'] }, exec), /writer_profile_ids is required/)
  await assert.rejects(() => benchmarkTool.execute({ action: 'run', writer_profile_ids: ['writer-a'] }, exec), /reviewer_profile_ids is required/)
} finally {
  globalThis.fetch = benchmarkFetch
}
assert.equal(new URL(benchmarkRequests[0].url).pathname, '/api/benchmarks')
assert.equal(new URL(benchmarkRequests[0].url).searchParams.get('limit'), '7')
assert.equal(benchmarkRequests[0].init.method, 'GET')
assert.equal(new URL(benchmarkRequests[1].url).pathname, '/api/benchmarks/bench_test_001')
assert.equal(benchmarkRequests[1].init.method, 'GET')
assert.equal(new URL(benchmarkRequests[2].url).pathname, '/api/benchmarks')
assert.equal(benchmarkRequests[2].init.method, 'POST')
assert.equal(benchmarkRequests[2].init.headers['X-OpenWrite-Studio'], '1')
assert.deepEqual(JSON.parse(benchmarkRequests[2].init.body), {
  writer_profile_ids: ['writer-a', 'writer-b'], reviewer_profile_ids: ['critic'],
  chapter_id: 'ch_003', execution_mode: 'framework', repeats: 2,
  target_words: 2400, concurrency: 2,
})

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
const benchmarkInvalidation = capture()
await invalidationRoute.handler({ method: 'GET' }, benchmarkInvalidation)
assert.deepEqual(JSON.parse(benchmarkInvalidation.body), {
  revision: 1,
  resource: 'benchmark',
  path: '/api/benchmarks',
})
assert.equal(Number(benchmarkInvalidation.headers['content-length']), Buffer.byteLength(benchmarkInvalidation.body))

const eventsRoute = routes.find(route => route.path === '/studio-panel/events')
const eventResponse = capture()
await eventsRoute.handler({ method: 'GET' }, eventResponse)
assert.equal(eventResponse.status, 200)
assert.match(eventResponse.headers['content-type'], /text\/event-stream/)
assert.match(eventResponse.chunks.join(''), /event: ready/)

const proxyRoute = routes.find(route => route.path === '/studio-panel/api')
const originalFetch = globalThis.fetch
const proxyRequests = []
globalThis.fetch = async (input, init = {}) => {
  proxyRequests.push({ url: String(input), init })
  const path = new URL(String(input)).pathname
  const payload = path === '/api/tasks'
    ? {
        ok: true,
        data: {
          tasks: [
            {
              task_id: 'tsk_benchmark', type: 'model_benchmark', status: 'completed', phase: 'done',
              result: {
                run_id: 'bench_smoke', status: 'completed', artifact_path: '/tmp/bench.json',
                context_hash: 'sha256:test', summary: { average_quality_score: 86 },
                candidates: [{ content: 'large candidate content must be removed' }],
                evaluations: [{ quality_score: 86 }],
              },
            },
            {
              task_id: 'tsk_review', type: 'chapter_review', status: 'completed', phase: 'done',
              result: {
                score: 84, passed: false, issues: 1, summary: 'Needs one repair',
                review_v2: {
                  schema_version: 'openwrite.review.v2',
                  execution_status: 'completed', quality_score: 84, coverage: 0.92,
                  gate_status: 'blocked', delivery_status: 'blocked',
                  production_gate_status: 'disabled_uncalibrated',
                  freshness_status: 'current', source_revision: 'sha256:smoke',
                  current_source_revision: 'sha256:smoke', domains: [{ id: 'large' }],
                },
                issue_details: [{
                  severity: 'critical', review_severity: 'critical', revision_priority: 'blocker',
                  dimension: 2, category: 'logic', description: 'Broken causal link', evidence: { quote: 'large' },
                }],
              },
            },
          ],
        },
      }
    : { ok: true }
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}
try {
  const mutationResponse = capture()
  await proxyRoute.handler({
    method: 'PUT',
    url: '/studio-panel/api/document',
    async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
  }, mutationResponse)
  assert.equal(mutationResponse.status, 200)
  assert.equal(Number(mutationResponse.headers['content-length']), Buffer.byteLength(mutationResponse.body))

  const documentInvalidation = capture()
  await invalidationRoute.handler({ method: 'GET' }, documentInvalidation)
  assert.deepEqual(JSON.parse(documentInvalidation.body), {
    revision: 2,
    resource: 'manuscript',
    path: '/api/document',
  })

  const benchmarkProxyResponse = capture()
  await proxyRoute.handler({
    method: 'POST',
    url: '/studio-panel/api/benchmarks',
    async *[Symbol.asyncIterator]() { yield Buffer.from('{"writer_profile_ids":["writer"]}') },
  }, benchmarkProxyResponse)
  assert.equal(benchmarkProxyResponse.status, 200)
  assert.equal(proxyRequests[1].init.headers['x-openwrite-studio'], '1')
  assert.equal(new URL(proxyRequests[1].url).pathname, '/api/benchmarks')

  const modelProxyResponse = capture()
  await proxyRoute.handler({
    method: 'POST',
    url: '/studio-panel/api/model/routes',
    async *[Symbol.asyncIterator]() { yield Buffer.from('{"routes":{}}') },
  }, modelProxyResponse)
  assert.equal(modelProxyResponse.status, 200)
  assert.equal(new URL(proxyRequests[2].url).pathname, '/api/model/routes')
  const taskListResponse = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/tasks' }, taskListResponse)
  const compactTasks = JSON.parse(taskListResponse.body).data.tasks
  const compactTask = compactTasks[0]
  assert.deepEqual(compactTask.result, {
    run_id: 'bench_smoke', status: 'completed', artifact_path: '/tmp/bench.json',
    context_hash: 'sha256:test', summary: { average_quality_score: 86 },
  })
  assert.deepEqual(compactTasks[1].result.review_v2, {
    schema_version: 'openwrite.review.v2',
    execution_status: 'completed', quality_score: 84, coverage: 0.92,
    gate_status: 'blocked', delivery_status: 'blocked',
    production_gate_status: 'disabled_uncalibrated',
    freshness_status: 'current', source_revision: 'sha256:smoke',
    current_source_revision: 'sha256:smoke',
  })
  assert.deepEqual(compactTasks[1].result.issue_details, [{
    severity: 'critical', review_severity: 'critical', revision_priority: 'blocker',
    dimension: 2, category: 'logic', summary: 'Broken causal link',
  }])
  assert.equal(taskListResponse.body.includes('"domains"'), false)
  assert.equal(taskListResponse.body.includes('"evidence"'), false)
  assert.equal(taskListResponse.body.includes('large candidate content'), false)
} finally {
  globalThis.fetch = originalFetch
}
const changedInvalidation = capture()
await invalidationRoute.handler({ method: 'GET' }, changedInvalidation)
assert.deepEqual(JSON.parse(changedInvalidation.body), {
  revision: 4,
  resource: 'models',
  path: '/api/model/routes',
})
assert.match(eventResponse.chunks.join(''), /event: invalidate/)

const dogWorkspace = await mkdtemp(join(tmpdir(), 'dsh-novel-dog-smoke-'))
try {
  const legacyFailed = buildDogReviewBundle({
    score: 90, passed: false,
    issue_details: [{ dimension: 7, severity: 'warning', description: 'Slow opening' }],
  }, 'ch_008', 70)
  assert.equal(legacyFailed.manifest.gateStatus, 'pass')
  assert.equal(legacyFailed.manifest.deliveryStatus, 'revise')

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
  assert.equal(Object.keys(graph.nodes).length, 47)
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
    score: 90, passed: false, source_revision: revision,
    issue_details: [{ id: 'issue-warning', severity: 'warning', dimension: 7 }],
  }), 'utf8')
  const legacyFailedDelivery = await materializeChapterDelivery({
    project: { root: dogWorkspace }, snapshot: { novel_id: 'smoke-book' },
  }, 'ch_009', 70)
  assert.equal(legacyFailedDelivery.readyForDelivery, false)
  assert.equal(legacyFailedDelivery.stages.closure, 'review_failed')

  await writeFile(join(dogWorkspace, 'data/novels/smoke-book/data/reviews/ch_009.json'), JSON.stringify({
    score: 90, passed: true, source_revision: revision, issue_details: [],
  }), 'utf8')
  const delivery = await materializeChapterDelivery({
    project: { root: dogWorkspace }, snapshot: { novel_id: 'smoke-book' },
  }, 'ch_009', 70)
  assert.equal(delivery.readyForDelivery, true)
  const deliveryGraph = JSON.parse(await readFile(delivery.graphPath, 'utf8'))
  assert.deepEqual(deliveryGraph.dependsOn.map(edge => `${edge.source}->${edge.target}`), [
    'review->writing', 'revision->review', 'application->revision',
    'rereview->application', 'closure->rereview',
  ])
} finally {
  await rm(dogWorkspace, { recursive: true, force: true })
}

await root.fiber.dispose()

console.log('smoke ok:', { name: mod.name, inject: mod.inject, tools: registered.length, config: resolved })
