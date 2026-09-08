/** Author-visible manuscript range used by selection polish and the editor. */
export type ManuscriptSelection = {
  start: number
  end: number
  text: string
}

export type SelectionPolishKind = 'expand' | 'compress' | 'naturalize' | 'reviewFix'

export const SELECTION_POLISH_ACTIONS: readonly {
  kind: SelectionPolishKind
  label: 'creation.selection.expand' | 'creation.selection.compress' | 'creation.selection.naturalize' | 'creation.selection.reviewFix'
}[] = [
  { kind: 'expand', label: 'creation.selection.expand' },
  { kind: 'compress', label: 'creation.selection.compress' },
  { kind: 'naturalize', label: 'creation.selection.naturalize' },
  { kind: 'reviewFix', label: 'creation.selection.reviewFix' },
]

const SELECTION_ACTION_MODE: Record<Exclude<SelectionPolishKind, 'reviewFix'>, string> = {
  expand: 'expand',
  compress: 'compress',
  naturalize: 'naturalize',
}

/** Mark chrome that must not steal the editor selection on pointer down. */
export const MANUSCRIPT_SELECTION_PRESERVE_ATTR = 'data-preserve-manuscript-selection'

export function nodePreservesManuscriptSelection(node: EventTarget | Node | null): boolean {
  return node instanceof Element && node.closest(`[${MANUSCRIPT_SELECTION_PRESERVE_ATTR}]`) !== null
}

/** False when a toolbar click collapsed the native range; keep the last editor span. */
export function shouldClearManuscriptSelection(options: {
  selectionInsideEditor: boolean
  preserveNode: EventTarget | Node | null
}): boolean {
  if (options.selectionInsideEditor) return false
  return !nodePreservesManuscriptSelection(options.preserveNode)
}

export function manuscriptSelectionFromRange(value: string, start: number, end: number): ManuscriptSelection | null {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > value.length || end <= start) return null
  return { start, end, text: value.slice(start, end) }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function issueQuote(value: unknown): string {
  const item = asRecord(value)
  const evidence = asRecord(item['evidence'])
  const quote = item['quote'] ?? evidence['quote'] ?? item['original_text']
  return typeof quote === 'string' ? quote : ''
}

function issueRange(value: unknown): { start: number; end: number } | null {
  const item = asRecord(value)
  const start = Number(item['start'] ?? asRecord(item['anchor'])['start'] ?? Number.NaN)
  const end = Number(item['end'] ?? asRecord(item['anchor'])['end'] ?? Number.NaN)
  return Number.isFinite(start) && Number.isFinite(end) ? { start, end } : null
}

/** Review issues whose evidence sits inside the current manuscript selection. */
export function reviewIssuesForSelection(issues: readonly unknown[], selection: ManuscriptSelection): string[] {
  const ids: string[] = []
  for (const raw of issues) {
    const item = asRecord(raw)
    const id = typeof item['id'] === 'string' ? item['id'] : ''
    if (id === '' || ids.includes(id)) continue
    const quote = issueQuote(item)
    if (quote !== '' && (selection.text.includes(quote) || quote.includes(selection.text))) {
      ids.push(id)
      continue
    }
    const range = issueRange(item)
    if (range !== null && range.start < selection.end && range.end > selection.start) ids.push(id)
  }
  return ids
}

export type SelectionPolishRequest =
  | { ok: true; path: '/revisions/selection' | '/revisions/from-review'; body: Record<string, unknown> }
  | { ok: false; reason: 'empty' | 'no-review' | 'no-issues' }

/** Map one author action onto the existing Studio revision-create routes. */
export function selectionPolishRequest(input: {
  kind: SelectionPolishKind
  chapterId: string
  selection: ManuscriptSelection
  documentRevision: string
  reviewRevision: string
  reviewFresh: boolean
  issueIds: string[]
}): SelectionPolishRequest {
  if (input.chapterId === '' || input.selection.text.trim() === '') return { ok: false, reason: 'empty' }
  if (input.kind === 'reviewFix') {
    if (!input.reviewFresh || input.reviewRevision === '' || input.documentRevision === '') {
      return { ok: false, reason: 'no-review' }
    }
    if (input.issueIds.length === 0) return { ok: false, reason: 'no-issues' }
    return {
      ok: true,
      path: '/revisions/from-review',
      body: {
        chapter_id: input.chapterId,
        issue_ids: input.issueIds,
        original_text: input.selection.text,
        expected_review_revision: input.reviewRevision,
        expected_document_revision: input.documentRevision,
      },
    }
  }
  return {
    ok: true,
    path: '/revisions/selection',
    body: {
      chapter_id: input.chapterId,
      start: input.selection.start,
      end: input.selection.end,
      original_text: input.selection.text,
      action: SELECTION_ACTION_MODE[input.kind],
    },
  }
}
