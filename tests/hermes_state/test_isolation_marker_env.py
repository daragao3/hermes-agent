"""Subprocess-surviving isolation marker (#82770).

``PYTEST_CURRENT_TEST`` / ``PYTEST_VERSION`` are pytest's vars: tests that
spawn children and rebuild the child environment routinely strip them so the
child "looks like a real CLI" — which used to disarm the live-DB guard in the
child at the same moment the child lost the ``HERMES_HOME`` redirect. That
pairing is exactly how fixture rows (dm:123 / chat-1 / wx-chat) landed in a
developer's production state.db.

``HERMES_TEST_ISOLATION`` is Hermes's own marker: the hermetic conftest
exports it (value = the isolation root) before any test module imports, it
inherits into children by default, and ``hermes_state`` honors it as a
test-context signal. These tests pin all three properties.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# NOTE: ``hermes_state`` is deliberately NOT imported here -- the parent process
# never touches it; every assertion below is about a spawned child. It was an
# unused import (ruff F401, which this repo enforces tree-wide with no
# suppressions) and blocked the commit that repaired these probes.
import hermes_state_guard

REPO_ROOT = Path(__file__).resolve().parents[2]

# Each probe below spawns a child that imports ``hermes_state``, which pulls in
# the agent stack: ~9s warm and ~33s cold on this host.  ``_spawn_probe``
# already budgets 60s for that, which the repo-wide 30s pytest cap (pyproject
# addopts) cannot honour -- the cap fires first and the test reads as a hang.
# 180s keeps the child's own 60s ceiling as the real limit.
_child_import_budget = pytest.mark.timeout(180)

_CHILD_PROBE = r"""
import json, os, sys
sys.path.insert(0, {repo!r})
import hermes_state as hs
import hermes_state_guard
fired = False
try:
    hs._ensure_test_isolation(hs._real_platform_state_root() / "state.db")
except RuntimeError:
    fired = True
print(json.dumps({{
    "armed": hermes_state_guard._running_under_pytest(),
    "fired": fired,
}}))
"""


def _spawn_probe(env: dict) -> dict:
    """Run the guard probe in a real child process with exactly *env*."""
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_PROBE.format(repo=str(REPO_ROOT))],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _minimal_env(**extra) -> dict:
    """A rebuilt-from-scratch child env — the residual-bypass pattern."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows needs it
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        # Windows resolves ~ from USERPROFILE (then HOMEDRIVE+HOMEPATH) and
        # never from HOME.  Without them ``Path.home()`` raises "Could not
        # determine home directory" while ``hermes_constants`` is imported --
        # the child dies before it can answer the question under test, and the
        # probe fails for a reason that has nothing to do with the guard.
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "HOMEDRIVE": os.environ.get("HOMEDRIVE", ""),
        "HOMEPATH": os.environ.get("HOMEPATH", ""),
    }
    env = {k: v for k, v in env.items() if v}
    env.update(extra)
    return env


def test_conftest_exports_the_marker():
    """The hermetic conftest must export the marker before tests run."""
    assert os.environ.get("HERMES_TEST_ISOLATION"), (
        "HERMES_TEST_ISOLATION must be exported by tests/conftest.py so "
        "subprocess children inherit a test-context signal that survives "
        "PYTEST_* scrubbing"
    )


def test_marker_alone_reports_test_context(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.setenv("HERMES_TEST_ISOLATION", "/tmp/some-isolation-root")
    assert hermes_state_guard._running_under_pytest() is True


def test_no_signals_reports_production(monkeypatch):
    """Marker absent + PYTEST_* absent = a real user run; guard must not arm
    off the env (ancestry may still arm it in a real child — not this seam)."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.delenv("HERMES_TEST_ISOLATION", raising=False)
    assert hermes_state_guard._running_under_pytest() is False


@_child_import_budget
def test_child_with_rebuilt_env_keeping_marker_refuses_production_db():
    """THE regression: a child whose env was rebuilt from scratch (PYTEST_*
    stripped, HERMES_HOME lost) but which keeps the marker must still refuse
    to open the production state.db."""
    env = _minimal_env(HERMES_TEST_ISOLATION="/tmp/pytest-isolation-root")
    result = _spawn_probe(env)
    assert result["armed"] is True
    assert result["fired"] is True, (
        "guard did not fire in a marker-carrying child aimed at the "
        "production state.db — the #82770 escape is open again"
    )


@_child_import_budget
def test_child_bypass_env_disarms_guard_even_with_marker():
    """The sanctioned escape hatch for children that genuinely need a real
    DB: HERMES_STATE_DB_GUARD_BYPASS=1, not marker-stripping."""
    env = _minimal_env(
        HERMES_TEST_ISOLATION="/tmp/pytest-isolation-root",
        HERMES_STATE_DB_GUARD_BYPASS="1",
    )
    result = _spawn_probe(env)
    assert result["fired"] is False


@_child_import_budget
def test_child_inheriting_full_test_env_refuses_production_db():
    """Default inheritance (env=None equivalent): everything rides along."""
    result = _spawn_probe(dict(os.environ))
    assert result["armed"] is True
    assert result["fired"] is True
