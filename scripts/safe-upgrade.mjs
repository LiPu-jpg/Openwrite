#!/usr/bin/env node
// Offline profile upgrades retain the previous complete dependency tree until commit.
import { cp, mkdir, readFile, readdir, rename, writeFile, open, access, readlink, symlink, unlink, realpath, lstat, rmdir, utimes } from 'node:fs/promises'
import { spawn, spawnSync } from 'node:child_process'
import { join, resolve, relative, isAbsolute, dirname, sep } from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { homedir } from 'node:os'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

const PROFILE = /^[a-zA-Z0-9_-]+$/
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
function upgradeDependencies(home, profile) {
  // Release archives do not contain node_modules. Resolve the same dependencies
  // from the explicitly selected installed profile, without loading its plugin.
  const resolvers = [createRequire(import.meta.url), createRequire(join(profileDirectory(home, profile), 'package.json'))]
  const load = name => {
    for (const require of resolvers) {
      try { return require(name) } catch (error) {
        if (error.code !== 'MODULE_NOT_FOUND') throw error
      }
    }
    throw new Error(`UPGRADE_DEPENDENCY_MISSING: ${name}; run this tool from an installed OpenWrite package or repair dependencies in the selected profile first`)
  }
  return { acquireLock: load('proper-lockfile').lock, yaml: load('js-yaml') }
}
async function exists(path) { try { await access(path); return true } catch (error) { if (error.code === 'ENOENT') return false; throw error } }
async function save(path, value) {
  const pending = path + '.pending-' + randomUUID()
  await writeFile(pending, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 })
  await rename(pending, path)
}

// Recovery cannot load dependencies through a profile which is between renames.
// Use proper-lockfile's same canonical <profiles>.lock directory and fresh mtime
// protocol, without importing any code from the missing or backup profile.
export async function acquireRecoveryLock(home) {
  const path = (await realpath(join(resolve(home), 'profiles'))) + '.lock'
  const locked = () => Object.assign(new Error('ELOCKED: another profile operation holds the upgrade lock'), { code: 'ELOCKED' })
  const same = (a, b) => a.dev === b.dev && a.ino === b.ino && a.birthtimeMs === b.birthtimeMs
  let owner
  for (let attempt = 0; attempt < 3; attempt++) {
    try { await mkdir(path, { mode: 0o700 }); owner = await lstat(path); break }
    catch (error) {
      if (error.code !== 'EEXIST') throw error
      let observed
      try { observed = await lstat(path) } catch (cause) { if (cause.code === 'ENOENT') continue; throw cause }
      if (!observed.isDirectory() || Date.now() - observed.mtimeMs <= 30_000) throw locked()
      const current = await lstat(path)
      if (!same(observed, current) || observed.mtimeMs !== current.mtimeMs) throw locked()
      try { await rmdir(path) } catch (cause) { if (cause.code !== 'ENOENT') throw locked() }
    }
  }
  if (!owner) throw locked()
  let pending = Promise.resolve(), compromised
  const assertOwned = async () => {
    if (compromised) throw compromised
    const current = await lstat(path)
    if (!same(owner, current)) throw locked()
  }
  const timer = setInterval(() => {
    pending = pending.then(async () => {
      await assertOwned()
      const now = new Date()
      await utimes(path, now, now)
    }).catch(error => { compromised = error })
  }, 1000)
  timer.unref()
  return {
    async assertOwned() { await pending; await assertOwned() },
    async release() {
      clearInterval(timer)
      await pending
      await assertOwned()
      await rmdir(path)
    },
  }
}

async function pinArchive(home, archive) {
  const bytes = await readFile(archive)
  const sha256 = digest(bytes)
  const cache = join(resolve(home), 'openwrite', 'packages')
  await mkdir(cache, { recursive: true, mode: 0o700 })
  const destination = join(cache, sha256 + '.tgz')
  if (await exists(destination) && digest(await readFile(destination)) === sha256) return { path: destination, sha256 }
  const pending = join(cache, '.' + sha256 + '-' + randomUUID() + '.pending')
  try {
    const handle = await open(pending, 'wx', 0o600)
    try { await handle.writeFile(bytes); await handle.sync() } finally { await handle.close() }
    if (digest(await readFile(pending)) !== sha256) throw new Error('PACKAGE_CACHE_CONFLICT: temporary archive verification failed')
    await rename(pending, destination)
    return { path: destination, sha256 }
  } finally { try { await unlink(pending) } catch (error) { if (error.code !== 'ENOENT') throw error } }
}

