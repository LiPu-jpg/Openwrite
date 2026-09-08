import { useId, useLayoutEffect, useRef } from 'react'
import type { StudioPanelKey } from './locales.ts'
import css from './views.module.css'

export interface DiscardDraftDialogProps {
  onKeep: () => void
  onDiscard: () => void
  t: (key: StudioPanelKey) => string
}

/** Mount while a navigation action is waiting for the draft decision. */
export function DiscardDraftDialog({ onKeep, onDiscard, t }: DiscardDraftDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const keepRef = useRef<HTMLButtonElement>(null)
  const discardRef = useRef<HTMLButtonElement>(null)
  const decided = useRef(false)
  const titleId = useId()
  const descriptionId = useId()

  useLayoutEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    // The native modal makes the surrounding workbench inert, including its
    // pointer targets. The fallback also lets DOM-only tests exercise focus.
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    keepRef.current?.focus({ preventScroll: true })
    const containFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !dialog.contains(event.target)) keepRef.current?.focus({ preventScroll: true })
    }
    document.addEventListener('focusin', containFocus)
    return () => {
      document.removeEventListener('focusin', containFocus)
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [])

  const decide = (action: () => void) => {
    if (decided.current) return
    decided.current = true
    action()
  }

  return (
    <dialog ref={dialogRef} className={css.notice} role="alertdialog" aria-modal="true"
      aria-labelledby={titleId} aria-describedby={descriptionId}
      style={{ width: 'min(440px, calc(100vw - 32px))', maxHeight: 'calc(100dvh - 32px)', boxSizing: 'border-box', overflow: 'auto', padding: 24,
        border: '1px solid var(--dsw-alias-border-l2)', borderRadius: 10, background: 'var(--dsw-alias-bg-base)' }}
      onCancel={event => { event.preventDefault(); decide(onKeep) }}
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          decide(onKeep)
        } else if (event.key === 'Tab') {
          event.preventDefault()
          const next = document.activeElement === keepRef.current ? discardRef.current : keepRef.current
          next?.focus()
        }
      }}>
      <strong id={titleId}>{t('creation.status.dirty')}</strong>
      <span id={descriptionId}>{t('creation.discardConfirm')}</span>
      <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 8 }}>
        <button ref={keepRef} type="button" className={css.button} onClick={() => decide(onKeep)}>{t('models.unsavedKeep')}</button>
        <button ref={discardRef} type="button" className={`${css.button} ${css.buttonDanger}`} onClick={() => decide(onDiscard)}>{t('models.unsavedDiscard')}</button>
      </div>
    </dialog>
  )
}
