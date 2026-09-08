import type { JsonValue } from '@deepseek-ai/dsh-util-values'
/** Model-facing DoG tools over the verification-first engine. */

import { defineTool, type ToolDefinition } from '@deepseek-ai/dsh-tools'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { SessionId } from '@deepseek-ai/dsh-session'
import type { JobRegistry } from '@deepseek-ai/dsh-jobs'

declare module '@deepseek-ai/dsh-jobs' {
  interface JobKindMap {
    dog: 'dog'
  }
}
import { DogEngine } from './core.ts'
import { isJsonValue } from './model.ts'
import type { CiReport, CompiledGraph, DogRun, GoalResult } from './model.ts'

export interface DogAgentLauncher {
  launch(input: {
    readonly label: string
    readonly prompt: string
    readonly parent: Agent
    readonly signal: AbortSignal
  }): Promise<{ readonly sessionId: SessionId }>
  interrupt?(sessionId: SessionId, parent: Agent): void | Promise<void>
}

export const DOG_VALIDATE_TOOL = 'dog_validate'
export const DOG_CREATE_TOOL = 'dog_create'
export const DOG_RUN_TOOL = 'dog_run'
export const DOG_BIND_AGENT_TOOL = 'dog_bind_agent'
export const DOG_DELEGATE_AGENT_TOOL = 'dog_delegate_agent'
export const DOG_STATUS_TOOL = 'dog_status'
export const DOG_CANCEL_TOOL = 'dog_cancel'
export const DOG_WAIT_TOOL = 'dog_wait'

const JSON_OUTPUT = {
  schema: { type: 'json' as const },
  render: (_args: unknown, value: JsonValue) => [{ type: 'text' as const, text: JSON.stringify(value, null, 2) }],
}

