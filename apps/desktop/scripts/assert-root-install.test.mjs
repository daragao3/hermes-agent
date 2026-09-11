import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'vitest'

import {
  BUILD_CRITICAL_PACKAGES as BUILD_CRITICAL,
  requiredPackages,
  checkLockDrift,
  checkRootInstall,
  checkWorkspaceInstall,
  installLooksCurrent
} from '../scripts/assert-root-install.mjs'

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(value), 'utf8')
}

// Minimal stand-in for the real workspace: a root with a lockfile and a hoisted
// vite, plus apps/desktop with its own manifest.
function makeWorkspace({ manifest = {}, lockPackages = {}, installed = {} } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-assert-root-install-'))
  const pkgDir = path.join(root, 'apps', 'desktop')

  writeJson(path.join(root, 'node_modules', 'vite', 'package.json'), { name: 'vite', version: '8.0.10' })
  writeJson(path.join(pkgDir, 'package.json'), manifest)
  writeJson(path.join(root, 'package-lock.json'), {
    packages: { 'node_modules/vite': { version: '8.0.10' }, ...lockPackages }
  })

  // installed: { "<dir-relative-to-root>/node_modules/<name>": version }
  for (const [where, version] of Object.entries(installed)) {
    writeJson(path.join(root, ...where.split('/'), 'package.json'), { version })
  }

  return { root, pkgDir, cleanup: () => fs.rmSync(root, { recursive: true, force: true }) }
}

test('checkLockDrift passes when the installed version matches the lockfile', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { '@assistant-ui/react-streamdown': '^0.3.4' } },
    lockPackages: { 'apps/desktop/node_modules/@assistant-ui/react-streamdown': { version: '0.3.5' } },
    installed: { 'apps/desktop/node_modules/@assistant-ui/react-streamdown': '0.3.5' }
  })
  try {
    assert.deepEqual(checkLockDrift(ws.root, ws.pkgDir), { ok: true, drift: [] })
  } finally {
    ws.cleanup()
  }
})

// The 2026-07-22 regression: lockfile bumped by a merge, tree never re-synced.
test('checkLockDrift reports a stale installed dependency', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { '@assistant-ui/react-streamdown': '^0.3.4' } },
    lockPackages: { 'apps/desktop/node_modules/@assistant-ui/react-streamdown': { version: '0.3.5' } },
    installed: { 'apps/desktop/node_modules/@assistant-ui/react-streamdown': '0.1.11' }
  })
  try {
    const result = checkLockDrift(ws.root, ws.pkgDir)
    assert.equal(result.ok, false)
    assert.deepEqual(result.drift, [
      { name: '@assistant-ui/react-streamdown', installed: '0.1.11', locked: '0.3.5' }
    ])

    const message = checkWorkspaceInstall(ws.root, ws.pkgDir).error
    assert.match(message, /@assistant-ui\/react-streamdown/)
    assert.match(message, /installed 0\.1\.11/)
    assert.match(message, /lockfile 0\.3\.5/)
    assert.match(message, /npm install/)
  } finally {
    ws.cleanup()
  }
})

test('checkLockDrift reports a declared dependency that is not installed at all', () => {
  const ws = makeWorkspace({
    manifest: { devDependencies: { katex: '^0.16.45' } },
    lockPackages: { 'node_modules/katex': { version: '0.16.45' } }
  })
  try {
    const result = checkLockDrift(ws.root, ws.pkgDir)
    assert.equal(result.ok, false)
    assert.deepEqual(result.drift, [{ name: 'katex', installed: null, locked: '0.16.45' }])
    assert.match(checkWorkspaceInstall(ws.root, ws.pkgDir).error, /katex\s+not installed\s+lockfile 0\.16\.45/)
  } finally {
    ws.cleanup()
  }
})

// npm hoists most deps to the workspace root, so the nearest-node_modules walk
// has to find them there.
test('checkLockDrift resolves dependencies hoisted to the workspace root', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { react: '^19.2.5' } },
    lockPackages: { 'node_modules/react': { version: '19.2.7' } },
    installed: { 'node_modules/react': '19.2.7' }
  })
  try {
    assert.equal(checkLockDrift(ws.root, ws.pkgDir).ok, true)
  } finally {
    ws.cleanup()
  }
})

