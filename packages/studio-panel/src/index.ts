/**
 * `@dsh-novel/studio-panel` host half: a minimal cordis plugin owning the
 * `studioUrl` config and publishing it to the browser half through same-origin
 * routes on the dsh web server. All UI composition lives in the client half
 * (src/client/); this side carries no slots, no stores.
 */
import type { Context } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'
// Empty type import carries the webServer Context merge (ctx.webServer).
import type {} from '@deepseek-ai/dsh-host-webserver'

/** Cordis plugin name. */
export const name = '@dsh-novel/studio-panel'

/**
 * Same-origin endpoint serving the resolved panel config to the client half.
 * Deliberately NOT under `/plugins` — that prefix is claimed by the client
 * module registry's bundle route.
 */
export const CONFIG_ROUTE = '/studio-panel/config.json'

/**
 * Studio API proxy: `/studio-panel/api/<path...>?query` forwards to
 * `${studioUrl}/api/<path...>?query`, passing through the upstream status,
 * content type, and body. Prefix route — one registration covers every
 * multi-segment Studio endpoint. GET/HEAD are open; POST/PUT are gated to a
 * small allowlist of asset-domain paths (the 资产 tab's editor), each write
 * forwarded verbatim with the `X-OpenWrite-Studio: 1` header Studio requires.
 * Manuscript/outline mutations stay exclusively in the agent tools
 * (@dsh-novel/openwrite-bridge).
 */
export const API_PROXY_ROUTE = '/studio-panel/api'

/**
 * Upstream paths the panel UI may write (path portion after /api/, no
 * query): asset update/create/package-import, and the revision-guarded
 * structural outline editor. Everything else stays GET-only.
 */
const WRITABLE_PATHS: Record<string, true> = {
  assets: true,
  'assets/update': true,
  'assets/package/import': true,
  'outline/edit': true,
}

/** Upstream fetch budget; the proxied reads/writes are local and fast. */
const PROXY_TIMEOUT_MS = 15_000

/** Plugin config, validated by the same-named schemastery schema. */
export interface Config {
  /** Base URL of the local OpenWrite Studio server embedded by the 稿件 view. */
  studioUrl: string
}

export const Config: Schema<Config> = Schema.object({
  studioUrl: Schema.string().default('http://127.0.0.1:4567'),
})

/** Minimal request face: the webserver's IncomingMessage plus a test-friendly body channel. */
interface ProxyRequest {
  method?: string | undefined
  url?: string | undefined
  /** Async chunk source (IncomingMessage is an async iterable). */
  [Symbol.asyncIterator]?: () => AsyncIterableIterator<Buffer | string>
}

type ProxyResponse = {
  writeHead: (status: number, headers?: Record<string, string>) => void
  end: (body?: string | Buffer) => void
}

type WebRouteHandler = (req: ProxyRequest, res: ProxyResponse) => void | Promise<void>

/** JSON response helper for the proxy's own errors (upstream answers pass through untouched). */
function sendJson(res: ProxyResponse, status: number, payload: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-cache' })
  res.end(JSON.stringify(payload))
}

/** Buffer the request body (writes only; GET/HEAD carry none). */
async function readBody(req: ProxyRequest): Promise<Buffer> {
  const iterator = req[Symbol.asyncIterator]
  if (iterator === undefined) return Buffer.alloc(0)
  const chunks: Buffer[] = []
  for await (const chunk of iterator.call(req)) {
    chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk)
  }
  return Buffer.concat(chunks)
}

/**
 * Build the proxy handler bound to one resolved Studio base URL.
 * @param studioUrl - configured Studio origin (e.g. `http://127.0.0.1:4567`).
 * @returns the webServer route handler.
 */
function createProxyHandler(studioUrl: string): WebRouteHandler {
  return async (req, res) => {
    // req.url is the raw request target (path + query); strip the route prefix
    // so `/studio-panel/api/outline?chapter=ch_1` forwards as `/api/outline?chapter=ch_1`.
    const sub = (req.url ?? '').slice(API_PROXY_ROUTE.length)
    if (sub === '' || !sub.startsWith('/')) {
      sendJson(res, 404, { error: 'studio-panel proxy: missing API path' })
      return
    }
    const method = req.method ?? 'GET'
    const pathPart = sub.split('?')[0]?.slice(1) ?? ''
    const isWrite = method === 'POST' || method === 'PUT'
    if (!isWrite && method !== 'GET' && method !== 'HEAD') {
      sendJson(res, 405, { error: 'studio-panel proxy allows only GET/HEAD and allowlisted writes' })
      return
    }
    if (isWrite && WRITABLE_PATHS[pathPart] !== true) {
      sendJson(res, 405, { error: `studio-panel proxy: write path "${pathPart}" is not allowlisted` })
      return
    }
    const target = new URL(`/api${sub}`, studioUrl)
    try {
      const headers: Record<string, string> = { accept: 'application/json' }
      let body: Buffer | undefined
      if (isWrite) {
        body = await readBody(req)
        headers['content-type'] = 'application/json'
        // Studio's write fence: every POST/PUT must carry this marker header.
        headers['x-openwrite-studio'] = '1'
      }
      const upstream = await fetch(target, {
        method,
        headers,
        ...(body !== undefined ? { body: new Uint8Array(body) } : {}),
        signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      })
      const text = await upstream.text()
      res.writeHead(upstream.status, {
        'content-type': upstream.headers.get('content-type') ?? 'application/json',
        'cache-control': 'no-cache',
      })
      res.end(text)
    } catch (error) {
      sendJson(res, 502, {
        error: `OpenWrite Studio unreachable at ${studioUrl}: ${error instanceof Error ? error.message : String(error)}`,
      })
    }
  }
}

/**
 * Publish the config and proxy routes over the web server when the deployment
 * has one (the `web` profile). `ctx.inject` waits on the optional service
 * instead of declaring a hard edge, so composing this plugin into a
 * server-less profile (e.g. headless) loads fine — the client half then falls
 * back to the schema default baked into its bundle.
 * @param ctx - host plugin context.
 * @param config - resolved plugin config (schema defaults applied).
 */
export function apply(ctx: Context, config: Config): void {
  ctx.inject(['webServer'], (webCtx) => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: 'exact',
      path: CONFIG_ROUTE,
      handler: (req, res) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405)
          res.end()
          return
        }
        res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-cache' })
        res.end(JSON.stringify({ studioUrl: config.studioUrl }))
      },
    }), 'studio-panel: config route')
    webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: API_PROXY_ROUTE,
      handler: createProxyHandler(config.studioUrl),
    }), 'studio-panel: API proxy route')
  })
}
