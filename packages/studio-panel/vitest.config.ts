/**
 * Vitest config for the offline React component layer (scripts/components/).
 * Run: npm run test:components
 *
 * - jsdom over happy-dom: React 18 + @testing-library/react are most heavily
 *   validated against jsdom, and jsdom implements more of the DOM surface the
 *   views touch (localStorage, matchMedia stubs aside) with fewer gaps.
 * - `dsh-react-flow-style` is a tsdown virtual module (see tsdown.config.ts);
 *   here it is aliased to an empty stub.
 * - CSS modules stay unprocessed (vitest stubs them to empty objects); the
 *   components tolerate undefined class names.
 */
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: {
    alias: {
      'dsh-react-flow-style': fileURLToPath(new URL('./scripts/components/stubs/empty.ts', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['scripts/components/**/*.test.{ts,tsx}'],
    setupFiles: ['scripts/components/setup.ts'],
    // Deterministic offline runs: no network, no watch artifacts.
    watch: false,
  },
})
