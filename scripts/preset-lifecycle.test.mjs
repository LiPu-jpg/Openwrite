import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readdir, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../plugin.mjs'

test('versioned preset supports two hosts and removes only unmodified package files', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-preset-test-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  const disposers = []
  const ctx = { effect: factory => disposers.push(factory()) }
  await Promise.all([apply(ctx), apply(ctx)])
  const names = await readdir(join(home, '.agent-presets'))
  assert.equal(names.length, 1)
  assert.match(names[0], /^[a-z0-9][a-z0-9-]*$/)
  const dir = join(home, '.agent-presets', names[0])
  await disposers.shift()()
  await readFile(join(dir, 'agent.cordis.yml'))
  await disposers.shift()()
  assert.deepEqual(await readdir(join(home, '.agent-presets')), [])
  await apply(ctx)
  await writeFile(join(dir, 'author-note.txt'), 'keep my modifications')
  await disposers.shift()()
  assert.equal(await readFile(join(dir, 'author-note.txt'), 'utf8'), 'keep my modifications')
})
