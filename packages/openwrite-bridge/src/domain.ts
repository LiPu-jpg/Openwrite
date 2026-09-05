import { Service, type Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-host-webserver'
import type { ToolRunContext } from '@deepseek-ai/dsh-tools'
import { StudioClient, type WorkspaceContext } from './client.js'
import { workspaceContextFromExec } from './tools.js'

export const CONFIG_ROUTE = '/studio-panel/config.json'
export const API_PROXY_ROUTE = '/studio-panel/api'
export const EVENTS_ROUTE = '/studio-panel/events'
export const INVALIDATION_ROUTE = '/studio-panel/invalidation.json'

const PROXY_TIMEOUT_MS = 60_000
/** Cap for the best-effort upstream context_epoch read; never blocks a snapshot longer. */
const CONTEXT_EPOCH_TIMEOUT_MS = 5_000
const WRITABLE_PATHS = new Set([
  'assets',
  'assets/update',
  'assets/package/import',
  'outline/edit',
  'rolling-plans',
  'narrative-forecasts',
  'sync',
  'import/preview',
  'import',
  'manuscript-imports/prepare',
  'manuscript-imports/structure',
  'manuscript-imports/confirm',
  'manuscript-imports/run',
  'manuscript-imports/discard',
  'project-archives/create',
  'project-archives/restore/preview',
  'project-archives/restore',
  'reading-order/move',
  'scenes/migration/apply',
  'scenes/migration/rollback',
  'scenes/metadata',
  'scenes/move',
  'tasks',
  'benchmarks',
  'document',
  'document/change-plan',
  'structured/change-plan',
  'manuscript-editing',
  'manuscript/acceptance/baseline',
  'manuscript/acceptance/external',
  'manuscript/acceptance/reconcile',
  'manuscript/acceptance/ack',
  'project/init',
  'model',
  'model/test',
  'model/embedding/test',
  'model/embedding',
  'model/embedding/select',
  'model/embedding/delete',
  'model/profiles',
  'model/profiles/delete',
  'model/routes',
  'chapter/delete-batch',
  'research/settings',
])
const WRITABLE_PATH_RE = /^(?:tasks\/[A-Za-z0-9_-]+\/(?:cancel|retry|confirm)|revisions\/(?:selection|from-review|rev_[A-Za-z0-9_-]+\/(?:apply|reject|regenerate)))$/

/** Mutation/SSE state bucket key for context-less (legacy) mutations. */
const LEGACY_ROOT_KEY = ''

interface ProxyRequest {
  method?: string
  url?: string
  headers?: Record<string, string | string[] | undefined>
  [Symbol.asyncIterator]?: () => AsyncIterableIterator<Buffer | string>
}

interface ProxyResponse {
  writeHead: (status: number, headers?: Record<string, string>) => void
  write: (body: string | Buffer) => void
  end: (body?: string | Buffer) => void
  on?: (event: string, listener: () => void) => void
}

type WebRouteHandler = (req: ProxyRequest, res: ProxyResponse) => void | Promise<void>

declare module '@deepseek-ai/cordis' {
  interface Context {
    novelDomain: NovelDomainService
  }
}

function sendJson(res: ProxyResponse, status: number, payload: unknown): void {
  const body = Buffer.from(JSON.stringify(payload))
  res.writeHead(status, {
    'content-type': 'application/json',
    'cache-control': 'no-cache',
    'content-length': String(body.length),
  })
  res.end(body)
}

async function readBody(req: ProxyRequest): Promise<Buffer> {
  const iterator = req[Symbol.asyncIterator]
  if (iterator === undefined) return Buffer.alloc(0)
  const chunks: Buffer[] = []
  for await (const chunk of iterator.call(req)) {
    chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk)
  }
  return Buffer.concat(chunks)
}

