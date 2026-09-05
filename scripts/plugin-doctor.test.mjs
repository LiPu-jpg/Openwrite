import assert from 'node:assert/strict'
import test from 'node:test'
import { auditBundle, auditVersions } from './plugin-doctor.mjs'

const sdk = '@deepseek-ai/dsh-tools'
const baseline = '0.1.0-rc.7'
const manifest = { devDependencies: { [sdk]: baseline }, overrides: { [sdk]: baseline } }
const lock = { packages: { '': { devDependencies: { [sdk]: baseline } },
  [`node_modules/${sdk}`]: { version: baseline } } }

test('accepts a consistent SDK and catches transitive version drift', () => {
  assert.deepEqual(auditVersions(manifest, lock, baseline), [])
  const bad = structuredClone(lock)
  bad.packages[`node_modules/${sdk}`].version = '0.1.0-rc.8'
  assert.match(auditVersions(manifest, bad, baseline).join(), /DSH lock drift/)
})
test('rejects loose ranges, missing overrides and stale root lock metadata', () => {
  const bad = { devDependencies: { [sdk]: `^${baseline}` } }
  const errors = auditVersions(bad, lock, baseline).join()
  assert.match(errors, /unpinned DSH dependency/)
  assert.match(errors, /missing DSH override/)
  assert.match(errors, /lock metadata differs/)
})
test('does not misclassify libraries nested below a DSH dependency as DSH packages', () => {
  const good = structuredClone(lock)
  good.packages[`node_modules/${sdk}/node_modules/react`] = { version: '18.3.1' }
  assert.deepEqual(auditVersions(manifest, good, baseline), [])
})
test('rejects a required direct SDK omitted entirely from the lock', () => {
  const bad = structuredClone(lock)
  delete bad.packages[`node_modules/${sdk}`]
  assert.match(auditVersions(manifest, bad, baseline).join(), /required SDK missing from lock/)
})

const bundle = { name: '@dsh-novel/test', main: 'lib/index.js', types: 'lib/index.d.ts',
  exports: { '.': { types: './lib/index.d.ts', default: './lib/index.js' }, './package.json': './package.json' },
  dsh: { bundle: { patch: './cordis.patch.yml' } } }
const files = ['package.json', 'lib/index.js', 'lib/index.d.ts', 'cordis.patch.yml']
const patch = [{ insert: [{ id: 'test', name: bundle.name }] }]
test('validates tarball contents rather than only files present in the checkout', () => {
  assert.deepEqual(auditBundle(bundle, files, patch), [])
  assert.match(auditBundle(bundle, files.filter(p => p !== 'lib/index.d.ts'), patch).join(), /entry missing from tarball/)
})
test('rejects escaping paths and incorrect or duplicated patch mounts', () => {
  assert.match(auditBundle({ ...bundle, main: '../index.js' }, files, patch).join(), /entry escapes package/)
  assert.match(auditBundle(bundle, files, [{ insert: [patch[0].insert[0], patch[0].insert[0]] }]).join(), /exactly once/)
  assert.match(auditBundle(bundle, files, []).join(), /exactly once/)
})
test('web packages must ship the editor runtime, license and auxiliary assets', () => {
  const web = structuredClone(bundle)
  web.dsh.client = { platform: 'web' }
  const errors = auditBundle(web, files, patch).join()
  assert.match(errors, /\.\/client export/)
  assert.match(errors, /editor asset missing from tarball: LICENSE/)
  assert.match(errors, /lute.min.js/)
})
test('a client export cannot bypass web checks by omitting dsh.client', () => {
  const web = structuredClone(bundle)
  web.exports['./client'] = './lib/client.js'
  const errors = auditBundle(web, [...files, 'lib/client.js'], patch).join()
  assert.match(errors, /platform=web/)
  assert.match(errors, /editor asset missing from tarball/)
})
