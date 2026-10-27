import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { zipSync, strToU8 } from 'fflate'
import { ManagedRuntime, stopOwnedProcess } from '../lib/managed-runtime.js'

let python
for (const command of [process.env.OPENWRITE_TEST_PYTHON, 'python3', 'python'].filter(Boolean)) {
  const found = spawnSync(command, ['-I', '-c', 'import sys; print(sys.executable if sys.version_info >= (3, 10) else "")'], { encoding: 'utf8', timeout: 10_000, windowsHide: true })
  if (found.status === 0 && found.stdout.trim()) { python = found.stdout.trim(); break }
}
const realPython = { skip: python ? false : 'Python >=3.10 is needed for the real interpreter integration' }

const backend = `
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import TCPServer
from tools.studio_http import health_payload
token = json.loads(sys.stdin.readline())['token']
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.headers.get('Authorization') == 'Bearer ' + token else 401)
        self.end_headers()
        self.wfile.write(json.dumps(health_payload()).encode())
    def log_message(self, *args): pass
# HTTPServer.server_bind calls getfqdn even for loopback. A local test
# server must not depend on the CI runner's external reverse-DNS service.
class Server(HTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]
server = Server(('127.0.0.1', 0), Handler)
print(json.dumps({'port': server.server_port}), flush=True)
server.serve_forever()
`

async function fixture(t, { missingDependency = false, reportedVersion = 'test-core' } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'openwrite-system-作者 '))
  const runtimes = []
  // Windows will not remove a live child's working directory. One teardown
  // owns every instance and stops them all before removing the fixture.
  t.after(async () => {
    await Promise.all(runtimes.map(runtime => runtime.dispose()))
    await rm(root, { recursive: true, force: true })
  })
  const artifacts = join(root, 'artifacts')
  const modules = join(root, 'prepared dependencies')
  await mkdir(artifacts)
  await mkdir(modules)
  if (!missingDependency) await writeFile(join(modules, 'supplied_dependency.py'), 'VALUE = "author dependency"\n')
  const wheel = zipSync(Object.fromEntries(Object.entries({
    'tools/__init__.py': '',
    'tools/studio.py': 'def create_server(): pass\n',
    'tools/studio_http.py': `from supplied_dependency import VALUE\ndef health_payload():\n    assert VALUE == 'author dependency'\n    return {'core_version': '${reportedVersion}', 'contract_version': 1}\n`,
    'tools/managed_runtime.py': backend,
  }).map(([name, text]) => [name, strToU8(text)])))
  const requirements = Buffer.from('prepared-by-author\n')
  await writeFile(join(artifacts, 'core.whl'), wheel)
  await writeFile(join(artifacts, 'requirements.lock'), requirements)
  const hash = value => createHash('sha256').update(value).digest('hex')
  const manifest = { platforms: {}, core_version: 'test-core', contract_version: 1,
    wheel: { file: 'core.whl', sha256: hash(wheel) }, requirements: { file: 'requirements.lock', sha256: hash(requirements) } }
  await writeFile(join(artifacts, 'runtime-manifest.json'), JSON.stringify(manifest))
  const runtimeRoot = join(root, 'owned runtime')
  const createRuntime = options => {
    const runtime = new ManagedRuntime(runtimeRoot, artifacts, options)
    runtimes.push(runtime)
    return runtime
  }
  const runtime = createRuntime({ pythonPath: python, pythonModulePaths: [modules], backoffMs: [1] })
  runtime.extract = async () => { throw new Error('A supplied Python must never download a runtime') }
  return { root, artifacts, modules, runtimeRoot, runtime, createRuntime }
}

test('supplied Python starts without a platform artifact, preserves dependencies, authenticates and recovers', realPython, async t => {
  const { runtime, runtimeRoot, modules } = await fixture(t)
  const previousLibraryPath = process.env.LD_LIBRARY_PATH
  process.env.LD_LIBRARY_PATH = modules
  t.after(() => { if (previousLibraryPath === undefined) delete process.env.LD_LIBRARY_PATH; else process.env.LD_LIBRARY_PATH = previousLibraryPath })
  const children = []
  let stage = 'preflight'
  const processes = []
  const diagnostic = setTimeout(() => console.error('Supplied Python fixture progress:', stage, runtime.status(), processes.map(child => ({ pid: child.pid, exit: child.exitCode, signal: child.signalCode }))), 8_000)
  t.after(() => clearTimeout(diagnostic))
  runtime.spawnFn = (command, args, options) => {
    children.push(options.env)
    const launch = [...args]
    const script = launch.indexOf('-c')
    if (script >= 0) launch[script + 1] = 'import faulthandler; faulthandler.dump_traceback_later(8, repeat=True); ' + launch[script + 1]
    const child = spawn(command, launch, options)
    processes.push(child)
    child.stderr?.on('data', bytes => console.error('Supplied Python fixture stderr:', String(bytes)))
    return child
  }
  const source = await readFile(join(modules, 'supplied_dependency.py'))
  const first = await runtime.ensure()
  stage = 'health checks'
  assert.equal(runtime.status().phase, 'ready')
  assert.equal(children.length, 2, 'preflight and managed child both use the supplied interpreter')
  assert.ok(children.every(env => env.LD_LIBRARY_PATH === modules))
  assert.equal((await fetch(first.baseUrl + '/api/health')).status, 401)
  const response = await fetch(first.baseUrl + '/api/health', { headers: { Authorization: `Bearer ${first.token}` } })
  assert.equal(response.status, 200)
  assert.equal((await response.json()).core_version, 'test-core')
  assert.deepEqual(await readFile(join(modules, 'supplied_dependency.py')), source)
  assert.deepEqual(await readdir(modules), ['supplied_dependency.py'], 'no dependency or bytecode files written')
  assert.equal((await readdir(runtimeRoot)).includes('binaries'), false)
  const previous = runtime.child
  stage = 'stop previous child'
  await stopOwnedProcess(previous)
  stage = 'recover child'
  const recovered = await runtime.ensure()
  stage = 'recovered health check'
  assert.notEqual(recovered.token, first.token)
  assert.equal(runtime.status().phase, 'ready')
  assert.equal((await fetch(recovered.baseUrl + '/api/health', { headers: { Authorization: `Bearer ${first.token}` } })).status, 401)
  await runtime.dispose()
  stage = 'disposed'
  clearTimeout(diagnostic)
  assert.ok(runtime.child === undefined)
})