async function relocateProfileLinks(staging, previous, replacementRoot, yaml) {
  const visit = async directory => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isSymbolicLink()) {
        const link = await readlink(path)
        if (isAbsolute(link) && (link === previous || link.startsWith(previous + sep))) {
          const moved = join(replacementRoot, relative(previous, link))
          await unlink(path)
          await symlink(process.platform === 'win32' ? moved : relative(dirname(path), moved), path, process.platform === 'win32' ? 'junction' : undefined)
        }
      } else if (entry.isDirectory()) await visit(path)
    }
  }
  await visit(staging)
  const path = join(staging, 'node_modules', '.modules.yaml')
  if (await exists(path)) {
    const modules = yaml.load(await readFile(path, 'utf8'))
    if (modules && typeof modules.virtualStoreDir === 'string' && isAbsolute(modules.virtualStoreDir)) {
      if (!modules.virtualStoreDir.startsWith(previous + sep)) throw new Error('UNSUPPORTED_STORE: profile virtual store is outside its dependency tree')
      modules.virtualStoreDir = relative(join(replacementRoot, 'node_modules'), join(replacementRoot, relative(previous, modules.virtualStoreDir)))
      await writeFile(path, yaml.dump(modules), { mode: 0o600 })
    }
  }
}

/** Refuse mutation while Desktop, dsh, or an OpenWrite managed backend is alive. */
export async function assertHostStopped(home, profile) {
  const command = process.platform === 'win32' ? 'powershell.exe' : 'ps'
  const args = process.platform === 'win32'
    ? ['-NoProfile', '-NonInteractive', '-Command', 'Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress']
    : ['-axo', 'pid=,command=']
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: 10000, windowsHide: true, maxBuffer: 8 * 1024 ** 2 })
  if (result.error || result.status !== 0) throw new Error('HOST_STATE_UNKNOWN: cannot inspect running processes; no profile files changed')
  const processes = process.platform === 'win32'
    ? [].concat(JSON.parse(result.stdout || '[]')).map(row => ({ pid: row.ProcessId, command: row.CommandLine || '' }))
    : result.stdout.split('\n').flatMap(line => { const match = /^\s*(\d+)\s+(.+)$/.exec(line); return match ? [{ pid: Number(match[1]), command: match[2] }] : [] })
  const active = processes.filter(row => row.pid !== process.pid && (
    /(?:DeepSeek Harness|DSH Desktop|dsh-desktop|dsh-host-desktop|tools\.managed_runtime)/i.test(row.command)
    || /(?:^|[\\/\s])dsh(?:[\\/\s.]|$)/i.test(row.command) && !/\splugin\s/.test(row.command)
      && !/safe-upgrade|openwrite-maintenance/.test(row.command)
  ))
  if (active.length) throw new Error(`HOST_RUNNING: quit DSH Desktop and stop dsh before upgrading ${profile}; active process IDs: ${active.map(row => row.pid).join(', ')}`)
}

async function runInstall(home, profile, spec, log) {
  const bin = process.env.DSH_BIN || 'dsh'
  if (process.platform === 'win32' && !/\.[cm]?js$/.test(bin)) throw new Error('DSH_BIN_REQUIRED: set DSH_BIN to the accepted Desktop runtime lib/bin.js before upgrading')
  const command = /\.[cm]?js$/.test(bin) ? process.execPath : bin
  const args = [...(/\.[cm]?js$/.test(bin) ? [bin] : []), 'plugin', '--profile', profile, 'add', '-w', spec]
  let writes = Promise.resolve()
  const child = spawn(command, args, { env: { ...process.env, DSH_HOME: home }, cwd: home,
    stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true, detached: process.platform !== 'win32' })
  let timer, drainTimer, escalation
  for (const stream of [child.stdout, child.stderr]) stream.on('data', bytes => { writes = writes.then(() => log.write(bytes)) })
  try {
    await new Promise((accept, reject) => {
      timer = setTimeout(() => {
        if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, timeout: 5000 })
        else { try { process.kill(-child.pid, 'SIGKILL') } catch (error) { if (error.code !== 'ESRCH') process.stderr.write(`Installer termination failed: ${error.message}\n`) } }
        escalation = setTimeout(() => { child.stdout.destroy(); child.stderr.destroy(); reject(new Error('INSTALL_TIMEOUT: staged installer exceeded 180 seconds; active profile unchanged')) }, 2000)
      }, 180000)
      child.once('exit', () => { drainTimer = setTimeout(() => { child.stdout.destroy(); child.stderr.destroy() }, 2000) })
      child.once('error', reject)
      child.once('close', (code, signal) => code === 0 ? accept() : reject(new Error(`INSTALL_FAILED: exit=${code}, signal=${signal || ''}`)))
    })
  } finally { clearTimeout(timer); clearTimeout(drainTimer); clearTimeout(escalation); await writes }
}

