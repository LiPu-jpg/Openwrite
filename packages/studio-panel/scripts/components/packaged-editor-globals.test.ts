import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadPackagedEditorGlobal } from '../../src/client/packaged-editor-globals.ts'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.head.querySelectorAll('script[data-openwrite-global]').forEach(script => script.remove())
})

describe('packaged editor scripts', () => {
  it('shares concurrent loads and waits for the global to initialize', async () => {
    const first = loadPackagedEditorGlobal('Lute')
    expect(loadPackagedEditorGlobal('Lute')).toBe(first)
    const scripts = document.head.querySelectorAll<HTMLScriptElement>('script[data-openwrite-global="Lute"]')
    expect(scripts).toHaveLength(1)
    expect(scripts[0].getAttribute('src')).toBe('/studio-panel/vendor/vditor/dist/js/lute/lute.min.js')
    vi.stubGlobal('Lute', {})
    scripts[0].dispatchEvent(new Event('load'))
    await first
    await loadPackagedEditorGlobal('Lute')
    expect(document.head.querySelectorAll('script[data-openwrite-global="Lute"]')).toHaveLength(1)
  })

  it('removes a failed script and allows a fresh request', async () => {
    const first = loadPackagedEditorGlobal('Lute')
    const failed = expect(first).rejects.toThrow('failed to load Lute')
    document.head.querySelector('script[data-openwrite-global="Lute"]')!.dispatchEvent(new Event('error'))
    await failed
    expect(document.head.querySelector('script[data-openwrite-global="Lute"]')).toBeNull()
    const retry = loadPackagedEditorGlobal('Lute')
    vi.stubGlobal('Lute', {})
    document.head.querySelector('script[data-openwrite-global="Lute"]')!.dispatchEvent(new Event('load'))
    await retry
  })

  it('rejects scripts that load without defining the expected global', async () => {
    const failed = expect(loadPackagedEditorGlobal('VditorI18n')).rejects.toThrow('did not initialize')
    document.head.querySelector('script[data-openwrite-global="VditorI18n"]')!.dispatchEvent(new Event('load'))
    await failed
  })

  it('settles a stalled load without leaving an unhandled rejection', async () => {
    vi.useFakeTimers()
    const failed = expect(loadPackagedEditorGlobal('Lute')).rejects.toThrow('timed out')
    await vi.advanceTimersByTimeAsync(20_000)
    await failed
    expect(document.head.querySelector('script[data-openwrite-global="Lute"]')).toBeNull()
  })
})
