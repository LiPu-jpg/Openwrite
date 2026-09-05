import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  novelMutationDefinition,
  TurnMutationSummaryView,
  type NovelMutationSummary,
} from '../../src/client/TurnMutationSummary.tsx'

function startState() {
  return novelMutationDefinition.start({} as never, {
    event: { type: 'turn/start', data: { turn: 7 } },
  } as never, {} as never)
}

function update(state: ReturnType<typeof startState>, event: Record<string, unknown>) {
  return novelMutationDefinition.update!({ state } as never, { event } as never)
}

function resultMessage(callId: string, payload: unknown, isError = false) {
  return {
    source: { callId },
    content: [{
      type: 'tool-result',
      toolCallId: callId,
      isError,
      content: [{ type: 'text', text: JSON.stringify({ data: payload }) }],
    }],
  }
}

describe('TurnMutationSummary', () => {
  it('records the committed output path, revision, and recoverable history entry', () => {
    let state = startState()
    state = update(state, {
      type: 'tool/call',
      data: {
        turn: 7, callId: 'call_write', name: 'novel_doc_write',
        arguments: JSON.stringify({ path: 'requested.md' }),
      },
    })
    state = update(state, {
      type: 'tool/result',
      data: {
        turn: 7,
        message: resultMessage('call_write', {
          path: 'data/manuscript/ch_001.md',
          revision: 'sha256:new',
          author_version: { version_id: 'ver_before_write' },
        }),
      },
    })

    expect(state.items).toEqual([expect.objectContaining({
      callId: 'call_write',
      path: 'data/manuscript/ch_001.md',
      revision: 'sha256:new',
      historyVersionId: 'ver_before_write',
      status: 'succeeded',
    })])
  })

  it('keeps failed and partial calls instead of reporting every call as a write', () => {
    let state = startState()
    for (const [callId, name] of [['call_failed', 'novel_revision_apply'], ['call_partial', 'novel_multi_write']] as const) {
      state = update(state, {
        type: 'tool/call',
        data: { turn: 7, callId, name, arguments: '{}' },
      })
    }
    state = update(state, {
      type: 'tool/result',
      data: {
        turn: 7,
        message: resultMessage('call_failed', { code: 'DOCUMENT_CONFLICT' }, true),
        error: { name: 'Error', code: 'DOCUMENT_CONFLICT' },
      },
    })
    state = update(state, {
      type: 'tool/result',
      data: {
        turn: 7,
        message: resultMessage('call_partial', { failures: [{ chapter_id: 'ch_002' }] }),
      },
    })

    expect(state.items.map(item => item.status)).toEqual(['failed', 'partial'])
    expect(state.items[0]?.errorCode).toBe('DOCUMENT_CONFLICT')
  })

  it('shows partial status and opens the actual changed file', () => {
    const openFile = vi.fn()
    const matched: NovelMutationSummary = {
      items: [{
        callId: 'call_one', tool: 'novel_doc_write', label: '更新文档',
        path: 'data/manuscript/ch_001.md', status: 'refresh_failed',
        errorCode: '', historyVersionId: 'ver_before_write', revision: 'sha256:new',
        sourceRevision: '', resultRevision: '', changes: [],
        previewToken: '', undoPreviewToken: '',
      }],
    }
    render(<TurnMutationSummaryView {...({ matched, openFile, t: (key: string) => key } as never)} />)

    expect(screen.getByText('turn.partial')).not.toBeNull()
    expect(screen.getByText('turn.refreshFailed')).not.toBeNull()
    expect(screen.getByText(/ver_before_write/)).not.toBeNull()
    fireEvent.click(screen.getByRole('button'))
    expect(openFile).toHaveBeenCalledWith('data/manuscript/ch_001.md')
  })

  it('renders real entity before and after values with source and result revisions', () => {
    let state = startState()
    state = update(state, {
      type: 'tool/call',
      data: {
        turn: 7, callId: 'call_asset', name: 'novel_asset_update',
        arguments: JSON.stringify({ kind: 'character', id: 'lin_cen' }),
      },
    })
    state = update(state, {
      type: 'tool/result',
      data: {
        turn: 7,
        message: resultMessage('call_asset', {
          operation_trace: {
            schema_version: 'openwrite.operation-trace.v1',
            trace_id: 'trace_001', path: 'data/traces/trace_001.json',
            model_call_count: 2, retention: { max_age_days: 30 },
          },
          mutation_summary: {
            schema_version: 'openwrite.mutation-summary.v1',
            execution_status: 'committed',
            source_revision: 'sha256:before',
            result_revision: 'sha256:after',
            items: [{
              change_id: 'character:lin_cen:data.goal',
              entity_kind: 'character', entity_id: 'lin_cen',
              path: 'src/characters/lin_cen.md', field: 'data.goal',
              source_revision: 'sha256:before', result_revision: 'sha256:after',
              execution_status: 'committed',
              before: { kind: 'text', value: '逃离', preview: '逃离', truncated: false, units: 2, sha256: 'sha256:a' },
              after: { kind: 'text', value: '保护旧城', preview: '保护旧城', truncated: false, units: 4, sha256: 'sha256:b' },
            }],
          },
        }),
      },
    })

    expect(state.items[0]).toEqual(expect.objectContaining({
      path: 'src/characters/lin_cen.md',
      sourceRevision: 'sha256:before',
      resultRevision: 'sha256:after',
      traceId: 'trace_001',
      tracePath: 'data/traces/trace_001.json',
      modelCallCount: 2,
      traceRetentionDays: 30,
      changes: [expect.objectContaining({
        entityKind: 'character', entityId: 'lin_cen', field: 'data.goal',
      })],
    }))

    const openFile = vi.fn()
    render(<TurnMutationSummaryView {...({
      matched: { items: state.items }, openFile, t: (key: string) => key,
    } as never)} />)
    fireEvent.click(screen.getByText(/turn.entityChanges/))
    expect(screen.getByText('逃离')).not.toBeNull()
    expect(screen.getByText('保护旧城')).not.toBeNull()
    expect(screen.getByText(/sha256:before/)).not.toBeNull()
    expect(screen.getByText(/sha256:after/)).not.toBeNull()
    expect(screen.getByText(/data.goal/)).not.toBeNull()
    const traceButton = screen.getByRole('button', { name: /trace_001/ })
    expect(traceButton.textContent).toContain('2 turn.modelCalls')
    expect(traceButton.textContent).toContain('30 turn.days')
    fireEvent.click(traceButton)
    expect(openFile).toHaveBeenCalledWith('data/traces/trace_001.json')
  })

  it('distinguishes a preview and applies only its immutable token after acceptance', async () => {
    let state = startState()
    state = update(state, {
      type: 'tool/call',
      data: {
        turn: 7, callId: 'call_plan', name: 'novel_document_change_plan',
        arguments: JSON.stringify({ action: 'preview', path: 'src/story/background.md' }),
      },
    })
    state = update(state, {
      type: 'tool/result',
      data: {
        turn: 7,
        message: resultMessage('call_plan', {
          applied: false,
          preview_token: 'a'.repeat(24),
          mutation_summary: {
            schema_version: 'openwrite.mutation-summary.v1',
            execution_status: 'proposed',
            source_revision: 'sha256:before',
            result_revision: 'sha256:predicted',
            items: [{
              change_id: 'canon:background:content', entity_kind: 'canon',
              entity_id: 'background', path: 'src/story/background.md', field: 'content',
              source_revision: 'sha256:before', result_revision: 'sha256:predicted',
              execution_status: 'proposed',
              before: { kind: 'text', value: '旧背景', preview: '旧背景', truncated: false, units: 3, sha256: 'sha256:a' },
              after: { kind: 'text', value: '新背景', preview: '新背景', truncated: false, units: 3, sha256: 'sha256:b' },
            }],
          },
        }),
      },
    })

    expect(state.items[0]?.status).toBe('proposed')
    const postStudioApi = vi.fn().mockResolvedValue({
      status: 'applied', undo_preview_token: 'b'.repeat(24),
      mutation_summary: {
        schema_version: 'openwrite.mutation-summary.v1', execution_status: 'committed',
        source_revision: 'sha256:before', result_revision: 'sha256:after',
        items: [{
          change_id: 'canon:background:content', entity_kind: 'canon', entity_id: 'background',
          path: 'src/story/background.md', field: 'content', source_revision: 'sha256:before',
          result_revision: 'sha256:after', execution_status: 'committed',
          before: { kind: 'text', value: '旧背景', preview: '旧背景', truncated: false, units: 3, sha256: 'sha256:a' },
          after: { kind: 'text', value: '新背景', preview: '新背景', truncated: false, units: 3, sha256: 'sha256:b' },
        }],
      },
    })
    render(<TurnMutationSummaryView {...({
      matched: { items: state.items }, openFile: vi.fn(), postStudioApi, t: (key: string) => key,
    } as never)} />)
    expect(screen.getAllByText('turn.proposed').length).toBeGreaterThan(0)
    expect(screen.queryByText('turn.changed')).toBeNull()
    fireEvent.click(screen.getByText(/turn.entityChanges/))
    expect(screen.getByRole('button', { name: 'turn.reject' })).not.toBeNull()
    expect(screen.getByRole('button', { name: 'turn.retry' })).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'turn.accept' }))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith(
      '/document/change-plan', { action: 'apply', preview_token: 'a'.repeat(24) },
    ))
    expect(await screen.findByText('turn.applied')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'turn.undo' }))
    await waitFor(() => expect(postStudioApi).toHaveBeenLastCalledWith(
      '/document/change-plan', { action: 'undo', preview_token: 'b'.repeat(24) },
    ))
    expect(await screen.findByText('turn.undone')).not.toBeNull()
  })

  it('routes structured preview actions through the structured server plan', async () => {
    let state = startState()
    state = update(state, {
      type: 'tool/call',
      data: {
        turn: 8, callId: 'call_structured', name: 'novel_structured_change_plan',
        arguments: JSON.stringify({ action: 'preview', change_kind: 'focus', change: { goal: '守桥' } }),
      },
    })
    state = update(state, {
      type: 'tool/result',
      data: {
        turn: 8,
        message: resultMessage('call_structured', {
          status: 'proposed', change_kind: 'focus', preview_token: 'c'.repeat(24),
          mutation_summary: {
            schema_version: 'openwrite.mutation-summary.v1', execution_status: 'proposed',
            source_revision: 'sha256:before', result_revision: 'sha256:after',
            items: [{
              change_id: 'canon:current_focus:goal', entity_kind: 'canon',
              entity_id: 'current_focus', path: 'src/story/current_focus.md', field: 'goal',
              source_revision: 'sha256:before', result_revision: 'sha256:after',
              execution_status: 'proposed',
              before: { kind: 'text', value: '', preview: '', truncated: false, units: 0, sha256: 'sha256:a' },
              after: { kind: 'text', value: '守桥', preview: '守桥', truncated: false, units: 2, sha256: 'sha256:b' },
            }],
          },
        }),
      },
    })
    const postStudioApi = vi.fn().mockResolvedValue({
      status: 'applied', change_kind: 'focus', undo_preview_token: 'd'.repeat(24),
      mutation_summary: {
        schema_version: 'openwrite.mutation-summary.v1', execution_status: 'committed',
        source_revision: 'sha256:before', result_revision: 'sha256:after', items: [],
      },
    })
    render(<TurnMutationSummaryView {...({
      matched: { items: state.items }, openFile: vi.fn(), postStudioApi, t: (key: string) => key,
    } as never)} />)
    fireEvent.click(screen.getByText(/turn.entityChanges/))
    fireEvent.click(screen.getByRole('button', { name: 'turn.accept' }))
    await waitFor(() => expect(postStudioApi).toHaveBeenCalledWith(
      '/structured/change-plan', { action: 'apply', preview_token: 'c'.repeat(24) },
    ))
  })
})
