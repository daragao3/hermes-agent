# Confirmed historical upgrade limitations

These failures cannot be repaired by changing the update target: the failing code is already loaded from the starting release. The workflow still executes each original update path. Only a match on the exact starting commit, method pair, failed assertion, and fresh log signatures produces a non-red known-failure receipt. Other errors still fail. The results table shows matched cases as `known [n]`, with the explanation and evidence in a footnote at the bottom. These cases are counted separately from passed upgrades.

The machine-readable rules in `e2e-assets/known-failures.json` own the matcher and report footnote text. This document explains their historical evidence. Logs are rotated before each attempt so an earlier failure cannot classify a later one.

## Windows launcher self-lock

Classification: **unfixable in the update target for the exact released `hermes.exe update` path**.

| Starting release | Released commit | Install → update | Verified failing job |
|---|---|---|---|
| `v2026.3.12` | `a370ab8391ca5f8de7ebbc449f05cb0df36ade7c` | `installer-script` → `hermes-update` | [101514756800](https://github.com/ethernet8023/hermes-agent/actions/runs/34043635705/job/101514756800) |
| `v2026.4.8` | `86960cdbb0148145890e2ee90b4e157fa899f6e1` | `installer-script` → `hermes-update` | [101514755527](https://github.com/ethernet8023/hermes-agent/actions/runs/34043635705/job/101514755527) |

The running console launcher holds `venv/Scripts/hermes.exe` open. The old updater pulls the new checkout, then asks uv to replace that same executable during an editable install. Windows rejects the replacement with `Access is denied. (os error 5)`. The old updater's ZIP fallback repeats the dependency install and encounters the same lock.

Evidence required: the CLI update phase failed, the traceback identifies the running `hermes.exe/__main__.py`, and uv reports failure to remove that install's `Scripts/hermes.exe` with OS error 5. A generic access-denied error on another file does not match.

The March call is in the released `hermes_cli/main.py:1678-1683`, with the ZIP fallback at `1571-1576`. April calls `_install_python_dependencies_with_optional_fallback`, whose released body at `3295-3321` runs the installs without launcher quarantine. Those function objects were loaded before the checkout changed. May's sampled CLI update passed; do not classify it from this record.

Re-running the installer is a separate tested upgrade route. Invoking the old CLI through its venv Python is a possible recovery route, but is not silently substituted for the console-launcher leg.

## Windows app offers only a manual update for script installs

Classification: **unfixable in the update target for the exact released app-button path**.

Starting releases: `v2026.7.1`, commit `7c1a029553d87c43ecff8a3821336bc95872213b`; and `v2026.8.3`, commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`.

| Install → update | Verified failing job |
|---|---|
| `installer-script` → `hermes-desktop-app-update` | [101514755236](https://github.com/ethernet8023/hermes-agent/actions/runs/34043635705/job/101514755236) |
| `installer-script+desktop` → `hermes-desktop-app-update` | [101514760893](https://github.com/ethernet8023/hermes-agent/actions/runs/34043635705/job/101514760893) |
| `installer-script+desktop` → `open-app-update` | [101514756508](https://github.com/ethernet8023/hermes-agent/actions/runs/34043635705/job/101514756508) |
| all three, from `v2026.8.3` | [35663715738](https://github.com/daragao3/hermes-agent/actions/runs/35663715738) |

These script installs have no staged updater. The released Electron code logs `no staged updater; surfacing manual` and returns `{ ok: true, manual: true, command }`. It does not start an update. Each job's `logs/desktop.log` records that branch followed by `[updates] manual: hermes update`; no target checkout/result signal appears.

The branch is unchanged between the two releases — July's `apps/desktop/electron/main.cjs:2212-2214` is `apps/desktop/electron/main.ts:2891-2894` at `v2026.8.3`. The August jobs reach it the same way and then spend the driver's full poll window waiting for a result file that the manual branch never writes, ending in `update completion signal never appeared`.

**This is not an onboarding failure.** The overlay loop in `launch-from-spec.mjs` succeeds first (`dismissed onboarding overlay`), and the `[overlay] iter N ... click failed` lines that precede it are the loop's designed retry behaviour during the boot window, not a defect. Read past them to the `[updates]` lines in `logs/desktop.log` before classifying.

Evidence required: an app-update leg from this released commit and those explicit manual-update log entries. A hand-off timeout without the manual message is not this limitation. Desktop-installer installs have a different staged-updater path and are not covered by this classification.

## August Windows updater cannot replace a native extension it has already imported

Classification: **unfixable in the update target for the exact released `hermes.exe update` path**.

Starting release: `v2026.8.3`, commit `3c27eb6234bf91b8ceee9e9071591b31e9b148cb`.

| Install → update | Verified failing job |
|---|---|
| `installer-script` → `hermes-update` | [106544714345](https://github.com/daragao3/hermes-agent/actions/runs/35663715738) |
| `installer-script+desktop` → `hermes-update` | [106544714345](https://github.com/daragao3/hermes-agent/actions/runs/35663715738) |

This is the loaded-module analogue of the launcher self-lock above, and it is a *different* file, so the launcher rule deliberately does not match it.

The released updater runs inside a Python process that has already imported `cryptography`, which maps `venv/Lib/site-packages/cryptography/hazmat/bindings/_rust.pyd` into the running interpreter. The update target raises the `cryptography` floor to 50.x (`2b618fe7e5`), so uv must replace that exact `.pyd`. Windows refuses with `Access is denied. (os error 5)`, uv reports `Failed to persist temporary file`, and the editable install exits 2. The extension module belongs to the starting release's process image; nothing in the update target can unload it, and the optional-extras retry re-runs the same install against the same lock.

Evidence required: the CLI update phase failed, uv reports failure to remove/persist that install's `cryptography/hazmat/bindings/_rust.pyd` with OS error 5, and the git update reports `uv.exe ... 'pip', 'install', '-e', '.'` returning exit status 2. An access-denied error on any other file does not match.

Re-running the installer is a separate tested upgrade route.

## Not classified as unfixable

The July desktop-installer → app-update failure was a driver lifetime bug, not a released-updater exception. The driver treated an expected page closure as failure and could exit before Playwright released its launch process. On Windows, inherited pipes delayed the `close` event even after the launch process exited with code 0. Playwright then ran its tree-kill cleanup. The driver now waits independently of the closing page, releases its pipe handles after process exit, and waits for `close` before it exits. [The real July rerun](https://github.com/ethernet8023/hermes-agent/actions/runs/34075042380/job/101599434616) reached the target commit, cleared the update marker, passed the CLI check, and relaunched the app.

The `desktop-installer@latest` **install** legs against a ref older than the published installer are a harness anachronism, not an upgrade limitation, and must not be given a label here. Run [35663715738](https://github.com/daragao3/hermes-agent/actions/runs/35663715738) lost 11 install-phase jobs (macOS dmg ×5, Windows ×6) because the published installer runs `node apps/desktop/scripts/ensure-rolldown-binding.mjs` — added upstream on 2026-09-01 — against a `v2026.8.3` checkout that predates it, so the desktop stage dies `MODULE_NOT_FOUND`. No user meets this: the published installer always clones the repo's current `main`, which carries the script. Only the matrix pairs today's installer with yesterday's tree, because just one installer binary is published and it is always the newest. The class recurs whenever the installer gains a dependency on a file newer than the oldest pinned ref, so the fix belongs in how the matrix pairs installers with refs — or in a presence guard inside the installer (added to this repo's `scripts/install.ps1` and `install.sh`, though the *published* binary is built upstream) — never in a rule in `known-failures.json`. The matcher could not express it anyway: `known-failures.cjs` classifies only `platform === 'windows'` **and** `phase === 'update'`, so install-phase and macOS failures never reach a rule.

Onboarding click failures, zoom drift, native permission dialogs, AutoHotkey window waits, stale update markers, autostash conflicts, network failures, and generic timeouts remain actionable or unclassified until diagnosed. They must not inherit a historical label because they occurred on an old release.

One caution on onboarding specifically: `[overlay] iter N ... click failed` lines are the dismiss loop's **designed** retry behaviour during the boot window, and are routinely followed by `dismissed onboarding overlay`. They are not themselves a failure. Before blaming onboarding, confirm the run never reached `dismissed onboarding overlay`, and read `logs/desktop.log` for what happened after `clicked Update now`.