// 2026-07-24: a concurrent `npm install` rewrote the lockfile to key
// @assistant-ui/react under apps/desktop/node_modules but npm hoisted the real
// files to the root node_modules; the nested path was absent. Reading the copy
// at the lockfile's key path saw "not installed" and reported drift even though
// the hoisted copy matched exactly. The installed version is the one node
// resolves to, so a hoisted-but-matching copy is not drift.
test('checkLockDrift accepts a package hoisted above its lockfile key', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { '@assistant-ui/react': '^0.14.24' } },
    lockPackages: { 'apps/desktop/node_modules/@assistant-ui/react': { version: '0.14.24' } },
    installed: { 'node_modules/@assistant-ui/react': '0.14.24' }
  })
  try {
    assert.deepEqual(checkLockDrift(ws.root, ws.pkgDir), { ok: true, drift: [] })
  } finally {
    ws.cleanup()
  }
})

// The flip side of the hoist case: a stray nested copy at the wrong version is
// what node actually loads, so it must be reported even though the lockfile
// keys the package (at the right version) higher up.
test('checkLockDrift reports a stray nested copy that shadows the locked one', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { react: '^19.2.5' } },
    lockPackages: { 'node_modules/react': { version: '19.2.7' } },
    installed: {
      'node_modules/react': '19.2.7',
      'apps/desktop/node_modules/react': '18.3.1'
    }
  })
  try {
    const result = checkLockDrift(ws.root, ws.pkgDir)
    assert.equal(result.ok, false)
    assert.deepEqual(result.drift, [{ name: 'react', installed: '18.3.1', locked: '19.2.7' }])
  } finally {
    ws.cleanup()
  }
})

// A nested copy shadows the hoisted one for anything under apps/desktop.
test('checkLockDrift prefers the nested copy over the hoisted one', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { '@types/node': '^22.20.0' } },
    lockPackages: {
      'node_modules/@types/node': { version: '24.0.0' },
      'apps/desktop/node_modules/@types/node': { version: '22.20.1' }
    },
    installed: {
      'node_modules/@types/node': '24.0.0',
      'apps/desktop/node_modules/@types/node': '22.20.1'
    }
  })
  try {
    assert.equal(checkLockDrift(ws.root, ws.pkgDir).ok, true)
  } finally {
    ws.cleanup()
  }
})

// file:../shared shows up as `link: true` with no version to compare.
test('checkLockDrift ignores linked workspace dependencies', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { '@hermes/shared': 'file:../shared' } },
    lockPackages: { 'node_modules/@hermes/shared': { resolved: 'apps/shared', link: true } },
    installed: { 'node_modules/@hermes/shared': '0.0.0' }
  })
  try {
    assert.deepEqual(checkLockDrift(ws.root, ws.pkgDir), { ok: true, drift: [] })
  } finally {
    ws.cleanup()
  }
})

test('checkLockDrift ignores dependencies the lockfile does not know about', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { 'some-unlocked-thing': '^1.0.0' } }
  })
  try {
    assert.deepEqual(checkLockDrift(ws.root, ws.pkgDir), { ok: true, drift: [] })
  } finally {
    ws.cleanup()
  }
})

test('checkRootInstall fails when the root install is missing entirely', () => {
  const ws = makeWorkspace()
  try {
    fs.rmSync(path.join(ws.root, 'node_modules'), { recursive: true, force: true })
    const result = checkRootInstall(ws.root)
    assert.equal(result.ok, false)
    assert.match(result.error, /npm ci/)

    // The root-install failure must win — otherwise every dependency reads as
    // missing and one real problem becomes a wall of noise.
    assert.equal(checkWorkspaceInstall(ws.root, ws.pkgDir).error, result.error)
  } finally {
    ws.cleanup()
  }
})

// The mtime fast path: an install at or after the last lockfile write means
// there is nothing to find, and the ~100 file reads can be skipped.
test('installLooksCurrent is true when the install is newer than the lockfile', () => {
  const ws = makeWorkspace()
  try {
    const lock = path.join(ws.root, 'package-lock.json')
    const hidden = path.join(ws.root, 'node_modules', '.package-lock.json')
    writeJson(hidden, { lockfileVersion: 3, packages: {} })
    const base = new Date('2026-07-22T12:00:00Z')
    fs.utimesSync(lock, base, base)
    fs.utimesSync(hidden, new Date(base.getTime() + 60_000), new Date(base.getTime() + 60_000))
    assert.equal(installLooksCurrent(ws.root), true)
  } finally {
    ws.cleanup()
  }
})

