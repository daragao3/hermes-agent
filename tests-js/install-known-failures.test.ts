import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const { matchKnownFailure, rules } = createRequire(import.meta.url)('../tests/install/e2e-assets/known-failures.cjs')
const classifier = path.resolve(import.meta.dirname, '../tests/install/e2e-assets/known-failures.cjs')

const lockedLog = [
  'error: failed to remove file `C:/install/venv/Lib/site-packages/../../Scripts/hermes.exe`: Access is denied. (os error 5)',
  'File "C:/install/venv/Scripts/hermes.exe/__main__.py", line 10, in <module>',
  "subprocess.CalledProcessError: Command '['uv', 'pip', 'install', '-e', '.', '--quiet']' returned non-zero exit status 2.",
].join('\n')

const base = {
  platform: 'windows', phase: 'update', commit: 'a370ab8391ca5f8de7ebbc449f05cb0df36ade7c',
  installMethod: 'installer-script', updateMethod: 'hermes-update',
  error: 'E2E ASSERTION FAILED: hermes update exited 1 (expected 0)', logs: { update: lockedLog },
}

describe('known install failures', () => {
  it('recognizes the released launcher self-lock, not generic access denied', () => {
    expect(matchKnownFailure(base)?.id).toBe('windows-launcher-self-lock')
    expect(matchKnownFailure({ ...base, logs: { update: lockedLog.replaceAll('hermes.exe', 'other.exe') } })).toBeNull()
    expect(matchKnownFailure({ ...base, logs: { update: lockedLog.replace('(os error 5)', '(os error 32)') } })).toBeNull()
  })

  it.each([
    { platform: 'linux' }, { phase: 'install' }, { commit: 'v2026.3.12' },
    { commit: 'f'.repeat(40) }, { installMethod: 'desktop-installer@latest' },
    { updateMethod: 'installer-script' }, { error: 'E2E ASSERTION FAILED: update marker cleaned up' },
    { logs: {} },
  ])('rejects a different case or missing evidence: %j', change => {
    expect(matchKnownFailure({ ...base, ...change })).toBeNull()
  })

  it('matches manual-only app updates only for the proven script cases', () => {
    const sample = {
      ...base, commit: '7c1a029553d87c43ecff8a3821336bc95872213b',
      updateMethod: 'hermes-desktop-app-update',
      error: 'E2E ASSERTION FAILED: app driven via captured hermes desktop spec; update completed',
      logs: { desktop: '[hermes] [updates] no staged updater; surfacing manual `hermes update` for CLI install at C:/install\n[hermes] [updates] manual: hermes update\n' },
    }

    expect(matchKnownFailure(sample)?.id).toBe('windows-july-manual-app-update')
    expect(matchKnownFailure({ ...sample, installMethod: 'desktop-installer@latest' })).toBeNull()
    expect(matchKnownFailure({ ...sample, error: 'onboarding timed out' })).toBeNull()
    expect(matchKnownFailure({ ...sample, logs: { desktop: '[updates] manual: hermes update' } })).toBeNull()
  })

  // v2026.8.3 reaches the identical no-staged-updater branch
  // (apps/desktop/electron/main.ts:2891-2894), so the same three script cases
  // are covered from that release too. Run 35663715738 proved all three.
  it('covers the same script cases from the August release', () => {
    const august = {
      ...base, commit: '3c27eb6234bf91b8ceee9e9071591b31e9b148cb',
      logs: { desktop: '[hermes] [updates] no staged updater; surfacing manual `hermes update` for CLI install at D:/install\n[hermes] [updates] manual: hermes update\n' },
    }
    const cases = [
      { installMethod: 'installer-script', updateMethod: 'hermes-desktop-app-update', error: 'E2E ASSERTION FAILED: app driven via captured hermes desktop spec; update completed' },
      { installMethod: 'installer-script+desktop', updateMethod: 'hermes-desktop-app-update', error: 'E2E ASSERTION FAILED: app driven via captured hermes desktop spec; update completed' },
      { installMethod: 'installer-script+desktop', updateMethod: 'open-app-update', error: 'E2E ASSERTION FAILED: GUI driver clicked Update now and the app quit for hand-off' },
    ]
    for (const c of cases) {
      expect(matchKnownFailure({ ...august, ...c })?.id).toBe('windows-july-manual-app-update')
    }
    // A desktop-installer install has a staged updater: still not covered.
    expect(matchKnownFailure({ ...august, ...cases[0], installMethod: 'desktop-installer@latest' })).toBeNull()
    // An August CLI-update failure must fall to the loaded-extension rule, not this one.
    expect(matchKnownFailure({ ...august, updateMethod: 'hermes-update', error: 'E2E ASSERTION FAILED: hermes update exited 1 (expected 0)' })).toBeNull()
  })

  it('recognizes the August loaded-native-extension self-lock, not a generic access denied', () => {
    const rustLock = [
      'error: failed to remove file `D:/install/venv/Lib/site-packages/cryptography/hazmat/bindings/_rust.pyd`: Access is denied. (os error 5)',
      'cause: Failed to persist temporary file to D:/install/venv/Lib/site-packages/cryptography/hazmat/bindings/_rust.pyd: Access is denied. (os error 5)',
      "Git update failed: Command '['D:/install/bin/uv.exe', 'pip', 'install', '-e', '.']' returned non-zero exit status 2.",
    ].join('\n')
    const august = {
      ...base, commit: '3c27eb6234bf91b8ceee9e9071591b31e9b148cb', logs: { update: rustLock },
    }

    expect(matchKnownFailure(august)?.id).toBe('windows-loaded-native-extension-self-lock')
    // The CLI updater is the same released code regardless of how the install
    // was produced, so all three install methods are covered. Run
    // 35743063675 proved the desktop-installer one once its install phase
    // stopped failing and the update leg could finally be observed.
    for (const installMethod of ['installer-script', 'installer-script+desktop', 'desktop-installer@latest']) {
      expect(matchKnownFailure({ ...august, installMethod })?.id).toBe('windows-loaded-native-extension-self-lock')
    }
    expect(matchKnownFailure({ ...base, logs: { update: rustLock } })).toBeNull()
    expect(matchKnownFailure({ ...august, logs: { update: rustLock.replaceAll('_rust.pyd', '_other.pyd') } })).toBeNull()
    expect(matchKnownFailure({ ...august, logs: { update: rustLock.replaceAll('(os error 5)', '(os error 32)') } })).toBeNull()
  })

  it('CLI writes a receipt and exits zero only on a confirmed match', () => {
    const root = mkdtempSync(path.join(os.tmpdir(), 'known-install-'))

    try {
      mkdirSync(path.join(root, 'logs'))
      writeFileSync(path.join(root, 'shas.json'), '\uFEFF' + JSON.stringify({ old: base.commit, current: 'f'.repeat(40), old_ref: 'v2026.3.12' }))
      writeFileSync(path.join(root, 'logs/update.log'), lockedLog)
      const args = [classifier, root, base.installMethod, base.updateMethod, base.error]
      expect(spawnSync(process.execPath, args).status).toBe(0)
      expect(JSON.parse(readFileSync(path.join(root, 'known-failure.json'), 'utf8')).id).toBe('windows-launcher-self-lock')
      writeFileSync(path.join(root, 'logs/update.log'), 'an unrelated failure')
      expect(spawnSync(process.execPath, args).status).toBe(1)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})

it('renders known receipts as footnotes, without suppressing a red job', async () => {
  const modulePath = new URL('../scripts/sandbox/generate-e2e-matrix.mjs', import.meta.url).href
  const { renderMarkdownResults, legId } = await import(/* @vite-ignore */ modulePath)
  const name = 'windows: installer-script -> hermes-update (v2026.3.12 -> HEAD)'
  const artifacts = new Map([[`install-e2e-known-${rules[0].id}--${legId(name)}`, 42]])
  const known = renderMarkdownResults([{ name: name + ' / e2e', conclusion: 'success' }], [], artifacts)
  expect(known).toContain('0 passed, 0 failed, 1 known failures')
  expect(known).toContain('known [^1]')
  expect(known).toContain(`[^1]: **${rules[0].title}.**`)
  const failed = renderMarkdownResults([{ name: name + ' / e2e', conclusion: 'failure' }], [], artifacts)
  expect(failed).toContain('0 passed, 1 failed, 0 known failures')
  expect(failed).not.toContain('known [^1]')
  const passed = renderMarkdownResults([{ name: name + ' / e2e', conclusion: 'success' }])
  expect(passed).toContain('1 passed, 0 failed, 0 known failures')
})
