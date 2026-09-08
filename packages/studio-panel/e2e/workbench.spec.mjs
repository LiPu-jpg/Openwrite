/**
 * Studio-panel E2E: secret non-echo on the model view, workbench shell and
 * mobile (390×844) interaction assertions.
 *
 * Skip gates:
 *   1. `beforeAll` probes dsh web (3080) and Studio (4567); when either is
 *      unreachable the whole file skips with the probe reason — these specs
 *      only produce evidence against a live dev stack (`npm run dev`).
 *   2. The conversation views (Create/Library/Tasks) only mount inside an
 *      started session; blank New Session pages do not mount the workbenches.
 *      When the local dsh state has no started session, the affected
 *      tests skip with an explicit reason instead of failing.
 *
 * Selectors accept both locale dictionaries (zh labels from locales.ts and
 * their en counterparts). Credential hygiene assertions never read real
 * profile secrets: they assert that password inputs stay empty and that no
 * credential-shaped marker reaches the DOM.
 */
import { expect, test } from '@playwright/test'
import { homedir } from 'node:os'
import { resolve } from 'node:path'
import { probeServices } from './helpers.mjs'

const VIEW_TABS = [/^(创作|Create)$/, /^(资料|Library)$/, /^(任务|Tasks)$/]
const TARGET_PROJECT = resolve(process.env.OPENWRITE_PROJECT || `${homedir()}/my_novel`)
let targetWorkspaceId = ''
let targetWorkspaceTitle = ''
let targetSessionId = ''

