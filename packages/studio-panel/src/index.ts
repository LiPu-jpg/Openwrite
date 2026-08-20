/**
 * `@dsh-novel/studio-panel` host half: a minimal cordis plugin owning the
 * `studioUrl` config and publishing it to the browser half through one
 * same-origin JSON route on the dsh web server. All UI composition lives in
 * the client half (src/client/); this side carries no slots, no stores.
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

/** Plugin config, validated by the same-named schemastery schema. */
export interface Config {
  /** Base URL of the local OpenWrite Studio server embedded by the 稿件 view. */
  studioUrl: string
}

export const Config: Schema<Config> = Schema.object({
  studioUrl: Schema.string().default('http://127.0.0.1:4567'),
})

/**
 * Publish the resolved config over the web server when the deployment has one
 * (the `web` profile). `ctx.inject` waits on the optional service instead of
 * declaring a hard edge, so composing this plugin into a server-less profile
 * (e.g. headless) loads fine — the client half then falls back to the schema
 * default baked into its bundle.
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
  })
}
