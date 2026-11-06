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
import { HostLlmRelay, newRelayToken, type HostDefaultSelection, type HostLlmService } from './host-llm.js'
import { HostWebRelay, type HostWebService } from './host-web.js'
import { join, isAbsolute } from 'node:path'
import { existsSync } from 'node:fs'
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
  /** Absolute path to a prepared Python >=3.10; skips uv and interpreter downloads. */
  pythonPath?: string
  /** Optional absolute directories containing dependencies for the supplied interpreter. */
  pythonModulePaths?: string[]
  /** Base URL of the local OpenWrite Studio server. */
  baseUrl: string
  /** Optional instance token of an externally managed Studio server. */
  authToken?: string
  /** Per-tool cooperative timeout in ms; chapter writing/review can take minutes. */
  timeoutMs: number
  /** Directory `novel_export` saves exported files into. */
  outputDir: string
}

export const Config: Schema<Config> = Schema.object({
  // Explicit default: the code relied on `undefined` falling through to external,
  // which is invisible in the schema and easy to break.
  mode: Schema.union(['managed', 'external']).default('external'),
  runtimeRoot: Schema.string(),
  artifacts: Schema.string(),
  pythonPath: Schema.string(),
  pythonModulePaths: Schema.array(Schema.string()),
  baseUrl: Schema.string().default('http://127.0.0.1:4567'),
  authToken: Schema.string().role('secret'),
  timeoutMs: Schema.number().default(600000),
  outputDir: Schema.string().default(join(tmpdir(), 'openwrite-exports')),
})

/**
 * Validate the configuration before any request is served. Every one of these
 * used to surface as a first-request failure with a misleading cause: a bogus
 * runtimeRoot or artifacts path only raised ENOENT inside `ensure()`, a
 * non-URL baseUrl threw inside `new URL()` and was rewritten to NETWORK_ERROR,
 * and `timeoutMs <= 0` made every request abort immediately.
 */
function validateConfig(config: Config): void {
  if (!Number.isFinite(config.timeoutMs) || config.timeoutMs <= 0) {
    throw new Error(`openwrite-bridge: timeoutMs must be a positive number, got ${String(config.timeoutMs)}`)
  }
  if (config.mode === 'external') {
    try {
      const parsed = new URL(config.baseUrl)
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        throw new Error(`unsupported protocol ${parsed.protocol}`)
      }
    } catch (cause) {
      throw new Error(`openwrite-bridge: baseUrl must be an http(s) URL, got ${JSON.stringify(config.baseUrl)} (${cause instanceof Error ? cause.message : String(cause)})`)
    }
    // No authToken rule here: a tokenless Studio server is a legitimate
    // external configuration, and there is no way to tell it from a forgotten
    // token without asking the server. Only the *contradiction* below is a
    // definite misconfiguration.
  }
  if (config.mode === 'managed') {
    // The token is only used in external mode; managed mode authenticates through
    // the runtime's own connection, so a supplied token is silently ignored.
    if (config.authToken !== undefined && config.authToken !== '') {
      throw new Error('openwrite-bridge: authToken is ignored in managed mode (the managed runtime issues its own connection token); remove it or switch to mode "external"')
    }
    const artifacts = config.artifacts ?? fileURLToPath(new URL('../../../release/', import.meta.url))
    if (!existsSync(join(artifacts, 'runtime-manifest.json'))) {
      throw new Error(`openwrite-bridge: artifacts must contain runtime-manifest.json, got ${JSON.stringify(artifacts)}`)
    }
    for (const [key, value] of [['pythonPath', config.pythonPath], ['runtimeRoot', config.runtimeRoot]] as const) {
      if (value === undefined || value === '') continue
      if (!isAbsolute(value)) throw new Error(`openwrite-bridge: ${key} must be an absolute path, got ${JSON.stringify(value)}`)
    }
    for (const value of config.pythonModulePaths ?? []) {
      if (!isAbsolute(value)) throw new Error(`openwrite-bridge: pythonModulePaths entries must be absolute, got ${JSON.stringify(value)}`)
    }
  }
}

