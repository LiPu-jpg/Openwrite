import { open, readFile, readdir, stat, mkdir, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { zstdDecompressSync } from 'node:zlib'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { load, Type, JSON_SCHEMA } from 'js-yaml'
import { detectCompanions } from './companions.mjs'
import { resolveDshHome } from '@deepseek-ai/dsh-home-paths'

// Preserve Loader expressions; evaluating them here loses the preset's baseUrl
// and entry-local realm. This is the host's entry-list !!js wire representation.
const schema = JSON_SCHEMA.extend(new Type('tag:yaml.org,2002:js', {
  kind: 'scalar', resolve: value => typeof value === 'string',
  construct: value => ({ __jsExpr: value }),
}))

export const stablePresetId = 'openwrite'

// These released identities are durable session references, even after their
// package-managed directories have been removed by older plugin versions. They
// are the safety net used when the session store cannot be read; the live alias
// set follows the sessions that actually reference them (see below).
/**
 * Every released identity on the current `major.minor` line.
 *
 * Derived from the package version rather than a hardcoded count: `{ length: 29 }`
 * could only ever express `0.2.x`, so a move to 0.3.0 or 1.0.0 structurally could
 * not produce the new identity and the durable-resume safety net would silently
 * omit it.
 */
const releaseVersion = JSON.parse(await readFile(new URL('package.json', import.meta.url), 'utf8')).version
const releaseLine = /^(\d+)\.(\d+)\.(\d+)/.exec(String(releaseVersion || ''))
export const legacyPresetIds = releaseLine === null
  ? []
  : Array.from({ length: Number(releaseLine[3]) }, (_, i) => `openwrite-${releaseLine[1]}-${releaseLine[2]}-${i + 1}`)

/** One released versioned preset identity, including any pre-release suffix. */
const versionedPresetId = /^openwrite-\d+-\d+-\d+(?:-[a-z0-9-]+)?$/

/** Session log artifacts, in both encodings the host persistence backend writes. */
const sessionLogSuffixes = ['.jsonl.zstd', '.jsonl']

/** A session header is the first frame of its log; a bounded prefix reads it. */
const headerPrefixBytes = 256 * 1024

/**
 * Name an alias after the release it restores. A bare id is an internal detail
 * that leaves dozens of identically prefixed entries in the preset selector.
 */
export function legacyAliasName(id, name) {
  if (!versionedPresetId.test(id)) return `${name}（历史会话 ${id}）`
  return `${name}（旧版 ${id.replace(/^openwrite-/, '').replaceAll('-', '.')} · 仅用于恢复历史会话）`
}

async function collectSessionLogs(root) {
  const logs = []
  const walk = async directory => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await walk(path)
      else if (sessionLogSuffixes.some(suffix => entry.name.endsWith(suffix))) logs.push(path)
    }
  }
  await walk(root)
  return logs
}

/**
 * A digest over every log's identity, not just {count, newest mtime}: deleting
 * one session and adding another in the same second keeps that pair unchanged
 * and would serve a stale alias set (a missing id, a lingering one). Stats only,
 * so this stays cheap enough to re-derive on every start.
 */
async function fingerprintLogs(logs) {
  const hash = createHash('sha256')
  const rows = []
  for (const path of logs) {
    let info
    try { info = await stat(path) } catch { continue }
    rows.push(`${path}\u0000${Math.round(info.mtimeMs)}\u0000${info.size}\n`)
  }
  rows.sort()
  for (const row of rows) hash.update(row)
  return { files: rows.length, digest: hash.digest('hex') }
}

/** The `agentPreset` a stored session header carries, or undefined when unreadable. */
async function headerPresetId(path) {
  const handle = await open(path, 'r')
  try {
    const buffer = Buffer.alloc(headerPrefixBytes)
    const { bytesRead } = await handle.read(buffer, 0, headerPrefixBytes, 0)
    const head = buffer.subarray(0, bytesRead)
    // node:zlib decodes the leading frame and ignores the appended event frames.
    const text = path.endsWith('.zstd') ? zstdDecompressSync(head).toString('utf8') : head.toString('utf8')
    const header = JSON.parse(text.split('\n', 1)[0])
    return typeof header?.agentPreset === 'string' ? header.agentPreset : undefined
  } finally {
    await handle.close()
  }
}

/**
 * The versioned preset ids stored sessions still reference. Registering every
 * released id instead would fill the new-session selector with entries no
 * session can resume, so the alias set is derived from the session store.
 * Returns null when that store cannot be read at all, which keeps the durable
 * alias list rather than silently dropping historical session resume.
 */
export async function referencedPresetIds(home) {
  const root = join(home, 'sessions')
  let logs
  try {
    logs = await collectSessionLogs(root)
  } catch (error) {
    if (error?.code !== 'ENOENT') return null
    logs = []
  }
  // fingerprintLogs skips logs it cannot stat (a dangling symlink, or one the
  // host prunes mid-scan); a walk that cannot even be listed is the only case
  // that falls back to the durable list.
  const fingerprint = await fingerprintLogs(logs).catch(() => null)
  if (!fingerprint) return null
  const cache = join(home, 'openwrite', 'preset-aliases.json')
  const cached = await readFile(cache, 'utf8').then(JSON.parse).catch(() => null)
  if (cached?.fingerprint?.files === fingerprint.files && cached.fingerprint.digest === fingerprint.digest) {
    return new Set((cached.ids ?? []).filter(id => versionedPresetId.test(id)))
  }
  const ids = new Set()
  for (const path of logs) {
    const id = await headerPresetId(path).catch(() => undefined)
    if (id && versionedPresetId.test(id)) ids.add(id)
  }
  await mkdir(join(home, 'openwrite'), { recursive: true }).catch(() => {})
  await writeFile(cache, JSON.stringify({ fingerprint, ids: [...ids] }) + '\n').catch(() => {})
  return ids
}

/**
 * Mount dsh-ops into this preset when the companion is installed, its declared
 * host range covers the running host, and it exposes the integration entry.
 */
async function adaptCompanions(plugins, options) {
  if (plugins.some(row => row.id === 'openwrite-ops')) return
  let companions = null
  try {
    companions = await detectCompanions(resolveDshHome(), options)
  } catch { /* an unreadable home leaves the preset exactly as shipped */ }
  if (!companions?.ops?.usable) return
  plugins.push({ id: 'openwrite-ops', name: 'dsh-openwrite/ops-integration' })
}

export async function presetDefinition(version, modern = false, options = {}) {
  const baseUrl = new URL('./presets/openwrite/', import.meta.url)
  const plugins = load(await readFile(new URL('agent.cordis.yml', baseUrl), 'utf8'), { schema })
  const metadata = load(await readFile(new URL('preset.yml', baseUrl), 'utf8'))
  if (modern) {
    const adapt = rows => {
      for (const row of rows) {
        // The workflow row is renamed for hosts that ship the PTC variant. This
        // repo's node_modules carries an older host without that package, so the
        // resolution gate treats it as expected-absent rather than failing (see
        // scripts/preset-smoke.mjs).
        if (row.name === '@deepseek-ai/dsh-workflow-worker-thread') {
          row.name = '@deepseek-ai/dsh-workflow-ptc'
        }
        if (row.name === '@deepseek-ai/dsh-skill-filesystem') {
          row.config.customSkillDirs = [fileURLToPath(new URL('skills/', baseUrl))]
        }
        if (row.group && Array.isArray(row.config)) adapt(row.config)
      }
    }
    adapt(plugins)
  }
  await adaptCompanions(plugins, options)
  return { ...metadata, id: stablePresetId, order: -1, plugins }
}
