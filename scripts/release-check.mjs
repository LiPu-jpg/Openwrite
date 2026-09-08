// Validate exactly what npm packs, rather than accepting a working source checkout.
import assert from 'node:assert/strict'
import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { x as untar } from 'tar'
import { unzipSync } from 'fflate'
const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url)))
const artifact = resolve(process.argv[2] ?? `dsh-openwrite-${pkg.version}.tgz`)
const directory = await mkdtemp(join(tmpdir(), 'openwrite-pack-check-'))
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
try {
  await untar({ file: artifact, cwd: directory, strict: true })
  const root = join(directory, 'package')
  const manifest = JSON.parse(await readFile(join(root, 'release/runtime-manifest.json')))
  const packed = JSON.parse(await readFile(join(root, 'package.json')))
  const sourceIdentity = JSON.parse(await readFile(join(root, 'release/source.json')))
  for (const component of sourceIdentity.components) for (const file of component.files) {
    assert.ok((await readFile(join(root, 'release/licenses', (component.name + '@' + component.version).replaceAll('/', '__'), file))).length > 0)
  }
  assert.equal(packed.name, 'dsh-openwrite')
  assert.equal(packed.private, undefined)
  for (const file of ['plugin.mjs', 'plugin.d.ts', 'cordis.patch.yml', 'packages/openwrite-bridge/lib/index.js', 'packages/openwrite-bridge/lib/index.d.ts', 'packages/openwrite-bridge/lib/preset-tools.js', 'packages/studio-panel/lib/client.js', 'packages/studio-panel/lib/types/index.d.ts', 'packages/studio-panel/vendor/vditor/LICENSE', 'vendor/dsh-dog/lib/index.js', 'vendor/dsh-dog/lib/client.js', 'vendor/dsh-dog/LICENSE', 'presets/openwrite/agent.cordis.yml', 'scripts/dog/review-record.js', 'LICENSE', 'THIRD_PARTY_NOTICES.md']) {
    assert.ok((await readFile(join(root, file))).length > 0, file)
  }
  for (const asset of [manifest.wheel, manifest.requirements, ...(manifest.dependency_wheels ?? [])]) assert.equal(hash(await readFile(join(root, 'release', asset.file))), asset.sha256, asset.file)
  const wheel = unzipSync(await readFile(join(root, 'release', manifest.wheel.file)))
  for (const file of ['tools/managed_runtime.py', 'tools/studio_http.py', 'tools/model_benchmark.py', 'tools/benchmark_scheduler.py']) assert.ok(wheel[file], `Core wheel: ${file}`)
  assert.ok(Object.keys(wheel).some(name => /dist-info\/licenses\/LICENSE/.test(name)), 'Core license')
  const bridge = await readFile(join(root, 'packages/openwrite-bridge/lib/index.js'), 'utf8')
  assert.doesNotMatch(bridge, /registerNovelTools\(/, 'host must not register novel tools')
  for (const file of ['packages/studio-panel/lib/client.js', 'vendor/dsh-dog/lib/client.js']) {
    const source = await readFile(join(root, file), 'utf8')
    assert.doesNotMatch(source, /(?:require\(|from\s*)["']node:/, 'browser must not import Node')
    assert.doesNotMatch(source, /class ToolRuntime|class ClientSessions|class SlotRegistry/, 'host services must remain external')
  }
  const result = { artifact: packed.name + '-' + packed.version + '.tgz', sha256: hash(await readFile(artifact)), core: manifest.wheel, host: manifest.dsh, checked: new Date().toISOString(), source: { ...manifest.sources, plugin: sourceIdentity } }
  await writeFile(artifact + '.manifest.json', JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result))
} finally { await rm(directory, { recursive: true, force: true }) }
