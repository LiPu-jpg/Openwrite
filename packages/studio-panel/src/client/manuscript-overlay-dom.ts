/** Map overlay needles onto live IR text nodes. Display-only; never writes into markdown. */

import { nthIndexOf } from './manuscript-selection.ts'

type TextPoint = { node: Text; offset: number }

function textNodes(root: ParentNode): Text[] {
  const nodes: Text[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node !== null) {
    nodes.push(node as Text)
    node = walker.nextNode()
  }
  return nodes
}

function pointInText(nodes: readonly Text[], index: number): TextPoint | null {
  let remaining = index
  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i]!
    const length = node.nodeValue?.length ?? 0
    if (remaining < length || (remaining === length && i === nodes.length - 1)) {
      return { node, offset: remaining }
    }
    remaining -= length
  }
  return null
}

/** nth occurrence of needle across adjacent text nodes, including Vditor IR splits. */
export function rangeForNeedle(root: ParentNode, needle: string, occurrence: number): Range | null {
  if (needle === '' || occurrence < 0 || !Number.isInteger(occurrence)) return null
  const nodes = textNodes(root)
  const haystack = nodes.map(node => node.nodeValue ?? '').join('')
  const start = nthIndexOf(haystack, needle, occurrence)
  if (start < 0) return null
  const from = pointInText(nodes, start)
  const to = pointInText(nodes, start + needle.length)
  if (from === null || to === null) return null
  const range = document.createRange()
  range.setStart(from.node, from.offset)
  range.setEnd(to.node, to.offset)
  return range
}

/** Repaint when the IR scroller moves or the frame size changes. */
export function bindOverlayResync(host: HTMLElement, refresh: () => void): () => void {
  const onScroll = () => refresh()
  host.addEventListener('scroll', onScroll, true)
  const ir = host.querySelector('.vditor-ir')
  ir?.addEventListener('scroll', onScroll)
  window.addEventListener('resize', onScroll)
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => refresh()) : null
  observer?.observe(host)
  if (ir instanceof Element) observer?.observe(ir)
  return () => {
    host.removeEventListener('scroll', onScroll, true)
    ir?.removeEventListener('scroll', onScroll)
    window.removeEventListener('resize', onScroll)
    observer?.disconnect()
  }
}

/** Select the quoted span in the live IR and bring it into view. */
export function revealNeedle(root: ParentNode, needle: string, occurrence: number): Range | null {
  const range = rangeForNeedle(root, needle, occurrence)
  if (range === null) return null
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
  const target = range.startContainer instanceof Element
    ? range.startContainer
    : range.startContainer.parentElement
  if (typeof target?.scrollIntoView === 'function') target.scrollIntoView({ block: 'nearest' })
  return range
}
