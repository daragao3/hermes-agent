# tests/gateway/test_whatsapp_connect.py: the 8 Windows-lane reds are resolved — by f8d58a66a1, not by CPython 3.13

**Measured 2026-09-18 14:00–14:50Z** on this box (Windows 11, CPU 100% under the
`agent-src-acceptance-ceremony-2e54e03348-20260918` stage-1 run), runner
`scripts/run_tests.sh` with `HERMES_PYTHON=.venv` (CPython 3.13.15, cut over
2026-09-18 04:50Z).

## The question

Eight ids — `TestConnectCleanup::test_releases_lock_when_npm_install_fails`,
`TestDataInitialized::test_no_name_error_when_json_always_fails`,
`TestKillPortProcess` ×4 (`test_uses_netstat_and_taskkill_on_windows`,
`test_psutil_is_the_primary_discovery_path`,
`test_falls_back_to_netstat_when_psutil_is_unavailable`,
`test_netstat_fallback_budget_is_not_five_seconds`),
`TestNoCredsPreflight::test_connect_proceeds_when_creds_present`,
`TestWaitForPortRelease::test_times_out_when_port_stays_bound` — were
adjudicated pre-existing-red in ceremonies 20260917e/g
(`evidence/agent-src-acceptance-20260917g/validation.json`), failed again at
trunk 6e064a8855 on the 3.12 venv at 2026-09-18 ~04:40Z, and then **passed** in
the 250-file stage-1 run of ceremony 973255d3f5 (04:50Z, first run on 3.13.15;
`evidence/agent-src-acceptance-20260918b/validation.json` →
`adjudication.whatsapp_connect`). Did the 3.13 runtime fix them?

## Answer: no. The fix is f8d58a66a1 (landed in 2e54e03348); 3.13 only turned a deterministic red into a coin flip

