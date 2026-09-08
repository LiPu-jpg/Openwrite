#!/usr/bin/env node
// Local maintenance never reads manuscript directories or prints credentials.
import { cp, mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { homedir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'

export const legacyBundles = ['@dsh-novel/openwrite-bridge', '@dsh-novel/studio-panel', '@dsh-external/dsh-dog']
export async function migrate(home, profile, apply = false) {
  if (!/^[a-zA-Z0-9_-]+$/.test(profile)) throw new Error('Invalid profile name')
  const directory = join(home, 'profiles', profile)
  const file = join(directory, 'package.json')
  const original = await readFile(file, 'utf8')
  const manifest = JSON.parse(original)
  const bundles = manifest.dsh?.profile?.bundles ?? []
  const removed = legacyBundles.filter(name => bundles.includes(name))
  if (!apply || !removed.length) return { profile, removed, changed: false }
  // Preserve the exact original configuration and custom presets before changing
  // only the obsolete bundle registrations. Dependency removal is left to dsh.
  const backup = join(home, 'openwrite', 'migration-backups', randomUUID())
  await mkdir(backup, { recursive: true, mode: 0o700 })
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
  manifest.dsh.profile.bundles = bundles.filter(name => !removed.includes(name))
  await writeFile(join(backup, 'migration.json'), JSON.stringify({ profile, removed, time: new Date().toISOString() }, null, 2), { mode: 0o600 })
  if (await readFile(file, 'utf8') !== original) throw new Error('Profile changed during backup; retry with dsh stopped')
  const staging = file + '.openwrite-' + randomUUID()
  await writeFile(staging, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o600 })
  await rename(staging, file)
  return { profile, removed, changed: true, backup }
}

export async function diagnose(home, profile) {
  if (!/^[a-zA-Z0-9_-]+$/.test(profile)) throw new Error('Invalid profile name')
  const manifest = JSON.parse(await readFile(join(home, 'profiles', profile, 'package.json')))
  const bundles = manifest.dsh?.profile?.bundles ?? []
  const runtime = await readFile(join(home, 'openwrite', 'active.json'), 'utf8').then(JSON.parse).catch(() => null)
  return { node: process.version, platform: process.platform, arch: process.arch, profile,
    installed: bundles.filter(name => name === 'dsh-openwrite').length === 1,
    legacyBundles: bundles.filter(name => legacyBundles.includes(name)),
    runtimePrepared: runtime !== null, instructions: 'OpenWrite → 诊断与帮助：查看实时健康状态；本命令不启动模型。' }
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
