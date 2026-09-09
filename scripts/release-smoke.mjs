// Install the actual packed artifact into an isolated profile and boot the real host.
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdtemp, readFile, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir, release as osRelease } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'node:net'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { setTimeout as delay } from 'node:timers/promises'
import { acceptRuntime } from './runtime-acceptance.mjs'
import { acceptBrowser } from './browser-acceptance.mjs'
const root = fileURLToPath(new URL('../', import.meta.url))
const version = JSON.parse(await readFile(join(root, 'package.json'))).version
const artifact = resolve(process.argv.find(arg => arg.endsWith('.tgz')) ?? join(root, `dsh-openwrite-${version}.tgz`))
const sourceSpec = process.argv.find(arg => arg.startsWith('github:'))
const installSpec = sourceSpec ?? artifact
const temporary = process.argv.includes('--reuse')
  ? JSON.parse(await readFile(join(root, '.tmp-release-smoke.json'), 'utf8')).temporary
  : await mkdtemp(join(tmpdir(), 'openwrite-release-'))
// Use an independently installed host to test precise compatibility releases.
const cli = resolve(process.argv.find(arg => arg.startsWith('--host-cli='))?.slice('--host-cli='.length)
  ?? join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js'))
const hostVersion = JSON.parse(await readFile(join(cli, '../../package.json'))).version
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/(?:API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)/i.test(key) && !key.startsWith('DSH_') && !['NODE_OPTIONS', 'NODE_PATH'].includes(key)))
Object.assign(env, { DSH_HOME: join(temporary, 'dsh'), XDG_CONFIG_HOME: join(temporary, 'config'), XDG_DATA_HOME: join(temporary, 'data'), CI: '1' })
await mkdir(env.DSH_HOME, { recursive: true })
function run(args) {
  const result = spawnSync(process.execPath, [cli, ...args], { cwd: temporary, env, encoding: 'utf8', timeout: 120_000, maxBuffer: 8 * 1024 ** 2 })
  if (result.status !== 0) throw new Error(`${args.slice(0, 3).join(' ')}: ${result.stderr}\n${result.stdout}`)
  return result.stdout
}
let host
let log = ''
async function stopHost() {
  if (!host || host.exitCode !== null || host.signalCode !== null) return
  const exited = new Promise(done => host.once('exit', done))
  if (process.platform === 'win32') {
    await new Promise(done => { const killer = spawn('taskkill', ['/pid', String(host.pid), '/T', '/F'], { stdio: 'ignore' }); killer.once('error', done); killer.once('exit', done) })
  } else host.kill('SIGTERM')
  await Promise.race([exited, delay(5000)])
  if (host.exitCode === null && host.signalCode === null) { host.kill('SIGKILL'); await exited }
}
const report = { host: hostVersion, platform: process.platform, osRelease: osRelease(), arch: process.arch, node: process.version, installSource: sourceSpec ?? 'release', artifactSha256: sourceSpec ? null : createHash('sha256').update(await readFile(artifact)).digest('hex'), checks: [], modelCalls: 0, status: 'failed' }
try {
  run(['--profile', 'web', '--dump-config'])
  const other = join(temporary, 'coexist-plugin')
  await mkdir(other, { recursive: true })
  await writeFile(join(other, 'package.json'), JSON.stringify({ name: 'dsh-openwrite-coexist-fixture', version: '1.0.0', type: 'module', main: 'index.mjs', dsh: { bundle: { patch: './cordis.patch.yml' } } }))
  await writeFile(join(other, 'cordis.patch.yml'), '- insert:\n    - id: coexist-fixture\n      name: dsh-openwrite-coexist-fixture\n')
  await writeFile(join(other, 'index.mjs'), `export const name = 'dsh-openwrite-coexist-fixture'; export function apply(ctx) { ctx.inject(['webServer'], c => c.effect(() => c.webServer.register({ kind: 'exact', path: '/coexist-fixture', handler: (_req, res) => { res.writeHead(200); res.end('other plugin available'); } }))); }`)
  run(['plugin', '--profile', 'web', 'add', '-w', other])
  run(['plugin', '--profile', 'web', 'add', '-w', installSpec])
  const profile = JSON.parse(await readFile(join(env.DSH_HOME, 'profiles/web/package.json')))
  assert.equal(profile.dsh.profile.bundles.filter(name => name === 'dsh-openwrite').length, 1)
  run(['plugin', '--profile', 'web', 'add', '-w', installSpec])
  report.checks.push('install', 'repeat-install')
  const dump = run(['--profile', 'web', '--dump-config'])
  assert.match(dump, /openwrite-bridge/)
  const server = createServer()
  await new Promise(done => server.listen(0, '127.0.0.1', done))
  const port = server.address().port
  await new Promise(done => server.close(done))
  host = spawn(process.execPath, [cli, 'web', '--no-open', '--port', String(port)], { cwd: temporary, env, stdio: ['pipe', 'pipe', 'pipe'] })
  host.stdout.on('data', bytes => { log = (log + bytes).slice(-60000) })
  host.stderr.on('data', bytes => { log = (log + bytes).slice(-60000) })
  const base = `http://127.0.0.1:${port}`
  let cookie = ''
  let loginUrl = ''
  for (let count = 0; count < 120; count++) {
    loginUrl = log.match(new RegExp(`http://(?:127\\.0\\.0\\.1|localhost):${port}/?\\?[^\\s\\u001b]+`))?.[0] ?? ''
    if (loginUrl) break
    if (host.exitCode !== null) throw new Error(`Host failed before login: ${log}`)
    await delay(500)
  }
  if (!loginUrl) throw new Error('Host did not publish a browser login URL')
  const login = await fetch(loginUrl, { redirect: 'manual' })
  cookie = login.headers.get('set-cookie')?.split(';')[0] ?? ''
  assert.ok(cookie, 'Host login must issue an authority-bound cookie')
  const browserFetch = (url, init = {}) => fetch(url, { ...init, headers: { ...init.headers, cookie } })
  let status
  for (let count = 0; count < 180; count++) {
    if (host.exitCode !== null) throw new Error(`Host exited: ${log}`)
    try { const response = await browserFetch(base + '/studio-panel/runtime'); if (response.ok) { status = await response.json(); break } } catch {}
    await delay(500)
  }
  assert.ok(status, `Runtime route unavailable: ${log}`)
  // dsh wires shared SDK dependencies while booting the profile. Inspect them
  // only after its runtime route proves the plugin has finished loading.
  const hostRequire = createRequire(cli)
  const pluginRequire = createRequire(join(env.DSH_HOME, 'profiles/web/node_modules/dsh-openwrite/package.json'))
  report.hostServices = {}
  for (const name of ['@deepseek-ai/cordis', '@deepseek-ai/dsh-home-paths', '@deepseek-ai/dsh-settings', '@deepseek-ai/dsh-tools']) {
    const expected = hostRequire(name + '/package.json').version
    const actual = pluginRequire(name + '/package.json').version
    assert.equal(actual, expected, `${name}: plugin must use the host's service version`)
    report.hostServices[name] = actual
  }
  report.checks.push('host-service-versions')
  assert.equal(await (await browserFetch(base + '/coexist-fixture')).text(), 'other plugin available')
  report.checks.push('existing-plugin-coexistence')
  const installedVersion = JSON.parse(await readFile(join(env.DSH_HOME, 'profiles/web/node_modules/dsh-openwrite/package.json'))).version
  report.pluginVersion = installedVersion
  const presetId = `openwrite-${installedVersion.replace(/[^a-z0-9-]/g, '-')}`
  assert.match(presetId, /^[a-z0-9][a-z0-9-]*$/)
  await readFile(join(env.DSH_HOME, '.agent-presets', presetId, 'agent.cordis.yml'))
  assert.equal((await fetch(base + '/studio-panel/runtime')).status, 401, 'runtime control requires host browser authentication')
  let html = ''
  for (let count = 0; count < 60; count++) {
    const page = await browserFetch(base)
    html = await page.text()
    if (page.ok && html.includes('__DSH_BOOT__')) break
    await delay(500)
  }
  if (!html) throw new Error(`Web app did not boot: ${log}`)
  assert.match(html, /@dsh-novel\/studio-panel/)
  assert.match(html, /@dsh-external\/dsh-dog/)
  const asset = await browserFetch(base + '/studio-panel/vendor/vditor/dist/js/lute/lute.min.js')
  assert.equal(asset.status, 200)
  assert.ok((await asset.text()).length > 1000)
  const control = await browserFetch(base + '/studio-panel/runtime', { method: 'POST', headers: { 'content-type': 'application/json', 'X-OpenWrite-Studio': '1' }, body: JSON.stringify({ action: 'prepare' }) })
  assert.equal(control.status, 202)
  let previous = ''
  for (let count = 0; count < 600; count++) {
    status = await (await browserFetch(base + '/studio-panel/runtime')).json()
    if (status.phase !== previous) { console.log(status.phase, status.message); previous = status.phase }
    if (status.phase === 'ready') break
    if (status.phase === 'error') throw new Error(JSON.stringify(status))
    await delay(1000)
  }
  assert.equal(status.phase, 'ready')
  report.checks.push('start', 'authenticated-runtime', 'isolated-python', 'core-handshake', 'editor-assets')
  report.checks.push(...await acceptRuntime(join(env.DSH_HOME, 'profiles/web/node_modules/dsh-openwrite'), env.DSH_HOME, temporary))
  if (process.argv.includes('--browser')) report.checks.push(...await acceptBrowser(loginUrl, temporary))
  console.log(JSON.stringify({ platform: process.platform, arch: process.arch, node: process.version, artifact, installed: true, backend: 'ready', editorAssets: true, modelCalls: 0 }))
  if (process.argv.includes('--keep')) {
    await writeFile(join(root, '.tmp-release-smoke.json'), JSON.stringify({ temporary, base, loginUrl, pid: host.pid, artifact }), { mode: 0o600 })
    console.log('Browser QA host:', base, 'isolated home:', env.DSH_HOME)
    await new Promise(done => host.once('exit', done))
  }
  await stopHost()
  run(['plugin', '--profile', 'web', 'remove', '-w', 'dsh-openwrite'])
  const removed = JSON.parse(await readFile(join(env.DSH_HOME, 'profiles/web/package.json')))
  assert.equal(removed.dsh.profile.bundles.includes('dsh-openwrite'), false)
  assert.equal(removed.dsh.profile.bundles.includes('dsh-openwrite-coexist-fixture'), true)
  assert.ok(await readFile(join(env.DSH_HOME, 'openwrite', 'active.json')), 'uninstall preserves runtime data')
  report.checks.push('uninstall', 'retain-data')
  report.status = 'passed'
  console.log('Uninstall passed')
} catch (error) {
  report.error = String(error).replace(/([?&](?:token|key|signature)=)[^&\s]+/gi, '$1[redacted]')
  console.error(report.error)
  throw error
} finally {
  await writeFile(join(root, `release-report-${process.argv.some(arg => arg.startsWith('--host-cli=')) ? hostVersion + '-' : ''}${sourceSpec ? 'source-' : ''}${process.platform}-${process.arch}-${process.version}.json`), JSON.stringify(report, null, 2) + '\n')
  await stopHost()
  if (!process.argv.includes('--keep')) await rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 })
}
