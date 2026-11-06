import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ContinuousReader } from '../../src/client/ContinuousReader.tsx'
import type { ChapterSummary } from '../../src/client/WorkbenchStore.ts'

vi.mock('../../src/client/MarkdownText.tsx', () => ({ MarkdownText: ({ text }: { text: string }) => <p>{text}</p> }))
const chapter = { occurrenceId: '', documentId: '', path: 'ch_1.md', revision: 'r1', status: 'present', title: 'First' } as ChapterSummary
const props = (fetchStudioApi: ReturnType<typeof vi.fn>) => ({
  chapters: [chapter], activePath: chapter.path, activeOccurrenceId: '', readingOrderRevision: '',
  fetchStudioApi, onOpenChapter: vi.fn(), t: (key: string) => key,
})

describe('continuous reader refresh', () => {
  it('keeps the DOM and scroll position through equivalent workspace polls; reloads revisions and manual refresh', async () => {
    const fetch = vi.fn(async () => ({ path: chapter.path, content: 'Body', revision: 'r1' }))
    const p = props(fetch)
    const { rerender } = render(<ContinuousReader {...p} />)
    await screen.findByText('Body')
    const article = screen.getByText('Body').closest('article')!
    const reader = article.parentElement!
    reader.scrollTop = 321
    rerender(<ContinuousReader {...p} chapters={[{ ...chapter }]} />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(screen.getByText('Body').closest('article')).toBe(article)
    expect(reader.scrollTop).toBe(321)
    rerender(<ContinuousReader {...p} chapters={[{ ...chapter, revision: 'r2' }]} />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    await waitFor(() => expect((screen.getByRole('button', { name: 'creation.reader.refresh' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: 'creation.reader.refresh' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
  })

  it('retains readable text during reload and ignores a superseded response', async () => {
    let settle: (value: unknown) => void = () => {}
    const fetch = vi.fn().mockResolvedValueOnce({ path: chapter.path, content: 'Old body' })
      .mockImplementationOnce(() => new Promise(resolve => { settle = resolve }))
      .mockResolvedValueOnce({ path: chapter.path, content: 'Newest body' })
    const p = props(fetch)
    const { rerender } = render(<ContinuousReader {...p} />)
    await screen.findByText('Old body')
    rerender(<ContinuousReader {...p} chapters={[{ ...chapter, revision: 'r2' }]} />)
    expect(screen.getByText('Old body')).toBeTruthy()
    rerender(<ContinuousReader {...p} chapters={[{ ...chapter, revision: 'r3' }]} />)
    await screen.findByText('Newest body')
    settle({ path: chapter.path, content: 'Stale body' })
    await waitFor(() => expect(screen.queryByText('Stale body')).toBeNull())
  })

  it('keeps chapters already fetched when a later request fails', async () => {
    // The catch used to setDocuments([]), so one failed request blanked the whole
    // reader - including chapters that had loaded fine moments earlier.
    const fetch = vi.fn(async (path: string) => {
      if (path.startsWith('/document')) return { path: chapter.path, content: 'First body' }
      throw new Error('network down')
    })
    const p = props(fetch)
    const { rerender } = render(<ContinuousReader {...p} />)
    await screen.findByText('First body')
    rerender(<ContinuousReader {...p} chapters={[{ ...chapter, revision: 'r2' }]} />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    expect(screen.getByText('First body')).toBeTruthy()
  })

  it('keeps documents already read when a later reading packet fails the identity check', async () => {
    // Canonical mode pushes each packet's documents before validating the next
    // one, so a mismatch part-way through used to discard everything read so far.
    // The first packet MUST chain (has_next + next_occurrence_id) or the loop
    // breaks before the second packet is ever requested.
    const first = {
      occurrenceId: 'occ_1', documentId: 'doc_1', path: 'ch_1.md', revision: 'r1', status: 'present', title: 'First',
    } as ChapterSummary
    const second = {
      ...first, occurrenceId: 'occ_2', documentId: 'doc_2', path: 'ch_2.md', revision: 'r1', status: 'present', title: 'Second',
    } as ChapterSummary
    const packet = (occurrenceId: string, documentId: string, chains: boolean) => ({
      schema_version: 'openwrite.reading-packet.v1', revision: 'r1',
      anchor_document_id: documentId, anchor_occurrence_id: occurrenceId,
      start_index: 0, end_index: 1, has_previous: false, has_next: chains, complete: !chains,
      documents: [{
        occurrence_id: occurrenceId, document_id: documentId,
        path: occurrenceId === 'occ_1' ? 'ch_1.md' : 'ch_2.md',
        previous_occurrence_id: '', next_occurrence_id: chains ? 'occ_2' : '',
        revision: 'r1', status: 'present', title: occurrenceId === 'occ_1' ? 'First' : 'Second',
        content: occurrenceId === 'occ_1' ? 'First body' : 'Second body',
      }],
      issues: [],
    })
    let call = 0
    const fetch = vi.fn(async (path: string) => {
      if (!path.startsWith('/reading-packet')) throw new Error('unexpected: ' + path)
      call += 1
      // The second packet claims an identity that does not match the chapter list.
      return call === 1 ? packet('occ_1', 'doc_1', true) : packet('occ_2', 'doc_other', false)
    })
    const p = {
      chapters: [first, second], activePath: 'ch_1.md', activeOccurrenceId: 'occ_1',
      readingOrderRevision: 'r1', fetchStudioApi: fetch, onOpenChapter: vi.fn(), t: (key: string) => key,
    }
    render(<ContinuousReader {...p} />)
    // The document read before the failure survives, and the failure is reported.
    expect(await screen.findByText('First body')).toBeTruthy()
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    expect(screen.getByText('First body')).toBeTruthy()
    expect(screen.getByRole('alert')).toBeTruthy()
  })
})
