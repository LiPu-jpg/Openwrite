// Smoke check for the built plugin: asserts the dsh plugin export contract
// (name / inject / apply / Config) without starting any server.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context, Service } from '@deepseek-ai/cordis'
import * as mod from '../lib/index.js'
import { StudioClient } from '../lib/client.js'
import { materializeChapterDelivery } from '../lib/dog-delivery.js'
import {
  buildDogReviewBundle, DOG_REVIEW_DIMENSIONS, DOG_REVIEW_DOMAINS,
  dogReviewFrameworkRevision, materializeCompletedDogTaskReview,
} from '../lib/dog-review.js'

assert.equal(mod.name, '@dsh-novel/openwrite-bridge', 'name export')
assert.deepEqual(mod.inject, ['tools'], 'inject export')
assert.equal(typeof mod.apply, 'function', 'apply export')
assert.ok(mod.Config, 'Config schema export')

// The Schemastery schema must validate an empty config and fill defaults.
const resolved = mod.Config({})
assert.equal(resolved.baseUrl, 'http://127.0.0.1:4567')
assert.equal(resolved.timeoutMs, 600000)
assert.equal(typeof resolved.outputDir, 'string')

// Two canonical workspace roots (realpath'd: tmpdir is a symlink on macOS).
const wsRootA = await realpath(await mkdtemp(join(tmpdir(), 'dsh-novel-ws-a-')))
const wsRootB = await realpath(await mkdtemp(join(tmpdir(), 'dsh-novel-ws-b-')))

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
// Host-trusted workspace_id → canonical root registry (dsh ctx.workspaceRegistry).
const workspacePaths = new Map([['ws_a', wsRootA], ['ws_b', wsRootB]])
class WorkspaceRegistryService extends Service {
  constructor(ctx) { super(ctx, 'workspaceRegistry') }
  get(id) {
    const path = workspacePaths.get(id)
    return path === undefined ? undefined : { path }
  }
}
const root = new Context()
await root.plugin(ToolsService)
await root.plugin(WebServerService)
await root.plugin(WorkspaceRegistryService)
await root.plugin(mod, resolved)
const expected = [
  // reads, then writes — the registration order in src/tools.ts
  'novel_embedding_profiles', 'novel_embedding_profile_save', 'novel_embedding_profile_select', 'novel_embedding_profile_delete',
  'novel_status', 'novel_review_framework', 'novel_manuscript_acceptance', 'novel_trace_list', 'novel_context_preview', 'novel_outline_read',
  'novel_reading_order', 'novel_reading_packet', 'novel_chapter_work',
  'novel_scene_structure', 'novel_chapter_scenes', 'novel_scene_migration_preview', 'novel_assets_list',
  'novel_search', 'novel_doc_read',
  'novel_outline_edit', 'novel_reading_order_move', 'novel_scene_migration_apply',
  'novel_scene_migration_rollback', 'novel_scene_update', 'novel_scene_move',
  'novel_write_chapter', 'novel_review_chapter', 'novel_asset_update',
  'novel_foreshadowing', 'novel_doc_write', 'novel_document_change_plan', 'novel_structured_change_plan', 'novel_focus',
  'novel_export_preflight', 'novel_export',
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
  'novel_chapter_delete', 'novel_chapter_delete_batch', 'novel_doc_create', 'novel_import_preview', 'novel_import',
  'novel_manuscript_import_action', 'novel_project_archive_action', 'novel_project_archive_download',
  'novel_sync', 'novel_settle_backfill', 'novel_writing_targets',
  // continuity & diagnostics
  'novel_continuity', 'novel_diagnostics',
  // planning: chapter runs, rolling plans, forecasts, manuscript editing
  'novel_chapter_run_action', 'novel_rolling_plan_action', 'novel_narrative_forecast_action',
  'novel_manuscript_edit_action', 'novel_manuscript_acceptance_reconcile',
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
assert.match(
  registered.find(tool => tool.name === 'novel_task_create')?.description ?? '',
  /manuscript_reconcile/,
  'task creation documents durable manuscript reconciliation',
)

const documentPlanTool = registered.find(tool => tool.name === 'novel_document_change_plan')
assert.ok(documentPlanTool, 'document change plan tool is registered')
await assert.rejects(
  () => documentPlanTool.execute({ action: 'preview', path: 'src/story/background.md', edits: [
    { old_text: 'a', new_text: 'b' }, { old_text: 'c', new_text: 'd' },
  ] }, { signal: new AbortController().signal }),
  /exactly one edit/,
)
await assert.rejects(
  () => documentPlanTool.execute({ action: 'apply' }, { signal: new AbortController().signal }),
  /requires preview_token/,
)

const structuredPlanTool = registered.find(tool => tool.name === 'novel_structured_change_plan')
assert.ok(structuredPlanTool, 'structured change plan tool is registered')
await assert.rejects(
  () => structuredPlanTool.execute({ action: 'preview', change: {} }, { signal: new AbortController().signal }),
  /requires change_kind/,
)
await assert.rejects(
  () => structuredPlanTool.execute({ action: 'apply' }, { signal: new AbortController().signal }),
  /requires preview_token/,
)

// A tool execution stamped with a dsh session context (contract §2.1).
const exec = {
  name: 'novel_model_benchmark',
  callId: 'call_test_001',
  rootCallId: 'call_root_001',
  signal: new AbortController().signal,
  agent: { session: { header: { cwd: wsRootA, id: 'ses_test' } } },
}
const execNoAgent = { signal: new AbortController().signal }

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
  // Fail closed: without a session context no tool call may reach Studio at all.
  const benchmarkRequestCount = benchmarkRequests.length
  await assert.rejects(
    () => benchmarkTool.execute({ action: 'list' }, execNoAgent),
    error => error?.code === 'WORKSPACE_CONTEXT_MISSING' && error?.status === 400,
  )
  assert.equal(benchmarkRequests.length, benchmarkRequestCount, 'no HTTP request without Workspace context')
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
// Tool-derived requests carry the §3 context headers (root + session id).
for (const request of benchmarkRequests) {
  assert.equal(request.init.headers['X-OpenWrite-Workspace-Root'], wsRootA, 'context root header')
  assert.equal(request.init.headers['X-OpenWrite-Session-Id'], 'ses_test', 'context session header')
  assert.equal(request.init.headers['X-OpenWrite-Tool-Call-Id'], 'call_test_001', 'tool call header')
  assert.equal(request.init.headers['X-OpenWrite-Root-Call-Id'], 'call_root_001', 'root call header')
  assert.equal(request.init.headers['X-OpenWrite-Tool-Name'], 'novel_model_benchmark', 'tool name header')
}
assert.deepEqual(JSON.parse(benchmarkRequests[2].init.body), {
  writer_profile_ids: ['writer-a', 'writer-b'], reviewer_profile_ids: ['critic'],
  chapter_id: 'ch_003', execution_mode: 'framework', repeats: 2,
  target_words: 2400, concurrency: 2,
})

const exportPreflightTool = registered.find(tool => tool.name === 'novel_export_preflight')
assert.ok(exportPreflightTool, 'export preflight tool is registered')
const exportPreflightRequests = []
const exportPreflightFetch = globalThis.fetch
globalThis.fetch = async (input, init = {}) => {
  exportPreflightRequests.push({ url: String(input), init })
  return new Response(JSON.stringify({
    ok: true,
    data: {
      schema_version: 'openwrite.export-preflight.v1',
      format: 'epub',
      purpose: 'backup',
      can_export: true,
      preflight_revision: 'pf_test_001',
    },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
}
try {
  assert.deepEqual(await exportPreflightTool.execute({ format: 'epub', purpose: 'backup' }, {
    ...exec,
    name: 'novel_export_preflight',
  }), {
    schema_version: 'openwrite.export-preflight.v1',
    format: 'epub',
    purpose: 'backup',
    can_export: true,
    preflight_revision: 'pf_test_001',
  })
} finally {
  globalThis.fetch = exportPreflightFetch
}
assert.equal(new URL(exportPreflightRequests[0].url).pathname, '/api/export/preflight')
assert.equal(new URL(exportPreflightRequests[0].url).searchParams.get('format'), 'epub')
assert.equal(new URL(exportPreflightRequests[0].url).searchParams.get('purpose'), 'backup')
assert.equal(exportPreflightRequests[0].init.method, 'GET')

// Native author-workbench tools preserve stable identities and CAS fields.
{
  const workbenchRequests = []
  const workbenchFetch = globalThis.fetch
  globalThis.fetch = async (input, init = {}) => {
    workbenchRequests.push({ url: String(input), init })
    return new Response(JSON.stringify({ ok: true, data: { accepted: true } }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    await registered.find(tool => tool.name === 'novel_reading_order').execute({}, { ...exec, name: 'novel_reading_order' })
    await registered.find(tool => tool.name === 'novel_reading_packet').execute({
      document_id: 'doc_0123456789abcdef01234567', before: 2, after: 3,
    }, { ...exec, name: 'novel_reading_packet' })
    await registered.find(tool => tool.name === 'novel_chapter_work').execute({
      chapter_id: 'ch_003', document_id: 'doc_0123456789abcdef01234567', recent_limit: 7,
    }, { ...exec, name: 'novel_chapter_work' })
    await registered.find(tool => tool.name === 'novel_scene_structure').execute({}, { ...exec, name: 'novel_scene_structure' })
    await registered.find(tool => tool.name === 'novel_chapter_scenes').execute({
      chapter_id: 'ch_003',
    }, { ...exec, name: 'novel_chapter_scenes' })
    await registered.find(tool => tool.name === 'novel_scene_migration_preview').execute({}, { ...exec, name: 'novel_scene_migration_preview' })
  } finally {
    globalThis.fetch = workbenchFetch
  }
  assert.equal(new URL(workbenchRequests[0].url).pathname, '/api/reading-order')
  assert.equal(new URL(workbenchRequests[1].url).pathname, '/api/reading-packet')
  assert.equal(new URL(workbenchRequests[1].url).searchParams.get('before'), '2')
  assert.equal(new URL(workbenchRequests[1].url).searchParams.get('after'), '3')
  assert.equal(new URL(workbenchRequests[2].url).pathname, '/api/chapters/ch_003/work-brief')
  assert.equal(new URL(workbenchRequests[2].url).searchParams.get('recent_limit'), '7')
  assert.equal(new URL(workbenchRequests[3].url).pathname, '/api/scenes')
  assert.equal(new URL(workbenchRequests[4].url).pathname, '/api/chapters/ch_003/scenes')
  assert.equal(new URL(workbenchRequests[5].url).pathname, '/api/scenes/migration-preview')
}

// StudioClient.scoped: a fully-populated context stamps all four §3 headers;
// a legacy (unscoped) client stamps none.
{
  const scopedRequests = []
  const directFetch = globalThis.fetch
  globalThis.fetch = async (input, init = {}) => {
    scopedRequests.push({ url: String(input), init })
    return new Response(JSON.stringify({ ok: true, data: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    const base = new StudioClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 1000 })
    const scoped = base.scoped({
      workspaceRoot: wsRootA, workspaceId: 'ws_a', sessionId: 'ses_test', contextEpoch: 3,
      toolCallId: 'call_a', rootCallId: 'root_a', toolName: 'novel_status',
    })
    await scoped.getJson('/api/workspace')
    await scoped.postJson('/api/sync', {})
    await base.getJson('/api/workspace')
  } finally {
    globalThis.fetch = directFetch
  }
  for (const request of scopedRequests.slice(0, 2)) {
    assert.equal(request.init.headers['X-OpenWrite-Workspace-Root'], wsRootA)
    assert.equal(request.init.headers['X-OpenWrite-Workspace-Id'], 'ws_a')
    assert.equal(request.init.headers['X-OpenWrite-Session-Id'], 'ses_test')
    assert.equal(request.init.headers['X-OpenWrite-Context-Epoch'], '3')
    assert.equal(request.init.headers['X-OpenWrite-Tool-Call-Id'], 'call_a')
    assert.equal(request.init.headers['X-OpenWrite-Root-Call-Id'], 'root_a')
    assert.equal(request.init.headers['X-OpenWrite-Tool-Name'], 'novel_status')
  }
  assert.equal(scopedRequests[2].init.headers['X-OpenWrite-Workspace-Root'], undefined, 'legacy client sends no context headers')
  assert.equal(scopedRequests[2].init.headers['X-OpenWrite-Session-Id'], undefined)
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
const eventsRoute = routes.find(route => route.path === '/studio-panel/events')
// These assertions run without a stubbed upstream: fail the context_epoch
// read fast so a live Studio on the default port can never leak into them.
const preProxyFetch = globalThis.fetch
globalThis.fetch = async () => { throw new Error('smoke: no upstream available') }
const eventResponseA = capture()
const eventResponseB = capture()
try {
const benchmarkInvalidation = capture()
await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, benchmarkInvalidation)
assert.deepEqual(JSON.parse(benchmarkInvalidation.body), {
  revision: 1,
  resource: 'benchmark',
  path: '/api/benchmarks',
  workspace_root: wsRootA,
})
assert.equal(Number(benchmarkInvalidation.headers['content-length']), Buffer.byteLength(benchmarkInvalidation.body))
// A never-mutated root reports a zero snapshot.
const pristineInvalidation = capture()
await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_b' }, pristineInvalidation)
assert.deepEqual(JSON.parse(pristineInvalidation.body), {
  revision: 0, resource: null, path: null, workspace_root: wsRootB,
})

// SSE requires ?workspace=<id>.
const anonymousEvents = capture()
await eventsRoute.handler({ method: 'GET', url: '/studio-panel/events' }, anonymousEvents)
assert.equal(anonymousEvents.status, 400)
assert.equal(JSON.parse(anonymousEvents.body).code, 'WORKSPACE_CONTEXT_MISSING')

await eventsRoute.handler({ method: 'GET', url: '/studio-panel/events?workspace=ws_a' }, eventResponseA)
assert.equal(eventResponseA.status, 200)
assert.match(eventResponseA.headers['content-type'], /text\/event-stream/)
assert.match(eventResponseA.chunks.join(''), /event: ready/)
assert.match(eventResponseA.chunks.join(''), new RegExp(`"workspace_root":${JSON.stringify(wsRootA).replace(/[/.]/g, '\\$&')}`))
// No readable upstream → the ready event omits context_epoch entirely.
assert.equal(eventResponseA.chunks.join('').includes('context_epoch'), false)

await eventsRoute.handler({ method: 'GET', url: '/studio-panel/events?workspace=ws_b' }, eventResponseB)
assert.equal(eventResponseB.status, 200)
} finally {
  globalThis.fetch = preProxyFetch
}

const proxyRoute = routes.find(route => route.path === '/studio-panel/api')
const originalFetch = globalThis.fetch
const proxyRequests = []
globalThis.fetch = async (input, init = {}) => {
  const path = new URL(String(input)).pathname
  // The invalidation snapshot's context_epoch read is not proxied traffic;
  // keep it out of the index-based proxy assertions below.
  if (path !== '/api/workspace/context') proxyRequests.push({ url: String(input), init })
  const payload = path === '/api/tasks'
    ? {
        ok: true,
        data: {
          tasks: [
            {
              task_id: 'tsk_benchmark', type: 'model_benchmark', status: 'completed', phase: 'complete',
              schema_version: 'openwrite.task-surface.v1', phase_index: 6,
              progress: { completed_units: 10, total_units: 10, ratio: 1, unit_kind: 'candidates' },
              result_ref: { type: 'benchmark_run', id: 'bench_smoke' },
              started_at: '2026-08-31T10:00:00Z', completed_at: '2026-08-31T10:05:00Z',
              result: {
                run_id: 'bench_smoke', status: 'completed', artifact_path: '/tmp/bench.json',
                context_hash: 'sha256:test', summary: { average_quality_score: 86 },
                candidates: [{ content: 'large candidate content must be removed' }],
                evaluations: [{ quality_score: 86 }],
              },
            },
            {
              task_id: 'tsk_review', type: 'chapter_review', status: 'completed', phase: 'complete',
              schema_version: 'openwrite.task-surface.v1', phase_index: 6,
              error: { code: 'MODEL_TEST_TIMEOUT', message: 'upstream timed out', recoverable: true, failed_stage: 'model' },
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
    : path === '/api/model/routes'
      ? {
          // M1c envelope flip: model POSTs answer { ok, data, error, request_id }.
          ok: true,
          data: {
            routes: { chapter_write: 'default', review: 'default' },
            impact: { changed_routes: [{ route: 'review', from: 'old', to: 'default' }], profiles_affected: ['old', 'default'] },
          },
          error: null,
          request_id: 'req_smoke_routes',
        }
      : { ok: true }
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}
try {
  // Fail closed: missing / unknown workspace ids never reach Studio.
  const proxyRequestCount = proxyRequests.length
  const missingId = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/tasks' }, missingId)
  assert.equal(missingId.status, 400)
  assert.equal(JSON.parse(missingId.body).code, 'WORKSPACE_CONTEXT_MISSING')
  const unknownId = capture()
  await proxyRoute.handler({ method: 'GET', url: '/studio-panel/api/tasks', headers: { 'x-dsh-workspace-id': 'ws_nope' } }, unknownId)
  assert.equal(unknownId.status, 400)
  assert.equal(JSON.parse(unknownId.body).code, 'WORKSPACE_UNKNOWN')
  assert.equal(proxyRequests.length, proxyRequestCount, 'rejected proxy calls never reach Studio')

  // project/open is no longer an allowlisted browser write (contract §5).
  const projectOpen = capture()
  await proxyRoute.handler({
    method: 'POST',
    url: '/studio-panel/api/project/open',
    headers: { 'x-dsh-workspace-id': 'ws_a' },
    async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
  }, projectOpen)
  assert.equal(projectOpen.status, 405)

  const mutationResponse = capture()
  await proxyRoute.handler({
    method: 'PUT',
    url: '/studio-panel/api/document',
    headers: { 'x-dsh-workspace-id': 'ws_a', 'x-dsh-session-id': 'ses_browser' },
    async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
  }, mutationResponse)
  assert.equal(mutationResponse.status, 200)
  assert.equal(Number(mutationResponse.headers['content-length']), Buffer.byteLength(mutationResponse.body))
  // The proxy swaps the browser workspace id for §3 context headers upstream.
  assert.equal(proxyRequests[0].init.headers['x-openwrite-workspace-root'], wsRootA)
  assert.equal(proxyRequests[0].init.headers['x-openwrite-workspace-id'], 'ws_a')
  assert.equal(proxyRequests[0].init.headers['x-openwrite-session-id'], 'ses_browser')

  const documentInvalidation = capture()
  await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, documentInvalidation)
  assert.deepEqual(JSON.parse(documentInvalidation.body), {
    revision: 2,
    resource: 'manuscript',
    path: '/api/document',
    workspace_root: wsRootA,
  })
  // Root A's SSE stream observed the mutation; root B's stream did not.
  assert.match(eventResponseA.chunks.join(''), /event: invalidate/)
  assert.equal(eventResponseB.chunks.filter(chunk => chunk.includes('event: invalidate')).length, 0)

  const benchmarkProxyResponse = capture()
  await proxyRoute.handler({
    method: 'POST',
    url: '/studio-panel/api/benchmarks',
    headers: { 'x-dsh-workspace-id': 'ws_b' },
    async *[Symbol.asyncIterator]() { yield Buffer.from('{"writer_profile_ids":["writer"]}') },
  }, benchmarkProxyResponse)
  assert.equal(benchmarkProxyResponse.status, 200)
  assert.equal(proxyRequests[1].init.headers['x-openwrite-studio'], '1')
  assert.equal(proxyRequests[1].init.headers['x-openwrite-workspace-root'], wsRootB)
  assert.equal(new URL(proxyRequests[1].url).pathname, '/api/benchmarks')
  // Independent per-root revisions: B advances to 1 while A stays at 2.
  const bInvalidation = capture()
  await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_b' }, bInvalidation)
  assert.deepEqual(JSON.parse(bInvalidation.body), {
    revision: 1, resource: 'benchmark', path: '/api/benchmarks', workspace_root: wsRootB,
  })
  const stillA = capture()
  await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, stillA)
  assert.equal(JSON.parse(stillA.body).revision, 2, 'workspace A revision untouched by B mutation')
  // SSE filtering: the B invalidate went only to B's stream.
  assert.match(eventResponseB.chunks.join(''), /event: invalidate/)
  assert.match(eventResponseB.chunks.join(''), /"revision":1/)
  assert.equal(eventResponseA.chunks.some(chunk => chunk.includes(wsRootB)), false, 'workspace A stream never sees B events')

  const modelProxyResponse = capture()
  await proxyRoute.handler({
    method: 'POST',
    url: '/studio-panel/api/model/routes',
    headers: { 'x-dsh-workspace-id': 'ws_a' },
    async *[Symbol.asyncIterator]() { yield Buffer.from('{"routes":{}}') },
  }, modelProxyResponse)
  assert.equal(modelProxyResponse.status, 200)
  assert.equal(new URL(proxyRequests[2].url).pathname, '/api/model/routes')
  // The enveloped M1c model POST response passes through the proxy verbatim.
  const modelRoutesBody = JSON.parse(modelProxyResponse.body)
  assert.equal(modelRoutesBody.ok, true)
  assert.equal(modelRoutesBody.error, null)
  assert.equal(modelRoutesBody.request_id, 'req_smoke_routes')
  assert.deepEqual(modelRoutesBody.data.impact, {
    changed_routes: [{ route: 'review', from: 'old', to: 'default' }],
    profiles_affected: ['old', 'default'],
  })

  const taskListResponse = capture()
  await proxyRoute.handler({
    method: 'GET',
    url: '/studio-panel/api/tasks',
    headers: { 'x-dsh-workspace-id': 'ws_a' },
  }, taskListResponse)
  const compactTasks = JSON.parse(taskListResponse.body).data.tasks
  const compactTask = compactTasks[0]
  assert.deepEqual(compactTask.result, {
    run_id: 'bench_smoke', status: 'completed', artifact_path: '/tmp/bench.json',
    context_hash: 'sha256:test', summary: { average_quality_score: 86 },
  })
  // M1c task fields survive compaction (panel BenchmarkView reads them).
  assert.equal(compactTask.schema_version, 'openwrite.task-surface.v1')
  assert.equal(compactTask.phase_index, 6)
  assert.deepEqual(compactTask.progress, { completed_units: 10, total_units: 10, ratio: 1, unit_kind: 'candidates' })
  assert.deepEqual(compactTask.result_ref, { type: 'benchmark_run', id: 'bench_smoke' })
  assert.equal(compactTask.started_at, '2026-08-31T10:00:00Z')
  assert.equal(compactTask.completed_at, '2026-08-31T10:05:00Z')
  // error passes through whole, including the M1c failed_stage.
  assert.deepEqual(compactTasks[1].error, {
    code: 'MODEL_TEST_TIMEOUT', message: 'upstream timed out', recoverable: true, failed_stage: 'model',
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
globalThis.fetch = async () => { throw new Error('smoke: no upstream available') }
let changedInvalidation
try {
  changedInvalidation = capture()
  await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, changedInvalidation)
} finally {
  globalThis.fetch = originalFetch
}
assert.deepEqual(JSON.parse(changedInvalidation.body), {
  revision: 3,
  resource: 'models',
  path: '/api/model/routes',
  workspace_root: wsRootA,
})
assert.match(eventResponseA.chunks.join(''), /event: invalidate/)

// M2a allowlist completion: task confirm and research settings proxy through;
// a non-allowlisted sibling (tasks/{id}/delete) still fails closed with 405.
{
  const allowlistRequests = []
  const allowlistBase = globalThis.fetch
  globalThis.fetch = async (input, init = {}) => {
    allowlistRequests.push({ url: String(input), init })
    return new Response(JSON.stringify({ ok: true, data: { accepted: true } }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    const confirmResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/tasks/tsk_smoke/confirm',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
    }, confirmResponse)
    assert.equal(confirmResponse.status, 200)
    assert.equal(new URL(allowlistRequests[0].url).pathname, '/api/tasks/tsk_smoke/confirm')
    assert.equal(allowlistRequests[0].init.method, 'POST')

    const researchResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/research/settings',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
    }, researchResponse)
    assert.equal(researchResponse.status, 200)
    assert.equal(new URL(allowlistRequests[1].url).pathname, '/api/research/settings')

    const historyResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/manuscript-editing',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{"action":"versions","chapter_id":"ch_001"}') },
    }, historyResponse)
    assert.equal(historyResponse.status, 200)
    assert.equal(new URL(allowlistRequests[2].url).pathname, '/api/manuscript-editing')

    const revisionResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/revisions/rev_smoke1234/apply',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{"selected_hunk_ids":["hunk_0"]}') },
    }, revisionResponse)
    assert.equal(revisionResponse.status, 200)
    assert.equal(new URL(allowlistRequests[3].url).pathname, '/api/revisions/rev_smoke1234/apply')

    const structuredResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/structured/change-plan',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{"action":"apply","preview_token":"aaaaaaaaaaaaaaaaaaaaaaaa"}') },
    }, structuredResponse)
    assert.equal(structuredResponse.status, 200)
    assert.equal(new URL(allowlistRequests[4].url).pathname, '/api/structured/change-plan')

    for (const [route, body] of [
      ['baseline', '{"chapter_id":"ch_001","confirm":true}'],
      ['external', '{"chapter_id":"ch_001","confirm":true}'],
      ['reconcile', '{"chapter_id":"ch_001","operation_id":"op_smoke"}'],
      ['ack', '{"chapter_id":"ch_001","operation_id":"op_smoke","domains":["outline","foreshadowing"],"confirm":true}'],
    ]) {
      const acceptanceResponse = capture()
      await proxyRoute.handler({
        method: 'POST',
        url: `/studio-panel/api/manuscript/acceptance/${route}`,
        headers: { 'x-dsh-workspace-id': 'ws_a' },
        async *[Symbol.asyncIterator]() { yield Buffer.from(body) },
      }, acceptanceResponse)
      assert.equal(acceptanceResponse.status, 200)
      assert.equal(new URL(allowlistRequests.at(-1).url).pathname, `/api/manuscript/acceptance/${route}`)
    }

    for (const [path, body] of [
      ['/api/manuscript-imports/prepare', '{"filename":"mine.md","content":"# 第一章\\n正文","arc_id":"arc_001"}'],
      ['/api/manuscript-imports/structure', '{"import_id":"import_20260905000000_abcdef123456","expected_preview_revision":"sha256:preview","chapters":[]}'],
      ['/api/manuscript-imports/confirm', '{"import_id":"import_20260905000000_abcdef123456","expected_preview_revision":"sha256:preview","confirm":true}'],
      ['/api/manuscript-imports/run', '{"import_id":"import_20260905000000_abcdef123456"}'],
      ['/api/manuscript-imports/discard', '{"import_id":"import_20260905000000_abcdef123456","confirm":true}'],
      ['/api/project-archives/create', '{"expected_preflight_revision":"sha256:preflight"}'],
      ['/api/project-archives/restore/preview', '{"archive_id":"owa_0123456789abcdef01234567","target_root":"/tmp/restored","reference_policy":"preserve_relative"}'],
      ['/api/project-archives/restore', '{"archive_id":"owa_0123456789abcdef01234567","target_root":"/tmp/restored","archive_sha256":"sha256:archive","reference_policy":"preserve_relative","confirm":true}'],
      ['/api/reading-order/move', '{"document_id":"doc_0123456789abcdef01234567","target_volume_id":"volume_2","target_index":0,"expected_revision":"sha256:order"}'],
      ['/api/scenes/migration/apply', '{"expected_preview_revision":"sha256:preview","confirm":true}'],
      ['/api/scenes/migration/rollback', '{"migration_id":"scmig_0123456789abcdef","expected_revision":"sha256:scene"}'],
      ['/api/scenes/metadata', '{"scene_id":"scn_0123456789abcdef","expected_revision":"sha256:scene","title":"车站"}'],
      ['/api/scenes/move', '{"scene_id":"scn_0123456789abcdef","target_chapter_id":"ch_002","target_index":0,"expected_revision":"sha256:scene","expected_source_revision":"sha256:source","expected_target_revision":"sha256:target"}'],
    ]) {
      const transferResponse = capture()
      await proxyRoute.handler({
        method: 'POST', url: `/studio-panel${path}`,
        headers: { 'x-dsh-workspace-id': 'ws_a' },
        async *[Symbol.asyncIterator]() { yield Buffer.from(body) },
      }, transferResponse)
      assert.equal(transferResponse.status, 200, path)
      assert.equal(new URL(allowlistRequests.at(-1).url).pathname, path)
    }
    assert.match(eventResponseA.chunks.join(''), /"resource":"tasks","path":"\/api\/manuscript-imports\/prepare"/)
    assert.match(eventResponseA.chunks.join(''), /"resource":"workspace","path":"\/api\/project-archives\/create"/)

    const beforeStart = allowlistRequests.length
    const startResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/manuscript/acceptance/start',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{"chapter_id":"ch_001"}') },
    }, startResponse)
    assert.equal(startResponse.status, 405)
    assert.equal(allowlistRequests.length, beforeStart, 'acceptance start cannot bypass the confirmation gate')

    const beforeDelete = allowlistRequests.length
    const deleteResponse = capture()
    await proxyRoute.handler({
      method: 'POST',
      url: '/studio-panel/api/tasks/tsk_smoke/delete',
      headers: { 'x-dsh-workspace-id': 'ws_a' },
      async *[Symbol.asyncIterator]() { yield Buffer.from('{}') },
    }, deleteResponse)
    assert.equal(deleteResponse.status, 405)
    assert.equal(allowlistRequests.length, beforeDelete, 'rejected writes never reach Studio')
  } finally {
    globalThis.fetch = allowlistBase
  }
}

