import type { TestProjectConfiguration } from 'vitest/config'
import { defineConfig } from 'vitest/config'

// vitest.setup.ts widens Testing Library's asyncUtilTimeout so findBy*/waitFor
// survive a starved runner. That only helps if the test itself is allowed to
// outlive the wait — at vitest's 5s default the test dies first and reports an
// opaque "Test timed out" instead of the query error. Keep testTimeout well
// above asyncUtilTimeout so the failing query is the thing that gets reported.
const TEST_TIMEOUT_MS = 30_000

const reactUi: TestProjectConfiguration = {
  extends: './vite.config.ts',
  test: {
    name: 'ui',
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    globals: true,
    testTimeout: TEST_TIMEOUT_MS,
    hookTimeout: TEST_TIMEOUT_MS
  }
}

const electronNative: TestProjectConfiguration = {
  test: {
    name: 'electron',
    environment: 'node',
    // `e2e/**/*.unit.test.ts` is the e2e HELPERS, not the specs: plain node
    // modules that should be provable without booting Electron. Playwright
    // ignores the same pattern so they run in exactly one runner.
    include: ['electron/**/*.test.ts', 'scripts/**.test.{ts,mjs}', 'e2e/**/*.unit.test.ts'],
    // These use node:test and have dedicated npm scripts, not Vitest suites.
    exclude: ['scripts/run-short-session-hang-repro.test.mjs', 'scripts/tasks-scroll.test.mjs'],
    testTimeout: TEST_TIMEOUT_MS,
    hookTimeout: TEST_TIMEOUT_MS
  }
}

export default defineConfig({
  test: {
    // Runs once for the whole run (both projects) and before any test file is
    // loaded, so lockfile drift is reported as drift instead of as 32 tests
    // failing on a missing export. See vitest.globalSetup.mjs.
    globalSetup: ['./vitest.globalSetup.mjs'],
    projects: [reactUi, electronNative]
  }
})
