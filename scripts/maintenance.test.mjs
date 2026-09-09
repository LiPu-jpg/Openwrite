import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { migrate, diagnose, inspectProfile, restoreBackup, defaultRunPlugin } from './maintenance.mjs'

const root = fileURLToPath(new URL('..', import.meta.url))
const cli = join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js')

const LEGACY = ['@dsh-novel/openwrite-bridge', '@dsh-novel/studio-panel', '@dsh-external/dsh-dog']

async function homeFixture(t) {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-migration-'))
  t.after(() => rm(home, { recursive: true, force: true }))
  await mkdir(join(home, 'profiles/web'), { recursive: true })
  await mkdir(join(home, '.agent-presets/custom'), { recursive: true })
  await mkdir(join(home, '.agent-presets/openwrite'), { recursive: true })
  await mkdir(join(home, 'sessions'), { recursive: true })
  await mkdir(join(home, 'openwrite'), { recursive: true })
  await mkdir(join(home, 'profiles/web/node_modules/@dsh-novel/openwrite-bridge'), { recursive: true })
  await writeFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'author-owned')
  await writeFile(join(home, '.agent-presets/openwrite/author-note.txt'), 'user-modified old default')
  await writeFile(join(home, 'credentials.json'), '{"token":"must-not-print-or-delete"}', { mode: 0o600 })
  await writeFile(join(home, 'sessions/sess_history.json'), '{"id":"sess_history"}')
  await writeFile(join(home, 'openwrite/works-marker.txt'), 'isolated-work-marker')
  await writeFile(join(home, 'settings.yaml'), 'theme: author\n')
  const sentinel = '/* sentinel: do not patch user node_modules */\nexport const name = "@dsh-novel/openwrite-bridge"\n'
  await writeFile(join(home, 'profiles/web/node_modules/@dsh-novel/openwrite-bridge/index.js'), sentinel)
  return { home, sentinel }
}

function manifestWith(extra = {}) {
  return {
    dependencies: {
      other: '1',
      '@dsh-novel/openwrite-bridge': 'file:/old/source',
      '@dsh-novel/studio-panel': 'file:/old/panel',
      '@dsh-external/dsh-dog': 'file:/old/dog',
      ...extra.dependencies,
    },
    dsh: { profile: { bundles: extra.bundles ?? ['other', ...LEGACY, 'dsh-openwrite'] } },
  }
}

async function fakeRemove(home, profile, args) {
  assert.equal(args[0], 'plugin')
  assert.deepEqual(args.slice(1, 3), ['--profile', profile])
  assert.equal(args[3], 'remove')
  assert.equal(args[4], '-w')
  const name = args[5]
  const file = join(home, 'profiles', profile, 'package.json')
  const manifest = JSON.parse(await readFile(file, 'utf8'))
  delete manifest.dependencies[name]
  manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter(item => item !== name)
  await writeFile(file, JSON.stringify(manifest, null, 2) + '\n')
}

test('inspect reports leftover dependencies even when they are absent from bundles', async t => {
  const { home } = await homeFixture(t)
  const original = JSON.stringify(manifestWith({ bundles: ['other', 'dsh-openwrite'] }))
  await writeFile(join(home, 'profiles/web/package.json'), original)
  const inspection = inspectProfile(JSON.parse(original))
  assert.deepEqual(inspection.leftoverDeps, LEGACY)
  assert.deepEqual(inspection.leftoverBundles, [])
  assert.deepEqual(inspection.leftover, LEGACY)
  assert.equal(inspection.installed, true)
  assert.deepEqual(inspection.otherPlugins, ['other'])
  const report = await diagnose(home, 'web')
  assert.deepEqual(report.leftoverDeps, LEGACY)
  assert.equal(report.legacyBundles.length, 0)
  assert.match(report.instructions, /migrate/)
  const dry = await migrate(home, 'web')
  assert.equal(dry.changed, false)
  assert.deepEqual(dry.leftoverDeps, LEGACY)
  assert.equal(await readFile(join(home, 'profiles/web/package.json'), 'utf8'), original)
})

