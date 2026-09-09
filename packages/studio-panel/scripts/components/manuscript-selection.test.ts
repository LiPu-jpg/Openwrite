import { describe, expect, it } from 'vitest'
import {
  MANUSCRIPT_SELECTION_PRESERVE_ATTR, locateQuote, locateSelectedMarkdown, manuscriptSelectionFromRange,
  reviewIssuesForSelection, selectionPolishRequest, shouldClearManuscriptSelection,
} from '../../src/client/manuscript-selection.ts'

describe('manuscript selection polish mapping', () => {
  const selection = { start: 0, end: 4, text: '密信还在' }

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
      kind: 'expand', chapterId: 'ch_001', selection, documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: [],
    })).toEqual({
      ok: true,
      path: '/revisions/selection',
      body: { chapter_id: 'ch_001', start: 0, end: 4, original_text: '密信还在', action: 'expand' },
    })
    expect(selectionPolishRequest({
      kind: 'naturalize', chapterId: 'ch_001', selection, documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: [],
    })).toMatchObject({ ok: true, body: { action: 'naturalize' } })
  })

  it('requires a fresh review and locatable issues for 按审稿改这段', () => {
    expect(selectionPolishRequest({
      kind: 'reviewFix', chapterId: 'ch_001', selection, documentRevision: 'rev',
      reviewRevision: '', reviewFresh: false, issueIds: ['issue-letter'],
    })).toEqual({ ok: false, reason: 'no-review' })
    expect(selectionPolishRequest({
      kind: 'reviewFix', chapterId: 'ch_001', selection, documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: [],
    })).toEqual({ ok: false, reason: 'no-issues' })
    expect(selectionPolishRequest({
      kind: 'reviewFix', chapterId: 'ch_001', selection, documentRevision: 'rev',
      reviewRevision: 'review', reviewFresh: true, issueIds: ['issue-letter'],
    })).toEqual({
      ok: true,
      path: '/revisions/from-review',
      body: {
        chapter_id: 'ch_001',
        issue_ids: ['issue-letter'],
        original_text: '密信还在',
        expected_review_revision: 'review',
        expected_document_revision: 'rev',
      },
    })
  })

  it('does not bind the first duplicate quote without an occurrence index', () => {
    expect(locateSelectedMarkdown('密信还在桌上。密信还在桌上。', '密信还在')).toBeNull()
    expect(locateSelectedMarkdown('密信还在桌上。密信还在桌上。', '密信还在', 1)).toEqual({
      start: 7, end: 11, text: '密信还在',
    })
    expect(locateSelectedMarkdown('只有一次密信还在这里', '密信还在')).toEqual({
      start: 4, end: 8, text: '密信还在',
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