// M2a: invalidation snapshots and the SSE ready event merge the upstream
// context_epoch when readable…
{
  const epochBase = globalThis.fetch
  globalThis.fetch = async (input) => {
    assert.equal(new URL(String(input)).pathname, '/api/workspace/context')
    return new Response(JSON.stringify({ context_epoch: 7, mode: 'workspace' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    const epochInvalidation = capture()
    await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, epochInvalidation)
    const epochPayload = JSON.parse(epochInvalidation.body)
    assert.equal(epochPayload.context_epoch, 7)
    assert.equal(epochPayload.workspace_root, wsRootA)
    const epochEvents = capture()
    await eventsRoute.handler({ method: 'GET', url: '/studio-panel/events?workspace=ws_b' }, epochEvents)
    assert.match(epochEvents.chunks.join(''), /event: ready/)
    assert.match(epochEvents.chunks.join(''), /"context_epoch":7/)
  } finally {
    globalThis.fetch = epochBase
  }
}

// …and the field is omitted (never null/0) when the upstream read fails or
// lacks it entirely.
{
  const failingBase = globalThis.fetch
  globalThis.fetch = async () => new Response('boom', { status: 500 })
  try {
    const failedInvalidation = capture()
    await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, failedInvalidation)
    assert.equal('context_epoch' in JSON.parse(failedInvalidation.body), false)
    const failedEvents = capture()
    await eventsRoute.handler({ method: 'GET', url: '/studio-panel/events?workspace=ws_b' }, failedEvents)
    assert.equal(failedEvents.chunks.join('').includes('context_epoch'), false)
  } finally {
    globalThis.fetch = failingBase
  }
}
{
  const bareBase = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ mode: 'workspace' }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
  try {
    const bareInvalidation = capture()
    await invalidationRoute.handler({ method: 'GET', url: '/studio-panel/invalidation.json?workspace=ws_a' }, bareInvalidation)
    assert.equal('context_epoch' in JSON.parse(bareInvalidation.body), false)
  } finally {
    globalThis.fetch = bareBase
  }
}

