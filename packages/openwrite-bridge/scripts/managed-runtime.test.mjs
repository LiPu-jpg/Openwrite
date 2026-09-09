import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { ManagedRuntime, sanitizeDiagnostic, stopOwnedProcess, buildChildEnv } from '../lib/managed-runtime.js'

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'openwrite-managed-test-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  return root
}

test('cross-process installation lease waits, cancels, and can be reacquired', async t => {
  const root = await fixture(t)
  const first = new ManagedRuntime(root, root)
  const second = new ManagedRuntime(root, root)
  const unlock = await first.lock(new AbortController().signal)
  const controller = new AbortController()
  const waiting = second.lock(controller.signal)
  setTimeout(() => controller.abort(), 30)
  await assert.rejects(waiting, { name: 'AbortError' })
  assert.equal(second.status().phase, 'waiting')
  await unlock()
  await (await second.lock(new AbortController().signal))()
})

test('untrusted local wheel fails before creating an environment; old active generation survives', async t => {
  const root = await fixture(t)
  const artifacts = join(root, 'artifacts')
  await mkdir(artifacts)
  await writeFile(join(root, 'active.json'), '{"generation":"old"}')
  await writeFile(join(artifacts, 'core.whl'), 'tampered')
  await writeFile(join(artifacts, 'runtime-manifest.json'), JSON.stringify({ platforms: { [`${process.platform}-${process.arch}`]: {} }, wheel: { file: 'core.whl', sha256: '0'.repeat(64) }, requirements: { file: 'requirements.lock', sha256: '0'.repeat(64) } }))
  const runtime = new ManagedRuntime(root, artifacts)
  await assert.rejects(runtime.ensure(), /校验失败/)
  assert.equal(runtime.status().phase, 'error')
  assert.equal(await readFile(join(root, 'active.json'), 'utf8'), '{"generation":"old"}')
  assert.equal((await readdir(root)).includes('environments'), false)
  await runtime.dispose()
  await assert.rejects(runtime.ensure(), /卸载/)
})

test('interrupted downloads remove partial files; retry verifies and reuses the cache', async t => {
  const root = await fixture(t)
  const payload = Buffer.alloc(32 * 1024, 7)
  let calls = 0
  const server = createServer((_req, res) => {
    calls++
    res.writeHead(200, { 'content-length': payload.length })
    res.write(payload.subarray(0, 16))
    if (calls > 1) res.end(payload.subarray(16))
  })
  await new Promise(done => server.listen(0, '127.0.0.1', done))
  t.after(() => { server.closeAllConnections(); server.close() })
  const item = { url: `http://127.0.0.1:${server.address().port}/uv.zip`, sha256: createHash('sha256').update(payload).digest('hex'), executable: 'uv' }
  const runtime = new ManagedRuntime(root, root)
  await assert.rejects(runtime.download(item, AbortSignal.timeout(100)))
  assert.deepEqual(await readdir(join(root, 'cache')), [])
  const path = await runtime.download(item, new AbortController().signal)
  assert.deepEqual(await readFile(path), payload)
  assert.equal(await runtime.download(item, new AbortController().signal), path)
  assert.equal(calls, 2)
})

test('owned process stops and diagnostics conceal credential-bearing errors', async () => {
  const child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { detached: process.platform !== 'win32', stdio: 'ignore' })
  await new Promise((done, reject) => { child.once('spawn', done); child.once('error', reject) })
  await stopOwnedProcess(child)
  assert.ok(child.exitCode !== null || child.signalCode !== null)
  const message = sanitizeDiagnostic('https://user:password@example.test/a?token=abc&key=def authorization: Bearer-secret api_key=xyz')
  for (const secret of ['user:password', 'abc', 'def', 'Bearer-secret', 'xyz']) assert.equal(message.includes(secret), false)
})

test('Unicode workspace headers survive HTTP byte restrictions without changing ASCII identities', async () => {
  const { workspaceRootHeaders } = await import('../lib/client.js')
  for (const path of ['/tmp/中文作品-100%', 'C:\\作者\\中文作品']) {
    const headers = new Headers(workspaceRootHeaders(path))
    assert.equal(headers.get('x-openwrite-workspace-root-encoding'), 'uri')
    assert.equal(decodeURIComponent(headers.get('x-openwrite-workspace-root')), path)
    assert.equal(new Headers(workspaceRootHeaders(path, true)).get('x-openwrite-workspace-root'), headers.get('x-openwrite-workspace-root'))
  }
  assert.deepEqual(workspaceRootHeaders('/tmp/book%20literal'), { 'X-OpenWrite-Workspace-Root': '/tmp/book%20literal' })
})