test('apply uses the host plugin remove path, backs up, and preserves author data', async t => {
  const { home, sentinel } = await homeFixture(t)
  const file = join(home, 'profiles/web/package.json')
  const original = JSON.stringify(manifestWith())
  await writeFile(file, original)
  const calls = []
  const result = await migrate(home, 'web', true, {
    runPlugin: async (dshHome, profile, args) => {
      calls.push(args)
      return fakeRemove(dshHome, profile, args)
    },
  })
  assert.equal(result.changed, true)
  assert.ok(result.backup)
  assert.equal(await readFile(join(result.backup, 'package.json'), 'utf8'), original)
  assert.equal(await readFile(join(result.backup, '.agent-presets/custom/agent.cordis.yml'), 'utf8'), 'author-owned')
  const next = JSON.parse(await readFile(file))
  assert.deepEqual(next.dsh.profile.bundles, ['other', 'dsh-openwrite'])
  assert.deepEqual(next.dependencies, { other: '1' })
  assert.deepEqual(calls.map(args => args.at(-1)), LEGACY)
  assert.equal(await readFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'utf8'), 'author-owned')
  assert.equal(await readFile(join(home, '.agent-presets/openwrite/author-note.txt'), 'utf8'), 'user-modified old default')
  assert.equal(await readFile(join(home, 'credentials.json'), 'utf8'), '{"token":"must-not-print-or-delete"}')
  assert.equal(await readFile(join(home, 'sessions/sess_history.json'), 'utf8'), '{"id":"sess_history"}')
  assert.equal(await readFile(join(home, 'openwrite/works-marker.txt'), 'utf8'), 'isolated-work-marker')
  assert.equal(await readFile(join(home, 'profiles/web/node_modules/@dsh-novel/openwrite-bridge/index.js'), 'utf8'), sentinel)
  const presets = result.presets.find(item => item.name === 'openwrite')
  assert.equal(presets.origin, 'author-owned')
  assert.equal(presets.preserved, true)
  assert.equal((await migrate(home, 'web', true, { runPlugin: fakeRemove })).changed, false)
  assert.equal((await diagnose(home, 'web')).installed, true)
  await assert.rejects(migrate(home, '../escape', true), /Invalid profile/)
})

test('failed host remove restores the backed-up profile and leaves other plugins', async t => {
  const { home, sentinel } = await homeFixture(t)
  const file = join(home, 'profiles/web/package.json')
  const original = JSON.stringify(manifestWith(), null, 2) + '\n'
  await writeFile(file, original)
  let removed = 0
  await assert.rejects(migrate(home, 'web', true, {
    runPlugin: async (dshHome, profile, args) => {
      if (removed++ === 0) return fakeRemove(dshHome, profile, args)
      throw new Error('simulated pnpm failure')
    },
  }), /simulated pnpm failure; restored profile from /)
  assert.equal(await readFile(file, 'utf8'), original)
  assert.equal(await readFile(join(home, 'profiles/web/node_modules/@dsh-novel/openwrite-bridge/index.js'), 'utf8'), sentinel)
  assert.equal(await readFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'utf8'), 'author-owned')
})

test('restoreBackup rewrites only the profile package files', async t => {
  const { home } = await homeFixture(t)
  const file = join(home, 'profiles/web/package.json')
  await writeFile(file, JSON.stringify(manifestWith()))
  const result = await migrate(home, 'web', true, { runPlugin: fakeRemove })
  await writeFile(file, '{"broken":true}\n')
  await restoreBackup(result.backup, home, 'web')
  assert.deepEqual(inspectProfile(JSON.parse(await readFile(file))).leftover, LEGACY)
})

async function dummyBundle(rootDir, name, id) {
  const dir = join(rootDir, name.replaceAll('/', '__'))
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, 'package.json'), JSON.stringify({
    name, version: '0.0.0-legacy', type: 'module', main: 'index.mjs',
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }))
  await writeFile(join(dir, 'cordis.patch.yml'), `- insert:\n    - id: ${id}\n      name: ${JSON.stringify(name)}\n`)
  await writeFile(join(dir, 'index.mjs'), `export const name = ${JSON.stringify(name)}; export function apply() {}\n`)
  return dir
}

