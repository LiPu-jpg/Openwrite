import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { ManagedRuntime, sanitizeDiagnostic, stopOwnedProcess } from '../lib/managed-runtime.js'

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
