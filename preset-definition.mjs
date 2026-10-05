import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { load, Type, JSON_SCHEMA } from 'js-yaml'

// Preserve Loader expressions; evaluating them here loses the preset's baseUrl
// and entry-local realm. This is the host's entry-list !!js wire representation.
const schema = JSON_SCHEMA.extend(new Type('tag:yaml.org,2002:js', {
  kind: 'scalar', resolve: value => typeof value === 'string',
  construct: value => ({ __jsExpr: value }),
}))

export async function presetDefinition(version, modern = false) {
  const baseUrl = new URL('./presets/openwrite/', import.meta.url)
  const plugins = load(await readFile(new URL('agent.cordis.yml', baseUrl), 'utf8'), { schema })
  const metadata = load(await readFile(new URL('preset.yml', baseUrl), 'utf8'))
  if (modern) {
    const adapt = rows => {
      for (const row of rows) {
        if (row.name === '@deepseek-ai/dsh-workflow-worker-thread') {
          row.name = '@deepseek-ai/dsh-workflow-ptc'
        }
        if (row.name === '@deepseek-ai/dsh-skill-filesystem') {
          row.config.customSkillDirs = [fileURLToPath(new URL('skills/', baseUrl))]
        }
        if (row.group && Array.isArray(row.config)) adapt(row.config)
      }
    }
    adapt(plugins)
  }
  return { ...metadata, id: `openwrite-${version.replace(/[^a-z0-9-]/g, '-')}`, plugins }
}
