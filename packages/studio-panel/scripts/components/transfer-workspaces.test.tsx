import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ManuscriptImportWorkspace, ProjectArchiveWorkspace } from '../../src/client/TransferWorkspaces.tsx'
import { setStudioContext } from '../../src/client/api.ts'

const harness = vi.hoisted(() => ({ invalidate: vi.fn() }))
vi.mock('../../src/client/WorkbenchStore.ts', () => ({ workbenchStore: { invalidate: harness.invalidate } }))

const t = (key: string): string => key
const importId = 'import_20260905000000_abcdef123456'
const archiveId = 'owa_0123456789abcdef01234567'

function stages(structureStatus = 'pending') {
  return Object.fromEntries(['snapshot', 'split', 'structure_confirmed', 'published', 'acceptance', 'reconcile', 'synthesis', 'complete']
    .map(name => [name, { status: name === 'snapshot' || name === 'split' ? 'completed' : name === 'structure_confirmed' ? structureStatus : 'pending', attempts: 1, input_sha256: `in-${name}`, output_sha256: `out-${name}`, error_code: '' }]))
}

function importOperation(status = 'awaiting_confirmation', structureStatus = 'pending') {
  return {
    schema_version: 'openwrite.manuscript-import.v1', import_id: importId, novel_id: 'demo', status, arc_id: 'arc_003',
    source: { filename: '我的旧稿.md', suffix: '.md', bytes: 100, sha256: 'sha256:source', original_path: '/private/never-render' },
    preview_revision: 'sha256:preview-1', confirmed_preview_revision: '', chapter_count: 2, writing_units: 8,
    stages: stages(structureStatus), publication_transaction: {}, published_chapters: [], acceptance_operation_id: '', acceptance_status: '',
    created_at: '2026-09-05T00:00:00Z', updated_at: '2026-09-05T00:01:00Z', last_error: null,
  }
}

function importDetail(status = 'awaiting_confirmation', revision = 'sha256:preview-1') {
  return { ok: true, data: {
    operation: importOperation(status, status === 'ready_to_publish' ? 'completed' : 'pending'),
    preview: {
      schema_version: 'openwrite.manuscript-import-preview.v1', import_id: importId, arc_id: 'arc_003', source_sha256: 'sha256:source',
      revision, chapter_count: 2, writing_units: 8, updated_at: '2026-09-05T00:01:00Z',
      chapters: [
        { order: 0, chapter_id: 'ch_005', title: '雨夜', content: '门外有人。', writing_units: 4, sha256: 'sha256:c1' },
        { order: 1, chapter_id: 'ch_006', title: '回声', content: '门后无人。', writing_units: 4, sha256: 'sha256:c2' },
      ],
    },
  } }
}

function importList() {
  return { ok: true, data: { schema_version: 'openwrite.manuscript-import.v1', novel_id: 'demo', operations: [importOperation()], counts: { awaiting_confirmation: 1 } } }
}

const archivePlan = {
  schema_version: 'openwrite.novel-archive.v1', novel_id: 'demo', archive_id: archiveId, preflight_revision: 'sha256:preflight',
  policies: { tasks: 'archive_no_resume', target: 'new_or_empty', references: { default: 'preserve_relative', supported: ['preserve_relative', 'rewrite_novel_id'] } },
  includes: {
    roots: ['novel_config.yaml'], file_count: 2, total_size: 345, category_counts: { config: 1, manuscript: 1 }, directories: ['data/novels/demo'],
    files: [
      { path: 'novel_config.yaml', archive_path: 'project/novel_config.yaml', category: 'config', sha256: 'sha256:config', size: 45 },
      { path: 'data/novels/demo/data/manuscript/arc_001/ch_001.md', archive_path: 'project/data/ch.md', category: 'manuscript', sha256: 'sha256:chapter', size: 300 },
    ],
  },
  excludes: { rules: ['secrets'], entries: [{ path: '.env', reason: 'secret' }] },
  missing: { required: [], optional: [{ path: 'data/reviews', reason: 'absent' }] },
  reference_inventory: { known: [{ path: 'novel_config.yaml', location: '$.novel_id', kind: 'novel_id' }], preserved: [], warnings: [{ path: 'refs.json', kind: 'absolute_reference_preserved' }] },
}

