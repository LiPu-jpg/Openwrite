import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SceneWorkbench } from '../../src/client/SceneWorkbench.tsx'
import { StudioApiError } from '../../src/client/api.ts'

function sceneEnvelope(options: { status?: string, plannedMissing?: number } = {}) {
  return {
    data: {
      schema_version: 'openwrite.scene-structure.v1',
      status: options.status ?? 'current',
      revision: 'structure-r1',
      ...(options.plannedMissing === undefined ? {} : { planned_missing_chapters: options.plannedMissing }),
      chapters: [
        {
          chapter_id: 'ch_001', title: '第一章', status: 'present', freshness: 'current', revision: 'chapter-one-r4',
        },
        {
          chapter_id: 'ch_002', title: '第二章', status: 'present', freshness: 'current', revision: 'chapter-two-r5',
        },
      ],
      reading_order: ['scene-a', 'scene-b'],
      story_time_order: ['scene-b', 'scene-a'],
      mutation_allowed: options.status === undefined || options.status === 'current',
      scenes: [
        {
          scene_id: 'scene-a', title: '较晚发生', order: 0, freshness: 'current',
          chapter: { chapter_id: 'ch_001', title: '第一章', revision: 'chapter-one-r4', reading_index: 0 },
          story_time: { sort_key: '20', label: '第二天' },
          references: { characters: ['阿青'], locations: ['城门'], events: ['归来'] },
        },
        {
          scene_id: 'scene-b', title: '较早发生', order: 1, freshness: 'current',
          chapter: { chapter_id: 'ch_001', title: '第一章', revision: 'chapter-one-r4', reading_index: 0 },
          story_time: { sort_key: '10', label: '第一天' },
          references: { characters: ['小满'], locations: ['客栈'], events: ['相遇'] },
        },
      ],
      issues: [
        { code: 'SCENE_TIME_GAP', scene_id: 'scene-a', chapter_id: 'ch_001', message: '故事时间跨度待核对' },
      ],
    },
  }
}

function previewEnvelope() {
  return {
    data: {
      schema_version: 'openwrite.scene-migration-preview.v1',
      preview_revision: 'preview-r3',
      can_apply: true,
      plan: [
        {
          chapter_id: 'ch_001', source_revision: 'chapter-one-r4',
          scenes: [{ scene_id: 'stable-scene-1', title: '旧分隔符后的场景' }],
        },
      ],
      issues: [],
    },
  }
}

function apiFor(structure: unknown) {
  const fetchStudioApi = vi.fn(async (path: string) => path === '/scenes' ? structure : previewEnvelope())
  const postStudioApi = vi.fn(async () => ({ data: { revision: 'structure-r2' } }))
  return { fetchStudioApi, postStudioApi }
}

