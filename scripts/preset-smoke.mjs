import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
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
const require = createRequire(new URL('package.json', root))
for (const row of allRows) {
  if (row.name?.startsWith('@deepseek-ai/')) require.resolve(row.name)
}

const metadata = load(await readFile(new URL('preset.yml', presetDir), 'utf8'))
assert.equal(metadata.name, 'OpenWrite 创作')
assert.match(metadata.description, /同一会话/)
assert.match(metadata.description, /六域/)
assert.doesNotMatch(composition + metadata.description, /37\s*维.*评审/)

const skillEntries = await readdir(new URL('skills/', presetDir), { withFileTypes: true })
const skillCount = skillEntries.filter(entry => entry.isDirectory()).length
assert.ok(skillCount >= 16, `expected merged skill set, found ${skillCount}`)
for (const entry of skillEntries.filter(entry => entry.isDirectory())) {
  const source = await readFile(new URL(`skills/${entry.name}/SKILL.md`, presetDir), 'utf8')
  const front = source.match(/^---\r?\n([\s\S]*?)\r?\n---/)
  assert.ok(front, `${entry.name}: missing skill frontmatter`)
  const skill = load(front[1])
  assert.equal(skill.name, entry.name, `${entry.name}: skill directory/name mismatch`)
  assert.ok(typeof skill.description === 'string' && skill.description.trim(), `${entry.name}: missing description`)
}

console.log(JSON.stringify({ preset: 'openwrite', rows: allRows.length, skills: skillCount, modulesResolved: true }))
