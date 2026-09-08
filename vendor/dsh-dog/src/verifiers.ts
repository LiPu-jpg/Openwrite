/** DoG v0.9 verification kernels: exactly two — programmatic (script) and agentic (LLM). */

import type { Agent } from '@deepseek-ai/dsh-agent'
import type { JsonValue, VerifierShape } from './model.ts'

/** A verdict is a two-field minimum: the judgment and free-form evidence. */
export interface Verdict {
 readonly state: 'pass' | 'fail' | 'inconclusive'
 readonly evidence: JsonValue
 readonly reason?: string
}

export interface IsolatedWorkspace {
 /** Absolute path of the mutually exclusive workspace directory. */
 readonly path: string
}

export interface VerifierExecutionEnv {
 readonly parent?: Agent | undefined
 readonly signal?: AbortSignal
 readonly runId?: string
 readonly goalId?: string
}

/** Programmatic kernel: runs a host-registered script with the captured object path. */
export type ProgrammaticRunner = (
 script: string,
 inputPath: string,
 env: VerifierExecutionEnv,
) => Promise<Verdict>

/** Agentic kernel: hands one natural-language instruction + the object to a worker agent. */
export type AgenticRunner = (
 instruction: string,
 workspace: IsolatedWorkspace,
 inputPath: string,
 env: VerifierExecutionEnv,
) => Promise<Verdict>

/** Result of one judgment, unified across both kernels. */
export interface Settlement {
 readonly state: 'pass' | 'fail' | 'inconclusive'
 readonly observation: Record<string, JsonValue>
 readonly evidence?: JsonValue
}

/**
 * Run one plan through the selected kernel. The engine holds none of the
 * judgment semantics: programmatic goes to a script, agentic to a worker agent
 * with only the instruction text — no parameter schema, no evidence format,
 * no tool allow-list.
 */
export async function runPlan(
 plan: { readonly verifier: VerifierShape; readonly target: string },
 workspace: IsolatedWorkspace,
 inputPath: string,
 env: VerifierExecutionEnv,
 programmatic: ProgrammaticRunner | undefined,
 agentic: AgenticRunner | undefined,
): Promise<Settlement> {
 if (plan.verifier.mode === 'programmatic') {
  if (programmatic === undefined) {
   return { state: 'inconclusive', observation: { outcome: 'programmatic kernel unavailable' } }
  }
  const verdict = await programmatic(plan.verifier.script, inputPath, env)
  return { state: verdict.state, observation: evidenceToObservation(verdict), evidence: verdict.evidence }
 }
 if (agentic === undefined) {
  return { state: 'inconclusive', observation: { outcome: 'agentic kernel unavailable' } }
 }
 const verdict = await agentic(plan.verifier.instruction, workspace, inputPath, env)
 return { state: verdict.state, observation: evidenceToObservation(verdict), evidence: verdict.evidence }
}

function evidenceToObservation(verdict: Verdict): Record<string, JsonValue> {
 const observation: Record<string, JsonValue> = { outcome: verdict.state }
 if (verdict.reason !== undefined) observation.reason = verdict.reason
 if (verdict.evidence !== undefined) observation.evidence = verdict.evidence
 return observation
}