/** Build the complete DoG v0.1 tool surface around one engine instance. */
export function createDogTools(
  engine: () => DogEngine,
  hostJobs: () => JobRegistry | undefined = () => undefined,
): readonly ToolDefinition[] {
  return [
    defineTool({
      name: DOG_VALIDATE_TOOL,
      description: 'Statically validate a DoG v0.2 graph. This does not write files, capture sandbox files, or run goals.',
      parameters: {
        graph: { type: 'json', required: true, description: 'Complete JSON DoG graph using schemaVersion 0.2.' },
      },
      output: JSON_OUTPUT,
      isConcurrencySafe: () => true,
      execute: async (args, exec) => {
        exec.signal.throwIfAborted()
        return jsonResult(engine().validate(args.graph))
      },
    }),
    defineTool({
      name: DOG_CREATE_TOOL,
      description: 'Compile and persist a valid DoG v0.2 graph, capturing verifier input files from the configured sandbox as immutable bytes.',
      parameters: {
        graph: { type: 'json', required: true, description: 'Complete JSON DoG graph using schemaVersion 0.2.' },
      },
      output: JSON_OUTPUT,
      async execute(args, exec) {
        exec.signal.throwIfAborted()
        const cwd = exec.agent?.session.header.cwd
        const compiled = await engine().create(
          args.graph,
          typeof cwd === 'string' && cwd.length > 0 ? { captureBaseDir: cwd } : {},
        )
        exec.signal.throwIfAborted()
        return jsonResult(compiledGraphSummary(compiled))
      },
    }),
    defineTool({
      name: DOG_RUN_TOOL,
      description: 'Run trusted atomic verification for the latest persisted revision of a graph and recompute its root result.',
      parameters: {
        graphId: { type: 'string', required: true, description: 'Graph ID previously persisted by dog_create.' },
      },
      output: JSON_OUTPUT,
      async execute(args, exec) {
        exec.signal.throwIfAborted()
        const run = await engine().startRun(args.graphId, {
          invocation: {
            callId: String(exec.callId),
            ...(exec.agent === undefined ? {} : { agentSessionId: String(exec.agent.id) }),
            ...(exec.agent?.session.header.parentSession === undefined ? {} : {
              parentSessionId: String(exec.agent.session.header.parentSession),
            }),
          },
          ...(exec.agent === undefined ? {} : { agent: exec.agent }),
        })
        exec.signal.throwIfAborted()
        return jsonResult(Object.assign({}, runSummary(run), {
          note: 'verification runs in the background; agentic leaves spawn verifier Agents that live in THIS process. '
            + 'If this is a one-shot launch (e.g. dsh --profile headless), the process exits after answering and '
            + 'verifier workers are interrupted: background agentic verification requires a resident host process. '
            + 'Poll with dog_status.',
        }))
      },
    }),
    defineTool({
      name: DOG_BIND_AGENT_TOOL,
      description: 'Bind the current trusted DSH Agent session to one goal in an existing DoG run. Use dog_delegate_agent instead when creating a new worker that must remain directly interactive after its first turn. Session identity is captured from the tool execution context and cannot be supplied by the model.',
      parameters: {
        runId: { type: 'string', required: true, description: 'Run ID returned by dog_run.' },
        goalId: { type: 'string', required: true, description: 'Goal ID this Agent is working on or verifying.' },
        role: {
          type: 'string',
          required: true,
          enum: ['orchestrator', 'verifier', 'reviewer'] as const,
          description: 'The Agent role for this goal.',
        },
      },
      output: JSON_OUTPUT,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        exec.signal.throwIfAborted()
        if (exec.agent === undefined) throw new Error('dog_bind_agent requires a trusted DSH Agent execution context')
        const binding = await engine().bindAgent({
          runId: args.runId,
          goalId: args.goalId,
          role: args.role,
          sessionId: String(exec.agent.id),
          ...(exec.agent.session.header.parentSession === undefined ? {} : {
            parentSessionId: String(exec.agent.session.header.parentSession),
          }),
        })
        exec.signal.throwIfAborted()
        return jsonResult({
          runId: binding.run.runId,
          goalId: args.goalId,
          agent: binding.agent,
        })
      },
    }),
    defineTool({
      name: DOG_STATUS_TOOL,
      description: 'Read the bounded persisted status and verifier evidence for one DoG run.',
      parameters: {
        runId: { type: 'string', required: true, description: 'Run ID returned by dog_run.' },
      },
      output: JSON_OUTPUT,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        exec.signal.throwIfAborted()
        const run = await engine().status(args.runId)
        exec.signal.throwIfAborted()
        return jsonResult(runSummary(run))
      },
    }),
    defineTool({
      name: DOG_WAIT_TOOL,
      description: 'Wait for one DoG run to settle. Preferred path: when the host job service is available this registers a background '
        + '"dog" job (returns instantly with jobId) and the harness notifies you automatically when the run completes — inspect with job_output, '
        + 'cancel with job_kill. Fallback (no job service, e.g. a bare one-shot process): returns the current state instantly and you must '
        + 'call dog_wait repeatedly until the state is terminal; each poll keeps the calling session and process alive, which protects '
        + 'the verifier workers the run spawned. Always wait until the returned state is terminal before summarizing — finishing early '
        + 'releases the workers. Same report shape as dog_status.',
      parameters: {
        runId: { type: 'string', required: true, description: 'Run ID returned by dog_run.' },
        timeout: { type: 'number', description: 'Advisory total wait budget in seconds; not enforced (each call returns instantly).' },
      },
      output: JSON_OUTPUT,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        exec.signal.throwIfAborted()
        const run = await engine().status(args.runId)
        exec.signal.throwIfAborted()
        const jobs = hostJobs()
        if (jobs !== undefined && run.state === 'running') {
          const controller = new AbortController()
          const done = engine().waitRun(args.runId, { signal: controller.signal, timeoutMs: 120 * 60_000 })
            .then(settled => ({
              status: 'completed' as const,
              output: JSON.stringify(runSummary(settled)),
            }))
            .catch((error: unknown) => ({
              status: controller.signal.aborted ? ('killed' as const) : ('failed' as const),
              detail: String(error instanceof Error ? error.message : error).slice(0, 200),
            }))
          const jobId = jobs.start({
            kind: 'dog',
            label: `DoG wait ${String(args.runId).slice(0, 8)}`,
            ...(exec.agent === undefined ? {} : { owner: exec.agent }),
            run: () => ({
              cancel: (reason?: string) => {
                controller.abort(new Error(reason ?? 'cancelled'))
              },
              done,
            }),
          })
          return jsonResult({
            runId: run.runId,
            graphId: run.graphId,
            state: run.state,
            jobId,
            note: 'background wait job registered; the harness will notify you when the run completes (that is the wait). '
              + 'NEVER call job_output with wait:true — a long wait gets interrupted by background notices and that interruption '
              + 'is expected; if an unofficial job_output result comes back interrupted, just keep your current turn alive or reply with another dog_wait.',
          })
        }
        return jsonResult(Object.assign({}, runSummary(run), {
          ...(run.state === 'running' ? {
            note: 'instant poll: the run is still running (this call returned immediately and cannot be interrupted). '
              + 'Call dog_wait again, repeatedly, until the state is terminal.',
          } : {}),
        }))
      },
    }),
    defineTool({
      name: DOG_CANCEL_TOOL,
      description: 'Cancel one running DoG run and its verifier workers; partial records remain inspectable.',
      parameters: {
        runId: { type: 'string', required: true, description: 'Run ID returned by dog_run.' },
        reason: { type: 'string', description: 'Bounded human-readable cancellation reason.' },
      },
      output: JSON_OUTPUT,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        exec.signal.throwIfAborted()
        const runId = args.runId
        const reason = typeof args.reason === 'string' && args.reason.length > 0 ? args.reason : 'cancelled by operator'
        const cancelled = await engine().cancelRun(runId, reason)
        exec.signal.throwIfAborted()
        return jsonResult(runSummary(cancelled))
      },
    }),
  ]
}