function archiveFetch(path: string) {
  if (path === '/project-archives/preflight') return { ok: true, data: archivePlan }
  if (path === '/project-archives') return { ok: true, data: { schema_version: 'openwrite.novel-archive.v1', novel_id: 'demo', archives: [{ archive_id: archiveId, archive_sha256: 'sha256:archive', created_at: '2026-09-05T00:00:00Z', file_count: 2, total_size: 345, missing: archivePlan.missing }] } }
  if (path === `/project-archives/${archiveId}`) return { ok: true, data: { archive: { archive_sha256: 'sha256:archive', file_count: 2, total_size: 345, manifest: archivePlan } } }
  return { ok: true, data: {} }
}

function sharedProps(overrides: Record<string, unknown> = {}) {
  return {
    t, busy: '', setBusy: vi.fn(), say: vi.fn(), workspaceReady: true, tasksEpoch: 0, workspaceEpoch: 0,
    fetchStudioApi: vi.fn(async () => ({ ok: true, data: {} })), postStudioApi: vi.fn(async () => ({ ok: true, data: {} })),
    ...overrides,
  }
}

beforeEach(() => {
  setStudioContext({ workspaceId: 'ws-a', sessionId: 's1' })
  harness.invalidate.mockClear()
})

describe('resumable manuscript import workspace', () => {
  it('edits revision-bound chapter boundaries, confirms them, then starts the durable task', async () => {
    let current = importDetail()
    const fetchStudioApi = vi.fn(async path => path === '/manuscript-imports' ? importList() : current)
    const postStudioApi = vi.fn(async (path, body) => {
      if (path === '/manuscript-imports/structure') {
        current = importDetail('awaiting_confirmation', 'sha256:preview-2')
        current.data.preview.chapters[0].title = String((body as { chapters: { title: string }[] }).chapters[0]?.title)
        return current
      }
      if (path === '/manuscript-imports/confirm') {
        current = { ok: true, data: { operation: importOperation('ready_to_publish', 'completed'), preview: null } } as typeof current
        return current
      }
      if (path === '/manuscript-imports/run') return { ok: true, data: { task_id: 'tsk_import_1' } }
      return { ok: true, data: {} }
    })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ManuscriptImportWorkspace {...(sharedProps({ fetchStudioApi, postStudioApi }) as any)} />)

    await screen.findByDisplayValue('雨夜')
    expect(screen.queryByText('/private/never-render')).toBeNull()
    expect(screen.getByText('out-snapshot')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('tools.import.workspace.chapterTitle 1'), { target: { value: '雨夜来信' } })
    fireEvent.click(screen.getByText('tools.import.workspace.saveStructure'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/manuscript-imports/structure', expect.objectContaining({
      import_id: importId, expected_preview_revision: 'sha256:preview-1',
      chapters: expect.arrayContaining([expect.objectContaining({ chapter_id: 'ch_005', title: '雨夜来信', content: '门外有人。' })]),
    })))

    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await screen.findByText('sha256:preview-2')
    fireEvent.click(screen.getByText('tools.import.workspace.confirmStructure'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/manuscript-imports/confirm', {
      import_id: importId, expected_preview_revision: 'sha256:preview-2', confirm: true,
    }))
    fireEvent.click(await screen.findByText('tools.import.workspace.run'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/manuscript-imports/run', { import_id: importId }))
    expect(harness.invalidate).toHaveBeenCalledWith('tasks')
  })

  it('prepares the author manuscript separately from reference analysis and explicitly discards an unpublished operation', async () => {
    const fetchStudioApi = vi.fn(async path => path === '/manuscript-imports' ? importList() : importDetail())
    const postStudioApi = vi.fn(async path => path === '/manuscript-imports/prepare' ? importDetail() : { ok: true, data: { operation: importOperation('discarded') } })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ManuscriptImportWorkspace {...(sharedProps({ fetchStudioApi, postStudioApi }) as any)} />)
    await screen.findByText('tools.import.workspace.ownHint')
    const file = new File(['# 第一章\n正文'], '作者旧稿.md', { type: 'text/markdown' })
    Object.defineProperty(file, 'text', { value: async () => '# 第一章\n正文' })
    fireEvent.change(screen.getByLabelText('tools.import.workspace.file'), { target: { files: [file] } })
    fireEvent.click(await screen.findByText('tools.import.workspace.prepare'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/manuscript-imports/prepare', {
      filename: '作者旧稿.md', content: '# 第一章\n正文', arc_id: 'arc_001',
    }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(await screen.findByText('tools.import.workspace.discard'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/manuscript-imports/discard', { import_id: importId, confirm: true }))
  })
})