function resourceForPath(path: string): string {
  if (path.startsWith('/api/manuscript-imports')) return 'tasks'
  if (path.startsWith('/api/project-archives')) return 'workspace'
  if (path.startsWith('/api/document') || path.startsWith('/api/write') || path.startsWith('/api/manuscript/acceptance')) return 'manuscript'
  if (path.startsWith('/api/outline')) return 'outline'
  if (path.startsWith('/api/scenes')) return 'outline'
  if (path.startsWith('/api/assets')) return 'assets'
  if (path.startsWith('/api/tasks') || path.startsWith('/api/review')) return 'tasks'
  if (path.startsWith('/api/benchmarks')) return 'benchmark'
  if (path.startsWith('/api/model')) return 'models'
  if (path.startsWith('/api/research')) return 'research'
  if (path.startsWith('/api/revisions')) return 'revisions'
  return 'workspace'
}

function compactTaskList(bytes: Buffer, pathPart: string, method: string): Buffer {
  if (method !== 'GET' || pathPart !== 'tasks') return bytes
  try {
    const envelope = JSON.parse(bytes.toString('utf8')) as Record<string, unknown>
    const data = envelope['data'] as Record<string, unknown> | undefined
    if (data === undefined || !Array.isArray(data['tasks'])) return bytes
    const tasks = data['tasks'].map((raw: unknown) => {
      if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return raw
      const task = raw as Record<string, unknown>
      const result = task['result'] !== null && typeof task['result'] === 'object' && !Array.isArray(task['result'])
        ? task['result'] as Record<string, unknown>
        : null
      const reviewV2 = result?.['review_v2'] !== null && typeof result?.['review_v2'] === 'object' && !Array.isArray(result?.['review_v2'])
        ? result['review_v2'] as Record<string, unknown>
        : null
      const reviewResult = task['type'] === 'chapter_review' && result !== null
        ? {
            score: result['score'],
            passed: result['passed'],
            issues: result['issues'],
            summary: result['summary'],
            review_v2: reviewV2 === null ? undefined : {
              schema_version: reviewV2['schema_version'],
              execution_status: reviewV2['execution_status'],
              quality_score: reviewV2['quality_score'],
              coverage: reviewV2['coverage'],
              gate_status: reviewV2['gate_status'],
              delivery_status: reviewV2['delivery_status'],
              production_gate_status: reviewV2['production_gate_status'],
              freshness_status: reviewV2['freshness_status'],
              source_revision: reviewV2['source_revision'],
              current_source_revision: reviewV2['current_source_revision'],
            },
            issue_details: Array.isArray(result['issue_details'])
              ? result['issue_details'].map((rawIssue: unknown) => {
                  const issue = rawIssue !== null && typeof rawIssue === 'object' && !Array.isArray(rawIssue)
                    ? rawIssue as Record<string, unknown>
                    : {}
                  return {
                    severity: issue['severity'],
                    review_severity: issue['review_severity'],
                    revision_priority: issue['revision_priority'],
                    legacy_severity: issue['legacy_severity'],
                    dimension: issue['dimension'],
                    category: issue['category'],
                    summary: issue['summary'] ?? issue['description'],
                  }
                })
              : [],
          }
        : null
      const benchmarkResult = task['type'] === 'model_benchmark' && result !== null
        ? {
            run_id: result['run_id'], status: result['status'], artifact_path: result['artifact_path'],
            context_hash: result['context_hash'], summary: result['summary'],
          }
        : null
      return {
        task_id: task['task_id'],
        type: task['type'],
        status: task['status'],
        phase: task['phase'],
        phase_index: task['phase_index'],
        progress: task['progress'],
        chapter_id: task['chapter_id'],
        input_summary: task['input_summary'],
        error: task['error'],
        retryable: task['retryable'],
        attempt: task['attempt'],
        created_at: task['created_at'],
        updated_at: task['updated_at'],
        started_at: task['started_at'],
        completed_at: task['completed_at'],
        result_ref: task['result_ref'],
        schema_version: task['schema_version'],
        result: reviewResult ?? benchmarkResult,
      }
    })
    return Buffer.from(JSON.stringify({ ...envelope, data: { ...data, tasks } }))
  } catch {
    return bytes
  }
}

