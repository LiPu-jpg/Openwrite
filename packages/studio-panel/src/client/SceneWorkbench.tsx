import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { StudioApiError, type StudioApiInjected } from './api.ts'
import css from './SceneWorkbench.module.css'

type StructureStatus = 'absent' | 'current' | 'stale' | 'ambiguous'
type OrderMode = 'reading' | 'story-time'

interface SceneIssue {
  key: string
  message: string
  code: string
  sceneId: string
  chapterId: string
}

interface SceneRecord {
  id: string
  chapterId: string
  chapterTitle: string
  title: string
  storyTimeSortKey: string
  storyTimeLabel: string
  characters: string[]
  locations: string[]
  events: string[]
  revision: string
  chapterRevision: string
  readingIndex: number
  storyTimeIndex: number
  chapterIndex: number
}

interface SceneChapter {
  id: string
  title: string
  revision: string
  sceneCount: number
}

interface SceneStructure {
  schemaVersion: string
  status: StructureStatus
  revision: string
  scenes: SceneRecord[]
  chapters: SceneChapter[]
  issues: SceneIssue[]
  plannedMissingChapters: number
  mutationAllowed: boolean
}

interface MigrationPreview {
  schemaVersion: string
  revision: string
  rows: string[]
  issues: SceneIssue[]
  canApply: boolean
}

interface MetadataDraft {
  title: string
  storyTimeSortKey: string
  storyTimeLabel: string
  characters: string
  locations: string
  events: string
}

interface MoveDraft {
  targetChapterId: string
  targetIndex: string
}

interface RecentMigration {
  id: string
  expectedRevision: string
}

export type SceneWorkbenchProps = Pick<StudioApiInjected, 'fetchStudioApi' | 'postStudioApi'>

function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function asString(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(item => {
      if (typeof item === 'string') return item
      const object = asObject(item)
      return asString(object['name'] ?? object['title'] ?? object['id'])
    }).filter(Boolean)
  }
  if (typeof value === 'string') return splitList(value)
  return []
}

function splitList(value: string): string[] {
  return value.split(/[,，\n]/u).map(item => item.trim()).filter(Boolean)
}

function envelopeData(value: unknown): { root: Record<string, unknown>, data: Record<string, unknown> } {
  const root = asObject(value)
  const data = Object.keys(asObject(root['data'])).length > 0 ? asObject(root['data']) : root
  return { root, data }
}

function schemaVersion(root: Record<string, unknown>, data: Record<string, unknown>): string {
  return asString(data['schema_version'] ?? root['schema_version'])
}

function statusOf(value: unknown): StructureStatus {
  const status = asString(value).toLowerCase()
  if (status === 'current' || status === 'stale' || status === 'ambiguous') return status
  return 'absent'
}

function parseIssues(value: unknown, prefix: string): SceneIssue[] {
  if (!Array.isArray(value)) return []
  return value.map((raw, index) => {
    if (typeof raw === 'string') {
      return { key: `${prefix}-${String(index)}`, message: raw, code: '', sceneId: '', chapterId: '' }
    }
    const issue = asObject(raw)
    const code = asString(issue['code'] ?? issue['kind'] ?? issue['type'])
    const sceneId = asString(issue['scene_id'])
    const chapterId = asString(issue['chapter_id'] ?? issue['ch_id'])
    const message = asString(issue['message'] ?? issue['detail'] ?? issue['reason'] ?? issue['description']) || '需要处理'
    return { key: `${prefix}-${code}-${sceneId}-${chapterId}-${String(index)}`, message, code, sceneId, chapterId }
  }).filter(issue => issue.code !== 'MISSING_CHAPTER_FILE')
}

function listFrom(container: Record<string, unknown>, ...keys: string[]): unknown[] {
  for (const key of keys) {
    if (Array.isArray(container[key])) return container[key] as unknown[]
  }
  return []
}

