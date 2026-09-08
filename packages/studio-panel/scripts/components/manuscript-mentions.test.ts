import { describe, expect, it } from 'vitest'
import {
  findManuscriptMentions, parseMentionAssets,
} from '../../src/client/manuscript-mentions.ts'

const character = {
  kind: 'character', id: 'linzhou', name: '林舟', summary: '钟楼守夜人', aliases: ['小舟'],
}
const location = {
  kind: 'world', id: 'bell-tower', name: '钟楼', summary: '旧城制高点', aliases: [],
}

describe('manuscript mention matcher', () => {
  it('parses character and location assets and ignores other kinds', () => {
    const assets = parseMentionAssets({
      data: {
        assets: [
          character,
          location,
          { kind: 'progression', id: 'arc-one', name: '第一卷', aliases: [] },
          { kind: 'character', id: '', name: '无名' },
        ],
      },
    })
    expect(assets.map(item => item.id)).toEqual(['linzhou', 'bell-tower'])
  })

  it('highlights name and alias hits and skips unregistered strings', () => {
    const text = '林舟走进钟楼。小舟看见密信。'
    const spans = findManuscriptMentions(text, [character, location])
    expect(spans.map(span => span.text)).toEqual(['林舟', '钟楼', '小舟'])
    expect(spans.map(span => span.id)).toEqual(['linzhou', 'bell-tower', 'linzhou'])
    expect(text.includes('密信')).toBe(true)
    expect(spans.some(span => span.text === '密信')).toBe(false)
  })

  it('lets a longer alias win over a shorter overlapping name', () => {
    const short = { kind: 'character', id: 'lin', name: '林', summary: '', aliases: [] as string[] }
    const long = { kind: 'character', id: 'linzhou', name: '林舟', summary: '', aliases: ['林舟兄'] }
    const spans = findManuscriptMentions('林舟兄站在钟楼。', [short, long, location])
    expect(spans.map(span => ({ text: span.text, id: span.id }))).toEqual([
      { text: '林舟兄', id: 'linzhou' },
      { text: '钟楼', id: 'bell-tower' },
    ])
  })
})
