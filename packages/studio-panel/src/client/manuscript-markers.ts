/** Core inline metadata: character state and directed relations. Display-only coloring. */

export const STATE_MARKER_RE = /^\/\/\*\*\s*([^\[\]@:：\r\n]+?)\s*(?:\[([^\]\r\n]+)\])?\s*[：:]\s*(.*?)\s*(?:->|→|⇒)\s*(.*?)\s*\*\*\s*$/
export const RELATION_MARKER_RE = /^\/\/\*\*\s*([^~～:：\r\n]+?)\s*[~～]\s*>?\s*([^:：\r\n]+?)\s*[：:]\s*(.+?)\s*\*\*\s*$/

const FENCE_RE = /^\s*(`{3,}|~{3,})/
const RESERVED = /[\r\n*\[\]@]/

export type MarkerKind = 'state' | 'relation'

export type ParsedMarker =
  | { kind: 'state'; name: string; field: string; oldState: string; newState: string }
  | { kind: 'relation'; source: string; target: string; description: string }

export type MarkerSpan = {
  kind: MarkerKind | 'invalid'
  start: number
  end: number
  line: number
  text: string
  parsed: ParsedMarker | null
  hint: string
}

export type MarkerDraftError = 'empty' | 'newline' | 'reserved'

function fenceToggle(line: string, open: string): string {
  const match = FENCE_RE.exec(line)
  if (!match) return open
  const marker = match[1]![0]!
  if (open === '') return marker
  return open === marker ? '' : open
}

export function parseMarkerLine(line: string): { parsed: ParsedMarker | null; invalid: boolean; hint: string } {
  const trimmed = line.trim()
  if (!trimmed.includes('//**')) return { parsed: null, invalid: false, hint: '' }
  const relation = RELATION_MARKER_RE.exec(trimmed)
  if (relation) {
    const source = relation[1]!.trim()
    const target = relation[2]!.trim()
    const description = relation[3]!.trim()
    if (!source || !target || !description) {
      return { parsed: null, invalid: true, hint: '关系源、目标和具体关系均不能为空' }
    }
    return { parsed: { kind: 'relation', source, target, description }, invalid: false, hint: '' }
  }
  if (trimmed.includes('~') || trimmed.includes('～')) {
    return { parsed: null, invalid: true, hint: '关系批注格式无效，应为 //**A~>B:具体关系**' }
  }
  const state = STATE_MARKER_RE.exec(trimmed)
  if (!state) {
    return { parsed: null, invalid: true, hint: '状态批注格式无效，应为 //**人物[维度]：旧状态 -> 新状态**' }
  }
  const name = state[1]!.trim()
  const field = (state[2] ?? '综合状态').trim()
  const oldState = state[3]!.trim()
  const newState = state[4]!.trim()
  if (!name || !field || !oldState || !newState) {
    return { parsed: null, invalid: true, hint: '人物、维度、旧状态和新状态均不能为空' }
  }
  return { parsed: { kind: 'state', name, field, oldState, newState }, invalid: false, hint: '' }
}

/** Parse markers outside fenced code. Invalid/unclosed fences keep source text. */
export function parseMarkers(text: string): MarkerSpan[] {
  const spans: MarkerSpan[] = []
  let offset = 0
  let fence = ''
  const lines = text.split(/(?<=\n)/)
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? ''
    const next = offset + line.length
    fence = fenceToggle(line, fence)
    if (fence === '' && line.includes('//**')) {
      const result = parseMarkerLine(line.replace(/\n$/, ''))
      if (result.parsed || result.invalid) {
        spans.push({
          kind: result.parsed?.kind ?? 'invalid',
          start: offset,
          end: next - (line.endsWith('\n') ? 1 : 0),
          line: index + 1,
          text: line.replace(/\n$/, ''),
          parsed: result.parsed,
          hint: result.hint,
        })
      }
    }
    offset = next
  }
  return spans
}

function rejectField(value: string): MarkerDraftError | null {
  const trimmed = value.trim()
  if (trimmed === '') return 'empty'
  if (/[\r\n]/.test(value)) return 'newline'
  if (RESERVED.test(trimmed) || trimmed.includes('**')) return 'reserved'
  return null
}

export function formatStateMarker(input: {
  name: string; field?: string; oldState: string; newState: string
}): { ok: true; markdown: string } | { ok: false; error: MarkerDraftError; field: string } {
  for (const [field, value] of [
    ['name', input.name], ['field', input.field ?? '综合状态'], ['oldState', input.oldState], ['newState', input.newState],
  ] as const) {
    const error = rejectField(value)
    if (error) return { ok: false, error, field }
  }
  const field = (input.field ?? '综合状态').trim()
  const body = field === '综合状态'
    ? `//**${input.name.trim()}：${input.oldState.trim()} -> ${input.newState.trim()}**`
    : `//**${input.name.trim()}[${field}]：${input.oldState.trim()} -> ${input.newState.trim()}**`
  return { ok: true, markdown: body }
}

export function formatRelationMarker(input: {
  source: string; target: string; description: string
}): { ok: true; markdown: string } | { ok: false; error: MarkerDraftError; field: string } {
  for (const [field, value] of [
    ['source', input.source], ['target', input.target], ['description', input.description],
  ] as const) {
    const error = rejectField(value)
    if (error) return { ok: false, error, field }
  }
  return { ok: true, markdown: `//**${input.source.trim()}~>${input.target.trim()}:${input.description.trim()}**` }
}

/** Readable prose with valid metadata lines removed; invalid markers stay. */
export function stripValidMarkers(text: string): string {
  const hidden = new Set(parseMarkers(text).filter(item => item.parsed !== null).map(item => item.line))
  return text.split(/(?<=\n)/).filter((_, index) => !hidden.has(index + 1)).join('')
}

export function readableWritingUnits(text: string): number {
  return stripValidMarkers(text).replace(/\s+/g, '').length
}
