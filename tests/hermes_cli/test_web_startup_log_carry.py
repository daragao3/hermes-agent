"""Startup failures remain in Hermes logs without losing upstream bind exit codes."""
import contextlib
import logging
from types import SimpleNamespace

import pytest

from hermes_cli import web_server as ws


@pytest.mark.parametrize("exit_code,conflict,expected", [(7, False, 7), (1, True, 75)])
def test_startup_exit_logs_and_preserves_bind_translation(monkeypatch, caplog, exit_code, conflict, expected):
    async def startup():
        raise SystemExit(exit_code)

    config = SimpleNamespace(loaded=True, lifespan_class=lambda config: None,
                             get_loop_factory=lambda: None)
    server = SimpleNamespace(capture_signals=contextlib.nullcontext, startup=startup)
    monkeypatch.setattr(ws, "_build_uvicorn_server", lambda *a, **k: (config, server))
    monkeypatch.setattr(ws, "_configure_auth_gate", lambda *a, **k: None)
    monkeypatch.setattr("hermes_cli.nous_auth_keepalive.start_nous_auth_keepalive", lambda: None)
    monkeypatch.setattr("hermes_cli.resource_limits.apply_nofile_soft_limit", lambda: None)
    monkeypatch.setattr(ws, "_apply_ssh_session_token", lambda *a: None)
    monkeypatch.setattr(ws, "_apply_ssh_owner_nonce", lambda *a: None)
    # The preflight succeeds, then a competing binder wins before startup.
    probes = iter([False, conflict])
    monkeypatch.setattr(ws, "_port_bind_conflict", lambda *a: next(probes))
    reports = []
    monkeypatch.setattr(ws, "_report_port_in_use", lambda *a: reports.append(a))
    monkeypatch.setattr(ws, "_on_server_started", lambda *a, **k: pytest.fail("failed startup announced ready"))
    monkeypatch.setattr(ws.app.state, "bound_host", None, raising=False)

    with caplog.at_level(logging.ERROR, logger="hermes_cli.web_server"):
        with pytest.raises(SystemExit) as error:
            ws.start_server(host="127.0.0.1", port=9123, open_browser=False)

    assert error.value.code == expected
    assert "could not start on 127.0.0.1:9123" in caplog.text
    assert f"exit={exit_code}" in caplog.text
    assert reports == ([("127.0.0.1", 9123)] if conflict else [])
