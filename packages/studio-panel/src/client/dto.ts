/** Runtime-checked DTO boundary for the OpenWrite Studio API. */
export type JsonRecord = Record<string, unknown>

export function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {}
}

export function unwrapData(value: unknown): JsonRecord {
  const root = asRecord(value)
  return asRecord(root['data'] ?? value)
}

export function asText(value: unknown): string {
  return typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
}

export function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function asInteger(value: unknown, fallback = 0): number {
  const number = asFiniteNumber(value)
  return number === null ? fallback : Math.round(number)
}

export type ModelProfileDto = {
  id: string
  label: string
  provider: string
  model: string
  base_url: string
  api_format: string
  context_tokens: number
  max_output_tokens: number
  embedding_provider: string
  embedding_model: string
  configured: boolean
  embedding_configured: boolean
}

export function parseModelProfiles(value: unknown): ModelProfileDto[] {
  const root = unwrapData(value)
  const profiles = Array.isArray(root['profiles']) ? root['profiles'] : []
  return profiles.map(raw => {
    const item = asRecord(raw)
    return {
      id: asText(item['id']), label: asText(item['label']), provider: asText(item['provider']), model: asText(item['model']),
      base_url: asText(item['base_url']), api_format: asText(item['api_format']),
      context_tokens: asInteger(item['context_tokens']), max_output_tokens: asInteger(item['max_output_tokens']),
      embedding_provider: asText(item['embedding_provider']), embedding_model: asText(item['embedding_model']),
      configured: item['configured'] === true, embedding_configured: item['embedding_configured'] === true,
    }
  }).filter(item => item.id !== '')
}

export function parseRouteMap(value: unknown): Record<string, string> {
  const root = unwrapData(value)
  const routes = asRecord(root['routes'])
  return Object.fromEntries(Object.entries(routes).map(([key, route]) => [key, asText(route)]))
}
