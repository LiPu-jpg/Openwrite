import { readFile } from 'node:fs/promises'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-host-webserver'

export const name = '@dsh-novel/studio-panel'
export const VENDOR_ROUTE = '/studio-panel/vendor/vditor'

const VENDOR_FILES: Readonly<Record<string, string>> = {
  '/LICENSE': 'text/plain; charset=utf-8',
  '/dist/index.css': 'text/css; charset=utf-8',
  '/dist/index.min.js': 'text/javascript; charset=utf-8',
  '/dist/css/content-theme/dark.css': 'text/css; charset=utf-8',
  '/dist/css/content-theme/light.css': 'text/css; charset=utf-8',
  '/dist/js/lute/lute.min.js': 'text/javascript; charset=utf-8',
  '/dist/js/icons/ant.js': 'text/javascript; charset=utf-8',
  '/dist/js/i18n/zh_CN.js': 'text/javascript; charset=utf-8',
}

/** Browser UI loader plus same-origin static assets for the packaged editor engine. */
export function apply(ctx: Context): void {
  ctx.inject(['webServer'], webCtx => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: VENDOR_ROUTE,
      handler: async (req, res) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405)
          res.end()
          return
        }
        const suffix = (req.url ?? '').slice(VENDOR_ROUTE.length).split('?')[0] ?? ''
        const contentType = VENDOR_FILES[suffix]
        if (contentType === undefined) {
          res.writeHead(404)
          res.end()
          return
        }
        try {
          const bytes = await readFile(new URL(`../vendor/vditor${suffix}`, import.meta.url))
          res.writeHead(200, { 'content-type': contentType, 'cache-control': 'public, max-age=31536000, immutable' })
          res.end(bytes)
        } catch {
          res.writeHead(404)
          res.end()
        }
      },
    }), 'studio-panel: packaged Vditor assets')
  })
}
