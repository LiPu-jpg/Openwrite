import { useEffect, useMemo, useState } from 'react'
import { MarkdownText } from '@deepseek-ai/dsh-client-ui-primitives'
import type { StudioApiInjected } from './api.ts'
import { parseReadingPacket } from './dto.ts'
import type { ChapterSummary } from './WorkbenchStore.ts'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import css from './Workbench.module.css'

interface ReaderDocument {
  occurrence: number
  chapter: ChapterSummary
  path: string
  documentId: string
  revision: string
  content: string
  error: string
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function parseLegacyDocument(value: unknown, chapter: ChapterSummary, occurrence: number): ReaderDocument {
  const outer = record(value)
  const item = Object.keys(record(outer['data'])).length > 0 ? record(outer['data']) : outer
  const returnedPath = typeof item['path'] === 'string' ? item['path'] : ''
  if (returnedPath !== chapter.path) {
    return {
      occurrence, chapter, path: chapter.path, documentId: chapter.documentId || '',
      revision: '', content: '', error: 'DOCUMENT_RESPONSE_MISMATCH',
    }
  }
  return {
    occurrence,
    chapter,
    path: returnedPath,
    documentId: typeof item['document_id'] === 'string' ? item['document_id'] : chapter.documentId || '',
    revision: typeof item['revision'] === 'string' ? item['revision'] : '',
    content: typeof item['content'] === 'string' ? item['content'] : '',
    error: '',
  }
}

export interface ContinuousReaderProps extends PropsLocale<'studio-panel'> {
  chapters: readonly ChapterSummary[]
  activePath: string
  activeOccurrenceId: string
  readingOrderRevision: string
  fetchStudioApi: StudioApiInjected['fetchStudioApi']
  onOpenChapter: (path: string, occurrenceId: string) => void
}

/** Read-only, revision-labelled manuscript view over immutable reading occurrences. */
export function ContinuousReader({
  chapters, activePath, activeOccurrenceId, readingOrderRevision, fetchStudioApi, onOpenChapter, t,
}: ContinuousReaderProps) {
  const [documents, setDocuments] = useState<ReaderDocument[]>([])
  const [state, setState] = useState<'loading' | 'ready'>('loading')
  const [loadError, setLoadError] = useState('')
  const [reload, setReload] = useState(0)
  const activeOccurrence = useMemo(() => chapters.findIndex(chapter =>
    activeOccurrenceId !== '' ? chapter.occurrenceId === activeOccurrenceId : chapter.path === activePath),
  [activeOccurrenceId, activePath, chapters])

  useEffect(() => {
    let cancelled = false
    setState('loading')
    setDocuments([])
    setLoadError('')
    void (async () => {
      const canonical = chapters.length > 0 && readingOrderRevision !== '' &&
        chapters.every(chapter => chapter.occurrenceId !== '' && chapter.documentId !== '')
      if (canonical) {
        const byOccurrence = new Map(chapters.map((chapter, index) => [chapter.occurrenceId, { chapter, index }]))
        let anchor = chapters[0]?.occurrenceId ?? ''
        const visited = new Set<string>()
        const loaded: ReaderDocument[] = []
        while (anchor !== '') {
          if (visited.has(anchor)) throw new Error('READING_PACKET_LOOP')
          visited.add(anchor)
          const packet = parseReadingPacket(await fetchStudioApi(
            `/reading-packet?document_id=${encodeURIComponent(anchor)}&before=0&after=20`,
          ))
          if (packet.schema_version !== 'openwrite.reading-packet.v1' || packet.revision !== readingOrderRevision ||
            packet.anchor_occurrence_id !== anchor) throw new Error('READING_ORDER_CONFLICT')
          for (const document of packet.documents) {
            if (document.status === 'missing') continue
            const expected = byOccurrence.get(document.occurrence_id)
            if (expected === undefined || expected.chapter.documentId !== document.document_id ||
              expected.chapter.path !== document.path) throw new Error('READING_PACKET_IDENTITY_MISMATCH')
            loaded.push({
              occurrence: expected.index, chapter: expected.chapter, path: document.path,
              documentId: document.document_id, revision: document.revision,
              content: document.content, error: document.status === 'present' || document.status === 'orphan' ? '' : document.status,
            })
          }
          if (cancelled) return
          setDocuments([...loaded].sort((left, right) => left.occurrence - right.occurrence))
          if (!packet.has_next) break
          anchor = packet.documents.at(-1)?.next_occurrence_id ?? ''
          if (anchor === '') throw new Error('READING_PACKET_TRUNCATED')
        }
      } else {
        // Compatibility path for Workspaces that do not expose stable
        // occurrence identities yet. Every list item remains visible.
        for (const [occurrence, chapter] of chapters.entries()) {
          let item: ReaderDocument
          try {
            item = parseLegacyDocument(await fetchStudioApi(`/document?path=${encodeURIComponent(chapter.path)}`), chapter, occurrence)
          } catch (cause: unknown) {
            item = {
              occurrence, chapter, path: chapter.path, documentId: chapter.documentId || '',
              revision: '', content: '', error: cause instanceof Error ? cause.message : String(cause),
            }
          }
          if (cancelled) return
          setDocuments(previous => [...previous, item])
        }
      }
      if (!cancelled) setState('ready')
    })().catch((cause: unknown) => {
      if (cancelled) return
      setLoadError(cause instanceof Error ? cause.message : String(cause))
      setState('ready')
    })
    return () => { cancelled = true }
  }, [chapters, fetchStudioApi, readingOrderRevision, reload])

  return <section className={css.continuousReader} aria-label={t('creation.reader.title')}>
    <header className={css.readerHeader}>
      <div>
        <strong>{t('creation.reader.title')}</strong>
        <span>{t('creation.reader.readOnly')}</span>
      </div>
      <button type="button" disabled={state === 'loading'} onClick={() => setReload(value => value + 1)}>
        {t('creation.reader.refresh')}
      </button>
    </header>
    {state === 'loading' && <div className={css.centerNotice} role="status">{t('creation.reader.loading')}</div>}
    {loadError !== '' && <div className={css.readerError} role="alert">{loadError}</div>}
    {state === 'ready' && loadError === '' && documents.length === 0 && <div className={css.centerNotice}>{t('creation.empty')}</div>}
    {documents.map(item => <article key={item.chapter.occurrenceId || `${String(item.occurrence)}:${item.path}`}
      id={`reader-chapter-${String(item.occurrence)}`} className={css.readerChapter} data-active={item.occurrence === activeOccurrence}>
      <header>
        <div>
          <span>{String(item.occurrence + 1).padStart(2, '0')}</span>
          <strong>{item.chapter.title}</strong>
        </div>
        <button type="button" onClick={() => onOpenChapter(item.path, item.chapter.occurrenceId)}>{t('creation.reader.openEditor')}</button>
      </header>
      <dl>
        <div><dt>{t('creation.reader.path')}</dt><dd><code>{item.path}</code></dd></div>
        {item.documentId !== '' && <div><dt>{t('creation.reader.documentId')}</dt><dd><code>{item.documentId}</code></dd></div>}
        <div><dt>{t('creation.reader.revision')}</dt><dd><code>{item.revision || t('creation.reader.revisionUnavailable')}</code></dd></div>
      </dl>
      {item.error !== ''
        ? <div className={css.readerError}>{item.error}</div>
        : <div className={css.readerContent}><MarkdownText text={item.content} /></div>}
    </article>)}
  </section>
}
