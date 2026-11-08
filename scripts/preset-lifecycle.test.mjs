import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readdir, readFile, stat, symlink, writeFile, rm, utimes } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { zstdCompressSync } from 'node:zlib'
import { apply } from '../plugin.mjs'
import { legacyAliasName, legacyPresetIds, presetDefinition, referencedPresetIds } from '../preset-definition.mjs'
/** Write one stored session log the way the host persistence backend does. */
async function writeSessionLog(home, id, agentPreset) {
  const directory = join(home, 'sessions', '_no-cwd', id)
  await mkdir(directory, { recursive: true })
  const header = JSON.stringify({ type: 'session', version: 4, id, createdAt: 1, delegationDepth: 0, isSeeded: false, ...(agentPreset === undefined ? {} : { agentPreset }) }) + '\n'
  const event = JSON.stringify({ type: 'user/message', version: 4, seq: 0, time: 1, data: {} }) + '\n'
  await writeFile(join(directory, 'session.v4.jsonl.zstd'), Buffer.concat([
    zstdCompressSync(Buffer.from(header, 'utf8')),
    zstdCompressSync(Buffer.from(event, 'utf8')),
  ]))
  return join(directory, 'session.v4.jsonl.zstd')
}

/** Run the plugin against a stubbed preset registry and collect registrations. */
async function registerPresets(home, definitions = new Map()) {
  const disposers = []
  let activation
  const stubWebServer = { effect: factory => factory(), webServer: { register: () => () => {} } }
  await apply({
    effect: factory => disposers.push(factory()),
    inject: (names, callback) => {
      if (names[0] === 'agentPresets') {
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
        return
      }
      callback(stubWebServer)
    },
  })
  const unregister = []
  for await (const dispose of activation) unregister.push(dispose)
  // Disposing drops every registration this plugin owns, so the returned map
  // is a snapshot of what the host would list while the plugin is active.
  return { definitions, unregister, disposeEffects: async () => { for (const dispose of unregister.reverse()) await dispose(); await disposers[0]() } }
}

test('released versioned identities remain resolvable after migrating sessions without preset directories', async () => {
  const { version } = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  assert.ok(legacyPresetIds.includes(`openwrite-${version.replaceAll('.', '-')}`),
    'record every new release identity in the durable alias list before publishing')
})

test('preset aliases follow the sessions that reference them', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-alias-scan-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  await writeSessionLog(home, 'session-a', 'openwrite-0-2-24')
  await writeSessionLog(home, 'session-b', 'openwrite-0-2-26')
  await writeSessionLog(home, 'session-c', 'standard')
  await writeSessionLog(home, 'session-d')
  const { definitions, disposeEffects } = await registerPresets(home)
  assert.equal(definitions.get('openwrite').id, 'openwrite')
  assert.deepEqual([...definitions.keys()].sort(), ['openwrite', 'openwrite-0-2-24', 'openwrite-0-2-26'])
  const alias = definitions.get('openwrite-0-2-24')
  assert.equal(alias.name, legacyAliasName('openwrite-0-2-24', 'OpenWrite 创作'))
  assert.equal(alias.name, 'OpenWrite 创作（旧版 0.2.24 · 仅用于恢复历史会话）')
  assert.equal(alias.order, 1000)
  assert.ok(alias.plugins.length > 10, 'an alias resolves the full preset')
  await disposeEffects()
  assert.deepEqual([...definitions.keys()], [], 'disposing drops every registration this plugin owns')
})

test('unreferenced release identities stay out of the preset selector', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-alias-clean-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  await writeSessionLog(home, 'session-a', 'standard')
  const { definitions } = await registerPresets(home)
  assert.deepEqual([...definitions.keys()], ['openwrite'])
})

test('an unreadable session store keeps the durable alias list', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-alias-fallback-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  // A file where the session root belongs makes every listing fail.
  await writeFile(join(home, 'sessions'), 'not a directory')
  const { definitions } = await registerPresets(home)
  const { version } = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  const current = `openwrite-${version.replaceAll('.', '-')}`
  for (const id of legacyPresetIds) {
    if (id === current) continue
    assert.ok(definitions.get(id), `${id} stays resumable`)
  }
  assert.equal(definitions.size, legacyPresetIds.length)
})

