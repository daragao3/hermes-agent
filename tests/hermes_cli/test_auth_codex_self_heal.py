"""Regression tests for Codex refresh_token self-heal (cross-store rotation).

Hermes keeps its OWN copy of the Codex OAuth token (per profile + top-level),
separate from the Codex CLI's ``~/.codex/auth.json``. OAuth refresh_tokens are
single-use, so when the Codex CLI (or another Hermes process) rotates the shared
token, the frozen copy's refresh_token goes stale and ``refresh_codex_oauth_pure``
fails with a relogin-required error. ``_refresh_codex_auth_tokens`` must then
recover by re-importing the canonical token from ``~/.codex/auth.json`` instead of
surfacing a hard 401 — but ONLY for relogin-required failures, never for transient
ones (e.g. 429 quota, where the stored token is still valid).
"""

import json

import pytest

import hermes_cli.auth as auth
import hermes_cli.auth_codex as auth_codex
from hermes_cli.auth import AuthError, _refresh_codex_auth_tokens, resolve_codex_runtime_credentials

STALE = {"access_token": "stale-access", "refresh_token": "stale-refresh"}


def test_self_heals_on_stale_refresh_token(monkeypatch):
    """invalid_grant (relogin-required) → reimport from ~/.codex and persist it."""
    saved = {}
    fresh = {
        "access_token": "fresh-access",
        "refresh_token": "fresh-refresh",
        "last_refresh": "2026-06-12T00:00:00Z",
    }

    def _rejected(*_a, **_k):
        raise AuthError(
            "refresh token rejected",
            provider="openai-codex",
            code="invalid_grant",
            relogin_required=True,
        )

    monkeypatch.setattr(auth, "refresh_codex_oauth_pure", _rejected)
    monkeypatch.setattr(auth_codex, "refresh_codex_oauth_pure", _rejected)
    monkeypatch.setattr(auth, "_import_codex_cli_tokens", lambda: dict(fresh))
    monkeypatch.setattr(auth_codex, "_import_codex_cli_tokens", lambda: dict(fresh))
    monkeypatch.setattr(auth, "_save_codex_tokens", lambda t, *a, **k: saved.update(t))
    monkeypatch.setattr(auth_codex, "_save_codex_tokens", lambda t, *a, **k: saved.update(t))

    out = _refresh_codex_auth_tokens(STALE, 20.0)

    assert out["access_token"] == "fresh-access"
    assert out["refresh_token"] == "fresh-refresh"
    # the recovered token was persisted to the Hermes auth store
    assert saved["access_token"] == "fresh-access"










def test_self_heals_missing_singleton_access_token_from_codex_cli(tmp_path, monkeypatch):
    """Exact cron failure path: Hermes auth has refresh_token but missing access_token."""
    hermes_home = tmp_path / "hermes"
    codex_home = tmp_path / "codex"
    hermes_home.mkdir()
    codex_home.mkdir()
    (hermes_home / "auth.json").write_text(json.dumps({
        "version": 1,
        "providers": {
            "openai-codex": {
                "tokens": {"refresh_token": "stale-refresh"},
                "last_refresh": "2026-06-01T00:00:00Z",
                "auth_mode": "chatgpt",
            },
        },
    }))
    (codex_home / "auth.json").write_text(json.dumps({
        "tokens": {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
        },
    }))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    resolved = resolve_codex_runtime_credentials()

    assert resolved["api_key"] == "fresh-access"
    assert resolved["source"] == "hermes-auth-store"
    stored = json.loads((hermes_home / "auth.json").read_text())
    tokens = stored["providers"]["openai-codex"]["tokens"]
    assert tokens["access_token"] == "fresh-access"
    assert tokens["refresh_token"] == "fresh-refresh"


def _write_stores(tmp_path, *, hermes_last_refresh, cli_last_refresh):
    """Build a HERMES_HOME + CODEX_HOME pair differing only in chain position."""
    hermes_home = tmp_path / "hermes"
    codex_home = tmp_path / "codex"
    hermes_home.mkdir()
    codex_home.mkdir()
    (hermes_home / "auth.json").write_text(json.dumps({
        "version": 1,
        "providers": {
            "openai-codex": {
                "tokens": {
                    "access_token": "hermes-access",
                    "refresh_token": "hermes-refresh",
                },
                "last_refresh": hermes_last_refresh,
                "auth_mode": "chatgpt",
            },
        },
    }))
    (codex_home / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt",
        "last_refresh": cli_last_refresh,
        "tokens": {
            "access_token": "cli-access",
            "refresh_token": "cli-refresh",
        },
    }))
    return hermes_home, codex_home


def test_does_not_adopt_codex_cli_token_superseded_by_hermes_copy(tmp_path, monkeypatch):
    """Latent re-fragmentation guard: a ~/.codex copy OLDER than Hermes' own copy is a
    spent link in the same rotating chain. Its access_token can still be unexpired, so
    the expiry check alone cannot catch it — importing it would overwrite Hermes' good
    refresh_token with a consumed one and resurrect refresh_token_reused."""
    hermes_home, codex_home = _write_stores(
        tmp_path,
        hermes_last_refresh="2026-07-25T13:56:54.335434Z",
        cli_last_refresh="2026-07-18T09:16:52.932843800Z",  # 9-digit fraction, as Codex CLI writes
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    refresh_calls = []

    def _reused(*_a, **_k):
        refresh_calls.append(1)
        raise AuthError(
            "refresh token reused",
            provider="openai-codex",
            code="refresh_token_reused",
            relogin_required=True,
        )

    # The candidate imports this hook from the auth facade inside the call.
    monkeypatch.setattr(auth, "refresh_codex_oauth_pure", _reused)

    with pytest.raises(AuthError) as ei:
        _refresh_codex_auth_tokens(
            {"access_token": "hermes-access", "refresh_token": "hermes-refresh"}, 20.0
        )

    assert refresh_calls == [1]
    assert ei.value.code == "refresh_token_reused"
    # Hermes' own (newer) credentials must survive untouched.
    stored = json.loads((hermes_home / "auth.json").read_text())
    tokens = stored["providers"]["openai-codex"]["tokens"]
    assert tokens["refresh_token"] == "hermes-refresh"
    assert tokens["access_token"] == "hermes-access"


def test_still_adopts_codex_cli_token_newer_than_hermes_copy(tmp_path, monkeypatch):
    """The guard must not over-block: when the Codex CLI genuinely rotated the shared
    chain AFTER Hermes' copy, self-heal must still fire (that is its whole purpose)."""
    hermes_home, codex_home = _write_stores(
        tmp_path,
        hermes_last_refresh="2026-07-18T09:16:52.932843800Z",
        cli_last_refresh="2026-07-25T13:56:54.335434Z",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    refresh_calls = []

    def _reused(*_a, **_k):
        refresh_calls.append(1)
        raise AuthError(
            "refresh token reused",
            provider="openai-codex",
            code="refresh_token_reused",
            relogin_required=True,
        )

    # The candidate imports this hook from the auth facade inside the call.
    monkeypatch.setattr(auth, "refresh_codex_oauth_pure", _reused)

    out = _refresh_codex_auth_tokens(
        {"access_token": "hermes-access", "refresh_token": "hermes-refresh"}, 20.0
    )

    assert refresh_calls == [1]
    assert out["access_token"] == "cli-access"
    assert out["refresh_token"] == "cli-refresh"
    stored = json.loads((hermes_home / "auth.json").read_text())
    assert stored["providers"]["openai-codex"]["tokens"]["refresh_token"] == "cli-refresh"
