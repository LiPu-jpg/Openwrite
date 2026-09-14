import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProjectMetadataEditor } from '../../src/client/ProjectMetadataEditor.tsx'

const project = { metadata: { title: '雾城', author: '', language: 'zh-CN' }, metadata_revision: 'sha256:original' }
const t = (key: string) => key

describe('publication metadata editing', () => {
  it('loads current metadata and saves with its revision before refreshing export', async () => {
    const fetchStudioApi = vi.fn(async () => ({ project }))
    const postStudioApi = vi.fn(async () => ({}))
    const onSaved = vi.fn()
    render(<ProjectMetadataEditor {...({ fetchStudioApi, postStudioApi, onSaved, t } as any)} />)
    fireEvent.click(screen.getByText('tools.metadata.edit'))
    fireEvent.change(await screen.findByLabelText('tools.export.metadata.author'), { target: { value: '测试作者' } })
    fireEvent.click(screen.getByText('tools.metadata.save'))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    expect(postStudioApi).toHaveBeenCalledWith('/project/metadata', { title: '雾城', author: '测试作者', language: 'zh-CN', expected_revision: 'sha256:original' })
    expect(screen.queryByLabelText('tools.export.metadata.author')).toBeNull()
  })

  it('keeps author input when a concurrent change rejects the save', async () => {
    const onSaved = vi.fn()
    render(<ProjectMetadataEditor {...({ fetchStudioApi: async () => ({ project }), postStudioApi: async () => { throw new Error('作品信息已变化') }, onSaved, t } as any)} />)
    fireEvent.click(screen.getByText('tools.metadata.edit'))
    fireEvent.change(await screen.findByLabelText('tools.export.metadata.author'), { target: { value: '保留的输入' } })
    fireEvent.click(screen.getByText('tools.metadata.save'))
    expect((await screen.findByRole('alert')).textContent).toBe('作品信息已变化')
    expect((screen.getByLabelText('tools.export.metadata.author') as HTMLInputElement).value).toBe('保留的输入')
    expect(onSaved).not.toHaveBeenCalled()
  })
})
