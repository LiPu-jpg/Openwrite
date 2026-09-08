// Native CI browser QA, backed by the installed plugin and isolated ProjectRegistry.
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../packages/studio-panel/package.json', import.meta.url))

export async function acceptBrowser(loginUrl, temporary) {
  const { chromium } = require('@playwright/test')
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto(loginUrl)
    await page.getByRole('button', { name: '打开 OpenWrite', exact: true }).click()
    await page.getByText('写作环境已就绪', { exact: true }).first().waitFor()
    const workspace = join(temporary, 'browser-novel')
    await mkdir(workspace, { recursive: true })
    await page.getByLabel('作品目录', { exact: true }).fill(workspace)
    await page.getByRole('button', { name: '进入作品', exact: true }).click()
    await page.getByRole('tab', { name: /^(创作|Create)$/ }).click()
    // The blank workbench and its initialization form must work without a model turn.
    await page.locator('button[data-actionable="true"]').click()
    await page.getByPlaceholder('my-novel', { exact: true }).fill('release-test')
    await page.getByLabel(/^(书名|Title)$/).fill('Release acceptance')
    await page.getByRole('button', { name: /^(初始化项目|Initialize project)$/ }).click()
    await page.getByRole('button', { name: /^(初始化项目|Initialize project)$/ }).waitFor({ state: 'hidden' })
    for (const label of [/^(资料|Library)$/, /^(任务|Tasks)$/]) await page.getByRole('tab', { name: label }).click()
    assert.deepEqual(errors, [], 'browser runtime errors')
    return ['native-browser-launch', 'blank-session-workbench', 'workspace-selection', 'initialize-project', 'workbench-navigation']
  } finally { await browser.close() }
}