/** Normalize the scene envelope without turning planned-missing chapters into scenes. */
export function parseSceneStructure(value: unknown): SceneStructure {
  const { root, data } = envelopeData(value)
  const structure = Object.keys(asObject(data['structure'])).length > 0 ? asObject(data['structure']) : data
  const version = schemaVersion(root, data) || asString(structure['schema_version'])
  const revision = asString(structure['revision'] ?? structure['current_revision'] ?? data['revision'])
  const status = statusOf(structure['status'] ?? structure['freshness_status'] ?? data['status'])
  const rawChapters = listFrom(structure, 'chapters', 'chapter_scenes')
  const rawTopScenes = listFrom(structure, 'scenes', 'items')
  const missingIds = new Set<string>()
  const chapters: SceneChapter[] = []
  const chapterById = new Map<string, SceneChapter>()
  const nestedScenes: Array<{ raw: unknown, chapter: SceneChapter, chapterIndex: number }> = []

  rawChapters.forEach((rawChapter, chapterOrder) => {
    const chapter = asObject(rawChapter)
    const id = asString(chapter['chapter_id'] ?? chapter['ch_id'] ?? chapter['id'])
    if (id === '') return
    const chapterStatus = asString(chapter['status'] ?? chapter['availability']).toLowerCase()
    const freshness = asString(chapter['freshness']).toLowerCase()
    const isMissing = chapterStatus === 'missing' || chapterStatus === 'planned_missing' || chapterStatus === 'absent'
      || freshness === 'planned_missing'
    if (isMissing) {
      missingIds.add(id)
      return
    }
    const rawScenes = listFrom(chapter, 'scenes', 'items')
    const parsed: SceneChapter = {
      id,
      title: asString(chapter['title'] ?? chapter['chapter_title']) || id,
      revision: asString(chapter['revision'] ?? chapter['current_revision'] ?? chapter['source_revision']),
      sceneCount: rawScenes.length,
    }
    chapters.push(parsed)
    chapterById.set(id, parsed)
    rawScenes.forEach((scene, index) => nestedScenes.push({ raw: scene, chapter: parsed, chapterIndex: index }))
    void chapterOrder
  })

  const readingOrderIds = listFrom(structure, 'reading_order', 'actual_order')
    .map(item => typeof item === 'string' ? item : asString(asObject(item)['scene_id'] ?? asObject(item)['id']))
  const readingPositions = new Map(readingOrderIds.map((id, index) => [id, index]))
  const storyTimeOrderIds = listFrom(structure, 'story_time_order')
    .map(item => typeof item === 'string' ? item : asString(asObject(item)['scene_id'] ?? asObject(item)['id']))
  const storyTimePositions = new Map(storyTimeOrderIds.map((id, index) => [id, index]))
  const sourceScenes: Array<{ raw: unknown, chapter: SceneChapter | undefined, chapterIndex: number }> = nestedScenes.length > 0
    ? nestedScenes
    : rawTopScenes.map((raw, index) => {
        const object = asObject(raw)
        const sceneChapter = asObject(object['chapter'])
        const chapterId = asString(object['chapter_id'] ?? object['ch_id'] ?? sceneChapter['chapter_id'] ?? sceneChapter['ch_id'])
        return { raw, chapter: chapterById.get(chapterId), chapterIndex: index }
      })

  const scenes: SceneRecord[] = []
  sourceScenes.forEach(({ raw, chapter, chapterIndex }, fallbackIndex) => {
    const scene = asObject(raw)
    const metadata = Object.keys(asObject(scene['metadata'])).length > 0 ? asObject(scene['metadata']) : scene
    const sceneChapter = asObject(scene['chapter'])
    const storyTime = asObject(metadata['story_time'] ?? scene['story_time'])
    const references = asObject(metadata['references'] ?? scene['references'])
    const id = asString(scene['scene_id'] ?? scene['stable_id'] ?? scene['id'])
    const chapterId = asString(scene['chapter_id'] ?? scene['ch_id'] ?? sceneChapter['chapter_id'] ?? sceneChapter['ch_id']) || chapter?.id || ''
    const sceneStatus = asString(scene['status'] ?? scene['availability'] ?? scene['freshness']).toLowerCase()
    if (id === '' || missingIds.has(chapterId) || sceneStatus === 'missing' || sceneStatus === 'planned_missing' || sceneStatus === 'absent') return
    const knownChapter = chapter ?? chapterById.get(chapterId)
    const parsed: SceneRecord = {
      id,
      chapterId,
      chapterTitle: asString(scene['chapter_title']) || knownChapter?.title || chapterId,
      title: asString(metadata['title'] ?? scene['title']) || id,
      storyTimeSortKey: asString(metadata['story_time_sort_key'] ?? scene['story_time_sort_key'] ?? storyTime['sort_key']),
      storyTimeLabel: asString(metadata['story_time_label'] ?? scene['story_time_label'] ?? storyTime['label']),
      characters: asStringList(metadata['characters'] ?? scene['characters'] ?? references['characters']),
      locations: asStringList(metadata['locations'] ?? scene['locations'] ?? references['locations']),
      events: asStringList(metadata['events'] ?? scene['events'] ?? references['events']),
      revision,
      chapterRevision: asString(scene['chapter_revision'] ?? scene['source_chapter_revision'] ?? sceneChapter['revision']) || knownChapter?.revision || '',
      readingIndex: readingPositions.get(id)
        ?? asNumber(scene['reading_index'] ?? scene['reading_order'] ?? sceneChapter['reading_index'], fallbackIndex),
      storyTimeIndex: storyTimePositions.get(id) ?? -1,
      chapterIndex: asNumber(scene['chapter_index'] ?? scene['index'] ?? scene['position'] ?? scene['order'], chapterIndex),
    }
    scenes.push(parsed)
    if (knownChapter === undefined && chapterId !== '') {
      const inferred = { id: chapterId, title: parsed.chapterTitle, revision: parsed.chapterRevision, sceneCount: 1 }
      chapters.push(inferred)
      chapterById.set(chapterId, inferred)
    }
  })

  for (const chapter of chapters) {
    chapter.sceneCount = scenes.filter(scene => scene.chapterId === chapter.id).length
  }

  const counts = asObject(structure['counts'])
  const explicitMissing = asNumber(
    structure['planned_missing_chapters']
      ?? structure['planned_missing_count']
      ?? counts['planned_missing_chapters']
      ?? counts['planned_missing'],
    -1,
  )
  const missingList = listFrom(structure, 'missing_chapters', 'planned_missing')
  const plannedMissingChapters = explicitMissing >= 0 ? explicitMissing : Math.max(missingIds.size, missingList.length)
  const issues = [
    ...parseIssues(structure['issues'], 'structure'),
    ...(structure === data ? [] : parseIssues(data['issues'], 'envelope')),
  ]
  if (version !== '' && version !== 'openwrite.scene-structure.v1') {
    issues.unshift({
      key: 'schema-version', code: 'SCHEMA_VERSION_UNSUPPORTED', sceneId: '', chapterId: '',
      message: `不支持的场景结构版本：${version}`,
    })
  }
  const mutationAllowed = typeof structure['mutation_allowed'] === 'boolean'
    ? structure['mutation_allowed']
    : status === 'current'
  return { schemaVersion: version, status, revision, scenes, chapters, issues, plannedMissingChapters, mutationAllowed }
}

