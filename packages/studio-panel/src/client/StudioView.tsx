/**
 * Studio panel view: one full-height iframe embedding the local OpenWrite
 * Studio server as a conversation view tab (稿件). Pure props component — the
 * Studio base URL arrives through the injected `resolveStudioUrl` callback.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import css from './StudioView.module.css'

/**
 * Injected share of the studio view entry: resolve the Studio base URL from
 * the host-side plugin config (same-origin config route; falls back to the
 * schema default when the route is absent).
 */
export interface StudioViewInjected {
  resolveStudioUrl: () => Promise<string>
}

/** Full studio-view props: conversation-view runtime share & injected share & locale seat. */
export type StudioViewProps =
  ConvViewProps & InjectFace<StudioViewInjected> & PropsLocale<'studio-panel'>

type FrameState = 'loading' | 'ready' | 'error'
type ShellTheme = 'dark' | 'light'

/** The dsh shell marks dark mode with `data-ds-dark-theme` on <body> (ui-theme design-platform.css). */
function currentShellTheme(): ShellTheme {
  return document.body.hasAttribute('data-ds-dark-theme') ? 'dark' : 'light'
}

/**
 * The 稿件 view body. The iframe is deliberately NOT sandboxed: Studio is a
 * trusted first-party local app that needs its own origin's
 * localStorage/cookies, form submits, downloads (manuscript export) and
 * possibly window.open — even `allow-scripts allow-same-origin` would break
 * downloads/popups, and sandboxing a same-machine dev tool buys nothing.
 *
 * Reachability note: Studio sends no CORS headers (checked
 * OpenWrite/tools/studio_http.py), so a cross-origin fetch health-check from
 * the dsh page origin is impossible; the panel instead renders the iframe
 * directly and relies on its load/error events. Cross-origin failure pages
 * still fire `load` in some browsers, so the error panel is best-effort — the
 * "open in new tab" escape hatch is always visible on failure.
 */
export function StudioView({ resolveStudioUrl, t }: StudioViewProps) {
  const [studioUrl, setStudioUrl] = useState<string | null>(null)
  const [frameState, setFrameState] = useState<FrameState>('loading')
  const [reloadKey, setReloadKey] = useState(0)
  const [shellTheme, setShellTheme] = useState<ShellTheme>(currentShellTheme)
  const frameRef = useRef<HTMLIFrameElement | null>(null)

  useEffect(() => {
    let cancelled = false
    void resolveStudioUrl().then((url) => {
      if (!cancelled) setStudioUrl(url)
    })
    return () => { cancelled = true }
  }, [resolveStudioUrl, reloadKey])

  // Follow the shell's light/dark switch without reloading the iframe.
  useEffect(() => {
    const observer = new MutationObserver(() => setShellTheme(currentShellTheme()))
    observer.observe(document.body, { attributes: true, attributeFilter: ['data-ds-dark-theme'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (studioUrl === null || frameState !== 'ready') return
    frameRef.current?.contentWindow?.postMessage(
      { type: 'studio-theme', theme: shellTheme },
      new URL(studioUrl).origin,
    )
  }, [studioUrl, frameState, shellTheme])

  // The initial theme rides the iframe URL (?embed=dsh&theme=); later changes
  // go through postMessage so a theme switch never reloads the editor.
  const frameSrc = useMemo(
    () => (studioUrl === null ? null : `${studioUrl}?embed=dsh&theme=${currentShellTheme()}`),
    [studioUrl],
  )

  const retry = () => {
    setFrameState('loading')
    setReloadKey(key => key + 1)
  }

  if (studioUrl === null || frameSrc === null) {
    return <div className={css.root}><div className={css.status}>{t('resolving')}</div></div>
  }
  if (frameState === 'error') {
    return (
      <div className={css.root}>
        <div className={css.status}>
          <span className={css.errorText}>{t('unreachable')}</span>
          <span className={css.actions}>
            <button type="button" className={css.button} onClick={retry}>{t('retry')}</button>
            <a className={css.button} href={studioUrl} target="_blank" rel="noreferrer">
              {t('openExternal')}
            </a>
          </span>
        </div>
      </div>
    )
  }
  return (
    <div className={css.root}>
      {frameState === 'loading' && <div className={css.status}>{t('loading')}</div>}
      <iframe
        key={reloadKey}
        ref={frameRef}
        className={css.frame}
        src={frameSrc}
        title={t('view.studio')}
        allow="clipboard-read; clipboard-write"
        onLoad={() => { setFrameState('ready') }}
        onError={() => { setFrameState('error') }}
      />
    </div>
  )
}
