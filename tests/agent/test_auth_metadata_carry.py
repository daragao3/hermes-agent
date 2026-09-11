"""Local auth/context contracts across upstream module decomposition."""
import json
from types import SimpleNamespace

import pytest

from agent import model_metadata as metadata
from hermes_cli import auth, auth_nous


@pytest.mark.parametrize("cli_stamp,expected", [
    ("2026-07-25T10:00:00Z", True),
    ("2026-07-25T11:00:00Z", True),
    ("2026-07-25T12:00:00Z", False),
    ("invalid", False),
])
def test_codex_recovery_compares_bom_encoded_cli_stamp(tmp_path, monkeypatch, cli_stamp, expected):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    cli = tmp_path / "cli-auth.json"
    cli.write_text(json.dumps({"last_refresh": cli_stamp}), encoding="utf-8-sig")
    monkeypatch.setattr(auth, "_codex_cli_auth_path", lambda: cli)
    monkeypatch.setattr(auth, "_load_auth_store", lambda: {
        "providers": {"openai-codex": {"last_refresh": "2026-07-25T11:00:00Z"}},
    })
    assert auth._codex_cli_import_is_superseded() is expected


@pytest.mark.parametrize("dead_token,remaining", [("dead", ["fresh", "unidentified"]), (None, ["dead", "fresh"])])
def test_nous_quarantine_preserves_other_chains(monkeypatch, dead_token, remaining):
    monkeypatch.setattr(auth_nous, "_oauth_trace", lambda *args, **kwargs: None)
    entries = [
        {"id": "dead", "source": "manual:device_code", "refresh_token": "dead"},
        {"id": "fresh", "source": "device_code", "refresh_token": "fresh"},
        {"id": "unidentified", "source": "device_code"},
    ]
    store = {"credential_pool": {"nous": entries}}
    assert auth_nous._quarantine_nous_pool_entries(
        store, SimpleNamespace(code="expired"), reason="test", dead_refresh_token=dead_token,
    )
    assert [entry["id"] for entry in store["credential_pool"]["nous"]] == remaining


@pytest.mark.parametrize("slug", ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"])
def test_local_context_fallback_keeps_value_and_provenance(slug):
    assert metadata._resolve_codex_oauth_context_length_with_source(slug) == (1_050_000, "fallback")
    # An explicit variant must not downgrade a non-stale source, matching upstream policy.
    assert metadata._resolve_codex_oauth_context_length_with_source(slug + "-900k") == (1_050_000, "fallback")
