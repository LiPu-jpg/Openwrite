import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Assert against the built module, and fail if it predates the source change so
// a stale build cannot make this gate pass.
const here = dirname(fileURLToPath(import.meta.url))
const built = join(here, '..', 'lib', 'host-llm.js')
assert.ok(existsSync(built), 'run `npm --prefix packages/openwrite-bridge run build` first')
assert.ok(readFileSync(built, 'utf8').includes('chat/completions'),
  'lib/host-llm.js is stale: rebuild packages/openwrite-bridge before running this test')
const { HostLlmRelay, newRelayToken, HOST_CURRENT_MODEL } = await import(built)

/** A host `llm` service that records what it was asked to do. */
function fakeLlm({ models = [], current } = {}) {
  const calls = []
  return {
    calls,
    listProviders: () => [
      { id: 'deepseek-official', name: 'DeepSeek' },
      { id: 'our-free-model', name: 'Our Free Model' },
    ],
    listModels: async provider => models.filter(entry => entry.provider === provider),
    stream(options) {
      calls.push(options)
      return (async function* () {
        yield { type: 'text-delta', index: 0, text: '你好' }
        yield { type: 'text-delta', index: 0, text: '，世界' }
        yield { type: 'usage', usage: { inputTokens: 11, outputTokens: 5, totalTokens: 16 } }
        yield { type: 'finish', reason: 'stop' }
      })()
    },
    current,
  }
}

async function withRelay(options, body) {
  const relay = new HostLlmRelay(options)
  await relay.listen()
  try { return await body(relay) } finally { await relay.close() }
}

test('the relay refuses a request without its machine token', async () => {
  await withRelay({ llm: fakeLlm(), token: 'secret-token' }, async relay => {
    const unauthorized = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: 'deepseek-official/deepseek-flash', messages: [{ role: 'user', content: 'hi' }] }),
    })
    assert.equal(unauthorized.status, 401)

    const wrongToken = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer wrong' },
      body: JSON.stringify({ model: 'deepseek-official/deepseek-flash', messages: [{ role: 'user', content: 'hi' }] }),
    })
    assert.equal(wrongToken.status, 401)

    const models = await fetch(relay.baseUrl() + '/models')
    assert.equal(models.status, 401)
  })
})

test('the relay answers the host model directory', async () => {
  const llm = fakeLlm({
    models: [
      { provider: 'deepseek-official', id: 'deepseek-flash', name: 'DeepSeek Flash' },
      { provider: 'our-free-model', id: 'vendor/Model-X', name: 'Model X' },
    ],
  })
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/models', { headers: { authorization: 'Bearer t' } })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.object, 'list')
    const ids = payload.data.map(entry => entry.id)
    assert.ok(ids.includes('deepseek-official/deepseek-flash'))
    assert.ok(ids.includes('our-free-model/vendor/Model-X'),
      'a model id that itself contains a slash must survive the provider/model split')
  })
})

test('a chat request reaches the host with the provider route split off', async () => {
  const llm = fakeLlm()
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({
        model: 'our-free-model/vendor/Model-X',
        messages: [
          { role: 'system', content: 'you are a novelist' },
          { role: 'user', content: 'write' },
        ],
        temperature: 0.3,
        max_tokens: 100,
      }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.choices[0].message.content, '你好，世界')
    assert.equal(payload.choices[0].finish_reason, 'stop')
    assert.equal(payload.usage.total_tokens, 16)

    assert.equal(llm.calls.length, 1)
    const call = llm.calls[0]
    assert.equal(call.provider, 'our-free-model')
    assert.equal(call.model, 'vendor/Model-X')
    assert.equal(call.temperature, 0.3)
    assert.equal(call.maxTokens, 100)
    const roles = call.messages.map(message => message.role)
    assert.deepEqual(roles, ['system', 'user'])
  })
})

test('the pseudo model resolves to whatever the host itself would use', async () => {
  const llm = fakeLlm()
  await withRelay({
    llm,
    token: 't',
    defaultSelection: () => ({ provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: 'max' }),
  }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({ model: HOST_CURRENT_MODEL, messages: [{ role: 'user', content: 'hi' }] }),
    })
    assert.equal(response.status, 200)
    assert.equal(llm.calls[0].provider, 'deepseek-official')
    assert.equal(llm.calls[0].model, 'deepseek-flash')
    assert.equal(llm.calls[0].reasoningEffort, 'max')
  })
})

