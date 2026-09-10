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

import { useEffect, useLayoutEffect, useRef } from 'react'
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import VditorRuntime, { installVditorIcons } from 'dsh-vditor-runtime'
import { loadPackagedEditorGlobal } from './packaged-editor-globals.ts'
import {
  countOccurrences, locateSelectedMarkdown, shouldClearManuscriptSelection, type ManuscriptSelection,
} from './manuscript-selection.ts'
import type { ManuscriptAnnotation } from './manuscript-annotations.ts'
import { parseMarkers } from './manuscript-markers.ts'
import { overlayBands, overlayFill, overlayUnderline, type OverlayBand } from './manuscript-overlay.ts'
import { bindOverlayResync, rangeForNeedle, revealNeedle } from './manuscript-overlay-dom.ts'
import css from './views.module.css'

/** The slice of the bundled Vditor API this editor uses. */
interface VditorInstance {
  getValue: () => string
  getSelection?: () => string
  insertValue?: (value: string, render?: boolean) => void
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
      loadPackagedEditorGlobal('VditorI18n'),
      loadPackagedEditorGlobal('Lute'),
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

export type ManuscriptEditorApi = {
  insertAtCaret: (markdown: string) => void
  revealQuote: (quote: string, start: number) => boolean
}

interface VditorBodyProps {
  /** Initial markdown (the editor is the source of truth afterwards). */
  initial: string
  onChange: (value: string) => void
  onSelectionChange?: (selection: ManuscriptSelection | null) => void
  onReady?: () => void
  onFailed: () => void
  disabled: boolean
  /** The consumer can synchronously retain callbacks delivered during cleanup. */
  flushOnLeave?: boolean
  annotations?: readonly ManuscriptAnnotation[]
  onInsertMarker?: () => void
  onEditorApi?: (api: ManuscriptEditorApi | null) => void
}

function occurrenceBeforeCaret(host: HTMLElement, selected: string): number | undefined {
  const native = window.getSelection()
  if (native === null || native.rangeCount === 0 || selected === '') return undefined
  const range = native.getRangeAt(0)
  if (!host.contains(range.startContainer)) return undefined
  const prefix = document.createRange()
  prefix.selectNodeContents(host)
  prefix.setEnd(range.startContainer, range.startOffset)
  return countOccurrences(prefix.toString(), selected)
}

function paintOverlay(host: HTMLElement, overlay: HTMLElement, bands: readonly OverlayBand[], dark: boolean): void {
  overlay.replaceChildren()
  const ir = host.querySelector('.vditor-ir') ?? host
  const frame = overlay.getBoundingClientRect()
  for (const band of bands) {
    const range = rangeForNeedle(ir, band.needle, band.occurrence)
    if (range === null) continue
    const fill = overlayFill(band.kind, dark ? 'dark' : 'light', band.color)
    for (const rect of Array.from(range.getClientRects())) {
      const mark = document.createElement('span')
      mark.className = css.overlayMark ?? 'ow-overlay-mark'
      mark.dataset.kind = band.kind
      mark.title = band.title
      mark.setAttribute('aria-hidden', 'true')
      mark.style.position = 'absolute'
      mark.style.left = `${rect.left - frame.left}px`
      mark.style.top = `${rect.top - frame.top}px`
      mark.style.width = `${rect.width}px`
      mark.style.height = `${rect.height}px`
      mark.style.background = fill
      if (band.kind === 'note') mark.style.boxShadow = `inset 0 -3px 0 ${overlayUnderline(dark ? 'dark' : 'light', band.color)}`
      mark.style.pointerEvents = 'none'
      overlay.append(mark)
    }
  }
}

/** One Vditor IR instance bound to the shell theme; destroyed on unmount. */
export function VditorBody({
  initial, onChange, onSelectionChange, onReady = () => {}, onFailed, disabled, flushOnLeave = false,
  annotations = [], onInsertMarker, onEditorApi,
}: VditorBodyProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<VditorInstance | null>(null)
  const annotationsRef = useRef(annotations)
  annotationsRef.current = annotations
  const onInsertMarkerRef = useRef(onInsertMarker)
  onInsertMarkerRef.current = onInsertMarker
  const onEditorApiRef = useRef(onEditorApi)
  onEditorApiRef.current = onEditorApi
  // onChange identity changes every keystroke upstream; keep the latest in a
  // ref so the Vditor `input` closure stays stable for the instance lifetime.
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  const onFailedRef = useRef(onFailed)
  onFailedRef.current = onFailed
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady
  const onSelectionChangeRef = useRef(onSelectionChange)
  onSelectionChangeRef.current = onSelectionChange
  const flushRef = useRef<(() => void) | null>(null)

  // Read live markdown before React detaches the editor DOM. Vditor's normal
  // input callback is debounced, so navigating immediately after typing can
  // otherwise destroy the instance before its final change is delivered.
  useLayoutEffect(() => () => { flushRef.current?.() }, [])

  useEffect(() => {
    let disposed = false
    let observer: MutationObserver | null = null
    let unbindOverlay: (() => void) | null = null
    let emitSelection: (() => void) | null = null
    let lastPointerTarget: EventTarget | null = null
    const rememberPointer = (event: Event) => { lastPointerTarget = event.target }
    document.addEventListener('mousedown', rememberPointer, true)
    const host = hostRef.current
    let inputObserved = false
    let lastValue = initial
    const emitChange = (value: string) => {
      if (disposed || value === lastValue) return
      lastValue = value
      onChangeRef.current(value)
    }
    const rememberInput = () => { inputObserved = true }
    const flush = () => {
      const current = instanceRef.current
      if (!inputObserved || current === null) return
      let value: string
      try { value = current.getValue() } catch { return }
      emitChange(value)
    }
    flushRef.current = flushOnLeave ? flush : null
    host?.addEventListener('input', rememberInput, true)
    // Flush before the next button click so Save and leave guards also see
    // the latest body, without serializing long manuscripts every keystroke.
    if (flushOnLeave) host?.addEventListener('focusout', flush)
    void loadVditor()
      .then((Vditor) => {
        if (disposed || hostRef.current === null) return
        const dark = document.body.hasAttribute('data-ds-dark-theme')
        let refreshOverlay = (_value: string) => { /* assigned after the instance exists */ }
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
            ...(onInsertMarkerRef.current ? [{
              name: 'ow-insert-marker',
              tip: '插入标记',
              tipPosition: 's',
              icon: '<svg viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M3 3h10v2H3zm0 4h7v2H3zm0 4h10v2H3z"/></svg>',
              click: () => onInsertMarkerRef.current?.(),
            }] : []),
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
          input: (value: string) => { inputObserved = true; emitChange(value); refreshOverlay(value) },
        })
        instanceRef.current = instance
        if (disposed) return
        refreshOverlay = (value: string) => {
          const overlay = overlayRef.current
          const editorHost = hostRef.current
          if (overlay === null || editorHost === null) return
          paintOverlay(
            editorHost,
            overlay,
            overlayBands(value, annotationsRef.current, parseMarkers(value)),
            document.body.hasAttribute('data-ds-dark-theme'),
          )
        }
        onEditorApiRef.current?.({
          insertAtCaret: (markdown: string) => {
            const current = instanceRef.current
            if (current === null || typeof current.insertValue !== 'function') return
            current.insertValue(`${markdown}\n`)
            const next = current.getValue()
            emitChange(next)
            refreshOverlay(next)
          },
          revealQuote: (quote: string, start: number) => {
            const editorHost = hostRef.current
            const current = instanceRef.current
            if (editorHost === null || current === null || quote === '') return false
            const value = current.getValue()
            const occurrence = countOccurrences(value.slice(0, Math.max(0, start)), quote)
            const ir = editorHost.querySelector('.vditor-ir') ?? editorHost
            const range = revealNeedle(ir, quote, occurrence)
            if (range === null) return false
            onSelectionChangeRef.current?.(locateSelectedMarkdown(value, quote, occurrence))
            refreshOverlay(value)
            return true
          },
        })
        const editorHost = hostRef.current
        if (editorHost !== null) {
          unbindOverlay = bindOverlayResync(editorHost, () => {
            const current = instanceRef.current
            if (current === null) return
            try { refreshOverlay(current.getValue()) } catch { /* editor not ready */ }
          })
        }
        refreshOverlay(instance.getValue())
        emitSelection = () => {
          const current = instanceRef.current
          const editorHost = hostRef.current
          const notify = onSelectionChangeRef.current
          if (current === null || editorHost === null || notify === undefined) return
          const native = window.getSelection()
          const insideEditor = native !== null && native.rangeCount > 0 && editorHost.contains(native.anchorNode)
          if (!insideEditor && !shouldClearManuscriptSelection({
            selectionInsideEditor: false,
            preserveNode: lastPointerTarget ?? document.activeElement,
          })) {
            return
          }
          if (!insideEditor) {
            notify(null)
            return
          }
          const selected = (typeof current.getSelection === 'function' ? current.getSelection() : native?.toString()) ?? ''
          const value = current.getValue()
          notify(locateSelectedMarkdown(value, selected, occurrenceBeforeCaret(editorHost, selected)))
        }
        hostRef.current.addEventListener('mouseup', emitSelection)
        hostRef.current.addEventListener('keyup', emitSelection)
        document.addEventListener('selectionchange', emitSelection)
        observer = new MutationObserver(() => {
          const current = instanceRef.current
          if (current !== null) applyTheme(current, document.body.hasAttribute('data-ds-dark-theme'))
        })
        observer.observe(document.body, { attributes: true, attributeFilter: ['data-ds-dark-theme'] })
      })
      .catch(() => { if (!disposed) onFailedRef.current() })
    return () => {
      if (flushOnLeave) flush()
      disposed = true
      flushRef.current = null
      host?.removeEventListener('input', rememberInput, true)
      host?.removeEventListener('focusout', flush)
      observer?.disconnect()
      unbindOverlay?.()
      document.removeEventListener('mousedown', rememberPointer, true)
      if (emitSelection !== null) {
        host?.removeEventListener('mouseup', emitSelection)
        host?.removeEventListener('keyup', emitSelection)
        document.removeEventListener('selectionchange', emitSelection)
      }
      // Vditor builds asynchronously; destroying before `after` may throw.
      try {
        instanceRef.current?.destroy()
      } catch {
        // Half-built instance: nothing committed, safe to drop.
      }
      instanceRef.current = null
      onEditorApiRef.current?.(null)
    }
    // initial seeds the editor once; later external value changes do not reset it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const host = hostRef.current
    const overlay = overlayRef.current
    const instance = instanceRef.current
    if (host === null || overlay === null || instance === null) return
    try {
      paintOverlay(host, overlay, overlayBands(instance.getValue(), annotations, parseMarkers(instance.getValue())), document.body.hasAttribute('data-ds-dark-theme'))
    } catch { /* editor not ready */ }
  }, [annotations])

  return (
    <div className={css.vditorFrame} aria-disabled={disabled}>
      <div className={css.vditorHost} ref={hostRef} />
      <div className={css.vditorOverlay} ref={overlayRef} aria-hidden="true" />
    </div>
  )
}

/** Loading line shown while the Vditor script is in flight. */
export function VditorLoading({ t }: { t: TFunc }) {
  return <div className={css.detailNotice}>{t('assets.edit.liveLoading')}</div>
}
