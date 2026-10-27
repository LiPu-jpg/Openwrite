/** Exact mapping between an editor's UTF-16 view and the saved source's code points. */
export type SourceRange = { start: number; end: number; text: string }
/** A pair captured from the editor's initial serialization, before author input. */
export type EditorSerialization = { source: string; value: string }

function normalize(text: string, foldLines = false): { text: string; boundaries: number[] } {
  const chars: string[] = []
  const boundaries = [0]
  let limit = text.length
  if (foldLines) while (limit > 0 && /[\r\n]/.test(text[limit - 1]!)) limit--
  for (let index = 0; index < limit; index++) {
    if (text[index] === '\r' || foldLines && text[index] === '\n') {
      if (foldLines) while (index + 1 < limit && /[\r\n]/.test(text[index + 1]!)) index++
      else if (text[index + 1] === '\n') index++
      chars.push('\n')
    } else chars.push(text[index]!)
    boundaries.push(index + 1)
  }
  return { text: chars.join(''), boundaries }
}

function boundary(text: string, index: number): boolean {
  if (!Number.isInteger(index) || index < 0 || index > text.length) return false
  const before = text.charCodeAt(index - 1), after = text.charCodeAt(index)
  return !(before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff)
}

function indexOfBoundary(items: number[], value: number): number {
  let left = 0, right = items.length - 1
  while (left <= right) {
    const middle = (left + right) >>> 1
    if (items[middle] === value) return middle
    if (items[middle]! < value) left = middle + 1
    else right = middle - 1
  }
  return -1
}

let cached: { source: string; editor: string; serialized: boolean; raw: ReturnType<typeof normalize>; view: ReturnType<typeof normalize>; points: number[] } | undefined
function coordinates(source: string, editor: string, serialization?: EditorSerialization) {
  const serialized = serialization?.source === source && serialization.value === editor
  if (cached?.source === source && cached.editor === editor && cached.serialized === serialized) return cached
  const points = [0]
  for (const point of source) points.push(points[points.length - 1]! + point.length)
  let raw = normalize(source), view = normalize(editor)
  // Extra/missing blank lines are accepted only for the exact pair observed at
  // editor initialization. Later author edits cannot borrow that proof.
  if (raw.text !== view.text && serialized) { raw = normalize(source, true); view = normalize(editor, true) }
  cached = { source, editor, serialized, raw, view, points }
  return cached
}

function mappedBoundary(from: ReturnType<typeof normalize>, to: ReturnType<typeof normalize>, index: number, fromLength: number, toLength: number): number {
  const position = indexOfBoundary(from.boundaries, index)
  if (position >= 0) return to.boundaries[position]!
  return index === fromLength ? toLength : -1
}

/** Exact content and witnessed newline serialization; never guess among quotes. */
export function mapEditorRange(source: string, editor: string, start: number, end: number, serialization?: EditorSerialization): SourceRange | null {
  if (end <= start || !boundary(editor, start) || !boundary(editor, end)) return null
  const { raw, view, points } = coordinates(source, editor, serialization)
  if (raw.text !== view.text) return null
  const rawStart = mappedBoundary(view, raw, start, editor.length, source.length)
  const rawEnd = mappedBoundary(view, raw, end, editor.length, source.length)
  if (rawStart < 0 || rawEnd <= rawStart) return null // Never split a newline run.
  return {
    start: indexOfBoundary(points, rawStart),
    end: indexOfBoundary(points, rawEnd),
    text: source.slice(rawStart, rawEnd),
  }
}

/** Translate stored source code-point hints back into the editor's UTF-16 view. */
export function mapSourceRange(source: string, editor: string, start: number, end: number, serialization?: EditorSerialization): SourceRange | null {
  const { raw, view, points } = coordinates(source, editor, serialization)
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end >= points.length) return null
  if (raw.text !== view.text) return null
  const rawStart = points[start]!, rawEnd = points[end]!
  const viewStart = mappedBoundary(raw, view, rawStart, source.length, editor.length)
  const viewEnd = mappedBoundary(raw, view, rawEnd, source.length, editor.length)
  if (viewStart < 0 || viewEnd <= viewStart) return null
  return { start: viewStart, end: viewEnd, text: editor.slice(viewStart, viewEnd) }
}
