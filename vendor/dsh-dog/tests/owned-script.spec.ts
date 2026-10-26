import { describe, it, expect } from 'vitest'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { runOwnedScript } from '../src/owned-script.ts'
import { parseVerdict, scriptFailureVerdict } from '../src/script-verdict.ts'
import { resolveScriptPath } from '../src/core.ts'

describe('owned verifier processes', () => {
  it('uses Node mode for JavaScript children and preserves the input argument', async () => {
    const root = await mkdtemp(join(tmpdir(), 'openwrite-dog-node-'))
    try {
      const script = join(root, 'verifier.mjs')
      await writeFile(script, 'console.log(JSON.stringify({verdict: process.env.ELECTRON_RUN_AS_NODE === "1" ? "pass" : "fail", evidence: {input:process.argv[2]}}))')
      expect(parseVerdict(await runOwnedScript(script, 'input with spaces.json'))).toEqual({state: 'pass', evidence: {input: 'input with spaces.json'}})
    } finally { await rm(root, { recursive: true, force: true }) }
  })

  it('distinguishes a missing script, a crashed process, and malformed output', async () => {
    const root = await mkdtemp(join(tmpdir(), 'openwrite-dog-errors-'))
    try {
      const script = join(root, 'verifier.mjs')
      const missing = await runOwnedScript(script, '').catch(scriptFailureVerdict)
      expect(missing).toMatchObject({state: 'inconclusive', evidence: {code: 'SCRIPT_NOT_FOUND', script}})
      let missingPathError: unknown
      try { resolveScriptPath(root, 'missing-verifier') } catch (error) { missingPathError = error }
      expect(scriptFailureVerdict(missingPathError)).toMatchObject({state: 'inconclusive', evidence: {code: 'SCRIPT_NOT_FOUND'}})
      await writeFile(script, 'process.stderr.write("runtime exploded"); process.stdout.write("unfinished"); process.exit(3)')
      const crashed = await runOwnedScript(script, '').catch(scriptFailureVerdict)
      expect(crashed).toMatchObject({state: 'inconclusive', evidence: {code: 'SCRIPT_EXIT_FAILED', exitCode: 3, stderr: 'runtime exploded', outputPreview: 'unfinished'}})
      await writeFile(script, 'process.stdout.write("not json" + "x".repeat(300))')
      const malformed = parseVerdict(await runOwnedScript(script, ''))
      expect(malformed).toMatchObject({state: 'inconclusive', evidence: {code: 'SCRIPT_OUTPUT_NOT_JSON'}})
      expect(Buffer.byteLength((malformed.evidence as {outputPreview: string}).outputPreview)).toBe(200)
    } finally { await rm(root, { recursive: true, force: true }) }
  })

  it('preserves UTF-8 characters split across stdout chunks', async () => {
    const root = await mkdtemp(join(tmpdir(), 'openwrite-dog-utf8-'))
    try {
      const script = join(root, 'verifier.mjs')
      await writeFile(script, 'const b=Buffer.from(JSON.stringify({verdict:"pass",evidence:{text:"中文证据"}})); const i=b.indexOf(Buffer.from("中"))+1; process.stdout.write(b.subarray(0,i)); setTimeout(()=>process.stdout.write(b.subarray(i)),50)')
      expect(parseVerdict(await runOwnedScript(script, ''))).toMatchObject({state: 'pass', evidence: {text: '中文证据'}})
    } finally { await rm(root, {recursive: true, force: true}) }
  })

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