async function listItems(method) {
  const response = await fetch(`http://127.0.0.1:3080/api/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      type: 'client-request',
      rpcId: `rpc_e2e_${String(Date.now())}`,
      method,
      payload: {},
    }),
  })
  expect(response.ok, `${method} must be reachable`).toBe(true)
  const payload = await response.json()
  expect(payload?.result?.ok, `${method} must succeed`).toBe(true)
  return payload?.result?.value?.items ?? []
}

test.beforeAll(async () => {
  const status = await probeServices()
  if (!status.ok) console.log(`[studio-panel e2e] skipping: ${status.reason}`)
  test.skip(!status.ok, `E2E skipped: ${status.reason}`)
  const [workspaces, sessions] = await Promise.all([listItems('workspace.list'), listItems('session.list')])
  const workspace = workspaces.find(item => resolve(item.path) === TARGET_PROJECT)
  if (workspace) {
    targetWorkspaceId = workspace.workspaceId
    targetWorkspaceTitle = workspace.title
    // A Workspace can retain a reusable blank session before its real one.
    // Select an actual conversation so the host mounts conversation.view.
    targetSessionId = sessions.find(session => session.blank === false && workspace.sessionIds?.includes(session.sessionId))?.sessionId ?? ''
  }
  test.skip(targetWorkspaceId === '', `E2E skipped: no dsh Workspace maps to ${TARGET_PROJECT}`)
  test.skip(targetSessionId === '', `E2E skipped: no started dsh session belongs to ${TARGET_PROJECT}`)
})

test.beforeEach(async ({ page }) => {
  // Apply before any application script in every test, including shell-only
  // checks that do not call openWorkbenchSession.
  await page.addInitScript(({ sessionId }) => {
    localStorage.setItem('dsh.sessions.current', JSON.stringify({ sessionId }))
  }, { sessionId: targetSessionId })
  await page.route('**/studio-panel/api/**', async route => {
    expect(route.request().headers()['x-dsh-workspace-id']).toBe(targetWorkspaceId)
    await route.continue()
  })
})

async function documentOverflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
}

/** The workbench tabs only render inside a conversation session; open one. */
async function openWorkbenchSession(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  // Mobile collapses the sidebar; open it to reach the session tree.
  const openSidebar = page.getByRole('button', { name: 'Open sidebar' })
  if ((page.viewportSize()?.width ?? 1000) <= 900) {
    await expect(openSidebar).toBeVisible({ timeout: 10_000 })
    await openSidebar.click()
  }
  const workspace = page.getByRole('treeitem', { name: targetWorkspaceTitle, exact: true })
  await expect(workspace).toHaveCount(1, { timeout: 10_000 })
  await expect(workspace).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('[role="treeitem"][aria-selected="true"]')).toHaveCount(1)
  await expect(page.getByRole('tab', { name: VIEW_TABS[0] })).toBeVisible({ timeout: 10_000 })
  // Session chrome appears before the Studio-backed Workspace snapshot. Wait
  // for the actual chapter projection so callers never interact with the
  // transient "Not open" shell while a prior synchronous request is draining.
  await expect(page.getByRole('banner').getByText(/ch_\d+\s*·/).first()).toHaveText(/ch_\d+\s*·/, { timeout: 60_000 })
}

async function deleteRecoveryDraft(page, key) {
  if (page.isClosed()) return
  await page.evaluate(async ({ key }) => {
    await new Promise((resolvePromise, rejectPromise) => {
      const request = indexedDB.open('dsh-novel-manuscript-drafts', 1)
      request.onupgradeneeded = () => request.result.createObjectStore('drafts', { keyPath: 'key' })
      request.onerror = () => rejectPromise(request.error)
      request.onsuccess = () => {
        const transaction = request.result.transaction('drafts', 'readwrite')
        transaction.objectStore('drafts').delete(key)
        transaction.oncomplete = () => { request.result.close(); resolvePromise() }
        transaction.onerror = () => rejectPromise(transaction.error)
      }
    })
  }, { key })
}

async function replaceEditorText(page, value) {
  const editable = page.locator('.vditor-ir [contenteditable="true"]')
  await expect(editable).toHaveCount(1)
  await editable.fill(value)
}

async function readDocument(page, path) {
  const response = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, {
    headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
  })
  expect(response.ok()).toBe(true)
  return response.json()
}

test('workbench shell loads with zero horizontal overflow', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('body')).not.toBeEmpty()

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
})

test('model view renders API key fields empty and echo-free', async ({ page }) => {
  await openWorkbenchSession(page)
  // Tasks view → 模型/Models segment (OperationsView → ModelView).
  await page.getByRole('tab', { name: /^(任务|Tasks)$/ }).click()
  await page.getByRole('button', { name: /^(模型|Models)$/ }).first().click()

  // M2b workbench: grouped editor sections are the entry points.
  await expect(page.getByText(/^(基本信息|Basic info)$/).first()).toBeVisible()
  await expect(page.getByText(/^(API Key)$/).first()).toBeVisible()

  const passwords = page.locator('input[type=password]')
  await expect(passwords.first()).toBeVisible()
  for (const input of await passwords.all()) {
    await expect(input).toHaveValue('')
  }
  // No key-shaped value may reach the DOM after CRUD list rendering.
  await expect(page.locator('body')).not.toContainText(['sk-or', 'v1-'].join('-'))
  await expect(page.locator('body')).not.toContainText('api_key')

  // Creating a profile must not pre-fill an API key either; the id box is
  // editable only in create mode. Nothing is saved here.
  await page.getByRole('button', { name: /^(新增档案|New profile)$/ }).click()
  const idInput = page.getByLabel(/^(档案 ID|Profile ID)/)
  await expect(idInput).toBeEnabled()
  for (const input of await page.locator('input[type=password]').all()) {
    await expect(input).toHaveValue('')
  }

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
})

test('key workbench controls remain reachable with zero overflow', async ({ page }) => {
  await openWorkbenchSession(page)
  for (const tab of VIEW_TABS) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible()
  }

  // Switch through the workbenches; the document must never grow wider than
  // the 390px viewport.
  await page.getByRole('tab', { name: /^(资料|Library)$/ }).click()
  await page.getByRole('tab', { name: /^(任务|Tasks)$/ }).click()

  // The model workbench must stay operable on mobile too: stacked layout,
  // grouped sections reachable, API key boxes empty, zero overflow.
  await page.getByRole('button', { name: /^(模型|Models)$/ }).first().click()
  await expect(page.getByText(/^(基本信息|Basic info)$/).first()).toBeVisible()
  await expect(page.locator('input[type=password]').first()).toBeVisible()

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
})

test('real asset editor preserves input across an immediate tab exit and explicitly discards it without saving', async ({ page }) => {
  test.setTimeout(180_000)
  const headers = { 'X-Dsh-Workspace-Id': targetWorkspaceId }
  const assetPath = '/studio-panel/api/assets/character/lin_ji'
  const beforeResponse = await page.request.get(assetPath, { headers })
  expect(beforeResponse.ok(), 'the isolated QA lin_ji fixture must exist').toBe(true)
  const before = (await beforeResponse.json()).data
  expect(before.id).toBe('lin_ji')
  const documentBefore = await readDocument(page, before.path)
  const attemptedWrites = []
  await page.route('**/studio-panel/api/**', async route => {
    const request = route.request()
    expect(request.headers()['x-dsh-workspace-id']).toBe(targetWorkspaceId)
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) {
      attemptedWrites.push({ method: request.method(), url: request.url() })
      await route.abort('blockedbyclient')
      return
    }
    await route.fallback()
  })

  await openWorkbenchSession(page)
  const libraryTab = page.getByRole('tab', { name: /^(资料|Library)$/ })
  const tasksTab = page.getByRole('tab', { name: /^(任务|Tasks)$/ })
  await libraryTab.click()
  await page.getByRole('button', { name: /^林霁(?:\s|$)/ }).click()
  const editable = page.locator('.vditor-ir [contenteditable="true"]')
  await expect(editable).toHaveCount(1)
  await expect(editable).toContainText(before.body_markdown.trim().split('\n').at(-1))
  const originalEditorText = await editable.innerText()
  await expect(tasksTab).toBeVisible()
  const tabHandle = await tasksTab.elementHandle()
  expect(tabHandle).not.toBeNull()
  const marker = `E2E 即时离开资料草稿 ${test.info().project.name}`

  // Native editing and the tab click share one renderer task. This exercises
  // the actual vendored Vditor, while guaranteeing its 200 ms input callback
  // cannot run between typing and unmount. No React/editor APIs are mocked.
  const exit = await editable.evaluate(async (editor, { marker, tab }) => {
    editor.focus()
    const selection = window.getSelection()
    const range = document.createRange()
    range.selectNodeContents(editor)
    selection.removeAllRanges()
    selection.addRange(range)
    let inputEvents = 0
    editor.addEventListener('input', () => { inputEvents += 1 }, { once: true })
    const started = performance.now()
    const inserted = document.execCommand('insertText', false, marker)
    const inputVisible = editor.textContent.includes(marker)
    tab.click()
    // React's discrete click commit finishes before timers, at the latest
    // in this microtask; record that unmount really preceded the debounce.
    await Promise.resolve()
    return { inserted, inputEvents, inputVisible, detached: !editor.isConnected, elapsedMs: performance.now() - started }
  }, { marker, tab: tabHandle })
  await tabHandle.dispose()
  expect(exit).toMatchObject({ inserted: true, inputEvents: 1, inputVisible: true, detached: true })
  expect(exit.elapsedMs, 'the editor must unmount before its 200 ms input debounce').toBeLessThan(200)
  await expect(tasksTab).toHaveAttribute('aria-selected', 'true')

  await libraryTab.click()
  await expect(page.getByText(/^(已恢复未保存的资料草稿|Unsaved asset draft restored)$/)).toBeVisible()
  await expect(editable).toHaveText(marker, { useInnerText: true })
  const cancel = page.getByRole('button', { name: /^(取消|Cancel)$/ })
  await expect(cancel).toHaveCount(1)
  await cancel.click()
  const dialog = page.getByRole('alertdialog', { name: /^(未保存|Unsaved)$/ })
  await expect(dialog).toBeVisible()
  const keep = dialog.getByRole('button', { name: /^(继续编辑|Keep editing)$/ })
  await expect(keep).toBeFocused()
  await keep.click()
  await expect(dialog).toHaveCount(0)
  await expect(editable).toHaveText(marker, { useInnerText: true })

  await cancel.click()
  await dialog.getByRole('button', { name: /^(放弃修改|Discard changes)$/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(editable).toHaveText(originalEditorText, { useInnerText: true })
  await expect(editable).not.toContainText(marker)
  // A discarded editor's teardown must not recreate the recovery in memory.
  await tasksTab.click()
  await libraryTab.click()
  await page.getByRole('button', { name: /^林霁(?:\s|$)/ }).click()
  await expect(editable).toHaveText(originalEditorText, { useInnerText: true })
  await expect(page.getByText(/^(已恢复未保存的资料草稿|Unsaved asset draft restored)$/)).toHaveCount(0)
  expect(attemptedWrites, 'editing, recovering and discarding must never save the asset').toEqual([])

  const afterResponse = await page.request.get(assetPath, { headers })
  expect(afterResponse.ok()).toBe(true)
  const after = (await afterResponse.json()).data
  expect(after.revision).toBe(before.revision)
  expect(after.raw_text).toBe(before.raw_text)
  expect(after.data).toEqual(before.data)
  expect(after.body_markdown).toBe(before.body_markdown)
  const documentAfter = await readDocument(page, before.path)
  expect(documentAfter.revision).toBe(documentBefore.revision)
  expect(documentAfter.content).toBe(documentBefore.content)
})

test('live benchmark options provide chapter choices, inclusive outline ranges and authoritative DAGs without writes', async ({ page }) => {
  const headers = { 'X-Dsh-Workspace-Id': targetWorkspaceId }
  const workspaceResponse = await page.request.get('/studio-panel/api/workspace', { headers })
  expect(workspaceResponse.ok()).toBe(true)
  const workspace = await workspaceResponse.json()
  const documentPaths = ['src/outline.md', ...(workspace.documents?.chapters ?? []).slice(-1).map(chapter => chapter.path)]
  const beforeDocuments = await Promise.all(documentPaths.map(path => readDocument(page, path)))
  const attemptedWrites = []
  await page.route('**/studio-panel/api/**', async route => {
    const request = route.request()
    expect(request.headers()['x-dsh-workspace-id']).toBe(targetWorkspaceId)
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) {
      attemptedWrites.push({ method: request.method(), url: request.url() })
      await route.abort('blockedbyclient')
      return
    }
    await route.fallback()
  })

  await openWorkbenchSession(page)
  await page.getByRole('tab', { name: /^(任务|Tasks)$/ }).click()
  const optionsResponsePromise = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/studio-panel/api/benchmarks/options' && response.request().method() === 'GET')
  await page.getByRole('button', { name: /^(模型测试|Model test)$/ }).first().click()
  const optionsResponse = await optionsResponsePromise
  expect(optionsResponse.ok()).toBe(true)
  const optionsEnvelope = await optionsResponse.json()
  expect(optionsEnvelope.ok).toBe(true)
  const options = optionsEnvelope.data
  const layoutSnapshot = async () => page.evaluate(() => {
    const form = document.querySelector('input[name="benchmark-task"]')?.closest('form')
    const frame = form?.closest('[style*="grid-template-columns"]')
    const size = element => ({ tag: element.tagName, role: element.getAttribute('role'), className: element.className,
      width: Math.round(element.getBoundingClientRect().width), left: Math.round(element.getBoundingClientRect().left) })
    return {
      viewport: window.innerWidth,
      gridTemplateColumns: frame ? getComputedStyle(frame).gridTemplateColumns : null,
      columns: frame ? [...frame.children].map(size) : [],
      form: form ? size(form) : null,
      taskChoices: form ? [...form.querySelectorAll('input[name="benchmark-task"]')].map(input => size(input.closest('label'))) : [],
      fields: form ? [...form.querySelectorAll('select, input[type="number"]')].filter(input => input.getClientRects().length).map(input => {
        const label = input.closest('label')?.cloneNode(true)
        label?.querySelectorAll('select, input').forEach(control => control.remove())
        return { ...size(input), label: label?.textContent?.trim() }
      }) : [],
    }
  })
  if (page.viewportSize().width <= 900) {
    await page.screenshot({ path: '/tmp/dsh-novel-benchmark-sidebar-open-mobile-20260909.png', fullPage: true })
    console.log('[benchmark-layout:mobile:sidebar-open]', JSON.stringify(await layoutSnapshot()))
    // The session helper temporarily opens the host's navigation. Restore its
    // normal compact rail before judging the mobile workbench's usable width.
    const collapseSidebar = page.getByRole('button', { name: /^(Collapse sidebar|收起侧边栏)$/ })
    await expect(collapseSidebar).toBeVisible()
    await collapseSidebar.click()
    await expect(page.getByRole('button', { name: /^(Open sidebar|打开侧边栏)$/ })).toBeVisible()
    await expect.poll(async () => (await layoutSnapshot()).form.width).toBeGreaterThanOrEqual(page.viewportSize().width - 100)
  }
  expect(options.chapters.length).toBeGreaterThan(0)
  expect(options.next_chapter_id).toMatch(/^ch_\d+$/)
  const chapterChoice = page.getByRole('combobox', { name: /^(章节|Chapter)$/ })
  await expect(chapterChoice).toHaveValue('next')
  const assertReadiness = async taskType => {
    const readiness = options.tasks.find(task => task.task_type === taskType)?.readiness
    if (readiness?.ok === false) {
      await expect(page.getByTestId('benchmark-readiness')).toHaveText(readiness.message || readiness.code)
      await expect(page.getByRole('button', { name: /^(开始测试|Run benchmark)$/ })).toBeDisabled()
    }
  }
  await assertReadiness('chapter')
  await expect(chapterChoice.locator('option')).toHaveCount(options.chapters.length + 2)
  const renderedChoices = await chapterChoice.locator('option').evaluateAll(elements => elements.map(option => ({
    value: option.value, text: option.textContent, disabled: option.disabled,
  })))
  expect(renderedChoices.find(option => option.value === 'next').text).toContain(options.next_chapter_id)
  for (const chapter of options.chapters) {
    const option = renderedChoices.find(item => item.value === chapter.chapter_id)
    expect(option, `chapter option ${chapter.chapter_id}`).toBeDefined()
    expect(option.text).toContain(chapter.title)
    expect(option.disabled).toBe(chapter.availability === 'unavailable')
  }
  const availableLater = options.chapters.find(chapter => chapter.availability !== 'unavailable' && chapter.chapter_id !== options.next_chapter_id)
  if (availableLater) {
    await chapterChoice.selectOption(availableLater.chapter_id)
    await expect(chapterChoice).toHaveValue(availableLater.chapter_id)
  }

  const dag = page.getByRole('region', { name: /^(智能 DAG 配置|Automatic DAG configuration)$/ })
  const assertPipeline = async pipeline => {
    expect(pipeline?.nodes.length).toBeGreaterThan(0)
    await expect(dag).toBeVisible()
    const stages = dag.locator('details')
    if (!(await stages.evaluate(element => element.open))) await stages.locator('summary').click()
    await expect(dag.locator('ol > li > strong')).toHaveText(pipeline.nodes.map(node => node.label))
    for (const [index, node] of pipeline.nodes.entries()) {
      const row = dag.locator('ol > li').nth(index)
      for (const dependency of node.depends_on) {
        const parent = pipeline.nodes.find(item => item.id === dependency)
        await expect(row).toContainText(parent?.label ?? dependency)
      }
    }
    for (const domain of pipeline.review_domains) await expect(dag).toContainText(domain.label)
    const { scrollWidth, clientWidth } = await documentOverflow(page)
    expect(scrollWidth, `benchmark overflow at ${page.viewportSize().width}px`).toBeLessThanOrEqual(clientWidth)
  }
  const chapterPipeline = options.tasks.find(task => task.task_type === 'chapter').pipelines.find(pipeline => pipeline.execution_mode === 'framework')
  await assertPipeline(chapterPipeline)

  await page.getByRole('radio', { name: /^(大纲设计|Outline planning)/ }).check()
  const origin = page.getByRole('combobox', { name: /^(设计起点|Planning origin)$/ })
  const start = page.getByRole('spinbutton', { name: /^(起始章号（包含本章）|Starting chapter \(inclusive\))$/ })
  const count = page.getByRole('spinbutton', { name: /^(设计章数|Chapters to plan)$/ })
  const controls = start.locator('xpath=ancestor::form')
  const range = (first, last) => new RegExp(`^(?:第 ${first} 至 ${last} 章|Chapters ${first} to ${last})$`)
  await expect(origin).toHaveValue('continue')
  await expect(start).toHaveValue(String(options.default_outline_start_chapter))
  await expect(start).toBeDisabled()
  await expect(count).toHaveValue('3')
  await expect(controls.getByText(range(options.default_outline_start_chapter, options.default_outline_start_chapter + 2))).toBeVisible()
  await expect(controls.getByRole('spinbutton', { name: /^(目标字数|Target words)$/ })).toHaveCount(0)
  await expect(controls.getByRole('combobox', { name: /^(执行模式|Execution mode)$/ })).toHaveCount(0)
  await expect(controls.locator('option[value="creative"]')).toHaveCount(0)
  const outlinePipeline = options.tasks.find(task => task.task_type === 'outline').pipelines.find(pipeline => pipeline.execution_mode === 'framework')
  await assertPipeline(outlinePipeline)
  await assertReadiness('outline')
  await page.getByRole('heading', { name: /^(框架内模型测试台|In-framework model benchmark)$/ }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: `/tmp/dsh-novel-outline-${test.info().project.name}-upper-20260909.png` })
  // Capture the viewport after scrolling, rather than a tall clipped form in
  // the host's inner scroll container. The DAG is validated expanded above.
  await dag.locator('summary').click()
  const defaultRange = controls.getByText(range(options.default_outline_start_chapter, options.default_outline_start_chapter + 2))
  await defaultRange.scrollIntoViewIfNeeded()
  const readinessNotice = page.getByTestId('benchmark-readiness')
  if (await readinessNotice.count()) await readinessNotice.scrollIntoViewIfNeeded()
  await expect(defaultRange).toBeInViewport()
  await expect(dag).toBeInViewport()
  if (await readinessNotice.count()) await expect(readinessNotice).toBeInViewport()
  await page.screenshot({ path: `/tmp/dsh-novel-outline-${test.info().project.name}-lower-20260909.png` })
  const layout = await layoutSnapshot()
  console.log(`[benchmark-layout:${test.info().project.name}:reading]`, JSON.stringify(layout))
  // A hidden-overflow shell must not turn a 70 px strip into a passing mobile
  // test. The compact host rail uses 56 px; allow at most 44 px of outer gaps.
  expect(layout.form.width).toBeGreaterThanOrEqual(page.viewportSize().width <= 900 ? page.viewportSize().width - 100 : 900)
  for (const task of layout.taskChoices) expect(task.width, 'task choices must remain readable').toBeGreaterThanOrEqual(200)
  for (const field of layout.fields) expect(field.width, `readable ${field.label}`).toBeGreaterThanOrEqual(field.tag === 'SELECT' ? 180 : 112)

  const minimum = options.limits.outline_start_chapter.min
  const maximum = options.limits.outline_start_chapter.max
  const manualStart = Math.max(minimum, Math.min(options.default_outline_start_chapter + 2, maximum - 2))
  expect(manualStart + 2).toBeLessThanOrEqual(maximum)
  await origin.selectOption('custom')
  await expect(start).toBeEnabled()
  await start.fill(String(manualStart))
  await count.fill('3')
  await expect(controls.getByText(range(manualStart, manualStart + 2))).toBeVisible()
  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `manual outline range overflow at ${page.viewportSize().width}px`).toBeLessThanOrEqual(clientWidth)
  expect(attemptedWrites, 'inspecting options and editing test configuration must remain read-only').toEqual([])
  const afterDocuments = await Promise.all(documentPaths.map(path => readDocument(page, path)))
  for (const [index, after] of afterDocuments.entries()) {
    expect(after.revision, documentPaths[index]).toBe(beforeDocuments[index].revision)
    expect(after.content, documentPaths[index]).toBe(beforeDocuments[index].content)
  }
})

test('benchmark and research result workbenches render existing artifacts read-only', async ({ page }) => {
  test.setTimeout(180_000)
  const headers = { 'X-Dsh-Workspace-Id': targetWorkspaceId }
  const [benchmarkResponse, researchResponse] = await Promise.all([
    page.request.get('/studio-panel/api/benchmarks?limit=30', { headers }),
    page.request.get('/studio-panel/api/research', { headers }),
  ])
  expect(benchmarkResponse.ok()).toBe(true)
  expect(researchResponse.ok()).toBe(true)
  const benchmarks = (await benchmarkResponse.json())?.data?.runs ?? []
  const reports = (await researchResponse.json())?.data?.reports ?? []
  expect(benchmarks.length).toBeGreaterThan(0)
  expect(reports.length).toBeGreaterThan(0)
  const benchmarkId = benchmarks[0].run_id
  const report = reports[0]
  const benchmarkDetailBefore = await page.request.get(
    `/studio-panel/api/benchmarks/${encodeURIComponent(benchmarkId)}`,
    { headers },
  )
  const reportDetailBefore = await page.request.get(
    `/studio-panel/api/research/reports/${encodeURIComponent(report.id)}`,
    { headers },
  )
  expect(benchmarkDetailBefore.ok()).toBe(true)
  expect(reportDetailBefore.ok()).toBe(true)
  const benchmarkSnapshot = (await benchmarkDetailBefore.json()).data
  const reportSnapshot = (await reportDetailBefore.json()).data

  await openWorkbenchSession(page)
  await page.getByRole('tab', { name: /^(任务|Tasks)$/ }).click()
  await page.getByRole('button', { name: /^(模型测试|Model test)$/ }).first().click()
  await expect(page.getByTestId('benchmark-comparison-group').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(benchmarkId, { exact: true }).first()).toBeVisible()
  await page.getByText(benchmarkId, { exact: true }).first().click()
  await expect(page.locator('[data-testid="benchmark-provenance"]')).toBeVisible()

  await page.getByRole('button', { name: /^(研究|Research)$/ }).first().click()
  const reportButton = page.locator('button').filter({ hasText: report.title || report.id }).first()
  await expect(reportButton).toBeVisible({ timeout: 30_000 })
  await reportButton.click()
  await expect(page.getByText(/^(来源核查|Source verification)$/)).toBeVisible()
  await expect(page.getByText(/^(研究报告是参考材料，不会自动写入正典、大纲或正文。|Research reports are reference material and never enter canon, outline, or manuscript automatically\.)$/)).toBeVisible()
  await expect(page.getByRole('button', { name: /^(导出 Markdown|Export Markdown)$/ })).toBeVisible()
  await expect(page.locator('[data-testid="research-provenance"]')).toBeVisible()

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
  const [benchmarkDetailAfter, reportDetailAfter] = await Promise.all([
    page.request.get(`/studio-panel/api/benchmarks/${encodeURIComponent(benchmarkId)}`, { headers }),
    page.request.get(`/studio-panel/api/research/reports/${encodeURIComponent(report.id)}`, { headers }),
  ])
  expect((await benchmarkDetailAfter.json()).data).toEqual(benchmarkSnapshot)
  expect((await reportDetailAfter.json()).data).toEqual(reportSnapshot)
})

test('author history and revision workbench renders read-only without changing the manuscript', async ({ page }) => {
  test.setTimeout(180_000)
  const workspaceResponse = await page.request.get('/studio-panel/api/workspace', {
    headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
  })
  expect(workspaceResponse.ok()).toBe(true)
  const workspace = await workspaceResponse.json()
  const chapters = workspace?.documents?.chapters ?? []
  expect(chapters.length).toBeGreaterThan(0)
  const path = chapters.at(-1).path
  const chapterId = /(?:^|\/)(ch_\d+)\.md$/.exec(path)?.[1]
  expect(chapterId).toBeTruthy()
  const beforeResponse = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, {
    headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
  })
  expect(beforeResponse.ok()).toBe(true)
  const before = await beforeResponse.json()
  const versionsResponse = await page.request.get(
    `/studio-panel/api/manuscript/versions?chapter=${encodeURIComponent(chapterId)}`,
    { headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId } },
  )
  expect(versionsResponse.ok()).toBe(true)
  const versionsPayload = await versionsResponse.json()
  const versions = versionsPayload?.data?.versions ?? []

  await openWorkbenchSession(page)
  await page.evaluate(({ workspaceId, path }) => {
    localStorage.setItem(`dsh-novel.inspectorVisible.${workspaceId}`, 'true')
    localStorage.setItem(`dsh-novel.activeChapterPath.${workspaceId}`, path)
  }, { workspaceId: targetWorkspaceId, path })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('tab', { name: /^(创作|Create)$/ })).toBeVisible()
  await page.getByRole('tab', { name: /^(创作|Create)$/ }).click()
  if ((page.viewportSize()?.width ?? 1000) <= 900) {
    await page.getByRole('button', { name: /^(检查器|Inspector)$/ }).first().click()
  }
  await page.getByRole('tab', { name: /^(修订|Revisions)$/ }).click()

  await expect(page.getByText(/^(正文历史|Manuscript history)$/)).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(/^(修订提案|Revision proposals)$/)).toBeVisible()
  await expect(page.locator('body')).not.toContainText('"proposal_id"')
  await expect(page.locator('body')).not.toContainText('"version_id"')
  if (versions.length > 0) {
    await page.getByRole('button', { name: /^(比较|Compare)$/ }).first().click()
    await expect(page.getByText(/^(恢复预览：当前正文 → 旧版本|Restore preview: current → saved version)$/)).toBeVisible()
  } else {
    await expect(page.getByText(/^(本章还没有可恢复的历史版本。|This chapter has no recoverable history yet\.)$/)).toBeVisible()
  }

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
  const afterResponse = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, {
    headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
  })
  expect(afterResponse.ok()).toBe(true)
  const after = await afterResponse.json()
  expect(after.revision).toBe(before.revision)
  expect(after.content).toBe(before.content)
})

test('context inspector shows the actual protected packet and separate budgets without changing the manuscript', async ({ page }) => {
  test.setTimeout(180_000)
  const headers = { 'X-Dsh-Workspace-Id': targetWorkspaceId }
  const workspaceResponse = await page.request.get('/studio-panel/api/workspace', { headers })
  expect(workspaceResponse.ok()).toBe(true)
  const workspace = await workspaceResponse.json()
  const chapters = workspace?.documents?.chapters ?? []
  expect(chapters.length).toBeGreaterThan(0)
  const path = chapters.at(-1).path
  const chapterId = /(?:^|\/)(ch_\d+)\.md$/.exec(path)?.[1]
  expect(chapterId).toBeTruthy()
  const beforeResponse = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, { headers })
  expect(beforeResponse.ok()).toBe(true)
  const before = await beforeResponse.json()
  const contextResponse = await page.request.get(
    `/studio-panel/api/context?chapter=${encodeURIComponent(chapterId)}`,
    { headers },
  )
  expect(contextResponse.ok()).toBe(true)
  const contextPayload = await contextResponse.json()
  const manifest = contextPayload?.manifest ?? {}
  expect(manifest.packet_revision).toBeTruthy()
  expect(manifest.source_revision).toBeTruthy()
  expect(manifest.freshness?.status).toBe('current')
  expect(manifest.request_budget?.scope).toBe('openwrite_writing_request')
  expect(manifest.session_budget).toMatchObject({ scope: 'dsh_session', available: false })
  expect((manifest.items ?? []).some(item => item.protected === true)).toBe(true)

  await openWorkbenchSession(page)
  await page.evaluate(({ workspaceId, path }) => {
    localStorage.setItem(`dsh-novel.inspectorVisible.${workspaceId}`, 'true')
    localStorage.setItem(`dsh-novel.activeChapterPath.${workspaceId}`, path)
  }, { workspaceId: targetWorkspaceId, path })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('tab', { name: /^(创作|Create)$/ }).click()
  if ((page.viewportSize()?.width ?? 1000) <= 900) {
    await page.getByRole('button', { name: /^(检查器|Inspector)$/ }).first().click()
  }

  await expect(page.getByText(/^(实际写章包 revision|Actual writing packet revision)$/)).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(manifest.packet_revision, { exact: true })).toBeVisible()
  await expect(page.getByText(/^(OpenWrite 写章请求预算|OpenWrite writing request budget)$/)).toBeVisible()
  await expect(page.getByText(/^(dsh 会话预算|dsh session budget)$/)).toBeVisible()
  await expect(page.getByText(/^(实际来源与选择结果|Actual sources and selection results)$/)).toBeVisible()
  await expect(page.getByText(/^(受保护|Protected)$/).first()).toBeVisible()
  await expect(page.locator('body')).not.toContainText('"packet_revision"')

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
  const afterResponse = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, { headers })
  expect(afterResponse.ok()).toBe(true)
  const after = await afterResponse.json()
  expect(after.revision).toBe(before.revision)
  expect(after.content).toBe(before.content)
})

test('save queue, retry, conflict and chapter barriers keep the canonical manuscript unchanged', async ({ page }) => {
  test.setTimeout(180_000)
  const headers = { 'X-Dsh-Workspace-Id': targetWorkspaceId }
  const workspaceResponse = await page.request.get('/studio-panel/api/workspace', { headers })
  expect(workspaceResponse.ok()).toBe(true)
  const workspace = await workspaceResponse.json()
  const chapters = workspace?.documents?.chapters ?? []
  expect(chapters.length).toBeGreaterThan(1)
  const chapter = chapters.at(-1)
  const alternateChapter = chapters.at(-2)
  const before = await readDocument(page, chapter.path)
  const alternateBefore = await readDocument(page, alternateChapter.path)
  const novelId = workspace.snapshot.novel_id
  const recoveryKey = `v1:${JSON.stringify([targetWorkspaceId, novelId, chapter.path])}`
  const requests = []
  let releaseFirst
  let firstSeen
  const firstSeenPromise = new Promise(resolvePromise => { firstSeen = resolvePromise })
  const releaseFirstPromise = new Promise(resolvePromise => { releaseFirst = resolvePromise })

  await page.route('**/studio-panel/api/document', async route => {
    const request = route.request()
    expect(request.headers()['x-dsh-workspace-id']).toBe(targetWorkspaceId)
    if (request.method() !== 'PUT') {
      await route.continue()
      return
    }
    const body = request.postDataJSON()
    const index = requests.push({
      content: body.content,
      version: body.version,
      saveOrigin: body.save_origin,
      force: body.force === true,
      workspaceId: request.headers()['x-dsh-workspace-id'],
    }) - 1
    if (index === 0) {
      firstSeen()
      await releaseFirstPromise
    }
    if (index === 2) {
      await route.abort('internetdisconnected')
      return
    }
    if (index === 4) {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'mock revision conflict', code: 'DOCUMENT_CONFLICT' }),
      })
      return
    }
    const successfulWrites = index <= 1 ? index + 1 : index === 3 ? 3 : 4
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        path: body.path,
        title: before.title,
        content: body.content,
        version: `e2e-version-${String(successfulWrites)}`,
        revision: `e2e-revision-${String(successfulWrites)}`,
      }),
    })
  })

  try {
    await openWorkbenchSession(page)
    await page.evaluate(({ workspaceId, path }) => {
      localStorage.setItem(`dsh-novel.activeChapterPath.${workspaceId}`, path)
      localStorage.setItem(`dsh-novel.chapterRailVisible.${workspaceId}`, 'true')
    }, { workspaceId: targetWorkspaceId, path: chapter.path })
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.getByRole('tab', { name: /^(创作|Create)$/ }).click()
    await expect(page.getByText(chapter.path, { exact: true })).toHaveText(chapter.path)
    await expect(page.locator('.vditor-ir')).toHaveCount(1)

    const queuedA = `E2E 保存队列 A ${test.info().project.name}`
    const queuedB = `E2E 保存队列 B ${test.info().project.name}`
    await replaceEditorText(page, queuedA)
    await page.getByRole('button', { name: /^(未保存|Unsaved)$/ }).click()
    await firstSeenPromise
    expect(requests).toHaveLength(1)
    await replaceEditorText(page, queuedB)
    await page.waitForTimeout(1_300)
    expect(requests).toHaveLength(1)
    releaseFirst()
    await expect.poll(() => requests.length).toBe(2)
    await expect(page.getByRole('button', { name: /^(已保存|Saved)$/ })).toBeDisabled()
    expect(requests[0].content.trim()).toBe(queuedA)
    expect(requests[0]).toMatchObject({
      version: before.version,
      saveOrigin: 'manual',
      force: false,
      workspaceId: targetWorkspaceId,
    })
    expect(requests[1].content.trim()).toBe(queuedB)
    expect(requests[1]).toMatchObject({
      version: 'e2e-version-1',
      saveOrigin: 'autosave',
      force: false,
      workspaceId: targetWorkspaceId,
    })

    const offlineDraft = `E2E 离线重试 ${test.info().project.name}`
    await replaceEditorText(page, offlineDraft)
    await page.getByRole('button', { name: /^(未保存|Unsaved)$/ }).click()
    await expect.poll(() => requests.length).toBe(3)
    await expect(page.getByRole('button', { name: /^(离线|Offline)$/ })).toBeVisible()
    await page.getByRole('button', { name: /^(重试|Retry)$/ }).click()
    await expect.poll(() => requests.length).toBe(4)
    await expect(page.getByRole('button', { name: /^(已保存|Saved)$/ })).toBeDisabled()
    expect(requests[2].content.trim()).toBe(offlineDraft)
    expect(requests[2]).toMatchObject({ version: 'e2e-version-2', force: false })
    expect(requests[3].content.trim()).toBe(offlineDraft)
    expect(requests[3]).toMatchObject({ version: 'e2e-version-2', saveOrigin: 'manual', force: false })

    const conflictDraft = `E2E 冲突覆盖 ${test.info().project.name}`
    await replaceEditorText(page, conflictDraft)
    await page.getByRole('button', { name: /^(未保存|Unsaved)$/ }).click()
    await expect.poll(() => requests.length).toBe(5)
    await expect(page.getByRole('button', { name: /^(有冲突|Conflict)$/ })).toBeVisible()
    page.once('dialog', dialog => dialog.accept())
    await page.getByRole('button', { name: /^(覆盖|Overwrite)$/ }).click()
    await expect.poll(() => requests.length).toBe(6)
    await expect(page.getByRole('button', { name: /^(已保存|Saved)$/ })).toBeDisabled()
    expect(requests[4].content.trim()).toBe(conflictDraft)
    expect(requests[4]).toMatchObject({ version: 'e2e-version-3', force: false })
    expect(requests[5].content.trim()).toBe(conflictDraft)
    expect(requests[5]).toMatchObject({
      version: 'e2e-version-3',
      saveOrigin: 'manual',
      force: true,
      workspaceId: targetWorkspaceId,
    })

    const discardedDraft = `E2E 章节切换屏障 ${test.info().project.name}`
    await replaceEditorText(page, discardedDraft)
    await expect(page.getByRole('button', { name: /^(未保存|Unsaved)$/ })).toBeVisible()
    if ((page.viewportSize()?.width ?? 1000) <= 900) {
      await page.getByRole('button', { name: /^(章节|Chapters)$/ }).first().click()
    }
    const alternateButton = page.getByRole('complementary').first().locator('button[data-active="false"]').last()
    await expect(alternateButton).toBeVisible()
    const dismissDialog = page.waitForEvent('dialog')
    const dismissClick = alternateButton.click()
    await (await dismissDialog).dismiss()
    await dismissClick
    await expect(page.getByText(chapter.path, { exact: true })).toHaveText(chapter.path)
    const acceptDialog = page.waitForEvent('dialog')
    const acceptClick = alternateButton.click()
    await (await acceptDialog).accept()
    await acceptClick
    await expect(page.getByText(alternateChapter.path, { exact: true })).toHaveText(alternateChapter.path)
    await expect(page.locator('.vditor-ir')).not.toContainText(discardedDraft)
    await page.waitForTimeout(1_300)
    expect(requests).toHaveLength(6)

    const after = await readDocument(page, chapter.path)
    const alternateAfter = await readDocument(page, alternateChapter.path)
    expect(after.revision).toBe(before.revision)
    expect(after.content).toBe(before.content)
    expect(alternateAfter.revision).toBe(alternateBefore.revision)
    expect(alternateAfter.content).toBe(alternateBefore.content)
  } finally {
    await deleteRecoveryDraft(page, recoveryKey)
  }
})

test('recovery draft is isolated, previewed explicitly, and removed without changing the manuscript', async ({ page }) => {
  test.setTimeout(180_000)
  const workspaceResponse = await page.request.get('/studio-panel/api/workspace', {
    headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
  })
  expect(workspaceResponse.ok()).toBe(true)
  const workspace = await workspaceResponse.json()
  const chapters = workspace?.documents?.chapters ?? []
  expect(chapters.length).toBeGreaterThan(0)
  const path = chapters.at(-1).path
  const novelId = workspace.snapshot.novel_id
  const documentResponse = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, {
    headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
  })
  expect(documentResponse.ok()).toBe(true)
  const document = await documentResponse.json()
  const marker = `E2E 本地恢复稿 ${test.info().project.name}`
  const key = `v1:${JSON.stringify([targetWorkspaceId, novelId, path])}`

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.evaluate(async ({ key, marker, novelId, path, revision, workspaceId }) => {
    // Select the chapter whose draft we seed. A new project's current chapter
    // can be its first chapter, so the default need not be chapters.at(-1).
    localStorage.setItem(`dsh-novel.activeChapterPath.${workspaceId}`, path)
    await new Promise((resolvePromise, rejectPromise) => {
      const request = indexedDB.open('dsh-novel-manuscript-drafts', 1)
      request.onupgradeneeded = () => request.result.createObjectStore('drafts', { keyPath: 'key' })
      request.onerror = () => rejectPromise(request.error)
      request.onsuccess = () => {
        const transaction = request.result.transaction('drafts', 'readwrite')
        transaction.objectStore('drafts').put({
          key,
          formatVersion: 1,
          workspaceId,
          novelId,
          path,
          baseRevision: revision,
          content: marker,
          updatedAt: Date.now(),
        })
        transaction.oncomplete = () => { request.result.close(); resolvePromise() }
        transaction.onerror = () => rejectPromise(transaction.error)
      }
    })
  }, { key, marker, novelId, path, revision: document.revision, workspaceId: targetWorkspaceId })

  const injected = await page.evaluate(async ({ key }) => await new Promise((resolvePromise, rejectPromise) => {
    const request = indexedDB.open('dsh-novel-manuscript-drafts', 1)
    request.onerror = () => rejectPromise(request.error)
    request.onsuccess = () => {
      const transaction = request.result.transaction('drafts', 'readonly')
      const get = transaction.objectStore('drafts').get(key)
      get.onsuccess = () => { request.result.close(); resolvePromise(get.result ?? null) }
      get.onerror = () => rejectPromise(get.error)
    }
  }), { key })
  expect(injected).toMatchObject({ key, workspaceId: targetWorkspaceId, novelId, path, content: marker })

  try {
    await openWorkbenchSession(page)
    await page.getByRole('tab', { name: /^(创作|Create)$/ }).click()
    const editor = page.locator('.vditor-ir')
    await expect(editor).toHaveCount(1, { timeout: 60_000 })
    await expect(page.getByText(/^(发现未保存的本地恢复稿。|An unsaved local recovery draft is available\.)$/)).toBeVisible({ timeout: 60_000 })
    await expect(editor).not.toContainText(marker)
    await page.getByText(/^(查看恢复稿|Preview recovery draft)$/).click()
    await expect(page.getByText(marker, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: /^(忽略并删除|Ignore and delete)$/ }).click()
    await expect(page.getByText(marker, { exact: true })).toHaveCount(0)

    const persisted = await page.evaluate(async ({ key }) => await new Promise((resolvePromise, rejectPromise) => {
      const request = indexedDB.open('dsh-novel-manuscript-drafts', 1)
      request.onerror = () => rejectPromise(request.error)
      request.onsuccess = () => {
        const transaction = request.result.transaction('drafts', 'readonly')
        const get = transaction.objectStore('drafts').get(key)
        get.onsuccess = () => { request.result.close(); resolvePromise(get.result ?? null) }
        get.onerror = () => rejectPromise(get.error)
      }
    }), { key })
    expect(persisted).toBeNull()
    const afterResponse = await page.request.get(`/studio-panel/api/document?path=${encodeURIComponent(path)}`, {
      headers: { 'X-Dsh-Workspace-Id': targetWorkspaceId },
    })
    expect(afterResponse.ok()).toBe(true)
    const after = await afterResponse.json()
    expect(after.revision).toBe(document.revision)
    expect(after.content).toBe(document.content)
  } finally {
    await deleteRecoveryDraft(page, key)
  }
})
