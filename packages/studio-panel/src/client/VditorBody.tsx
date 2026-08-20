/**
 * Vditor live (IR) body editor, loaded at runtime from the Studio server
 * origin — the exact engine and options OpenWrite Studio's manuscript editor
 * uses (tools/studio_assets/js/markdown-editor.js), NOT bundled: the script
 * and CSS arrive via injected <script>/<link> tags, so the purity gate's
 * external list stays react / react-dom / ui-primitives only.
 *
 * Mirrors Studio's options: mode 'ir', lang zh_CN, cache off, dark theme
 * mapped from the dsh shell's `body[data-ds-dark-theme]` (ui-theme's
 * boot-theme contract) — classic when light, dark when dark, with a
 * MutationObserver following live theme switches. Toolbar is Studio's
 * compact subset plus headings/code/table (card-body scope).
 */

import { useEffect, useRef } from 'react'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import css from './views.module.css'

/** The slice of the Vditor API this editor uses (arrives as window.Vditor). */
interface VditorInstance {
  getValue: () => string
  setTheme: (theme: string) => void
  destroy: () => void
}

type VditorCtor = new (host: HTMLElement, options: Record<string, unknown>) => VditorInstance

type TFunc = PropsLocale<'studio-panel'>['t']

/** Cached loader promise — one script injection per page, shared by all editors. */
let loading: Promise<VditorCtor> | null = null

/**
 * Inject Vditor's CSS + script from the Studio origin and resolve with the
 * constructor. Rejects (and clears the cache, so a later retry can reload)
 * when the script fails or the global is missing.
 * @param studioUrl - Studio base URL (serves /vendor/vditor/dist/*).
 */
export function loadVditor(studioUrl: string): Promise<VditorCtor> {
  if (loading !== null) return loading
  loading = new Promise<VditorCtor>((resolve, reject) => {
    const win = window as unknown as { Vditor?: VditorCtor }
    if (win.Vditor !== undefined) {
      resolve(win.Vditor)
      return
    }
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = `${studioUrl}/vendor/vditor/dist/index.css`
    document.head.appendChild(link)
    const script = document.createElement('script')
    script.src = `${studioUrl}/vendor/vditor/dist/index.min.js`
    script.onload = () => {
      if (win.Vditor !== undefined) resolve(win.Vditor)
      else {
        loading = null
        reject(new Error('studio-panel: Vditor script loaded but window.Vditor is missing'))
      }
    }
    script.onerror = () => {
      loading = null
      reject(new Error(`studio-panel: failed to load Vditor from ${studioUrl}`))
    }
    document.head.appendChild(script)
  })
  return loading
}

interface VditorBodyProps {
  /** Initial markdown (the editor is the source of truth afterwards). */
  initial: string
  /** Studio origin (CDN root for Vditor assets and content themes). */
  studioUrl: string
  onChange: (value: string) => void
  onFailed: () => void
  disabled: boolean
}

/** One Vditor IR instance bound to the shell theme; destroyed on unmount. */
export function VditorBody({ initial, onChange, studioUrl, onFailed, disabled }: VditorBodyProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<VditorInstance | null>(null)
  // onChange identity changes every keystroke upstream; keep the latest in a
  // ref so the Vditor `input` closure stays stable for the instance lifetime.
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onFailedRef = useRef(onFailed)
  onFailedRef.current = onFailed

  useEffect(() => {
    let disposed = false
    let observer: MutationObserver | null = null
    void loadVditor(studioUrl)
      .then((Vditor) => {
        if (disposed || hostRef.current === null) return
        const dark = document.body.hasAttribute('data-ds-dark-theme')
        const instance = new Vditor(hostRef.current, {
          value: initial,
          cdn: `${studioUrl}/vendor/vditor`,
          lang: 'zh_CN',
          icon: '',
          mode: 'ir',
          theme: dark ? 'dark' : 'classic',
          cache: { enable: false },
          height: 'auto',
          minHeight: 260,
          tab: '    ',
          typewriterMode: false,
          toolbar: [
            'undo', 'redo', '|', 'headings', 'bold', 'italic', 'strike', '|',
            'list', 'ordered-list', 'quote', 'link', 'inline-code', 'code', 'table',
          ],
          toolbarConfig: { pin: false },
          counter: { enable: false },
          resize: { enable: false },
          outline: { enable: false },
          preview: {
            actions: [],
            hljs: { enable: false, lineNumber: false, style: 'github' },
            markdown: { codeBlockPreview: false, mathBlockPreview: false },
            theme: {
              current: dark ? 'dark' : 'light',
              path: `${studioUrl}/vendor/vditor/dist/css/content-theme`,
            },
          },
          input: (value: string) => { onChangeRef.current(value) },
        })
        instanceRef.current = instance
        observer = new MutationObserver(() => {
          instanceRef.current?.setTheme(
            document.body.hasAttribute('data-ds-dark-theme') ? 'dark' : 'classic',
          )
        })
        observer.observe(document.body, { attributes: true, attributeFilter: ['data-ds-dark-theme'] })
      })
      .catch(() => { onFailedRef.current() })
    return () => {
      disposed = true
      observer?.disconnect()
      // Vditor builds asynchronously; destroying before `after` may throw.
      try {
        instanceRef.current?.destroy()
      } catch {
        // Half-built instance: nothing committed, safe to drop.
      }
      instanceRef.current = null
    }
    // initial seeds the editor once; later external value changes do not reset it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studioUrl])

  return <div className={css.vditorHost} ref={hostRef} aria-disabled={disabled} />
}

/** Loading line shown while the Vditor script is in flight. */
export function VditorLoading({ t }: { t: TFunc }) {
  return <div className={css.detailNotice}>{t('assets.edit.liveLoading')}</div>
}
