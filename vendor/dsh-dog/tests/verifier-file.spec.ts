import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { parseSettlementFile, waitForSettlement } from '../src/verifier-file.ts'

const temporaryRoots: string[] = []

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('continuable verifier settlement file', () => {
  it('parses a valid settlement JSON object', () => {
    expect(parseSettlementFile('{"settlement":"pass","observation":{"checked":true}}')).toEqual({
      state: 'pass',
      observation: { checked: true },
    })
    expect(parseSettlementFile('{"settlement":"fail","observation":{"overlap":0.31}}')).toEqual({
      state: 'fail',
      observation: { overlap: 0.31 },
    })
  })

  it('rejects bare assertions and invalid settlements as inconclusive', () => {
    const bad = parseSettlementFile('{"settlement":"pass"}')
    expect(bad.state).toBe('inconclusive')
    const wrongEnum = parseSettlementFile('{"settlement":"maybe"}')
    expect(wrongEnum.state).toBe('inconclusive')
    const notObject = parseSettlementFile('"ok"')
    expect(notObject.state).toBe('inconclusive')
  })

  it('returns inconclusive on abort without throwing', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-dog-settle-'))
    temporaryRoots.push(root)
    const controller = new AbortController()
    controller.abort()
    const result = await waitForSettlement(join(root, 'settlement.json'), controller.signal, 5_000)
    expect(result.state).toBe('inconclusive')
    expect(result.observation.outcome).toBe('aborted')
  })

  it('returns inconclusive on timeout', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-dog-settle-'))
    temporaryRoots.push(root)
    const result = await waitForSettlement(join(root, 'missing.json'), new AbortController().signal, 300)
    expect(result.state).toBe('inconclusive')
    expect(result.observation.outcome).toContain('timed out')
  })

  it('picks up the file once the subagent writes it', async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-dog-settle-'))
    temporaryRoots.push(root)
    const path = join(root, 'settlement.json')
    await writeFile(path, '{"settlement":"pass","observation":{"boxes":["a"],"ok":true}}')
    const result = await waitForSettlement(path, new AbortController().signal, 2_000)
    expect(result.state).toBe('pass')
    expect(result.observation.boxes).toEqual(['a'])
  })
})
