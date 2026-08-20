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
 * Read-only Studio API proxy: `GET /studio-panel/api/<path...>?query` forwards
 * to `${studioUrl}/api/<path...>?query`, passing through the upstream status,
 * content type, and body. Prefix route — one registration covers every
 * multi-segment Studio GET endpoint. GET only on purpose: mutations stay with
 * the agent tools (@dsh-novel/openwrite-bridge), the native views are
 * read-only surfaces.
 */
export const API_PROXY_ROUTE = '/studio-panel/api'

/** Upstream fetch budget; the proxied reads (outline/assets) are local and fast. */
const PROXY_TIMEOUT_MS = 15_000

/** Plugin config, validated by the same-named schemastery schema. */
export interface Config {
  /** Base URL of the local OpenWrite Studio server embedded by the 稿件 view. */
  studioUrl: string
}

export const Config: Schema<Config> = Schema.object({
  studioUrl: Schema.string().default('http://127.0.0.1:4567'),
})

type WebRouteHandler = (
  req: { method?: string | undefined; url?: string | undefined },
  res: {
    writeHead: (status: number, headers?: Record<string, string>) => void
    end: (body?: string) => void
  },
) => void | Promise<void>

/** JSON response helper for the proxy's own errors (upstream answers pass through untouched). */
function sendJson(res: Parameters<WebRouteHandler>[1], status: number, payload: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-cache' })
  res.end(JSON.stringify(payload))
}

/**
 * Build the proxy handler bound to one resolved Studio base URL.
 * @param studioUrl - configured Studio origin (e.g. `http://127.0.0.1:4567`).
 * @returns the webServer route handler.
 */
function createProxyHandler(studioUrl: string): WebRouteHandler {
  return async (req, res) => {
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      sendJson(res, 405, { error: 'studio-panel proxy is read-only (GET)' })
      return
    }
    // req.url is the raw request target (path + query); strip the route prefix
    // so `/studio-panel/api/outline?chapter=ch_1` forwards as `/api/outline?chapter=ch_1`.
    const sub = (req.url ?? '').slice(API_PROXY_ROUTE.length)
    if (sub === '' || !sub.startsWith('/')) {
      sendJson(res, 404, { error: 'studio-panel proxy: missing API path' })
      return
    }
    const target = new URL(`/api${sub}`, studioUrl)
    try {
      const upstream = await fetch(target, {
        headers: { accept: 'application/json' },
        signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      })
      const body = await upstream.text()
      res.writeHead(upstream.status, {
        'content-type': upstream.headers.get('content-type') ?? 'application/json',
        'cache-control': 'no-cache',
      })
      res.end(body)
    } catch (error) {
      sendJson(res, 502, {
        error: `OpenWrite Studio unreachable at ${studioUrl}: ${error instanceof Error ? error.message : String(error)}`,
      })
    }
  }
}

/**
 * Publish the config and read-only proxy routes over the web server when the
 * deployment has one (the `web` profile). `ctx.inject` waits on the optional
 * service instead of declaring a hard edge, so composing this plugin into a
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
