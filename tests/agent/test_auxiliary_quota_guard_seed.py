"""The auxiliary router honours the cross-session provider quota guard.

Regression for 2026-09-16: after the OpenCode Go weekly wall the main agent loop diverted
every cron fire straight to the deepseek hop (``agent.provider_quota_guard``), while
``call_llm(task="approval")`` kept resolving ``fallback_providers[0](opencode-go)`` afresh,
took the 429, and escalated -- 4/4 smart approvals failed with a working hop one entry
further down the same chain. The aux unhealthy cache now seeds itself from the guard.
"""
import logging
import time
from unittest.mock import patch

import pytest

from agent import auxiliary_client as aux
from agent import provider_quota_guard as pqg


@pytest.fixture
def guard_env(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(pqg, "_state_path", lambda: str(home / "rate_limits" / "providers.json"))
    aux._reset_aux_unhealthy_cache()
    yield home
    aux._reset_aux_unhealthy_cache()


def _wall(provider: str, model: str = "deepseek-v4-pro", secs: float = 3 * 86400.0) -> None:
    """Record ``provider`` exhausted for ``secs`` the way the main loop does on a 429."""
    err = type("RateLimitError", (Exception,), {})()
    err.body = {"error": {"resets_in_seconds": secs}}
    assert pqg.record_provider_exhaustion(provider, model, api_error=err) is not None


def test_guard_wall_makes_provider_unhealthy_until_its_reset(guard_env, caplog):
    _wall("opencode-go")
    with caplog.at_level(logging.INFO, logger=aux.__name__):
        assert aux._is_provider_unhealthy("opencode-go")
        aux._log_skip_unhealthy("opencode-go", "approval")
    skip = [r.getMessage() for r in caplog.records if "skipping opencode-go" in r.getMessage()]
    assert len(skip) == 1
    assert "quota wall recorded by an earlier session" in skip[0]
    assert "resets in 3.0d" in skip[0]
    # Seeded expiry tracks the wall's own reset, not the 10-minute payment-error TTL.
    key = aux._unhealthy_cache_key("opencode-go", None)
    assert aux._aux_unhealthy_until[key] - time.time() > aux._AUX_UNHEALTHY_TTL_SECONDS * 10


def test_no_wall_recorded_leaves_provider_healthy(guard_env):
    assert not aux._is_provider_unhealthy("opencode-go")
    assert not aux._aux_unhealthy_until


def test_guard_read_failure_fails_open(guard_env):
    with patch.object(pqg, "provider_exhaustion_remaining", side_effect=RuntimeError("boom")):
        assert not aux._is_provider_unhealthy("opencode-go")


def test_main_fallback_chain_skips_walled_hop_and_lands_on_the_next(guard_env, caplog):
    _wall("opencode-go")
    chain = [
        {"provider": "opencode-go", "model": "deepseek-v4-pro"},
        {"provider": "deepseek", "model": "deepseek-v4-pro"},
        {"provider": "kimi-coding", "model": "kimi-for-coding"},
    ]
    resolved = []

    def _resolve(entry):
        resolved.append(entry["provider"])
        return object(), entry["model"]

    with patch("hermes_cli.config.load_config_readonly", return_value={}), patch(
        "hermes_cli.fallback_config.get_fallback_chain", return_value=chain,
    ), patch.object(aux, "_resolve_fallback_entry", side_effect=_resolve), patch.object(
        aux, "_context_too_small", return_value=None,
    ), caplog.at_level(logging.INFO, logger=aux.__name__):
        client, model, provider = aux._try_main_fallback_chain(
            "approval", "openai-codex", reason="model incompatible with route")

    assert client is not None
    assert (provider, model) == ("deepseek", "deepseek-v4-pro")
    # The walled hop was never resolved -- no client built, no call spent on it.
    assert resolved == ["deepseek"]
    assert any("fallback_providers[1](deepseek)" in r.getMessage() for r in caplog.records)


def test_main_fallback_chain_still_takes_first_hop_when_no_wall(guard_env):
    chain = [
        {"provider": "opencode-go", "model": "deepseek-v4-pro"},
        {"provider": "deepseek", "model": "deepseek-v4-pro"},
    ]
    with patch("hermes_cli.config.load_config_readonly", return_value={}), patch(
        "hermes_cli.fallback_config.get_fallback_chain", return_value=chain,
    ), patch.object(aux, "_resolve_fallback_entry", side_effect=lambda e: (object(), e["model"])), patch.object(
        aux, "_context_too_small", return_value=None,
    ):
        _client, _model, provider = aux._try_main_fallback_chain("approval", "openai-codex")
    assert provider == "opencode-go"
