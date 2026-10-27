// Exercise the exact accepted package's Vditor, standalone wrapper and Core
// mapper, plus the native panel mapper. No novel or user configuration is opened.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { createRequire, stripTypeScriptTypes } from 'node:module'
import { resolve, sep } from 'node:path'

const { chromium } = createRequire(new URL('../package.json', import.meta.url))('@playwright/test')
const { unzipSync } = createRequire(new URL('../../../package.json', import.meta.url))('fflate')
const importSource = source => import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))

export async function checkEditorSelections(packageRoot) {
  const manifest = JSON.parse(await readFile(resolve(packageRoot, 'release/runtime-manifest.json'), 'utf8'))
  const wheel = unzipSync(await readFile(resolve(packageRoot, 'release', manifest.wheel.file)))
  const code = name => Buffer.from(wheel['tools/studio_assets/js/' + name]).toString('utf8')
  const core = await importSource(code('selection-coordinates.js'))
  const native = await importSource(stripTypeScriptTypes(await readFile(new URL('../src/client/selection-coordinates.ts', import.meta.url), 'utf8')))
  const assets = resolve(packageRoot, 'packages/studio-panel/vendor/vditor')
  const html = '<!doctype html><div id="editor"></div><script src="/vendor/vditor/dist/js/i18n/zh_CN.js"></script>' +
    '<script id="vditorLuteScript" src="/vendor/vditor/dist/js/lute/lute.min.js"></script>' +
    '<script id="vditorIconScript" src="/vendor/vditor/dist/js/icons/ant.js"></script><script src="/vendor/vditor/dist/index.min.js"></script>'
  const server = createServer(async (req, res) => {
    try {
      const path = new URL(req.url, 'http://localhost').pathname
      if (path === '/') { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(html); return }
      if (path === '/editor.js') { res.setHeader('Content-Type', 'text/javascript'); res.end(code('markdown-editor.js')); return }
      const file = resolve(assets, '.' + path.replace(/^\/vendor\/vditor/, ''))
      if (!path.startsWith('/vendor/vditor/') || !file.startsWith(assets + sep)) { res.writeHead(404); res.end(); return }
      res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'application/octet-stream')
      res.end(await readFile(file))
    } catch { res.writeHead(500); res.end() }
  })
  await new Promise(done => server.listen(0, '127.0.0.1', done))
  const origin = 'http://127.0.0.1:' + server.address().port
  let browser
  const cases = [
    ['前文。选中文本。尾部。', '选中文本'],
    ['前文。选中文本。尾部。\n', '选中文本'],
    ['# 标题\r\n\r\n前文。选中文本。\r\n', '选中文本'],
    ['# 标题\n前文。选中文本。\n', '选中文本'],
    ['前文。\n\n\n选中文本。\n', '选中文本'],
    ['1. 前文。\n2. 选中文本。\n', '选中文本'],
    ['前文。__选中文本__。\n', '选中文本'],
    ['选中文本\n\n\n# 标题\r\n😀选中文本', '选中文本'],
    ['# 标题\r\n选中\r\n\r\n\r\n正文\r\n', '选中\n\n正文'],
  ]
  try {
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage()
    await page.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort())
    for (const [raw, quote] of cases) {
      await page.goto(origin)
      const { value, serialization } = await page.evaluate(async raw => {
        const { MarkdownEditor } = await import('/editor.js')
        const editor = new MarkdownEditor(document.querySelector('#editor'), { value: raw, toolbar: [], compact: true })
        await Promise.race([editor.ready, new Promise((_, reject) => setTimeout(() => reject(Error('Editor did not initialize')), 5000))])
        return { value: editor.getValue(), serialization: editor.getSerialization() }
      }, raw)
      const start = value.lastIndexOf(quote), end = start + quote.length
      assert.ok(start >= 0, JSON.stringify({ raw, value, quote }))
      assert.equal(serialization.source, raw)
      for (const mapper of [native, core]) {
        const range = mapper.mapEditorRange(raw, value, start, end, serialization)
        assert.ok(range, JSON.stringify({ raw, value, quote }))
        assert.equal(Array.from(raw).slice(range.start, range.end).join(''), range.text)
        assert.equal(mapper.mapSourceRange(raw, value, range.start, range.end, serialization).text, quote)
        assert.equal(mapper.mapEditorRange(raw + '外部改动', value, start, end, serialization), null)
        assert.equal(mapper.mapEditorRange(raw, value + '作者输入', start, end, serialization), null)
      }
    }
    return { passed: true, cases: cases.length, nativeMapper: true, packagedCoreMapper: true, realVditor: true }
  } finally {
    if (browser) await browser.close()
    await new Promise(done => server.close(done))
  }
}
