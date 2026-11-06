import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, writeFile, rm, utimes, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { detectCompanions, resolveHostVersion, satisfiesRange } from '../companions.mjs'

const semver = createRequire(import.meta.url)('semver')

/** Build one profile with the given bundle list and installed packages. */
async function writeProfile(home, name, { bundles = [], packages = {} } = {}) {
  const directory = join(home, 'profiles', name)
  await mkdir(join(directory, 'node_modules'), { recursive: true })
  await writeFile(join(directory, 'package.json'), JSON.stringify({ name: `openwrite-${name}`, private: true, dsh: { profile: { bundles } } }) + '\n')
  for (const [package_, manifest] of Object.entries(packages)) {
    const target = join(directory, 'node_modules', ...package_.split('/'))
    await mkdir(target, { recursive: true })
    await writeFile(join(target, 'package.json'), JSON.stringify({ name: package_, private: true, ...manifest }) + '\n')
  }
  return join(directory, 'package.json')
}


/** Write a dsh-ops package that really exposes `dsh-ops/integration`. */
async function writeOpsPackage(home, version, range, profile = 'web') {
  const directory = join(home, 'profiles', profile, 'node_modules', 'dsh-ops')
  await mkdir(join(directory, 'lib', 'integration'), { recursive: true })
  await writeFile(join(directory, 'package.json'), JSON.stringify({
    name: 'dsh-ops', version, exports: { '.': './lib/index.js', './integration': './lib/integration/index.js' },
    peerDependencies: range === undefined ? {} : { '@deepseek-ai/dsh': range },
  }) + '\n')
  await writeFile(join(directory, 'lib', 'integration', 'index.js'), 'export const integration = () => ({ name: "dsh-ops-integration", apply: () => {} })\n')
  return directory
}

test('companion host ranges follow the host\'s own semver semantics', () => {
  // The dsh host decides with semver.satisfies(version, range,
  // { includePrerelease: true }) - see dsh-app-boot unmetRequirements/satisfies.
  // That flag relaxes npm's rule that a prerelease only matches a comparator
  // carrying the same major/minor/patch, so 0.2.1-rc.5 DOES satisfy
  // >=0.2.0-rc.2 <0.2.2-0. Detection must agree with the host, not with npm's
  // install-time resolution, or a companion the host loads is reported unusable.
  const ranges = [
    '>=0.2.1-0 <0.3.0-0',
    '>=0.2.0-rc.2 <0.2.2-0',
    '^0.1.2-rc.1 || ^0.1.7-rc.2 || ^0.2.0-rc.1',
    '0.1.2-rc.1 || 0.2.1-rc.5',
    '^0.2.0-rc.1',
    '~0.2.1',
    'not-a-range',
  ]
  const hosts = ['0.1.2-rc.1', '0.2.0-rc.2', '0.2.1-rc.3', '0.2.1-rc.5', '0.2.2-alpha.3', 'nonsense']
  for (const range of ranges) {
    for (const host of hosts) {
      const hostSays = semver.satisfies(host, range, { includePrerelease: true })
      assert.equal(satisfiesRange(host, range), hostSays,
        `detection disagrees with the host for ${host} against ${range}`)
    }
  }
  // Concrete expectations, pinned so a future change cannot drift silently.
  assert.equal(satisfiesRange('0.2.1-rc.5', '>=0.2.1-0 <0.3.0-0'), true)
  assert.equal(satisfiesRange('0.2.0-rc.2', '>=0.2.1-0 <0.3.0-0'), false)
  // The case that used to be reported incompatible while the host loaded it.
  assert.equal(satisfiesRange('0.2.1-rc.5', '>=0.2.0-rc.2 <0.2.2-0'), true)
  assert.equal(satisfiesRange('0.2.1-rc.5', '^0.1.2-rc.1 || ^0.1.7-rc.2 || ^0.2.0-rc.1'), true)
  // Anything unparseable is refused rather than guessed.
  assert.equal(satisfiesRange('0.2.1-rc.5', 'not-a-range'), false)
  assert.equal(satisfiesRange('0.2.1-rc.5', undefined), false)
  assert.equal(satisfiesRange('nonsense', '^1.0.0'), false)
})

