import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { load } from 'js-yaml'
import { presetDefinition } from '../preset-definition.mjs'
import { entryListSchema } from '@deepseek-ai/cordis-plugin-include'

const root = new URL('../', import.meta.url)
const presetDir = new URL('presets/openwrite/', root)
const composition = await readFile(new URL('agent.cordis.yml', presetDir), 'utf8')
const hostCli = process.argv.find(arg => arg.startsWith('--host-cli='))?.slice('--host-cli='.length)
const require = createRequire(hostCli ? resolve(hostCli) : new URL('package.json', root))
// `plugin.mjs` always registers the modern definition, so the gate must validate
// that same one. Deriving `modern` from a package that is not installed made the
// resolution sweep check a definition the plugin never registers.
const modern = true
const version = JSON.parse(await readFile(new URL('package.json', root), 'utf8')).version
// The row gate is judged against the host under test: the plugin resolves a
// row from the host's own package tree, so the host that is being installed
// is the only context that answers whether the host can resolve it. Without
// `--host-cli` the host under test is the one this checkout pins.
const hostEntry = hostCli
  ? resolve(hostCli)
  : fileURLToPath(new URL('node_modules/@deepseek-ai/dsh/lib/bin.js', root))
const rows = (await presetDefinition(version, modern, { hostEntry })).plugins
assert.ok(Array.isArray(rows) && rows.length > 10, 'unified preset must be a non-trivial entry list')
const flatten = entries => entries.flatMap(row => [row, ...(row.group && Array.isArray(row.config) ? flatten(row.config) : [])])
const allRows = flatten(rows)
assert.equal(allRows.some(row => row?.name === '@dsh-novel/openwrite-bridge'), false,
  'openwrite-bridge belongs to the host profile and must not be mounted by the preset')
// Host packages the modern definition names but this repo's node_modules does not
// carry, because the checkout pins an older host. Listed explicitly so the sweep
// still fails on any *other* unresolvable row — silently skipping them would
// recreate the blind spot this loop exists to close.
const expectedAbsent = new Set(['@deepseek-ai/dsh-workflow-ptc'])
const unresolvable = []
for (const row of allRows) {
  if (!row.name?.startsWith('@deepseek-ai/')) continue
  if (expectedAbsent.has(row.name)) continue
  try { require.resolve(row.name) } catch { unresolvable.push(row.name) }
}
assert.deepEqual(unresolvable, [], `unresolvable host rows in the registered preset: ${unresolvable.join(', ')}`)

// Validate against the actual host schema: alpha renamed persona.text to prefix.
const persona = rows.find(row => row.name === '@deepseek-ai/dsh-persona')
assert.equal(persona.config.prefix, persona.config.text, 'both SDK contracts share one persona')
const personaModule = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-persona')).href)
const personaConfig = personaModule.Config(persona.config)
const sections = []
personaModule.apply({
  effect: action => action(),
  systemPrompt: { section: value => sections.push(value), getSectionOrder: () => 0 },
}, personaConfig)
assert.equal(sections.filter(section => section.text === persona.config.text).length, 1, 'persona appears exactly once')

const metadata = load(await readFile(new URL('preset.yml', presetDir), 'utf8'))
assert.equal(metadata.name, 'OpenWrite 创作')
assert.match(metadata.description, /同一会话/)
assert.match(metadata.description, /六域/)
assert.doesNotMatch(composition + metadata.description, /37\s*维.*评审/)

const skillEntries = await readdir(new URL('skills/', presetDir), { withFileTypes: true })
const skillCount = skillEntries.filter(entry => entry.isDirectory()).length
assert.ok(skillCount >= 16, `expected merged skill set, found ${skillCount}`)
const skillSources = {}
const skillMeta = {}
for (const entry of skillEntries.filter(entry => entry.isDirectory())) {
  const source = await readFile(new URL(`skills/${entry.name}/SKILL.md`, presetDir), 'utf8')
  skillSources[entry.name] = source
  const front = source.match(/^---\r?\n([\s\S]*?)\r?\n---/)
  assert.ok(front, `${entry.name}: missing skill frontmatter`)
  const skill = load(front[1])
  skillMeta[entry.name] = skill
  assert.equal(skill.name, entry.name, `${entry.name}: skill directory/name mismatch`)
  assert.ok(typeof skill.description === 'string' && skill.description.trim(), `${entry.name}: missing description`)
}

const writeReviewWorkflow = ['novel-creator', 'novel-reviewer', 'workflow-manager']
const forbiddenLegacy = [
  'get_outline_structure',
  'get_workflow_status',
  'advance_workflow',
  'WriterAgent',
  'ReviewerAgent',
  'create_foreshadowing',
  'list_foreshadowing',
  'query_world',
  'get_world_relations',
  'validate_truth',
]
const authorEntries = [
  { name: 'progress', phrase: '看进度', tools: ['novel_status', 'novel_chapter_work', 'novel_task'] },
  { name: 'write-next', phrase: '写下一章', tools: ['novel_outline_read', 'novel_context_preview', 'novel_write_chapter'] },
  { name: 'review-chapter', phrase: '审这一章', tools: ['novel_chapter_work', 'novel_review_chapter'] },
  { name: 'revise-span', phrase: '改这段', tools: ['novel_revision'] },
  { name: 'foreshadow', phrase: '查伏笔', tools: ['novel_chapter_work', 'novel_continuity'] },
  { name: 'canon', phrase: '查设定', tools: ['novel_assets'] },
  { name: 'learn', phrase: '写法记忆', tools: ['novel_source_action', 'novel_change_plan', 'novel_assets'] },
  { name: 'export-book', phrase: '导出', tools: ['novel_export'] },
]
const authorNames = new Set(authorEntries.map(entry => entry.name))

