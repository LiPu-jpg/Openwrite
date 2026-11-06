import { cp, lstat, mkdir, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises'
import { createHash, randomUUID } from 'node:crypto'
import { lock } from 'proper-lockfile'
import { resolveDshHome } from '@deepseek-ai/dsh-home-paths'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import { legacyPresetIds, legacyAliasName, presetDefinition, referencedPresetIds } from './preset-definition.mjs'
import { detectCompanions, OPENWRITE_OPS_OPTIONS, summarizeOpsPlan } from './companions.mjs'

export const name = 'dsh-openwrite'

/**
 * Which companion plugins are installed and loadable here, for the workbench's
 * companion section. Best-effort by design: an unreadable home reports nothing
 * rather than failing the route.
 */
async function loadOpsResolver(home, entry) {
  // The companion may live in a profile whose node_modules is not on this
  // plugin's resolution path (dsh-openwrite can be a symlinked dev install), so
  // resolve from the profile that actually owns dsh-ops first.
  const candidates = []
  if (typeof entry.profile === 'string' && entry.profile !== '') {
    try {
      const fromProfile = createRequire(join(home, 'profiles', entry.profile, 'package.json'))
      candidates.push(fromProfile.resolve('dsh-ops/integration'))
    } catch { /* fall through to the normal resolution path */ }
  }
  candidates.push('dsh-ops/integration')
  for (const candidate of candidates) {
    try {
      const module = await import(candidate.startsWith('/') ? pathToFileURL(candidate).href : candidate)
      if (typeof module.resolveIntegrationConfig === 'function') return module.resolveIntegrationConfig
    } catch { /* try the next candidate */ }
  }
  return null
}

async function opsPlan(home, entry) {
  if (!entry.usable) return null
  try {
    // Read-only normalization: the same options the preset row uses. A dsh-ops
    // release without this export (or one that changed the option names) is
    // reported as no plan rather than failing the companion inventory.
    const resolveIntegrationConfig = await loadOpsResolver(home, entry)
    if (resolveIntegrationConfig === null) return null
    return summarizeOpsPlan(resolveIntegrationConfig({ ...OPENWRITE_OPS_OPTIONS }))
  } catch { return null }
}

export async function companionSummary(home) {
  try {
    const companions = await detectCompanions(home)
    const describe = entry => ({ installed: entry.installed, usable: entry.usable, version: entry.version, reason: entry.reason })
    return {
      host: companions.host,
      dog: describe(companions.dog),
      ops: { ...describe(companions.ops), plan: await opsPlan(home, companions.ops) },
      freeModel: describe(companions.freeModel),
    }
  } catch { return null }
}

/**
 * The host's own default-model selection, read from the service the host
 * exposes to plugins (`ctx.agentDefaultModel`).
 *
 * The API key is deliberately NOT part of this answer. The selection is a fact
 * the author already sees in the host's own settings; the key is a secret that
 * must never travel to a browser, and the host keeps it in its credentials
 * service rather than in this selection at all.
 *
 * A host that does not compose the service, or one whose selection is not
 * configured yet, answers `available: false` instead of throwing: the settings
 * page shows "not configured", which is true, rather than failing to open.
 */
function hostModelSelection(ctx) {
  const empty = { available: false, provider: '', model: '', reasoningEffort: '' }
  let service
  try { service = ctx.get('agentDefaultModel') } catch { return empty }
  if (service === undefined || service === null) return empty
  let selection
  try { selection = service.currentSelection() } catch { return empty }
  const provider = typeof selection?.provider === 'string' ? selection.provider : ''
  const model = typeof selection?.model === 'string' ? selection.model : ''
  const reasoningEffort = typeof selection?.reasoningEffort === 'string' ? selection.reasoningEffort : ''
  // A selection with no provider or no model names no model: report it as
  // unconfigured rather than as a selection of two empty strings.
  return { available: provider !== '' && model !== '', provider, model, reasoningEffort }
}

/** Every non-hidden file of a tree, keyed by its path relative to the root. */
async function listFiles(dir, prefix = '', found = new Map()) {
  for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    // Editor and OS noise is not an author edit: a `.DS_Store` must not make the
    // next activation refuse to start.
    if (entry.name.startsWith('.')) continue
    const key = prefix + entry.name
    const path = join(dir, entry.name)
    if (entry.isDirectory()) await listFiles(path, key + '/', found)
    else found.set(key, path)
  }
  return found
}

