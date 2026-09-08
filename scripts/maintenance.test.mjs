import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { migrate, diagnose } from './maintenance.mjs'

test('migration backs up authored presets and changes only known bundle registrations', async () => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-migration-'))
  try {
    await mkdir(join(home, 'profiles/web'), { recursive: true })
    await mkdir(join(home, '.agent-presets/custom'), { recursive: true })
    await writeFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'author-owned')
    const file = join(home, 'profiles/web/package.json')
    const original = JSON.stringify({ dependencies: { other: '1', '@dsh-novel/openwrite-bridge': 'file:/old/source' }, dsh: { profile: { bundles: ['other', '@dsh-novel/openwrite-bridge', 'dsh-openwrite'] } } })
    await writeFile(file, original)
    assert.equal((await migrate(home, 'web')).changed, false)
    assert.equal(await readFile(file, 'utf8'), original)
    const result = await migrate(home, 'web', true)
    assert.equal(await readFile(join(result.backup, 'package.json'), 'utf8'), original)
    assert.equal(await readFile(join(result.backup, '.agent-presets/custom/agent.cordis.yml'), 'utf8'), 'author-owned')
    assert.deepEqual(JSON.parse(await readFile(file)).dsh.profile.bundles, ['other', 'dsh-openwrite'])
    assert.equal(await readFile(join(home, '.agent-presets/custom/agent.cordis.yml'), 'utf8'), 'author-owned')
    assert.equal((await migrate(home, 'web', true)).changed, false)
    assert.equal((await diagnose(home, 'web')).installed, true)
    await assert.rejects(migrate(home, '../escape', true), /Invalid profile/)
  } finally { await rm(home, { recursive: true, force: true }) }
})
