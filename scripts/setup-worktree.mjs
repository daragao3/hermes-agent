#!/usr/bin/env node
// Set up a fresh git worktree so apps/desktop tests + typecheck run with no
// manual node_modules junctions.
//
// Why this is needed at all: apps/desktop pins older majors of several deps
// than the repo root and the sibling `web` workspace — @types/node ^22 (root
// 24), @nous-research/ui ^0.13 (root 0.16, web 0.18), undici-types — so npm
// *must* nest them under apps/desktop/node_modules. This is not lockfile cruft:
// a from-scratch `npm install` resolves them to the exact same nested spots,
// because the versions genuinely conflict and cannot be hoisted.
//
// A git worktree lives under .claude/worktrees/<name>/. Node resolves a bare
// import by walking node_modules upward from the requiring file, so from
// <worktree>/apps/desktop it reaches <repo>/node_modules but never
// <repo>/apps/desktop/node_modules (that is a sibling, not an ancestor). The
// pinned nested versions are therefore invisible to a worktree, and ~11 UI test
// files fail to resolve @assistant-ui/* (plus @nous-research/ui etc.). The old
// workaround junctioned four scopes into the worktree by hand; this replaces
// that with a real per-worktree install, which nests those deps under the
// worktree's OWN apps/desktop/node_modules where they resolve natively.
//
// Matches CI (.github/workflows/js-tests.yml): `npm ci --ignore-scripts`.
// --ignore-scripts skips the Electron download and the native node-pty rebuild.
// The vitest suite needs neither, and requiring a C++ build toolchain in every
// worktree would defeat the point.
//
// Idempotent: a no-op when the workspace is already installed and in sync with
// the lockfile, so it is safe to run on every worktree entry — and in the main
// checkout, where it finds an install and does nothing.

import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { checkWorkspaceInstall } from "../apps/desktop/scripts/assert-root-install.mjs"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const desktopDir = join(root, "apps", "desktop")

const status = checkWorkspaceInstall(root, desktopDir)
if (status.ok) {
  console.log("✓ workspace already installed — nothing to do")
  process.exit(0)
}

console.log(`Installing workspace dependencies in ${root}`)
console.log("  npm ci --ignore-scripts\n")

// How npm is spawned, and why it is not simply `spawnSync("npm.cmd", ...)`:
// since the CVE-2024-27980 hardening (node 18.20.2 / 20.12.2 / 21.7.3 and
// every later release) node refuses to spawn a .cmd/.bat file without
// `shell: true`, and reports it as `spawnSync npm.cmd EINVAL` — measured on
// node v24.14.0 and v24.19.0 / Windows 11, 2026-09-14/15. And `shell: true`
// with an args array is itself deprecated (DEP0190: args are concatenated, not
// escaped). So run npm's JS entry point (npm-cli.js) with the node that is
// already running this script: `npm run setup:worktree` hands it over as
// npm_execpath; a direct `node scripts/setup-worktree.mjs` has no such env var,
// so look next to the node binary (Windows layout, then the POSIX prefix
// layout). Only if neither exists fall back to the shell with a single command
// string, which is what a bare `npm ci` in a terminal does anyway.
const npmArgs = ["ci", "--ignore-scripts"]
const nodeDir = dirname(process.execPath)
const npmCli = [
  process.env.npm_execpath,
  join(nodeDir, "node_modules", "npm", "bin", "npm-cli.js"),
  join(nodeDir, "..", "lib", "node_modules", "npm", "bin", "npm-cli.js")
].find((p) => p && existsSync(p))
const result = npmCli
  ? spawnSync(process.execPath, [npmCli, ...npmArgs], { cwd: root, stdio: "inherit" })
  : spawnSync(["npm", ...npmArgs].join(" "), { cwd: root, stdio: "inherit", shell: true })

if (result.error) {
  console.error(`
✗ setup-worktree: could not run npm — ${result.error.message}`)
  process.exit(1)
}

if (result.status !== 0) {
  // The repo .npmrc sets engine-strict=true so that the root package.json
  // `engines.npm` range rejects the npm releases (11.10-11.16) that honour
  // min-release-age but ignore min-release-age-exclude. That same flag also
  // makes npm refuse any DEPENDENCY whose engines range this node does not
  // satisfy (2026-09-14: jsdom@30.0.1 wants ^24.15.0, the box had v24.14.0).
  // The fix for that is a newer node, not `--engine-strict=false`: passing the
  // override here would silently disable the npm-version guard the .npmrc
  // exists for.
  console.error(
    `
✗ setup-worktree: npm ci exited ${result.status ?? "by signal"}.` +
      `
  If npm reported EBADENGINE for a dependency, this node (${process.version}) is older` +
      `
  than the lockfile requires — upgrade node. Do not set engine-strict=false: it would` +
      `
  also lift the npm-version guard in .npmrc (see the comment there).`
  )
  process.exit(result.status ?? 1)
}

// Confirm the install actually resolved the drift the guard was complaining
// about, so a green exit here is a real signal and not just "npm succeeded".
const after = checkWorkspaceInstall(root, desktopDir)
if (!after.ok) {
  console.error(`\n✗ setup-worktree: install finished but the workspace still looks wrong:\n${after.error}`)
  process.exit(1)
}

console.log("\n✓ workspace ready — run apps/desktop tests with: cd apps/desktop && npx vitest run")
process.exit(0)