// A host without ctx.workspaceRegistry fails closed with 503.
{
  const routes2 = []
  class ToolsService2 extends Service {
    constructor(ctx) { super(ctx, 'tools') }
    register() {}
  }
  class WebServerService2 extends Service {
    constructor(ctx) { super(ctx, 'webServer') }
    register(route) { routes2.push(route); return () => {} }
  }
  const root2 = new Context()
  await root2.plugin(ToolsService2)
  await root2.plugin(WebServerService2)
  await root2.plugin(mod, resolved)
  const proxy2 = routes2.find(route => route.path === '/studio-panel/api')
  const unavailable = capture()
  await proxy2.handler({
    method: 'GET',
    url: '/studio-panel/api/tasks',
    headers: { 'x-dsh-workspace-id': 'ws_a' },
  }, unavailable)
  assert.equal(unavailable.status, 503)
  assert.equal(JSON.parse(unavailable.body).code, 'WORKSPACE_REGISTRY_UNAVAILABLE')
  const events2 = routes2.find(route => route.path === '/studio-panel/events')
  const unavailableEvents = capture()
  await events2.handler({ method: 'GET', url: '/studio-panel/events?workspace=ws_a' }, unavailableEvents)
  assert.equal(unavailableEvents.status, 503)
  await root2.fiber.dispose()
}

