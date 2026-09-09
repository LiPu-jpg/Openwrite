import { describe, expect, it, vi } from 'vitest'
import { bindOverlayResync, rangeForNeedle, revealNeedle } from '../../src/client/manuscript-overlay-dom.ts'

function irRoot(build: (root: HTMLDivElement) => void): HTMLDivElement {
  const root = document.createElement('div')
  root.className = 'vditor-ir'
  build(root)
  document.body.append(root)
  return root
}

describe('IR overlay needle ranges', () => {
  it('still maps a quote that lives in one text node', () => {
    const root = irRoot(node => { node.append('密信还在桌上。') })
    const range = rangeForNeedle(root, '密信还在', 0)
    expect(range?.toString()).toBe('密信还在')
    root.remove()
  })

  it('maps a quote split across formatted IR text nodes', () => {
    const root = irRoot(node => {
      const strong = document.createElement('strong')
      strong.append('密信')
      node.append(strong, document.createTextNode('还在桌上。'))
    })
    const range = rangeForNeedle(root, '密信还在', 0)
    expect(range).not.toBeNull()
    expect(range!.toString()).toBe('密信还在')
    root.remove()
  })

  it('maps a Core marker whose //** wrapper is split from the body', () => {
    const root = irRoot(node => {
      node.append(
        document.createTextNode('//**'),
        document.createTextNode('林霁[位置]：旧港 -> 灯塔'),
        document.createTextNode('**'),
      )
    })
    const range = rangeForNeedle(root, '//**林霁[位置]：旧港 -> 灯塔**', 0)
    expect(range).not.toBeNull()
    expect(range!.toString()).toBe('//**林霁[位置]：旧港 -> 灯塔**')
    root.remove()
  })

  it('selects the nth split quote and scrolls it into view', () => {
    const root = irRoot(node => {
      node.append(
        document.createTextNode('密信'),
        document.createTextNode('还在桌上。密信'),
        document.createTextNode('还在灯塔。'),
      )
    })
    const scrolled: Element[] = []
    const previous = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      writable: true,
      value(this: Element) { scrolled.push(this) },
    })
    const range = revealNeedle(root, '密信还在', 1)
    expect(range).not.toBeNull()
    expect(range!.toString()).toBe('密信还在')
    expect(window.getSelection()?.toString()).toBe('密信还在')
    expect(scrolled.length).toBeGreaterThan(0)
    if (previous === undefined) delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
    else Object.defineProperty(Element.prototype, 'scrollIntoView', previous)
    root.remove()
  })
})

describe('overlay resync', () => {
  it('repaints when the IR scroller or window resizes', () => {
    const host = document.createElement('div')
    const ir = document.createElement('div')
    ir.className = 'vditor-ir'
    host.append(ir)
    document.body.append(host)
    const refresh = vi.fn()
    const stop = bindOverlayResync(host, refresh)
    ir.dispatchEvent(new Event('scroll'))
    expect(refresh.mock.calls.length).toBeGreaterThan(0)
    const afterScroll = refresh.mock.calls.length
    window.dispatchEvent(new Event('resize'))
    expect(refresh.mock.calls.length).toBeGreaterThan(afterScroll)
    const frozen = refresh.mock.calls.length
    stop()
    ir.dispatchEvent(new Event('scroll'))
    window.dispatchEvent(new Event('resize'))
    expect(refresh).toHaveBeenCalledTimes(frozen)
    host.remove()
  })
})
