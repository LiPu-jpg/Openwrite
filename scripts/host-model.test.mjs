/**
 * The host-model route: what OpenWrite tells the host's settings dialog about
 * the model dsh itself would use.
 *
 * The route is exercised through the plugin's own `apply()`, so the test covers
 * the real registration and the real authentication fence — the two things a
 * browser-visible route must not get wrong.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

/**
 * A cordis-shaped context that records the web routes the plugin registers.
 * The agentPresets generator is never iterated, exactly as the host leaves it
 * when that service is absent.
 */
function fakeContext(services = {}) {
  const routes = []
  const webServer = { register: route => { routes.push(route); return () => {} } }
  const webCtx = {
    get: name => services[name],
    effect: fn => { fn(); return () => {} },
    webServer,
  }
  return {
    routes,
    get: name => services[name],
    effect: fn => { fn(); return () => {} },
    inject: (_names, fn) => { fn(webCtx); return () => {} },
  }
}

/** A Node response that records what the handler wrote. */
function fakeResponse() {
  const state = { status: 0, body: '' }
  return {
    state,
    writeHead(code) { state.status = code; return this },
    end(payload) { state.body = String(payload ?? ''); return this },
  }
}

/** The host-model route as registered by the plugin. */
async function hostModelRoute(services = {}) {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-host-model-'))
  const previous = process.env['DSH_HOME']
  process.env['DSH_HOME'] = home
  try {
    // A host with no `connection` service answers 503 — the route is closed
    // rather than open. The default here is the authenticated case: the
    // fence exists and lets this request through.
    const ctx = fakeContext({ connection: { requestRejection: () => undefined }, ...services })
    const { apply } = await import('../plugin.mjs')
    await apply(ctx)
    const route = ctx.routes.find(entry => entry.path === '/studio-panel/host-model')
    assert.ok(route, 'the host-model route must be registered')
    return route
  } finally {
    if (previous === undefined) delete process.env['DSH_HOME']
    else process.env['DSH_HOME'] = previous
    await rm(home, { recursive: true, force: true })
  }
}

test('the route reports the host selection without a key', async () => {
  const route = await hostModelRoute({
    agentDefaultModel: { currentSelection: () => ({ provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: 'max' }) },
  })
  const res = fakeResponse()
  await route.handler({ method: 'GET', headers: {} }, res)
  assert.equal(res.state.status, 200)
  const payload = JSON.parse(res.state.body)
  assert.deepEqual(payload, { available: true, provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: 'max' })
  // The selection is a browser-visible fact; a key must never travel with it.
  assert.equal(JSON.stringify(payload).includes('api_key'), false)
})

test('a host without the service answers unconfigured, not broken', async () => {
  const route = await hostModelRoute()
  const res = fakeResponse()
  await route.handler({ method: 'GET', headers: {} }, res)
  assert.equal(res.state.status, 200)
  assert.equal(JSON.parse(res.state.body).available, false)
})

test('a selection service that throws answers unconfigured', async () => {
  const route = await hostModelRoute({
    agentDefaultModel: { currentSelection: () => { throw new Error('not configured') } },
  })
  const res = fakeResponse()
  await route.handler({ method: 'GET', headers: {} }, res)
  assert.equal(res.state.status, 200)
  assert.equal(JSON.parse(res.state.body).available, false)
})

test('a half-filled selection names no model', async () => {
  const route = await hostModelRoute({
    agentDefaultModel: { currentSelection: () => ({ provider: 'deepseek-official', model: '' }) },
  })
  const res = fakeResponse()
  await route.handler({ method: 'GET', headers: {} }, res)
  const payload = JSON.parse(res.state.body)
  assert.equal(payload.available, false)
  assert.equal(payload.model, '')
})

test('the route sits behind the host browser-authentication fence', async () => {
  const route = await hostModelRoute({
    agentDefaultModel: { currentSelection: () => ({ provider: 'p', model: 'm' }) },
    connection: { requestRejection: () => 401 },
  })
  const res = fakeResponse()
  await route.handler({ method: 'GET', headers: {} }, res)
  assert.equal(res.state.status, 401)
  assert.equal(JSON.parse(res.state.body).code, 'AUTHENTICATION_REQUIRED')
  // The selection must not leak into the rejection body.
  assert.equal(res.state.body.includes('"m"'), false)
})

test('the route refuses a write', async () => {
  const route = await hostModelRoute()
  const res = fakeResponse()
  await route.handler({ method: 'POST', headers: {} }, res)
  assert.equal(res.state.status, 405)
})
