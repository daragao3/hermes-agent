import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest

from gateway.config import PlatformConfig
from hermes_cli import _subprocess_compat as capture
from plugins.platforms.whatsapp import adapter as wa


def test_passive_dependency_check_never_spawns(monkeypatch):
    monkeypatch.setattr(wa, "node_executable_present", lambda name: name == "node")
    run = Mock(side_effect=AssertionError("passive probe spawned"))
    monkeypatch.setattr(wa.subprocess, "run", run)
    assert wa.whatsapp_deps_available()
    run.assert_not_called()


@pytest.mark.parametrize("verified", [False, True])
def test_port_kill_retains_identity_guard_with_windows_budget(monkeypatch, verified):
    monkeypatch.setattr(wa, "_IS_WINDOWS", True)
    monkeypatch.setattr(wa, "_listener_pids_on_port", lambda port: [456])
    monkeypatch.setattr(wa, "_pid_looks_like_node_bridge", lambda pid: verified)
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(wa.subprocess, "run", run)
    wa._kill_port_process(9999)
    if verified:
        assert run.call_args.args[0] == ["taskkill", "/PID", "456", "/F"]
        assert run.call_args.kwargs["timeout"] == 30
    else:
        run.assert_not_called()


def test_npm_capture_and_fresh_dependency_stamp(tmp_path, monkeypatch):
    adapter = wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={"session_path": str(tmp_path / "session")}))
    (tmp_path / "package.json").write_text('{"name":"fake"}', encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(wa, "find_node_executable", lambda name: "fake-npm.cmd")
    run = create_autospec(capture.run_text_capture)
    run.return_value = subprocess.CompletedProcess([], 0, "installed", "")
    monkeypatch.setattr(capture, "run_text_capture", run)
    assert adapter._ensure_bridge_deps(tmp_path)
    assert run.call_args.args[0] == ["fake-npm.cmd", "install", "--silent"]
    assert run.call_args.kwargs["timeout"] == 300
    assert adapter._ensure_bridge_deps(tmp_path)
    run.assert_called_once()
    (tmp_path / "package.json").write_text('{"name":"changed"}', encoding="utf-8")
    assert adapter._ensure_bridge_deps(tmp_path)
    assert run.call_count == 2


def test_bridge_log_rotates_only_above_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_BRIDGE_LOG_MAX_BYTES", "4")
    log = tmp_path / "bridge.log"
    log.write_text("1234", encoding="utf-8")
    wa._rotate_bridge_log_if_large(log)
    assert log.read_text() == "1234"
    log.write_text("12345", encoding="utf-8")
    wa._rotate_bridge_log_if_large(log)
    assert not log.exists()
    assert (tmp_path / "bridge.log.1").read_text() == "12345"


@pytest.mark.asyncio
async def test_connect_waits_for_port_then_rotates_before_mocked_spawn(tmp_path, monkeypatch):
    adapter = wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={
        "session_path": str(tmp_path / "session"), "bridge_script": str(tmp_path / "bridge.js")}))
    trace = []
    for name in ["_preflight", "_ensure_bridge_deps", "_acquire_platform_lock"]:
        monkeypatch.setattr(adapter, name, Mock(return_value=True))
    monkeypatch.setattr(adapter, "_reuse_running_bridge", AsyncMock(return_value=False))
    monkeypatch.setattr(wa, "_kill_stale_bridge_by_pidfile", Mock())
    monkeypatch.setattr(wa, "_kill_port_process", Mock())
    async def wait(port):
        trace.append("wait")
        return True
    monkeypatch.setattr(wa, "_wait_for_port_release", wait)
    monkeypatch.setattr(wa, "_rotate_bridge_log_if_large", lambda path: trace.append("rotate"))
    def spawn(*args, **kwargs):
        trace.append("spawn")
        return SimpleNamespace(pid=456)
    monkeypatch.setattr(wa.subprocess, "Popen", spawn)
    monkeypatch.setattr(wa, "_write_bridge_pidfile", Mock())
    monkeypatch.setattr(wa, "find_node_executable", lambda name: "fake-node.exe")
    monkeypatch.setattr(adapter, "_wait_for_bridge", AsyncMock(return_value=True))
    monkeypatch.setattr(adapter, "_attach_to_bridge", lambda proc: setattr(adapter, "_running", True))
    monkeypatch.setattr(adapter, "_wire_plugin_handlers", Mock())
    try:
        assert await adapter.connect()
        assert trace == ["wait", "rotate", "spawn"]
    finally:
        adapter._close_bridge_log()
