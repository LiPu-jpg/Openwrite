/** DeepSeek Harness DoG plugin entry: configuration, lifecycle, and tools. */

import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'
import type { } from '@deepseek-ai/dsh-client-connection'
import { runOwnedScript } from './owned-script.ts'
import { fileURLToPath } from 'node:url'
import { dshHomePath } from '@deepseek-ai/dsh-home-paths'
import type {} from '@deepseek-ai/dsh-settings'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { AgentRegistry } from '@deepseek-ai/dsh-agent'
import type { SessionId } from '@deepseek-ai/dsh-session'
import type { SubagentRuntime, SubagentInterruptAuthority } from '@deepseek-ai/dsh-subagent'
import type { JobRegistry } from '@deepseek-ai/dsh-jobs'
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'
import { writeFile } from 'node:fs/promises'
import { mkdir } from 'node:fs/promises'
import { isAbsolute, join } from 'node:path'
import z from '@deepseek-ai/schemastery'
import { DogEngine, resolveScriptPath } from './core.ts'
import { DOG_DEBUG_RPC_CHANNEL, createDogDebugRpcHandler } from './debug.ts'
import { loadSchemaSet } from './schema.ts'
import { DogRepository } from './storage.ts'
import { createDogDelegateAgentTool, createDogTools } from './tools.ts'
import { isJsonValue } from './model.ts'
import { WorkspaceManager } from './workspace.ts'
import { waitForSettlementFlexible } from './verifier-file.ts'
import type { AgenticRunner, ProgrammaticRunner, Verdict } from './verifiers.ts'


export { DogEngine } from './core.ts'
export {
  DOG_DEBUG_RPC_CHANNEL,
  DOG_DEBUG_SNAPSHOT_ENDPOINT,
  DOG_RUNTIME_TRACE_ENDPOINT,
  buildDogDebugSnapshot,
  buildGoalRuntimeTrace,
  createDogDebugRpcHandler,
} from './debug.ts'
export type { DogDebugGraphRevision, DogDebugSnapshot } from './debug.ts'
export { DogValidationError, parseGraph } from './graph.ts'
export { evaluateBoolExpr, parseBoolExpr } from './logic.ts'
export { runPlan, type AgenticRunner, type ProgrammaticRunner, type Verdict } from './verifiers.ts'
export { WorkspaceManager } from './workspace.ts'
export { loadSchemaSet } from './schema.ts'
export {
  DOG_BIND_AGENT_TOOL,
  DOG_CREATE_TOOL,
  DOG_DELEGATE_AGENT_TOOL,
  DOG_RUN_TOOL,
  DOG_STATUS_TOOL,
  DOG_WAIT_TOOL,
  DOG_VALIDATE_TOOL,
  createDogDelegateAgentTool,
  createDogTools,
} from './tools.ts'
export type * from './model.ts'

/** Cordis plugin name. */
export const name = 'dsh-dog'
/** Required Harness services. */
export const inject = ['tools', 'subagents']

declare module '@deepseek-ai/cordis' { interface Context { openwriteDog: { tools: ToolDefinition[] } } }

/** Host-owned deployment configuration. */
export interface Config {
  storageDirectory: string
  /** Verifier workspace root (WorkspaceManager.baseDir): verifiers only read files inside this tree. */
  workspaceRoot: string
  /** Host-registered programmatic script library (relative to DSH_HOME, or absolute). */
  scriptsDirectory: string
  maxGraphNodes: number
  maxExpressionNodes: number
  maxExpressionDepth: number
  maxSandboxBytes: number
  allowPartialRoot: boolean
  maxConcurrentVerifications: number
  revalidateThreshold: number
  gmDigestAlgo: string
  subagentProvider: string
  subagentMaxDepth: number
}

/** Loader-validated DoG deployment configuration. */
export const Config: z<Config> = z.object({
  storageDirectory: z.string().default('dog'),
  workspaceRoot: z.string().default('dog/workspace'),
  scriptsDirectory: z.string().default(fileURLToPath(new URL('../../../scripts/dog/', import.meta.url))),
  maxGraphNodes: z.natural().min(1).default(256),
  maxExpressionNodes: z.natural().min(1).default(512),
  maxExpressionDepth: z.natural().min(1).default(64),
  maxSandboxBytes: z.natural().min(1).default(67_108_864),
  allowPartialRoot: z.boolean().default(false),
  maxConcurrentVerifications: z.natural().min(1).default(1),
  revalidateThreshold: z.number().default(0.3),
  gmDigestAlgo: z.string().default('sha256'),
  subagentProvider: z.string().default('spawn'),
  subagentMaxDepth: z.natural().default(3),
})

