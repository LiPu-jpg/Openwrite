import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const built = join(here, '..', 'lib', 'host-web.js')
assert.ok(existsSync(built), 'run `npm --prefix packages/openwrite-bridge run build` first')
assert.ok(readFileSync(built, 'utf8').includes('bocha'), 'lib/host-web.js is stale: rebuild the bridge first')

const { HostWebRelay } = await import(built)

function fakeWeb() {
  const calls = []
  return {
    calls,
    async search(request, signal) {
      calls.push({ kind: 'search', request, aborted: signal?.aborted === true })
      return {
        content: 'answer',
        sources: [
          { url: 'https://example.com/a', title: 'A', snippet: 'first' },
          { url: 'https://example.com/b', title: 'B' },
        ],
        truncated: false,
      }
    },
    async fetch(request, signal) {
      calls.push({ kind: 'fetch', request, aborted: signal?.aborted === true })
      return { url: request.url, statusCode: 200, body: { kind: 'text', content: 'page text' }, truncated: true }
    },
  }
}

async function withRelay(web, body) {
  const relay = new HostWebRelay({ web, token: 'test-token' })
  await relay.listen()
  try { return await body(relay) } finally { await relay.close() }
}

test('the host web relay requires its machine token', async () => {
  const web = fakeWeb()
  await withRelay(web, async relay => {
    const response = await fetch(relay.baseUrl() + '/search', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ query: 'x' }),
    })
    assert.equal(response.status, 401)
    assert.equal(web.calls.length, 0)
  })
})

test('search returns normalized sources and forwards maxResults', async () => {
  const web = fakeWeb()
  await withRelay(web, async relay => {
    const response = await fetch(relay.baseUrl() + '/search', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${relay.token()}` },
      body: JSON.stringify({ query: 'hello', maxResults: 3 }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.deepEqual(payload.sources.map(source => source.url), ['https://example.com/a', 'https://example.com/b'])
    assert.equal(payload.content, 'answer')
    assert.equal(web.calls[0].request.query, 'hello')
    assert.equal(web.calls[0].request.maxResults, 3)
  })
})

test('the Bocha-compatible endpoint maps host sources into the provider response', async () => {
  const web = fakeWeb()
  await withRelay(web, async relay => {
    const response = await fetch(relay.baseUrl() + '/bocha', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${relay.token()}` },
      body: JSON.stringify({ query: 'hello', count: 2 }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.code, 200)
    assert.deepEqual(payload.data.webPages.value.map(item => item.name), ['A', 'B'])
    assert.equal(payload.data.webPages.value[0].snippet, 'first')
  })
})

test('fetch returns the normalized body and honors a non-2xx result', async () => {
  const web = fakeWeb()
  await withRelay(web, async relay => {
    const response = await fetch(relay.baseUrl() + '/fetch', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${relay.token()}` },
      body: JSON.stringify({ url: 'https://example.com/a' }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.deepEqual(payload, {
      url: 'https://example.com/a', statusCode: 200,
      body: { kind: 'text', content: 'page text' }, truncated: true,
    })
  })
})
