"""Dashboard messaging setup stays bounded and avoids repeated config probes."""

import subprocess

import pytest
from fastapi import HTTPException
from hermes_cli.web_routers import messaging


@pytest.mark.parametrize("timeout", [False, True])
def test_whatsapp_install_uses_bounded_capture(tmp_path, monkeypatch, timeout):
    import hermes_constants
    from hermes_cli import _subprocess_compat
    calls = []
    monkeypatch.setattr(hermes_constants, "find_node_executable", lambda name: "npm.cmd")
    monkeypatch.setattr(hermes_constants, "with_hermes_node_path", lambda: {"TASK_ENV": "test"})
    monkeypatch.setattr(messaging.subprocess, "run", lambda *a, **k: pytest.fail("pipe capture used"))
    def capture(command, **kwargs):
        calls.append((command, kwargs))
        if timeout:
            raise subprocess.TimeoutExpired(command, 300)
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(_subprocess_compat, "run_text_capture", capture)
    if timeout:
        with pytest.raises(HTTPException) as error:
            messaging._ensure_whatsapp_bridge_dependencies(tmp_path)
        assert error.value.status_code == 500
        assert "timed out" in error.value.detail
    else:
        messaging._ensure_whatsapp_bridge_dependencies(tmp_path)
    assert calls[0][0] == ["npm.cmd", "install", "--silent"]
    assert calls[0][1]["env"] == {"TASK_ENV": "test"}
    assert calls[0][1]["timeout"] > 0


def test_platform_batch_shares_one_config_snapshot(monkeypatch):
    import gateway.config
    snapshot = object()
    loads, seen = [], []
    monkeypatch.setattr(gateway.config, "load_gateway_config", lambda: loads.append(True) or snapshot)
    monkeypatch.setattr(messaging, "load_env", lambda: {})
    monkeypatch.setattr(messaging, "read_runtime_status", lambda **kw: None)
    monkeypatch.setattr(messaging, "_messaging_platform_payload", lambda entry, *a, **kw: seen.append(kw.get("gateway_config_shared")) or entry)
    entries = [{"id": "first"}, {"id": "second"}]
    assert messaging._platform_payloads(None, entries) == entries
    assert loads == [True]
    assert seen == [snapshot, snapshot]
