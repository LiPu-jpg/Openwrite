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

export function inspectProfile(manifest, options = {}) {
  const bundles = Array.isArray(manifest?.dsh?.profile?.bundles) ? manifest.dsh.profile.bundles : []
  const dependencies = manifest?.dependencies && typeof manifest.dependencies === 'object'
    ? Object.keys(manifest.dependencies) : []
  const leftoverBundles = legacyPackages.filter(name => bundles.includes(name))
  const leftoverDeps = legacyPackages.filter(name => dependencies.includes(name))
  // A manifest that names the bundle while node_modules is gone is not a working
  // install; the caller passes bundlePresent so `installed` can say so. Without
  // it the diagnostic reported "installed: true" and the healthy instruction on
  // a profile that cannot boot.
  const bundlePresent = options.bundlePresent !== false
  return {
    leftover: [...new Set([...leftoverBundles, ...leftoverDeps])],
    leftoverBundles,
    leftoverDeps,
    installed: bundlePresent && bundles.filter(name => name === 'dsh-openwrite').length === 1,
    bundlePresent,
    malformedBundles: manifest?.dsh?.profile?.bundles !== undefined && !Array.isArray(manifest.dsh.profile.bundles),
    otherPlugins: bundles.filter(name => name !== 'dsh-openwrite' && !legacyPackages.includes(name)),
  }
}

export async function inspectPresets(home) {
  const dir = join(home, '.agent-presets')
  const names = await readdir(dir).catch(error => { if (error.code === 'ENOENT') return []; throw error })
  const presets = []
  for (const name of names) {
    const markerPath = join(dir, name, '.openwrite-managed.json')
    const raw = await readFile(markerPath, 'utf8').catch(() => null)
    // A marker that exists but does not parse is not the same as no marker: a
    // crash during the install (or a hand edit) can leave a truncated file, and
    // treating that as "author-owned" made the preset permanently unupgradable
    // with no diagnostic. Report it distinctly so the fix (re-run the installer)
    // is visible.
    let marker = null
    let origin = 'author-owned'
    if (raw !== null) {
      try { marker = JSON.parse(raw) } catch { marker = null; origin = 'marker-corrupt' }
      if (marker) origin = 'package-managed'
    }
    presets.push({ name, origin, preserved: true, marker })
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
  // The spec each removed dependency was installed from, so a failure midway can
  // put the packages back instead of leaving a half-migrated profile whose
  // manifest lists dependencies node_modules no longer contains.
  const removedSpecs = []
  try {
    if (await readFile(file, 'utf8') !== original) throw new Error('Profile changed during backup; retry with dsh stopped')
    for (const name of inspection.leftoverDeps) {
      const spec = manifest.dependencies?.[name]
      await runPlugin(home, profile, ['plugin', '--profile', profile, 'remove', '-w', name])
      if (typeof spec === 'string') removedSpecs.push(spec)
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
    // Restoring the manifest alone is not enough: the host remove already
    // deleted these packages from node_modules. Put them back so the profile the
    // user is left with is the one the manifest describes.
    for (const spec of removedSpecs) {
      await runPlugin(home, profile, ['plugin', '--profile', profile, 'add', '-w', spec]).catch(() => {})
    }
    error.message = `${error.message}; restored profile from ${backup}`
    throw error
  }
}

export async function diagnose(home, profile) {
  const { manifest } = await readManifest(home, profile)
  const presets = await inspectPresets(home)
  const runtime = await readFile(join(home, 'openwrite', 'active.json'), 'utf8').then(JSON.parse).catch(() => null)
  const installedPackage = await readFile(join(home, 'profiles', profile, 'node_modules', 'dsh-openwrite', 'package.json'), 'utf8').then(JSON.parse).catch(() => null)
  // A manifest that names the bundle while the tree is absent is not a working
  // install. Reading the package first lets `installed` say so, instead of
  // reporting healthy on a profile that cannot boot.
  const inspection = inspectProfile(manifest, { bundlePresent: installedPackage !== null })
  const toolPackage = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  const requestedSpec = manifest.dependencies?.['dsh-openwrite']
  const packageSelection = {
    // A private registry/git URL can contain credentials in its authority,
    // query, fragment or path. Do not copy it into a shareable diagnostic.
    requestedSpec: typeof requestedSpec === 'string'
      ? requestedSpec.includes('://') || /^[^\s@]+@[^\s:]+:/.test(requestedSpec) ? '[remote package URL redacted]' : requestedSpec
      : null,
    resolvedVersion: installedPackage?.version ?? null,
    diagnosticToolVersion: toolPackage.version,
    matchesDiagnosticTool: installedPackage?.version === toolPackage.version,
    reinstallTarget: `dsh-openwrite@${toolPackage.version}`,
    instructions: 'After stopping dsh and backing up the profile, explicitly select a verified version or @latest; a bare add may preserve the existing dependency selection. See docs/INSTALL.md#stale-package-selection.',
  }
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
    packageSelection,
    bundlePresent: inspection.bundlePresent,
    malformedBundles: inspection.malformedBundles,
    instructions: inspection.leftover.length
      ? 'Stop dsh, run openwrite-maintenance migrate --profile web --apply, then install the Release package. Author-owned presets and historical sessions are preserved.'
      : !inspection.bundlePresent
        ? 'The manifest lists dsh-openwrite but node_modules/dsh-openwrite is missing, so the plugin cannot load. Stop dsh, then reinstall with dsh plugin add dsh-openwrite@<verified version>.'
        : inspection.malformedBundles
          ? 'dsh.profile.bundles is not an array, so no bundle can be registered. Restore the profile manifest from a backup or reinstall the plugin.'
          : 'OpenWrite → 诊断与帮助：查看实时健康状态；本命令不启动模型。',
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const command = process.argv[2] ?? 'doctor'
  const index = process.argv.indexOf('--profile')
  const home = resolve(process.env.DSH_HOME || join(homedir(), '.dsh'))
  try {
    if (!['doctor', 'migrate'].includes(command)) throw new Error('Usage: openwrite-maintenance doctor|migrate --profile web [--apply]')
    // `--profile` with no value must be a usage error. `PROFILE.test(undefined)`
    // coerces to the string "undefined", which the pattern accepts, so the guard
    // downstream cannot catch it and the failure surfaces as a raw TypeError.
    if (index >= 0 && process.argv[index + 1] === undefined) throw new Error('Usage: openwrite-maintenance doctor|migrate --profile <name> [--apply]')
    const profile = index < 0 ? 'web' : process.argv[index + 1]
    console.log(JSON.stringify(await (command === 'migrate' ? migrate(home, profile, process.argv.includes('--apply')) : diagnose(home, profile)), null, 2))
  } catch (error) { console.error(error.message); process.exitCode = 1 }
}
