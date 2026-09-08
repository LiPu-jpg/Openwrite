import { describe, it, expect } from 'vitest'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { runOwnedScript } from '../src/owned-script.ts'

describe('owned verifier processes', () => {
  it('executes packaged JavaScript through Node and cancels in-flight work', async () => {
    const root = await mkdtemp(join(tmpdir(), 'openwrite-dog-script-'))
    try {
      const script = join(root, 'verifier.mjs')
      await writeFile(script, 'console.log(JSON.stringify({verdict:"pass", evidence:{input:process.argv[2]}}))')
      expect(JSON.parse(await runOwnedScript(script, 'input.json')).verdict).toBe('pass')
      await writeFile(script, 'setInterval(()=>{},1000)')
      const controller = new AbortController()
      const running = runOwnedScript(script, 'input.json', controller.signal)
      setTimeout(() => controller.abort(), 80)
      await expect(running).rejects.toThrow()
    } finally { await rm(root, { recursive: true, force: true }) }
  })
})