test('the alias cache re-derives only when the session store changes', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-alias-cache-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  const log = await writeSessionLog(home, 'session-a', 'openwrite-0-2-24')
  assert.deepEqual([...(await referencedPresetIds(home))].sort(), ['openwrite-0-2-24'])
  const cached = JSON.parse(await readFile(join(home, 'openwrite', 'preset-aliases.json'), 'utf8'))
  assert.deepEqual(cached.ids, ['openwrite-0-2-24'])
  // A same-second swap (delete one log, add another) must not be mistaken for an
  // unchanged store: the digest covers every log, so the new id is derived and
  // the deleted one does not linger.
  const stored = await stat(log)
  const added = await writeSessionLog(home, 'session-b', 'openwrite-0-2-27')
  await utimes(added, stored.atime, stored.mtime)
  assert.deepEqual([...(await referencedPresetIds(home))].sort(), ['openwrite-0-2-24', 'openwrite-0-2-27'])
  const replaced = await writeSessionLog(home, 'session-c', 'openwrite-0-2-25')
  await rm(added)
  await utimes(replaced, stored.atime, stored.mtime)
  assert.deepEqual([...(await referencedPresetIds(home))].sort(), ['openwrite-0-2-24', 'openwrite-0-2-25'])
  // A torn log changes the digest and is dropped rather than silently kept.
  await writeFile(log, 'torn')
  await utimes(log, stored.atime, stored.mtime)
  assert.deepEqual([...(await referencedPresetIds(home))].sort(), ['openwrite-0-2-25'])
})