test('real dsh plugin remove/add does not revive leftover deps as duplicate openwrite-bridge', async t => {
  const temporary = await mkdtemp(join(tmpdir(), 'openwrite-host-migrate-'))
  t.after(() => rm(temporary, { recursive: true, force: true }))
  const home = join(temporary, 'dsh')
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/(?:API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(key)
    && !key.startsWith('DSH_') && !/^npm_config_/i.test(key)
    && !['NODE_OPTIONS', 'NODE_PATH'].includes(key)))
  Object.assign(env, {
    DSH_HOME: home,
    XDG_CONFIG_HOME: join(temporary, 'config'),
    XDG_CACHE_HOME: join(temporary, 'cache'),
    XDG_DATA_HOME: join(temporary, 'data'),
    npm_config_userconfig: join(temporary, 'npmrc'),
    npm_config_cache: join(temporary, 'npm-cache'),
    npm_config_store_dir: join(temporary, 'pnpm-store'),
    npm_config_update_notifier: 'false',
    CI: '1',
    DSH_BIN: cli,
  })
  const previousBin = process.env.DSH_BIN
  process.env.DSH_BIN = cli
  t.after(() => {
    if (previousBin === undefined) delete process.env.DSH_BIN
    else process.env.DSH_BIN = previousBin
  })
  await mkdir(home, { recursive: true })
  await writeFile(env.npm_config_userconfig, '')
  const run = args => {
    const result = spawnSync(process.execPath, [cli, ...args], {
      cwd: temporary, env, encoding: 'utf8', timeout: 120_000, maxBuffer: 8 * 1024 ** 2,
    })
    return result
  }
  const must = (label, result) => {
    if (result.status !== 0 || result.error) {
      throw new Error(`${label}: ${(result.stderr || result.stdout || result.error?.message || '').slice(0, 2000)}`)
    }
    return result.stdout
  }
  must('init', run(['--profile', 'web', '--dump-config']))
  const other = await dummyBundle(temporary, 'dsh-openwrite-coexist-fixture', 'coexist-fixture')
  const legacyDirs = {
    '@dsh-novel/openwrite-bridge': await dummyBundle(temporary, '@dsh-novel/openwrite-bridge', 'openwrite-bridge'),
    '@dsh-novel/studio-panel': await dummyBundle(temporary, '@dsh-novel/studio-panel', 'studio-panel'),
    '@dsh-external/dsh-dog': await dummyBundle(temporary, '@dsh-external/dsh-dog', 'dsh-dog'),
  }
  const next = await dummyBundle(temporary, 'dsh-openwrite', 'openwrite-bridge')
  must('other', run(['plugin', '--profile', 'web', 'add', '-w', '--offline', other]))
  for (const dir of Object.values(legacyDirs)) {
    must('legacy add', run(['plugin', '--profile', 'web', 'add', '-w', '--offline', dir]))
  }
  await mkdir(join(home, '.agent-presets/custom'), { recursive: true })
  await writeFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'author-owned')
  await writeFile(join(home, 'credentials.json'), '{"token":"keep"}', { mode: 0o600 })
  const profileFile = join(home, 'profiles/web/package.json')
  const before = JSON.parse(await readFile(profileFile, 'utf8'))
  assert.deepEqual(inspectProfile(before).leftover.sort(), LEGACY.slice().sort())
  // 0.2.1-style bundle-only strip still leaves deps; a later add re-registers them.
  before.dsh.profile.bundles = before.dsh.profile.bundles.filter(name => !LEGACY.includes(name))
  await writeFile(profileFile, JSON.stringify(before, null, 2) + '\n')
  must('stale add without migrate', run(['plugin', '--profile', 'web', 'add', '-w', '--offline', next]))
  const revived = JSON.parse(await readFile(profileFile, 'utf8'))
  assert.ok(revived.dsh.profile.bundles.includes('@dsh-novel/openwrite-bridge'), '0.2.1 leftover deps are re-registered')
  assert.ok(revived.dsh.profile.bundles.includes('dsh-openwrite'))
  must('remove colliding new package before real migrate', run(['plugin', '--profile', 'web', 'remove', '-w', 'dsh-openwrite']))
  const migrated = await migrate(home, 'web', true, {
    runPlugin: (dshHome, profile, args) => defaultRunPlugin(dshHome, profile, args),
  })
  assert.equal(migrated.changed, true)
  const cleaned = JSON.parse(await readFile(profileFile, 'utf8'))
  assert.deepEqual(inspectProfile(cleaned).leftover, [])
  assert.ok(cleaned.dsh.profile.bundles.includes('dsh-openwrite-coexist-fixture'))
  must('new add after migrate', run(['plugin', '--profile', 'web', 'add', '-w', '--offline', next]))
  const dump = must('dump after migrate', run(['--profile', 'web', '--dump-config']))
  assert.doesNotMatch(dump, /duplicate loader entry id: openwrite-bridge/)
  const installed = JSON.parse(await readFile(profileFile, 'utf8'))
  assert.equal(installed.dsh.profile.bundles.includes('@dsh-novel/openwrite-bridge'), false)
  assert.equal(installed.dependencies?.['@dsh-novel/openwrite-bridge'], undefined)
  must('second add', run(['plugin', '--profile', 'web', 'add', '-w', '--offline', next]))
  const twice = must('dump twice', run(['--profile', 'web', '--dump-config']))
  assert.doesNotMatch(twice, /duplicate loader entry id: openwrite-bridge/)
  assert.equal(inspectProfile(JSON.parse(await readFile(profileFile, 'utf8'))).leftover.length, 0)
  assert.equal(await readFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'utf8'), 'author-owned')
  assert.equal(await readFile(join(home, 'credentials.json'), 'utf8'), '{"token":"keep"}')
}, { timeout: 180_000 })