export function parseMigrationPreview(value: unknown): MigrationPreview | null {
  const { root, data } = envelopeData(value)
  const preview = Object.keys(asObject(data['preview'])).length > 0 ? asObject(data['preview']) : data
  const version = schemaVersion(root, data) || asString(preview['schema_version'])
  const revision = asString(preview['preview_revision'] ?? preview['revision'] ?? data['preview_revision'])
  const directRows = listFrom(preview, 'changes', 'items', 'scenes', 'migrations')
  const planRows = listFrom(preview, 'plan').flatMap((rawChapter) => {
    const chapter = asObject(rawChapter)
    const chapterId = asString(chapter['chapter_id'] ?? chapter['ch_id'])
    return listFrom(chapter, 'scenes', 'items').map(rawScene => ({
      ...asObject(rawScene),
      chapter_id: asString(asObject(rawScene)['chapter_id']) || chapterId,
      action: asString(asObject(rawScene)['action']) || 'create',
    }))
  })
  const rawRows = directRows.length > 0 ? directRows : planRows
  const rows = rawRows.map((raw, index) => {
    if (typeof raw === 'string') return raw
    const row = asObject(raw)
    const sceneId = asString(row['scene_id'] ?? row['stable_id'] ?? row['id'])
    const chapterId = asString(row['chapter_id'] ?? row['ch_id'])
    const title = asString(row['title'] ?? row['scene_title'] ?? row['summary'])
    const action = asString(row['action'] ?? row['operation'])
    return [action, sceneId, chapterId, title].filter(Boolean).join(' · ') || `迁移项 ${String(index + 1)}`
  })
  const issues = parseIssues(preview['issues'] ?? data['issues'], 'preview')
  const canApply = typeof preview['can_apply'] === 'boolean' ? preview['can_apply'] : issues.length === 0
  if (version !== '' && version !== 'openwrite.scene-migration-preview.v1') {
    issues.unshift({
      key: 'preview-schema-version', code: 'SCHEMA_VERSION_UNSUPPORTED', sceneId: '', chapterId: '',
      message: `不支持的迁移预览版本：${version}`,
    })
  }
  if (revision === '' && rows.length === 0 && issues.length === 0 && version === '') return null
  return { schemaVersion: version, revision, rows, issues, canApply }
}

