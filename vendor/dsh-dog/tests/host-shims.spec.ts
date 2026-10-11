import { describe, expect, it } from 'vitest'
import { defineTool, dshHomePath, validateArgs } from '../src/host-shims.ts'

describe('host-shims defineTool', () => {
  const tool = defineTool({
    name: 't_demo',
    description: 'demo',
    parameters: {
      graph: { type: 'json', required: true, description: 'graph' },
      runId: { type: 'string', required: true },
      role: { type: 'string', required: true, enum: ['orchestrator', 'verifier'] as const },
      timeout: { type: 'number' },
    },
    output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => [{ type: 'text' as const, text: JSON.stringify(value) }] },
    isConcurrencySafe: () => true,
    execute: async (args) => args,
  })

  it('compiles the parameter schema like the host', () => {
    expect(tool.parameters).toEqual({
      type: 'object',
      properties: {
        graph: { description: 'graph' },
        runId: { type: 'string' },
        role: { type: 'string', enum: ['orchestrator', 'verifier'] },
        timeout: { type: 'number' },
      },
      required: ['graph', 'runId', 'role'],
    })
  })

  it('compiles the json output schema to annotation-only', () => {
    expect(tool.output.schema).toEqual({})
  })

  it('executes with valid args', async () => {
    const args = { graph: { a: 1 }, runId: 'r1', role: 'verifier' }
    await expect(tool.execute(args, {} as never)).resolves.toEqual(args)
  })

  it('rejects missing required args', async () => {
    await expect(tool.execute({ graph: {} }, {} as never)).rejects.toThrow(/invalid arguments: .*runId/)
  })

  it('rejects enum violations', async () => {
    await expect(tool.execute({ graph: {}, runId: 'r', role: 'boss' }, {} as never)).rejects.toThrow(/must be one of/)
  })

  it('rejects wrong scalar types', async () => {
    await expect(tool.execute({ graph: {}, runId: 5, role: 'verifier' }, {} as never)).rejects.toThrow(/expected string, got number/)
  })

  it('isConcurrencySafe returns false on invalid args', () => {
    expect(tool.isConcurrencySafe?.({})).toBe(false)
    expect(tool.isConcurrencySafe?.({ graph: 1, runId: 'r', role: 'orchestrator' })).toBe(true)
  })
})

describe('host-shims dshHomePath', () => {
  it('joins segments onto $DSH_HOME', () => {
    process.env.DSH_HOME = '/tmp/dsh-home-test'
    expect(dshHomePath('a', 'b')).toBe('/tmp/dsh-home-test/a/b')
    delete process.env.DSH_HOME
  })

  it('falls back to ~/.dsh', () => {
    delete process.env.DSH_HOME
    expect(dshHomePath('x')).toContain('.dsh')
  })

  it('validateArgs walks arrays and nested objects', () => {
    const violations = validateArgs(
      { type: 'object', properties: { list: { type: 'array', items: { type: 'integer' } } }, required: ['list'] },
      { list: [1, 'x'] },
    )
    expect(violations).toEqual(['arguments.list[1]: expected integer, got string'])
  })
})