/** Register all DoG tools as Cordis-owned effects so fiber disposal removes them. */
export async function apply(ctx: Context, config: Config): Promise<void> {
  const schema = await loadSchemaSet()
  let resolved: Config = config
  let settingsCurrent: (() => Config) | undefined
  ctx.inject(['settings'], settingsCtx => settingsCtx.settings.installSection(
    ctx,
    'dog',
    z.object({
      storageDirectory: z.string().default('dog'),
      workspaceRoot: z.string().default('dog/workspace'),
      scriptsDirectory: z.string().default(fileURLToPath(new URL('../../../scripts/dog/', import.meta.url))),
      maxGraphNodes: z.natural().min(1).default(256),
      maxExpressionNodes: z.natural().min(1).default(512),
      maxExpressionDepth: z.natural().min(1).default(64),
      maxSandboxBytes: z.natural().min(1).default(67_108_864),
      allowPartialRoot: z.boolean().default(false),
      maxConcurrentVerifications: z.natural().min(1).default(1),
      revalidateThreshold: z.number().default(0.3),
      gmDigestAlgo: z.string().default('sha256'),
      subagentProvider: z.string().default('spawn'),
      subagentMaxDepth: z.natural().default(3),
    }),
    config,
    {
      setSource: (current: () => Config) => {
        settingsCurrent = current
        resolved = { ...config, ...current() }
      },
      onChange: () => undefined,
    },
  ))
  const repository = new DogRepository(dshHomePath(config.storageDirectory), schema)
  // Host boot: cancel runs a previous process left `running` (killed/restarted
  // host) as soon as the plugin loads — before any engine or tool call. Their
  // settled leaves remain inheritable by the next run of the same graph.
  void repository.markOrphanedRunningRuns(new Date().toISOString()).catch(() => undefined)
  const scriptsDir = isAbsolute(config.scriptsDirectory) ? config.scriptsDirectory : dshHomePath(config.scriptsDirectory)
  const programmatic: ProgrammaticRunner = async (script, inputPath, env) => {
    let out: string
    try {
      out = await runOwnedScript(resolveScriptPath(scriptsDir, script), inputPath, env.signal)
    } catch (error) {
      return {
        state: 'inconclusive',
        evidence: { error: String(error instanceof Error ? error.message : error) },
        reason: 'script execution failed',
      }
    }
    return parseVerdict(out)
  }
  let dogEngine: DogEngine | undefined
  ctx.effect(() => async () => { await dogEngine?.dispose() })
  let agenticRunnerRef: AgenticRunner | undefined
  let subagentRuntimeRef: SubagentRuntime | undefined
  // Live verifier subagents keyed by session id — dog_cancel interrupts them.
  const activeVerifiers = new Map<string, { readonly parent: Agent; readonly runId: string }>()
  const getEngine = (): DogEngine => {
    if (dogEngine === undefined) {
      // settingsCurrent re-reads the live scope: the initial registration may
      // have resolved before the settings file finished loading (async), which
      // would otherwise freeze schema defaults (e.g. a relative workspaceRoot).
      const effective = settingsCurrent === undefined ? resolved : { ...config, ...settingsCurrent() }
      dogEngine = new DogEngine({
        config: {
          ...effective,
          workspaceRoot: isAbsolute(effective.workspaceRoot) ? effective.workspaceRoot : dshHomePath(effective.workspaceRoot),
          scriptsDirectory: isAbsolute(effective.scriptsDirectory) ? effective.scriptsDirectory : dshHomePath(effective.scriptsDirectory),
        },
        programmatic,
        ...(agenticRunnerRef === undefined ? {} : { agentic: agenticRunnerRef }),
        repository,
        workspaces: new WorkspaceManager({ baseDir: effective.workspaceRoot }),
        onRunCancelled: runId => {
          for (const [sessionId, record] of activeVerifiers) {
            if (record.runId !== runId) continue
            try {
              subagentRuntimeRef?.interrupt(
                sessionId as SessionId,
                { kind: 'ancestor', agent: record.parent } satisfies SubagentInterruptAuthority,
              )
            } catch {
              // best-effort; the run record is already cancelled
            }
          }
        },
        liveConfig: () => {
          const live = settingsCurrent?.()
          return live === undefined ? {} : { maxConcurrentVerifications: live.maxConcurrentVerifications }
        },
        resolveLivingAgent: sessionId => {
          const agents = ctx.get('agents') as AgentRegistry | undefined
          return agents?.get(sessionId as SessionId)
        },
      })
    }
    return dogEngine
  }
  const scopedTools = [...createDogTools(getEngine, () => ctx.get('jobs') as JobRegistry | undefined)]
  ctx.provide('openwriteDog', { tools: scopedTools })
  ctx.inject(['subagents'], (subagentCtx) => {
    const subagents: SubagentRuntime = subagentCtx.subagents
    subagentRuntimeRef = subagents
    const agenticRunner: AgenticRunner = async (instruction, workspace, inputPath, env) => {
      const { parent, runId } = env
      const signal = env.signal ?? new AbortController().signal
      const goalId = env.goalId ?? 'verification'
      const resultPath = join(workspace.path, 'settlement.json')
      const parentSessionId = readSessionId(parent)
      if (parent === undefined) {
        throw new Error('verifier delegation requires a live parent Agent (recovered runs without a live parent cannot spawn verification workers)')
      }
      const started = await subagents.startContinuable({
        provider: config.subagentProvider,
        label: `verifier ${goalId} · ${runId === undefined ? 'run' : runId.slice(0, 6)}`,
        request: {
          prompt: [{ type: 'text', text: buildVerifierPrompt(instruction, inputPath, resultPath) }],
          parent,
          maxDepth: config.subagentMaxDepth,
        },
        signal,
      })
      const sessionId = started.childId
      activeVerifiers.set(sessionId, { parent, runId: runId ?? '' })
      if (runId !== undefined) {
        try {
          await getEngine().annotateRun(runId, `bind-branch entered for ${goalId}: session ${sessionId.slice(0, 8)}`)
          const binding = await getEngine().bindAgent(
            {
              runId,
              goalId,
              role: 'verifier',
              sessionId,
              ...(parentSessionId.length > 0 ? { parentSessionId } : {}),
            },
            { allowUnrooted: parentSessionId.length === 0 },
          )
          await getEngine().annotateRun(
            runId,
            `verifier bound for ${goalId}: ${sessionId.slice(0, 8)} (${binding.run.goals[goalId]?.agentSessions?.length ?? 0} bound)`,
          )
        } catch (bindingError) {
          await getEngine().annotateRun(runId, `verifier binding failed for ${goalId}: ${String(bindingError).slice(0, 300)}`)
          await getEngine().recordVerifierLifecycle(runId, goalId, 'verifier_bind_failed', sessionId, String(bindingError))
        }
      }
      const settlement = await waitForSettlementFlexible(
        resultPath,
        signal,
        900_000,
        async () => verifierChildTurnEnded(ctx, sessionId),
      )
      if (settlement.source !== undefined && runId !== undefined) {
        // The verifier workspace is reclaimed at run teardown; keep the
        // verbatim judgment on disk so 'what happened' stays inspectable.
        void repository.saveSettlement(runId, goalId, settlement.source).catch(() => undefined)
      }
      if (runId !== undefined && parent !== undefined && parentSessionId.length > 0) {
        try {
          // Quiet release: interrupting a finished-but-not-yet-released child
          // emits "Background subagent … was stopped" notifications into the
          // parent session, which interrupt a parent-turn that is blocked in
          // dog_wait. drainContinuableChildren releases the Activation/session
          // handle without that notification storm.
          await subagents.drainContinuableChildren(parent, [sessionId])
          activeVerifiers.delete(sessionId)
          await getEngine().recordVerifierLifecycle(runId, goalId, 'verifier_released', sessionId)
        } catch (releaseError) {
          await getEngine().annotateRun(runId, `verifier release failed for ${goalId}: ${String(releaseError).slice(0, 300)}`)
        }
      }
      return { state: settlement.state, evidence: settlement.observation }
    }
    agenticRunnerRef = agenticRunner
    const delegateTool = createDogDelegateAgentTool(getEngine, {
      async launch(input) {
        const started = await subagents.startContinuable({
          provider: config.subagentProvider,
          label: input.label,
          request: {
            prompt: [{ type: 'text', text: input.prompt }],
            parent: input.parent,
            maxDepth: config.subagentMaxDepth,
          },
          signal: input.signal,
        })
        return { sessionId: started.childId }
      },
      interrupt(sessionId, parent) {
        subagents.interrupt(sessionId, { kind: 'ancestor', agent: parent } satisfies SubagentInterruptAuthority)
      },
    })
    scopedTools.push(delegateTool)
  })
  const debugHandler = createDogDebugRpcHandler(repository)
  // Runtime forensic capture: whenever a session turn is interrupted, snapshot
  // the on-scene facts (process uptime, recent event sequence, seed boundary)
  // so the next incident carries its own evidence instead of post-hoc guessing.
  ctx.on('session/event', (session: Session, event: SessionEvent) => {
    if (event.type !== 'turn/end') return
    const reason = (event.data as { readonly reason?: { readonly kind?: string } }).reason
    if (reason?.kind !== 'interrupted') return
    void captureInterruptedTurn(repository, session, event as { readonly seq: number; readonly time: number }).catch(() => undefined)
  })
  ctx.inject(['connection'], (connectionCtx) => {
    connectionCtx.effect(() => connectionCtx.connection.rpc.handle(
      DOG_DEBUG_RPC_CHANNEL,
      debugHandler,
    ), 'dog: trusted debugger RPC')
  })
}