test('installLooksCurrent is false when the lockfile is newer than the install', () => {
  const ws = makeWorkspace()
  try {
    const lock = path.join(ws.root, 'package-lock.json')
    const hidden = path.join(ws.root, 'node_modules', '.package-lock.json')
    writeJson(hidden, { lockfileVersion: 3, packages: {} })
    const base = new Date('2026-07-22T12:00:00Z')
    fs.utimesSync(hidden, base, base)
    // A merge or pull rewrote package-lock.json and nobody re-ran npm install.
    fs.utimesSync(lock, new Date(base.getTime() + 60_000), new Date(base.getTime() + 60_000))
    assert.equal(installLooksCurrent(ws.root), false)
  } finally {
    ws.cleanup()
  }
})

test('installLooksCurrent is false when npm has never written a hidden lockfile', () => {
  const ws = makeWorkspace()
  try {
    assert.equal(installLooksCurrent(ws.root), false)
  } finally {
    ws.cleanup()
  }
})

// The fast path must not swallow drift that the deep check would report.
test('checkWorkspaceInstall skips the deep check when the install is current', () => {
  const ws = makeWorkspace({
    manifest: { dependencies: { katex: '^0.16.45' } },
    lockPackages: { 'node_modules/katex': { version: '0.16.45' } },
    installed: { 'node_modules/katex': '0.15.0' }
  })
  try {
    assert.equal(checkLockDrift(ws.root, ws.pkgDir).ok, false)

    const hidden = path.join(ws.root, 'node_modules', '.package-lock.json')
    writeJson(hidden, { lockfileVersion: 3, packages: {} })
    const base = new Date('2026-07-22T12:00:00Z')
    fs.utimesSync(path.join(ws.root, 'package-lock.json'), base, base)
    fs.utimesSync(hidden, new Date(base.getTime() + 60_000), new Date(base.getTime() + 60_000))

    assert.equal(checkWorkspaceInstall(ws.root, ws.pkgDir).ok, true)
  } finally {
    ws.cleanup()
  }
})

// The guard is only useful if it is quiet on a healthy tree — run the deep
// check (not the mtime fast path) against the real repo, so a false positive
// here fails loudly in CI instead of blocking someone's dev server.
test('checkLockDrift is clean against the real workspace', () => {
  const pkgDir = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
  const root = path.resolve(pkgDir, '..', '..')
  const result = checkLockDrift(root, pkgDir)
  assert.equal(
    result.ok,
    true,
    `unexpected drift: ${result.drift.map(d => `${d.name} ${d.installed} != ${d.locked}`).join(', ')}`
  )
})

// Build a throwaway repo shaped like this one: an app workspace whose
// dependencies are hoisted to the repo root, which is what the guard walks.
// `manifest` is merged into the app's package.json so tests can declare
// dependencies the guard is expected to read.
function makeTree({ rootPackages = BUILD_CRITICAL, react = '19.2.7', reactDom = '19.2.7', manifest = {} } = {}) {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-assert-root-'))
  const appDir = path.join(tempRoot, 'apps', 'desktop')
  fs.mkdirSync(appDir, { recursive: true })
  fs.writeFileSync(path.join(appDir, 'package.json'), JSON.stringify({ name: 'desktop', ...manifest }), 'utf8')

  const writePackage = (name, version) => {
    const dir = path.join(tempRoot, 'node_modules', name)
    fs.mkdirSync(dir, { recursive: true })
    fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name, version }), 'utf8')
  }
  for (const name of rootPackages) writePackage(name, '1.0.0')
  if (react !== null) writePackage('react', react)
  if (reactDom !== null) writePackage('react-dom', reactDom)

  return { tempRoot, appDir }
}

