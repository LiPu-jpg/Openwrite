/**
 * Playwright E2E runner for the studio-panel workbenches.
 * Run: npm run test:e2e
 *
 * Browsers live inside the repo: the npm script sets
 * PLAYWRIGHT_BROWSERS_PATH=.pw-browsers (gitignored). Install with:
 *   cd packages/studio-panel && PLAYWRIGHT_BROWSERS_PATH=.pw-browsers npx playwright install chromium
 *
 * The specs are service-gated: e2e/helpers.mjs probes dsh web (127.0.0.1:3080)
 * and OpenWrite Studio (127.0.0.1:4567) first, and every test skips with the
 * probe reason when either is unreachable — an absent dev stack must never
 * fail this suite.
 */
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 60_000 },
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:3080',
    // The dev shell exports http_proxy; loopback must bypass it.
    launchOptions: {},
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
  ],
})
