import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hermes_cli import gateway as gw
from gateway import status


def test_cleanup_removes_only_dead_owned_records_and_preserves_unknown(tmp_path, monkeypatch):
    pid = tmp_path / "gateway.pid"
    lock = tmp_path / "gateway.lock"
    scope = tmp_path / "scope"
    scope.mkdir()
    monkeypatch.setattr(status, "_get_pid_path", lambda: pid)
    monkeypatch.setattr(status, "_get_gateway_lock_path", lambda path: lock)
    monkeypatch.setattr(status, "_get_lock_dir", lambda: scope)
    monkeypatch.setattr(status, "_pid_exists", lambda owner: owner == 20)
    pid.write_text("10", encoding="utf-8")
    lock.write_text(json.dumps({"pid": 20}), encoding="utf-8")
    for name, value in {"dead.lock": {"pid": 30}, "unknown.lock": {}, "invalid.lock": {"pid": True}}.items():
        (scope / name).write_text(json.dumps(value), encoding="utf-8")
    assert set(gw.cleanup_gateway_state_files()) == {"gateway.pid", "dead.lock"}
    assert lock.exists() and (scope / "unknown.lock").exists() and (scope / "invalid.lock").exists()


def test_cleanup_preserves_replacement_owner_during_liveness_probe(tmp_path, monkeypatch):
    pid = tmp_path / "gateway.pid"
    pid.write_text(json.dumps({"pid": 10}), encoding="utf-8")
    monkeypatch.setattr(status, "_get_pid_path", lambda: pid)
    monkeypatch.setattr(status, "_get_gateway_lock_path", lambda path: tmp_path / "absent")
    monkeypatch.setattr(status, "_get_lock_dir", lambda: tmp_path / "scope")
    def probe(owner):
        pid.write_text(json.dumps({"pid": 20}), encoding="utf-8")
        return False
    monkeypatch.setattr(status, "_pid_exists", probe)
    assert gw.cleanup_gateway_state_files() == []
    assert json.loads(pid.read_text())["pid"] == 20


@pytest.mark.real_gateway_pid_scan
def test_windows_record_formats_share_strict_runtime_matching(monkeypatch, tmp_path):
    monkeypatch.setattr(gw, "is_windows", lambda: True)
    monkeypatch.setattr(gw, "_get_ancestor_pids", lambda: set())
    monkeypatch.setattr(gw, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(gw, "_profile_arg", lambda *a: "")
    monkeypatch.setattr(gw, "_filter_venv_launcher_stubs", lambda pids: pids)
    listing = """CommandLine : "C:\\app\\hermes.exe" gateway run
ProcessId : 101
CommandLine=python -m hermes_cli.main gateway run
ProcessId=102
CommandLine : "C:\\app\\hermes.exe" gateway status
ProcessId : 103
"""
    monkeypatch.setattr(gw, "_windows_process_listing", lambda: listing)
    assert gw._scan_gateway_pids(set()) == [101, 102]


def test_detached_launch_pins_profile_root_and_closes_parent_handles(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(gw, "get_hermes_home", lambda: tmp_path / "profile")
    monkeypatch.setattr(gw, "installed_package_root", lambda: tmp_path / "installed")
    monkeypatch.setattr(gw, "_gateway_run_command", lambda: ["python.exe", "-m", "hermes_cli.main", "--profile", "main", "gateway", "run", "--replace"])
    popen = Mock(return_value=SimpleNamespace(pid=789))
    monkeypatch.setattr(gw.subprocess, "Popen", popen)
    assert gw.launch_gateway_detached() == 789
    call = popen.call_args
    assert call.args[0][-4:] == ["--profile", "main", "gateway", "run"]
    assert call.kwargs["cwd"] == str(tmp_path / "installed")
    assert call.kwargs["env"]["HERMES_HOME"] == str(tmp_path / "profile")
    assert call.kwargs["env"]["HERMES_GATEWAY_DETACHED"] == "1"
    assert call.kwargs["stdout"].closed and call.kwargs["stderr"].closed


@pytest.mark.parametrize("failure,expected", [(None, "DONE"), (SystemExit(2), "EXIT 2"), (RuntimeError("failed"), "FAILED")])
def test_restart_claim_wraps_every_body_outcome(monkeypatch, failure, expected):
    from hermes_cli import gateway_restart_claim
    claim = Mock()
    trace = []
    monkeypatch.setattr(gw, "_refuse_from_inside_gateway", lambda *a: None)
    monkeypatch.setattr(gw, "_safe_find_gateway_pids", lambda: [456])
    def open_claim(**kwargs):
        trace.append("open")
        assert kwargs["reason"] == "upgrade"
        return claim
    monkeypatch.setattr(gateway_restart_claim, "guard_and_open", open_claim)
    def body(args):
        trace.append("body")
        if failure is not None:
            raise failure
    monkeypatch.setattr(gw, "_gateway_restart_subcommand", body)
    args = SimpleNamespace(reason="upgrade")
    if failure is None:
        gw._cmd_restart(args)
    else:
        with pytest.raises(type(failure)):
            gw._cmd_restart(args)
    assert trace == ["open", "body"]
    claim.close.assert_called_once_with(outcome=expected, new_pids=[456])


def test_start_diagnostic_precedes_conflict_guard_without_loading_gateway(monkeypatch):
    trace = []
    monkeypatch.setattr(gw, "_guard_official_docker_root_gateway", lambda: trace.append("root"))
    monkeypatch.setattr(gw, "_make_exit_diag", lambda: lambda tag, **kw: trace.append(tag))
    monkeypatch.setattr(gw, "_windows_console_window_attached", lambda: False)
    monkeypatch.setattr(gw, "_windows_gateway_breakaway_state", lambda: False)
    monkeypatch.setattr(gw, "_windows_gateway_should_absorb_console_controls", lambda: False)
    def stop(**kwargs):
        trace.append("guard")
        raise RuntimeError("stop before startup")
    monkeypatch.setattr(gw, "_guard_named_profile_under_multiplexer", stop)
    with pytest.raises(RuntimeError, match="stop before startup"):
        gw.run_gateway()
    assert trace == ["root", "gateway.start", "guard"]