export interface NovelDomainOptions {
  baseUrl: string
  timeoutMs: number
  /**
   * Host-trusted workspace_id → canonical root resolution (dsh
   * `ctx.workspaceRegistry`), looked up lazily per call so plugin start order
   * cannot strand it. Absent resolver or a `null` result means the registry
   * service itself is missing: every browser entry fails closed with
   * WORKSPACE_REGISTRY_UNAVAILABLE. `undefined` means unknown id.
   */
  resolveWorkspace?: (workspaceId: string) => string | undefined | null
}

interface RootState {
  revision: number
  lastMutation: { revision: number, resource: string, path: string }
}

interface WorkspaceRejection {
  status: number
  code: string
  message: string
}

/** Read a single-valued request header (node lowercases header names). */
function headerValue(req: ProxyRequest, name: string): string | undefined {
  const value = req.headers?.[name]
  return typeof value === 'string' && value !== '' ? value : undefined
}

/** Read the `?workspace=` query parameter of a route URL. */
function workspaceParam(req: ProxyRequest): string | undefined {
  const value = new URL(req.url ?? '/', 'http://localhost').searchParams.get('workspace')
  return value === null || value === '' ? undefined : value
}

/** Single host-side boundary shared by agent tools, browser proxy and live invalidation. */
export class NovelDomainService extends Service {
  readonly client: StudioClient
  readonly baseUrl: string
  private readonly resolveWorkspace: ((workspaceId: string) => string | undefined | null) | undefined
  /** Per-root invalidation state, keyed by canonical workspace root ('' = legacy). */
  private readonly roots = new Map<string, RootState>()
  /** Open SSE connections bound to the root key they subscribed to. */
  private readonly streams = new Map<ProxyResponse, string>()

  constructor(ctx: Context, options: NovelDomainOptions) {
    super(ctx, 'novelDomain')
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.resolveWorkspace = options.resolveWorkspace
    this.client = new StudioClient({
      baseUrl: this.baseUrl,
      timeoutMs: options.timeoutMs,
      onMutation: (path, context) => this.notifyMutation(path, context),
    })
  }

  /**
   * Factory for the tool surface: every tool execution derives its own
   * request-scoped client from the dsh session context (fail closed).
   */
  clientFactory(): (exec: ToolRunContext) => StudioClient {
    return exec => this.client.scoped(workspaceContextFromExec(exec))
  }

  /** Record a mutation under its root and broadcast only to that root's SSE connections. */
  notifyMutation(path: string, context?: WorkspaceContext): void {
    const root = context?.workspaceRoot ?? LEGACY_ROOT_KEY
    const state = this.roots.get(root) ?? { revision: 0, lastMutation: { revision: 0, resource: 'workspace', path: '' } }
    state.revision += 1
    state.lastMutation = { revision: state.revision, resource: resourceForPath(path), path }
    this.roots.set(root, state)
    const event = JSON.stringify({ workspace_root: root, ...state.lastMutation })
    for (const [stream, key] of this.streams) {
      if (key === root) stream.write(`event: invalidate\ndata: ${event}\n\n`)
    }
  }

  /** Snapshot of one root's invalidation state (zero revision when never mutated). */
  private snapshotFor(root: string): Record<string, unknown> {
    const state = this.roots.get(root)
    if (state === undefined) return { revision: 0, resource: null, path: null, workspace_root: root }
    return { workspace_root: root, ...state.lastMutation }
  }

  /**
   * Best-effort read of the upstream per-root context epoch (the only signal
   * that background task transitions bump). ANY failure — network, non-2xx,
   * missing/invalid field — degrades to null so the caller omits the field;
   * this helper never throws and never breaks a snapshot.
   */
  private async fetchContextEpoch(root: string, id: string, signal?: AbortSignal): Promise<number | null> {
    try {
      const timeout = AbortSignal.timeout(CONTEXT_EPOCH_TIMEOUT_MS)
      const payload = await this.client
        .scoped({ workspaceRoot: root, workspaceId: id })
        .getJson('/api/workspace/context', {}, signal === undefined ? timeout : AbortSignal.any([timeout, signal]))
      const epoch = (payload as Record<string, unknown> | null)?.['context_epoch']
      return typeof epoch === 'number' && Number.isFinite(epoch) ? epoch : null
    } catch {
      return null
    }
  }