function profileDirectory(home, profile) {
  if (!PROFILE.test(profile)) throw new Error('Invalid profile name')
  return join(resolve(home), 'profiles', profile)
}

/** Recover a previously approved directory swap without overwriting later edits. */
export async function recoverUpgrade(home, operationId, options = {}) {
  if (!/^upgrade_[a-f0-9-]+$/.test(operationId)) throw new Error('Invalid upgrade operation ID')
  const root = join(resolve(home), 'openwrite', 'upgrades', operationId)
  const operation = JSON.parse(await readFile(join(root, 'operation.json'), 'utf8'))
  const target = profileDirectory(home, operation.profile)
  await (options.assertStopped || assertHostStopped)(home, operation.profile)
  const previous = join(root, 'previous-profile')
  const lease = await acquireRecoveryLock(home)
  try {
    if (!await exists(target) && await exists(previous)) {
      if (!operation.old_manifest_sha256 || digest(await readFile(join(previous, 'package.json'))) !== operation.old_manifest_sha256) {
        throw new Error('PROFILE_CHANGED: backup manifest differs from the approved operation; no profile restored')
      }
      await lease.assertOwned()
      await rename(previous, target)
      operation.status = 'rolled_back'
    } else if (await exists(target)) {
      const actual = digest(await readFile(join(target, 'package.json')))
      if (actual === operation.new_manifest_sha256) operation.status = 'completed'
      else if (actual === operation.old_manifest_sha256) operation.status = 'rolled_back'
      else throw new Error('PROFILE_CHANGED: preserve the backup and reconcile the profile manually')
    } else throw new Error('RECOVERY_REQUIRED: neither active nor previous profile is available')
    await lease.assertOwned()
    await save(join(root, 'operation.json'), operation)
    return { operation_id: operationId, status: operation.status, backup: previous }
  } finally { await lease.release() }
}