/**
 * Digest of a managed preset directory, over the files the package ships only.
 * A foreign file (the author's note, a skill they added, a dangling symlink) is
 * not a modification: counting it would make one stray file brick the plugin.
 */
async function digestShipped(source, destination) {
  const shipped = await listFiles(source)
  const present = await listFiles(destination)
  const hash = createHash('sha256')
  for (const key of [...shipped.keys()].sort()) {
    const path = present.get(key)
    if (path === undefined) { hash.update(key + '\u0000missing'); continue }
    hash.update(key)
    try { hash.update(await readFile(path)) }
    catch (error) { if (error.code !== 'ENOENT') hash.update(key + '\u0000unreadable') }
  }
  return hash.digest('hex')
}

/** Keep legacy filesystem presets and resolve durable session identities on upgrade. */
export async function apply(ctx) {
  const home = resolveDshHome()
  const source = fileURLToPath(new URL('./presets/openwrite/', import.meta.url))
  const version = JSON.parse(await readFile(new URL('./package.json', import.meta.url), 'utf8')).version
  const id = `openwrite-${version.replace(/[^a-z0-9-]/g, '-')}`
  const destination = join(home, '.agent-presets', id)
  const managedRoot = join(home, 'openwrite')
  const leases = join(managedRoot, 'preset-leases', id)
  await mkdir(leases, { recursive: true })
  await mkdir(join(home, '.agent-presets'), { recursive: true })
  const lease = join(leases, `${process.pid}-${randomUUID()}.json`)
  const withLock = async operation => {
    const release = await lock(leases, { realpath: false, stale: 30_000, retries: { retries: 30, minTimeout: 100, maxTimeout: 500 } })
    try { return await operation() } finally { await release() }
  }
  const marker = join(destination, '.openwrite-managed.json')
  await withLock(async () => {
    const existing = await readFile(marker, 'utf8').then(JSON.parse).catch(() => null)
    if (existing) {
      if (existing.source !== await digestShipped(source, destination)) {
        throw new Error(`OpenWrite preset ${id} was modified; copy it to a custom preset before reinstalling this version`)
      }
    }
    if (!existing) {
      if (await lstat(destination).then(() => true).catch(error => { if (error.code === 'ENOENT') return false; throw error })) {
        throw new Error(`OpenWrite preset ${id} already exists without an ownership marker; preserve it under a custom preset name first`)
      }
      const staging = join(managedRoot, 'preset-' + randomUUID())
      await mkdir(staging, { recursive: true })
      try {
        await cp(source, staging, { recursive: true })
        const digest = await digestShipped(source, staging)
        await writeFile(join(staging, '.openwrite-managed.json'), JSON.stringify({ source: digest, tree: digest, version }))
        await rename(staging, destination)
      } finally { await rm(staging, { recursive: true, force: true }) }
    }
    await writeFile(lease, JSON.stringify({ pid: process.pid }), { mode: 0o600 })
  })
  // 0.1 resolves session identities through these directories. They must outlive
  // a host and a plugin upgrade; removing them strands historical sessions.
  ctx.effect(() => async () => withLock(async () => {
    await rm(lease, { force: true })
    for (const entry of await readdir(leases)) {
      const file = join(leases, entry)
      try {
        const record = JSON.parse(await readFile(file, 'utf8'))
        try { process.kill(record.pid, 0) }
        catch (error) { if (error.code === 'ESRCH') await rm(file, { force: true }) }
      } catch { /* unknown files never grant deletion authority */ }
    }
  }))
  // 0.1 discovers the managed directory above; 0.2 only accepts registered
  // definitions. The declaring context owns registration and its resolution base.
  ctx.inject(['agentPresets'], async function* (presetCtx) {
    if (typeof presetCtx.agentPresets.register !== 'function') return
    const definition = await presetDefinition(version, true)
    yield await presetCtx.agentPresets.register(definition)
    const discovered = (await readdir(join(home, '.agent-presets')).catch(() => []))
      .filter(name => /^openwrite-\d+-\d+-\d+(?:-[a-z0-9-]+)?$/.test(name))
    // An alias keeps a session written by an older release resumable. Registering
    // every released id instead floods the new-session selector with entries no
    // session references, so the alias set follows the session store and only
    // falls back to the durable list when that store cannot be read. This
    // release's own identity is excluded: it is registered as the stable preset
    // and its directory belongs to this plugin, so an alias for it is noise.
    const referenced = await referencedPresetIds(home)
    const ids = new Set([...(referenced ?? legacyPresetIds), ...discovered].filter(candidate => candidate !== id))
    for (const legacyId of ids) {
      // An author-supplied definition wins; readDocument checks presence without
      // waiting for host activation (list/resolve would deadlock startup).
      if (typeof presetCtx.agentPresets.readDocument === 'function') {
        try { await presetCtx.agentPresets.readDocument(legacyId); continue }
        catch (error) { if (error?.code !== 'agent-preset/not-found') throw error }
      }
      yield await presetCtx.agentPresets.register({ ...definition, id: legacyId,
        order: 1000, name: legacyAliasName(legacyId, definition.name),
      })
    }
  })
  // Companion status for the workbench's companion section, and the host's own
  // default-model selection, so OpenWrite's page in the host's settings dialog
  // can show which model dsh itself would use. The companion route reports
  // which implementation serves DoG and whether the optional integrations are
  // live; it never changes what the preset mounts. The model route carries no
  // key: the selection is a browser-visible fact, the key is not. Like every
  // other /studio-panel/* route both sit behind the host's
  // browser-authentication fence: without it any local process could read the
  // host version, the companion inventory and the host's model selection.
  ctx.inject(['webServer'], webCtx => webCtx.effect(() => {
    webCtx.webServer.register({
      kind: 'exact', path: '/studio-panel/companions', handler: async (req, res) => {
        const respond = (code, data) => { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(data)) }
        const connection = webCtx.get('connection')
        const rejection = connection ? connection.requestRejection({ headers: req.headers }) : 503
        if (rejection !== undefined) { respond(rejection, { error: 'dsh browser authentication required', message: 'dsh browser authentication required', code: 'AUTHENTICATION_REQUIRED' }); return }
        if (req.method !== 'GET') { respond(405, { error: 'Method not allowed', message: 'Method not allowed', code: 'METHOD_NOT_ALLOWED' }); return }
        respond(200, await companionSummary(home) ?? { host: null, dog: { installed: false, usable: false, version: null, reason: null }, ops: { installed: false, usable: false, version: null, reason: null }, freeModel: { installed: false, usable: false, version: null, reason: null } })
      },
    }, 'openwrite: companion status')
    webCtx.webServer.register({
      kind: 'exact', path: '/studio-panel/host-model', handler: async (req, res) => {
        const respond = (code, data) => { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(data)) }
        const connection = webCtx.get('connection')
        const rejection = connection ? connection.requestRejection({ headers: req.headers }) : 503
        if (rejection !== undefined) { respond(rejection, { error: 'dsh browser authentication required', message: 'dsh browser authentication required', code: 'AUTHENTICATION_REQUIRED' }); return }
        if (req.method !== 'GET') { respond(405, { error: 'Method not allowed', message: 'Method not allowed', code: 'METHOD_NOT_ALLOWED' }); return }
        respond(200, hostModelSelection(ctx))
      },
    }, 'openwrite: host model selection')
  }))
}
