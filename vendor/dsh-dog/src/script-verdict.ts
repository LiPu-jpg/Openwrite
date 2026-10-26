import { isJsonValue } from './model.ts'
import type { Verdict } from './verifiers.ts'
import { outputPreview, ScriptExecutionError } from './owned-script.ts'

export function scriptFailureVerdict(error: unknown): Verdict {
  const message = error instanceof Error ? error.message : String(error)
  return {
    state: 'inconclusive',
    reason: message,
    evidence: error instanceof ScriptExecutionError
      ? { code: error.code, error: message, ...error.diagnostics }
      : { code: 'SCRIPT_EXECUTION_FAILED', error: message },
  }
}

export function parseVerdict(out: string): Verdict {
  let value: unknown
  try { value = JSON.parse(out) } catch {
    return { state: 'inconclusive', evidence: { code: 'SCRIPT_OUTPUT_NOT_JSON', parseError: 'script output was not JSON', outputPreview: outputPreview(out) }, reason: 'script output was not JSON' }
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return { state: 'inconclusive', evidence: { code: 'SCRIPT_OUTPUT_INVALID', parseError: 'script output was not an object', outputPreview: outputPreview(out) }, reason: 'script output was not an object' }
  }
  const record = value as Record<string, unknown>
  const verdict = record.verdict
  if (verdict !== 'pass' && verdict !== 'fail' && verdict !== 'inconclusive') {
    return { state: 'inconclusive', evidence: { code: 'SCRIPT_OUTPUT_INVALID', parseError: 'invalid verdict', outputPreview: outputPreview(out) }, reason: 'script returned an invalid verdict' }
  }
  return { state: verdict, evidence: isJsonValue(record.evidence) ? record.evidence : { outcome: 'no evidence supplied by script' } }
}