test('upgrade resolves retired preset identities without rewriting session data or custom definitions', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-upgrade-resume-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  await writeSessionLog(home, 'session-legacy', 'openwrite-0-2-24')
  const session = join(home, 'sessions', '_no-cwd', 'session-legacy', 'session.v4.jsonl.zstd')
  const original = await readFile(session)
  const definitions = new Map([['openwrite-0-2-23', { id: 'openwrite-0-2-23', name: 'Author preset' }]])
  const { disposeEffects } = await registerPresets(home, definitions)
  for (const id of ['openwrite', 'openwrite-0-2-24']) {
    assert.ok(definitions.get(id).plugins.length > 10, `session preset ${id} resolves`)
  }
  assert.equal(definitions.get('openwrite-0-2-23').name, 'Author preset')
  assert.deepEqual(await readFile(session), original, 'the session log is read, never rewritten')
  assert.equal((await presetDefinition('0.2.26', true)).id, (await presetDefinition('0.3.0', true)).id)
  await disposeEffects()
  assert.deepEqual([...definitions.keys()], ['openwrite-0-2-23'])
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
  const injections = []
  await apply({
    effect: factory => disposers.push(factory()),
    inject: (names, callback) => {
      injections.push([...names])
      if (names[0] !== 'agentPresets') return callback({ effect: factory => factory(), webServer: { register: () => () => {} } })
      activation = callback({ agentPresets: { async register(definition) {
        registration = definition
        return () => { unregistered = true }
      } } })
    },
  })
  assert.deepEqual(injections, [['agentPresets'], ['webServer']])
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

/** One temporary DSH home with an installed host package. */
async function companionHome() {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-preset-companion-'))
  const directory = join(home, 'profiles', 'web')
  await mkdir(join(directory, 'node_modules', '@deepseek-ai', 'dsh'), { recursive: true })
  const bundles = ['@deepseek-ai/dsh-base', 'dsh-openwrite']
  await writeFile(join(directory, 'package.json'), JSON.stringify({ name: 'openwrite-web', private: true,
    dsh: { profile: { bundles } } }) + '\n')
  await writeFile(join(directory, 'node_modules', '@deepseek-ai', 'dsh', 'package.json'),
    JSON.stringify({ name: '@deepseek-ai/dsh', version: '0.2.1-rc.5' }) + '\n')
  return home
}

test('the preset mounts dsh-ops only when the companion can serve the host', async t => {
  const home = await companionHome()
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  assert.equal((await presetDefinition('0.2.29', true)).plugins.some(row => row.id === 'openwrite-ops'), false)
  // The companion is installed but its declared range excludes this host line.
  const directory = join(home, 'profiles', 'web')
  await mkdir(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration'), { recursive: true })
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'package.json'),
    JSON.stringify({ name: 'dsh-ops', version: '0.5.0-alpha3', exports: { './integration': './lib/integration/index.js' }, peerDependencies: { '@deepseek-ai/dsh': '>=0.2.2-0 <0.3.0-0' } }) + '\n')
  await writeFile(join(directory, 'node_modules', 'dsh-ops', 'lib', 'integration', 'index.js'),
    'export function integration(options) { return { name: "dsh-ops-integration", apply: () => {}, options } }\n')
  await writeFile(join(directory, 'package.json'), JSON.stringify({ name: 'openwrite-web', private: true,
    dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', 'dsh-openwrite', 'dsh-ops'] } } }) + '\n')
  assert.equal((await presetDefinition('0.2.29', true)).plugins.some(row => row.id === 'openwrite-ops'), false,
    'a companion the host would reject must not be mounted')
  // The same companion is usable on the host its range covers.
  const covered = await presetDefinition('0.2.29', true, { hostVersion: '0.2.2-alpha.3' })
  const ops = covered.plugins.find(row => row.id === 'openwrite-ops')
  assert.equal(ops?.name, 'dsh-openwrite/ops-integration')
})

// The row being inserted is only half the contract: the options we hand dsh-ops
// decide which tools appear. A regression that dropped `files: true` or flipped
// `replaceOfficial` would silently change the tool surface while every existing
// test still passed, because none of them looked at the options.
// The row being inserted is only half the contract: the options handed to
// dsh-ops decide which tools appear. `files: true` mounts the bounded file
// tools, `replaceOfficial: false` keeps the official ones, `shell: false` keeps
// a shell out of the OpenWrite preset. A regression in any of them silently
// changes the tool surface while every other test still passes.
//
// The options are asserted against the integration module's source rather than
// by importing it: `dsh-ops/integration` resolves from the real profile, not
// from this checkout, so a runtime import here would exercise the wrong module.
test('the ops integration passes the options that decide the tool surface', async t => {
  const source = await readFile(new URL('../presets/openwrite/ops-integration.mjs', import.meta.url), 'utf8')

  // Parse the literal options object out of the `integration({ ... })` call.
  // Matching `name: value` anywhere in the file would hit the prose comment
  // above it first, which says the opposite of what the code does.
  const call = source.match(/integration\(\s*\{([\s\S]*?)\}\s*\)/)
  assert.ok(call, 'ops-integration.mjs must call integration({ ... })')
  const options = new Function(`return {${call[1]}}`)()
  const option = (name, expected) => {
    assert.ok(name in options, `ops-integration.mjs must pass ${name}`)
    assert.equal(options[name], expected, `${name} must stay ${expected}`)
  }

  option('preset', 'openwrite')
  option('files', true)
  option('discovery', true)
  option('presentation', 'native')
  option('replaceOfficial', false)
  option('shell', false)

  // And the module must stay defensive: a companion that changed its entry
  // between detection and load has to degrade to a no-op row.
  assert.match(source, /catch/, 'the integration import must stay defensive')
  assert.match(source, /integration unavailable/, 'the degradation path must stay labelled')
})

test('editor noise and foreign files do not brick the managed preset', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-preset-noise-'))
  const previous = process.env.DSH_HOME
  process.env.DSH_HOME = home
  t.after(async () => { if (previous === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = previous; await rm(home, { recursive: true, force: true }) })
  const disposers = []
  const ctx = () => ({ effect: factory => disposers.push(factory()), inject() {} })
  await apply(ctx())
  const directory = join(home, '.agent-presets')
  const target = join(directory, (await readdir(directory))[0])
  await writeFile(join(target, 'agent.cordis.yml.bak'), 'editor backup')
  await writeFile(join(target, '.DS_Store'), 'os artifact')
  await symlink('/definitely/not/here', join(target, 'dangling-link'))
  await writeFile(join(target, 'author-note.txt'), 'mine')
  // None of these is a modification of the package tree, so activation proceeds.
  await apply(ctx())
  const { definitions } = await registerPresets(home)
  assert.equal(definitions.get('openwrite').id, 'openwrite')
  // A real edit of a shipped file is still a modification.
  await writeFile(join(target, 'preset.yml'), 'author edited this')
  await assert.rejects(apply(ctx()), /was modified/)
  for (const dispose of disposers) await dispose()
})

/**
 * A host package tree that publishes the `./list-agents` subpath, and one that
 * does not. Both claim the same host version: the row has to follow what the
 * host actually exports, because the host refuses a preset whose row it
 * cannot resolve.
 */
async function hostTree(listAgents) {
  const root = await mkdtemp(join(tmpdir(), 'openwrite-host-tree-'))
  const host = join(root, 'node_modules', '@deepseek-ai', 'dsh')
  await mkdir(join(host, 'lib'), { recursive: true })
  await writeFile(join(host, 'package.json'), JSON.stringify({ name: '@deepseek-ai/dsh', version: '0.2.2-rc.1' }) + '\n')
  await writeFile(join(host, 'lib', 'bin.js'), '// host entry\n')
  const control = join(root, 'node_modules', '@deepseek-ai', 'dsh-tool-subagent-control')
  await mkdir(join(control, 'lib'), { recursive: true })
  const published = { '.': { default: './lib/index.js' }, './src/*': './src/*', './package.json': './package.json' }
  if (listAgents) published['./list-agents'] = { default: './lib/list-agents.js' }
  await writeFile(join(control, 'package.json'), JSON.stringify({
    name: '@deepseek-ai/dsh-tool-subagent-control', version: '0.2.2-rc.1', exports: published,
  }) + '\n')
  // The resolver checks that the exported target exists, not only that the
  // subpath is declared.
  await writeFile(join(control, 'lib', 'index.js'), '// tool control\n')
  if (listAgents) await writeFile(join(control, 'lib', 'list-agents.js'), '// list agents\n')
  return { root, entry: join(host, 'lib', 'bin.js') }
}

/** The preset rows, flattened the way the host walks them. */
function presetRows(definition) {
  const rows = []
  const walk = entries => {
    for (const row of entries) {
      rows.push(row)
      if (row.group && Array.isArray(row.config)) walk(row.config)
    }
  }
  walk(definition.plugins)
  return rows
}

test('a preset row follows the host exports rather than a host version', async t => {
  const dropped = await hostTree(false)
  const kept = await hostTree(true)
  t.after(async () => {
    await rm(dropped.root, { recursive: true, force: true })
    await rm(kept.root, { recursive: true, force: true })
  })
  const name = '@deepseek-ai/dsh-tool-subagent-control/list-agents'
  // The host imports a preset row from its own package tree, so the plugin has
  // to ask the host's tree - the plugin's own node_modules are a different one
  // and would answer for the wrong resolver.
  assert.equal(presetRows(await presetDefinition('0.2.36', true, { hostEntry: dropped.entry }))
    .some(row => row.name === name), false, 'a row the host cannot resolve must be dropped')
  assert.equal(presetRows(await presetDefinition('0.2.36', true, { hostEntry: kept.entry }))
    .some(row => row.name === name), true, 'a row the host can resolve must be kept')
})

test('a row the host may not provide is dropped when no host can be located', async t => {
  const home = await mkdtemp(join(tmpdir(), 'openwrite-host-unknown-'))
  const previousHome = process.env.DSH_HOME
  const previousEntry = process.argv[1]
  process.env.DSH_HOME = home
  // The running process and the installed profiles are where the host is
  // looked for. Point both at empty ground so that no host can be located -
  // the shape of the Electron desktop application, whose host lives in the
  // application bundle and whose profile holds plugins only.
  process.argv[1] = join(home, 'entry.mjs')
  t.after(async () => {
    process.argv[1] = previousEntry
    if (previousHome === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = previousHome
    await rm(home, { recursive: true, force: true })
  })
  const name = '@deepseek-ai/dsh-tool-subagent-control/list-agents'
  const rows = presetRows(await presetDefinition('0.2.37', true))
  assert.equal(rows.some(row => row.name === name), false,
    'a row that may not resolve must not be kept when no host can be located: the host refuses the whole preset')
})
