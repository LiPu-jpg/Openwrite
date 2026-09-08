import type {} from '@deepseek-ai/dsh-client-connection'
/**
 * `@dsh-novel/openwrite-bridge`: a dsh plugin registering `novel_*` tools that
 * call the local OpenWrite Studio HTTP action surface. dsh owns agent
 * orchestration; OpenWrite owns the novel domain logic; this package is a thin
 * bridge over the HTTP contract only.
 */

import { tmpdir, homedir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { ManagedRuntime } from './managed-runtime.js'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { WorkspaceId } from '@deepseek-ai/dsh-workspace'
import Schema from '@deepseek-ai/schemastery'
import { NovelDomainService } from './domain.js'


export const name = '@dsh-novel/openwrite-bridge'
export const inject: string[] = []

export interface Config {
  mode?: 'managed' | 'external'
  runtimeRoot?: string
  artifacts?: string
  /** Base URL of the local OpenWrite Studio server. */
  baseUrl: string
  /** Per-tool cooperative timeout in ms; chapter writing/review can take minutes. */
  timeoutMs: number
  /** Directory `novel_export` saves exported files into. */
  outputDir: string
}

export const Config: Schema<Config> = Schema.object({
  mode: Schema.union(['managed', 'external']),
  runtimeRoot: Schema.string(),
  artifacts: Schema.string(),
  baseUrl: Schema.string().default('http://127.0.0.1:4567'),
  timeoutMs: Schema.number().default(600000),
  outputDir: Schema.string().default(join(tmpdir(), 'openwrite-exports')),
})

export function apply(ctx: Context, config: Config) {
  // The web host process mounts ctx.workspaceRegistry. Resolve it lazily on
  // every call: plugin start order must not strand the lookup, an absent
  // registry (null) fails closed in the domain, and ctx.inject(['webServer',
  // ...]) would silently never fire if we inject-required a second service.
  const resolveWorkspace = (workspaceId: string): string | undefined | null => {
    const registry = ctx.get('workspaceRegistry')
    if (registry === undefined) return null
    return registry.get(workspaceId as WorkspaceId)?.path
  }
  // A supplied legacy baseUrl remains external; the standard bundle selects managed explicitly.
  const runtime = config.mode === 'managed' ? new ManagedRuntime(
    config.runtimeRoot ?? join(process.env['DSH_HOME']?.trim() || join(homedir(), '.dsh'), 'openwrite'),
    config.artifacts ?? fileURLToPath(new URL('../../../release/', import.meta.url)),
  ) : undefined
  const authorizeRequest = (headers: Record<string, string | string[] | undefined>): number | undefined => {
    const connection = ctx.get('connection')
    return connection ? connection.requestRejection({ headers }) : 503
  }
  const domain = new NovelDomainService(ctx, { authorizeRequest, baseUrl: config.baseUrl, timeoutMs: config.timeoutMs, outputDir: config.outputDir, resolveWorkspace,
    ...(runtime ? { connect: () => runtime.ensure() } : {}),
  })
  ctx.effect(() => () => runtime?.dispose(), 'openwrite: owned runtime cleanup')
  ctx.inject(['webServer'], webCtx => webCtx.effect(() => webCtx.webServer.register({
    kind: 'exact', path: '/studio-panel/runtime', handler: async (req, res) => {
      const respond = (code: number, data: unknown) => { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(data)) }
      const rejection = authorizeRequest(req.headers)
      if (rejection !== undefined) { respond(rejection, { error: 'dsh browser authentication required' }); return }
      if (req.method === 'GET') { respond(200, runtime?.status() ?? { phase: 'ready', message: '使用外部写作环境' }); return }
      if (req.method !== 'POST' || req.headers['x-openwrite-studio'] !== '1') { respond(405, { error: '操作不允许' }); return }
      const chunks: Buffer[] = []
      let size = 0
      for await (const chunk of req) { size += chunk.length; if (size > 1024) { respond(413, { error: '请求过大' }); return }; chunks.push(Buffer.from(chunk)) }
      try {
        const action = JSON.parse(Buffer.concat(chunks).toString()).action
        if (action === 'cancel') await runtime?.cancel()
        else if (action === 'prepare' || action === 'retry') void runtime?.ensure().catch(() => {})
        else { respond(400, { error: '未知操作' }); return }
        respond(202, runtime?.status() ?? { phase: 'ready' })
      } catch { respond(400, { error: '请求无效' }) }
    },
  }), 'openwrite: runtime controls'))
  ctx.inject(['webServer'], webCtx => domain.registerWebRoutes(webCtx))
}