describe('project archive workspace', () => {
  it('shows archive scope/checksums and performs a confirmed restore with archived tasks', async () => {
    const fetchStudioApi = vi.fn(async path => archiveFetch(path))
    const restorePreview = {
      archive_id: archiveId, archive_sha256: 'sha256:archive', source_novel_id: 'demo', target_novel_id: 'restored_demo',
      target_root: '/restore/demo', reference_policy: 'rewrite_novel_id', can_restore: true, conflicts: [], file_count: 2, total_size: 345,
      missing: archivePlan.missing, task_file_count: 4, task_archive_path: 'data/novels/restored_demo/data/workflows/task_archive/archive', auto_resume_tasks: false,
      path_rewrites: [{ source: 'data/novels/demo', target: 'data/novels/restored_demo' }],
      rewritten_files: [{ source_path: 'novel_config.yaml', target_path: 'novel_config.yaml', sha256_before: 'sha256:old', sha256_after: 'sha256:new', reference_count: 1 }],
      rewritten_references: [{ path: 'novel_config.yaml', location: '$.novel_id', kind: 'novel_id', before: 'demo', after: 'restored_demo', replacement_count: 1 }], preserved_references: [],
      reference_warnings: [{ path: 'refs.json', kind: 'absolute_reference_preserved' }], reference_conflicts: [],
    }
    const postStudioApi = vi.fn(async path => path.endsWith('/preview') ? { ok: true, data: restorePreview } : { ok: true, data: { task_id: 'tsk_restore_1' } })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ProjectArchiveWorkspace {...(sharedProps({ fetchStudioApi, postStudioApi, workspaces: { pickDirectory: vi.fn(async () => '/restore/demo') } }) as any)} />)

    await screen.findByText('novel_config.yaml')
    expect(screen.getByText('.env · secret')).toBeTruthy()
    expect(screen.getByText('config: 1 · manuscript: 1')).toBeTruthy()
    expect(screen.getByText('sha256:config', { exact: false })).toBeTruthy()
    fireEvent.click(screen.getByText(archiveId))
    await waitFor(() => expect(fetchStudioApi).toHaveBeenCalledWith(`/project-archives/${archiveId}`))
    fireEvent.change(screen.getByLabelText('tools.archive.targetRoot'), { target: { value: '/restore/demo' } })
    fireEvent.change(screen.getByLabelText('tools.archive.targetNovelId'), { target: { value: 'restored_demo' } })
    fireEvent.change(screen.getByLabelText('tools.archive.referencePolicy'), { target: { value: 'rewrite_novel_id' } })
    fireEvent.click(screen.getByText('tools.archive.previewRestore'))
    await screen.findByText('data/novels/demo → data/novels/restored_demo')
    expect(screen.getByText('novel_config.yaml · $.novel_id · demo → restored_demo')).toBeTruthy()
    expect(screen.getByText('tools.archive.noAutoResume', { exact: false })).toBeTruthy()

    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByText('tools.archive.confirmRestore'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/project-archives/restore', {
      archive_id: archiveId, target_root: '/restore/demo', target_novel_id: 'restored_demo',
      reference_policy: 'rewrite_novel_id', archive_sha256: 'sha256:archive', confirm: true,
    }))
    expect(harness.invalidate).toHaveBeenCalledWith('tasks')
  })

  it('creates from the current preflight revision and downloads the selected archive', async () => {
    const fetchStudioApi = vi.fn(async path => archiveFetch(path))
    const postStudioApi = vi.fn(async () => ({ ok: true, data: { archive: { archive_id: archiveId } } }))
    const downloadFetch = vi.fn(async () => new Response('zip', { headers: { 'content-disposition': `attachment; filename=${archiveId}.owarchive.zip` } }))
    vi.stubGlobal('fetch', downloadFetch)
    const NativeUrl = URL
    class DownloadUrl extends NativeUrl { static createObjectURL = vi.fn(() => 'blob:archive'); static revokeObjectURL = vi.fn() }
    vi.stubGlobal('URL', DownloadUrl)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<ProjectArchiveWorkspace {...(sharedProps({ fetchStudioApi, postStudioApi, workspaces: { pickDirectory: vi.fn() } }) as any)} />)

    fireEvent.click(await screen.findByText('tools.archive.create'))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/project-archives/create', { expected_preflight_revision: 'sha256:preflight' }))
    fireEvent.click(screen.getByLabelText(`tools.archive.download ${archiveId}`))
    await waitFor(() => expect(downloadFetch).toHaveBeenCalledWith(`/studio-panel/api/project-archives/${archiveId}/download`, expect.objectContaining({ headers: expect.objectContaining({ 'X-Dsh-Workspace-Id': 'ws-a' }) })))
  })
})
