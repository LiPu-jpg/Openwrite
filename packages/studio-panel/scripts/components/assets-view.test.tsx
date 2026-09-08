import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AssetsView } from '../../src/client/AssetsView.tsx'

vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({ MarkdownText: ({ text }: { text: string }) => <span>{text}</span> }))
vi.mock('../../src/client/AssetEditor.tsx', () => ({
  AssetEditor: ({ source, onFieldSave, onSave }: {
    source: { name: string; body: string; summary: string }
    onFieldSave: (field: string, value: string) => void
    onSave: (data: object, body: string) => void
  }) => <div>
    <p>{`Editing ${source.name}`}</p>
    <p>{source.summary}</p>
    <button onClick={() => onFieldSave('summary', 'New summary')}>Save field</button>
    <button onClick={() => onSave({ summary: 'Full summary' }, source.body)}>Save asset</button>
  </div>,
  NewAssetForm: () => null,
}))

function makeApi() {
  const assets = [{ kind: 'character', id: 'a', name: 'Alice' }, { kind: 'character', id: 'b', name: 'Bob' }]
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/assets') return { data: { assets } }
    if (path === '/workspace') return {}
    const id = path.endsWith('/a') ? 'a' : 'b'
    return { data: { revision: `revision-${id}`, name: id === 'a' ? 'Alice' : 'Bob', data: { summary: id }, body_markdown: '' } }
  })
  const postStudioApi = vi.fn(async () => ({ asset: { revision: 'revision-a-saved' } }))
  return { fetchStudioApi, postStudioApi, t: (key: string) => key }
}

describe('AssetsView per-asset revision locks', () => {
  it('loads successfully under StrictMode effect cleanup and replay', async () => {
    const api = makeApi()
    render(<StrictMode><AssetsView {...(api as never)} /></StrictMode>)
    expect(await screen.findByRole('button', { name: 'Alice' })).toBeTruthy()
  })

  it('uses the selected cached asset revision and chains only that asset’s autosaves', async () => {
    const api = makeApi()
    render(<AssetsView {...(api as never)} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Alice' }))
    await screen.findByText('Editing Alice')
    fireEvent.click(screen.getByRole('button', { name: 'Bob' }))
    await screen.findByText('Editing Bob')
    fireEvent.click(screen.getByRole('button', { name: 'Alice' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenCalledWith('/assets/update', {
      kind: 'character', id: 'a', revision: 'revision-a', data: { summary: 'New summary' },
    }))
    await act(async () => { await Promise.resolve() })
    fireEvent.click(screen.getByRole('button', { name: 'Bob' }))
    fireEvent.click(screen.getByRole('button', { name: 'Alice' }))
    expect(screen.getByText('New summary')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Save asset' }))
    await waitFor(() => expect(api.postStudioApi).toHaveBeenLastCalledWith('/assets/update', {
      kind: 'character', id: 'a', revision: 'revision-a-saved', data: { summary: 'Full summary' }, body_markdown: '',
    }))
  })
})
