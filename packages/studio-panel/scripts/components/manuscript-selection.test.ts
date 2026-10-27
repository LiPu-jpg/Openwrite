import { describe, expect, it } from 'vitest'
import { mapEditorRange, mapSourceRange } from '../../src/client/selection-coordinates.ts'
import {
  MANUSCRIPT_SELECTION_PRESERVE_ATTR, locateQuote, locateSelectedMarkdown, manuscriptSelectionFromRange,
  reviewIssuesForSelection, selectionPolishRequest, shouldClearManuscriptSelection,
} from '../../src/client/manuscript-selection.ts'

describe('manuscript selection polish mapping', () => {
  const selection = manuscriptSelectionFromRange('密信还在', 0, 4)!

  it('keeps the editor span when the pointer is on the polish bar', () => {
    expect(shouldClearManuscriptSelection({ selectionInsideEditor: true, preserveNode: null })).toBe(false)
    expect(shouldClearManuscriptSelection({ selectionInsideEditor: false, preserveNode: null })).toBe(true)
    const bar = document.createElement('div')
    bar.setAttribute(MANUSCRIPT_SELECTION_PRESERVE_ATTR, '')
    const button = document.createElement('button')
    bar.append(button)
    expect(shouldClearManuscriptSelection({ selectionInsideEditor: false, preserveNode: button })).toBe(false)
  })

  it('rejects empty ranges', () => {
    expect(manuscriptSelectionFromRange('abc', 1, 1)).toBeNull()
    expect(manuscriptSelectionFromRange('abc', -1, 1)).toBeNull()
    expect(manuscriptSelectionFromRange('abc', 0, 4)).toBeNull()
  })

  it('maps expand/compress/naturalize onto /revisions/selection', () => {
    expect(selectionPolishRequest({
      kind: 'expand', chapterId: 'ch_001', selection, documentContent: '密信还在', documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: [],
    })).toEqual({
      ok: true,
      path: '/revisions/selection',
      body: { chapter_id: 'ch_001', start: 0, end: 4, original_text: '密信还在', action: 'expand', expected_document_revision: 'rev' },
    })
    expect(selectionPolishRequest({
      kind: 'naturalize', chapterId: 'ch_001', selection, documentContent: '密信还在', documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: [],
    })).toMatchObject({ ok: true, body: { action: 'naturalize' } })
  })

  it('requires a fresh review and locatable issues for 按审稿改这段', () => {
    expect(selectionPolishRequest({
      kind: 'reviewFix', chapterId: 'ch_001', selection, documentContent: '密信还在', documentRevision: 'rev',
      reviewRevision: '', reviewFresh: false, issueIds: ['issue-letter'],
    })).toEqual({ ok: false, reason: 'no-review' })
    expect(selectionPolishRequest({
      kind: 'reviewFix', chapterId: 'ch_001', selection, documentContent: '密信还在', documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: [],
    })).toEqual({ ok: false, reason: 'no-issues' })
    expect(selectionPolishRequest({
      kind: 'reviewFix', chapterId: 'ch_001', selection, documentContent: '密信还在', documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: ['issue-letter'],
    })).toEqual({
      ok: true,
      path: '/revisions/from-review',
      body: {
        chapter_id: 'ch_001',
        issue_ids: ['issue-letter'],
        original_text: '密信还在',
        selection: { start: 0, end: 4, original_text: '密信还在' },
        expected_review_revision: 'review',
        expected_document_revision: 'rev',
      },
    })
  })

  it('does not bind the first duplicate quote without an occurrence index', () => {
    expect(locateSelectedMarkdown('密信还在桌上。密信还在桌上。', '密信还在')).toBeNull()
    expect(locateSelectedMarkdown('密信还在桌上。密信还在桌上。', '密信还在', 1)).toEqual({
      start: 7, end: 11, text: '密信还在', source: '密信还在桌上。密信还在桌上。',
    })
    expect(locateSelectedMarkdown('只有一次密信还在这里', '密信还在')).toEqual({
      start: 4, end: 8, text: '密信还在', source: '只有一次密信还在这里',
    })
  })

  it('relocates a unique quote and detaches ambiguous or missing spans', () => {
    expect(locateQuote('前 密信还在 后', '密信还在', 0, 4)).toEqual({ state: 'relocated', start: 2, end: 6 })
    expect(locateQuote('密信还在。密信还在。', '密信还在', 1, 5)).toEqual({ state: 'detached', reason: 'ambiguous' })
    expect(locateQuote('没有这段', '密信还在', 0, 4)).toEqual({ state: 'detached', reason: 'missing' })
    expect(locateQuote('密信还在桌上', '密信还在', 0, 4)).toEqual({ state: 'attached', start: 0, end: 4 })
  })

  it('selects review issues whose quote or range sits in the selection', () => {
    expect(reviewIssuesForSelection([
      { id: 'hit', quote: '密信还在' },
      { id: 'miss', quote: '别的句子' },
      { id: 'range', start: 2, end: 6 },
    ], selection)).toEqual(['hit', 'range'])
  })
})

