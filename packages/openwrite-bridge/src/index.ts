/**
 * `@dsh-novel/openwrite-bridge`: a dsh plugin registering `novel_*` tools that
 * call the local OpenWrite Studio HTTP action surface. dsh owns agent
 * orchestration; OpenWrite owns the novel domain logic; this package is a thin
 * bridge over the HTTP contract only.
 */

import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'
import { NovelDomainService } from './domain.js'
import { registerNovelTools } from './tools.js'

export const name = '@dsh-novel/openwrite-bridge'
export const inject = ['tools']

export interface Config {
  /** Base URL of the local OpenWrite Studio server. */
  baseUrl: string
  /** Per-tool cooperative timeout in ms; chapter writing/review can take minutes. */
  timeoutMs: number
  /** Directory `novel_export` saves exported files into. */
  outputDir: string
}

export const Config: Schema<Config> = Schema.object({
  baseUrl: Schema.string().default('http://127.0.0.1:4567'),
  timeoutMs: Schema.number().default(600000),
  outputDir: Schema.string().default(join(tmpdir(), 'openwrite-exports')),
})

export function apply(ctx: Context, config: Config) {
  const domain = new NovelDomainService(ctx, { baseUrl: config.baseUrl, timeoutMs: config.timeoutMs })
  registerNovelTools(ctx, domain.client, { timeoutMs: config.timeoutMs, outputDir: config.outputDir })
  ctx.inject(['webServer'], webCtx => domain.registerWebRoutes(webCtx))
}