const dogWorkspace = await mkdtemp(join(tmpdir(), 'dsh-novel-dog-smoke-'))
try {
  // Transport fixture: production obtains this immutable blueprint from
  // OpenWrite's /api/review/framework endpoint.
  const domainIds = DOG_REVIEW_DOMAINS.map(domain => `domain-${domain.id}`)
  const rootChildren = ['context', ...domainIds, 'gate', 'aggregate']
  const frameworkNodes = {
    root: { kind: 'composite', title_template: '{chapter_id} 评审 DAG', constraint: 'hard', artifact: 'review.json', verifier: { mode: 'programmatic', script: 'review-record' } },
    context: { kind: 'leaf', title: '上下文完整性', constraint: 'hard', artifact: 'context.json', verifier: { mode: 'programmatic', script: 'review-record' } },
    gate: { kind: 'composite', title: '硬门禁', constraint: 'hard', artifact: 'gate.json', verifier: { mode: 'programmatic', script: 'review-record' } },
    aggregate: { kind: 'leaf', title: '聚合与交付判定', constraint: 'hard', artifact: 'aggregate.json', verifier: { mode: 'programmatic', script: 'review-record' } },
  }
  const frameworkContains = rootChildren.map(child => ({ parent: 'root', child, required: true, failure: 'fatal' }))
  for (const domain of DOG_REVIEW_DOMAINS) {
    const domainId = `domain-${domain.id}`
    frameworkNodes[domainId] = { kind: 'composite', title: domain.name, constraint: 'soft', artifact: `domain_${domain.id}.json`, verifier: { mode: 'programmatic', script: 'review-record' } }
    for (const checkId of domain.legacyCheckIds) {
      const nodeId = `dim-${String(checkId).padStart(2, '0')}`
      frameworkNodes[nodeId] = { kind: 'leaf', title: `${checkId}. ${DOG_REVIEW_DIMENSIONS[checkId]}`, constraint: 'soft', artifact: `dim_${String(checkId).padStart(2, '0')}.json`, verifier: { mode: 'programmatic', script: 'review-dimension' } }
      frameworkContains.push({ parent: domainId, child: nodeId, required: true, failure: 'warn' })
    }
  }
  frameworkNodes['dim-27'] = { kind: 'leaf', title: '27. 敏感词检查', constraint: 'hard', artifact: 'dim_27.json', verifier: { mode: 'programmatic', script: 'review-dimension' } }
  frameworkContains.push({ parent: 'gate', child: 'dim-27', required: true, failure: 'fatal' })
  const frameworkDependsOn = [
    ...domainIds.map(source => ({ source, target: 'context', data: ['review-context'] })),
    { source: 'gate', target: 'context', data: ['review-context'] },
    ...domainIds.map(target => ({ source: 'aggregate', target, data: ['domain-result'] })),
    { source: 'aggregate', target: 'gate', data: ['gate-result'] },
  ]
  const reviewFramework = {
    schema_version: 'openwrite.review-dag-framework.v1', id: 'openwrite.standard-chapter-review',
    version: '1.0.0', rubric_version: 'openwrite.review-rubric.v2', graph_schema_version: '0.9', root: 'root', topology_locked: true,
    topology: { nodes: frameworkNodes, contains: frameworkContains, dependsOn: frameworkDependsOn },
    invariants: { node_count: 47, contains_count: 46, dependency_count: 14 },
  }
  reviewFramework.revision = dogReviewFrameworkRevision(reviewFramework)
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
  }, reviewFramework)
  assert.equal(dogReview.status, 'ready')
  const graph = JSON.parse(await readFile(dogReview.graphPath, 'utf8'))
  assert.equal(Object.keys(graph.nodes).length, 47)
  assert.equal(JSON.parse(await readFile(join(dogWorkspace, 'data/novels/smoke-book/data/dog/reviews/ch_009/dim_01.json'), 'utf8')).verdict, 'fail')
  assert.equal(JSON.parse(await readFile(join(dogWorkspace, 'data/novels/smoke-book/data/dog/reviews/ch_009/dim_03.json'), 'utf8')).verdict, 'inconclusive')
  const manifest = JSON.parse(await readFile(join(dogWorkspace, 'data/novels/smoke-book/data/dog/reviews/ch_009/review.json'), 'utf8'))
  assert.equal(manifest.issueCount, 2)
  assert.equal(manifest.unmappedIssueCount, 1)
  assert.equal(await materializeCompletedDogTaskReview({ task: { type: 'chapter_write', status: 'completed' } }, {}, reviewFramework), undefined)

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

  // Anti-drift: a payload root matching the canonical context root passes…
  const canonicalDogWorkspace = await realpath(dogWorkspace)
  const matched = await materializeChapterDelivery({
    project: { root: dogWorkspace }, snapshot: { novel_id: 'smoke-book' },
  }, 'ch_009', 70, canonicalDogWorkspace)
  assert.equal(matched.readyForDelivery, true)
  // …a different context root is rejected as WORKSPACE_CONTEXT_MISMATCH…
  await assert.rejects(
    () => materializeChapterDelivery({
      project: { root: dogWorkspace }, snapshot: { novel_id: 'smoke-book' },
    }, 'ch_009', 70, join(canonicalDogWorkspace, 'elsewhere')),
    error => error?.code === 'WORKSPACE_CONTEXT_MISMATCH' && error?.status === 409,
  )
  // …and so is a write target escaping the root via a hostile novel_id.
  await assert.rejects(
    () => materializeChapterDelivery({
      project: { root: dogWorkspace }, snapshot: { novel_id: '../../..' },
    }, 'ch_009', 70),
    error => error?.code === 'WORKSPACE_CONTEXT_MISMATCH' && error?.status === 409,
  )
} finally {
  await rm(dogWorkspace, { recursive: true, force: true })
}