test('a model without a provider route is rejected instead of guessed', async () => {
  await withRelay({ llm: fakeLlm(), token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({ model: 'deepseek-flash', messages: [{ role: 'user', content: 'hi' }] }),
    })
    assert.equal(response.status, 400)
  })
})

test('a streaming request is answered as server-sent events', async () => {
  const llm = fakeLlm()
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({ model: 'deepseek-official/deepseek-flash', messages: [{ role: 'user', content: 'hi' }], stream: true }),
    })
    assert.equal(response.status, 200)
    assert.match(String(response.headers.get('content-type')), /text\/event-stream/)
    const text = await response.text()
    assert.ok(text.includes('"content":"你好"'))
    assert.ok(text.includes('"content":"，世界"'))
    assert.ok(text.trimEnd().endsWith('data: [DONE]'))
  })
})

test('an adapter that only closes its block still reaches the client', async () => {
  // The host's assembler treats `block-end` as the authoritative content: an
  // adapter may stream deltas, close the block, or do both. Whichever it did,
  // the text must arrive exactly once.
  const llm = {
    ...fakeLlm(),
    stream: () => (async function* () {
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: '只有整块' } }
      yield { type: 'finish', reason: 'stop' }
    })(),
  }
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({ model: 'deepseek-official/deepseek-flash', messages: [{ role: 'user', content: 'hi' }] }),
    })
    const payload = await response.json()
    assert.equal(payload.choices[0].message.content, '只有整块')
  })
})

test('a closed block is not counted twice when deltas already carried it', async () => {
  const llm = {
    ...fakeLlm(),
    stream: () => (async function* () {
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: '增量' }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: '增量' } }
      yield { type: 'finish', reason: 'stop' }
    })(),
  }
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({ model: 'deepseek-official/deepseek-flash', messages: [{ role: 'user', content: 'hi' }] }),
    })
    const payload = await response.json()
    assert.equal(payload.choices[0].message.content, '增量')
  })
})

test('a provider failure is answered as an error, not as an empty completion', async () => {
  // The host reports a failed call as a terminal finish chunk carrying the
  // provider's own words. Answering 200 with empty content would hide it.
  const llm = {
    ...fakeLlm(),
    stream: () => (async function* () {
      yield { type: 'finish', reason: { kind: 'error', failure: { message: '上游通道未启用', code: 'EGRESS_DISABLED', status: 503 } } }
    })(),
  }
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({ model: 'our-free-model/vendor/Model-X', messages: [{ role: 'user', content: 'hi' }] }),
    })
    // The provider's own status travels with the failure.
    assert.equal(response.status, 503)
    const payload = await response.json()
    assert.equal(payload.error.message, '上游通道未启用')
    assert.equal(payload.error.code, 'EGRESS_DISABLED')
  })
})

test('"no reasoning" in the request body becomes a host reasoning effort', async () => {
  // The Core cannot pass `reasoning_effort` through LiteLLM (drop_params
  // removes it for a custom model name), so it expresses "no reasoning" the
  // way the OpenAI body does. The host speaks reasoning effort: without this
  // translation a flash model keeps reasoning, burns the whole output budget
  // on it, and answers with an empty "length" stop.
  const llm = fakeLlm()
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({
        model: 'deepseek-official/deepseek-flash',
        messages: [{ role: 'user', content: 'hi' }],
        thinking: { type: 'disabled' },
      }),
    })
    assert.equal(response.status, 200)
    assert.equal(llm.calls.length, 1)
    assert.equal(llm.calls[0].reasoningEffort, 'off')
  })
})

test('an explicit reasoning effort still wins when the body does not disable reasoning', async () => {
  const llm = fakeLlm()
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({
        model: 'deepseek-official/deepseek-flash',
        messages: [{ role: 'user', content: 'hi' }],
        reasoning_effort: 'high',
      }),
    })
    assert.equal(response.status, 200)
    assert.equal(llm.calls[0].reasoningEffort, 'high')
  })
})

