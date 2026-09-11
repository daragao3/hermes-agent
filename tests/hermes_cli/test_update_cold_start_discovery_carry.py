"""Repeated updater calls must not spawn again before the first child is discoverable."""
import sys
from unittest.mock import Mock
import pytest
from hermes_cli import gateway, gateway_windows, update_cmd, update_cmd_windows as windows

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="native Windows cold-start contract")

@pytest.fixture
def cold_start(monkeypatch):
    monkeypatch.setattr(windows, "_COLD_START_SPAWNED_AT", None)
    monkeypatch.setattr(windows, "_COLD_START_PID", None)
    monkeypatch.setattr(gateway, "find_gateway_pids", lambda **kw: [])
    monkeypatch.setattr(update_cmd, "_desktop_owns_gateway_lifecycle", lambda: False)
    spawn = Mock(return_value=4242)
    ready = Mock(return_value=[])
    monkeypatch.setattr(gateway_windows, "_spawn_detached", spawn)
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", ready)
    monkeypatch.setattr(gateway_windows, "_write_start_attestation", Mock())
    return spawn, ready

def test_repeated_failed_readiness_does_not_duplicate_spawn(cold_start):
    spawn, ready = cold_start
    for _ in range(2):
        with pytest.raises(RuntimeError, match="did not become ready"):
            windows._cold_start_windows_gateway_after_update()
    spawn.assert_called_once_with(reason="update:windows-cold-start")
    assert ready.call_count == 2

def test_late_ready_child_is_accepted_without_another_spawn(cold_start):
    spawn, ready = cold_start
    with pytest.raises(RuntimeError, match="did not become ready"):
        windows._cold_start_windows_gateway_after_update()
    ready.return_value = [4242]
    assert windows._cold_start_windows_gateway_after_update() is True
    assert spawn.call_count == 1

def test_expired_window_allows_new_attempt(cold_start, monkeypatch):
    spawn, ready = cold_start
    monkeypatch.setattr(windows, "_COLD_START_SPAWNED_AT", windows._time.monotonic() - 61)
    ready.return_value = [4242]
    assert windows._cold_start_windows_gateway_after_update() is True
    assert spawn.call_count == 1