test('a companion the host itself would reject stays unusable', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-reject-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
  })
  // A range that names one host exactly, so the boundary is unambiguous.
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.1-rc.4 <0.2.1-rc.5')
  const onCovered = await detectCompanions(home, { hostVersion: '0.2.1-rc.4' })
  assert.equal(onCovered.ops.installed, true)
  assert.equal(onCovered.ops.usable, true, 'the host its range names must be accepted')
  const outside = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(outside.ops.usable, false, 'a host outside the range must be refused')
  assert.match(outside.ops.reason, /excludes dsh 0\.2\.1-rc\.5/)

  // dsh-ops really declares >=0.2.0-rc.2 <0.2.2-0. Under the host's semantics that
  // covers every 0.2.x host, including the ones npm's install-time resolution
  // refuses. This is the case detection used to misreport as incompatible while
  // the host loaded the plugin (verified against a real 0.2.1-rc.5 host).
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0')
  for (const host of ['0.2.0-rc.2', '0.2.1-rc.3', '0.2.1-rc.5']) {
    const seen = await detectCompanions(home, { hostVersion: host })
    assert.equal(seen.ops.usable, true, `dsh-ops must be usable on ${host}`)
    assert.equal(seen.ops.reason, null)
  }
})

test('a companion without a host constraint is accepted as installed', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-unconstrained-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@ebony-vinyl/dsh-our-free-model'],
    packages: { '@ebony-vinyl/dsh-our-free-model': { version: '2.7.4' } },
  })
  const companions = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(companions.freeModel.installed, true)
  assert.equal(companions.freeModel.usable, true)
  assert.equal(companions.freeModel.version, '2.7.4')
})

test('companions are found in any profile of the home', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-multi-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', { bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite'] })
  await writeProfile(home, 'desktop', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
  })
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0', 'desktop')
  const companions = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(companions.ops.usable, true)
  assert.equal(companions.ops.profile, 'desktop')
})

test('the companion cache is reused until the profile manifests change', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-cache-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  const manifest = await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
  })
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0')
  assert.equal((await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })).cached, false)
  const cache = JSON.parse(await readFile(join(home, 'openwrite', 'companions.json'), 'utf8'))
  assert.equal(cache.ops.usable, true)
  assert.equal((await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })).cached, true)
  // A different host is a different answer even when the manifests are untouched.
  const covered = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(covered.cached, false)
  assert.equal(covered.ops.usable, true)
  // Removing the bundle invalidates the fingerprint.
  await writeFile(manifest, JSON.stringify({ name: 'openwrite-web', private: true, dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite'] } } }) + '\n')
  const refreshed = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(refreshed.cached, false)
  assert.equal(refreshed.ops.installed, false)
})

test('the host version is read from the installed host package', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-host-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base'],
    packages: { '@deepseek-ai/dsh': { version: '0.2.1-rc.5' } },
  })
  assert.equal(await resolveHostVersion(home), '0.2.1-rc.5')
  const companions = await detectCompanions(home)
  assert.equal(companions.host, '0.2.1-rc.5')
})

test('an unknown host version fails closed', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-unknown-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
  })
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0')
  const companions = await detectCompanions(home, { hostVersion: null })
  assert.equal(companions.ops.installed, true)
  assert.equal(companions.ops.usable, false)
  assert.match(companions.ops.reason, /unknown/)
})

test('a home without profiles is reported, not thrown', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-empty-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  const companions = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(companions.ops.installed, false)
})

test('a companion that does not expose its entry is treated as absent', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-entry-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  // An older dsh-ops release without the `dsh-ops/integration` export.
  const directory = join(home, 'profiles', 'web')
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.4.4', peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' } } },
  })
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'package.json'),
    JSON.stringify({ name: 'dsh-ops', version: '0.4.4', exports: { '.': './lib/index.js' }, peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' } }) + '\n')
  const companions = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(companions.ops.installed, true)
  assert.equal(companions.ops.usable, false)
  assert.match(companions.ops.reason, /does not expose dsh-ops\/integration/)
})

test('a companion that exposes its entry is usable', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-entry-ok-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  const directory = join(home, 'profiles', 'web')
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3', peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' } } },
  })
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'package.json'),
    JSON.stringify({ name: 'dsh-ops', version: '0.5.0-alpha3', exports: { '.': './lib/index.js', './integration': './lib/integration/index.js' }, peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' } }) + '\n')
  await mkdir(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration'), { recursive: true })
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration', 'index.js'), 'export const integration = () => ({ name: "dsh-ops-integration", apply: () => {} })\n')
  const companions = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(companions.ops.usable, true)
  assert.equal(companions.ops.reason, null)
})

test('a companion whose entry rejects the OpenWrite options is reported', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-options-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  const directory = join(home, 'profiles', 'web')
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '9.9.9' } },
  })
  await mkdir(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration'), { recursive: true })
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'package.json'),
    JSON.stringify({ name: 'dsh-ops', version: '9.9.9', exports: { './integration': './lib/integration/index.js' } }) + '\n')
  // A future release that renamed an option must be caught here, not at load time.
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration', 'index.js'),
    'export function integration(options) { if (options.discovery) throw new Error("discovery was removed"); return { name: "x", apply: () => {} } }\n')
  const companions = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(companions.ops.installed, true)
  assert.equal(companions.ops.usable, false)
  assert.match(companions.ops.reason, /rejected the OpenWrite integration: discovery was removed/)
})

