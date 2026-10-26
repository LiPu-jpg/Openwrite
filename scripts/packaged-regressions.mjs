// Run platform regressions against the exact tarball being accepted. A fresh
// install runner has no built lib/ tree in its source checkout.
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFile, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { x as extract } from 'tar'

const checkout = fileURLToPath(new URL('../', import.meta.url))
const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url)))
const artifact = process.argv[2] ?? `${pkg.name}-${pkg.version}.tgz`
const temporary = await mkdtemp(join(tmpdir(), 'openwrite-packaged-regressions-'))
try {
  await extract({ file: resolve(artifact), cwd: temporary, strict: true })
  const root = join(temporary, 'package')
  await symlink(join(checkout, 'node_modules'), join(root, 'node_modules'), 'junction')
  const tests = [
    'scripts/preset-lifecycle.test.mjs',
    'scripts/safe-upgrade.test.mjs',
    'packages/openwrite-bridge/scripts/managed-runtime.test.mjs',
  ]
  for (const file of tests) {
    await mkdir(dirname(join(root, file)), { recursive: true })
    await copyFile(join(checkout, file), join(root, file))
  }
  await new Promise((done, reject) => {
    const child = spawn(process.execPath, ['--test', '--test-reporter=tap', ...tests], {
      cwd: root, stdio: 'inherit', detached: process.platform !== 'win32', windowsHide: true,
    })
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      if (!child.pid) return
      if (process.platform === 'win32') {
        const killer = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
        killer.once('error', () => child.kill('SIGKILL'))
      } else {
        try { process.kill(-child.pid, 'SIGKILL') } catch { child.kill('SIGKILL') }
      }
    }, 120_000)
    child.once('error', error => { clearTimeout(timer); reject(error) })
    child.once('exit', (code, signal) => {
      clearTimeout(timer)
      if (code === 0 && !timedOut) done()
      else reject(new Error(`Packaged regressions failed: ${timedOut ? 'timeout' : signal ?? code}`))
    })
  })
  const report = {
    status: 'passed', platform: process.platform, arch: process.arch, node: process.version,
    artifactSha256: createHash('sha256').update(await readFile(resolve(artifact))).digest('hex'),
    checks: ['durable-preset-identities', 'offline-profile-upgrade', 'managed-runtime'],
  }
  await writeFile(`packaged-regressions-report-${process.platform}-${process.arch}-${process.versions.node}.json`, JSON.stringify(report, null, 2) + '\n')
} finally {
  await rm(temporary, { recursive: true, force: true })
}
