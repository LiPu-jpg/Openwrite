import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const root = resolve(process.cwd(), '../..')
const require = createRequire(join(root, 'package.json'))
const { unzipSync } = require('fflate')
const ts = createRequire(join(root, 'packages/openwrite-bridge/package.json'))('typescript')
const manifest = JSON.parse(readFileSync(join(root, 'release/runtime-manifest.json'), 'utf8'))
const wheel = unzipSync(readFileSync(join(root, 'release', manifest.wheel.file)))
const source = (name: string): string => Buffer.from(wheel['tools/studio_assets/js/' + name]).toString('utf8')
const load = (text: string, modules: Record<string, unknown> = {}): Record<string, any> => {
  const result: Record<string, any> = {}
  const code = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  new Function('require', 'exports', code)((name: string) => {
    if (!(name in modules)) throw new Error('Unexpected dependency ' + name)
    return modules[name]
  }, result)
  return result
}

describe('the actual standalone editor shipped inside the Core wheel', () => {
  it.each([
    ['multiline CRLF', '前言\r\n选中\r\n正文\r\n尾部', '选中\n正文'],
    ['duplicate after emoji and mixed EOL', '选中文本\r\n😀\n选中文本\r\n尾部', '选中文本'],
  ])('submits exact raw selection bytes for %s', async (_name, raw, quote) => {
    const view = raw.replace(/\r\n?/g, '\n')
    const start = view.lastIndexOf(quote), end = start + quote.length
    const elements = new Map<string, HTMLElement>()
    const $ = (selector: string): any => {
      if (!elements.has(selector)) {
        const node = document.createElement(selector === '#revision-original-text' ? 'textarea' : 'button')
        Object.assign(node, { showModal: vi.fn(), close: vi.fn() })
        elements.set(selector, node)
      }
      return elements.get(selector)
    }
    const enqueueTask = vi.fn(async (_kind: string, _payload: unknown) => ({}))
    const state = { document: { path: 'data/manuscript/arc_001/ch_001.md', content: raw, revision: 'current' }, dirty: false }
    const modules: Record<string, unknown> = {
      '/js/core.js': { $, state, showToast: vi.fn(), api: vi.fn(), formatNumber: String },
      '/js/tasks.js': { enqueueTask },
      '/js/markdown-editor.js': { getPrimaryMarkdownEditor: () => ({ getValue: () => view, selection: () => ({ start, end }) }) },
    }
    if (wheel['tools/studio_assets/js/selection-coordinates.js']) {
      modules['/js/selection-coordinates.js'] = load(source('selection-coordinates.js'))
    }
    const ui = load(source('revisions.js'), modules)
    ui['bindRevisionUI']()
    $('#revision-selection').click()
    $('#revision-request-form').dispatchEvent(new Event('submit', { cancelable: true }))
    expect(enqueueTask).toHaveBeenCalledOnce()
    const payload = enqueueTask.mock.calls[0]![1] as unknown as Record<string, unknown>
    expect(Array.from(raw).slice(Number(payload['start']), Number(payload['end'])).join('')).toBe(payload['original_text'])
    expect(String(payload['original_text']).replace(/\r\n?/g, '\n')).toBe(quote)
    if (quote.includes('\n')) {
      expect(payload['original_text']).toContain('\r\n')
      expect($('#revision-original-text').value).not.toContain('\r')
    }
  })
})