/** Build the DoG-aware continuable Agent launcher once the host subagent service is available. */
export function createDogDelegateAgentTool(engine: () => DogEngine, launcher: DogAgentLauncher): ToolDefinition {
  return defineTool({
    name: DOG_DELEGATE_AGENT_TOOL,
    description: 'Start a durable continuable DSH Agent for one DoG goal and bind its host-issued session identity to the run. The child remains directly interactive in the session UI after its first turn. Use this instead of a foreground or one-shot subagent for user-addressable DoG workers.',
    parameters: {
      runId: { type: 'string', required: true, description: 'Run ID returned by dog_run.' },
      goalId: { type: 'string', required: true, description: 'Goal ID assigned to the new Agent.' },
      role: {
        type: 'string',
        required: true,
        enum: ['orchestrator', 'verifier', 'reviewer'] as const,
        description: 'The Agent role for this goal.',
      },
      label: { type: 'string', required: true, description: 'Short human-readable Agent label shown in the session tree.' },
      prompt: { type: 'string', required: true, description: 'Complete first-turn assignment for the Agent.' },
    },
    output: JSON_OUTPUT,
    async execute(args, exec) {
      exec.signal.throwIfAborted()
      if (exec.agent === undefined) throw new Error('dog_delegate_agent requires a trusted DSH Agent execution context')
      const parentSessionId = String(exec.agent.id)
      await engine().assertAgentCanDelegate({
        runId: args.runId,
        goalId: args.goalId,
        parentSessionId,
      })
      exec.signal.throwIfAborted()
      const child = await launcher.launch({
        label: args.label,
        prompt: args.prompt,
        parent: exec.agent,
        signal: exec.signal,
      })
      if (child.sessionId.length === 0) throw new Error('DoG Agent launcher returned an empty child session ID')
      try {
        const binding = await engine().bindAgent({
          runId: args.runId,
          goalId: args.goalId,
          role: args.role,
          sessionId: child.sessionId,
          parentSessionId,
        })
        return jsonResult({
          runId: binding.run.runId,
          goalId: args.goalId,
          lifecycle: 'continuable',
          agent: binding.agent,
        })
      } catch (error) {
        try {
          await launcher.interrupt?.(child.sessionId, exec.agent)
        } catch {
          // Preserve the authoritative binding failure; interruption is only best-effort cleanup.
        }
        throw error
      }
    },
  })
}

function compiledGraphSummary(compiled: CompiledGraph): JsonValue {
  return {
    graphId: compiled.input.id,
    graphDigest: compiled.graphDigest,
    acceptancePlans: Object.values(compiled.acceptancePlans).map(plan => ({
      goalId: plan.goalId,
      mode: plan.verifier.mode,
      ...(plan.verifier.mode === 'programmatic' ? { script: plan.verifier.script } : { instruction: plan.verifier.instruction }),
      target: plan.target,
      ...(plan.input === undefined ? {} : { inputPath: plan.input.path, digest: plan.input.digest, exists: plan.input.exists, byteLength: plan.input.byteLength }),
    })),
  }
}

function ciReport(run: DogRun): CiReport {
  const goals = Object.entries(run.goals).map(([goalId, result]) => goalReport(goalId, result))
  const revalidated = Object.entries(run.gmDigests)
    .filter(([goalId]) => run.goals[goalId]?.state !== 'inherited')
    .map(([goalId]) => goalId)
  const inherited = Object.entries(run.goals)
    .filter(([, result]) => result.state === 'inherited')
    .map(([goalId, result]) => ({
      goalId,
      fromRunId: result.inheritedFrom ?? run.runId,
      state: 'inherited' as const,
    }))
  const warning = revalidateWarning(run, revalidated)
  return {
    runId: run.runId,
    graphId: run.graphId,
    ...(run.graphDigest === undefined ? {} : { graphDigest: run.graphDigest }),
    rootState: run.rootState ?? (run.state === 'running' ? 'running' : 'cancelled'),
    goals: goals.sort((left, right) => left.goalId.localeCompare(right.goalId)),
    revalidated,
    inherited,
    ...(warning === undefined ? {} : { warning }),
    generatedAt: run.updatedAt,
  }
}

function goalReport(goalId: string, result: GoalResult): CiReport['goals'][number] {
  const verification = result.verification
  return {
    goalId,
    state: result.state,
    ...(verification === undefined ? {} : {
      verifier: {
        mode: verification.judgment.mode,
      },
    }),
    ...(verification === undefined || verification.evidence === undefined ? {} : { evidence: [verification.evidence as unknown as Record<string, JsonValue>] }),
    ...(result.reason === undefined ? {} : { defect: result.reason }),
  }
}

function revalidateWarning(run: DogRun, revalidated: readonly string[]): string | undefined {
  void revalidated
  const warning = run.runtimeWarning
  return warning === undefined ? undefined : warning
}

function runSummary(run: DogRun): JsonValue {
  return ciReport(run) as unknown as JsonValue
}

function jsonResult(value: unknown): JsonValue {
  if (!isJsonValue(value)) throw new Error('DoG produced a non-JSON tool result')
  return value
}
