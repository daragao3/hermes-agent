"""Fixtures shared across hermes_cli kanban tests."""

from __future__ import annotations

import pytest


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