describe('SceneWorkbench migration', () => {
  it('keeps the preview read-only and requires explicit confirmation before apply', async () => {
    const api = apiFor(sceneEnvelope({ status: 'absent' }))
    api.postStudioApi.mockResolvedValueOnce({
      data: { migration_id: 'migration-7', scene_structure: { revision: 'structure-r2' } },
    })
    render(<SceneWorkbench {...api} />)

    const preview = await screen.findByRole('heading', { name: '迁移预览（只读）' })
    expect(screen.getByText(/stable-scene-1/)).toBeTruthy()
    expect(preview.closest('section')?.querySelectorAll('input:not([type="checkbox"])')).toHaveLength(0)

    const apply = screen.getByRole('button', { name: '应用迁移' })
    expect((apply as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox', { name: /确认应用迁移/ }))
    expect((apply as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(apply)

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/scenes/migration/apply', {
      expected_preview_revision: 'preview-r3', confirm: true,
    }))
    expect((await screen.findAllByText(/migration-7/)).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: '回滚最近迁移' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/scenes/migration/rollback', {
      migration_id: 'migration-7', expected_revision: 'structure-r2',
    }))
  })

  it('allows an explicitly confirmed stale re-anchor with the exact preview revision', async () => {
    const stale = sceneEnvelope({ status: 'stale' })
    const current = sceneEnvelope({ status: 'current' })
    current.data.revision = 'structure-r2'
    let sceneReads = 0
    const fetchStudioApi = vi.fn(async (path: string) => {
      if (path !== '/scenes') return previewEnvelope()
      sceneReads += 1
      return sceneReads === 1 ? stale : current
    })
    const postStudioApi = vi.fn(async () => ({
      data: { migration_id: 'migration-reanchor', scene_structure: current.data },
    }))
    render(<SceneWorkbench fetchStudioApi={fetchStudioApi} postStudioApi={postStudioApi} />)

    expect(await screen.findByText(/stale · 已过期/)).toBeTruthy()
    fireEvent.click(screen.getByRole('checkbox', { name: /确认应用迁移/ }))
    fireEvent.click(screen.getByRole('button', { name: '应用迁移' }))

    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith('/scenes/migration/apply', {
      expected_preview_revision: 'preview-r3', confirm: true,
    }))
    expect(await screen.findByText(/current · 当前/)).toBeTruthy()
  })

  it('refreshes a stale migration preview conflict without showing success', async () => {
    const api = apiFor(sceneEnvelope({ status: 'stale' }))
    api.postStudioApi.mockRejectedValueOnce(new StudioApiError('preview changed', 409, 'SCENE_MIGRATION_CONFLICT'))
    render(<SceneWorkbench {...api} />)

    await screen.findByText(/stale · 已过期/)
    fireEvent.click(screen.getByRole('checkbox', { name: /确认应用迁移/ }))
    fireEvent.click(screen.getByRole('button', { name: '应用迁移' }))

    expect(await screen.findByText(/结构已刷新，请基于最新版本重试/)).toBeTruthy()
    expect(api.fetchStudioApi.mock.calls.filter(call => call[0] === '/scenes')).toHaveLength(2)
    expect(screen.queryByText(/迁移已应用/)).toBeNull()
  })
})

describe('SceneWorkbench revision-guarded editing', () => {
  it('sends metadata CAS and exact source/target revisions for a cross-chapter move', async () => {
    const api = apiFor(sceneEnvelope())
    render(<SceneWorkbench {...api} />)

    fireEvent.click(await screen.findByRole('button', { name: '编辑元数据 scene-a' }))
    fireEvent.change(screen.getByRole('textbox', { name: '标题 scene-a' }), { target: { value: '城门重逢' } })
    fireEvent.change(screen.getByRole('textbox', { name: '人物 scene-a' }), { target: { value: '阿青，小满' } })
    fireEvent.click(screen.getByRole('button', { name: '保存元数据' }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/scenes/metadata', {
      scene_id: 'scene-a',
      expected_revision: 'structure-r1',
      title: '城门重逢',
      story_time_sort_key: '20',
      story_time_label: '第二天',
      characters: ['阿青', '小满'],
      locations: ['城门'],
      events: ['归来'],
    }))

    fireEvent.click(await screen.findByRole('button', { name: '编辑元数据 scene-a' }))
    fireEvent.change(screen.getByRole('combobox', { name: '目标章 scene-a' }), { target: { value: 'ch_002' } })
    fireEvent.change(screen.getByRole('spinbutton', { name: '目标位置 scene-a' }), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '移动场景' }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/scenes/move', {
      scene_id: 'scene-a',
      target_chapter_id: 'ch_002',
      target_index: 0,
      expected_revision: 'structure-r1',
      expected_source_revision: 'chapter-one-r4',
      expected_target_revision: 'chapter-two-r5',
    }))
  })

  it('uses the same exact chapter revision on both sides of an in-chapter move', async () => {
    const api = apiFor(sceneEnvelope())
    render(<SceneWorkbench {...api} />)

    fireEvent.click(await screen.findByRole('button', { name: '编辑元数据 scene-b' }))
    fireEvent.change(screen.getByRole('spinbutton', { name: '目标位置 scene-b' }), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '移动场景' }))

    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/scenes/move', {
      scene_id: 'scene-b',
      target_chapter_id: 'ch_001',
      target_index: 0,
      expected_revision: 'structure-r1',
      expected_source_revision: 'chapter-one-r4',
      expected_target_revision: 'chapter-one-r4',
    }))
  })

  it('refreshes on a conflict and never reports the rejected mutation as success', async () => {
    const api = apiFor(sceneEnvelope())
    api.postStudioApi.mockRejectedValueOnce(new StudioApiError('revision mismatch', 409, 'SCENE_REVISION_CONFLICT'))
    render(<SceneWorkbench {...api} />)

    fireEvent.click(await screen.findByRole('button', { name: '编辑元数据 scene-a' }))
    fireEvent.change(screen.getByRole('textbox', { name: '标题 scene-a' }), { target: { value: '冲突标题' } })
    fireEvent.click(screen.getByRole('button', { name: '保存元数据' }))

    expect(await screen.findByText(/结构已刷新，请基于最新版本重试/)).toBeTruthy()
    expect(api.fetchStudioApi.mock.calls.filter(call => call[0] === '/scenes')).toHaveLength(2)
    expect(screen.queryByText(/元数据已保存/)).toBeNull()
  })

  it('disables all scene mutations while the structure is stale', async () => {
    const api = apiFor(sceneEnvelope({ status: 'stale' }))
    render(<SceneWorkbench {...api} />)

    expect(await screen.findByText(/stale · 已过期/)).toBeTruthy()
    const editButtons = screen.getAllByRole('button', { name: /编辑元数据 scene-/ })
    for (const button of editButtons) expect((button as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(editButtons[0]!)
    expect(screen.queryByRole('button', { name: '保存元数据' })).toBeNull()
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })
})