test('checkRootInstall passes on a complete root install', () => {
  const { tempRoot, appDir } = makeTree()
  try {
    assert.deepEqual(checkRootInstall(appDir, tempRoot), { ok: true })
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

// The regression this guard was widened for: the updater's partial `npm install`
// left katex out while vite was present, so the old vite-only check passed and
// the build died on an unresolved `katex/dist/katex.min.css` (#86443).
test('checkRootInstall fails when katex is missing but vite is present', () => {
  const { tempRoot, appDir } = makeTree({
    rootPackages: BUILD_CRITICAL.filter(name => name !== 'katex')
  })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /katex/)
    assert.match(result.error, /npm ci/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('checkRootInstall fails when electron is missing', () => {
  const { tempRoot, appDir } = makeTree({
    rootPackages: BUILD_CRITICAL.filter(name => name !== 'electron')
  })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /electron/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('checkRootInstall reports every missing package at once', () => {
  const { tempRoot, appDir } = makeTree({ rootPackages: ['vite'] })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    for (const name of ['katex', 'electron', 'electron-builder']) {
      assert.match(result.error, new RegExp(name))
    }
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

// The original guard's only check — kept, so widening coverage cannot silently
// drop the case it already handled.
test('checkRootInstall still fails when vite is missing', () => {
  const { tempRoot, appDir } = makeTree({
    rootPackages: BUILD_CRITICAL.filter(name => name !== 'vite')
  })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /vite/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('checkRootInstall fails on a react/react-dom version split', () => {
  const { tempRoot, appDir } = makeTree({ react: '19.2.7', reactDom: '19.1.0' })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /#527/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

// A package installed into the app's own node_modules rather than hoisted to the
// root is still installed. The guard walks upward like Node does, so it must not
// insist on the hoisted location.
test('checkRootInstall accepts a package nested in the app workspace', () => {
  const { tempRoot, appDir } = makeTree({
    rootPackages: BUILD_CRITICAL.filter(name => name !== 'katex')
  })
  const nested = path.join(appDir, 'node_modules', 'katex')
  fs.mkdirSync(nested, { recursive: true })
  fs.writeFileSync(path.join(nested, 'package.json'), JSON.stringify({ name: 'katex' }), 'utf8')
  try {
    assert.deepEqual(checkRootInstall(appDir, tempRoot), { ok: true })
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

// The class, not the four instances: the floor list is what a partial install
// has been *seen* to drop, but any declared non-optional package can be the one
// missing next (`vite.config.ts` imports `@rolldown/plugin-babel`, which the
// floor never named). The guard must read the manifest so the list cannot drift
// behind a new import.
test('checkRootInstall fails when a declared devDependency outside the floor is missing', () => {
  const { tempRoot, appDir } = makeTree({
    manifest: { devDependencies: { '@rolldown/plugin-babel': '1.0.0', esbuild: '1.0.0' } },
    rootPackages: [...BUILD_CRITICAL, 'esbuild']
  })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /@rolldown\/plugin-babel/)
    assert.doesNotMatch(result.error, /esbuild/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('checkRootInstall fails when a declared runtime dependency is missing', () => {
  const { tempRoot, appDir } = makeTree({
    manifest: { dependencies: { '@vscode/codicons': '1.0.0' } }
  })
  try {
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /@vscode\/codicons/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

// npm skips optionalDependencies legitimately (platform-gated natives), so an
// absent optional package is not a partial install.
test('checkRootInstall ignores missing optionalDependencies', () => {
  const { tempRoot, appDir } = makeTree({
    manifest: { optionalDependencies: { 'get-windows': '9.3.0' } }
  })
  try {
    assert.deepEqual(checkRootInstall(appDir, tempRoot), { ok: true })
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('checkRootInstall passes when every declared package is installed', () => {
  const { tempRoot, appDir } = makeTree({
    manifest: { dependencies: { '@scope/pkg': '1.0.0' }, devDependencies: { esbuild: '1.0.0' } },
    rootPackages: [...BUILD_CRITICAL, '@scope/pkg', 'esbuild']
  })
  try {
    assert.deepEqual(checkRootInstall(appDir, tempRoot), { ok: true })
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

// The floor is unconditional: a manifest the guard cannot parse must not turn
// the check off.
test('checkRootInstall keeps the floor when the manifest is unreadable', () => {
  const { tempRoot, appDir } = makeTree({ rootPackages: ['vite'] })
  fs.writeFileSync(path.join(appDir, 'package.json'), '{not json', 'utf8')
  try {
    assert.deepEqual(requiredPackages(appDir), [])
    const result = checkRootInstall(appDir, tempRoot)
    assert.equal(result.ok, false)
    assert.match(result.error, /katex/)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})