// Tool route mapping runs after invalidation revision assertions so its write
// does not disturb the proxy state-machine checks above.
const acceptanceReadTool = registered.find(tool => tool.name === 'novel_manuscript_acceptance')
const acceptanceReconcileTool = registered.find(tool => tool.name === 'novel_manuscript_acceptance_reconcile')
assert.ok(acceptanceReadTool, 'manuscript acceptance read tool is registered')
assert.ok(acceptanceReconcileTool, 'manuscript acceptance reconcile tool is registered')
{
  const acceptanceRequests = []
  const acceptanceFetch = globalThis.fetch
  globalThis.fetch = async (input, init = {}) => {
    acceptanceRequests.push({ url: String(input), init })
    return new Response(JSON.stringify({ ok: true, data: { status: 'pending', operation_id: 'op_smoke' } }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    const acceptanceExec = { ...exec, name: 'novel_manuscript_acceptance' }
    assert.deepEqual(await acceptanceReadTool.execute({}, acceptanceExec), { status: 'pending', operation_id: 'op_smoke' })
    const mutationExec = { ...exec, name: 'novel_manuscript_acceptance_reconcile' }
    await acceptanceReconcileTool.execute({ action: 'baseline', chapter_id: 'ch_003', confirm: true }, mutationExec)
    await acceptanceReconcileTool.execute({ action: 'external', chapter_id: 'ch_003', confirm: true }, mutationExec)
    await acceptanceReconcileTool.execute({
      action: 'resume', chapter_id: 'ch_003', operation_id: 'op_smoke', domains: ['facts', 'context'],
    }, mutationExec)
    await acceptanceReconcileTool.execute({
      action: 'acknowledge', chapter_id: 'ch_003', operation_id: 'op_smoke', confirm: true,
    }, mutationExec)
    const requestCount = acceptanceRequests.length
    await assert.rejects(
      () => acceptanceReconcileTool.execute({ action: 'external', chapter_id: '../bad', confirm: true }, exec),
      /chapter_id must match/,
    )
    assert.equal(acceptanceRequests.length, requestCount, 'invalid chapter ids never reach Studio')
  } finally {
    globalThis.fetch = acceptanceFetch
  }
  assert.equal(new URL(acceptanceRequests[0].url).pathname, '/api/manuscript/acceptance')
  assert.equal(acceptanceRequests[0].init.method, 'GET')
  assert.deepEqual(acceptanceRequests.slice(1).map(request => new URL(request.url).pathname), [
    '/api/manuscript/acceptance/baseline',
    '/api/manuscript/acceptance/external',
    '/api/manuscript/acceptance/reconcile',
    '/api/manuscript/acceptance/ack',
  ])
  assert.ok(acceptanceRequests.slice(1).every(request => request.init.method === 'POST'))
  assert.deepEqual(JSON.parse(acceptanceRequests[3].init.body), {
    chapter_id: 'ch_003', operation_id: 'op_smoke', domains: ['facts', 'context'],
  })
  assert.deepEqual(JSON.parse(acceptanceRequests[4].init.body), {
    chapter_id: 'ch_003', operation_id: 'op_smoke', confirm: true,
    domains: ['outline', 'foreshadowing'],
  })
}

const manuscriptImportTool = registered.find(tool => tool.name === 'novel_manuscript_import_action')
const projectArchiveTool = registered.find(tool => tool.name === 'novel_project_archive_action')
assert.ok(manuscriptImportTool, 'resumable manuscript import tool is registered')
assert.ok(projectArchiveTool, 'project archive lifecycle tool is registered')
{
  const transferRequests = []
  const transferFetch = globalThis.fetch
  globalThis.fetch = async (input, init = {}) => {
    transferRequests.push({ url: String(input), init })
    return new Response(JSON.stringify({ ok: true, data: { accepted: true } }), {
      status: 200, headers: { 'content-type': 'application/json' },
    })
  }
  const importId = 'import_20260905000000_abcdef123456'
  const archiveId = 'owa_0123456789abcdef01234567'
  try {
    const importExec = { ...exec, name: 'novel_manuscript_import_action' }
    await manuscriptImportTool.execute({ action: 'list', limit: 12 }, importExec)
    await manuscriptImportTool.execute({ action: 'get', import_id: importId }, importExec)
    await manuscriptImportTool.execute({ action: 'prepare', filename: 'mine.md', content: '# 第一章\n正文', arc_id: 'arc_001', start_number: 3 }, importExec)
    await manuscriptImportTool.execute({ action: 'structure', import_id: importId, expected_preview_revision: 'sha256:preview', chapters: [{ chapter_id: 'ch_003', title: '第一章', content: '正文' }] }, importExec)
    await manuscriptImportTool.execute({ action: 'confirm', import_id: importId, expected_preview_revision: 'sha256:preview', confirm: true }, importExec)
    await manuscriptImportTool.execute({ action: 'run', import_id: importId }, importExec)
    await manuscriptImportTool.execute({ action: 'discard', import_id: importId, confirm: true }, importExec)
    const archiveExec = { ...exec, name: 'novel_project_archive_action' }
    await projectArchiveTool.execute({ action: 'preflight' }, archiveExec)
    await projectArchiveTool.execute({ action: 'list' }, archiveExec)
    await projectArchiveTool.execute({ action: 'get', archive_id: archiveId }, archiveExec)
    await projectArchiveTool.execute({ action: 'create', expected_preflight_revision: 'sha256:preflight' }, archiveExec)
    await projectArchiveTool.execute({ action: 'restore_preview', archive_id: archiveId, target_root: '/tmp/restored', reference_policy: 'rewrite_novel_id', target_novel_id: 'restored' }, archiveExec)
    await projectArchiveTool.execute({ action: 'restore', archive_id: archiveId, target_root: '/tmp/restored', reference_policy: 'rewrite_novel_id', target_novel_id: 'restored', archive_sha256: 'sha256:archive', confirm: true }, archiveExec)
  } finally {
    globalThis.fetch = transferFetch
  }
  assert.deepEqual(transferRequests.map(request => [request.init.method, new URL(request.url).pathname]), [
    ['GET', '/api/manuscript-imports'], ['GET', `/api/manuscript-imports/${importId}`],
    ['POST', '/api/manuscript-imports/prepare'], ['POST', '/api/manuscript-imports/structure'],
    ['POST', '/api/manuscript-imports/confirm'], ['POST', '/api/manuscript-imports/run'],
    ['POST', '/api/manuscript-imports/discard'], ['GET', '/api/project-archives/preflight'],
    ['GET', '/api/project-archives'], ['GET', `/api/project-archives/${archiveId}`],
    ['POST', '/api/project-archives/create'], ['POST', '/api/project-archives/restore/preview'],
    ['POST', '/api/project-archives/restore'],
  ])
  assert.equal(new URL(transferRequests[0].url).searchParams.get('limit'), '12')
  assert.deepEqual(JSON.parse(transferRequests[12].init.body), {
    archive_id: archiveId, target_root: '/tmp/restored', reference_policy: 'rewrite_novel_id',
    target_novel_id: 'restored', archive_sha256: 'sha256:archive', confirm: true,
  })
}

await root.fiber.dispose()
await rm(wsRootA, { recursive: true, force: true })
await rm(wsRootB, { recursive: true, force: true })

console.log('smoke ok:', { name: mod.name, inject: mod.inject, tools: registered.length, config: resolved })