describe('editor/source coordinate boundary', () => {
  it.each([
    ['前文。选中文本。', '前文。选中文本。\n'],
    ['# 标题\r\n选中文本\r\n', '# 标题\n\n选中文本\n'],
    ['选中文本\n\n\n😀\n\n\n选中文本\n', '选中文本\n\n😀\n\n选中文本\n'],
  ])('maps a witnessed editor serialization without changing source bytes', (source, view) => {
    const serialization = { source, value: view }
    const start = view.lastIndexOf('选中文本'), end = start + 4
    const mapped = mapEditorRange(source, view, start, end, serialization)!
    expect(mapped).toEqual({ start: Array.from(source.slice(0, source.lastIndexOf('选中文本'))).length,
      end: Array.from(source.slice(0, source.lastIndexOf('选中文本'))).length + 4, text: '选中文本' })
    expect(mapSourceRange(source, view, mapped.start, mapped.end, serialization)).toEqual({ start, end, text: '选中文本' })
    expect(mapEditorRange(source, view, start, end)).toBeNull()
    expect(mapEditorRange(source, view + '\n', start, end, serialization)).toBeNull()
    expect(mapEditorRange(source + '\n外改', view, start, end, serialization)).toBeNull()
  })

  it('preserves raw multiline gaps and refuses invented text or NBSP equivalence', () => {
    const source = '前\r\n\r\n\r\n后', view = '前\n\n后\n', serialization = { source, value: view }
    expect(mapEditorRange(source, view, 0, view.length, serialization)?.text).toBe(source)
    expect(mapEditorRange(source, view, 2, 4, serialization)).toBeNull()
    for (const [raw, rendered] of [['原文', '已改\n'], ['a\u00a0b', 'a b\n']]) {
      expect(mapEditorRange(raw!, rendered!, 0, 1, { source: raw!, value: rendered! })).toBeNull()
    }
  })

  it('selects review evidence by position before comparing duplicate quotes', () => {
    const text = '密信还在。中间。密信还在'
    const selection = manuscriptSelectionFromRange(text, text.lastIndexOf('密信'), text.length)!
    expect(reviewIssuesForSelection([
      { id: 'first', evidence: { quote: '密信还在' }, anchor: { start_hint: 0, end_hint: 4 } },
      { id: 'second', evidence: { quote: '密信还在' }, anchor: { start_hint: selection.start, end_hint: selection.end } },
    ], selection)).toEqual(['second'])
  })
  it.each([
    ['LF', '前言\n选中文本\n尾部', '选中文本'],
    ['emoji', '前😀后选中文本尾部', '选中文本'],
    ['CRLF', '前言\r\n选中\r\n正文\r\n尾部', '选中\n正文'],
    ['mixed duplicate', '选中文本\r\n😀\n选中文本\r尾部', '选中文本'],
  ])('maps %s without moving to a different occurrence', (_name, source, quote) => {
    const view = source.replace(/\r\n?/g, '\n')
    const index = view.lastIndexOf(quote)
    const selected = manuscriptSelectionFromRange(view, index, index + quote.length)!
    const request = selectionPolishRequest({
      kind: 'expand', chapterId: 'ch_001', selection: selected, documentContent: source,
      documentRevision: 'rev', reviewRevision: '', reviewFresh: false, issueIds: [],
    })
    expect(request.ok).toBe(true)
    if (!request.ok) return
    const start = Number(request.body['start']), end = Number(request.body['end'])
    expect(Array.from(source).slice(start, end).join('')).toBe(request.body['original_text'])
    expect(String(request.body['original_text']).replace(/\r\n?/g, '\n')).toBe(quote)
    expect(mapSourceRange(source, view, start, end)).toEqual({ start: index, end: index + quote.length, text: quote })
    if (source.includes('😀')) expect(start).toBe(Array.from(source.slice(0, source.lastIndexOf(quote.split('\n')[0]!))).length)
  })

  it('refuses changed content, NBSP substitution, and split code points/newlines', () => {
    expect(mapEditorRange('原文', '已改', 0, 1)).toBeNull()
    expect(mapEditorRange('>\u00a0原文', '> 原文', 0, 2)).toBeNull()
    expect(mapEditorRange('😀', '😀', 0, 1)).toBeNull()
    expect(mapEditorRange('a\r\nb', 'a\r\nb', 2, 4)).toBeNull()
    expect(mapEditorRange('>\u00a0原文', '>\u00a0原文', 0, 4)?.text).toBe('>\u00a0原文')
  })
})