test('an integration factory that returns nothing is refused, not mounted', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-retval-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  const directory = join(home, 'profiles', 'web')
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '9.9.9' } },
  })
  await mkdir(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration'), { recursive: true })
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'package.json'),
    JSON.stringify({ name: 'dsh-ops', version: '9.9.9', exports: { './integration': './lib/integration/index.js' } }) + '\n')
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration', 'index.js'),
    'export function integration() { return }\n')
  const companions = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(companions.ops.installed, true)
  assert.equal(companions.ops.usable, false)
  assert.match(companions.ops.reason, /returned no plugin object/)
})

test('a usable copy in any profile wins over an unusable one', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-multi-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  // One profile carries a copy without the entry, the other a good one.
  for (const name of ['aaa-web', 'zzz-web']) {
    await writeProfile(home, name, {
      bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
      packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
    })
    await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0', name)
  }
  const directory = join(home, 'profiles', 'zzz-web', 'node_modules', 'dsh-ops')
  await writeFile(join(directory, 'package.json'),
    JSON.stringify({ name: 'dsh-ops', version: '0.4.4', exports: { '.': './lib/index.js' }, peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' } }) + '\n')
  const companions = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(companions.ops.usable, true, 'the usable copy must win regardless of readdir order')
  assert.equal(companions.ops.profile, 'aaa-web')
})

test('a cache hit serves the stored answer instead of recomputing', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-cache-hit-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
  })
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0')
  const first = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(first.cached, false)
  assert.equal(first.ops.usable, true)
  // Removing the package MUST invalidate the answer: the companion's own
  // manifest is part of the fingerprint, so a stale "usable: true" cannot be
  // served for a package that is no longer installed.
  await rm(join(home, 'profiles', 'web', 'node_modules', 'dsh-ops'), { recursive: true, force: true })
  const second = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(second.cached, false, 'removing the companion must invalidate the cache')
  assert.equal(second.ops.usable, false, 'a removed companion is not usable')
  // A pure repeat still hits the cache.
  const third = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(third.cached, true, 'an unchanged fingerprint is served from cache')
  assert.equal(third.ops.usable, false)
})

// A scoped package whose own cordis.patch.yml names the bare package can never
// activate: the host imports `dsh-our-free-model` and finds nothing. Reporting it
// usable made the panel offer an integration that never loaded.
test('a bundle patch that names a package other than its own is not usable', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-scoped-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  const scoped = '@ebony-vinyl/dsh-our-free-model'
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', scoped],
    packages: { [scoped]: { version: '2.8.0' } },
  })
  const directory = join(home, 'profiles', 'web', 'node_modules', ...scoped.split('/'))
  await writeFile(join(directory, 'package.json'), JSON.stringify({
    name: scoped, version: '2.8.0', exports: { '.': './index.js' },
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }) + '\n')
  await writeFile(join(directory, 'index.js'), 'export function apply() {}\n')
  // The published 2.8.0 patch: the bare package name, which does not exist here.
  await writeFile(join(directory, 'cordis.patch.yml'),
    "- insert:\n    - id: our-free-model\n      name: 'dsh-our-free-model'\n      config: {}\n")

  const companions = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(companions.freeModel.installed, true)
  assert.equal(companions.freeModel.usable, false, 'a patch naming another package cannot activate')
  assert.match(companions.freeModel.reason, /bundle patch names dsh-our-free-model/)
  assert.match(companions.freeModel.reason, /host cannot load it/)
})

// The same package installed under its own name must stay usable: the fix must
// not reject a self-consistent patch.
test('a bundle patch naming its own package stays usable', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-bare-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-our-free-model'],
    packages: { 'dsh-our-free-model': { version: '2.1.0' } },
  })
  const directory = join(home, 'profiles', 'web', 'node_modules', 'dsh-our-free-model')
  await writeFile(join(directory, 'package.json'), JSON.stringify({
    name: 'dsh-our-free-model', version: '2.1.0', exports: { '.': './index.js' },
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }) + '\n')
  await writeFile(join(directory, 'index.js'), 'export function apply() {}\n')
  await writeFile(join(directory, 'cordis.patch.yml'),
    "- insert:\n    - id: our-free-model\n      name: 'dsh-our-free-model'\n      config: {}\n")

  const companions = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(companions.freeModel.usable, true, 'a self-consistent patch must stay usable')
  assert.equal(companions.freeModel.reason, null)
})