test('missing supplied dependencies fail before promotion, without downloads or replacing the prior environment', realPython, async t => {
  const { runtime, runtimeRoot } = await fixture(t, { missingDependency: true })
  await mkdir(runtimeRoot)
  await writeFile(join(runtimeRoot, 'active.json'), '{"generation":"previous"}')
  await assert.rejects(runtime.ensure(), /Supplied Python is not ready:.*supplied_dependency/s)
  assert.match(runtime.status().error, /No uv or Python download was attempted/)
  assert.equal(await readFile(join(runtimeRoot, 'active.json'), 'utf8'), '{"generation":"previous"}')
  assert.equal((await readdir(runtimeRoot)).includes('binaries'), false)
  const environments = await readdir(join(runtimeRoot, 'environments'))
  assert.deepEqual(environments, [], 'failed staging is removed')
})

test('dependency preflight runs again for a cached supplied environment', realPython, async t => {
  const { runtime, runtimeRoot, modules, createRuntime } = await fixture(t)
  await runtime.ensure()
  await runtime.dispose()
  const active = await readFile(join(runtimeRoot, 'active.json'))
  await rm(join(modules, 'supplied_dependency.py'))
  const next = createRuntime({ pythonPath: python, pythonModulePaths: [modules] })
  await assert.rejects(next.ensure(), /supplied_dependency/)
  assert.deepEqual(await readFile(join(runtimeRoot, 'active.json')), active)
})

test('a mismatched bundled Core fails the supplied-Python preflight', realPython, async t => {
  const { runtime } = await fixture(t, { reportedVersion: 'wrong-core' })
  await assert.rejects(runtime.ensure(), /Core version or API mismatch/)
})

test('environment interpreter selection works and explicit config takes precedence', realPython, async t => {
  const { runtimeRoot, modules, createRuntime } = await fixture(t)
  const previous = process.env.OPENWRITE_PYTHON
  process.env.OPENWRITE_PYTHON = join(runtimeRoot, 'nonexistent-python')
  t.after(() => { if (previous === undefined) delete process.env.OPENWRITE_PYTHON; else process.env.OPENWRITE_PYTHON = previous })
  const explicit = createRuntime({ pythonPath: python, pythonModulePaths: [modules] })
  await explicit.ensure()
  await explicit.dispose()
  process.env.OPENWRITE_PYTHON = python
  const fromEnv = createRuntime({ pythonModulePaths: [modules] })
  assert.equal((await fromEnv.ensure()).baseUrl.startsWith('http://127.0.0.1:'), true)
})

test('supplied interpreter validation rejects command strings and relative dependency paths', async t => {
  const { runtimeRoot, createRuntime } = await fixture(t)
  for (const options of [{ pythonPath: 'python3 --flag' }, { pythonPath: join(runtimeRoot, 'python'), pythonModulePaths: ['relative'] }]) {
    const runtime = createRuntime(options)
    await assert.rejects(runtime.ensure(), /absolute/)
    await runtime.dispose()
  }
})

test('supplied setup can be cancelled without promoting partial state', async t => {
  const { runtimeRoot, createRuntime } = await fixture(t)
  let child, started
  const spawned = new Promise(resolve => { started = resolve })
  const runtime = createRuntime({ pythonPath: join(runtimeRoot, 'python'), spawn: (_command, _args, options) => {
    child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], options)
    child.once('spawn', started)
    return child
  } })
  const pending = assert.rejects(runtime.ensure(), { name: 'AbortError' })
  await spawned
  await runtime.cancel()
  await pending
  assert.equal(runtime.status().phase, 'cancelled')
  assert.ok(child.exitCode !== null || child.signalCode !== null)
  await assert.rejects(readFile(join(runtimeRoot, 'active.json')), { code: 'ENOENT' })
})
