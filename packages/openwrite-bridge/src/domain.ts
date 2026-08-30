import { Service, type Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-host-webserver'
import { StudioClient } from './client.js'

export const CONFIG_ROUTE = '/studio-panel/config.json'
export const API_PROXY_ROUTE = '/studio-panel/api'
export const EVENTS_ROUTE = '/studio-panel/events'
export const INVALIDATION_ROUTE = '/studio-panel/invalidation.json'

const PROXY_TIMEOUT_MS = 60_000
const WRITABLE_PATHS = new Set([
  'assets',
  'assets/update',
  'assets/package/import',
  'outline/edit',
  'sync',
  'import/preview',
  'import',
  'tasks',
  'benchmarks',
  'document',
  'project/open',
  'project/init',
  'model',
  'model/test',
  'model/embedding/test',
  'model/profiles',
  'model/profiles/delete',
  'model/routes',
])
const WRITABLE_PATH_RE = /^tasks\/[A-Za-z0-9_-]+\/(?:cancel|retry)$/

interface ProxyRequest {
  method?: string
  url?: string
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
  if (path.startsWith('/api/document') || path.startsWith('/api/write')) return 'manuscript'
  if (path.startsWith('/api/outline')) return 'outline'
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
        chapter_id: task['chapter_id'],
        input_summary: task['input_summary'],
        error: task['error'],
        retryable: task['retryable'],
        attempt: task['attempt'],
        created_at: task['created_at'],
        updated_at: task['updated_at'],
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
}

/** Single host-side boundary shared by agent tools, browser proxy and live invalidation. */
export class NovelDomainService extends Service {
  readonly client: StudioClient
  readonly baseUrl: string
  private revision = 0
  private lastMutation = { revision: 0, resource: 'workspace', path: '' }
  private readonly streams = new Set<ProxyResponse>()

  constructor(ctx: Context, options: NovelDomainOptions) {
    super(ctx, 'novelDomain')
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.client = new StudioClient({
      baseUrl: this.baseUrl,
      timeoutMs: options.timeoutMs,
      onMutation: path => this.notifyMutation(path),
    })
  }

  notifyMutation(path: string): void {
    this.revision += 1
    this.lastMutation = { revision: this.revision, resource: resourceForPath(path), path }
    const event = JSON.stringify(this.lastMutation)
    for (const stream of this.streams) stream.write(`event: invalidate\ndata: ${event}\n\n`)
  }

  registerWebRoutes(ctx: Context): void {
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
      handler: (req, res) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405)
          res.end()
          return
        }
        sendJson(res, 200, this.lastMutation)
      },
    }), 'novel-domain: invalidation snapshot')
    ctx.effect(() => ctx.webServer.register({
      kind: 'exact',
      path: EVENTS_ROUTE,
      handler: (req, res) => {
        if (req.method !== 'GET') {
          res.writeHead(405)
          res.end()
          return
        }
        res.writeHead(200, {
          'content-type': 'text/event-stream',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        })
        res.write(`event: ready\ndata: ${JSON.stringify({ revision: this.revision })}\n\n`)
        this.streams.add(res)
        const dispose = () => { this.streams.delete(res) }
        res.on?.('close', dispose)
        res.on?.('error', dispose)
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
        const headers: Record<string, string> = { accept: 'application/json' }
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
        if (isWrite && upstream.ok) this.notifyMutation(`/api/${pathPart}`)
      } catch (error) {
        sendJson(res, 502, {
          error: `OpenWrite Studio unreachable at ${this.baseUrl}: ${error instanceof Error ? error.message : String(error)}`,
        })
      }
    }
  }
}
