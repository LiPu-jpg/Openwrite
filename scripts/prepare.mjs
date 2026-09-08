// Git installs build here only after the user authorizes this package in pnpm.
// Precompiled Release tarballs need no install script or sibling checkout.
import { access, readFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
const manifest = JSON.parse(await readFile(new URL('../release/runtime-manifest.json', import.meta.url), 'utf8'))
let built = false
await access(new URL('../release/' + manifest.wheel.file, import.meta.url))
for (const dir of ['packages/openwrite-bridge', 'packages/studio-panel', 'vendor/dsh-dog']) {
  try { await access(new URL(`../${dir}/lib/index.js`, import.meta.url)); await access(new URL(`../${dir}/lib/${dir.endsWith('openwrite-bridge') ? 'preset-tools.js' : 'client.js'}`, import.meta.url)); continue } catch {}
  built = true
  for (const args of [['ci', '--ignore-scripts', '--no-audit', '--no-fund'], ['run', 'build']]) {
    const result = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', args, { cwd: root + dir, stdio: 'inherit', shell: process.platform === 'win32' })
    if (result.status !== 0) throw new Error(`${dir}: ${args.join(' ')} failed`)
  }
}
if (built) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('./release-provenance.mjs', import.meta.url))], { cwd: root, stdio: 'inherit' })
  if (result.status !== 0) throw new Error('Release provenance generation failed')
}
