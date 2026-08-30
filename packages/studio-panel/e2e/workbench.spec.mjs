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
import { probeServices } from './helpers.mjs'

const VIEW_TABS = [/^(创作|Create)$/, /^(资料|Library)$/, /^(任务|Tasks)$/]

test.beforeAll(async () => {
  const status = await probeServices()
  if (!status.ok) console.log(`[studio-panel e2e] skipping: ${status.reason}`)
  test.skip(!status.ok, `E2E skipped: ${status.reason}`)
})

async function documentOverflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
}

/** The workbench tabs only render inside a conversation session; open one. */
async function openWorkbenchSession(page) {
  await page.goto('/', { waitUntil: 'networkidle' })
  // Mobile collapses the sidebar; open it to reach the session tree.
  const openSidebar = page.getByRole('button', { name: 'Open sidebar' })
  if (await openSidebar.count() > 0) await openSidebar.first().click()
  // Session treeitems carry a relative-age suffix ("查询当前作品状态 9d");
  // workspace group rows and the "New Session" draft do not.
  const sessions = page.getByRole('treeitem', { name: /\s\d+[dh]\b/ })
  const count = await sessions.count()
  test.skip(count === 0, 'no existing dsh session hosts the workbench views')
  await sessions.first().click()
  await expect(page.getByRole('tab', { name: VIEW_TABS[0] })).toBeVisible({ timeout: 10_000 })
}

test('workbench shell loads with zero horizontal overflow', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  await expect(page.locator('body')).not.toBeEmpty()

  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
})

test('model view renders credential fields empty and echo-free', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'desktop-only scenario')

  await openWorkbenchSession(page)
  // Tasks view → 模型/Models segment (OperationsView → ModelView).
  await page.getByRole('tab', { name: /^(任务|Tasks)$/ }).click()
  await page.getByRole('button', { name: /^(模型|Models)$/ }).first().click()

  const passwords = page.locator('input[type=password]')
  await expect(passwords.first()).toBeVisible()
  for (const input of await passwords.all()) {
    await expect(input).toHaveValue('')
  }
  // No credential-shaped value may reach the DOM after CRUD list rendering.
  await expect(page.locator('body')).not.toContainText('sk-or-v1-')
  await expect(page.locator('body')).not.toContainText('api_key')
})

test('mobile: key workbench controls reachable, zero overflow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'mobile-only scenario')

  await openWorkbenchSession(page)
  for (const tab of VIEW_TABS) {
    await expect(page.getByRole('tab', { name: tab })).toBeVisible()
  }

  // Switch through the workbenches; the document must never grow wider than
  // the 390px viewport.
  await page.getByRole('tab', { name: /^(资料|Library)$/ }).click()
  await page.getByRole('tab', { name: /^(任务|Tasks)$/ }).click()
  const { scrollWidth, clientWidth } = await documentOverflow(page)
  expect(scrollWidth, `horizontal overflow: scrollWidth ${scrollWidth} > clientWidth ${clientWidth}`).toBeLessThanOrEqual(clientWidth)
})
