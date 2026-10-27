import assert from 'node:assert/strict'
import { test } from 'node:test'
import { copyFile, mkdtemp, mkdir, readFile, writeFile, readdir, rename, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { upgradeProfile, recoverUpgrade, repairProfile } from './safe-upgrade.mjs'

async function fixture() {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-upgrade-'))
  const profile = join(home, 'profiles', 'desktop')
  await mkdir(profile, { recursive: true })
  await writeFile(join(profile, 'package.json'), JSON.stringify({ name: 'test-profile', dependencies: { 'dsh-openwrite': '0.2.24', other: '1' }, dsh: { profile: { bundles: ['other', 'dsh-openwrite'] } } }))
  await writeFile(join(profile, 'cordis.patch.yml'), '# author settings\n')
  await writeFile(join(home, 'settings.yaml'), 'private settings\n')
  return { home, profile, options: { assertStopped: async () => {} } }
}
async function installFake(home, profile, spec, log) {
  assert.equal(spec, 'dsh-openwrite@0.2.25')
  const root = join(home, 'profiles', profile)
  const bundle = join(root, 'node_modules', 'dsh-openwrite')
  for (const file of ['plugin.mjs', 'cordis.patch.yml', 'packages/openwrite-bridge/lib/index.js', 'packages/studio-panel/lib/client.js']) {
    const path = join(bundle, file)
    await mkdir(join(path, '..'), { recursive: true })
    await writeFile(path, 'staged package\n')
  }
  await writeFile(join(bundle, 'package.json'), JSON.stringify({ name: 'dsh-openwrite', version: '0.2.25', dsh: { bundle: { patch: './cordis.patch.yml' } } }))
  const manifest = JSON.parse(await readFile(join(root, 'package.json')))
  manifest.dependencies['dsh-openwrite'] = '0.2.25'
  await writeFile(join(root, 'package.json'), JSON.stringify(manifest))
  await log.write('pnpm fake stdout\npnpm fake stderr\n')
}

test('staged upgrade retains the complete old profile and unrelated settings', async () => {
  const { home, profile, options } = await fixture()
  try {
    const original = await readFile(join(profile, 'package.json'), 'utf8')
    const result = await upgradeProfile(home, 'desktop', 'dsh-openwrite@0.2.25', { ...options, run: async (...args) => {
      assert.equal(await readFile(join(profile, 'package.json'), 'utf8'), original)
      await installFake(...args)
    } })
    assert.equal(result.status, 'completed')
    assert.equal(await readFile(join(result.backup, 'package.json'), 'utf8'), original)
    assert.match(await readFile(result.log, 'utf8'), /fake stderr/)
    const after = JSON.parse(await readFile(join(profile, 'package.json')))
    assert.deepEqual(after.dsh.profile.bundles, ['other', 'dsh-openwrite'])
    assert.equal(after.dependencies.other, '1')
    assert.equal(await readFile(join(home, 'settings.yaml'), 'utf8'), 'private settings\n')
  } finally { await rm(home, { recursive: true, force: true }) }
})

test('failed installation leaves the active profile byte-identical and writes a nonempty log', async () => {
  const { home, profile, options } = await fixture()
  try {
    const original = await readFile(join(profile, 'package.json'), 'utf8')
    await assert.rejects(upgradeProfile(home, 'desktop', 'dsh-openwrite@0.2.25', { ...options, run: async () => { throw new Error('native module failure') } }), /native module failure/)
    assert.equal(await readFile(join(profile, 'package.json'), 'utf8'), original)
    const [id] = await readdir(join(home, 'openwrite', 'upgrades'))
    assert.match(await readFile(join(home, 'openwrite', 'upgrades', id, 'pnpm.log'), 'utf8'), /native module failure/)
  } finally { await rm(home, { recursive: true, force: true }) }
})

test('running-host refusal happens before staging or touching the active profile', async () => {
  const { home, profile } = await fixture()
  try {
    await assert.rejects(upgradeProfile(home, 'desktop', 'dsh-openwrite@0.2.25', { assertStopped: async () => { throw new Error('HOST_RUNNING') } }), /HOST_RUNNING/)
    assert.deepEqual(await readdir(join(home, 'profiles')), ['desktop'])
    assert.match(await readFile(join(profile, 'package.json'), 'utf8'), /0.2.24/)
  } finally { await rm(home, { recursive: true, force: true }) }
})

test('repair disables only the broken OpenWrite bundle and is dry-run by default', async () => {
  const { home, profile, options } = await fixture()
  try {
    assert.equal((await repairProfile(home, 'desktop')).changed, false)
    const result = await repairProfile(home, 'desktop', true, options)
    const manifest = JSON.parse(await readFile(join(profile, 'package.json')))
    assert.deepEqual(manifest.dsh.profile.bundles, ['other'])
    assert.equal(manifest.dependencies['dsh-openwrite'], '0.2.24')
    assert.match(await readFile(result.backup, 'utf8'), /dsh-openwrite/)
  } finally { await rm(home, { recursive: true, force: true }) }
})

test('an interrupted swap restores the previous profile without an installer', async () => {
  const { home, profile, options } = await fixture()
  const id = 'upgrade_aaaaaaaa-bbbb'
  const root = join(home, 'openwrite', 'upgrades', id)
  try {
    await mkdir(root, { recursive: true })
    await writeFile(join(root, 'operation.json'), JSON.stringify({ profile: 'desktop', status: 'swapping' }))
    await rename(profile, join(root, 'previous-profile'))
    const result = await recoverUpgrade(home, id, options)
    assert.equal(result.status, 'rolled_back')
    assert.match(await readFile(join(profile, 'package.json'), 'utf8'), /0.2.24/)
  } finally { await rm(home, { recursive: true, force: true }) }
})

test('an unpacked upgrade script resolves dependencies from the selected installed profile', async () => {
  const { home, profile, options } = await fixture()
  try {
    const require = createRequire(import.meta.url)
    await mkdir(join(profile, 'node_modules'))
    for (const name of ['proper-lockfile', 'js-yaml']) {
      await symlink(dirname(require.resolve(name + '/package.json')),
        join(profile, 'node_modules', name), 'junction')
    }
    const unpacked = join(home, 'download', 'package', 'scripts', 'safe-upgrade.mjs')
    await mkdir(dirname(unpacked), { recursive: true })
    await copyFile(new URL('./safe-upgrade.mjs', import.meta.url), unpacked)
    const standalone = await import(pathToFileURL(unpacked).href)
    const result = await standalone.upgradeProfile(home, 'desktop', 'dsh-openwrite@0.2.25',
      { ...options, run: installFake })
    assert.equal(result.status, 'completed')
    assert.equal(JSON.parse(await readFile(join(profile, 'package.json'))).dependencies.other, '1')
  } finally { await rm(home, { recursive: true, force: true }) }
})

test('a local release archive is pinned outside disposable download directories before install', async () => {
  const { home, profile, options } = await fixture()
  const download = await mkdtemp(join(tmpdir(), 'openwrite-disposable-download-'))
  const file = join(download, 'dsh-openwrite-0.2.25.tgz')
  await writeFile(file, 'controlled tarball fixture')
  try {
    let cached
    const result = await upgradeProfile(home, 'desktop', file, { ...options, run: async (h, p, spec, log) => {
      cached = spec
      assert.ok(spec.startsWith(join(home, 'openwrite', 'packages')))
      assert.equal(await readFile(spec, 'utf8'), 'controlled tarball fixture')
      await rm(download, { recursive: true, force: true })
      await installFake(h, p, 'dsh-openwrite@0.2.25', log)
      const path = join(h, 'profiles', p, 'package.json')
      const manifest = JSON.parse(await readFile(path))
      manifest.dependencies['dsh-openwrite'] = 'file:' + spec
      await writeFile(path, JSON.stringify(manifest))
    } })
    assert.equal(result.status, 'completed')
    assert.equal(await readFile(cached, 'utf8'), 'controlled tarball fixture')
    assert.equal(JSON.parse(await readFile(join(profile, 'package.json'))).dependencies['dsh-openwrite'], 'file:' + cached)
  } finally {
    await rm(home, { recursive: true, force: true })
    await rm(download, { recursive: true, force: true })
  }
})