  /**
   * Resolve a browser-supplied workspace id through the host registry, failing
   * closed per the contract: missing id → 400 WORKSPACE_CONTEXT_MISSING, no
   * registry → 503 WORKSPACE_REGISTRY_UNAVAILABLE, unknown id → 400 WORKSPACE_UNKNOWN.
   */
  private resolveBrowserWorkspace(id: string | undefined): { root: string, id: string } | { rejection: WorkspaceRejection } {
    if (id === undefined) {
      return { rejection: { status: 400, code: 'WORKSPACE_CONTEXT_MISSING', message: 'missing workspace id (x-dsh-workspace-id header or ?workspace= param)' } }
    }
    if (this.resolveWorkspace === undefined) {
      return { rejection: { status: 503, code: 'WORKSPACE_REGISTRY_UNAVAILABLE', message: 'host workspaceRegistry service is not available' } }
    }
    const root = this.resolveWorkspace(id)
    if (root === null) {
      return { rejection: { status: 503, code: 'WORKSPACE_REGISTRY_UNAVAILABLE', message: 'host workspaceRegistry service is not available' } }
    }
    if (root === undefined) {
      return { rejection: { status: 400, code: 'WORKSPACE_UNKNOWN', message: `workspace id is not registered: ${id}` } }
    }
    return { root, id }
  }

  private static sendRejection(res: ProxyResponse, rejection: WorkspaceRejection): void {
    sendJson(res, rejection.status, { error: rejection.message, code: rejection.code })
  }

