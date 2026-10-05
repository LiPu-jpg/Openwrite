import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readdir, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../plugin.mjs'

test('versioned preset supports two hosts and removes only unmodified package files', async t => {
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
  assert.deepEqual(await readdir(join(home, '.agent-presets')), [])
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

test('0.2 registers a versioned preset with package skills and owns its disposer', async t => {
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
  const version = JSON.parse(await readFile(new URL('../package.json', import.meta.url))).version
  assert.equal(registration.id, `openwrite-${version.replace(/[^a-z0-9-]/g, '-')}`)
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
