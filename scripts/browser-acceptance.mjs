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
  page.setDefaultTimeout(30_000)
  const errors = []
  let initializationStarted = 0
  page.on('response', response => {
    if (response.url().includes('/studio-panel/api/project/init')) console.log('Browser: initialization HTTP response', response.status(), Date.now() - initializationStarted, 'ms')
  })
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto(loginUrl)
    // Complete the host's normal first-use notice and defer model credentials;
    // neither step changes permission presets or makes a paid model request.
    await page.getByRole('button', { name: /^(继续|Continue)$/ }).click()
    await page.getByRole('button', { name: /^(稍后配置|Configure later)$/ }).click()
    console.log('Browser: host onboarding complete')
    await page.getByRole('button', { name: '打开 OpenWrite', exact: true }).click()
    await page.getByText('写作环境已就绪', { exact: true }).first().waitFor()
    const workspace = join(temporary, '中文作品-100%')
    await mkdir(workspace, { recursive: true })
    await page.getByLabel('作品目录', { exact: true }).fill(workspace)
    await page.getByRole('button', { name: '进入作品', exact: true }).click()
    await page.getByRole('tab', { name: /^(创作|Create)$/ }).click()
    console.log('Browser: blank-session workbench opened')
    // The blank workbench and its initialization form must work without a model turn.
    await page.locator('button[data-actionable="true"]').click()
    await page.getByPlaceholder('my-novel', { exact: true }).fill('release-test')
    await page.getByLabel(/^(书名|Title)$/).fill('中文作品验收')
    initializationStarted = Date.now()
    await page.getByRole('button', { name: /^(初始化项目|Initialize project)$/ }).click()
    await page.getByRole('button', { name: /^(初始化项目|Initialize project)$/ }).waitFor({ state: 'hidden', timeout: 90_000 })
    for (const label of [/^(资料|Library)$/, /^(任务|Tasks)$/]) await page.getByRole('tab', { name: label }).click()
    assert.deepEqual(errors, [], 'browser runtime errors')
    return ['native-browser-launch', 'blank-session-workbench', 'workspace-selection', 'initialize-project', 'workbench-navigation']
  } catch (error) {
    await page.screenshot({ path: `release-browser-${process.platform}-${process.arch}.png`, fullPage: true }).catch(() => {})
    console.error('Browser errors:', errors)
    throw error
  } finally { await browser.close() }
}
