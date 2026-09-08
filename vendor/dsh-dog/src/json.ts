/** Deterministic JSON utilities used for graph and snapshot identities. */

import { createHash } from 'node:crypto'
import type { JsonValue } from './model.ts'

/**
 * Produce a deterministic JSON representation with recursively sorted object keys.
 * @param value - JSON-compatible input.
 * @returns canonical JSON text.
 */
export function canonicalJson(value: JsonValue | unknown): string {
  return JSON.stringify(sortJson(value))
}

/**
 * Hash a JSON-compatible value with SHA-256.
 * @param value - value to hash.
 * @returns a lower-case hexadecimal SHA-256 digest.
 */
export function sha256Json(value: JsonValue | unknown): string {
  return createHash('sha256').update(canonicalJson(value)).digest('hex')
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJson)
  if (value !== null && typeof value === 'object') {
    const result: Record<string, unknown> = {}
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      result[key] = sortJson((value as Record<string, unknown>)[key])
    }
    return result
  }
  return value
}
