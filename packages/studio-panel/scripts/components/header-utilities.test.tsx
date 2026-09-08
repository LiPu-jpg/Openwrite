import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HeaderUtilities } from '../../src/client/HeaderChrome.tsx'

const invalidate = vi.hoisted(() => vi.fn())
vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: vi.fn(),
  workbenchStore: { invalidate },
}))

describe('header utilities', () => {
  it('shows sync failures and lets the author retry without an unhandled rejection', async () => {
    const postStudioApi = vi.fn()
      .mockRejectedValueOnce(new Error('服务暂时不可用'))
      .mockResolvedValueOnce({ ok: true })
    render(<HeaderUtilities {...({ postStudioApi, t: (key: string) => key } as any)} />)
    const trigger = screen.getByRole('button', { name: 'tools.title' })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('button', { name: 'tools.sync' }))
    expect((await screen.findByRole('alert')).textContent).toBe('服务暂时不可用')
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'tools.sync' }))
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('false'))
    expect(invalidate).toHaveBeenCalledWith('workspace')
    expect(postStudioApi).toHaveBeenCalledTimes(2)
  })

  it('returns keyboard focus to the trigger when Escape closes the popover', () => {
    render(<HeaderUtilities {...({ postStudioApi: vi.fn(), t: (key: string) => key } as any)} />)
    const trigger = screen.getByRole('button', { name: 'tools.title' })
    fireEvent.click(trigger)
    screen.getByRole('button', { name: 'tools.sync' }).focus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger)
  })
})
