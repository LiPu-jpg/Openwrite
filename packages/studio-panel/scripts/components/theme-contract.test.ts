import { readFileSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const themeRoot = dirname(require.resolve('@deepseek-ai/dsh-client-ui-theme/package.json'))
const themeDirectory = join(themeRoot, 'lib/styles')
const theme = readdirSync(themeDirectory)
  .filter(file => file.endsWith('.css'))
  .map(file => readFileSync(join(themeDirectory, file), 'utf8'))
  .join('\n')
const provided = new Set([...theme.matchAll(/(--dsw-alias-[\w-]+)\s*:/g)].map(match => match[1]))
const clientDirectory = join(dirname(fileURLToPath(import.meta.url)), '../../src/client')

describe('installed dsh theme contract', () => {
  it('resolves every semantic color used by the workbenches against the installed theme', () => {
    // A missing variable silently removes the whole declaration in browsers:
    // the previous border-l / state-info aliases erased borders and focus rings.
    expect(provided.size).toBeGreaterThan(50)
    const missing: string[] = []
    for (const file of readdirSync(clientDirectory).filter(name => /\.(css|tsx?)$/.test(name))) {
      const source = readFileSync(join(clientDirectory, file), 'utf8')
      const used = new Set([...source.matchAll(/--dsw-alias-[\w-]+/g)].map(match => match[0]))
      for (const token of used) {
        if (!provided.has(token)) missing.push(`${file}: ${token}`)
      }
    }
    expect(missing, 'Use semantic tokens exported by the installed dsh theme.').toEqual([])
  })
})