// dsh-dog declares no `@deepseek-ai/dsh` peer at all: it constrains the host
// through `@deepseek-ai/dsh-*` sub-packages instead. Reading only the direct peer
// would report it usable on every host, including ones where the host itself
// refuses it - the same false positive fixed for the scoped free-model package.
test('a companion constrained only by dsh-* sub-package peers is range-checked', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-dog-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', '@dsh-external/dsh-dog'],
    packages: { '@dsh-external/dsh-dog': { version: '1.4.0-alpha.1' } },
  })
  const directory = join(home, 'profiles', 'web', 'node_modules', '@dsh-external', 'dsh-dog')
  await writeFile(join(directory, 'package.json'), JSON.stringify({
    name: '@dsh-external/dsh-dog', version: '1.4.0-alpha.1',
    exports: { '.': './index.js' },
    // No `@deepseek-ai/dsh` peer: the sub-package ranges are the constraint.
    peerDependencies: {
      '@deepseek-ai/cordis': '>=4.0.5-0 <4.1.0-0',
      '@deepseek-ai/dsh-agent': '>=0.2.1-0 <0.3.0-0',
      '@deepseek-ai/dsh-session': '>=0.2.1-0 <0.3.0-0',
    },
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }) + '\n')
  await writeFile(join(directory, 'index.js'), 'export function apply() {}\n')
  await writeFile(join(directory, 'cordis.patch.yml'),
    "- insert:\n    - id: dsh-dog\n      name: '@dsh-external/dsh-dog'\n      config: {}\n")

  // A host the sub-package ranges cover.
  const ok = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(ok.dog.installed, true)
  assert.equal(ok.dog.usable, true, 'a host inside the sub-package ranges must be accepted')
  assert.equal(ok.dog.version, '1.4.0-alpha.1')

  // A host they exclude.
  const bad = await detectCompanions(home, { hostVersion: '0.2.0-rc.2' })
  assert.equal(bad.dog.installed, true)
  assert.equal(bad.dog.usable, false, 'a host outside the sub-package ranges must be refused')
  assert.match(bad.dog.reason, /0\.2\.0-rc\.2/)
})

// An unknown host version must not silently accept a companion.
test('an unknown host version keeps every companion fail-closed', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-nohost-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', '@dsh-external/dsh-dog'],
    packages: { '@dsh-external/dsh-dog': { version: '1.4.0-alpha.1' } },
  })
  const directory = join(home, 'profiles', 'web', 'node_modules', '@dsh-external', 'dsh-dog')
  await writeFile(join(directory, 'package.json'), JSON.stringify({
    name: '@dsh-external/dsh-dog', version: '1.4.0-alpha.1',
    exports: { '.': './index.js' },
    peerDependencies: { '@deepseek-ai/dsh-agent': '>=0.2.1-0 <0.3.0-0' },
  }) + '\n')

  const companions = await detectCompanions(home, { hostVersion: null })
  assert.equal(companions.dog.installed, true)
  assert.equal(companions.dog.usable, false, 'an unknown host must not authorize a companion')
  assert.match(companions.dog.reason, /unknown/)
})

// The cache used to be keyed on the profile manifests and the host only. An
// upgrade that changes the detection logic (a new companion, corrected range
// semantics) therefore kept serving the previous answer: a real 0.2.1-rc.5 host
// reported the old "ops excludes dsh 0.2.1-rc.5" verdict with no DoG row at all
// until the manifests happened to change.
test("the cache is invalidated by a change in this plugin own version", async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-build-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3' } },
  })
  await writeOpsPackage(home, '0.5.0-alpha3', '>=0.2.0-rc.2 <0.2.2-0')

  const first = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(first.cached, false)
  const cache = JSON.parse(await readFile(join(home, 'openwrite', 'companions.json'), 'utf8'))
  assert.equal(typeof cache.build, 'string', 'the cache must record the plugin build')

  // A repeat with an untouched manifest hits the cache.
  const second = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(second.cached, true)

  // Simulate an upgrade by rewriting only the build stamp, leaving every
  // manifest untouched: the answer must be recomputed, not served stale.
  cache.build = '9.9.9'
  await writeFile(join(home, 'openwrite', 'companions.json'), JSON.stringify(cache) + '\n')
  const third = await detectCompanions(home, { hostVersion: '0.2.1-rc.5' })
  assert.equal(third.cached, false, 'a plugin upgrade must invalidate the cache')
})