async function captureInterruptedTurn(
  repository: DogRepository,
  session: Session,
  event: { readonly seq: number; readonly time: number },
): Promise<void> {
  const diagnosticsDir = join(repository.rootPath, 'diagnostics')
  await mkdir(diagnosticsDir, { recursive: true })
  const recentEvents = session.snapshotEvents().slice(-12).map(candidate => ({
    seq: candidate.seq,
    type: candidate.type,
    time: candidate.time,
  }))
  const payload = {
    capturedAt: new Date().toISOString(),
    process: {
      pid: process.pid,
      startedAt: new Date(Date.now() - process.uptime() * 1000).toISOString(),
    },
    sessionId: session.id,
    interruptSeq: event.seq,
    interruptEventTime: new Date(event.time).toISOString(),
    recentEvents,
  }
  await writeFile(
    join(diagnosticsDir, `interrupt-${session.id.replaceAll(/[^a-zA-Z0-9-]/gu, '_')}-${event.seq}.json`),
    JSON.stringify(payload, null, 2),
  )
}

function buildVerifierPrompt(
  instruction: string,
  inputPath: string,
  resultPath: string,
): string {
  return [
    'You are a DoG verifier. Judge only the object handed to you.',
    '',
    `Object (read from here; only this tree is yours): ${inputPath}`,
    '',
    'Instruction:',
    instruction,
    '',
    'Decide on your own terms; gather the strongest evidence you can with your own judgment. No fixed evidence format.',
    `Write your verdict to this exact absolute path: ${resultPath}. The file must contain exactly:`,
    '{"verdict": "pass" | "fail" | "inconclusive", "evidence": <any JSON>}',
    'Create it (it does not exist yet); never write it as a relative path or to another location. After writing, stop.',
  ].join('\n')
}

