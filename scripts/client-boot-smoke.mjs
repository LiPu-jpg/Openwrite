// Real browser boot against an independently installed host, without models
// or runtime preparation. Every profile and preset write stays temporary.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, mkdir, writeFile, symlink, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { createServer } from 'node:net'
import { setTimeout as delay } from 'node:timers/promises'
import { x as extract } from 'tar'

const root = fileURLToPath(new URL('../', import.meta.url))
const cli = resolve(process.argv.find(arg => arg.startsWith('--host-cli='))?.slice(11)
  ?? join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js'))
const hostVersion = JSON.parse(await readFile(join(cli, '../../package.json'))).version
const temporary = await mkdtemp(join(tmpdir(), 'openwrite-client-boot-'))
const home = join(temporary, 'dsh')
const profile = join(home, 'profiles/web')
const require = createRequire(join(root, 'packages/studio-panel/package.json'))
const expected = ['@dsh-novel/studio-panel', '@dsh-external/dsh-dog']
const errors = []
let host, browser
let log = ''
try {
  let plugin = root
  const artifact = process.argv.find(arg => arg.endsWith('.tgz'))
  if (artifact) {
    const staging = join(temporary, 'artifact')
    await mkdir(staging)
    await extract({ file: resolve(artifact), cwd: staging })
    plugin = join(staging, 'package')
    // Runtime dependencies come from this locked checkout; host peers resolve
    // through DSH's own runtime resolver, as they do in an installed profile.
    await symlink(join(root, 'node_modules'), join(plugin, 'node_modules'), 'junction')
  }
  await mkdir(join(profile, 'node_modules'), { recursive: true })
  await symlink(plugin, join(profile, 'node_modules/dsh-openwrite'), 'junction')
  const other = join(profile, 'node_modules/openwrite-coexist-fixture')
  await mkdir(other)
  await writeFile(join(other, 'package.json'), JSON.stringify({
    name: 'openwrite-coexist-fixture', version: '1.0.0', type: 'module', main: 'index.mjs',
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }))
  await writeFile(join(other, 'cordis.patch.yml'), '- insert:\n    - id: coexist\n      name: openwrite-coexist-fixture\n')
  await writeFile(join(other, 'index.mjs'), `export function apply(ctx) {
    ctx.inject(['webServer'], c => c.effect(() => c.webServer.register({
      kind: 'exact', path: '/openwrite-coexist-fixture',
      handler: (_req, res) => { res.writeHead(200); res.end('available'); },
    })));
  }`)
  const manifest = { name: 'openwrite-client-test', private: true,
    dependencies: { 'dsh-openwrite': 'file:' + plugin, 'openwrite-coexist-fixture': 'file:' + other },
    dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app', 'dsh-openwrite', 'openwrite-coexist-fixture'] } },
  }
  await writeFile(join(profile, 'package.json'), JSON.stringify(manifest))
  const server = createServer()
  await new Promise(done => server.listen(0, '127.0.0.1', done))
  const port = server.address().port
  await new Promise(done => server.close(done))
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/(?:API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(key) && !key.startsWith('DSH_')
    && !['NODE_OPTIONS', 'NODE_PATH'].includes(key)))
  Object.assign(env, { DSH_HOME: home, CI: '1' })
  host = spawn(process.execPath, [cli, 'web', '--no-open', '--port', String(port)], {
    cwd: temporary, env, stdio: ['ignore', 'pipe', 'pipe'],
  })
  for (const stream of [host.stdout, host.stderr]) stream.on('data', bytes => { log = (log + bytes).slice(-60000) })
  let login
  for (let count = 0; count < 120; count++) {
    login = log.match(new RegExp(`http://(?:127\\.0\\.0\\.1|localhost):${port}/?\\?[^\\s\\u001b]+`))?.[0]
    if (login) break
    assert.equal(host.exitCode, null, 'host exited before readiness')
    await delay(250)
  }
  assert.ok(login, 'host login URL unavailable')
  assert.doesNotMatch(log, /disabling profile plugin row|did not activate|incompatible with dsh/)
  browser = await require('@playwright/test').chromium.launch({ headless: true })
  const page = await browser.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  await page.goto(login)
  await page.getByRole('button', { name: /^(Continue|继续)$/ }).click()
  const configureLater = page.getByRole('button', { name: /^(Configure later|稍后配置)$/ })
  if (await configureLater.isVisible()) await configureLater.click()
  await page.getByRole('button', { name: /^(Open OpenWrite|打开 OpenWrite)$/ }).waitFor()
  const entries = await page.evaluate(() => window.__DSH_BOOT__.entries.map(entry => entry.id))
  for (const id of expected) assert.ok(entries.includes(id), `${id}: missing client boot entry`)
  assert.equal(await page.evaluate(async () => (await fetch('/openwrite-coexist-fixture')).text()), 'available')
  await page.evaluate(() => window.dispatchEvent(new Event('openwrite:dog-open')))
  await page.getByRole('dialog', { name: /DoG/i }).waitFor()
  assert.deepEqual(errors, [], 'client initialization and debugger render errors')
  assert.deepEqual(JSON.parse(await readFile(join(profile, 'package.json'))).dsh.profile.bundles, manifest.dsh.profile.bundles)
  console.log(JSON.stringify({ host: hostVersion, clients: expected, checks: [
    'version-gates-without-exemptions', 'client-activation', 'launcher', 'dog-overlay', 'other-plugin-preserved',
  ], modelCalls: 0 }))
} finally {
  await browser?.close()
  if (host && host.exitCode === null && host.signalCode === null) {
    const exited = new Promise(done => host.once('exit', done))
    host.kill('SIGTERM')
    await Promise.race([exited, delay(5000)])
    if (host.exitCode === null && host.signalCode === null) { host.kill('SIGKILL'); await exited }
  }
  await rm(temporary, { recursive: true, force: true })
}
