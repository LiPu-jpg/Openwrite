import { describe, expect, it } from 'vitest'
import {
  formatRelationMarker, formatStateMarker, parseMarkers, readableWritingUnits, stripValidMarkers,
} from '../../src/client/manuscript-markers.ts'
import {
  annotationColor, annotateRequest, parseAnnotation, revalidateAnnotationRange, unsavedAnnotationGuard,
} from '../../src/client/manuscript-annotations.ts'
import { characterMatches, resolveCharacterChoice } from '../../src/client/manuscript-mentions.ts'

describe('inline Core markers', () => {
  it('formats the two Core grammars and rejects empty/newline/reserved fields', () => {
    expect(formatStateMarker({ name: '林霁', field: '位置', oldState: '旧港', newState: '灯塔' })).toEqual({
      ok: true, markdown: '//**林霁[位置]：旧港 -> 灯塔**',
    })
    expect(formatRelationMarker({ source: '林霁', target: '周舟', description: '共同调查灯塔' })).toEqual({
      ok: true, markdown: '//**林霁~>周舟:共同调查灯塔**',
    })
    expect(formatStateMarker({ name: '', oldState: 'a', newState: 'b' })).toMatchObject({ ok: false, error: 'empty' })
    expect(formatRelationMarker({ source: 'A', target: 'B\nC', description: 'x' })).toMatchObject({ ok: false, error: 'newline' })
    expect(formatStateMarker({ name: '林*霁', oldState: 'a', newState: 'b' })).toMatchObject({ ok: false, error: 'reserved' })
  })

  it('parses valid markers, keeps invalid/unclosed/fenced text, and excludes metadata from readable units', () => {
    const body = [
      '她走进灯塔。',
      '//**林霁[位置]：旧港 -> 灯塔**',
      '//**林霁~>周舟:共同调查灯塔**',
      '```',
      '//**不是标记：代码 -> 示例**',
      '```',
      '//**坏掉的',
      '普通对话「你好」。',
      '**粗体** 不是标记。',
    ].join('\n')
    const spans = parseMarkers(body)
    expect(spans.filter(item => item.parsed?.kind === 'state')).toHaveLength(1)
    expect(spans.filter(item => item.parsed?.kind === 'relation')).toHaveLength(1)
    expect(spans.some(item => item.kind === 'invalid' && item.text.includes('坏掉的'))).toBe(true)
    expect(spans.some(item => item.text.includes('代码'))).toBe(false)
    const stripped = stripValidMarkers(body)
    expect(stripped).toContain('她走进灯塔。')
    expect(stripped).toContain('普通对话')
    expect(stripped).toContain('//**不是标记：代码 -> 示例**')
    expect(stripped).toContain('//**坏掉的')
    expect(stripped).not.toContain('共同调查灯塔')
    expect(readableWritingUnits(body)).toBe(readableWritingUnits(stripped))
    expect(readableWritingUnits(body)).toBeLessThan(body.replace(/\s+/g, '').length)
  })
})

describe('selection annotations', () => {
  it('defaults missing color and refuses unsaved or empty annotate requests', () => {
    expect(annotationColor(undefined)).toBe('amber')
    expect(annotationColor({ not: 'a color' })).toBe('amber')
    expect(parseAnnotation({
      annotation_id: 'ann_abcdefghijklmnop', chapter_id: 'ch_001', quote: '密信', note: '查来源',
    })?.color).toBe('amber')
    expect(unsavedAnnotationGuard(true)).toBe('save-first')
    expect(annotateRequest({
      chapterId: 'ch_001', revision: '', selection: { start: 0, end: 2, text: '密信' }, note: '查', color: 'sky',
    })).toEqual({ ok: false, reason: 'save-first' })
    expect(annotateRequest({
      chapterId: 'ch_001', revision: 'sha256:abc', selection: { start: 0, end: 2, text: '密信' }, note: '查来源', color: 'sky',
    }).ok).toBe(true)
  })

  it('requires an explicit character id when names or aliases collide', () => {
    const assets = [
      { kind: 'character', id: 'c1', name: '林霁', summary: '灯塔看守', aliases: ['霁哥'] },
      { kind: 'character', id: 'c2', name: '林霁', summary: '同名路人', aliases: [] },
    ]
    expect(characterMatches(assets, '林霁')).toHaveLength(2)
    expect(characterMatches(assets, '霁哥')[0]?.id).toBe('c1')
    expect(characterMatches(assets, '周舟')).toEqual([])
    expect(resolveCharacterChoice(assets, '', '林霁')).toBeNull()
    expect(resolveCharacterChoice(assets, 'c2', '林霁')?.id).toBe('c2')
    expect(revalidateAnnotationRange('密信还在桌上', { start: 0, end: 4, text: '密信还在' })).toEqual({
      start: 0, end: 4, text: '密信还在',
    })
    expect(revalidateAnnotationRange('已经改掉了', { start: 0, end: 4, text: '密信还在' })).toBeNull()
  })
})