function parseVerdict(out: string): Verdict {
  let value: unknown
  try {
    value = JSON.parse(out)
  } catch {
    return { state: 'inconclusive', evidence: { parseError: 'script output was not JSON' }, reason: 'script output was not JSON' }
  }
  const record = value as Record<string, unknown>
  if (record === null || typeof record !== 'object' || Array.isArray(record)) {
    return { state: 'inconclusive', evidence: { parseError: 'script output was not an object' }, reason: 'script output was not an object' }
  }
  const verdict = record.verdict
  if (verdict !== 'pass' && verdict !== 'fail' && verdict !== 'inconclusive') {
    return { state: 'inconclusive', evidence: { parseError: 'invalid verdict' }, reason: 'script returned an invalid verdict' }
  }
  return {
    state: verdict,
    evidence: isJsonValue(record.evidence) ? record.evidence : { outcome: 'no evidence supplied by script' },
  }
}

/** Read the durable session id from a live Agent, or '' outside an agent boundary. */
function readSessionId(parent: Agent | undefined): string {
  if (parent === undefined) return ''
  return String(parent.id)
}

/** True once the verifier child's turn has ended (or the child is gone entirely). */
function verifierChildTurnEnded(ctx: Context, sessionId: string): boolean {
  const agents = ctx.get('agents') as AgentRegistry | undefined
  const agent = agents?.get(sessionId as SessionId)
  if (agent === undefined) return true
  return agent.session.snapshotEvents().at(-1)?.type === 'turn/end'
}
