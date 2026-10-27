// Isolated browser fixtures: real Vditor/native wrappers and packaged Core
// browser modules. No novel, model, DSH profile or project registry is opened.
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { resolve, join, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
const require = createRequire(new URL('../package.json', import.meta.url))
const { createServer } = await import(require.resolve('vite'))
const playwright = require('@playwright/test')
const rootRequire = createRequire(new URL('../../../package.json', import.meta.url))
const { unzipSync } = rootRequire('fflate')
const panel = fileURLToPath(new URL('../', import.meta.url))
const checkout = resolve(panel, '../..')
const option = name => process.argv.find(arg => arg.startsWith(`--${name}=`))?.slice(name.length + 3)
const engine = option('browser') ?? 'webkit'
assert.ok(['webkit', 'chromium'].includes(engine))
const coreRoot = option('core')
let wheel, artifactSha256, unpacked, nativeInputs = 'checkout-source'
if (!coreRoot) {
  const pkg = JSON.parse(await readFile(resolve(checkout, 'package.json')))
  const archive = await readFile(resolve(option('artifact') ?? resolve(checkout, `dsh-openwrite-${pkg.version}.tgz`)))
  // Core browser modules come from the exact archive accepted by CI.
  artifactSha256 = createHash('sha256').update(archive).digest('hex')
  unpacked = await mkdtemp(join(tmpdir(), 'openwrite-mobile-assets-'))
  const { x: extract } = rootRequire('tar')
  await extract({ file: resolve(option('artifact') ?? resolve(checkout, `dsh-openwrite-${pkg.version}.tgz`)), cwd: unpacked, strict: true })
  const installed = join(unpacked, 'package')
  const manifest = JSON.parse(await readFile(resolve(installed, 'release/runtime-manifest.json')))
  wheel = unzipSync(await readFile(resolve(installed, 'release', manifest.wheel.file)))
  const client = await readFile(join(installed, 'packages/studio-panel/lib/client.js'), 'utf8')
  const sourceMap = JSON.parse(await readFile(join(installed, 'packages/studio-panel/lib/client.js.map'), 'utf8'))
  for (const file of ['VditorBody.tsx', 'browser-download.ts', 'manuscript-selection.ts', 'selection-coordinates.ts', 'manuscript-overlay.ts', 'manuscript-overlay-dom.ts']) {
    const index = sourceMap.sources.indexOf(`../src/client/${file}`)
    assert.ok(index >= 0, `Packaged source map is missing ${file}`)
    assert.equal(sourceMap.sourcesContent[index], await readFile(join(panel, 'src/client', file), 'utf8'), `Fixture source differs from packaged ${file}`)
  }
  const { transform } = require('lightningcss')
  for (const file of ['Workbench.module.css', 'views.module.css']) {
    const filename = join(panel, 'src/client', file)
    const { code } = transform({filename, code: await readFile(filename), cssModules: {pattern: '[hash]_[local]'}, minify: true})
    assert.ok(client.includes(JSON.stringify(code.toString())), `Fixture style differs from packaged ${file}`)
  }
  for (const file of ['dist/index.min.js', 'dist/index.css', 'dist/js/lute/lute.min.js', 'dist/js/i18n/zh_CN.js', 'dist/js/icons/ant.js']) {
    assert.deepEqual(await readFile(join(panel, 'vendor/vditor', file)), await readFile(join(installed, 'packages/studio-panel/vendor/vditor', file)), `Vendored fixture differs: ${file}`)
  }
  nativeInputs = 'checkout-source-matched-to-package'
}
const core = async path => coreRoot ? readFile(resolve(coreRoot, path)) : Buffer.from(wheel[`tools/studio_assets/${path}`])
const vendor = resolve(panel, 'vendor/vditor')
const mime = path => path.endsWith('.css') ? 'text/css' : path.endsWith('.svg') ? 'image/svg+xml' : path.endsWith('.html') ? 'text/html; charset=utf-8' : 'text/javascript; charset=utf-8'
const globals = '<script id="vditorLuteScript" src="/vendor/vditor/dist/js/lute/lute.min.js"></script><script src="/vendor/vditor/dist/js/i18n/zh_CN.js"></script><script src="/vendor/vditor/dist/js/icons/ant.js"></script><script src="/vendor/vditor/dist/index.min.js"></script>'
const coreHarness = `
loadWorkspace = async () => {};
renderInspectorContext = () => {};
export const mobileCoreTest = {
  state,
  editor: () => getPrimaryMarkdownEditor(),
  save: saveDocument,
  retain: retainDocumentDraft,
  dirty: markEditorDirty,
  recovery: renderDocumentRecovery,
  restore: restoreDocumentRecovery,
  showRecovery: () => renderDocumentRecovery(documentDrafts.load(documentOwner.identity, documentOwner.version)),
  settle: () => { clearTimeout(state.autoSaveTimer); state.autoSaveTimer = null; },
  async prepare(path, content, version = 'v1') {
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
    state.workspace = {project: {root: '/mobile-fixture'}, snapshot: {novel_id: 'mobile'}, model: {configured: false}};
    const editor = await initializePrimaryMarkdownEditor({onInput: () => markEditorDirty()});
    await editor.setValue(content);
    const doc = {path, content, version, title: path};
    state.document = doc; state.dirty = false;
    documentOwner = {document: doc, version, savedContent: editor.getValue(), identity: {projectRoot: '/mobile-fixture', novelId: 'mobile', path}};
    renderDocumentRecovery();
    document.querySelector('#dashboard-view').hidden = true;
    document.querySelector('#editor-view').hidden = false;
    document.querySelector('#app').setAttribute('aria-busy', 'false');
  },
  draft(path, version) { return documentDrafts.load({projectRoot: '/mobile-fixture', novelId: 'mobile', path}, version); }
};
window.mobileCoreTest = mobileCoreTest;
`
const server = await createServer({
  root: panel, configFile: false,
  server: { host: '127.0.0.1', port: 0 },
  resolve: { alias: { 'dsh-vditor-runtime': resolve(panel, 'scripts/mobile/runtime.ts') } },
  plugins: [{ name: 'mobile-fixtures', configureServer(vite) {
    vite.middlewares.use(async (req, res, next) => {
      const path = new URL(req.url, 'http://localhost').pathname
      try {
        let body
        if (path === '/mobile.html') body = await vite.transformIndexHtml(path, '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;width:100%;}*{box-sizing:border-box}</style></head><body>'+globals+'<div id="root"></div><script type="module" src="/scripts/mobile/harness.tsx"></script></body></html>')
        else if (path === '/core-test.html') body = (await core('index.html')).toString().replace(/<script type="module" src="\/app\.js[^>]*><\/script>/, '<script type="module" src="/core-test-boot.js"></script>')
        else if (path === '/core-test-boot.js') body = "import '/core-application.js'; document.title='core-ready';"
        else if (path === '/core-application.js') body = (await core('js/application.js')).toString().replace(/\nstart\(\);\s*$/, '\n') + coreHarness
        else if (path.startsWith('/js/') || path === '/styles.css') body = await core(path.slice(1))
        else if (path.startsWith('/brand/')) body = await core(path.endsWith('logo-dark.svg') ? 'logo-dark.svg' : 'logo.svg')
        else if (path.startsWith('/vendor/vditor/') || path.startsWith('/studio-panel/vendor/vditor/')) {
          const relative = path.replace(/^\/(?:studio-panel\/)?vendor\/vditor\//, '')
          const file = resolve(vendor, relative)
          if (!file.startsWith(vendor + sep)) throw Error('Invalid vendor path')
          body = await readFile(file)
        } else { next(); return }
        res.setHeader('Content-Type', mime(path))
        res.end(body)
      } catch (error) { res.statusCode = 500; res.end(String(error)) }
    })
  } }],
})
await server.listen()
const origin = `http://127.0.0.1:${server.httpServer.address().port}`
let browser
const checks = []
const authorText = '手机中文输入与 emoji 😀，最后一行。'
async function typePending(page, text) {
  await page.evaluate(text => {
    const editable = document.querySelector('.vditor-ir [contenteditable="true"]')
    const block = editable.querySelector('p') ?? editable
    block.textContent = text
    const range = document.createRange(); range.selectNodeContents(block); range.collapse(false)
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    editable.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}))
    editable.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertCompositionText', data: text, isComposing: true}))
    editable.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true, data: text}))
  }, text)
}
try {
  browser = await playwright[engine].launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  context.setDefaultTimeout(15_000)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort())
  await page.goto(origin + '/mobile.html')
  await page.waitForFunction(() => window.mobileTest?.ready || window.mobileTest?.failed)
  assert.equal(await page.evaluate(() => window.mobileTest.failed), undefined)
  await page.locator('.vditor-ir [contenteditable="true"]').waitFor()
  await page.evaluate(() => { window.mobileHoldInput = true })
  await typePending(page, authorText)
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')))
  assert.ok((await page.evaluate(() => window.mobileTest.changes.at(-1))).includes(authorText))
  checks.push('native-pending-ime-pagehide')
  await typePending(page, '切到后台前的另一段输入 😀')
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  assert.ok((await page.evaluate(() => window.mobileTest.changes.at(-1))).includes('切到后台前的另一段输入 😀'))
  checks.push('native-hidden-draft-flush')
  await page.evaluate(() => {
    const block = document.querySelector('.vditor-ir p')
    const range = document.createRange(); range.selectNodeContents(block)
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  const selected = await page.evaluate(() => window.mobileTest.selection?.text)
  assert.ok(selected)
  await page.getByTestId('selection-action').dispatchEvent('pointerdown', { pointerType: 'touch' })
  await page.evaluate(() => { window.getSelection().collapseToEnd(); document.dispatchEvent(new Event('selectionchange')) })
  assert.equal(await page.evaluate(() => window.mobileTest.selection?.text), selected)
  checks.push('touch-selection-preserved')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载测试正文' }).tap()
  const download = await downloadPromise
  assert.equal(download.suggestedFilename(), '手机正文.md')
  assert.equal(await download.failure(), null)
  assert.equal(await readFile(await download.path(), 'utf8'), '手机导出正文')
  checks.push('blob-download')
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 480 })
    const metrics = await page.evaluate(() => {
      const root = document.querySelector('[data-testid="workbench"]')
      const editor = document.querySelector('.vditor-ir')
      return { overflow: document.documentElement.scrollWidth > window.innerWidth,
        height: root.getBoundingClientRect().height, editorWidth: editor.getBoundingClientRect().width,
        inputSize: getComputedStyle(document.querySelector('input')).fontSize,
        closedDrawer: getComputedStyle(document.querySelector('[data-testid="inspector"]')).visibility }
    })
    assert.equal(metrics.overflow, false, JSON.stringify({width, metrics}))
    assert.ok(metrics.height >= 200 && metrics.editorWidth >= 120, JSON.stringify({width, metrics}))
    assert.equal(metrics.closedDrawer, 'hidden')
    if (width <= 600) {
      assert.ok(parseFloat(metrics.inputSize) >= 16)
      assert.ok(metrics.editorWidth >= width * 0.8, JSON.stringify({width, metrics}))
    }
  }
  checks.push('small-viewports-and-hidden-drawers')
  await page.setViewportSize({width: 390, height: 844})
  await page.getByRole('button', { name: '章节目录' }).tap()
  await page.getByRole('textbox', { name: '搜索章节' }).waitFor({state: 'visible'})
  await page.getByRole('button', { name: '关闭目录' }).tap()
  assert.deepEqual(errors, [])
  await context.close()

  const coreContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  coreContext.setDefaultTimeout(15_000)
  const corePage = await coreContext.newPage()
  const coreErrors = []
  corePage.on('pageerror', error => coreErrors.push(error.message))
  await corePage.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort())
  await corePage.goto(origin + '/core-test.html')
  await corePage.waitForFunction(() => window.mobileCoreTest)
  await corePage.evaluate(() => window.mobileCoreTest.prepare('src/story/mobile-a.md', '原始正文。\n'))
  await typePending(corePage, authorText)
  await corePage.evaluate(() => window.dispatchEvent(new Event('pagehide')))
  assert.ok((await corePage.evaluate(() => window.mobileCoreTest.draft('src/story/mobile-a.md')?.content)).includes(authorText))
  checks.push('core-pagehide-recovery')
  let releaseSave
  const delayed = new Promise(resolve => { releaseSave = resolve })
  let savedRequest
  await corePage.route('**/api/document', async route => {
    const body = route.request().postDataJSON(); savedRequest = body
    await delayed
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({...body, version: 'v2'})})
  })
  await corePage.evaluate(() => { void window.mobileCoreTest.save() })
  const deadline = Date.now() + 5000
  while (!savedRequest && Date.now() < deadline) await new Promise(done => setTimeout(done, 20))
  assert.ok(savedRequest, 'Core save did not start')
  await corePage.evaluate(() => window.mobileCoreTest.prepare('src/story/mobile-b.md', '另一文档正文。\n'))
  releaseSave()
  await corePage.waitForFunction(() => !window.mobileCoreTest.state.saving)
  assert.equal(await corePage.evaluate(() => window.mobileCoreTest.state.document.path), 'src/story/mobile-b.md')
  assert.equal(savedRequest.path, 'src/story/mobile-a.md')
  checks.push('late-save-keeps-document-owner')
  // Reopening the original document shows a retained draft. A changed server
  // version may only be downloaded, never restored over newer server content.
  await corePage.evaluate(() => window.mobileCoreTest.prepare('src/story/recovery.md', '服务器正文。\n'))
  await typePending(corePage, '未保存的恢复正文 😀')
  await corePage.evaluate(() => { window.dispatchEvent(new Event('pagehide')); window.mobileCoreTest.settle() })
  await corePage.reload()
  await corePage.waitForFunction(() => window.mobileCoreTest)
  await corePage.evaluate(async () => { await window.mobileCoreTest.prepare('src/story/recovery.md', '更新后的服务器正文。\n', 'v2'); window.mobileCoreTest.showRecovery() })
  await corePage.locator('#editor-recovery').waitFor({state: 'visible'})
  assert.equal(await corePage.locator('#editor-recovery-restore').isDisabled(), true)
  await corePage.evaluate(() => window.mobileCoreTest.restore())
  assert.ok((await corePage.evaluate(() => window.mobileCoreTest.editor().getValue())).includes('更新后的服务器正文'))
  await typePending(corePage, '服务器新版上的后续修改')
  await corePage.evaluate(() => { window.dispatchEvent(new Event('pagehide')); window.mobileCoreTest.settle() })
  assert.equal(await corePage.evaluate(() => window.mobileCoreTest.draft('src/story/recovery.md', 'v1')?.content.includes('未保存的恢复正文')), true)
  checks.push('recovery-reload-and-version-conflict')
  await corePage.evaluate(async () => { await window.mobileCoreTest.prepare('src/story/recovery.md', '服务器正文。\n', 'v1'); window.mobileCoreTest.showRecovery(); await window.mobileCoreTest.restore(); window.mobileCoreTest.settle() })
  assert.equal(await corePage.evaluate(() => window.mobileCoreTest.state.dirty), true)
  assert.ok((await corePage.evaluate(() => window.mobileCoreTest.editor().getValue())).includes('未保存的恢复正文'))
  checks.push('explicit-recovery-restores-editor')
  await corePage.unroute('**/api/document')
  let manualSave
  await corePage.route('**/api/document', async route => {
    manualSave = {body: route.request().postDataJSON(), root: route.request().headers()['x-openwrite-workspace-root']}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({...manualSave.body, version: 'saved'}) })
  })
  await corePage.evaluate(() => window.mobileCoreTest.prepare('src/story/manual.md', '原文。\n'))
  await typePending(corePage, '立即手动保存的中文 😀')
  await corePage.evaluate(() => window.mobileCoreTest.save())
  assert.ok(manualSave.body.content.includes('立即手动保存的中文 😀'))
  assert.equal(decodeURIComponent(manualSave.root), '/mobile-fixture')
  assert.equal(await corePage.evaluate(() => window.mobileCoreTest.state.dirty), false)
  checks.push('manual-save-flush-and-workspace-binding')
  await corePage.evaluate(() => window.mobileCoreTest.prepare('src/story/concurrent.md', '原文。\n'))
  await typePending(corePage, '请求提交时的正文')
  let submitted
  let releaseConcurrent
  const pendingSave = new Promise(resolve => { releaseConcurrent = resolve })
  await corePage.unroute('**/api/document')
  await corePage.route('**/api/document', async route => {
    submitted = route.request().postDataJSON()
    await pendingSave
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({...submitted, version: 'new-version'})})
  })
  await corePage.evaluate(() => { void window.mobileCoreTest.save() })
  const saveDeadline = Date.now() + 5000
  while (!submitted && Date.now() < saveDeadline) await new Promise(done => setTimeout(done, 20))
  assert.ok(submitted)
  await typePending(corePage, '保存请求途中继续输入的新正文 😀')
  await corePage.evaluate(() => { window.dispatchEvent(new Event('pagehide')); window.mobileCoreTest.settle() })
  releaseConcurrent()
  await corePage.waitForFunction(() => !window.mobileCoreTest.state.saving)
  assert.equal(await corePage.evaluate(() => window.mobileCoreTest.state.dirty), true)
  assert.ok((await corePage.evaluate(() => window.mobileCoreTest.draft('src/story/concurrent.md', 'new-version')?.content)).includes('继续输入的新正文'))
  await corePage.evaluate(() => window.mobileCoreTest.save())
  assert.equal(await corePage.evaluate(() => window.mobileCoreTest.draft('src/story/concurrent.md')), null)
  checks.push('newer-input-during-save-retained')
  for (const width of [320, 390, 768]) {
    await corePage.setViewportSize({width, height: 480})
    assert.equal(await corePage.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, `Core overflow at ${width}`)
  }
  checks.push('core-small-viewports')
  assert.deepEqual(coreErrors, [])
  await coreContext.close()
  const report = {status: 'passed', engine, artifactSha256, nativeInputs, coreInputs: coreRoot ? 'checkout-source' : 'packaged-wheel', isolatedComponents: true, realVditor: true, realDevice: false, checks}
  await writeFile(option('report') ?? `mobile-browser-report-${engine}.json`, JSON.stringify(report, null, 2) + '\n')
  console.log(JSON.stringify(report))
} finally {
  if (browser) await browser.close()
  await server.close()
  if (unpacked) await rm(unpacked, { recursive: true, force: true })
}
