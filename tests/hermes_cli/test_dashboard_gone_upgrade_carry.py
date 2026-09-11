"""Retain already-exited cleanup semantics without weakening PID identity."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hermes_cli import dashboard_procs


pytestmark = pytest.mark.windows_only


@pytest.mark.parametrize("exists", [False, True])
def test_failed_taskkill_requires_confirmed_absence(monkeypatch, exists):
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: 123.0)
    monkeypatch.setattr("hermes_cli._subprocess_compat.pid_is_hermes", lambda *a, **kw: True)
    probe = Mock(return_value=exists)
    monkeypatch.setattr("gateway.status.pid_exists", probe)
    kill = Mock(return_value=SimpleNamespace(returncode=128, stdout="", stderr="not found"))
    monkeypatch.setattr(dashboard_procs.subprocess, "run", kill)
    killed, failed = [], []

    dashboard_procs._kill_pids_windows([4242], killed, failed)

    kill.assert_called_once()
    probe.assert_called_once_with(4242)
    assert killed == ([] if exists else [4242])
    assert failed == ([(4242, "not found")] if exists else [])


def test_reused_pid_never_reaches_taskkill(monkeypatch):
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: 123.0)
    monkeypatch.setattr("hermes_cli._subprocess_compat.pid_is_hermes", lambda *a, **kw: False)
    kill = Mock()
    monkeypatch.setattr(dashboard_procs.subprocess, "run", kill)
    killed, failed = [], []

    dashboard_procs._kill_pids_windows([4242], killed, failed)

    kill.assert_not_called()
    assert killed == []
    assert failed == [(4242, "not hermes-owned or process identity changed")]


def test_indeterminate_absence_remains_failure(monkeypatch):
    monkeypatch.setattr("gateway.status.get_process_start_time", lambda pid: 123.0)
    monkeypatch.setattr("hermes_cli._subprocess_compat.pid_is_hermes", lambda *a, **kw: True)
    monkeypatch.setattr("gateway.status.pid_exists", Mock(side_effect=OSError("probe unavailable")))
    monkeypatch.setattr(dashboard_procs.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=128, stdout="", stderr="not found")))
    killed, failed = [], []

    dashboard_procs._kill_pids_windows([4242], killed, failed)

    assert killed == []
    assert len(failed) == 1