function assertNoLegacyCommands(name, source) {
  for (const token of forbiddenLegacy) {
    assert.equal(source.includes(token), false, `${name} must not instruct ${token}`)
  }
  assert.equal(
    /(?<!novel_)write_chapter/.test(source),
    false,
    `${name} must not instruct the unsuffixed write_chapter command`,
  )
}

for (const name of writeReviewWorkflow) {
  const source = skillSources[name]
  assert.ok(typeof source === 'string' && source.length > 0, `missing shipped skill ${name}`)
  assertNoLegacyCommands(name, source)
}

assert.match(skillSources['novel-creator'], /novel_outline_read/)
assert.match(skillSources['novel-creator'], /novel_write_chapter/)
assert.match(skillSources['novel-reviewer'], /novel_review_chapter/)
assert.match(skillSources['novel-reviewer'], /钩子/)
assert.match(skillSources['novel-reviewer'], /黄金三章/)
assert.match(skillSources['novel-reviewer'], /追读力/)
assert.match(skillSources['review-chapter'], /web_novel/)
assert.match(skillSources['workflow-manager'], /novel_write_chapter/)
assert.match(skillSources['workflow-manager'], /novel_review_chapter/)

for (const entry of authorEntries) {
  const source = skillSources[entry.name]
  assert.ok(typeof source === 'string' && source.length > 0, `missing author entry skill ${entry.name}`)
  assert.match(skillMeta[entry.name].description, new RegExp(entry.phrase))
  assert.notEqual(skillMeta[entry.name]['user-invocable'], false, `${entry.name} must stay on the slash menu`)
  assertNoLegacyCommands(entry.name, source)
  for (const tool of entry.tools) {
    assert.match(source, new RegExp(`\\b${tool}\\b`))
  }
}

for (const name of Object.keys(skillSources)) {
  if (authorNames.has(name)) continue
  assert.equal(skillMeta[name]['user-invocable'], false, `${name} must stay off the slash menu`)
}

// Every shipped skill, including the ones no list enumerates. The hardcoded
// `forbiddenLegacy` list is only as good as its last update; scanning all of
// them keeps a renamed/removed skill from silently skipping every check.
const enumerated = new Set([...writeReviewWorkflow, ...authorNames])
for (const name of Object.keys(skillSources)) {
  if (enumerated.has(name)) continue
  assertNoLegacyCommands(name, skillSources[name])
}

// The DoG handoff graph is executed by an external plugin; a placeholder id or
// a missing title makes dog_validate reject the whole graph only after the
// author has already agreed to spend verifier calls.
const dogSkill = skillSources['dog-delivery-verification']
const dogGraphBlock = /```json\n([\s\S]*?)```/.exec(dogSkill)
assert.ok(dogGraphBlock !== null, 'dog-delivery-verification must ship a JSON graph')
const dogGraph = JSON.parse(dogGraphBlock[1])
assert.equal(dogGraph.schemaVersion, '0.9')
assert.match(dogGraph.id, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/)
assert.ok(dogGraph.nodes?.[dogGraph.root])
for (const [id, node] of Object.entries(dogGraph.nodes)) {
  assert.ok(typeof node.title === 'string' && node.title.length > 0, `${id} must have a title`)
  assert.ok(typeof node.target === 'string' && node.target.length > 0, `${id} must have a target`)
  // dog_create captures from the session cwd; a bare "manuscript.md" would look
  // in the workspace root instead of the handoff directory.
  assert.match(node.target, /^\.openwrite\/dog-handoff\/[^/<>]+\//, `${id} target must be relative to the workspace root`)
}
for (const edge of dogGraph.contains ?? []) {
  assert.ok(dogGraph.nodes[edge.parent], `contains parent ${edge.parent} exists`)
  assert.ok(dogGraph.nodes[edge.child], `contains child ${edge.child} exists`)
}

assert.equal(skillSources['export-book'].includes('/export-book'), true)
assert.equal(/\n\/export\b/.test(skillSources['export-book']), false, 'manuscript export must not collide with host /export')
assert.match(composition, /\/progress/)
assert.match(composition, /看进度/)
assert.match(composition, /\/write-next/)
assert.match(composition, /\/review-chapter/)
assert.match(composition, /\/revise-span/)
assert.match(composition, /\/foreshadow/)
assert.match(composition, /\/canon/)
assert.match(composition, /\/learn/)
assert.match(composition, /写法记忆/)
assert.match(composition, /\/export-book/)
assert.match(composition, /初始引导/)
assert.match(composition, /复制脱敏诊断信息/)
assert.match(skillSources['progress'], /复制脱敏诊断信息/)
assert.match(skillSources['learn'], /WORKSPACE_CONTEXT_MISSING/)

console.log(JSON.stringify({
  preset: 'openwrite',
  rows: allRows.length,
  skills: skillCount,
  modulesResolved: true,
  novelToolSkills: writeReviewWorkflow,
  authorEntries: [...authorNames],
}))