  registerWebRoutes(ctx: Context): void {
    // These responses belong to this webServer injection scope. Removing a
    // route does not close requests already handled by it; end them explicitly
    // so EventSource reconnects to the newly mounted plugin after a reload.
    const responses = new Set<ProxyResponse>()
    const lifetime = new AbortController()
    let disposed = false
    ctx.effect(() => () => {
      disposed = true
      lifetime.abort()
      for (const response of responses) {
        this.streams.delete(response)
        try { response.end() } catch { /* already disconnected */ }
      }
      responses.clear()
    }, 'novel-domain: close live invalidation responses')

    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path: CONFIG_ROUTE,
      handler: (req, res) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405)
          res.end()
          return
        }
        res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-cache' })
        res.end(JSON.stringify({ studioUrl: this.baseUrl }))
      },
    }), 'novel-domain: config route')
    ctx.effect(() => ctx.webServer.register({
      kind: 'prefix',
      path: API_PROXY_ROUTE,
      handler: this.createProxyHandler(),
    }), 'novel-domain: API proxy')
    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path: INVALIDATION_ROUTE,
      handler: async (req, res) => {
        if (disposed) {
          sendJson(res, 503, { error: 'novel-domain is reloading', code: 'NOVEL_DOMAIN_DISPOSED' })
          return
        }
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405)
          res.end()
          return
        }
        const resolved = this.resolveBrowserWorkspace(workspaceParam(req))
        if ('rejection' in resolved) {
          NovelDomainService.sendRejection(res, resolved.rejection)
          return
        }
        const snapshot = this.snapshotFor(resolved.root)
        // Merge the upstream context epoch (omitted when unreadable): this is
        // how polling clients observe background task transitions that never
        // touch the bridge-local revision.
        responses.add(res)
        const contextEpoch = await this.fetchContextEpoch(resolved.root, resolved.id, lifetime.signal)
        responses.delete(res)
        if (disposed) return
        sendJson(res, 200, contextEpoch === null ? snapshot : { ...snapshot, context_epoch: contextEpoch })
      },
    }), 'novel-domain: invalidation snapshot')
    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path: EVENTS_ROUTE,
      handler: async (req, res) => {
        if (disposed) {
          sendJson(res, 503, { error: 'novel-domain is reloading', code: 'NOVEL_DOMAIN_DISPOSED' })
          return
        }
        if (req.method !== 'GET') {
          res.writeHead(405)
          res.end()
          return
        }
        const resolved = this.resolveBrowserWorkspace(workspaceParam(req))
        if ('rejection' in resolved) {
          NovelDomainService.sendRejection(res, resolved.rejection)
          return
        }
        res.writeHead(200, {
          'content-type': 'text/event-stream',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        })
        responses.add(res)
        this.streams.set(res, resolved.root)
        const dispose = () => { this.streams.delete(res); responses.delete(res) }
        res.on?.('close', dispose)
        res.on?.('error', dispose)
        // The ready event carries the upstream context epoch when it is
        // readable; the stream waits for the fetch to settle (capped at
        // CONTEXT_EPOCH_TIMEOUT_MS), never longer. A client gone by then
        // simply never gets the ready event — polling carries epochs anyway.
        const revision = this.roots.get(resolved.root)?.revision ?? 0
        const contextEpoch = await this.fetchContextEpoch(resolved.root, resolved.id, lifetime.signal)
        if (disposed || !this.streams.has(res)) return
        const ready: Record<string, unknown> = { workspace_root: resolved.root, revision }
        if (contextEpoch !== null) ready['context_epoch'] = contextEpoch
        res.write(`event: ready\ndata: ${JSON.stringify(ready)}\n\n`)
      },
    }), 'novel-domain: invalidation stream')
  }

  private createProxyHandler(): WebRouteHandler {
    return async (req, res) => {
      const sub = (req.url ?? '').slice(API_PROXY_ROUTE.length)
      if (sub === '' || !sub.startsWith('/')) {
        sendJson(res, 404, { error: 'novel-domain proxy: missing API path' })
        return
      }
      // Every browser request carries only a workspace_id; the trusted host
      // registry resolves it to the canonical root (contract §2.2).
      const resolved = this.resolveBrowserWorkspace(headerValue(req, 'x-dsh-workspace-id'))
      if ('rejection' in resolved) {
        NovelDomainService.sendRejection(res, resolved.rejection)
        return
      }
      const method = req.method ?? 'GET'
      const pathPart = sub.split('?')[0]?.slice(1) ?? ''
      const isWrite = method === 'POST' || method === 'PUT'
      if (!isWrite && method !== 'GET' && method !== 'HEAD') {
        sendJson(res, 405, { error: 'novel-domain proxy allows only GET/HEAD and allowlisted writes' })
        return
      }
      if (isWrite && !WRITABLE_PATHS.has(pathPart) && !WRITABLE_PATH_RE.test(pathPart)) {
        sendJson(res, 405, { error: `novel-domain proxy: write path "${pathPart}" is not allowlisted` })
        return
      }
      try {
        const headers: Record<string, string> = {
          accept: 'application/json',
          'x-openwrite-workspace-root': resolved.root,
          'x-openwrite-workspace-id': resolved.id,
        }
        const sessionId = headerValue(req, 'x-dsh-session-id')
        if (sessionId !== undefined) headers['x-openwrite-session-id'] = sessionId
        let body: Buffer | undefined
        if (isWrite) {
          body = await readBody(req)
          headers['content-type'] = 'application/json'
          headers['x-openwrite-studio'] = '1'
        }
        const upstream = await fetch(new URL(`/api${sub}`, this.baseUrl), {
          method,
          headers,
          ...(body !== undefined ? { body: new Uint8Array(body) } : {}),
          signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
        })
        const upstreamBytes = Buffer.from(await upstream.arrayBuffer())
        const bytes = compactTaskList(upstreamBytes, pathPart, method)
        const responseHeaders: Record<string, string> = {
          'content-type': upstream.headers.get('content-type') ?? 'application/json',
          'cache-control': 'no-cache',
          'content-length': String(bytes.length),
        }
        const disposition = upstream.headers.get('content-disposition')
        if (disposition !== null) responseHeaders['content-disposition'] = disposition
        res.writeHead(upstream.status, responseHeaders)
        res.end(bytes)
        if (isWrite && upstream.ok) {
          this.notifyMutation(`/api/${pathPart}`, { workspaceRoot: resolved.root, workspaceId: resolved.id })
        }
      } catch (error) {
        sendJson(res, 502, {
          error: `OpenWrite Studio unreachable at ${this.baseUrl}: ${error instanceof Error ? error.message : String(error)}`,
        })
      }
    }
  }
}
