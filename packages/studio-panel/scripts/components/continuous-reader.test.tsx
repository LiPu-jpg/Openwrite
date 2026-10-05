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
})