test('a model that refuses the effort is retried once without it', async () => {
  // Asking for "no reasoning" must never turn into a failed call: a model
  // that declares no reasoning support rejects an explicit effort.
  const calls = []
  const llm = {
    ...fakeLlm(),
    stream(options) {
      calls.push(options)
      const attempt = calls.length
      return (async function* () {
        if (options.reasoningEffort !== undefined) {
          yield {
            type: 'finish',
            reason: {
              kind: 'error',
              failure: {
                message: 'model "vendor/x" does not support reasoning effort "off"',
                code: 'UNSUPPORTED_REASONING_EFFORT',
                status: 400,
              },
            },
          }
          return
        }
        yield { type: 'text-delta', index: 0, text: 'ok' }
        yield { type: 'finish', reason: 'stop' }
        assert.ok(attempt === 2, 'the retry is the second call')
      })()
    },
  }
  await withRelay({ llm, token: 't' }, async relay => {
    const response = await fetch(relay.baseUrl() + '/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer t' },
      body: JSON.stringify({
        model: 'our-free-model/vendor/Model-X',
        messages: [{ role: 'user', content: 'hi' }],
        thinking: { type: 'disabled' },
      }),
    })
    assert.equal(response.status, 200)
    const payload = await response.json()
    assert.equal(payload.choices[0].message.content, 'ok')
    assert.equal(calls.length, 2)
    assert.equal(calls[0].reasoningEffort, 'off')
    assert.equal(calls[1].reasoningEffort, undefined)
  })
})

test('the relay token is unguessable', () => {
  assert.notEqual(newRelayToken(), newRelayToken())
  assert.equal(newRelayToken().length, 64)
})

test('the model directory answers while one provider is still loading', async () => {
  // A plugin that registers its own providers resolves its directory over the
  // network the first time it is asked, so one provider can stay silent while
  // the rest are ready. The directory must still answer with the providers
  // that are ready: the Core behind this relay gives up after ten seconds,
  // and an unanswered directory reaches the user as an empty model list.
  const llm = {
    listProviders: () => [
      { id: 'slow-provider', name: 'Slow' },
      { id: 'deepseek-official', name: 'DeepSeek' },
    ],
    listModels: async provider => {
      if (provider === 'slow-provider') return new Promise(() => {})
      return [{ provider, id: 'deepseek-flash', name: 'DeepSeek Flash' }]
    },
    stream: () => (async function* () {})(),
  }
  await withRelay({ llm, token: 't', providerDeadlineMs: 50 }, async relay => {
    const started = Date.now()
    const response = await fetch(relay.baseUrl() + '/models', { headers: { authorization: 'Bearer t' } })
    const elapsed = Date.now() - started
    assert.equal(response.status, 200)
    assert.ok(elapsed < 3000, `the directory answered in ${elapsed}ms; a provider that never answers must not hold it`)
    const payload = await response.json()
    const ids = payload.data.map(entry => entry.id)
    assert.ok(ids.includes('deepseek-official/deepseek-flash'),
      'the providers that did answer must still be listed')
  })
})

test('the model directory asks every provider at once', async () => {
  // Asking one provider after another made the answer as slow as the sum of
  // every plugin's first answer. The host's own catalog asks them in parallel.
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
  const llm = {
    listProviders: () => [
      { id: 'first', name: 'First' },
      { id: 'second', name: 'Second' },
    ],
    listModels: async provider => {
      await wait(150)
      return [{ provider, id: `${provider}-model`, name: provider }]
    },
    stream: () => (async function* () {})(),
  }
  await withRelay({ llm, token: 't', providerDeadlineMs: 5000 }, async relay => {
    const started = Date.now()
    const response = await fetch(relay.baseUrl() + '/models', { headers: { authorization: 'Bearer t' } })
    const elapsed = Date.now() - started
    assert.equal(response.status, 200)
    assert.ok(elapsed < 250, `two providers took ${elapsed}ms; they must be asked at once, not one after another`)
    const payload = await response.json()
    assert.equal(payload.data.length, 2)
  })
})
