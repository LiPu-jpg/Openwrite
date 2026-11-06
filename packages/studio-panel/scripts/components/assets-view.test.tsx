import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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

function emptyApi() {
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/assets') return { data: { assets: [] } }
    if (path === '/workspace') return { data: {} }
    return { data: {} }
  })
  const postStudioApi = vi.fn(async () => ({ data: {} }))
  return { fetchStudioApi, postStudioApi, t: (key: string) => key }
}

describe('AssetsView empty main pane', () => {
  // Vitest stubs CSS modules to empty objects, so the dedicated empty-state
  // styling cannot be asserted from the DOM. Pin it in the source instead:
  // reusing the generic `.notice` is what made the pane look blank.
  it('does not style the empty pane with the generic notice', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/client/AssetsView.tsx'), 'utf-8')
    const branch = source.slice(source.indexOf("if (selected === null) {"), source.indexOf("if (selected.startsWith('doc:'))"))
    expect(branch).toContain('css.mainEmpty')
    expect(branch).not.toContain('css.notice')
  })

  it('explains the empty pane instead of one grey line', async () => {
    // The old state was a single `.notice` line at the top of a ~700px pane,
    // which reads as a rendering failure rather than an empty section.
    const api = emptyApi()
    render(<AssetsView {...(api as never)} />)

    expect(await screen.findByText('assets.emptyTitle')).toBeTruthy()
    expect(screen.getByText('assets.emptyHint')).toBeTruthy()
    expect(screen.queryByText('assets.selectHint')).toBeNull()
  })

  it('offers the create action for cardable segments', async () => {
    const api = emptyApi()
    render(<AssetsView {...(api as never)} />)

    const create = await screen.findByRole('button', { name: 'assets.create.open' })
    expect((create as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(create)
    // NewAssetForm is mocked to null, so only assert nothing was posted.
    await act(async () => { await Promise.resolve() })
    expect(api.postStudioApi).not.toHaveBeenCalled()
  })

  it('points at the agent tools for read-only segments', async () => {
    const api = emptyApi()
    render(<AssetsView {...(api as never)} />)
    await screen.findByText('assets.emptyTitle')

    fireEvent.click(screen.getByRole('button', { name: /references/i }))
    expect(await screen.findByText('assets.emptyAgent')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'assets.create.open' })).toBeNull()
  })
})
