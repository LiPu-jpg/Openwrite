import { cp, lstat, mkdir, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises'
import { createHash, randomUUID } from 'node:crypto'
import { lock } from 'proper-lockfile'
import { resolveDshHome } from '@deepseek-ai/dsh-home-paths'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-openwrite'

async function digestTree(dir) {
  const hash = createHash('sha256')
  async function visit(path, prefix = '') {
    for (const entry of (await readdir(path, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.name === '.openwrite-managed.json') continue
      const key = prefix + entry.name
      hash.update(key)
      if (entry.isDirectory()) await visit(join(path, entry.name), key + '/')
      else hash.update(await readFile(join(path, entry.name)))
    }
  }
  await visit(dir)
  return hash.digest('hex')
}

/** A versioned preset leaves existing authored copies and session identities alone. */
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
  const expected = await digestTree(source)
  const marker = join(destination, '.openwrite-managed.json')
  await withLock(async () => {
    const existing = await readFile(marker, 'utf8').then(JSON.parse).catch(() => null)
    if (existing && (existing.source !== expected || existing.tree !== await digestTree(destination))) {
      throw new Error(`OpenWrite preset ${id} was modified; copy it to a custom preset before reinstalling this version`)
    }
    if (!existing) {
      if (await lstat(destination).then(() => true).catch(error => { if (error.code === 'ENOENT') return false; throw error })) {
        throw new Error(`OpenWrite preset ${id} already exists without an ownership marker; preserve it under a custom preset name first`)
      }
      const staging = join(managedRoot, 'preset-' + randomUUID())
      await mkdir(staging, { recursive: true })
      try {
        await cp(source, staging, { recursive: true })
        await writeFile(join(staging, '.openwrite-managed.json'), JSON.stringify({ source: expected, tree: expected, version }))
        await rename(staging, destination)
      } finally { await rm(staging, { recursive: true, force: true }) }
    }
    await writeFile(lease, JSON.stringify({ pid: process.pid }), { mode: 0o600 })
  })
  // Preset files are package-managed UI entries. Remove only our unmodified
  // copy after its last live host stops; authored copies and session logs remain.
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
    if ((await readdir(leases)).length !== 0) return
    const owned = await readFile(marker, 'utf8').then(JSON.parse).catch(() => null)
    if (owned?.source === expected && owned.tree === await digestTree(destination).catch(() => null)) {
      await rm(destination, { recursive: true })
    }
  }))
}