// The running host is normally started through the `dsh` shim in the npm global
// bin directory, which is a symlink into lib/node_modules/@deepseek-ai/dsh.
// `path.resolve` does not follow symlinks, so walking up from the shim never
// reached the package and the version silently fell through to this checkout's
// own devDependency - a real 0.2.1-rc.5 host was reported as 0.1.2-rc.1.
test('the host version is resolved through the dsh shim symlink', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-shim-'))
  t.after(async () => await rm(home, { recursive: true, force: true }))
  await mkdir(join(home, 'profiles'), { recursive: true })

  // Lay out a fake global install: bin/dsh -> lib/node_modules/@deepseek-ai/dsh.
  const prefix = join(home, 'global')
  const package_dir = join(prefix, 'lib', 'node_modules', '@deepseek-ai', 'dsh')
  await mkdir(join(package_dir, 'lib'), { recursive: true })
  await mkdir(join(prefix, 'bin'), { recursive: true })
  await writeFile(join(package_dir, 'package.json'), JSON.stringify({ name: '@deepseek-ai/dsh', version: '0.2.1-rc.5' }) + '\n')
  await writeFile(join(package_dir, 'lib', 'bin.js'), '//x\n')
  await symlink(join(package_dir, 'lib', 'bin.js'), join(prefix, 'bin', 'dsh'))

  const previous = process.argv[1]
  process.argv[1] = join(prefix, 'bin', 'dsh')
  try {
    assert.equal(await resolveHostVersion(home), '0.2.1-rc.5',
      'the version must be resolved through the shim, not fall through to this checkout')
  } finally {
    process.argv[1] = previous
  }
})

test('the dsh-ops plan is the bounded file + discovery row, with no shell', async () => {
  const { OPENWRITE_OPS_OPTIONS, summarizeOpsPlan } = await import('../companions.mjs')
  assert.deepEqual(OPENWRITE_OPS_OPTIONS, {
    preset: 'openwrite',
    files: true,
    discovery: true,
    presentation: 'native',
    replaceOfficial: false,
    shell: false,
  })
  assert.deepEqual(summarizeOpsPlan({
    files: true,
    discovery: true,
    presentation: 'native',
    shell: false,
    replaceOfficial: false,
    residentTools: true,
    residentNames: ['read_file', 'list_dir'],
  }), {
    files: true,
    discovery: true,
    presentation: 'native',
    shell: false,
    replaceOfficial: false,
    residentTools: true,
    residentNames: 2,
  })
})

test('the host companion summary resolves the dsh-ops plan it will mount', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-companions-summary-'))
  const previous = process.env.OPENWRITE_HOST_VERSION
  process.env.OPENWRITE_HOST_VERSION = '0.2.1-rc.5'
  t.after(async () => {
    if (previous === undefined) delete process.env.OPENWRITE_HOST_VERSION
    else process.env.OPENWRITE_HOST_VERSION = previous
    await rm(home, { recursive: true, force: true })
  })
  await writeProfile(home, 'web', {
    bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'],
    packages: { 'dsh-ops': { version: '0.5.0-alpha3', peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' } } },
  })
  const directory = join(home, 'profiles', 'web', 'node_modules', 'dsh-ops')
  await mkdir(join(directory, 'lib', 'integration'), { recursive: true })
  await writeFile(join(directory, 'package.json'), JSON.stringify({
    name: 'dsh-ops', version: '0.5.0-alpha3',
    exports: { '.': './lib/index.js', './integration': './lib/integration/index.js' },
    peerDependencies: { '@deepseek-ai/dsh': '>=0.2.0-rc.2 <0.2.2-0' },
  }) + '\n')
  await writeFile(join(directory, 'lib', 'integration', 'index.js'), [
    'export const integration = () => ({ name: "dsh-ops-integration", apply: () => {} })',
    'export const resolveIntegrationConfig = options => ({ ...options, enabled: true, residentTools: true, residentNames: ["read_file", "list_dir"] })',
    '',
  ].join('\n'))
  const { companionSummary } = await import('../plugin.mjs')
  const summary = await companionSummary(home)
  assert.equal(summary.ops.installed, true)
  assert.equal(summary.ops.usable, true)
  assert.deepEqual(summary.ops.plan, {
    files: true,
    discovery: true,
    presentation: 'native',
    shell: false,
    replaceOfficial: false,
    residentTools: true,
    residentNames: 2,
  })
})