function mutationPayload(value: unknown): Record<string, unknown> {
  const { data } = envelopeData(value)
  return data
}

function issueLabel(issue: SceneIssue): string {
  const scope = [issue.chapterId, issue.sceneId].filter(Boolean).join(' / ')
  const code = issue.code === '' ? '' : `[${issue.code}] `
  return `${code}${scope === '' ? '' : `${scope}：`}${issue.message}`
}

function metadataDraft(scene: SceneRecord): MetadataDraft {
  return {
    title: scene.title,
    storyTimeSortKey: scene.storyTimeSortKey,
    storyTimeLabel: scene.storyTimeLabel,
    characters: scene.characters.join('，'),
    locations: scene.locations.join('，'),
    events: scene.events.join('，'),
  }
}

function storyTimeCompare(left: SceneRecord, right: SceneRecord): number {
  if (left.storyTimeIndex >= 0 && right.storyTimeIndex >= 0) return left.storyTimeIndex - right.storyTimeIndex
  const leftKey = left.storyTimeSortKey.trim()
  const rightKey = right.storyTimeSortKey.trim()
  if (leftKey === '' && rightKey !== '') return 1
  if (rightKey === '' && leftKey !== '') return -1
  if (leftKey !== rightKey) return leftKey < rightKey ? -1 : 1
  return left.readingIndex - right.readingIndex
}

const STATUS_TEXT: Readonly<Record<StructureStatus, { label: string, explanation: string }>> = {
  absent: { label: 'absent · 尚未迁移', explanation: '当前项目还没有原生场景结构。请先审阅下方迁移预览。' },
  current: { label: 'current · 当前', explanation: '场景结构与当前章节一致，可以编辑元数据和顺序。' },
  stale: { label: 'stale · 已过期', explanation: '章节已变化；元数据与移动已停用，可在下方核对预览后重新迁移并稳定锚定。' },
  ambiguous: { label: 'ambiguous · 有歧义', explanation: '结构存在无法自动判定的场景，请先逐项解决问题。' },
}