| Commit under test | Contains f8d58a66a1? | Runtime | Runner result (3 runs) |
|---|---|---|---|
| 2e54e03348 (trunk) | yes | 3.13.15 | 22 passed / 0 failed / 2 skipped — **3 of 3** |
| 973255d3f5 (ceremony candidate) | no | 3.13.15 | green, **the same 8 failed**, green |
| 973255d3f5, bare pytest `-p no:cacheprovider` | no | 3.13.15 | the 8 failed — 3 of 3 (all at peak load) |
| 6e064a8855 | no | 3.12.13 | the 8 failed (51ef1feed3's message; both-pins record) |

Run logs: this session's scratchpad (`wa_run_{1,2,3}.log`, `wa_prefix_run_{1,2,3}.log`);
the pre-fix red run's ids are byte-identical to the adjudicated list above.

## Mechanism

1. `aiohttp.helpers` evaluates `platform.system()` at import
   (`IS_WINDOWS = platform.system() == "Windows"`). The test helper
   `_connect_patches` resolved `patch("aiohttp.ClientSession")` **last**, so on a
   cold process the first aiohttp import happened while `subprocess.run` was
   already a `MagicMock`.
2. `platform.uname()` → `win32_ver()` → `_win32_ver()` asks WMI first
   (`platform._wmi_query("OS", "Version")`), and on `OSError` falls back to
   `sys.getwindowsversion()` **plus `_syscmd_ver()`**, which is
   `subprocess.check_output(["ver"])` → `subprocess.run` → the mock →
   `TypeError: expected string or bytes-like object, got 'MagicMock'`.
3. On **3.12** `tests/conftest.py` installs `_offline_wmi_query` (the gh-130727
   stray-thread guard, gated `sys.version_info < (3, 13, 4)`), which refuses the
   OS query unconditionally — so the `ver` shell-out, and the red, were
   deterministic.
4. On **3.13.15** the stub is gated off and the real `_wmi.exec_query` runs. On a
   quiet box it answers and nothing shells out (green); under load it times out
   (`[WinError 258]`, ~2 in 3 raw attempts at CPU 100% today), the first timeout
   sets `platform._wmi = None` for the rest of the process, and the same `ver`
   fallback fires (red). That is the runner's green/red/green above.
5. The one failure became eight because `_AllPatches.__enter__` built its
   `ExitStack` outside the `with` and a raise mid-enter leaked the already-entered
   `Path.exists/mkdir/open` patches into every later test (`Cannot autospec attr
   'exists' … already been mocked out`, bridge.js `FileNotFoundError`, the
   netstat/taskkill `any()` asserts, the `None`-second budget, the port-release
   timeout).

f8d58a66a1 (`claude/both-pins-reds-20260918`, merged as 2e54e03348) pre-imports
aiohttp before `subprocess` is patched and `pop_all()`s only after every patcher
entered, which closes both (1) and (5) regardless of what WMI does. The
`windows-lane-both-pins-reds-19-files-20260918` loops record has the triage;
this note records the runtime question that the 04:50Z ceremony pass raised.

## What ceremony holders should take from this

* A stage-1 pass of this file at a commit **before** 2e54e03348 on 3.13 is not
  evidence that the file was fixed there; the file's outcome at such a commit
  depends on a per-process WMI timeout. Everything at or after 2e54e03348 is
  green deterministically (3 of 3 under load) and needs no re-adjudication.
* General shape, for other files: a test that mocks `subprocess.run` (or
  `check_output`) and then triggers the **first** `platform.system()` /
  `platform.uname()` / `platform.win32_ver()` of the process is deterministic red
  on 3.12 (conftest WMI stub) and load-flaky on ≥ 3.13.4 (real WMI, 258 timeout
  under load). Fix the test by warming `platform.uname()` or importing the lazy
  module before the mock; never widen the mock or re-enable the stub for 3.13.

## Addendum 2026-09-18 (sweep): no other test file has this shape

**Question.** Does any other file under `tests/` mock `subprocess.run` /
`check_output` / `Popen` while the pytest process's first
`platform.uname()` / `win32_ver()` fires — the shape that made this file a
per-process coin flip on 3.13.15?

**Method** (trunk 009454192e, venv CPython 3.13.15, host at 100% CPU with
~70 foreign python processes, 17:44–19:44Z).

1. Candidates: every test file that patches a real subprocess seam —
   `patch("…subprocess.run")` / `patch.object(subprocess, "run")` /
   `monkeypatch.setattr(subprocess, …)` / module-qualified forms
   (`plugins.platforms.whatsapp.adapter.subprocess.run`) / the alias form
   `import subprocess as _sp; setattr(_sp, "Popen", …)` — 208 files
   (207 by the literal regex, plus `tests/devflow_delegation/test_agent_tools.py`
   found by the alias grep). No `patch.multiple` / `sys.modules["subprocess"]`
   forms exist. Positive control: the pre-fix 973255d3f5 copy of this file,
   run as `tests/gateway/test_zz_probe_wa_prefix.py`.
2. Import-time `platform.*` callers, by AST (module/class body, not inside a
   def) over site-packages: `aiohttp.helpers` (57, 58),
   `aiohttp.web_urldispatcher` (82), `rich._windows` (70), `truststore._api`
   (19, 21), `grpclib.metadata` (18), `modal._output.rich` (57),
   `modal._utils.grpc_utils` (49), `setuptools.msvc` (29),
   `setuptools._distutils.compat.py39` (23), `sounddevice` (76–82),
   `simple_term_menu` (39), `onnxruntime.capi._pybind_state` (14, 22),
   `alibabacloud_credentials.provider.cli_profile` (10). The repo's own
   product code has none. (Calls hidden behind a module-level helper call
   escape this scan; the dynamic probe below is the authoritative filter.)
3. Deterministic reproduction: every candidate file was run through
   `scripts/run_tests.sh <files> -p _wmi_off_probe -p no:cacheprovider`, where
   the untracked probe plugin sets `platform._wmi = None` at import (exactly
   what the 3.12-only conftest stub produced for the OS query: `_wmi_query`
   raises OSError, so the first `uname()` shells out through
   `_syscmd_ver` → `subprocess.check_output(['ver'])`) and wraps
   `platform._syscmd_ver` to log, per call, the current test id and which of
   `subprocess.run/check_output/Popen` is test-patched at that moment (the
   autouse live-system guard's `_guarded_*` wrappers excluded; the log is
   written through `io.open`, because the tests patch `builtins.open`).

**Result.** 208 files: 5105 tests passed, 50 failed, 326 skipped.

| Outcome | Files |
|---|---|
| `_syscmd_ver` fired under a test-patched seam (the shape) | **only the positive control** (`run`+`Popen` MagicMocks → `TypeError … got 'MagicMock'`, the same 8 ids as the adjudicated list, reproduced 2 of 2) |
| First `uname()` fired mid-test but with the live guard / originals in place (real `ver`, ok) | 12: `agent/test_anthropic_adapter`, `cron/test_cron_no_agent`, `cron/test_cron_script`, `cron/test_scheduler_overdue_diagnostics`, `cron/test_script_claim_heartbeat`, `gateway/test_whatsapp_connect` (the fixed file: its warm `import aiohttp` is the event), `gateway/test_whatsapp_stale_bridge`, `plugins/memory/test_hindsight_provider`, `test_bitwarden_secrets`, `tools/test_tirith_security`, `tools/test_voice_mode`, `tui_gateway/test_bot_relay_methods` |
| Never reached `platform.uname()` in the file's process | the other 195 |

The 42 non-control reds are not this shape: none of their failure blocks
mention `platform`, `_syscmd_ver` or a MagicMock, and none logged a
patched-seam event. They are host-load timeouts (`Timeout (>30.0s) from
pytest-timeout` inside real-process spawns / `_wait_for_process` snapshot
waits / a timeout firing inside pytest's own traceback rendering:
`test_local_env_blocklist` ×19, `test_read_extract` ×5, `test_npm_engine` ×3,
`test_terminal_degraded_mode` ×3, `test_resource_limits` ×2,
`test_gui_command`, `test_windows_native_support`, `test_transcription_tools`,
`test_env_probe`, `test_environment_and_runner`, `test_tts_command_providers`,
`test_bot_relay_methods` (1 error); timing bounds under load —
`test_worktree_sync_base` "fetch timed out after 5s",
`test_script_claim_heartbeat` "script did not start", `test_cron_script`
"spawner never wrote the grandchild pid", `test_run_tests_parallel_kill_tree`
spawn-window race, `test_hindsight_provider` 0.25 s bound ×2) plus one
pre-existing trunk red confirmed probe-independent (bare pytest, no plugin):
`tests/computer_use/test_cua_wsl_manifest_path.py` ×2 —
`_wsl_windows_path_to_posix` joins with `os.path` on a Windows host and
returns `/mnt\c\Users\…`; the first of the two tests does not touch
`subprocess` at all. Those load reds were not re-run without the probe;
their attribution is by traceback and by the absence of a patched-seam event.

**Conclusion.** f8d58a66a1 closed the only instance. No test change was
needed from this sweep. For the next occurrence: a Windows red whose
traceback ends in `platform._syscmd_ver` / `check_output(['ver'])` under a
mock is fixed in the test (warm `platform.uname()` or import the lazy module
before the subprocess patch); the probe above turns the 3.13 coin flip into a
deterministic red for bisecting. Loops record:
`platform-under-mocked-subprocess-sweep-20260918`.
