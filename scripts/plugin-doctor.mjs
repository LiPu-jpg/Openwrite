#!/usr/bin/env node
// Offline maintenance checks. Never reads credentials, starts a model, or edits profiles.
import { readFile, realpath } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { isAbsolute, join, resolve } from 'node:path'
import { load } from 'js-yaml'

const root = fileURLToPath(new URL('../', import.meta.url))
const packageDirs = ['.', 'packages/openwrite-bridge', 'packages/studio-panel']
const isDsh = name => /^@deepseek-ai\/dsh(?:-|$)/.test(name)
const lockName = path => path.match(/(?:^|\/)node_modules\/(@deepseek-ai\/[^/]+)$/)?.[1]
const readJson = async path => JSON.parse(await readFile(path, 'utf8'))
const exactVersion = value => /^\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(value ?? '')

export function auditVersions(manifest, lock, baseline) {
  const errors = []
  if (!exactVersion(baseline)) errors.push('DSH baseline must be an exact version')
  for (const field of ['dependencies', 'devDependencies', 'peerDependencies']) {
    const declared = manifest[field] ?? {}
    const locked = lock.packages?.['']?.[field] ?? {}
    for (const name of new Set([...Object.keys(declared), ...Object.keys(locked)])) {
      if (declared[name] !== locked[name]) errors.push(`lock metadata differs: ${field}.${name}`)
      if (isDsh(name) && declared[name] !== undefined && declared[name] !== baseline) {
        errors.push(`unpinned DSH dependency: ${name}=${declared[name]}`)
      }
      if (isDsh(name) && declared[name] !== undefined
        && (field !== 'peerDependencies' || !manifest.peerDependenciesMeta?.[name]?.optional)
        && !lock.packages?.[`node_modules/${name}`]) {
        errors.push(`required SDK missing from lock: ${name}`)
      }
    }
  }
  for (const [path, entry] of Object.entries(lock.packages ?? {})) {
    const name = lockName(path)
    if (name && isDsh(name) && entry.version !== baseline) {
      errors.push(`DSH lock drift: ${name}=${entry.version}, expected ${baseline}`)
    }
    if (name && isDsh(name) && manifest.overrides?.[name] !== baseline) {
      errors.push(`missing DSH override: ${name}`)
    }
    if (name === '@deepseek-ai/cordis' && entry.version !== '4.0.1') {
      errors.push(`Cordis lock drift: ${entry.version}, expected 4.0.1`)
    }
  }
  if (!lock.packages?.['']) errors.push('missing lockfile root metadata')
  return errors
}

const exportPaths = value => typeof value === 'string' ? [value]
  : value && typeof value === 'object' ? Object.values(value).flatMap(exportPaths) : []
