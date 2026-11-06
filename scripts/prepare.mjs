// Git installs build here only after the user authorizes this package in pnpm.
// Precompiled Release tarballs need no install script or sibling checkout.
import { access, readFile, stat } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
const manifest = JSON.parse(await readFile(new URL('../release/runtime-manifest.json', import.meta.url), 'utf8'))
let built = false
await access(new URL('../release/' + manifest.wheel.file, import.meta.url))
// The plugin version is baked into the client bundle as the preset identity
// (`openwrite-<version>`), so a package.json edited after the last build
// leaves the bundle naming the previous release. A build that only checks
// whether the outputs exist packs that stale identity, and the host then
// answers `preset "openwrite-<old>" not found`. Rebuild whenever the manifest
// is newer than the artifacts it feeds.
const manifestStamp = (await stat(new URL('../package.json', import.meta.url))).mtimeMs
for (const dir of ['packages/openwrite-bridge', 'packages/studio-panel']) {
  const outputs = [
    new URL(`../${dir}/lib/index.js`, import.meta.url),
    new URL(`../${dir}/lib/${dir.endsWith('openwrite-bridge') ? 'preset-tools.js' : 'client.js'}`, import.meta.url),
  ]
  let newest = 0
  try { for (const file of outputs) newest = Math.max(newest, (await stat(file)).mtimeMs) } catch { newest = 0 }
  if (newest !== 0 && newest >= manifestStamp) continue
  built = true
  for (const args of [['ci', '--ignore-scripts', '--no-audit', '--no-fund'], ['run', 'build']]) {
    const result = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', args, { cwd: root + dir, stdio: 'inherit', shell: process.platform === 'win32' })
    if (result.status !== 0) throw new Error(`${dir}: ${args.join(' ')} failed`)
  }
}
// Provenance must be refreshed whenever the source tree no longer matches the
// recorded hash, not merely when this run happened to build. Gating on `built`
// alone means "edit src/, then pack without rebuilding" publishes a tarball
// whose release/source.json still names the previous tree — and that file is
// gitignored, so release-report.mjs's dirty check cannot see it either.
let provenanceStale = true
try {
  provenanceStale = !JSON.parse(await readFile(new URL('../release/source.json', import.meta.url), 'utf8')).sourceTreeSha256
} catch { /* missing or unreadable: regenerate */ }
if (built || provenanceStale) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('./release-provenance.mjs', import.meta.url))], { cwd: root, stdio: 'inherit' })
  if (result.status !== 0) throw new Error('Release provenance generation failed')
}
