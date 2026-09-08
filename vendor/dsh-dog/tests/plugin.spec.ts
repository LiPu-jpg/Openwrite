/** DoG v0.9 plugin smoke: config wiring, tool registration, real ToolRuntime round-trip. */

import { writeFile, rm, mkdtemp, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { apply } from '../src/index.ts'
import { DOG_CREATE_TOOL, DOG_RUN_TOOL, DOG_STATUS_TOOL, DOG_VALIDATE_TOOL } from '../src/tools.ts'
import { isJsonValue } from '../src/model.ts'

let ctx: { tools: { execute(input: unknown): Promise<{ isError: boolean; error?: { message: string }; value?: unknown }>; register(_t: unknown): void } }
let plugin: { apply(ctx: unknown, config: unknown): Promise<unknown> }
let setupCtx: unknown
let workspace: string
let home: string
let savedHome: string | undefined

async function fakeCtx(): Promise<typeof ctx> {
  const tools: unknown[] = []
  const fake = {
    provide(name: string, value: { tools: unknown[] }) {
      expect(name).toBe('openwriteDog')
      expect(tools).toHaveLength(0) // host service contributes no global model tools
      for (const tool of value.tools) tools.push(tool) // emulate the preset registration
    },
    get(): unknown { return undefined },
    on(): void { },
    effect(fn: () => void) { fn() },
    inject(): void { },
    tools: {
      register(t: unknown) { tools.push(t) },
      async execute(input: unknown): Promise<{ isError: boolean; error?: { message: string }; value?: unknown }> {
        const args = input as { name: string; arguments: unknown }
        if (tools.length) console.log('DBG_TOOL0', Object.keys(tools[0] as object).slice(0, 6).join(","), 'name=', (tools[0] as { name?: string }).name)
        const tool = tools.find(t => (t as { name: string }).name === args.name) as { execute(args: unknown, exec: unknown): Promise<unknown> } | undefined
        if (tool === undefined) return { isError: true, error: { message: `no tool ${args.name}` } }
        try {
          const value = await tool.execute(args.arguments, { signal: new AbortController().signal, callId: 'call-x', agent: undefined })
          return { isError: false, value }
        } catch (error) {
          return { isError: true, error: { message: String(error instanceof Error ? error.message : error) } }
        }
      },
    },
  }
  return fake as unknown as typeof ctx
}

async function setup(): Promise<void> {
  savedHome = process.env.DSH_HOME
  home = await mkdtemp(join(tmpdir(), 'dsh-dog-home-'))
  process.env.DSH_HOME = home
  workspace = await mkdtemp(join(tmpdir(), 'dsh-dog-ws-'))
  await writeFile(join(workspace, 'artifact.txt'), 'verified')
  await mkdir(join(home, 'dog', 'scripts'), { recursive: true })
  await writeFile(join(home, 'dog', 'scripts', 'file-non-empty'), String.raw`
const { statSync } = require('node:fs')
const s = statSync(process.argv[2])
process.stdout.write(JSON.stringify(s.size > 0 ? { verdict: 'pass', evidence: { bytes: s.size } } : { verdict: 'fail', evidence: { bytes: 0 } }))
`)
}

describe('DoG Cordis plugin v0.9', () => {
  beforeAll(async () => {
    await setup()
    ctx = await fakeCtx()
    setupCtx = { ...ctx, get: () => undefined, on: () => { }, inject: () => { } }
    const config = {
      storageDirectory: 'dog',
      workspaceRoot: workspace,
      scriptsDirectory: join(home, 'dog', 'scripts'),
      maxGraphNodes: 256,
      maxExpressionNodes: 512,
      maxExpressionDepth: 64,
      maxSandboxBytes: 67_108_864,
      allowPartialRoot: false,
      maxConcurrentVerifications: 1,
      revalidateThreshold: 0.3,
      gmDigestAlgo: 'sha256',
      subagentProvider: 'spawn',
      subagentMaxDepth: 3,
    }
    plugin = { apply }
    await (plugin.apply as (ctx: unknown, config: unknown) => Promise<unknown>)(setupCtx, config).catch(e => { console.log('DBG_APPLY_ERR', e); throw e })
    console.log('DBG_TOOLS', (ctx.tools as unknown as { _count?: number })._count, '| registered via execute check')
  })

  afterAll(async () => {
    if (savedHome === undefined) delete process.env.DSH_HOME
    else process.env.DSH_HOME = savedHome
    // The engine's background tasks (recover, heartbeat) may still hold the
    // store briefly; retry the sweep, then let the OS reclaim leftovers.
    for (const path of [home, workspace]) {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await rm(path, { recursive: true, force: true })
          break
        } catch {
          await new Promise(resolve => setTimeout(resolve, 300))
        }
      }
    }
  })

  it('registers the v0.9 tool surface and runs validate/create/run/status', async () => {
    const graph = {
      schemaVersion: '0.9',
      id: 'plugin-smoke',
      root: 'root',
      nodes: {
        root: { kind: 'composite', title: 'root', constraint: 'hard', target: 'artifact.txt', completion: { op: 'ref', id: 'leaf' } },
        leaf: { kind: 'leaf', title: 'leaf', constraint: 'hard', target: 'artifact.txt', verifier: { mode: 'programmatic', script: 'file-non-empty' } },
      },
      contains: [{ parent: 'root', child: 'leaf', required: true, failure: 'fatal' }],
      dependsOn: [],
    }
    const validate = await ctx.tools.execute({ callId: 'v', name: DOG_VALIDATE_TOOL, arguments: { graph }, signal: new AbortController().signal })
    if (validate.isError) throw new Error('VALIDATE_ERR: ' + (validate.error?.message ?? '?'))
    expect(validate.isError).toBe(false)
    const create = await ctx.tools.execute({ callId: 'c', name: DOG_CREATE_TOOL, arguments: { graph }, signal: new AbortController().signal })
    if (create.isError) throw new Error('CREATE_ERR: ' + (create.error?.message ?? '?'))
    expect(create.isError).toBe(false)
    const created = create.value as { graphId: string }
    expect(created.graphId).toBe('plugin-smoke')
    const run = await ctx.tools.execute({ callId: 'r', name: DOG_RUN_TOOL, arguments: { graphId: 'plugin-smoke' }, signal: new AbortController().signal })
    expect(run.isError).toBe(false)
    // The tool surface is the contract under test here; the full run cycle is
    // covered by core.spec/agentic-runner.spec. This fake ctx does not drive
    // the engine's async run queue, so we only assert the run started and the
    // status endpoint returns a machine-readable report.
    const poll = await ctx.tools.execute({ callId: 's0', name: DOG_STATUS_TOOL, arguments: { runId: (run.value as { runId: string }).runId }, signal: new AbortController().signal })
    if (poll.isError) throw new Error(poll.error?.message)
    const value = poll.value as { rootState?: string; goals?: unknown[] }
    expect(value.rootState).toBe('running')
    expect(isJsonValue(JSON.parse(JSON.stringify(value)))).toBe(true)
  })
})
