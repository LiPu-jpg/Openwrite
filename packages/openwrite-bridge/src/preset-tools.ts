import z from '@deepseek-ai/schemastery'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type {} from './domain.js'
import { registerNovelTools } from './tools.js'
import { novelPolicyDenial } from './tool-policy.js'

export const name = '@dsh-novel/openwrite-tools'
export const inject = ['novelDomain', 'tools']

export const Config = z.object({ presentation: z.union(['native', 'ptc', 'both']).default('native') })

/** This row belongs in an Agent preset, never in the host bundle. */
export function apply(ctx: Context, config: { presentation?: 'native' | 'ptc' | 'both' } = {}): void {
  if (config.presentation && config.presentation !== 'native') ctx.effect(() => ctx.tools.presentAs(config.presentation!), 'openwrite: tool presentation')
  ctx.effect(() => ctx.tools.guard(execution => novelPolicyDenial(ctx, execution)), 'openwrite: execution policy')
  registerNovelTools(ctx, ctx.novelDomain.clientFactory(), {
    timeoutMs: ctx.novelDomain.toolOptions.timeoutMs,
    outputDir: ctx.novelDomain.toolOptions.outputDir ?? join(tmpdir(), 'openwrite-exports'),
  })
}
