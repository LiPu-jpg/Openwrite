#!/usr/bin/env node
// Local maintenance never reads manuscript directories or prints credentials.
import { cp, mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { homedir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'

export const legacyPackages = ['@dsh-novel/openwrite-bridge', '@dsh-novel/studio-panel', '@dsh-external/dsh-dog']
export const legacyBundles = legacyPackages

const PROFILE = /^[a-zA-Z0-9_-]+$/
const PROFILE_FILES = ['package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'cordis.patch.yml']

export function inspectProfile(manifest) {
  const bundles = Array.isArray(manifest?.dsh?.profile?.bundles) ? manifest.dsh.profile.bundles : []
  const dependencies = manifest?.dependencies && typeof manifest.dependencies === 'object'
    ? Object.keys(manifest.dependencies) : []
  const leftoverBundles = legacyPackages.filter(name => bundles.includes(name))
  const leftoverDeps = legacyPackages.filter(name => dependencies.includes(name))
  return {
    leftover: [...new Set([...leftoverBundles, ...leftoverDeps])],
    leftoverBundles,
    leftoverDeps,
    installed: bundles.filter(name => name === 'dsh-openwrite').length === 1,
    otherPlugins: bundles.filter(name => name !== 'dsh-openwrite' && !legacyPackages.includes(name)),
  }
}

export async function inspectPresets(home) {
  const dir = join(home, '.agent-presets')
  const names = await readdir(dir).catch(error => { if (error.code === 'ENOENT') return []; throw error })
  const presets = []
  for (const name of names) {
    const marker = await readFile(join(dir, name, '.openwrite-managed.json'), 'utf8').then(JSON.parse).catch(() => null)
    presets.push({ name, origin: marker ? 'package-managed' : 'author-owned', preserved: true })
  }
  return presets
}

export function defaultRunPlugin(home, _profile, args) {
  const bin = process.env.DSH_BIN
  const command = bin && /\.[cm]?js$/.test(bin) ? process.execPath : (bin || 'dsh')
  const argv = bin && /\.[cm]?js$/.test(bin) ? [bin, ...args] : args
  const result = spawnSync(command, argv, {
    cwd: home,
    env: { ...process.env, DSH_HOME: home },
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 8 * 1024 ** 2,
    windowsHide: true,
  })
  if (result.error?.code === 'ENOENT') {
    throw new Error('dsh not found; install the accepted host and re-run migrate with dsh stopped')
  }
  if (result.status !== 0) {
    throw new Error(`dsh ${args.join(' ')} failed: ${(result.stderr || result.stdout || result.error?.message || '').trim() || `exit ${result.status}`}`)
  }
  return result.stdout
}

async function readManifest(home, profile) {
  if (!PROFILE.test(profile)) throw new Error('Invalid profile name')
  const file = join(home, 'profiles', profile, 'package.json')
  const original = await readFile(file, 'utf8')
  return { file, original, manifest: JSON.parse(original), directory: join(home, 'profiles', profile) }
}

async function backupProfile(home, profile, extra) {
  const backup = join(home, 'openwrite', 'migration-backups', randomUUID())
  await mkdir(backup, { recursive: true, mode: 0o700 })
  const directory = join(home, 'profiles', profile)
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isFile() && /\.(?:json|ya?ml)$/.test(entry.name)) {
      await cp(join(directory, entry.name), join(backup, entry.name))
    }
  }
  for (const name of ['settings.yaml', '.agent-presets']) {
    await cp(join(home, name), join(backup, name), { recursive: true, dereference: false }).catch(error => {
      if (error.code !== 'ENOENT') throw error
    })
  }
  await writeFile(join(backup, 'migration.json'), JSON.stringify({
    profile, time: new Date().toISOString(), ...extra,
  }, null, 2), { mode: 0o600 })
  return backup
}

export async function restoreBackup(backup, home, profile) {
  if (!PROFILE.test(profile)) throw new Error('Invalid profile name')
  const directory = join(home, 'profiles', profile)
  for (const name of PROFILE_FILES) {
    await cp(join(backup, name), join(directory, name)).catch(error => {
      if (error.code !== 'ENOENT') throw error
    })
  }
}

async function stripRemainingBundles(file, original, leftoverBundles) {
  if (!leftoverBundles.length) return false
  if (await readFile(file, 'utf8') !== original) {
    // Host remove already rewrote the manifest; re-read rather than clobber it.
    original = await readFile(file, 'utf8')
  }
  const manifest = JSON.parse(original)
  const bundles = manifest.dsh?.profile?.bundles ?? []
  const next = bundles.filter(name => !legacyPackages.includes(name))
  if (next.length === bundles.length) return false
  if (!manifest.dsh) manifest.dsh = {}
  if (!manifest.dsh.profile) manifest.dsh.profile = {}
  manifest.dsh.profile.bundles = next
  const staging = file + '.openwrite-' + randomUUID()
  await writeFile(staging, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
  await rename(staging, file)
  return true
}

export async function migrate(home, profile, apply = false, options = {}) {
  const { file, original, manifest } = await readManifest(home, profile)
  const inspection = inspectProfile(manifest)
  const presets = await inspectPresets(home)
  const base = { profile, ...inspection, presets, changed: false }
  if (!apply || !inspection.leftover.length) return base
  const backup = await backupProfile(home, profile, {
    leftover: inspection.leftover, leftoverBundles: inspection.leftoverBundles, leftoverDeps: inspection.leftoverDeps,
  })
  const runPlugin = options.runPlugin ?? defaultRunPlugin
  try {
    if (await readFile(file, 'utf8') !== original) throw new Error('Profile changed during backup; retry with dsh stopped')
    for (const name of inspection.leftoverDeps) {
      await runPlugin(home, profile, ['plugin', '--profile', profile, 'remove', '-w', name])
    }
    const afterRemove = await readFile(file, 'utf8')
    const remaining = inspectProfile(JSON.parse(afterRemove))
    await stripRemainingBundles(file, afterRemove, remaining.leftoverBundles)
    const final = inspectProfile(JSON.parse(await readFile(file, 'utf8')))
    if (final.leftover.length) {
      throw new Error(`legacy packages still present after host remove: ${final.leftover.join(', ')}`)
    }
    return { ...base, leftover: [], leftoverBundles: [], leftoverDeps: [], changed: true, backup, otherPlugins: final.otherPlugins }
  } catch (error) {
    await restoreBackup(backup, home, profile)
    error.message = `${error.message}; restored profile from ${backup}`
    throw error
  }
}

export async function diagnose(home, profile) {
  const { manifest } = await readManifest(home, profile)
  const inspection = inspectProfile(manifest)
  const presets = await inspectPresets(home)
  const runtime = await readFile(join(home, 'openwrite', 'active.json'), 'utf8').then(JSON.parse).catch(() => null)
  return {
    node: process.version, platform: process.platform, arch: process.arch, profile,
    installed: inspection.installed,
    leftover: inspection.leftover,
    leftoverBundles: inspection.leftoverBundles,
    leftoverDeps: inspection.leftoverDeps,
    legacyBundles: inspection.leftoverBundles,
    otherPlugins: inspection.otherPlugins,
    presets,
    runtimePrepared: runtime !== null,
    instructions: inspection.leftover.length
      ? 'Stop dsh, run openwrite-maintenance migrate --profile web --apply, then install the Release package. Author-owned presets and historical sessions are preserved.'
      : 'OpenWrite → 诊断与帮助：查看实时健康状态；本命令不启动模型。',
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const command = process.argv[2] ?? 'doctor'
  const index = process.argv.indexOf('--profile')
  const profile = index < 0 ? 'web' : process.argv[index + 1]
  const home = resolve(process.env.DSH_HOME || join(homedir(), '.dsh'))
  try {
    if (!['doctor', 'migrate'].includes(command)) throw new Error('Usage: openwrite-maintenance doctor|migrate --profile web [--apply]')
    console.log(JSON.stringify(await (command === 'migrate' ? migrate(home, profile, process.argv.includes('--apply')) : diagnose(home, profile)), null, 2))
  } catch (error) { console.error(error.message); process.exitCode = 1 }
}
