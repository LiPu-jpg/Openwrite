// Guard: no description, parameter doc, skill, or generated reference may name a
// tool the registry does not define. Run by `npm run docs:check`.
import { readFile, readdir } from 'node:fs/promises'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../', import.meta.url))
const tools = await readFile(join(root, 'packages/openwrite-bridge/src/tools.ts'), 'utf8')
const live = new Set([...tools.matchAll(/name: '(novel_[a-z_]+)'/g)].map(match => match[1]))

/** `novel_*` spellings that are data fields rather than tool names. */
const identifiers = new Set(['novel_id', 'novel_config'])

/**
 * Command-style tool names retired before the tool merge. Not `novel_*`-shaped,
 * so the registry check cannot see them; a hardcoded list is the only way to
 * catch them, and it is exactly what `preset-smoke.mjs` applies to 11 of the 24
 * shipped skills. Checking every skill here closes that gap.
 */
const retiredCommands = [
  'get_outline_structure', 'get_workflow_status', 'advance_workflow',
  'create_foreshadowing', 'list_foreshadowing', 'update_foreshadowing', 'validate_foreshadowing',
  'query_world', 'get_world_relations', 'validate_truth',
  'WriterAgent', 'ReviewerAgent',
]

async function markdown(...targets) {
  const found = []
  const walk = async directory => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await walk(path)
      else if (/\.md$/.test(entry.name)) found.push(path)
    }
  }
  for (const target of targets) await walk(target)
  return found
}

/**
 * Prose files whose historical narrative legitimately names removed tools and
 * deleted bundles. A status doc that says "0.2.23 shipped the DoG panel" is a
 * record, not an instruction; the gate must not rewrite history, but it must
 * flag anything a reader could follow today.
 */
const historical = new Set([
  'docs/RELEASE_ACCEPTANCE.md',
  'docs/ISSUES_149_150_151.md',
  'docs/PLUGIN_MAINTENANCE_RC7.md',
  'docs/PLUGIN_MAINTENANCE_RC6.md',
  // Dated records of a specific past release or plan. Each states its own date
  // and status in its opening lines; they record what the surface looked like
  // then, and rewriting them would destroy the evidence.
  'docs/EDITOR_SAFETY_REPAIRS.md',
  'docs/ISSUES_121_123.md',
  'docs/ISSUE_76_REPAIRS.md',
  'docs/IMPROVEMENT_PLAN.md',
  'docs/OPEN_SOURCE_NOVEL_AUDIT.md',
  'docs/TARGETED_NOVEL_PROJECT_REVIEW.md',
])

const problems = []
// 1. The tool source itself: descriptions and parameter docs.
tools.split('\n').forEach((line, index) => {
  for (const match of line.matchAll(/\bnovel_[a-z_]+\b/g)) {
    if (live.has(match[0]) || identifiers.has(match[0])) continue
    problems.push(`packages/openwrite-bridge/src/tools.ts:${index + 1}: unknown tool ${match[0]}`)
  }
})
// 2. Every shipped skill.
for (const path of await markdown(join(root, 'presets/openwrite/skills'))) {
  const text = await readFile(path, 'utf8')
  for (const match of text.matchAll(/\bnovel_[a-z_]+\b/g)) {
    if (live.has(match[0]) || identifiers.has(match[0])) continue
    problems.push(`${relative(root, path)}: unknown tool ${match[0]}`)
  }
  for (const command of retiredCommands) {
    if (text.includes(command)) problems.push(`${relative(root, path)}: retired command ${command}`)
  }
  // A skill must not teach the model to *print* a tool request as assistant
  // text: nothing in this plugin parses `[COMMAND]`, so the described operation
  // silently never happens. Real tool calls are emitted by the host, not typed.
  if (text.includes('[COMMAND]')) {
    problems.push(`${relative(root, path)}: pseudo-invocation "[COMMAND]" — the model must emit a real tool call, not print one`)
  }
  // The only binaries this package ships.
  const shippedBins = new Set(['openwrite-maintenance', 'openwrite-safe-upgrade'])
  for (const match of text.matchAll(/\bopenwrite\s+(style|setting|source|studio|goethe|dante|desk|init|export)\b/g)) {
    problems.push(`${relative(root, path)}: instructs a \`openwrite ${match[1]}\` CLI that this package does not ship (bin: ${[...shippedBins].join(', ')})`)
  }
}
// 3. Every user-facing doc, not just the generated reference: a doc that names a
// retired tool sends the reader down a path that no longer exists. Historical
// release logs are excluded above — they record what was true, not what to do.
for (const path of await markdown(join(root, 'docs'))) {
  const relativePath = relative(root, path)
  if (historical.has(relativePath)) continue
  const text = await readFile(path, 'utf8')
  for (const match of text.matchAll(/\bnovel_[a-z_]+\b/g)) {
    if (live.has(match[0]) || identifiers.has(match[0])) continue
    // A link into another repository's own `tools/*.py` names that project's
    // tool, not one of ours; those lines are out of scope.
    const line = text.slice(text.lastIndexOf('\n', match.index), match.index).split('\n')[0] ?? ''
    if (/\.\.\/\.\.\/|\([^)]*OpenWrite\/tools\//.test(line)) continue
    problems.push(`${relativePath}: unknown tool ${match[0]}`)
  }
  for (const command of retiredCommands) {
    if (text.includes(command)) problems.push(`${relativePath}: retired command ${command}`)
  }
}

if (problems.length > 0) {
  console.error(problems.slice(0, 20).join('\n'))
  if (problems.length > 20) console.error(`… and ${problems.length - 20} more`)
  process.exitCode = 1
} else {
  console.log(`Every referenced tool exists (${live.size} registered)`)
}
