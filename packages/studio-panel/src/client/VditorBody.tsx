/**
 * Vditor live (IR) body editor. The engine is vendored with this plugin and
 * served by the dsh host at a same-origin route; Studio remains a headless
 * domain backend and never supplies browser assets.
 *
 * Mirrors Studio's options: mode 'ir', lang zh_CN, cache off, dark theme
 * mapped from the dsh shell's `body[data-ds-dark-theme]` (ui-theme's
 * boot-theme contract) — classic when light, dark when dark, with a
 * MutationObserver following live theme switches. Toolbar is Studio's
 * compact subset plus headings/code/table (card-body scope).
 */

import { useEffect, useRef } from 'react'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import VditorRuntime, { installVditorIcons } from 'dsh-vditor-runtime'
import css from './views.module.css'

/** The slice of the bundled Vditor API this editor uses. */
interface VditorInstance {
  getValue: () => string
  setTheme: (theme: string, contentTheme?: string, codeTheme?: string, contentThemePath?: string) => void
  destroy: () => void
}

type VditorCtor = new (host: HTMLElement, options: Record<string, unknown>) => VditorInstance

type TFunc = PropsLocale<'studio-panel'>['t']

/** Cached constructor promise shared by all editor instances. */
let loading: Promise<VditorCtor> | null = null
const VDITOR_BASE = '/studio-panel/vendor/vditor'
const CONTENT_THEME_PATH = `${VDITOR_BASE}/dist/css/content-theme`

function applyTheme(instance: VditorInstance, dark: boolean): void {
  instance.setTheme(dark ? 'dark' : 'classic', dark ? 'dark' : 'light', undefined, CONTENT_THEME_PATH)
}

async function installPackagedGlobal(path: string, globalName: 'Lute' | 'VditorI18n'): Promise<void> {
  const win = window as unknown as Record<string, unknown>
  if (win[globalName] !== undefined) return
  const response = await fetch(path, { headers: { accept: 'text/javascript' } })
  if (!response.ok) {
    throw new Error(`studio-panel: failed to load ${globalName} (${String(response.status)})`)
  }
  const source = await response.text()
  if (win[globalName] !== undefined) return
  new Function(source).call(window)
  if (win[globalName] === undefined) throw new Error(`studio-panel: ${globalName} did not initialize`)
}

/**
 * Attach Vditor's packaged CSS and resolve the constructor bundled into this
 * plugin. Auxiliary language/theme assets continue to use the same-origin
 * vendor route.
 */
export function loadVditor(): Promise<VditorCtor> {
  if (loading !== null) return loading
  loading = (async () => {
    const win = window as unknown as { Vditor?: VditorCtor; VditorI18n?: Record<string, string> }
    const packaged = VditorRuntime as VditorCtor
    if (win.Vditor === undefined) win.Vditor = packaged
    if (document.querySelector(`link[href="${VDITOR_BASE}/dist/index.css"]`) === null) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = `${VDITOR_BASE}/dist/index.css`
      document.head.appendChild(link)
    }
    await Promise.all([
      installPackagedGlobal(`${VDITOR_BASE}/dist/js/i18n/zh_CN.js`, 'VditorI18n'),
      installPackagedGlobal(`${VDITOR_BASE}/dist/js/lute/lute.min.js`, 'Lute'),
    ])
    if (document.getElementById('vditorLuteScript') === null) {
      const marker = document.createElement('script')
      marker.id = 'vditorLuteScript'
      marker.type = 'application/json'
      document.head.appendChild(marker)
    }
    installVditorIcons()
    if (document.getElementById('vditorIconScript') === null) {
      const marker = document.createElement('script')
      marker.id = 'vditorIconScript'
      marker.type = 'application/json'
      document.head.appendChild(marker)
    }
    if (typeof packaged !== 'function') throw new Error('studio-panel: packaged Vditor constructor is missing')
    return packaged
  })()
  const current = loading
  void current.catch(() => {
    if (loading === current) loading = null
  })
  return loading
}

interface VditorBodyProps {
  /** Initial markdown (the editor is the source of truth afterwards). */
  initial: string
  onChange: (value: string) => void
  onReady?: () => void
  onFailed: () => void
  disabled: boolean
}

/** One Vditor IR instance bound to the shell theme; destroyed on unmount. */
export function VditorBody({ initial, onChange, onReady = () => {}, onFailed, disabled }: VditorBodyProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<VditorInstance | null>(null)
  // onChange identity changes every keystroke upstream; keep the latest in a
  // ref so the Vditor `input` closure stays stable for the instance lifetime.
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onFailedRef = useRef(onFailed)
  onFailedRef.current = onFailed
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady

  useEffect(() => {
    let disposed = false
    let observer: MutationObserver | null = null
    void loadVditor()
      .then((Vditor) => {
        if (disposed || hostRef.current === null) return
        const dark = document.body.hasAttribute('data-ds-dark-theme')
        const instance = new Vditor(hostRef.current, {
          value: initial,
          cdn: VDITOR_BASE,
          lang: 'zh_CN',
          i18n: (window as unknown as { VditorI18n?: Record<string, string> }).VditorI18n,
          icon: 'ant',
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
              path: CONTENT_THEME_PATH,
            },
          },
          after: () => { onReadyRef.current() },
          input: (value: string) => { onChangeRef.current(value) },
        })
        instanceRef.current = instance
        observer = new MutationObserver(() => {
          const current = instanceRef.current
          if (current !== null) applyTheme(current, document.body.hasAttribute('data-ds-dark-theme'))
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
  }, [])

  return <div className={css.vditorHost} ref={hostRef} aria-disabled={disabled} />
}

/** Loading line shown while the Vditor script is in flight. */
export function VditorLoading({ t }: { t: TFunc }) {
  return <div className={css.detailNotice}>{t('assets.edit.liveLoading')}</div>
}