export function apply(ctx: Context, config: Config) {
  validateConfig(config)
  // The web host process mounts ctx.workspaceRegistry. Resolve it lazily on
  // every call: plugin start order must not strand the lookup, an absent
  // registry (null) fails closed in the domain, and ctx.inject(['webServer',
  // ...]) would silently never fire if we inject-required a second service.
  const resolveWorkspace = (workspaceId: string): string | undefined | null => {
    const registry = ctx.get('workspaceRegistry')
    if (registry === undefined) return null
    return registry.get(workspaceId as WorkspaceId)?.path
  }
  // The relay onto the host's own model directory. It is created lazily: a
  // host that composes no `llm` service still loads the plugin, it just offers
  // no host models. The relay binds an ephemeral loopback port and answers
  // only to a machine token, so no provider key and no browser session can
  // reach it.
  let relay: HostLlmRelay | undefined
  const defaultSelection: HostDefaultSelection = () => {
    let service
    try { service = ctx.get('agentDefaultModel') } catch { return undefined }
    if (service === undefined || service === null) return undefined
    try {
      const selection = service.currentSelection()
      const provider = typeof selection?.provider === 'string' ? selection.provider : ''
      const model = typeof selection?.model === 'string' ? selection.model : ''
      if (provider === '' || model === '') return undefined
      const effort = typeof selection?.reasoningEffort === 'string' ? selection.reasoningEffort : ''
      return { provider, model, ...(effort === '' ? {} : { reasoningEffort: effort }) }
    } catch { return undefined }
  }
  const ensureRelay = async (): Promise<HostLlmRelay | undefined> => {
    if (relay !== undefined) return relay
    let llm
    try { llm = ctx.get('llm') } catch { return undefined }
    if (llm === undefined || llm === null) return undefined
    const created = new HostLlmRelay({
      llm: llm as unknown as HostLlmService,
      token: newRelayToken(),
      defaultSelection,
    })
    await created.listen()
    relay = created
    return relay
  }
  ctx.effect(() => () => { void relay?.close(); relay = undefined }, 'openwrite: host llm relay cleanup')
  // The relay onto the host's own web search/fetch. Only the managed runtime
  // needs it; an external Studio keeps its own search providers.
  let webRelay: HostWebRelay | undefined
  const ensureWebRelay = async (): Promise<HostWebRelay | undefined> => {
    if (webRelay !== undefined) return webRelay
    let web
    try { web = ctx.get('web') } catch { return undefined }
    if (web === undefined || web === null) return undefined
    const created = new HostWebRelay({ web: web as unknown as HostWebService, token: newRelayToken() })
    await created.listen()
    webRelay = created
    return created
  }
  ctx.effect(() => () => { void webRelay?.close(); webRelay = undefined }, 'openwrite: host web relay cleanup')
  // A supplied legacy baseUrl remains external; the standard bundle selects managed explicitly.
  const runtime = config.mode === 'managed' ? new ManagedRuntime(
    config.runtimeRoot ?? join(process.env['DSH_HOME']?.trim() || join(homedir(), '.dsh'), 'openwrite'),
    config.artifacts ?? fileURLToPath(new URL('../../../release/', import.meta.url)),
    { pythonPath: config.pythonPath, pythonModulePaths: config.pythonModulePaths,
      // The relay is resolved per backend start: its port is ephemeral, so a
      // cached address would outlive the server it points at.
      hostLlm: async () => {
        const created = await ensureRelay()
        return created === undefined ? undefined : { url: created.baseUrl(), token: created.token() }
      },
      hostWeb: async () => {
        const created = await ensureWebRelay()
        return created === undefined ? undefined : { url: created.baseUrl(), token: created.token() }
      } },
  ) : undefined
  const authorizeRequest = (headers: Record<string, string | string[] | undefined>): number | undefined => {
    const connection = ctx.get('connection')
    return connection ? connection.requestRejection({ headers }) : 503
  }
  const domain = new NovelDomainService(ctx, { authorizeRequest, baseUrl: config.baseUrl, timeoutMs: config.timeoutMs, outputDir: config.outputDir, resolveWorkspace,
    ...(runtime ? { connect: () => runtime.ensure() }
      : config.authToken ? { connect: async () => ({ baseUrl: config.baseUrl, token: config.authToken }) } : {}),
  })
  ctx.effect(() => () => runtime?.dispose(), 'openwrite: owned runtime cleanup')
  ctx.inject(['webServer'], webCtx => webCtx.effect(() => webCtx.webServer.register({
    kind: 'exact', path: '/studio-panel/runtime', handler: async (req, res) => {
      const respond = (code: number, data: unknown) => { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(data)) }
      const rejection = authorizeRequest(req.headers)
      if (rejection !== undefined) { respond(rejection, { error: 'dsh browser authentication required', message: 'dsh browser authentication required', code: 'AUTHENTICATION_REQUIRED' }); return }
      if (req.method === 'GET') { respond(200, runtime?.status() ?? { phase: 'ready', message: 'Using an external writing environment' }); return }
      if (req.method !== 'POST' || req.headers['x-openwrite-studio'] !== '1') { respond(405, { error: 'Method not allowed', message: 'Method not allowed', code: 'METHOD_NOT_ALLOWED' }); return }
      const chunks: Buffer[] = []
      let size = 0
      // Answering 413 while still iterating `req` resets the connection, so the
      // client sees a truncated response. Drain first, then respond.
      let tooLarge = false
      for await (const chunk of req) {
        size += chunk.length
        if (size > 1024) { tooLarge = true; break }
        chunks.push(Buffer.from(chunk))
      }
      if (tooLarge) { respond(413, { error: 'Request too large', message: 'Request too large', code: 'REQUEST_TOO_LARGE' }); return }
      try {
        const action = JSON.parse(Buffer.concat(chunks).toString()).action
        if (action === 'cancel') await runtime?.cancel()
        else if (action === 'prepare' || action === 'retry') void runtime?.ensure().catch(() => {})
        else { respond(400, { error: 'Unknown action', message: 'Unknown action', code: 'INVALID_ACTION' }); return }
        respond(202, runtime?.status() ?? { phase: 'ready' })
      } catch { respond(400, { error: 'Invalid request', message: 'Invalid request', code: 'INVALID_INPUT' }) }
    },
  }), 'openwrite: runtime controls'))
  ctx.inject(['webServer'], webCtx => domain.registerWebRoutes(webCtx))
}
