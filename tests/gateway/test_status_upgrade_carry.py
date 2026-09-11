"""Status carry integration: no process termination or live home mutation."""
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gateway import status


@pytest.fixture(autouse=True)
def no_real_termination(monkeypatch):
    monkeypatch.setattr(status, "write_diag", Mock())
    monkeypatch.setattr(status.os, "kill", Mock(side_effect=AssertionError("real kill forbidden")))
    monkeypatch.setattr(status, "_IS_WINDOWS", True)


@pytest.mark.parametrize("alive", [False, True])
def test_guarded_taskkill_timeout_uses_liveness_not_child_exit(monkeypatch, alive):
    monkeypatch.setattr(status, "_get_process_start_time", lambda pid: 123)
    monkeypatch.setattr(status, "_pid_exists", lambda pid: alive)
    monkeypatch.setattr(status, "_TASKKILL_VERIFY_TIMEOUT_S", 0)
    run = Mock(side_effect=subprocess.TimeoutExpired("taskkill", 30))
    monkeypatch.setattr(status.subprocess, "run", run)
    if alive:
        with pytest.raises(OSError, match="still alive"):
            status.terminate_pid(987654, force=True, expected_start_time=123, reason="drain expired")
    else:
        status.terminate_pid(987654, force=True, expected_start_time=123, reason="drain expired")
    assert run.call_args.kwargs["timeout"] == 30
    assert status.write_diag.call_args.kwargs["reason"] == "drain expired"
    status.os.kill.assert_not_called()


@pytest.mark.parametrize("expected", [None, 999])
def test_identity_refusal_precedes_kill_and_termination_event(monkeypatch, expected):
    monkeypatch.setattr(status, "_get_process_start_time", lambda pid: 123)
    run = Mock()
    monkeypatch.setattr(status.subprocess, "run", run)
    with pytest.raises(OSError, match="refusing"):
        status.terminate_pid(987654, force=True, expected_start_time=expected)
    run.assert_not_called()
    status.os.kill.assert_not_called()
    status.write_diag.assert_not_called()


@pytest.mark.parametrize("handle,error,wait,alive", [
    (0, 87, 0, False), (0, 5, 0, True), (0, 6, 0, True),
    (1, 0, 0, False), (1, 0, 258, True), (1, 0, 0xFFFFFFFF, True),
])
def test_native_probe_only_reports_dead_on_definite_os_evidence(monkeypatch, handle, error, wait, alive):
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=handle),
        GetLastError=Mock(return_value=error), WaitForSingleObject=Mock(return_value=wait),
        CloseHandle=Mock())
    fake = SimpleNamespace(windll=SimpleNamespace(kernel32=kernel), c_void_p=object, c_uint=object)
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    assert status._pid_exists_win32_ctypes(987654) is alive
    assert kernel.CloseHandle.call_count == bool(handle)
    status.os.kill.assert_not_called()


def test_failed_psutil_falls_through_to_native_probe(monkeypatch):
    broken = SimpleNamespace(Process=Mock(side_effect=RuntimeError("denied")),
        pid_exists=Mock(side_effect=RuntimeError("denied")), STATUS_ZOMBIE="zombie")
    monkeypatch.setitem(sys.modules, "psutil", broken)
    native = Mock(return_value=True)
    monkeypatch.setattr(status, "_pid_exists_win32_ctypes", native)
    assert status.pid_exists(987654) is True
    native.assert_called_once_with(987654)
    status.os.kill.assert_not_called()


def test_confirmed_active_unreadable_lock_never_deletes_pid_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(status, "is_gateway_runtime_lock_active", lambda path: True)
    monkeypatch.setattr(status, "_read_pid_record", lambda path: None)
    monkeypatch.setattr(status, "_read_gateway_lock_record", lambda path: {"locked": True})
    cleanup = Mock()
    monkeypatch.setattr(status, "_cleanup_invalid_pid_path", cleanup)
    assert status.get_running_pid(tmp_path / "gateway.pid") is None
    cleanup.assert_not_called()


def test_recheck_does_not_remove_new_lock_owner(monkeypatch, tmp_path):
    path = tmp_path / "identity.lock"
    old, new = {"pid": 987654, "start_time": 10}, {"pid": 987655, "start_time": 20}
    path.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(status, "_get_scope_lock_path", lambda *args: path)
    monkeypatch.setattr(status, "_scoped_lock_record_is_stale", lambda *args: False)
    monkeypatch.setattr(status.time, "sleep", lambda delay: path.write_text(json.dumps(new), encoding="utf-8"))
    acquired, owner = status.acquire_scoped_lock("test", "identity", pid_recheck_after_seconds=2)
    assert acquired is False and owner == new
    assert json.loads(path.read_text()) == new
