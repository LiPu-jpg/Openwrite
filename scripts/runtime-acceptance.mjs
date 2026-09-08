// Exercise process lifecycle against the installed wheel, using only isolated state.
import assert from 'node:assert/strict'
import { readFile, writeFile, cp, mkdir, rm } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'

export async function acceptRuntime(installed, home, temporary) {
  const { ManagedRuntime, stopOwnedProcess } = await import(pathToFileURL(join(installed, 'packages/openwrite-bridge/lib/managed-runtime.js')).href)
  const artifacts = join(installed, 'release')
  const root = join(home, 'openwrite')
  const first = new ManagedRuntime(root, artifacts)
  const second = new ManagedRuntime(root, artifacts)
  try {
    const [a, b] = await Promise.all([first.ensure(), second.ensure()])
    const native = spawnSync(first.child.spawnfile, ['-I', '-c', 'import onnxruntime, fastembed; from cryptography.hazmat.backends.openssl.backend import backend; assert "CPUExecutionProvider" in onnxruntime.get_available_providers(); assert backend.openssl_version_text()'], { cwd: root, encoding: 'utf8', timeout: 60_000 })
    assert.equal(native.status, 0, `Native dependency import failed: ${native.stderr}`)
    assert.notEqual(a.baseUrl, b.baseUrl, 'instances choose separate free ports')
    assert.equal((await fetch(a.baseUrl + '/api/health')).status, 401)
    assert.equal((await fetch(a.baseUrl + '/api/project/init', { method: 'POST', headers: { 'X-OpenWrite-Studio': '1' } })).status, 401)
    const health = await fetch(a.baseUrl + '/api/health', { headers: { Authorization: 'Bearer ' + a.token } })
    assert.equal((await health.json()).contract_version, 1)
    await stopOwnedProcess(first.child)
    assert.equal(first.status().phase, 'error')
    const recovered = await first.ensure()
    assert.equal(first.status().phase, 'ready')
    assert.equal((await fetch(recovered.baseUrl + '/api/health', { headers: { Authorization: 'Bearer ' + b.token } })).status, 401)
    await first.dispose()
    assert.equal(second.status().phase, 'ready', 'one plugin cannot stop another instance')
    assert.equal((await fetch(b.baseUrl + '/api/health', { headers: { Authorization: 'Bearer ' + b.token } })).status, 200)
    const previous = await readFile(join(root, 'active.json'), 'utf8')
    const bad = join(temporary, 'corrupt-release')
    await mkdir(bad)
    const manifest = JSON.parse(await readFile(join(artifacts, 'runtime-manifest.json')))
    await cp(join(artifacts, 'runtime-manifest.json'), join(bad, 'runtime-manifest.json'))
    await writeFile(join(bad, manifest.wheel.file), 'interrupted upgrade')
    const failed = new ManagedRuntime(root, bad)
    await assert.rejects(failed.ensure(), /校验失败/)
    assert.equal(await readFile(join(root, 'active.json'), 'utf8'), previous)
    await failed.dispose()
    await rm(bad, { recursive: true })
    const rollback = new ManagedRuntime(root, artifacts)
    try { await rollback.ensure(); assert.equal(rollback.status().phase, 'ready') }
    finally { await rollback.dispose() }
    return ['native-dependency-load', 'multiple-instances', 'dynamic-ports', 'backend-auth', 'crash-recovery', 'owned-process-cleanup', 'failed-upgrade-preserves-active', 'rollback']
  } finally { await first.dispose(); await second.dispose() }
}
