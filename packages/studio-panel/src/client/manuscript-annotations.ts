import { asRecord, asText } from './dto.ts'
import { locateQuote, locateSelectedMarkdown, type QuoteAnchor } from './manuscript-selection.ts'

export const ANNOTATION_COLORS = ['amber', 'rose', 'sky', 'lime', 'violet'] as const
export type AnnotationColor = (typeof ANNOTATION_COLORS)[number]
export const DEFAULT_ANNOTATION_COLOR: AnnotationColor = 'amber'
export const ANNOTATION_COLOR_LABEL: Record<AnnotationColor, `creation.notes.color.${AnnotationColor}`> = {
  amber: 'creation.notes.color.amber',
  rose: 'creation.notes.color.rose',
  sky: 'creation.notes.color.sky',
  lime: 'creation.notes.color.lime',
  violet: 'creation.notes.color.violet',
}

export type AnnotationStatus = 'open' | 'resolved'
export type AnnotationAnchorState = 'attached' | 'relocated' | 'detached'

export type ManuscriptAnnotation = {
  annotationId: string
  chapterId: string
  sourceRevision: string
  quote: string
  startHint: number
  endHint: number
  note: string
  status: AnnotationStatus
  anchorState: AnnotationAnchorState
  currentStart: number | null
  currentEnd: number | null
  color: AnnotationColor
  createdAt: string
  updatedAt: string
}

export function isAnnotationColor(value: string): value is AnnotationColor {
  return (ANNOTATION_COLORS as readonly string[]).includes(value)
}

/** Old records without color keep amber; unknown values also default. */
export function annotationColor(value: unknown): AnnotationColor {
  return typeof value === 'string' && isAnnotationColor(value) ? value : DEFAULT_ANNOTATION_COLOR
}

export function parseAnnotation(value: unknown): ManuscriptAnnotation | null {
  const item = asRecord(value)
  const annotationId = asText(item['annotation_id'])
  const chapterId = asText(item['chapter_id'])
  const quote = asText(item['quote'])
  const note = asText(item['note'])
  if (!annotationId.startsWith('ann_') || chapterId === '' || quote === '' || note === '') return null
  const status = asText(item['status']) === 'resolved' ? 'resolved' : 'open'
  const anchor = asText(item['anchor_state'])
  const anchorState: AnnotationAnchorState = anchor === 'relocated' || anchor === 'detached' ? anchor : 'attached'
  const currentStart = typeof item['current_start'] === 'number' ? item['current_start'] : null
  const currentEnd = typeof item['current_end'] === 'number' ? item['current_end'] : null
  return {
    annotationId,
    chapterId,
    sourceRevision: asText(item['source_revision']),
    quote,
    startHint: typeof item['start_hint'] === 'number' ? item['start_hint'] : 0,
    endHint: typeof item['end_hint'] === 'number' ? item['end_hint'] : 0,
    note,
    status,
    anchorState,
    currentStart,
    currentEnd,
    color: annotationColor(item['color']),
    createdAt: asText(item['created_at']),
    updatedAt: asText(item['updated_at']),
  }
}

export function parseAnnotationList(value: unknown): ManuscriptAnnotation[] {
  const root = asRecord(value)
  const inner = asRecord(root['data'] ?? value)
  const list = Array.isArray(inner['annotations']) ? inner['annotations']
    : Array.isArray(root['annotations']) ? root['annotations'] : []
  return list.map(parseAnnotation).filter((item): item is ManuscriptAnnotation => item !== null)
}

export function unsavedAnnotationGuard(dirty: boolean): 'ok' | 'save-first' {
  return dirty ? 'save-first' : 'ok'
}

export function annotationLocateLabel(anchor: QuoteAnchor | { state: AnnotationAnchorState }): string {
  if (anchor.state === 'detached') return '已脱离原文／需重新定位'
  if (anchor.state === 'relocated') return '已重新定位'
  return '已定位'
}

export function liveAnnotationAnchor(content: string, item: ManuscriptAnnotation): QuoteAnchor {
  if (item.anchorState === 'detached' && item.currentStart === null) {
    return locateQuote(content, item.quote, item.startHint, item.endHint)
  }
  return locateQuote(
    content,
    item.quote,
    item.currentStart ?? item.startHint,
    item.currentEnd ?? item.endHint,
  )
}

export function revalidateAnnotationRange(
  content: string,
  selection: { start: number; end: number; text: string },
): { start: number; end: number; text: string } | null {
  if (content.slice(selection.start, selection.end) === selection.text) return selection
  return locateSelectedMarkdown(content, selection.text)
}

export function annotateRequest(input: {
  chapterId: string
  revision: string
  selection: { start: number; end: number; text: string }
  note: string
  color: AnnotationColor
}): { ok: true; body: Record<string, unknown> } | { ok: false; reason: 'empty' | 'save-first'; } {
  if (input.chapterId === '' || input.selection.text.trim() === '' || input.note.trim() === '') {
    return { ok: false, reason: 'empty' }
  }
  if (input.revision === '') return { ok: false, reason: 'save-first' }
  return {
    ok: true,
    body: {
      action: 'annotate',
      chapter_id: input.chapterId,
      revision: input.revision,
      quote: input.selection.text,
      start_hint: input.selection.start,
      end_hint: input.selection.end,
      note: input.note.trim(),
      color: input.color,
    },
  }
}