describe('SceneWorkbench projections and missing chapters', () => {
  it('switches between reading order and story-time order', async () => {
    const api = apiFor(sceneEnvelope())
    render(<SceneWorkbench {...api} />)

    const reading = await screen.findByRole('list', { name: '阅读顺序场景' })
    expect(within(reading).getAllByRole('listitem').map(item => item.getAttribute('data-scene-id'))).toEqual(['scene-a', 'scene-b'])

    fireEvent.click(screen.getByRole('button', { name: '故事时间' }))
    const storyTime = screen.getByRole('list', { name: '故事时间场景' })
    expect(within(storyTime).getAllByRole('listitem').map(item => item.getAttribute('data-scene-id'))).toEqual(['scene-b', 'scene-a'])
  })

  it('keeps 127 planned-missing chapters visible as a notice but out of scenes and move targets', async () => {
    const structure = sceneEnvelope()
    for (let index = 0; index < 127; index += 1) {
      structure.data.chapters.push({
        chapter_id: `ch_missing_${String(index)}`, title: `规划章 ${String(index + 1)}`,
        status: 'missing', freshness: 'planned_missing', revision: '',
      } as never)
      structure.data.issues.push({
        code: 'MISSING_CHAPTER_FILE', chapter_id: `ch_missing_${String(index)}`,
        message: `missing ${String(index)}`,
      })
    }
    structure.data.scenes.push({
      scene_id: 'fake-planned-scene', title: '不应显示', order: 0, freshness: 'absent',
      chapter: { chapter_id: 'ch_missing_0', title: '规划章 1', revision: '', reading_index: 999 },
      story_time: { sort_key: '', label: '' }, references: { characters: [], locations: [], events: [] },
    } as never)
    const api = apiFor(structure)
    render(<SceneWorkbench {...api} />)

    expect(await screen.findByText(/127 个规划章节尚无稿件/)).toBeTruthy()
    expect(screen.queryByText('fake-planned-scene')).toBeNull()
    expect(screen.getByText('2 个可编辑场景')).toBeTruthy()
    expect(screen.queryByText(/MISSING_CHAPTER_FILE/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '编辑元数据 scene-a' }))
    const target = screen.getByRole('combobox', { name: '目标章 scene-a' })
    expect(within(target).queryByRole('option', { name: /ch_missing_0/ })).toBeNull()
  })
})