/** Stage a complete profile beside the active tree, validate, then swap while stopped. */
export async function upgradeProfile(home, profile, spec, options = {}) {
  if (typeof spec !== 'string' || !spec || spec.startsWith('-') || /[\r\n]/.test(spec)) throw new Error('A package spec or Release tarball is required')
  const target = profileDirectory(home, profile)
  const stopped = options.assertStopped || assertHostStopped
  await stopped(home, profile)
  const { acquireLock, yaml } = upgradeDependencies(home, profile)
  const release = await acquireLock(join(home, 'profiles'), { realpath: true, retries: 0 })
  const id = 'upgrade_' + randomUUID()
  const root = join(resolve(home), 'openwrite', 'upgrades', id)
  const stagingName = 'openwrite-stage-' + randomUUID()
  const staging = profileDirectory(home, stagingName)
  const previous = join(root, 'previous-profile')
  const logPath = join(root, 'pnpm.log')
  let log
  let moved = false
  const operation = { operation_id: id, profile, spec, status: 'preparing', created_at: new Date().toISOString() }
  try {
    await mkdir(root, { recursive: true, mode: 0o700 })
    log = await open(logPath, 'wx', 0o600)
    await log.write('Preparing isolated profile installation. The active profile is unchanged.\n')
    const oldManifest = await readFile(join(target, 'package.json'))
    operation.old_manifest_sha256 = digest(oldManifest)
    await save(join(root, 'operation.json'), operation)
    await cp(target, staging, { recursive: true, dereference: false, verbatimSymlinks: true,
      filter: source => !source.includes('/.plugin-manager/') && !source.endsWith('/.plugin-manager') })
    await relocateProfileLinks(staging, target, staging, yaml)
    // A downloaded tarball may live in a disposable directory. Pin its bytes
    // below DSH_HOME before the installer writes file: references into locks.
    let installSpec = spec
    const localPath = spec.startsWith('file:') ? spec.slice(5) : spec
    if (/\.(?:tgz|tar\.gz)$/i.test(localPath) && await exists(resolve(localPath))) {
      const archive = resolve(localPath)
      const pinned = await pinArchive(home, archive)
      installSpec = pinned.path
      operation.install_spec = installSpec
      operation.package_sha256 = pinned.sha256
      await save(join(root, 'operation.json'), operation)
    }
    await (options.run || runInstall)(home, stagingName, installSpec, log)
    const installed = JSON.parse(await readFile(join(staging, 'node_modules', 'dsh-openwrite', 'package.json'), 'utf8'))
    if (installed.name !== 'dsh-openwrite' || !installed.version || !installed.dsh?.bundle?.patch) throw new Error('BUNDLE_INCOMPLETE: staged OpenWrite manifest is invalid')
    const bundleRoot = join(staging, 'node_modules', 'dsh-openwrite')
    const patchPath = resolve(bundleRoot, installed.dsh.bundle.patch)
    if (!patchPath.startsWith(bundleRoot + sep)) throw new Error('BUNDLE_INCOMPLETE: invalid bundle patch path')
    for (const file of [patchPath, ...['plugin.mjs', 'packages/openwrite-bridge/lib/index.js', 'packages/studio-panel/lib/client.js'].map(name => join(bundleRoot, name))]) await access(file)
    operation.new_manifest_sha256 = digest(await readFile(join(staging, 'package.json')))
    if (digest(await readFile(join(target, 'package.json'))) !== operation.old_manifest_sha256) throw new Error('PROFILE_CHANGED: the active profile changed during staging')
    await stopped(home, profile)
    await relocateProfileLinks(staging, staging, target, yaml)
    operation.status = 'swapping'
    await save(join(root, 'operation.json'), operation)
    await rename(target, previous)
    moved = true
    await rename(staging, target)
    operation.status = 'completed'
    operation.version = installed.version
    await save(join(root, 'operation.json'), operation)
    await log.write('Upgrade committed. Previous complete profile retained in previous-profile.\n')
    return { operation_id: id, status: operation.status, version: installed.version, backup: previous, log: logPath }
  } catch (error) {
    try { await log?.write(`${error.stack || error.message}\n`) } catch (logError) { process.stderr.write(`Upgrade diagnostic could not be written: ${logError.message}\n`) }
    if (moved && !await exists(target)) {
      try { await rename(previous, target); operation.status = 'rolled_back' }
      catch (rollbackError) { operation.status = 'recovery_required'; await log.write(`Rollback failed: ${rollbackError.message}\n`) }
    } else operation.status = moved ? 'recovery_required' : 'failed'
    await save(join(root, 'operation.json'), operation)
    error.message += `; operation=${id}; log=${logPath}`
    throw error
  } finally { try { await log?.close() } finally { await release() } }
}

/** Disable only an incomplete OpenWrite bundle so a stopped profile can boot for repair. */
export async function repairProfile(home, profile, apply = false, options = {}) {
  const target = profileDirectory(home, profile)
  const manifestPath = join(target, 'package.json')
  const original = await readFile(manifestPath, 'utf8')
  const manifest = JSON.parse(original)
  let broken = false
  try { const pkg = JSON.parse(await readFile(join(target, 'node_modules', 'dsh-openwrite', 'package.json'), 'utf8')); broken = pkg.name !== 'dsh-openwrite' }
  catch (error) { if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error; broken = true }
  const enabled = manifest.dsh?.profile?.bundles?.includes('dsh-openwrite') === true
  if (!apply || !broken || !enabled) return { profile, incomplete: broken, enabled, changed: false }
  await (options.assertStopped || assertHostStopped)(home, profile)
  const { acquireLock } = upgradeDependencies(home, profile)
  const release = await acquireLock(join(home, 'profiles'), { realpath: true, retries: 0 })
  try {
    if (await readFile(manifestPath, 'utf8') !== original) throw new Error('PROFILE_CHANGED: refresh repair inspection')
    const backup = join(target, 'package.json.openwrite-repair-' + randomUUID())
    await writeFile(backup, original, { mode: 0o600 })
    manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter(name => name !== 'dsh-openwrite')
    await save(manifestPath, manifest)
    return { profile, changed: true, backup, incomplete: true, enabled: false }
  } finally { await release() }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const value = name => { const i = process.argv.indexOf(name); return i < 0 ? undefined : process.argv[i + 1] }
  const home = resolve(process.env.DSH_HOME || join(homedir(), '.dsh'))
  try {
    const profile = value('--profile') || 'web'
    const result = value('--recover') ? await recoverUpgrade(home, value('--recover'))
      : process.argv.includes('--repair') ? await repairProfile(home, profile, process.argv.includes('--apply'))
      : await upgradeProfile(home, profile, value('--package'))
    console.log(JSON.stringify(result, null, 2))
  } catch (error) { console.error(error.message); process.exitCode = 1 }
}
