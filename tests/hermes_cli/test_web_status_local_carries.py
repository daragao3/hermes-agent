"""Preserve the local cheap-health and active-gateway status contracts."""

import asyncio
import json
import types

import pytest
from hermes_cli.web_routers import status


@pytest.mark.parametrize("auth_required", [False, True])
def test_health_keeps_both_payload_contracts(monkeypatch, auth_required):
    monkeypatch.setattr(status, "app", types.SimpleNamespace(state=types.SimpleNamespace(auth_required=auth_required)))
    response = asyncio.run(status.get_health())
    body = json.loads(response.body)
    assert body == {"ok": True, "status": "ok", "version": status.__version__,
                    "release_date": status.__release_date__, "auth_required": auth_required}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("active,owns_pid", [(None, False), ("default", True), ("worker", False), ("worker", True)])
def test_default_gateway_selection_keeps_multiplex_fallback(tmp_path, monkeypatch, active, owns_pid):
    import hermes_constants
    monkeypatch.setattr(hermes_constants, "get_default_hermes_root", lambda: tmp_path)
    if active:
        (tmp_path / "active_profile").write_text(active, encoding="utf-8")
        target = tmp_path if active == "default" else tmp_path / "profiles" / active
        target.mkdir(parents=True, exist_ok=True)
        if owns_pid:
            (target / "gateway.pid").write_text("123", encoding="utf-8")
    expected = tmp_path / "profiles" / "worker" if active == "worker" and owns_pid else None
    assert status._default_gateway_profile_dir() == expected
