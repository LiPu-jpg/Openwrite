import { describe, expect, it } from 'vitest'
import { parseAnnotation } from '../../src/client/manuscript-annotations.ts'
import { parseMarkers } from '../../src/client/manuscript-markers.ts'
import { overlayBands, overlayFill } from '../../src/client/manuscript-overlay.ts'

describe('display-only overlay bands', () => {
  it('paints notes and markers distinctly and skips detached or resolved notes', () => {
    const content = '密信还在桌上。\n//**林霁[位置]：旧港 -> 灯塔**\n'
    const attached = parseAnnotation({
      annotation_id: 'ann_abcdefghijklmnop', chapter_id: 'ch_001', quote: '密信还在', note: '查来源',
      start_hint: 0, end_hint: 4, current_start: 0, current_end: 4, status: 'open', anchor_state: 'attached',
    })!
    const detached = parseAnnotation({
      annotation_id: 'ann_qrstuvwxyzabcdef', chapter_id: 'ch_001', quote: '不存在的句子', note: '旧批注',
      status: 'open', anchor_state: 'detached',
    })!
    const resolved = parseAnnotation({
      annotation_id: 'ann_resolvedxxxxxxxx', chapter_id: 'ch_001', quote: '密信还在', note: '已处理',
      start_hint: 0, end_hint: 4, status: 'resolved',
    })!
    const bands = overlayBands(content, [attached, detached, resolved], parseMarkers(content))
    expect(bands.some(item => item.kind === 'note' && item.color === 'amber' && item.start === 0)).toBe(true)
    expect(bands.some(item => item.kind === 'state')).toBe(true)
    expect(bands.some(item => item.title === '旧批注' || item.title === '已处理')).toBe(false)
    expect(overlayFill('note', 'light', 'amber')).not.toBe(overlayFill('state', 'light'))
    expect(overlayFill('note', 'dark', 'sky')).not.toBe(overlayFill('relation', 'dark'))
  })
})