/** Native scene-structure editor. All mutations are guarded by envelope and chapter revisions. */
export function SceneWorkbench({ fetchStudioApi, postStudioApi }: SceneWorkbenchProps) {
  const [structure, setStructure] = useState<SceneStructure | null>(null)
  const [preview, setPreview] = useState<MigrationPreview | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [order, setOrder] = useState<OrderMode>('reading')
  const [editingId, setEditingId] = useState('')
  const [metadata, setMetadata] = useState<MetadataDraft | null>(null)
  const [move, setMove] = useState<MoveDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [notice, setNotice] = useState<{ message: string, bad: boolean } | null>(null)
  const [recentMigration, setRecentMigration] = useState<RecentMigration | null>(null)
  const requestId = useRef(0)

  const load = useCallback(async (): Promise<boolean> => {
    const id = requestId.current + 1
    requestId.current = id
    setState('loading')
    const [structureResult, previewResult] = await Promise.allSettled([
      fetchStudioApi('/scenes'),
      fetchStudioApi('/scenes/migration-preview'),
    ])
    if (requestId.current !== id) return false
    if (structureResult.status === 'rejected') {
      setError(structureResult.reason instanceof Error ? structureResult.reason.message : String(structureResult.reason))
      setState('error')
      return false
    }
    setStructure(parseSceneStructure(structureResult.value))
    setEditingId('')
    setMetadata(null)
    setMove(null)
    setError('')
    if (previewResult.status === 'fulfilled') {
      setPreview(parseMigrationPreview(previewResult.value))
      setPreviewError('')
    } else {
      setPreview(null)
      setPreviewError(previewResult.reason instanceof Error ? previewResult.reason.message : String(previewResult.reason))
    }
    setState('ready')
    return true
  }, [fetchStudioApi])

  useEffect(() => {
    void load()
    return () => { requestId.current += 1 }
  }, [load])

  const editable = state === 'ready'
    && structure?.status === 'current'
    && structure.mutationAllowed
    && structure.schemaVersion !== ''
    && structure.schemaVersion === 'openwrite.scene-structure.v1'

  const orderedScenes = useMemo(() => {
    if (structure === null) return []
    const copy = [...structure.scenes]
    return order === 'reading'
      ? copy.sort((left, right) => left.readingIndex - right.readingIndex)
      : copy.sort(storyTimeCompare)
  }, [structure, order])

  const beginEdit = (scene: SceneRecord) => {
    if (!editable || busy) return
    setEditingId(scene.id)
    setMetadata(metadataDraft(scene))
    setMove({ targetChapterId: scene.chapterId, targetIndex: String(scene.chapterIndex) })
    setNotice(null)
  }

  const conflictRefresh = async () => {
    setNotice({ message: '检测到修订冲突，正在刷新场景结构…', bad: true })
    const refreshed = await load()
    setNotice({
      message: refreshed ? '修订冲突：结构已刷新，请基于最新版本重试。' : '修订冲突，且刷新失败；请手动重试。',
      bad: true,
    })
  }

  const mutationFailed = async (cause: unknown, action: string) => {
    if (cause instanceof StudioApiError && (cause.status === 409 || cause.code?.includes('CONFLICT') === true)) {
      await conflictRefresh()
      return
    }
    setNotice({ message: `${action}失败：${cause instanceof Error ? cause.message : String(cause)}`, bad: true })
  }

  const saveMetadata = async (scene: SceneRecord) => {
    if (!editable || metadata === null || busy || scene.revision === '') return
    setBusy(true)
    setNotice(null)
    try {
      await postStudioApi('/scenes/metadata', {
        scene_id: scene.id,
        expected_revision: scene.revision,
        title: metadata.title.trim(),
        story_time_sort_key: metadata.storyTimeSortKey.trim(),
        story_time_label: metadata.storyTimeLabel.trim(),
        characters: splitList(metadata.characters),
        locations: splitList(metadata.locations),
        events: splitList(metadata.events),
      })
      const refreshed = await load()
      setNotice(refreshed
        ? { message: `场景 ${scene.id} 的元数据已保存。`, bad: false }
        : { message: '元数据已提交，但无法刷新确认当前版本。', bad: true })
    } catch (cause: unknown) {
      await mutationFailed(cause, '保存元数据')
    } finally {
      setBusy(false)
    }
  }

  const moveScene = async (scene: SceneRecord) => {
    if (!editable || move === null || structure === null || busy) return
    const target = structure.chapters.find(chapter => chapter.id === move.targetChapterId)
    const source = structure.chapters.find(chapter => chapter.id === scene.chapterId)
    const targetIndex = Number(move.targetIndex)
    if (target === undefined || source === undefined || scene.revision === '' || source.revision === '' || target.revision === ''
      || !Number.isInteger(targetIndex) || targetIndex < 0) return
    setBusy(true)
    setNotice(null)
    try {
      await postStudioApi('/scenes/move', {
        scene_id: scene.id,
        target_chapter_id: target.id,
        target_index: targetIndex,
        expected_revision: scene.revision,
        expected_source_revision: source.revision,
        expected_target_revision: target.revision,
      })
      const refreshed = await load()
      setNotice(refreshed
        ? { message: `场景 ${scene.id} 已移动。`, bad: false }
        : { message: '移动已提交，但无法刷新确认当前版本。', bad: true })
    } catch (cause: unknown) {
      await mutationFailed(cause, '移动场景')
    } finally {
      setBusy(false)
    }
  }

  const applyMigration = async () => {
    if (state !== 'ready' || (structure?.status !== 'absent' && structure?.status !== 'stale')
      || preview === null || !preview.canApply || preview.revision === '' || !confirmed || busy) return
    setBusy(true)
    setNotice(null)
    try {
      const result = mutationPayload(await postStudioApi('/scenes/migration/apply', {
        expected_preview_revision: preview.revision,
        confirm: true,
      }))
      const migrationId = asString(result['migration_id'])
      const returnedStructure = asObject(result['scene_structure'])
      const returnedRevision = asString(
        result['rollback_expected_revision'] ?? result['current_revision'] ?? result['revision'] ?? returnedStructure['revision'],
      )
      const refreshed = await load()
      const currentRevision = returnedRevision || structure.revision
      if (migrationId !== '') setRecentMigration({ id: migrationId, expectedRevision: currentRevision })
      setConfirmed(false)
      setNotice(refreshed
        ? { message: migrationId === '' ? '迁移已应用。' : `迁移已应用：${migrationId}`, bad: false }
        : { message: '迁移已提交，但无法刷新确认当前版本。', bad: true })
    } catch (cause: unknown) {
      await mutationFailed(cause, '应用迁移')
    } finally {
      setBusy(false)
    }
  }

  const rollbackMigration = async () => {
    if (state !== 'ready' || recentMigration === null || recentMigration.expectedRevision === '' || busy) return
    setBusy(true)
    setNotice(null)
    try {
      await postStudioApi('/scenes/migration/rollback', {
        migration_id: recentMigration.id,
        expected_revision: recentMigration.expectedRevision,
      })
      const refreshed = await load()
      if (refreshed) setRecentMigration(null)
      setNotice(refreshed
        ? { message: `迁移 ${recentMigration.id} 已回滚。`, bad: false }
        : { message: '回滚已提交，但无法刷新确认当前版本。', bad: true })
    } catch (cause: unknown) {
      await mutationFailed(cause, '回滚迁移')
    } finally {
      setBusy(false)
    }
  }

  const statusText = STATUS_TEXT[structure?.status ?? 'absent']

  return (
    <section className={css.root} aria-labelledby="scene-workbench-title">
      <header className={css.header}>
        <div>
          <h2 id="scene-workbench-title">原生场景结构</h2>
          <p>按稳定场景 ID 管理元数据与章内、跨章顺序。</p>
        </div>
        <button type="button" className={css.button} disabled={state === 'loading' || busy} onClick={() => { void load() }}>
          刷新场景
        </button>
      </header>

      {state === 'loading' && structure === null && <p className={css.notice}>正在读取场景结构…</p>}
      {state === 'error' && (
        <div className={`${css.notice} ${css.bad}`} role="alert">
          <span>{error}</span>
          <button type="button" className={css.button} onClick={() => { void load() }}>重试</button>
        </div>
      )}

      {structure !== null && (
        <>
          <div className={css.statusRow} data-status={structure.status}>
            <strong>{statusText.label}</strong>
            <span>{statusText.explanation}</span>
            {structure.revision !== '' && <code title="场景结构 revision">rev {structure.revision}</code>}
          </div>

          {structure.plannedMissingChapters > 0 && (
            <p className={css.missingNotice} role="note">
              {structure.plannedMissingChapters} 个规划章节尚无稿件；它们保留在项目计划中，不会作为可编辑场景显示。
            </p>
          )}

          {structure.issues.length > 0 && (
            <div className={css.issuePanel}>
              <strong>结构问题（{structure.issues.length}）</strong>
              <ul>{structure.issues.map(issue => <li key={issue.key}>{issueLabel(issue)}</li>)}</ul>
            </div>
          )}

          {notice !== null && <p className={`${css.notice} ${notice.bad ? css.bad : css.good}`} role="status">{notice.message}</p>}

          {structure.status !== 'absent' && (
            <>
              <div className={css.orderToolbar} aria-label="场景排序">
                <span>显示顺序</span>
                <button type="button" data-active={order === 'reading'} onClick={() => setOrder('reading')}>阅读顺序</button>
                <button type="button" data-active={order === 'story-time'} onClick={() => setOrder('story-time')}>故事时间</button>
                <span className={css.count}>{structure.scenes.length} 个可编辑场景</span>
              </div>

              {structure.scenes.length === 0
                ? <p className={css.notice}>当前没有可显示的原生场景。</p>
                : (
                  <ol className={css.sceneList} aria-label={order === 'reading' ? '阅读顺序场景' : '故事时间场景'}>
                    {orderedScenes.map(scene => {
                      const isEditing = editingId === scene.id
                      const source = structure.chapters.find(chapter => chapter.id === scene.chapterId)
                      const target = structure.chapters.find(chapter => chapter.id === move?.targetChapterId)
                      const moveRevisionsReady = scene.revision !== ''
                        && source !== undefined && source.revision !== ''
                        && target !== undefined && target.revision !== ''
                      return (
                        <li key={scene.id} className={css.sceneCard} data-scene-id={scene.id}>
                          <div className={css.sceneHeading}>
                            <div>
                              <code className={css.sceneId}>{scene.id}</code>
                              <span className={css.chapter}>{scene.chapterTitle || scene.chapterId} · {scene.chapterId}</span>
                            </div>
                            <button
                              type="button"
                              className={css.button}
                              disabled={!editable || busy || scene.revision === ''}
                              title={!editable ? '只有 current 场景结构可以修改' : undefined}
                              aria-label={`编辑元数据 ${scene.id}`}
                              onClick={() => beginEdit(scene)}
                            >
                              编辑
                            </button>
                          </div>
                          <h3>{scene.title}</h3>
                          <dl className={css.metadataGrid}>
                            <div><dt>故事时间</dt><dd>{scene.storyTimeLabel || '未标注'}{scene.storyTimeSortKey === '' ? '' : ` · ${scene.storyTimeSortKey}`}</dd></div>
                            <div><dt>人物</dt><dd>{scene.characters.join('、') || '—'}</dd></div>
                            <div><dt>地点</dt><dd>{scene.locations.join('、') || '—'}</dd></div>
                            <div><dt>事件</dt><dd>{scene.events.join('、') || '—'}</dd></div>
                          </dl>

                          {isEditing && metadata !== null && move !== null && (
                            <div className={css.editor} aria-label={`场景编辑器 ${scene.id}`}>
                              <div className={css.formGrid}>
                                <label>标题<input aria-label={`标题 ${scene.id}`} value={metadata.title} onChange={event => setMetadata({ ...metadata, title: event.target.value })} /></label>
                                <label>故事时间排序键<input aria-label={`故事时间排序键 ${scene.id}`} value={metadata.storyTimeSortKey} onChange={event => setMetadata({ ...metadata, storyTimeSortKey: event.target.value })} /></label>
                                <label>故事时间标签<input aria-label={`故事时间标签 ${scene.id}`} value={metadata.storyTimeLabel} onChange={event => setMetadata({ ...metadata, storyTimeLabel: event.target.value })} /></label>
                                <label>人物<input aria-label={`人物 ${scene.id}`} value={metadata.characters} onChange={event => setMetadata({ ...metadata, characters: event.target.value })} /></label>
                                <label>地点<input aria-label={`地点 ${scene.id}`} value={metadata.locations} onChange={event => setMetadata({ ...metadata, locations: event.target.value })} /></label>
                                <label>事件<input aria-label={`事件 ${scene.id}`} value={metadata.events} onChange={event => setMetadata({ ...metadata, events: event.target.value })} /></label>
                              </div>
                              <div className={css.actions}>
                                <button type="button" className={css.primaryButton} disabled={busy || scene.revision === ''} onClick={() => { void saveMetadata(scene) }}>
                                  保存元数据
                                </button>
                                <button type="button" className={css.button} onClick={() => { setEditingId(''); setMetadata(null); setMove(null) }}>取消</button>
                              </div>
                              <div className={css.moveRow}>
                                <label>
                                  目标章
                                  <select aria-label={`目标章 ${scene.id}`} value={move.targetChapterId} onChange={event => setMove({ ...move, targetChapterId: event.target.value })}>
                                    {structure.chapters.map(chapter => <option key={chapter.id} value={chapter.id}>{chapter.title} · {chapter.id}</option>)}
                                  </select>
                                </label>
                                <label>
                                  目标位置（从 0 开始）
                                  <input type="number" min="0" step="1" aria-label={`目标位置 ${scene.id}`} value={move.targetIndex} onChange={event => setMove({ ...move, targetIndex: event.target.value })} />
                                </label>
                                <button type="button" className={css.primaryButton} disabled={busy || !moveRevisionsReady || !/^\d+$/u.test(move.targetIndex)} onClick={() => { void moveScene(scene) }}>
                                  移动场景
                                </button>
                              </div>
                              {!moveRevisionsReady && <p className={css.inlineWarning}>缺少 scene、源章或目标章 revision，无法安全移动。</p>}
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ol>
                )}
            </>
          )}

          <section className={css.migration} aria-labelledby="migration-preview-title">
            <div className={css.migrationHeading}>
              <div>
                <h3 id="migration-preview-title">迁移预览（只读）</h3>
                <p>应用前逐项核对；预览本身不会写入项目。</p>
              </div>
              {preview?.revision !== '' && <code>preview rev {preview?.revision}</code>}
            </div>
            {previewError !== '' && <p className={`${css.notice} ${css.bad}`}>无法读取迁移预览：{previewError}</p>}
            {preview === null && previewError === '' && <p className={css.notice}>暂无迁移预览。</p>}
            {preview !== null && (
              <>
                {preview.rows.length > 0
                  ? <ol className={css.previewList}>{preview.rows.map((row, index) => <li key={`${String(index)}-${row}`}>{row}</li>)}</ol>
                  : <p className={css.notice}>预览中没有迁移项。</p>}
                {preview.issues.length > 0 && <ul className={css.previewIssues}>{preview.issues.map(issue => <li key={issue.key}>{issueLabel(issue)}</li>)}</ul>}
                {(structure.status === 'absent' || structure.status === 'stale') && (
                  <div className={css.confirmRow}>
                    <label>
                      <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
                      我已核对只读预览，确认应用迁移
                    </label>
                    <button
                      type="button"
                      className={css.primaryButton}
                      disabled={state !== 'ready' || busy || !confirmed || preview.revision === '' || !preview.canApply}
                      onClick={() => { void applyMigration() }}
                    >
                      应用迁移
                    </button>
                  </div>
                )}
              </>
            )}
            {recentMigration !== null && (
              <div className={css.rollbackRow}>
                <span>本会话最近迁移：<code>{recentMigration.id}</code></span>
                <button type="button" className={css.button} disabled={state !== 'ready' || busy || recentMigration.expectedRevision === ''} onClick={() => { void rollbackMigration() }}>
                  回滚最近迁移
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  )
}
