import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'

/**
 * A loopback-only relay onto the host's own `ctx.web` service.
 *
 * OpenWrite's deep research runs as a separate Node process. The host's search
 * and fetch providers (including `web_search` / `web_fetch`) live in the host
 * process, so the child cannot reach them directly. This relay gives it a
 * machine-token HTTP face over exactly those two capabilities; no provider key
 * and no browser session can reach it.
 *
 * `/bocha` exists because the vendored DeepResearch framework already speaks
 * the Bocha search protocol. Mapping one search onto that protocol lets us use
 * the host's search without forking the framework's search-provider union.
 */

export interface HostWebSearchSource {
  url: string
  title?: string
  snippet?: string
  publishedAt?: string
}

export interface HostWebSearchResult {
  content?: string
  sources: HostWebSearchSource[]
  truncated?: boolean
}

export interface HostWebFetchResult {
  url: string
  statusCode: number
  body: { kind: 'html' | 'text'; content: string }
  truncated?: boolean
}

/** Structural view of the host's `web` service (`ctx.get('web')`). */
export interface HostWebService {
  search(request: { query: string; maxResults?: number }, signal?: AbortSignal): Promise<HostWebSearchResult>
  fetch(request: { url: string }, signal?: AbortSignal): Promise<HostWebFetchResult>
}

export interface HostWebRelayOptions {
  web: HostWebService
  /** Machine token; every request must present it as a bearer credential. */
  token: string
}

const BODY_LIMIT_BYTES = 1 * 1024 * 1024
const REQUEST_TIMEOUT_MS = 120_000

function json(res: ServerResponse, status: number, payload: unknown): void {
  const body = JSON.stringify(payload)
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' })
  res.end(body)
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > BODY_LIMIT_BYTES) throw new Error('request body too large')
    chunks.push(Buffer.from(chunk))
  }
  if (chunks.length === 0) return {}
  const parsed: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('request body must be a JSON object')
  return parsed as Record<string, unknown>
}

function nonEmptyString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** Normalize the host's search result to the wire shape. */
function searchWire(result: HostWebSearchResult): Record<string, unknown> {
  const sources = Array.isArray(result.sources)
    ? result.sources
        .filter(source => source !== null && typeof source === 'object' && nonEmptyString(source.url) !== '')
        .map(source => ({
          url: nonEmptyString(source.url),
          ...(nonEmptyString(source.title) === '' ? {} : { title: nonEmptyString(source.title) }),
          ...(nonEmptyString(source.snippet) === '' ? {} : { snippet: nonEmptyString(source.snippet) }),
          ...(nonEmptyString(source.publishedAt) === '' ? {} : { publishedAt: nonEmptyString(source.publishedAt) }),
        }))
    : []
  return {
    ...(nonEmptyString(result.content) === '' ? {} : { content: nonEmptyString(result.content) }),
    sources,
    truncated: result.truncated === true,
  }
}

/** Normalize the host's fetch result; body kind and text are always present. */
function fetchWire(result: HostWebFetchResult): Record<string, unknown> {
  const kind = result.body?.kind === 'html' ? 'html' : 'text'
  return {
    url: nonEmptyString(result.url),
    statusCode: Number.isInteger(result.statusCode) ? result.statusCode : 0,
    body: { kind, content: typeof result.body?.content === 'string' ? result.body.content : '' },
    truncated: result.truncated === true,
  }
}

/** The Bocha response shape the vendored search provider parses. */
function bochaWire(sources: HostWebSearchSource[]): Record<string, unknown> {
  return {
    code: 200,
    data: {
      webPages: {
        value: sources.map(source => ({
          name: nonEmptyString(source.title) || nonEmptyString(source.url),
          url: nonEmptyString(source.url),
          snippet: nonEmptyString(source.snippet),
          summary: nonEmptyString(source.snippet),
        })),
      },
    },
  }
}

export class HostWebRelay {
  private server?: Server
  private port = 0
  private closed = false

  constructor(private readonly options: HostWebRelayOptions) {}

  async listen(): Promise<void> {
    if (this.server !== undefined) return
    const server = createServer((req, res) => {
      void this.handle(req, res).catch((error: unknown) => {
        if (res.headersSent) { res.end(); return }
        json(res, 502, { error: { message: error instanceof Error ? error.message : String(error) } })
      })
    })
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject)
      server.listen(0, '127.0.0.1', () => {
        server.removeListener('error', reject)
        resolve()
      })
    })
    const address = server.address()
    this.port = typeof address === 'object' && address !== null ? address.port : 0
    this.server = server
  }

  baseUrl(): string {
    return `http://127.0.0.1:${this.port}`
  }

  token(): string {
    return this.options.token
  }

  async close(): Promise<void> {
    if (this.closed) return
    this.closed = true
    const server = this.server
    this.server = undefined
    if (server === undefined) return
    await new Promise<void>(resolve => server.close(() => resolve()))
  }

  private authorized(req: IncomingMessage): boolean {
    return req.headers.authorization === `Bearer ${this.options.token}`
  }

  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (!this.authorized(req)) { json(res, 401, { error: { message: 'unauthorized' } }); return }
    if (req.method !== 'POST') { json(res, 405, { error: { message: 'method not allowed' } }); return }
    const url = new URL(req.url ?? '/', 'http://relay')
    const body = await readJson(req)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    try {
      if (url.pathname === '/search') {
        const query = nonEmptyString(body.query)
        if (query === '') throw new Error('query is required')
        const maxResults = Number.isInteger(body.maxResults) && Number(body.maxResults) > 0 ? Number(body.maxResults) : undefined
        json(res, 200, searchWire(await this.options.web.search({ query, ...(maxResults === undefined ? {} : { maxResults }) }, controller.signal)))
        return
      }
      if (url.pathname === '/bocha') {
        const query = nonEmptyString(body.query)
        if (query === '') throw new Error('query is required')
        const count = Number.isInteger(body.count) && Number(body.count) > 0 ? Number(body.count) : 10
        const result = await this.options.web.search({ query, maxResults: Math.min(count, 50) }, controller.signal)
        json(res, 200, bochaWire(result.sources ?? []))
        return
      }
      if (url.pathname === '/fetch') {
        const target = nonEmptyString(body.url)
        if (target === '') throw new Error('url is required')
        json(res, 200, fetchWire(await this.options.web.fetch({ url: target }, controller.signal)))
        return
      }
      json(res, 404, { error: { message: 'not found' } })
    } finally {
      clearTimeout(timer)
    }
  }
}