const BACKEND = `
const { createServer } = require('node:http')
const { createInterface } = require('node:readline')
const { appendFileSync } = require('node:fs')
const crash = process.env.OPENWRITE_CRASH || ''
const crashMs = Number(process.env.OPENWRITE_CRASH_MS || 0)
const log = process.env.OPENWRITE_POST_LOG
const rl = createInterface({ input: process.stdin })
rl.once('line', line => {
  const token = JSON.parse(line).token
  const server = createServer((req, res) => {
    if (log && req.method !== 'GET') appendFileSync(log, req.method + ' ' + (req.url || '') + '\\n')
    if ((req.url || '').startsWith('/api/health')) {
      if (req.headers.authorization !== 'Bearer ' + token) { res.writeHead(401); res.end(); return }
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ core_version: 'test-core', contract_version: 1 }))
      return
    }
    if ((req.url || '').startsWith('/api/write')) {
      if (process.env.OPENWRITE_HANG_WRITE) return
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: true, data: { accepted: true } }))
      return
    }
    res.writeHead(404); res.end()
  })
  server.listen(0, '127.0.0.1', () => {
    process.stdout.write(JSON.stringify({ port: server.address().port }) + '\\n')
    if (crash === 'after-ready' || crashMs) setTimeout(() => process.exit(Number(process.env.OPENWRITE_EXIT_CODE || 7)), crashMs || 60)
  })
})
`

