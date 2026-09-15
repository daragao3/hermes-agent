import type { TestProjectConfiguration } from 'vitest/config'
import { defineConfig } from 'vitest/config'

// vitest.setup.ts widens Testing Library's asyncUtilTimeout so findBy*/waitFor
// survive a starved runner. That only helps if the test itself is allowed to
// outlive the wait — at vitest's 5s default the test dies first and reports an
// opaque "Test timed out" instead of the query error. Keep testTimeout well
// above asyncUtilTimeout (15s) so the failing query is the thing that gets
// reported.
//
// 30s was not enough, and the symptom was misleading. MEASURED 2026-09-15:
// config-settings.test.tsx costs 5.6s of test time and keys-settings.test.tsx
// 3.1s when their file is run alone, yet BOTH died at exactly
// "Test timed out in 30000ms" under the full 764-file suite — a >5x load
// inflation on a box that routinely carries 20+ concurrent agent worktrees.
// An opaque timeout is the one failure mode this constant exists to prevent,
// so it was doing the opposite of its job: the reds looked like defects in
// the autosave and env-var logic, which are both fine. 60s keeps the 4x
// margin over asyncUtilTimeout and leaves ~2x headroom over the measured
// loaded cost. The cost of the raise is that a genuinely hung test now takes
// 60s to report instead of 30s.
const TEST_TIMEOUT_MS = 60_000

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
