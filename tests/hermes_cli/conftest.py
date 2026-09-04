"""Fixtures shared across hermes_cli kanban tests."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture
def restore_purged_modules():
    """Put ``sys.modules`` back the way a HERMES_HOME purge found it.

    The ``isolated_kanban_home*`` fixtures drop every ``hermes_cli*`` /
    ``hermes_state*`` / ``hermes_constants`` module and re-import, which is the
    right way to pick up a changed ``HERMES_HOME``. What they never did is put
    them back, so every test collected *after* those files ran against freshly
    imported duplicates while already-imported test modules still held
    references to the originals.

    pytest imports every test module during collection, up front, so
    ``tests/hermes_cli/test_tools_config.py`` binds ``tools_command`` from the
    original module object.  After the purge,
    ``monkeypatch.setattr("hermes_cli.tools_config._prompt_choice", fake)``
    resolves that string by *importing* — the name is gone, so Python builds a
    **fresh** module object and the patch lands on that one instead.  The
    already-bound ``tools_command`` still reads the original module's globals,
    so the patch silently does nothing and the real interactive/network code
    path runs.  That is what hung ``tests/hermes_cli`` at 83% on
    ``test_configure_all_platforms_configures_selected_tool_missing_provider``.

    Restoring ``sys.modules`` alone is NOT enough, and this is the part that is
    easy to get wrong: ``import a.b as x`` reads ``sys.modules``, while
    ``from a.b import y`` reads the attribute ``b`` on the parent package. Fix
    only the first and half the imports still resolve to the stale copy. Same
    two-step as ``tests/agent/test_verification_stop_caching.py``.
    """
    snapshot = dict(sys.modules)
    yield
    purged = {
        name: module for name, module in snapshot.items()
        if sys.modules.get(name) is not module
    }
    for name, module in purged.items():
        sys.modules[name] = module
    for name, module in purged.items():
        parent_name, _, child = name.rpartition(".")
        if not parent_name:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, child, None) is not module:
            setattr(parent, child, module)


@pytest.fixture
def all_assignees_spawnable(monkeypatch):
    """Pretend every assignee maps to a real Hermes profile.

    Most dispatcher tests use synthetic assignees ("alice", "bob") that
    don't correspond to actual profile directories on disk. Without this
    patch, the dispatcher's profile-exists guard (PR #20105) routes
    those tasks into ``skipped_nonspawnable`` instead of spawning, which
    would break tests that assert spawn behavior.
    """
    from hermes_cli import profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: True)


@pytest.fixture(autouse=True)
def _suppress_concurrent_hermes_gate(request, monkeypatch):
    """Default ``_detect_concurrent_hermes_instances`` to ``[]`` for every test.

    The Windows update path now refuses to proceed when another
    ``hermes.exe`` is detected (issue #26670). On a developer's Windows
    machine running the test suite via ``hermes`` itself, this would
    flag the running agent as a concurrent instance and abort every
    ``cmd_update`` test. Tests that want to exercise the gate explicitly
    re-patch ``_detect_concurrent_hermes_instances`` with their own
    return value — autouse here gives a clean default without touching
    the rest of the suite.

    Tests that need to call the REAL function (e.g. unit tests for the
    helper itself) opt out with ``@pytest.mark.real_concurrent_gate``.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    # raising=False: under pytest's per-test spawn isolation, a concurrent
    # xdist worker importing a module that transitively touches hermes_cli.main
    # can briefly expose a partially-initialized module object here — one where
    # _detect_concurrent_hermes_instances isn't defined yet. A bare setattr
    # would raise AttributeError and error the (unrelated) test. The attribute
    # always exists once main.py finishes importing, so a no-op when it's
    # transiently absent is the correct, race-free default.
    monkeypatch.setattr(
        _cli_main,
        "_detect_concurrent_hermes_instances",
        lambda *_a, **_k: [],
        raising=False,
    )


@pytest.fixture(autouse=True)
def _stub_provider_model_fetch(request, monkeypatch):
    """Default ``cached_provider_model_ids`` to ``[]`` for every test.

    ``list_authenticated_providers`` (and the picker built on it) calls
    ``hermes_cli.models.cached_provider_model_ids`` for every credentialed
    provider. On a cache miss that is a LIVE path: an outbound model-catalog
    fetch per provider, followed by ``_save_provider_models_cache`` ->
    ``utils.atomic_json_write`` -> ``os.fsync`` against the developer's real
    provider-model cache file. Tests that only exercise the *credential* gate
    pay all of it -- measured 13-22s per test in
    ``test_authenticated_providers_exhausted_pool.py``.

    That mattered beyond slowness, and the consequence has since been removed
    at the source. ``--timeout-method=thread`` (pyproject.toml) cannot raise
    into the main thread, so a test crossing the 30s cap used to take the WHOLE
    pytest process down: no summary line, and the reported failure set was
    whatever had accumulated when the run died. Because these tests sat right
    at the cap, the set varied between invocations -- a standing trap for
    anyone taking a ``tests/hermes_cli`` baseline.
    ``tests/_nonfatal_timeout.py`` now makes a cap breach fail one test instead
    of killing the run, so the trap is gone; this stub still matters, because
    keeping these tests far from the cap is what stops them failing at all.

    ``[]`` is the semantically safe default, not merely a fast one: every
    caller already treats an empty result as "live discovery unavailable" and
    falls back to the curated static list (``curated.get(slug, [])``), which is
    exactly what happens offline. The credential gate under test is unaffected.

    Tests that assert on live discovery opt out with
    ``@pytest.mark.real_provider_model_fetch``. Tests needing specific model
    ids keep patching the same attribute themselves -- a per-test
    ``monkeypatch`` runs after this fixture and therefore still wins.
    """
    if request.node.get_closest_marker("real_provider_model_fetch"):
        return
    try:
        from hermes_cli import models as _models
    except Exception:
        return
    # raising=False for the same partially-initialized-module race documented
    # on _suppress_concurrent_hermes_gate above.
    monkeypatch.setattr(
        _models, "cached_provider_model_ids", lambda *_a, **_k: [], raising=False
    )


@pytest.fixture(autouse=True)
def _stub_lazy_feature_refresh(request, monkeypatch):
    """Neutralize ``_refresh_active_lazy_features`` for every test.

    ``cmd_update`` calls it, and it reaches ``tools.lazy_deps`` on the REAL
    interpreter: ``active_features()`` probes all 34 features / 54 specs in
    ``LAZY_DEPS`` via ``importlib.metadata``, each a distribution scan over
    site-packages (2.5s), then ``feature_missing`` re-scans per active feature,
    then ``ensure()`` runs the install path and re-scans again to verify.

    ``test_cmd_update.py`` already stubs ``_venv_pip_install`` so nothing is
    installed for real, but it deliberately left the refresh itself live "so
    the refresh stays observable for the test that asserts on it". No such test
    exists -- no test in that file references the refresh at all -- so the only
    thing still being bought is the scan cost and its side effects.

    Those side effects are the worse half. The refresh issues install commands
    through the ``subprocess.run`` mock these tests install, appending entries
    the git-only ``side_effect`` never anticipated. That desynchronizes
    assertions counting calls (``len(pull_cmds) == 1``) and produced a
    non-deterministic 2-3 failures per run, including a bare ``SystemExit: 2``
    -- failures that vanish when the affected test runs alone.

    Real coverage of the lazy-deps functions lives in
    ``tests/tools/test_lazy_deps.py``, which this directory-scoped fixture does
    not touch. Opt out with ``@pytest.mark.real_lazy_feature_refresh``.
    """
    if request.node.get_closest_marker("real_lazy_feature_refresh"):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    monkeypatch.setattr(
        _cli_main, "_refresh_active_lazy_features", lambda *_a, **_k: None,
        raising=False,
    )


_SEEN_RESUME_HOOKS: set = set()


@pytest.fixture(autouse=True)
def _unarm_gateway_resume_atexit_hook():
    """Never let a test leave a gateway-resume ``atexit`` hook armed.

    ``_cmd_update_impl`` registers ``_resume_windows_gateways_after_update``
    with ``atexit`` so an update that dies partway still restores the gateway
    it paused. In production that is a safety net. In a test process it is a
    live grenade: ``atexit`` hooks fire at INTERPRETER SHUTDOWN, long after
    pytest has torn down every ``monkeypatch`` and restored the real
    ``gateway_windows._spawn_detached``.

    Observed 2026-08-18 -- a ``pytest tests/hermes_cli/`` run printed
    "Starting Windows gateway after update (PID 43828)" *after* its own summary
    line. That was a real detached gateway (gateway-exit-diag.log recorded the
    spawn with ``site='update:windows-cold-start'`` and a parent_chain naming
    the pytest process). It lost the double-run race 7s later and the watchdog
    spawned a replacement, so the test suite restarted production.

    Unconditional and cheap: ``atexit.unregister`` removes every registration
    of the callable and is a no-op when none exist. Tested end-to-end in
    tests/hermes_cli/test_gateway_resume_atexit_leak.py.

    ATTEMPT 1 FAILED and this is why it accumulates. Unregistering only the
    CURRENT ``hermes_cli.main._resume_windows_gateways_after_update`` is not
    enough: the ``isolated_kanban_home*`` fixtures purge and re-import every
    ``hermes_cli*`` module (see ``restore_purged_modules`` above), so the
    session runs through several distinct module objects, each with its own
    distinct function object. ``atexit.unregister`` matches by equality, so a
    hook armed by incarnation #1 is untouched by unregistering incarnation #2's
    function -- verified 2026-08-18, a full-suite run still spawned real
    gateway PID 51880 with the single-incarnation version of this fixture.

    So remember every incarnation seen and unregister them all.
    """
    yield
    import atexit

    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    hook = getattr(_cli_main, "_resume_windows_gateways_after_update", None)
    if hook is not None:
        _SEEN_RESUME_HOOKS.add(hook)
    for seen in _SEEN_RESUME_HOOKS:
        atexit.unregister(seen)


@pytest.fixture(autouse=True)
def _suppress_venv_holder_gate(request, monkeypatch):
    """Default ``_detect_venv_python_processes`` to ``[]`` for every test.

    Sibling of ``_suppress_concurrent_hermes_gate`` above, for the other
    Windows update gate. ``_cmd_update_impl`` calls it once per run (main.py,
    just before the git work) to refuse updating while a venv interpreter
    holds ``.pyd`` files mapped. It walks the REAL host process table:
    ``psutil.process_iter(["pid", "exe", "name", "cmdline", "cwd"])`` plus a
    ``Path(exe).resolve()`` on every entry.

    On a developer box that is not a gate, it is a stall. Measured here: 926
    processes, **7.5-12.3s per call**, once for every test that drives
    ``cmd_update`` — and this directory has seven files that do. The cost has
    no ceiling: ``resolve()`` walks MSIX/WindowsApps reparse points whose
    realpath can stall indefinitely, so under a loaded parallel sweep the tail
    grows without bound. On 2026-08-16 a full ``run_tests_parallel.py`` sweep
    sat at 43.4% for 2h16m inside this call. pytest-timeout printed its
    "+++ Timeout +++" dump and the runner still never advanced, so the
    per-file timeout is no protection — the stub is.

    It escapes every patch these tests install: it takes no ``subprocess``
    route and never consults ``shutil.which``. tests/conftest.py's live-system
    guard does not stop it either, and correctly so — enumerating processes
    reads host state without mutating it, exactly what that guard permits.

    ``[]`` is the "nothing is holding the venv" answer, so the gate becomes a
    no-op and the update flow proceeds — which is what every caller in this
    directory wants. ``test_update_venv_health.py`` owns the gate's real
    coverage and opts out with ``@pytest.mark.real_venv_holder_gate``.
    """
    if request.node.get_closest_marker("real_venv_holder_gate"):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    # raising=False for the same partially-initialized-module race documented
    # on _suppress_concurrent_hermes_gate above.
    monkeypatch.setattr(
        _cli_main,
        "_detect_venv_python_processes",
        lambda *_a, **_k: [],
        raising=False,
    )


@pytest.fixture(autouse=True)
def _suppress_windows_gateway_pause(request, monkeypatch):
    """Neutralize the update flow's Windows gateway pause/resume.

    ``_cmd_update_impl`` brackets the update with
    ``_pause_windows_gateways_for_update`` / ``_resume_windows_gateways_after_update``.
    The pause calls ``find_gateway_pids(all_profiles=True)`` and then
    ``terminate_pid`` on whatever it finds — on a developer box that means a
    unit test can **stop the user's real gateway**, and the resume half will
    happily relaunch processes the test never started. Discovery alone costs
    ~2.2s per ``cmd_update`` call here (24 ``psutil`` ppid lookups through
    ``hermes_cli/gateway.py::_get_parent_pid``, ~91ms each on Windows).

    ``None`` is the honest pause result for "no gateway was paused" — it is
    exactly what the real function returns off-Windows and when discovery finds
    nothing — and the resume is a no-op given that token.

    Opt-out reuses ``real_concurrent_gate`` rather than adding a marker:
    ``test_update_concurrent_quarantine.py`` owns this pair's coverage (it
    calls both directly and asserts on which PIDs get stopped and respawned)
    and already carries that marker file-wide for the sibling gate.
    ``test_update_venv_health.py`` patches both seams itself, so it is
    unaffected either way.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    monkeypatch.setattr(
        _cli_main,
        "_pause_windows_gateways_for_update",
        lambda *_a, **_k: None,
        raising=False,
    )
    monkeypatch.setattr(
        _cli_main,
        "_resume_windows_gateways_after_update",
        lambda *_a, **_k: None,
        raising=False,
    )


class _FakeClock:
    """Proxy the real ``time`` module with a virtual, instantly-advancing clock.

    ``sleep`` banks the requested duration instead of waiting, and ``monotonic``
    / ``time`` report the real reading plus everything banked so far. Every
    other attribute falls through to the real module.

    Advancing the clock rather than making ``sleep`` a plain no-op is the point.
    ``_cmd_update_impl`` contains a poll loop of the form ``deadline =
    _time.monotonic() + timeout; while ...: subprocess.run(...); if
    _time.monotonic() >= deadline: return False; _time.sleep(0.5)``. With a
    no-op sleep and a real clock that becomes a busy loop that re-runs the
    mocked subprocess thousands of times over 0.5s of wall time, inflating the
    call lists these tests assert on. With a banked sleep it exits after one
    iteration, which is the behavior the test intends.
    """

    def __init__(self, real):
        self._real = real
        self._offset = 0.0

    def sleep(self, seconds=0.0):
        try:
            self._offset += max(float(seconds), 0.0)
        except (TypeError, ValueError):
            pass

    def monotonic(self):
        return self._real.monotonic() + self._offset

    def time(self):
        return self._real.time() + self._offset

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def no_update_sleep(monkeypatch):
    """Opt-in: make ``hermes_cli.main`` sleep instantly. Request it by name.

    The post-restart survivor sweep in ``_cmd_update_impl`` sleeps 3.0s
    unconditionally (``main.py:11713``) and another 1.5s after force-killing
    stragglers -- on EVERY test that drives ``cmd_update`` far enough to be
    "behind". Stubbing the gateway-discovery functions does not skip it: the
    3.0s sleep is the first statement inside its own ``try``, before anything
    that consults a PID list.

    This rebinds the module-global ``_time`` name in ``hermes_cli.main``
    (bound once at ``main.py:819``, never shadowed inside ``_cmd_update_impl``)
    rather than patching ``time.sleep`` process-wide. That distinction matters:
    a global patch would reach background threads and, concretely, would break
    ``test_backup.py``, which sleeps a real 1.05s to force distinct timestamps.
    Scoped this way, nothing outside ``hermes_cli.main`` observes a fake clock.

    NOT autouse -- other tests in this directory exercise sleeping code paths in
    ``hermes_cli.main`` on purpose, so files opt in by naming this fixture in
    their own update fixture's signature.
    """
    import time as _real_time

    from hermes_cli import main as _cli_main

    monkeypatch.setattr(_cli_main, "_time", _FakeClock(_real_time), raising=False)
