/**
 * Studio-panel E2E: secret non-echo on the model view, workbench shell and
 * mobile (390×844) interaction assertions.
 *
 * Skip gates:
 *   1. `beforeAll` probes dsh web (3080) and Studio (4567); when either is
 *      unreachable the whole file skips with the probe reason — these specs
 *      only produce evidence against a live dev stack (`npm run dev`).
 *   2. The conversation views (Create/Library/Tasks) only mount inside an
 *      existing session; when the local dsh state has none, the affected
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

async function workspaceList() {
  const response = await fetch('http://127.0.0.1:3080/api/workspace.list', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      type: 'client-request',
      rpcId: `rpc_e2e_${String(Date.now())}`,
      method: 'workspace.list',
      payload: {},
    }),
  })
  const payload = await response.json()
  return payload?.result?.value?.items ?? []
}

test.beforeAll(async () => {
  const status = await probeServices()
  if (!status.ok) console.log(`[studio-panel e2e] skipping: ${status.reason}`)
  test.skip(!status.ok, `E2E skipped: ${status.reason}`)
  const workspace = (await workspaceList()).find(item => resolve(item.path) === TARGET_PROJECT)
  if (workspace) {
    targetWorkspaceId = workspace.workspaceId
    targetWorkspaceTitle = workspace.title
    targetSessionId = workspace.sessionIds?.find(sessionId => typeof sessionId === 'string') ?? ''
  }
  test.skip(targetWorkspaceId === '', `E2E skipped: no dsh Workspace maps to ${TARGET_PROJECT}`)
  test.skip(targetSessionId === '', `E2E skipped: no dsh session belongs to ${TARGET_PROJECT}`)
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
    localStorage.removeItem(`dsh-novel.activeChapterPath.${workspaceId}`)
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
