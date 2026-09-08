/** File-backed settlement channel for continuable verifier subagents. */

import { readFile } from 'node:fs/promises'
import type { JsonValue } from './model.ts'

export interface SettlementFileSummary {
 readonly state: 'pass' | 'fail' | 'inconclusive'
 readonly observation: Record<string, JsonValue>
 readonly waitedMs: number
 /** The verbatim settlement text (present only when the file was readable). */
 readonly source?: string
}

/**
 * Wait (bounded polling) for a continuable verifier subagent to write its
 * settlement JSON to `resultPath`. Returns inconclusive on timeout or abort
 * instead of throwing, so the verification turn always settles honestly.
 */
export async function waitForSettlement(
 resultPath: string,
 signal: AbortSignal,
 timeoutMs: number,
): Promise<SettlementFileSummary> {
 const startAt = Date.now()
 while (Date.now() - startAt < timeoutMs) {
  if (signal.aborted) return { state: 'inconclusive', observation: { outcome: 'aborted' }, waitedMs: Date.now() - startAt }
  try {
   const source = await readFile(resultPath, 'utf8')
   return { ...parseSettlementFile(source), source, waitedMs: Date.now() - startAt }
  } catch (error) {
   if (isMissing(error)) {
    await sleep(500)
    continue
   }
   return { state: 'inconclusive', observation: { outcome: 'unreadable settlement file' }, waitedMs: Date.now() - startAt }
  }
 }
 return { state: 'inconclusive', observation: { outcome: 'timed out waiting for verifier result' }, waitedMs: Date.now() - startAt }
}

/**
 * Same as {@link waitForSettlement}, but short-circuits once the verifier child
 * has finished its turn: if the settlement file is still absent shortly after
 * the child's turn ended, the child is not coming back — settle inconclusive
 * immediately instead of blocking the run for the full timeout.
 */
export async function waitForSettlementFlexible(
 resultPath: string,
 signal: AbortSignal,
 timeoutMs: number,
 childSettled: () => Promise<boolean>,
): Promise<SettlementFileSummary> {
 const startAt = Date.now()
 while (Date.now() - startAt < timeoutMs) {
  if (signal.aborted) return { state: 'inconclusive', observation: { outcome: 'aborted' }, waitedMs: Date.now() - startAt }
  try {
   const source = await readFile(resultPath, 'utf8')
   return { ...parseSettlementFile(source), source, waitedMs: Date.now() - startAt }
  } catch (error) {
   if (!isMissing(error)) {
    return { state: 'inconclusive', observation: { outcome: 'unreadable settlement file' }, waitedMs: Date.now() - startAt }
   }
   if (await childSettled()) {
    // Subagent turns may end while the model is still composing the file
    // (multi-turn fixes); the workspace now outlives the turn, so give a
    // generous last-write window before settling inconclusive.
    await sleep(15_000)
    try {
     const source = await readFile(resultPath, 'utf8')
     return { ...parseSettlementFile(source), source, waitedMs: Date.now() - startAt }
    } catch {
     return { state: 'inconclusive', observation: { outcome: 'verifier child finished without writing the settlement file' }, waitedMs: Date.now() - startAt }
    }
   }
   await sleep(500)
  }
 }
 return { state: 'inconclusive', observation: { outcome: 'timed out waiting for verifier result' }, waitedMs: Date.now() - startAt }
}

export function parseSettlementFile(source: string): { readonly state: 'pass' | 'fail' | 'inconclusive'; readonly observation: Record<string, JsonValue> } {
 const value = parseLooseJson(source)
 if (value === null || typeof value !== 'object' || Array.isArray(value)) {
  return { state: 'inconclusive', observation: { outcome: 'settlement file is not a JSON object' } }
 }
 const raw = value as Record<string, unknown>
 // 0.9 contract: {"verdict": "pass|fail|inconclusive", "evidence": <any JSON>}.
 // Accept the pre-0.9 {"settlement", "observation"} spelling as a fallback.
 const state = raw.verdict ?? raw.settlement
 if (state !== 'pass' && state !== 'fail' && state !== 'inconclusive') {
  return { state: 'inconclusive', observation: { outcome: 'settlement file has an invalid settlement value' } }
 }
 const observation = raw.evidence ?? raw.observation
 if (observation === undefined) {
  return { state: 'inconclusive', observation: { outcome: 'settlement file has no observation evidence' } }
 }
 if (observation === null || typeof observation !== 'object' || Array.isArray(observation)) {
  return { state: 'inconclusive', observation: { outcome: 'settlement observation is not an object' } }
 }
 const record: Record<string, JsonValue> = {}
 for (const [key, item] of Object.entries(observation)) {
  if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean' || item === null) {
   record[key] = item
  } else if (Array.isArray(item) || typeof item === 'object') {
   if (isJsonValueLike(item)) record[key] = item
  }
 }
 if (Object.keys(record).length === 0) record.settled = state
 return { state, observation: record }
}

/** Parse a settlement payload leniently: strip markdown fences, then try to extract the outermost JSON object. */
function parseLooseJson(source: string): unknown {
 let text = source.trim()
 if (text.startsWith('```')) {
  text = text.replace(/^```[A-Za-z]*\s*/u, '').replace(/\s*```\s*$/u, '')
  text = text.trim()
 }
 try {
  return JSON.parse(text) as unknown
 } catch {
  const start = text.indexOf('{')
  if (start < 0) throw new Error('no JSON object found')
  let depth = 0
  for (let index = start; index < text.length; index++) {
   const ch = text[index]
   if (ch === '{') depth++
   else if (ch === '}') {
    depth--
    if (depth === 0) {
     return JSON.parse(text.slice(start, index + 1)) as unknown
    }
   }
  }
 }
 throw new Error('no complete JSON object found')
}

function isJsonValueLike(value: unknown): boolean {
 if (value === null || typeof value === 'string' || typeof value === 'boolean') return true
 if (typeof value === 'number') return Number.isFinite(value)
 if (Array.isArray(value)) return value.every(isJsonValueLike)
 if (typeof value !== 'object') return false
 return Object.values(value).every(isJsonValueLike)
}

function isMissing(error: unknown): boolean {
 return error instanceof Error && 'code' in error && error.code === 'ENOENT'
}

function sleep(ms: number): Promise<void> {
 return new Promise(resolve => setTimeout(resolve, ms))
}
