import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readdir, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../plugin.mjs'
import { legacyPresetIds, presetDefinition } from '../preset-definition.mjs'

test('released versioned identities remain resolvable after migrating sessions without preset directories', async () => {
  const { version } = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  assert.ok(legacyPresetIds.includes(`openwrite-${version.replaceAll('.', '-')}`),
    'record every new release identity in the durable alias list before publishing')
})

test('upgrade resolves retired preset identities without rewriting session data or custom definitions', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-upgrade-resume-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  const session = join(home, 'historical-session.json')
  const original = JSON.stringify({ agentPreset: 'openwrite-0-2-24', message: 'openwrite-0-2-24' })
  await writeFile(session, original)
  const definitions = new Map([['openwrite-0-2-23', { id: 'openwrite-0-2-23', name: 'Author preset' }]])
  const disposers = []
  let activation
  await apply({
    effect: factory => disposers.push(factory()),
    inject: (_names, callback) => {
      activation = callback({ agentPresets: {
        async readDocument(id) {
          if (definitions.has(id)) return definitions.get(id)
          throw Object.assign(new Error('missing'), { code: 'agent-preset/not-found' })
        },
        async register(definition) {
          assert.equal(definitions.has(definition.id), false)
          definitions.set(definition.id, definition)
          return () => definitions.delete(definition.id)
        },
      } })
    },
  })
  const unregister = []
  for await (const dispose of activation) unregister.push(dispose)
  for (const id of ['openwrite', 'openwrite-0-2-1', 'openwrite-0-2-24', 'openwrite-0-2-25', 'openwrite-0-2-26']) {
    assert.ok(definitions.get(id).plugins.length > 10, `session preset ${id} resolves`)
  }
  assert.equal(definitions.get('openwrite-0-2-23').name, 'Author preset')
  assert.equal(await readFile(session, 'utf8'), original)
  assert.equal((await presetDefinition('0.2.26', true)).id, (await presetDefinition('0.3.0', true)).id)
  for (const dispose of unregister.reverse()) await dispose()
  assert.deepEqual([...definitions.keys()], ['openwrite-0-2-23'])
  await disposers[0]()
})

test('versioned preset survives host shutdown for legacy session resume and preserves authored files', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-preset-test-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  const disposers = []
  const ctx = { effect: factory => disposers.push(factory()), inject() {} }
  await Promise.all([apply(ctx), apply(ctx)])
  const names = await readdir(join(home, '.agent-presets'))
  assert.equal(names.length, 1)
  assert.match(names[0], /^[a-z0-9][a-z0-9-]*$/)
  const dir = join(home, '.agent-presets', names[0])
  await disposers.shift()()
  await readFile(join(dir, 'agent.cordis.yml'))
  await disposers.shift()()
  await readFile(join(dir, 'agent.cordis.yml'))
  await rm(dir, { recursive: true })
  await mkdir(dir)
  await writeFile(join(dir, 'author.txt'), 'unmanaged custom preset')
  await assert.rejects(apply(ctx), /ownership marker/)
  assert.deepEqual(await readdir(dir), ['author.txt'])
  await rm(dir, { recursive: true })
  await apply(ctx)
  await writeFile(join(dir, 'author-note.txt'), 'keep my modifications')
  await disposers.shift()()
  assert.equal(await readFile(join(dir, 'author-note.txt'), 'utf8'), 'keep my modifications')
})

test('0.2 registers a stable preset with package skills and owns its disposer', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-preset-registry-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  const disposers = []
  let registration
  let unregistered = false
  let activation
  await apply({
    effect: factory => disposers.push(factory()),
    inject: (names, callback) => {
      assert.deepEqual(names, ['agentPresets'])
      activation = callback({ agentPresets: { async register(definition) {
        registration = definition
        return () => { unregistered = true }
      } } })
    },
  })
  const installed = await activation.next()
  assert.equal(registration.id, 'openwrite')
  const flatten = rows => rows.flatMap(row => [row, ...(row.group ? flatten(row.config) : [])])
  const rows = flatten(registration.plugins)
  assert.ok(rows.some(row => row.name === '@deepseek-ai/dsh-workflow-ptc'))
  assert.ok(!rows.some(row => row.name === '@deepseek-ai/dsh-workflow-worker-thread'))
  const skills = rows.find(row => row.name === '@deepseek-ai/dsh-skill-filesystem').config.customSkillDirs
  await readFile(join(skills[0], 'progress', 'SKILL.md'))
  installed.value()
  await activation.return()
  assert.equal(unregistered, true)
  await disposers[0]()
})