const packagePath = path => path?.replace(/^\.\//, '')

export function auditBundle(manifest, files, patch) {
  const errors = []
  const available = new Set(files)
  const required = [manifest.main, manifest.types, manifest.dsh?.bundle?.patch,
    ...exportPaths(manifest.exports)]
  if (!manifest.dsh?.bundle?.patch) errors.push('missing dsh.bundle.patch')
  if (!manifest.main || !manifest.types) errors.push('missing host JS/types entry')
  for (const path of required.filter(Boolean)) {
    if (isAbsolute(path) || path.split(/[\\/]/).includes('..') || path.includes('\\')) {
      errors.push(`entry escapes package: ${path}`)
    } else if (!available.has(packagePath(path))) errors.push(`entry missing from tarball: ${path}`)
  }
  const rows = Array.isArray(patch) ? patch.flatMap(op => op?.insert ?? []) : []
  if (rows.filter(row => row.name === manifest.name).length !== 1) {
    errors.push('bundle patch must mount its host package exactly once')
  }
  const ids = rows.map(row => row.id)
  if (ids.some(id => typeof id !== 'string' || !id) || new Set(ids).size !== ids.length) {
    errors.push('bundle patch has missing/duplicate row ids')
  }
  if (manifest.dsh?.client || manifest.exports?.['./client']) {
    if (manifest.dsh?.client?.platform !== 'web' || !manifest.exports?.['./client']) {
      errors.push('web client needs platform=web and ./client export')
    }
    // The host route serves these on demand; a source-tree-only build can mask omissions.
    for (const path of ['LICENSE', 'dist/index.css', 'dist/index.min.js',
      'dist/css/content-theme/dark.css', 'dist/css/content-theme/light.css',
      'dist/js/lute/lute.min.js', 'dist/js/icons/ant.js', 'dist/js/i18n/zh_CN.js']) {
      if (!available.has(`vendor/vditor/${path}`)) errors.push(`editor asset missing from tarball: ${path}`)
    }
  }
  return errors
}

async function checkProfiles(report) {
  const home = process.env.DSH_HOME ?? join(process.env.HOME ?? '', '.dsh')
  for (const profile of ['web', 'headless']) {
    const dir = join(home, 'profiles', profile)
    await report(`profile ${profile}`, async () => {
      const manifest = await readJson(join(dir, 'package.json'))
      const names = ['@dsh-novel/openwrite-bridge', ...(profile === 'web' ? ['@dsh-novel/studio-panel'] : [])]
      for (const name of names) {
        if (!manifest.dependencies?.[name]) throw new Error(`missing dependency ${name}; run scripts/install.sh`)
        if (manifest.dsh?.profile?.bundles?.filter(n => n === name).length !== 1) {
          throw new Error(`missing/duplicate bundle ${name}; rerun scripts/install.sh`)
        }
        const installed = await realpath(join(dir, 'node_modules', name))
        const source = await realpath(join(root, 'packages', name.split('/')[1]))
        if (installed !== source) throw new Error(`${name} is not linked to this checkout; rerun scripts/install.sh`)
      }
    })
  }
}

export async function doctor({ profiles = false } = {}) {
  let failures = 0
  const report = async (label, check) => {
    try { await check(); console.log(`PASS  ${label}`) }
    catch (error) { failures++; console.error(`FAIL  ${label}: ${error.message}`) }
  }
  const assertClean = errors => { if (errors.length) throw new Error(errors.slice(0, 8).join('; ') + (errors.length > 8 ? `; +${errors.length - 8} more` : '')) }
  const rootManifest = await readJson(join(root, 'package.json'))
  const baseline = rootManifest.devDependencies?.['@deepseek-ai/dsh']
  console.log(`dsh-Openwrite doctor — DSH ${baseline}, Cordis 4.0.1 (offline)`)
  await report('Node >= 22.19.0', () => {
    const [major, minor] = process.versions.node.split('.').map(Number)
    if (major < 22 || (major === 22 && minor < 19)) throw new Error(`found ${process.versions.node}`)
  })
  for (const relative of packageDirs) {
    const dir = resolve(root, relative)
    const manifest = await readJson(join(dir, 'package.json'))
    const lock = await readJson(join(dir, 'package-lock.json'))
    await report(`${relative}: manifest + lock compatibility`, () => assertClean(auditVersions(manifest, lock, baseline)))
    await report(`${relative}: installed SDK matches lock`, async () => {
      const errors = []
      for (const [path, entry] of Object.entries(lock.packages ?? {})) {
        const name = lockName(path)
        if (!name || (!isDsh(name) && name !== '@deepseek-ai/cordis')) continue
        try {
          const installed = await readJson(join(dir, path, 'package.json'))
          if (installed.version !== entry.version) errors.push(`${name}=${installed.version}, lock=${entry.version}`)
        } catch { errors.push(`missing ${name}; run npm ci in ${relative}`) }
      }
      assertClean(errors)
    })
    if (relative === '.') continue
    await report(`${manifest.name}: packed entries + patch + assets`, async () => {
      const packed = JSON.parse(execFileSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'],
        { cwd: dir, encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'] }))
      const patch = load(await readFile(join(dir, manifest.dsh.bundle.patch), 'utf8'))
      assertClean(auditBundle(manifest, packed[0].files.map(file => file.path), patch))
      const host = await import(pathToFileURL(join(dir, manifest.main)).href)
      if (host.name !== manifest.name || typeof host.apply !== 'function') throw new Error('host must export name + apply')
    })
  }
  if (profiles) await checkProfiles(report)
  console.log(failures ? `${failures} check(s) failed.` : 'All checks passed. No model or live-service call was made.')
  return failures ? 1 : 0
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const unknown = process.argv.slice(2).filter(arg => arg !== '--profiles')
  if (unknown.length) { console.error('Usage: node scripts/plugin-doctor.mjs [--profiles]'); process.exitCode = 2 }
  else {
    try { process.exitCode = await doctor({ profiles: process.argv.includes('--profiles') }) }
    catch (error) { console.error(`FAIL  ${error.message}`); process.exitCode = 1 }
  }
}