async function prepared(t) {
  const root = await fixture(t)
  const artifacts = join(root, 'artifacts')
  await mkdir(artifacts)
  const wheel = Buffer.from('wheel')
  const requirements = Buffer.from('req')
  await writeFile(join(artifacts, 'core.whl'), wheel)
  await writeFile(join(artifacts, 'requirements.lock'), requirements)
  const manifest = {
    schema: 1, dsh: '0.1.2-rc.1', python_version: '3.12', core_version: 'test-core', contract_version: 1,
    platforms: { [`${process.platform}-${process.arch}`]: {
      uv: { url: 'http://127.0.0.1/uv', sha256: '0'.repeat(64), executable: 'uv' },
      python: { url: 'http://127.0.0.1/py', sha256: '0'.repeat(64), executable: 'python' },
    } },
    wheel: { file: 'core.whl', sha256: createHash('sha256').update(wheel).digest('hex') },
    requirements: { file: 'requirements.lock', sha256: createHash('sha256').update(requirements).digest('hex') },
  }
  await writeFile(join(artifacts, 'runtime-manifest.json'), JSON.stringify(manifest))
  const parsed = JSON.parse(await readFile(join(artifacts, 'runtime-manifest.json'), 'utf8'))
  const generation = createHash('sha256').update(JSON.stringify(parsed)).digest('hex').slice(0, 24)
  const envDir = join(root, 'environments', generation)
  await mkdir(join(envDir, process.platform === 'win32' ? 'Scripts' : 'bin'), { recursive: true })
  await writeFile(join(envDir, '.complete'), generation)
  await writeFile(join(envDir, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'), '')
  return { root, artifacts }
}

function backendSpawn(t, extraEnv = {}, recorded = []) {
  const spawnFn = (command, args, options) => {
    recorded.push({ command, args: [...args], env: { ...(options.env ?? {}) } })
    if (args.includes('tools.managed_runtime')) {
      return spawn(process.execPath, ['-e', BACKEND], {
        ...options,
        env: { ...options.env, ...extraEnv() },
      })
    }
    return spawn(command, args, options)
  }
  return spawnFn
}

async function waitPhase(runtime, phase, timeout = 8_000) {
  const start = Date.now()
  while (Date.now() - start < timeout) {
    if (runtime.status().phase === phase) return runtime.status()
    await new Promise(resolve => setTimeout(resolve, 20))
  }
  throw new Error(`timed out waiting for ${phase}, last ${JSON.stringify(runtime.status())}`)
}

test('child env allowlist drops provider keys and keeps proxy/cert/OS start vars', () => {
  const env = buildChildEnv({
    OPENAI_API_KEY: 'sk-test', ANTHROPIC_API_KEY: 'ant-test', LLM_API_KEY: 'llm-test',
    PATH: '/bin', HTTP_PROXY: 'http://proxy.example:8080', SSL_CERT_FILE: '/certs/ca.pem',
    HOME: '/home/author', SYSTEMROOT: 'C:\\\\Windows',
  }, { PYTHONNOUSERSITE: '1', PYTHONUTF8: '1', UV_CACHE_DIR: '/tmp/uv' })
  for (const key of ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'LLM_API_KEY']) assert.equal(env[key], undefined)
  assert.equal(env.PATH, '/bin')
  assert.equal(env.HTTP_PROXY, 'http://proxy.example:8080')
  assert.equal(env.SSL_CERT_FILE, '/certs/ca.pem')
  assert.equal(env.PYTHONUTF8, '1')
  assert.equal(env.PYTHONNOUSERSITE, '1')
  assert.equal(env.UV_CACHE_DIR, '/tmp/uv')
})

test('ready managed child auto-restarts with backoff; cap leaves a retryable error', async t => {
  const previous = {
    OPENAI_API_KEY: process.env.OPENAI_API_KEY,
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
    LLM_API_KEY: process.env.LLM_API_KEY,
  }
  Object.assign(process.env, { OPENAI_API_KEY: 'sk-test', ANTHROPIC_API_KEY: 'ant-test', LLM_API_KEY: 'llm-test' })
  t.after(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  })
  const { root, artifacts } = await prepared(t)
  const recorded = []
  const delays = []
  const crash = { value: '' }
  const runtime = new ManagedRuntime(root, artifacts, {
    spawn: backendSpawn(t, () => ({ OPENWRITE_CRASH: crash.value, OPENWRITE_EXIT_CODE: '7' }), recorded),
    delay: async (ms, value, options) => {
      delays.push(ms)
      if (options?.signal?.aborted) { const error = new Error('aborted'); error.name = 'AbortError'; throw error }
      return value
    },
    restartLimit: 2,
    backoffMs: [11, 22],
  })
  t.after(() => runtime.dispose())
  const first = await runtime.ensure()
  assert.equal(runtime.status().phase, 'ready')
  assert.ok(first.token)
  assert.equal((await fetch(first.baseUrl + '/api/health')).status, 401)
  const backendSpawns = () => recorded.filter(item => item.args.includes('tools.managed_runtime'))
  assert.equal(backendSpawns()[0].env.OPENAI_API_KEY, undefined)
  assert.equal(backendSpawns()[0].env.ANTHROPIC_API_KEY, undefined)
  assert.equal(backendSpawns()[0].env.LLM_API_KEY, undefined)
  assert.equal(backendSpawns()[0].env.PYTHONUTF8, '1')
  crash.value = 'after-ready'
  await stopOwnedProcess(runtime.child)
  const recovering = await waitPhase(runtime, 'recovering')
  assert.match(recovering.message, /正在恢复/)
  assert.match(recovering.error ?? '', /exit 7|signal/)
  const recovered = await waitPhase(runtime, 'ready')
  assert.match(recovered.message, /不会自动重试/)
  assert.doesNotMatch(recovered.message, /任务恢复成功|写作任务已恢复/)
  assert.ok(delays.includes(11) || delays.includes(22))
  await waitPhase(runtime, 'error', 12_000)
  assert.match(runtime.status().message, /手动重试/)
  assert.match(runtime.status().error ?? '', /exit 7|signal/)
  crash.value = ''
  const retried = await runtime.ensure()
  assert.equal(runtime.status().phase, 'ready')
  assert.equal((await fetch(retried.baseUrl + '/api/health', { headers: { Authorization: 'Bearer ' + retried.token } })).status, 200)
  await runtime.dispose()
  assert.equal(runtime.status().phase, 'uninstalled')
  assert.equal(runtime.child, undefined)
})

