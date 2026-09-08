import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DiscardDraftDialog } from '../../src/client/DiscardDraftDialog.tsx'

const t = (key: string) => key

describe('discard draft dialog', () => {
  it('names and describes the modal, starts on keep, and traps focus in both directions', () => {
    render(<><button>Outside</button><DiscardDraftDialog t={t} onKeep={vi.fn()} onDiscard={vi.fn()} /></>)
    const dialog = screen.getByRole('alertdialog', { name: 'creation.status.dirty' })
    const keep = screen.getByRole('button', { name: 'models.unsavedKeep' })
    const discard = screen.getByRole('button', { name: 'models.unsavedDiscard' })
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(document.getElementById(dialog.getAttribute('aria-describedby') ?? '')?.textContent).toBe('creation.discardConfirm')
    expect(document.activeElement).toBe(keep)
    fireEvent.keyDown(keep, { key: 'Tab' })
    expect(document.activeElement).toBe(discard)
    fireEvent.keyDown(discard, { key: 'Tab' })
    expect(document.activeElement).toBe(keep)
    fireEvent.keyDown(keep, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(discard)
    fireEvent.keyDown(discard, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(keep)
    screen.getByRole('button', { name: 'Outside' }).focus()
    expect(document.activeElement).toBe(keep)
  })

  it.each(['keep', 'discard', 'escape', 'cancel'] as const)('resolves %s once and restores focus to the initiating button', action => {
    const onKeep = vi.fn()
    const onDiscard = vi.fn()
    function Harness() {
      const [open, setOpen] = useState(false)
      return <><button onClick={() => setOpen(true)}>Switch asset</button>{open && <DiscardDraftDialog t={t}
        onKeep={() => { onKeep(); setOpen(false) }} onDiscard={() => { onDiscard(); setOpen(false) }} />}</>
    }
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Switch asset' })
    trigger.focus()
    fireEvent.click(trigger)
    if (action === 'escape') fireEvent.keyDown(screen.getByRole('button', { name: 'models.unsavedKeep' }), { key: 'Escape' })
    else if (action === 'cancel') fireEvent(screen.getByRole('alertdialog'), new Event('cancel', { cancelable: true }))
    else fireEvent.click(screen.getByRole('button', { name: action === 'keep' ? 'models.unsavedKeep' : 'models.unsavedDiscard' }))
    expect(onKeep).toHaveBeenCalledTimes(action === 'discard' ? 0 : 1)
    expect(onDiscard).toHaveBeenCalledTimes(action === 'discard' ? 1 : 0)
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('does not dispatch repeated decisions while the parent is closing', () => {
    const onKeep = vi.fn()
    const onDiscard = vi.fn()
    render(<DiscardDraftDialog t={t} onKeep={onKeep} onDiscard={onDiscard} />)
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    fireEvent.click(screen.getByRole('button', { name: 'models.unsavedDiscard' }))
    fireEvent.keyDown(screen.getByRole('button', { name: 'models.unsavedKeep' }), { key: 'Escape' })
    expect(onDiscard).toHaveBeenCalledTimes(1)
    expect(onKeep).not.toHaveBeenCalled()
  })
})
