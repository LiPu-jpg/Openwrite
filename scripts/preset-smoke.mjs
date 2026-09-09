import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { load } from 'js-yaml'
import { entryListSchema } from '@deepseek-ai/cordis-plugin-include'

const root = new URL('../', import.meta.url)
const presetDir = new URL('presets/openwrite/', root)
const composition = await readFile(new URL('agent.cordis.yml', presetDir), 'utf8')
const rows = load(composition, { schema: entryListSchema })
assert.ok(Array.isArray(rows) && rows.length > 10, 'unified preset must be a non-trivial entry list')
const flatten = entries => entries.flatMap(row => [row, ...(row.group && Array.isArray(row.config) ? flatten(row.config) : [])])
const allRows = flatten(rows)
assert.equal(allRows.some(row => row?.name === '@dsh-novel/openwrite-bridge'), false,
  'openwrite-bridge belongs to the host profile and must not be mounted by the preset')
const hostCli = process.argv.find(arg => arg.startsWith('--host-cli='))?.slice('--host-cli='.length)
const require = createRequire(hostCli ? resolve(hostCli) : new URL('package.json', root))
for (const row of allRows) {
  if (row.name?.startsWith('@deepseek-ai/')) require.resolve(row.name)
}

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
  { name: 'progress', phrase: '看进度', tools: ['novel_status', 'novel_chapter_work', 'novel_tasks_list'] },
  { name: 'write-next', phrase: '写下一章', tools: ['novel_outline_read', 'novel_context_preview', 'novel_write_chapter'] },
  { name: 'review-chapter', phrase: '审这一章', tools: ['novel_chapter_work', 'novel_review_chapter'] },
  { name: 'revise-span', phrase: '改这段', tools: ['novel_revision_create_selection', 'novel_revision_apply'] },
  { name: 'foreshadow', phrase: '查伏笔', tools: ['novel_chapter_work', 'novel_continuity'] },
  { name: 'canon', phrase: '查设定', tools: ['novel_assets_list', 'novel_asset_read'] },
  { name: 'learn', phrase: '写法记忆', tools: ['novel_source_action', 'novel_structured_change_plan', 'novel_assets_list'] },
  { name: 'export-book', phrase: '导出', tools: ['novel_export_preflight', 'novel_export'] },
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
assert.match(skillSources['learn'], /WORKSPACE_CONTEXT_MISSING/)

console.log(JSON.stringify({
  preset: 'openwrite',
  rows: allRows.length,
  skills: skillCount,
  modulesResolved: true,
  novelToolSkills: writeReviewWorkflow,
  authorEntries: [...authorNames],
}))
