/**
 * The sidebar launcher: the way *into* a novel.
 *
 * It used to be a settings page too — environment diagnostics, the companion
 * inventory, a pointer to the model editor. Those moved into the host's
 * settings dialog, so this test pins the launcher as a launcher: it opens a
 * work, and it points at the settings dialog for everything else.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LaunchOpenWrite } from '../../src/client/LaunchOpenWrite.tsx'

/** jsdom has no dialog.showModal; the component calls it on open. */
function stubDialog() {
  const proto = window.HTMLDialogElement.prototype as unknown as Record<string, unknown>
  if (typeof proto['showModal'] !== 'function') proto['showModal'] = function showModal() { this['open'] = true }
  if (typeof proto['close'] !== 'function') proto['close'] = function close() { this['open'] = false }
}

function stubRuntime(phase = 'ready') {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/studio-panel/runtime') && init?.method === 'POST') {
      return new Response(JSON.stringify({ phase, message: 'ready' }), { status: 202, headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/studio-panel/runtime')) {
      return new Response(JSON.stringify({ phase, message: 'The writing environment is ready' }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`unexpected fetch ${url}`)
  }))
}

beforeEach(() => { stubDialog() })

describe('LaunchOpenWrite', () => {
  it('opens on the directory field and the way in', async () => {
    stubRuntime()
    const openWorkspace = vi.fn(async () => true)
    render(<LaunchOpenWrite wide openWorkspace={openWorkspace} />)

    fireEvent.click(screen.getByRole('button', { name: '打开 OpenWrite' }))
    await waitFor(() => expect(screen.getByLabelText('作品目录')).toBeTruthy())
    expect(screen.getByText('写作环境已就绪')).toBeTruthy()
    expect(screen.getByRole('button', { name: '选择目录并进入' })).toBeTruthy()
  })

  it('hands the typed path to the workspace opener', async () => {
    stubRuntime()
    const openWorkspace = vi.fn(async () => true)
    render(<LaunchOpenWrite wide openWorkspace={openWorkspace} />)
    fireEvent.click(screen.getByRole('button', { name: '打开 OpenWrite' }))
    const field = await screen.findByLabelText('作品目录')
    fireEvent.change(field, { target: { value: '/novels/demo' } })
    fireEvent.click(screen.getByRole('button', { name: '进入作品' }))
    await waitFor(() => expect(openWorkspace).toHaveBeenCalledWith('/novels/demo'))
  })

  it('no longer carries the settings it moved to the host dialog', async () => {
    stubRuntime()
    const openWorkspace = vi.fn(async () => true)
    render(<LaunchOpenWrite wide openWorkspace={openWorkspace} />)
    fireEvent.click(screen.getByRole('button', { name: '打开 OpenWrite' }))
    await screen.findByLabelText('作品目录')
    // The companion inventory and the environment diagnostics live in the
    // host's settings dialog now.
    expect(screen.queryByText('联动插件')).toBeNull()
    expect(screen.queryByText('诊断与帮助')).toBeNull()
    expect(screen.queryByText(/模型可在/)).toBeNull()
    // The launcher points at the settings dialog instead.
    expect(screen.getByText(/设置 → OpenWrite/)).toBeTruthy()
  })
})
