/**
 * Shared jsdom setup for the component layer: the DAG/graph components read
 * `window.matchMedia` and React Flow expects `ResizeObserver`; jsdom ships
 * neither. Stubs are minimal on purpose — layout fidelity is browser-QA
 * territory, these tests only need the components to mount deterministically.
 */
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })
}

if (typeof globalThis.ResizeObserver !== 'function') {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
}

if (typeof window.requestAnimationFrame !== 'function') {
  window.requestAnimationFrame = (callback: FrameRequestCallback): number => window.setTimeout(() => callback(0), 0)
  window.cancelAnimationFrame = (handle: number): void => window.clearTimeout(handle)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})
