import type { BackendConnection } from './managed-runtime.js'
import { Service, type Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-host-webserver'
import type { ToolRunContext } from '@deepseek-ai/dsh-tools'
import { StudioClient, StudioError, workspaceRootHeaders, workspaceRootsEqual, mutationAffectsState, type WorkspaceContext } from './client.js'
import { workspaceContextFromExec } from './tools.js'

export const CONFIG_ROUTE = '/studio-panel/config.json'
export const API_PROXY_ROUTE = '/studio-panel/api'
export const EVENTS_ROUTE = '/studio-panel/events'
export const INVALIDATION_ROUTE = '/studio-panel/invalidation.json'

const PROXY_TIMEOUT_MS = 60_000
/** Cap for the best-effort upstream context_epoch read; never blocks a snapshot longer. */
const CONTEXT_EPOCH_TIMEOUT_MS = 5_000
/** Every browser write path the proxy forwards. Exported for the regression test. */
export const WRITABLE_PATHS = new Set([
  'writing-assets',
  'arc-reconcile',
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
  'manuscript/drafts/restore',
  'manuscript/acceptance/baseline',
  'manuscript/acceptance/external',
  'manuscript/acceptance/reconcile',
  'manuscript/acceptance/ack',
  'manuscript/acceptance/abandon',
  'review/history',
  'project/init',
  'project/metadata',
  'model',
  'model/test',
  'model/embedding/test',
  'model/embedding',
  'model/embedding/select',
  'model/embedding/delete',
  'model/profiles',
  'model/profiles/delete',
  // The two-step delete the panel drives: preview first, then the real delete.
  'model/profiles/delete-preview',
  'model/routes',
  // One profile that calls a model of the host's own directory.
  'model/host-profiles',
  'chapter/delete-batch',
  'research/settings',
  'research/preferences',
])
export const WRITABLE_PATH_RE = /^(?:tasks\/[A-Za-z0-9_-]+\/(?:cancel|retry|confirm)|revisions\/(?:selection|from-review|rev_[A-Za-z0-9_-]+\/(?:apply|reject|regenerate)))$/

/**
 * Paths whose payload is global, not project-scoped.
 *
 * The model profile library lives outside every project — Studio keeps it in
 * the user's preferences directory (`model-profiles.json`), and every model
 * route is registered with `requires_project=False`. The host settings dialog
 * is the one surface that is opened *without* a bound workspace, so these
 * paths must be reachable without a workspace id: the browser sends no
 * `X-Dsh-Workspace-Id` and the proxy forwards the call without a project
 * root, exactly as the contract's project-free routes expect.
 *
 * Every other proxied path stays fail-closed on a missing workspace id.
 */
export const GLOBAL_PATHS = new Set([
  'model',
  'model/test',
  'model/embedding',
  'model/embedding/test',
  'model/embedding/select',
  'model/embedding/delete',
  'model/profiles',
  'model/profiles/delete',
  'model/profiles/delete-preview',
  'model/routes',
  'model/host-models',
  'model/host-profiles',
  'research/preferences',
])

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
  write: (body: string | Buffer) => boolean | void
  end: (body?: string | Buffer) => void
  on?: (event: string, listener: () => void) => void
  /** Present on the host's ServerResponse; used to avoid writing into a dead socket. */
  headersSent?: boolean
  writableEnded?: boolean
  setTimeout?: (milliseconds: number, listener: () => void) => void
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

/**
 * Ceiling for one proxied request body. The runtime route already caps its
 * uploads at 1 KiB; without a cap here an authenticated browser session can
 * push an unbounded body into the host process's memory.
 */
const MAX_PROXY_BODY_BYTES = 32 * 1024 * 1024
/** Ceiling for one proxied download (export / project archive). */
const MAX_PROXY_DOWNLOAD_BYTES = 64 * 1024 * 1024
/** Per-stream ceiling on undelivered SSE bytes before the stream is dropped. */
const MAX_SSE_PENDING_BYTES = 4 * 1024 * 1024
/** Concurrent invalidation streams allowed per workspace root. */
const MAX_SSE_STREAMS_PER_ROOT = 64
/** Reap an SSE connection that has been silent this long (half-open peers). */
const SSE_IDLE_TIMEOUT_MS = 120_000

async function readBody(req: ProxyRequest): Promise<Buffer> {
  const iterator = req[Symbol.asyncIterator]
  if (iterator === undefined) return Buffer.alloc(0)
  const chunks: Buffer[] = []
  let total = 0
  for await (const chunk of iterator.call(req)) {
    const bytes = typeof chunk === 'string' ? Buffer.from(chunk) : chunk
    total += bytes.byteLength
    if (total > MAX_PROXY_BODY_BYTES) {
      throw new StudioError(`Proxied request body exceeds ${MAX_PROXY_BODY_BYTES} bytes`, 413, 'PAYLOAD_TOO_LARGE')
    }
    chunks.push(bytes)
  }
  return Buffer.concat(chunks)
}

function resourceForPath(path: string): string {
  if (path.startsWith('/api/manuscript-imports')) return 'tasks'
  if (path.startsWith('/api/project-archives')) return 'workspace'
  if (path.startsWith('/api/document') || path.startsWith('/api/write') || path.startsWith('/api/manuscript/')) return 'manuscript'
  if (path.startsWith('/api/outline')) return 'outline'
  if (path.startsWith('/api/scenes')) return 'outline'
  if (path.startsWith('/api/assets')) return 'assets'
  if (path.startsWith('/api/tasks') || path.startsWith('/api/review')) return 'tasks'
  if (path.startsWith('/api/benchmarks')) return 'benchmark'
  if (path.startsWith('/api/model')) return 'models'
  if (path.startsWith('/api/research')) return 'research'
  if (path.startsWith('/api/manuscript-editing')) return 'manuscript'
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
  outputDir?: string
  authorizeRequest?: (headers: Record<string, string | string[] | undefined>) => number | undefined
  connect?: () => Promise<BackendConnection>
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
  readonly toolOptions: { timeoutMs: number; outputDir?: string }
  readonly client: StudioClient
  private readonly authorizeRequest: NovelDomainOptions['authorizeRequest']
  private readonly connect: (() => Promise<BackendConnection>) | undefined
  readonly baseUrl: string
  private readonly resolveWorkspace: ((workspaceId: string) => string | undefined | null) | undefined
  /** Undelivered SSE bytes per stream, for backpressure (see notifyMutation). */
  private readonly streamPending = new Map<ProxyResponse, number>()
  /** Per-root invalidation state, keyed by canonical workspace root ('' = legacy). */
  private readonly roots = new Map<string, RootState>()
  /** Open SSE connections bound to the root key they subscribed to. */
  private readonly streams = new Map<ProxyResponse, string>()

  constructor(ctx: Context, options: NovelDomainOptions) {
    super(ctx, 'novelDomain')
    this.toolOptions = { timeoutMs: options.timeoutMs, ...(options.outputDir ? { outputDir: options.outputDir } : {}) }
    this.connect = options.connect
    this.authorizeRequest = options.authorizeRequest
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.resolveWorkspace = options.resolveWorkspace
    this.client = new StudioClient({
      connect: options.connect,
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
    const payload = `event: invalidate\ndata: ${event}\n\n`
    for (const [stream, key] of this.streams) {
      if (key !== root) continue
      // Honour backpressure. `write()` returning false means the socket is not
      // draining; without a `drain` listener the host buffers every event for a
      // stalled client without bound. Track pending bytes and drop a stream that
      // falls too far behind — EventSource reconnects and catches up from the
      // revision in the ready event.
      const pending = (this.streamPending.get(stream) ?? 0) + Buffer.byteLength(payload)
      if (pending > MAX_SSE_PENDING_BYTES) {
        this.streamPending.delete(stream)
        this.streams.delete(stream)
        try { stream.end() } catch { /* already disconnected */ }
        continue
      }
      const drained = stream.write(payload)
      if (drained === false) {
        this.streamPending.set(stream, pending)
        const onDrain = () => {
          stream.on?.('drain', onDrain)
          const left = Math.max(0, (this.streamPending.get(stream) ?? 0) - Buffer.byteLength(payload))
          if (left === 0) this.streamPending.delete(stream)
          else this.streamPending.set(stream, left)
        }
        stream.on?.('drain', onDrain)
      } else {
        this.streamPending.delete(stream)
      }
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
  /**
   * The workspace a browser view belongs to, for invalidation only.
   *
   * An unknown or absent workspace id resolves to the global bucket rather
   * than to a rejection: the payload of a global path does not depend on the
   * workspace, so a stale id must not turn a readable answer into an error.
   */
  private viewerRoot(id: string | undefined): string {
    if (id === undefined || id === '') return LEGACY_ROOT_KEY
    if (this.resolveWorkspace === undefined) return LEGACY_ROOT_KEY
    const root = this.resolveWorkspace(id)
    return root === undefined || root === null ? LEGACY_ROOT_KEY : root
  }

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
    const register: typeof ctx.webServer.register = route => ctx.webServer.register({ ...route, handler: (req, res) => {
      const rejection = this.authorizeRequest?.(req.headers)
      if (rejection !== undefined) { sendJson(res, rejection, { error: 'dsh browser authentication required' }); return }
      return route.handler(req, res)
    } })

    // These responses belong to this webServer injection scope. Removing a
    // route does not close requests already handled by it; end them explicitly
    // so EventSource reconnects to the newly mounted plugin after a reload.
    const responses = new Set<ProxyResponse>()
    /** Responses the dispose cleanup already answered; handlers must not write again. */
    const finalized = new Set<ProxyResponse>()
    const lifetime = new AbortController()
    let disposed = false
    ctx.effect(() => () => {
      disposed = true
      lifetime.abort()
      for (const response of responses) {
        this.streams.delete(response)
        this.streamPending.delete(response)
        finalized.add(response)
        // A response the handler has not started must not be ended with no
        // status and no body: Node silently drops the later writeHead/end, so
        // the browser sees an empty 200 and pollInvalidation throws on .json(),
        // flipping the panel to "offline" on a mere plugin reload.
        try {
          if (response.headersSent !== true) {
            response.writeHead(503, { 'content-type': 'application/json', 'cache-control': 'no-cache' })
            response.end(JSON.stringify({ error: 'novel-domain is reloading', code: 'NOVEL_DOMAIN_DISPOSED' }))
          } else if (response.writableEnded !== true) {
            response.end()
          }
        } catch { /* already disconnected */ }
      }
      responses.clear()
      // Do NOT clear `finalized`: a handler suspended on its upstream epoch read
      // resumes after this cleanup and must still see that its response was
      // already answered, or it writes a second status into a closed socket.
    }, 'novel-domain: close live invalidation responses')

    ctx.effect(() => register({
      kind: 'exact',
      path: CONFIG_ROUTE,
      handler: async (req, res) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405)
          res.end()
          return
        }
        res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-cache' })
        // In managed mode `this.baseUrl` is only the configured default (often
        // the never-bound 127.0.0.1:4567); the real backend is the one `connect()`
        // resolves. Report the live URL when there is one, and say so when the
        // mode makes a static URL meaningless.
        const managed = this.connect !== undefined
        // Await the resolution so the route answers once, with the real URL.
        let studioUrl = this.baseUrl
        let available = true
        if (this.connect !== undefined) {
          try {
            const connection = await this.connect()
            if (connection !== undefined) studioUrl = connection.baseUrl
          } catch { available = false }
        }
        res.end(JSON.stringify(available
          ? { studioUrl, managed }
          : { studioUrl, managed, available: false }))
      },
    }), 'novel-domain: config route')
    ctx.effect(() => register({
      kind: 'prefix',
      path: API_PROXY_ROUTE,
      handler: this.createProxyHandler(lifetime.signal, responses),
    }), 'novel-domain: API proxy')
    ctx.effect(() => register({
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
        try {
          const contextEpoch = await this.fetchContextEpoch(resolved.root, resolved.id, lifetime.signal)
          // Check `disposed` while still registered: deleting `res` first made
          // this guard unreachable, and the cleanup then ended an unstarted
          // response as an empty 200.
          if (disposed || finalized.has(res)) {
            // Already answered by the dispose cleanup: its 503 notice stands.
            if (!finalized.has(res)) {
              sendJson(res, 503, { error: 'novel-domain is reloading', code: 'NOVEL_DOMAIN_DISPOSED' })
            }
            return
          }
          sendJson(res, 200, contextEpoch === null ? snapshot : { ...snapshot, context_epoch: contextEpoch })
        } finally {
          responses.delete(res)
        }
      },
    }), 'novel-domain: invalidation snapshot')
    ctx.effect(() => register({
      kind: 'exact',
      path: EVENTS_ROUTE,
      handler: async (req, res) => {
        if (disposed || finalized.has(res)) {
          // A reload ends every live response with a 503 notice; a handler that
          // resumes afterwards must not write to it again.
          if (!finalized.has(res)) {
            sendJson(res, 503, { error: 'novel-domain is reloading', code: 'NOVEL_DOMAIN_DISPOSED' })
          }
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
        // Cap concurrent streams per root, and reap connections whose peer
        // vanished without FIN/RST (sleep, Wi-Fi handoff) — those never emit
        // 'close', so both maps and the socket leak until OS keepalive.
        let live = 0
        for (const key of this.streams.values()) if (key === resolved.root) live += 1
        if (live >= MAX_SSE_STREAMS_PER_ROOT) {
          sendJson(res, 429, { error: 'Too many live invalidation streams for this workspace', code: 'SSE_LIMIT' })
          return
        }
        res.writeHead(200, {
          'content-type': 'text/event-stream',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        })
        responses.add(res)
        this.streams.set(res, resolved.root)
        const dispose = () => { this.streams.delete(res); this.streamPending.delete(res); responses.delete(res) }
        res.on?.('close', dispose)
        res.on?.('error', dispose)
        res.setTimeout?.(SSE_IDLE_TIMEOUT_MS, () => { dispose(); try { res.end() } catch { /* already gone */ } })
        // The ready event carries the upstream context epoch when it is
        // readable; the stream waits for the fetch to settle (capped at
        // CONTEXT_EPOCH_TIMEOUT_MS), never longer. A client gone by then
        // simply never gets the ready event — polling carries epochs anyway.
        const revision = this.roots.get(resolved.root)?.revision ?? 0
        const contextEpoch = await this.fetchContextEpoch(resolved.root, resolved.id, lifetime.signal)
        // The dispose cleanup may have ended this response already (with its
        // 503 notice); writing again would throw or be silently dropped. The
        // entry guard above already covers `writableEnded`.
        if (disposed || !this.streams.has(res) || finalized.has(res)) return
        const ready: Record<string, unknown> = { workspace_root: resolved.root, revision }
        if (contextEpoch !== null) ready['context_epoch'] = contextEpoch
        res.write(`event: ready\ndata: ${JSON.stringify(ready)}\n\n`)
      },
    }), 'novel-domain: invalidation stream')
  }

  private createProxyHandler(lifetime: AbortSignal, responses: Set<ProxyResponse>): WebRouteHandler {
    return async (req, res) => {
      if (lifetime.aborted) { sendJson(res, 503, { error: 'OpenWrite 已停止' }); return }
      const sub = (req.url ?? '').slice(API_PROXY_ROUTE.length)
      if (sub === '' || !sub.startsWith('/')) {
        sendJson(res, 404, { error: 'novel-domain proxy: missing API path' })
        return
      }
      // Every browser request carries only a workspace_id; the trusted host
      // registry resolves it to the canonical root (contract §2.2).
      const method = req.method ?? 'GET'
      const pathPart = sub.split('?')[0]?.slice(1) ?? ''
      const isWrite = method === 'POST' || method === 'PUT'
      // A global path (the model library) is answered without a workspace:
      // its payload lives outside every project, and the settings dialog has
      // no workspace bound to send.
      const isGlobal = GLOBAL_PATHS.has(pathPart)
      const resolved = isGlobal
        ? { root: '', id: '' }
        : this.resolveBrowserWorkspace(headerValue(req, 'x-dsh-workspace-id'))
      if ('rejection' in resolved) {
        NovelDomainService.sendRejection(res, resolved.rejection)
        return
      }
      // A global path is answered without a workspace: its payload lives
      // outside every project. The view that asked is still a view, though —
      // its own workspace has to learn that the model library moved. The
      // upstream call stays workspace-free; only the invalidation follows the
      // requester, and a request that named no workspace stays global.
      const mutationRoot = isGlobal
        ? this.viewerRoot(headerValue(req, 'x-dsh-workspace-id'))
        : resolved.root
      if (!isWrite && method !== 'GET' && method !== 'HEAD') {
        sendJson(res, 405, { error: 'novel-domain proxy allows only GET/HEAD and allowlisted writes' })
        return
      }
      if (isWrite && !WRITABLE_PATHS.has(pathPart) && !WRITABLE_PATH_RE.test(pathPart)) {
        sendJson(res, 405, { error: `novel-domain proxy: write path "${pathPart}" is not allowlisted` })
        return
      }
      responses.add(res)
      try {
        const headers: Record<string, string> = {
          accept: 'application/json',
          // A global path carries no workspace identity at all: the Core reads
          // a blank root header as "legacy mode" and serves the request from
          // the root app, whose model library is the user's global one.
          ...(isGlobal ? {} : { ...workspaceRootHeaders(resolved.root, true), 'x-openwrite-workspace-id': resolved.id }),
        }
        const sessionId = headerValue(req, 'x-dsh-session-id')
        if (sessionId !== undefined) headers['x-openwrite-session-id'] = sessionId
        let body: Buffer | undefined
        if (isWrite) {
          body = await readBody(req)
          headers['content-type'] = 'application/json'
          headers['x-openwrite-studio'] = '1'
        }
        const connection = await this.connect?.()
        if (connection?.token) headers['authorization'] = `Bearer ${connection.token}`
        const upstream = await fetch(new URL(`/api${sub}`, connection?.baseUrl ?? this.baseUrl), {
          method,
          headers,
          ...(body !== undefined ? { body: new Uint8Array(body) } : {}),
          signal: AbortSignal.any([lifetime, AbortSignal.timeout(PROXY_TIMEOUT_MS)]),
        })
        if (lifetime.aborted) return
        const actualRoot = upstream.headers.get('X-OpenWrite-Project-Path')
        // A global path asked for no project, so the root the upstream reports
        // is the only one it can have: comparing it against an empty request
        // root would reject every answer.
        if (!isGlobal && upstream.ok && actualRoot && !workspaceRootsEqual(decodeURIComponent(actualRoot), resolved.root)) {
          await upstream.body?.cancel()
          sendJson(res, 409, { error: 'Connected workspace differs from requested project', code: 'WORKSPACE_CONTEXT_MISMATCH', details: { requested_path: resolved.root, project_path: decodeURIComponent(actualRoot) } })
          return
        }
        // Bound the buffer: an export or project archive is read fully into
        // memory, and `content-length` is computed from it afterwards.
        const declaredLength = Number(upstream.headers.get('content-length') ?? '')
        if (Number.isFinite(declaredLength) && declaredLength > MAX_PROXY_DOWNLOAD_BYTES) {
          await upstream.body?.cancel()
          sendJson(res, 502, { error: 'The download is too large to proxy', code: 'DOWNLOAD_TOO_LARGE', details: { limit: MAX_PROXY_DOWNLOAD_BYTES } })
          return
        }
        const upstreamBytes = Buffer.from(await upstream.arrayBuffer())
        if (upstreamBytes.byteLength > MAX_PROXY_DOWNLOAD_BYTES) {
          sendJson(res, 502, { error: 'The download is too large to proxy', code: 'DOWNLOAD_TOO_LARGE', details: { limit: MAX_PROXY_DOWNLOAD_BYTES } })
          return
        }
        const bytes = compactTaskList(upstreamBytes, pathPart, method)
        const responseHeaders: Record<string, string> = {
          'content-type': upstream.headers.get('content-type') ?? 'application/json',
          'cache-control': 'no-cache',
          'content-length': String(bytes.length),
        }
        const disposition = upstream.headers.get('content-disposition')
        const instanceId = upstream.headers.get('X-OpenWrite-Instance-Id')
        if (instanceId) responseHeaders['X-OpenWrite-Instance-Id'] = instanceId
        if (actualRoot) responseHeaders['X-OpenWrite-Project-Path'] = actualRoot
        if (disposition !== null) responseHeaders['content-disposition'] = disposition
        res.writeHead(upstream.status, responseHeaders)
        res.end(bytes)
        if (isWrite && upstream.ok && mutationAffectsState(pathPart, body, upstream.headers)) {
          this.notifyMutation(`/api/${pathPart}`, { workspaceRoot: mutationRoot, workspaceId: resolved.id })
        }
      } catch (error) {
        // A browser that disconnects mid-upload makes readBody reject; writing a
        // response into a dead socket throws again and masks the real cause.
        if (!lifetime.aborted && !res.headersSent && res.writableEnded !== true) {
          const failure = error as { code?: string; status?: number; message?: string; details?: unknown }
          if (failure.code === 'RUNTIME_PLATFORM_UNSUPPORTED') {
            sendJson(res, 503, { error: failure.message, code: failure.code })
          } else if (failure.code === 'PAYLOAD_TOO_LARGE') {
            sendJson(res, 413, { error: failure.message, code: failure.code })
          } else if (failure.code === 'DOWNLOAD_TOO_LARGE') {
            sendJson(res, 502, { error: failure.message, code: failure.code })
          } else {
            // Preserve the upstream identity: the panel maps specific codes
            // (DOCUMENT_CONFLICT, STALE_REVISION, WORKSPACE_NOT_INITIALIZED, …)
            // to localized, actionable messages. Collapsing them into one 502
            // turns a recoverable conflict into an opaque failure.
            const status = typeof failure.status === 'number' && failure.status >= 400 && failure.status < 600 ? failure.status : 502
            const code = typeof failure.code === 'string' && failure.code !== '' ? failure.code : 'STUDIO_UNAVAILABLE'
            const message = status === 502 ? '写作环境暂不可用，请打开环境与诊断重试' : (failure.message ?? 'Studio request failed')
            sendJson(res, status, { error: message, code, ...(failure.details === undefined ? {} : { details: failure.details }) })
          }
        }
      } finally {
        responses.delete(res)
      }
    }
  }
}
