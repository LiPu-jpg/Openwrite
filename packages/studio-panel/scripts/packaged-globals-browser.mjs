// Check the real packaged globals under CSP without unsafe-eval or inline scripts.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes, createRequire } from 'node:module'
const require = createRequire(new URL('../package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const helper = stripTypeScriptTypes(await readFile(new URL('../src/client/packaged-editor-globals.ts', import.meta.url), 'utf8'))
const assets = new Map([
  ['/studio-panel/vendor/vditor/dist/js/lute/lute.min.js', new URL('../vendor/vditor/dist/js/lute/lute.min.js', import.meta.url)],
  ['/studio-panel/vendor/vditor/dist/js/i18n/zh_CN.js', new URL('../vendor/vditor/dist/js/i18n/zh_CN.js', import.meta.url)],
])
const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://localhost').pathname
    res.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'")
    if (path === '/') {
      res.setHeader('Content-Type', 'text/html')
      res.end('<!doctype html><script type="module" src="/start.js"></script>')
    } else if (path === '/start.js') {
      res.setHeader('Content-Type', 'text/javascript')
      res.end(`import { loadPackagedEditorGlobal as load } from '/helper.js'; await Promise.all([load('Lute'), load('Lute'), load('VditorI18n')]); document.title = window.Lute.New().Md2HTML('**ready**') .includes('<strong>ready</strong>') && Object.keys(window.VditorI18n).length > 0 ? 'ready' : 'failed';`)
    } else if (path === '/helper.js' || assets.has(path)) {
      res.setHeader('Content-Type', 'text/javascript')
      res.end(path === '/helper.js' ? helper : await readFile(assets.get(path)))
    } else { res.writeHead(404); res.end() }
  } catch { res.writeHead(500); res.end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
let browser
try {
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`http://127.0.0.1:${server.address().port}`)
  await page.waitForFunction(() => document.title === 'ready')
  assert.deepEqual(errors, [])
  console.log('Packaged Lute and language resources initialized under CSP without unsafe-eval')
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => server.close(resolve))
}