test('cancel, dispose and a stale child exit do not revive or clobber a newer connection', async t => {
  const { root, artifacts } = await prepared(t)
  const recorded = []
  const runtime = new ManagedRuntime(root, artifacts, {
    spawn: backendSpawn(t, () => ({}), recorded),
    delay: async (ms, value, options) => {
      if (options?.signal?.aborted) { const error = new Error('aborted'); error.name = 'AbortError'; throw error }
      return value
    },
    restartLimit: 3,
    backoffMs: [5, 5, 5],
  })
  t.after(() => runtime.dispose())
  const a = await runtime.ensure()
  const childA = runtime.child
  await runtime.cancel()
  await stopOwnedProcess(childA)
  await new Promise(resolve => setTimeout(resolve, 80))
  assert.notEqual(runtime.status().phase, 'recovering')
  assert.notEqual(runtime.status().phase, 'ready')
  const b = await runtime.ensure()
  assert.equal(runtime.status().phase, 'ready')
  const spawnsBeforeDispose = recorded.filter(item => item.args.includes('tools.managed_runtime')).length
  await runtime.dispose()
  await new Promise(resolve => setTimeout(resolve, 50))
  assert.equal(recorded.filter(item => item.args.includes('tools.managed_runtime')).length, spawnsBeforeDispose)
  await assert.rejects(runtime.ensure(), /卸载/)
  assert.notEqual(a.baseUrl, b.baseUrl)
})

test('concurrent ensure starts one process; an old exit leaves the new connection', async t => {
  const { root, artifacts } = await prepared(t)
  t.mock.method(globalThis, 'fetch', async url => {
    if (String(url).includes('/api/health')) {
      return new Response(JSON.stringify({ core_version: 'test-core', contract_version: 1 }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response('{}', { status: 404 })
  })
  let port = 18080
  const children = []
  const spawnFn = () => {
    const child = new EventEmitter()
    const current = port++
    child.stdin = new PassThrough()
    child.stdout = new PassThrough()
    child.stderr = new PassThrough()
    child.exitCode = null
    child.signalCode = null
    child.kill = () => { child.exitCode = 1; child.emit('exit', 1, null) }
    child.stdin.once('data', () => child.stdout.write(JSON.stringify({ port: current }) + '\n'))
    children.push(child)
    return child
  }
  const runtime = new ManagedRuntime(root, artifacts, { spawn: spawnFn, delay: async () => undefined, restartLimit: 3, backoffMs: [1] })
  const [one, two] = await Promise.all([runtime.ensure(), runtime.ensure()])
  assert.equal(one.baseUrl, two.baseUrl)
  assert.equal(children.length, 1)
  runtime.connection = undefined
  const next = await runtime.ensure()
  assert.equal(children.length, 2)
  assert.notEqual(next.baseUrl, one.baseUrl)
  children[0].emit('exit', 1, null)
  assert.equal(runtime.status().phase, 'ready')
  assert.equal((await runtime.ensure()).baseUrl, next.baseUrl)
  await runtime.dispose()
})

test('in-flight generate is not replayed when the managed child is recovered', async t => {
  const { root, artifacts } = await prepared(t)
  const log = join(root, 'posts.log')
  await writeFile(log, '')
  const runtime = new ManagedRuntime(root, artifacts, {
    spawn: backendSpawn(t, () => ({ OPENWRITE_POST_LOG: log, OPENWRITE_HANG_WRITE: '1' }), []),
    delay: async (ms, value, options) => {
      if (options?.signal?.aborted) { const error = new Error('aborted'); error.name = 'AbortError'; throw error }
      return value
    },
    backoffMs: [5],
    restartLimit: 3,
  })
  t.after(() => runtime.dispose())
  const connection = await runtime.ensure()
  const hung = fetch(connection.baseUrl + '/api/write', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + connection.token, 'content-type': 'application/json' },
    body: JSON.stringify({ chapter_id: 'ch_1' }),
  })
  const hungFailure = hung.then(() => { throw new Error('in-flight write completed after backend crash') }, error => error)
  await new Promise(resolve => setTimeout(resolve, 40))
  await stopOwnedProcess(runtime.child)
  await waitPhase(runtime, 'ready')
  assert.ok(await hungFailure)
  assert.equal((await readFile(log, 'utf8')).trim().split('\n').filter(Boolean).length, 1)
  assert.match(runtime.status().message, /不会自动重试|已就绪/)
  assert.doesNotMatch(runtime.status().message, /任务恢复成功/)
})

