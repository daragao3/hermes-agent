"""Cross-session provider quota guard (agent.provider_quota_guard) and its two wiring points:
the pre-call divert in ``nous_rate_limit_guard`` and the memo write in ``handle_api_error``."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import provider_quota_guard as pqg
from agent import turn_api_call, turn_api_error


@pytest.fixture
def guard_env(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(pqg, "_state_path", lambda: str(home / "rate_limits" / "providers.json"))
    return home


class _CodexError(Exception):
    """Shape of openai.RateLimitError for a Codex usage wall: body dict + message text."""

    def __init__(self, resets_in_seconds=377072, resets_at=None, *, body=True):
        payload = {"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached",
                             "plan_type": "pro", "resets_at": resets_at, "eligible_promo": None,
                             "resets_in_seconds": resets_in_seconds}}
        self.message = f"Error code: 429 - {payload}"
        self.status_code = 429
        self.body = payload if body else None
        super().__init__(self.message)


# ------------------------------------------------------------------ parsing

def test_reset_from_codex_body_relative_seconds():
    assert pqg.reset_seconds_from_error(_CodexError(377072)) == 377072


def test_reset_from_body_epoch_when_no_relative_field():
    now = 1_789_000_000.0
    err = _CodexError(resets_in_seconds=None, resets_at=now + 3600)
    assert pqg.reset_seconds_from_error(err, now=now) == pytest.approx(3600)


def test_reset_from_message_text_when_body_is_missing():
    err = _CodexError(120, body=False)
    assert pqg.reset_seconds_from_error(err) == 120


def test_reset_from_retry_after_header():
    err = SimpleNamespace(message="429 slow down", response=SimpleNamespace(headers={"Retry-After": "900"}))
    assert pqg.reset_seconds_from_error(err) == 900


def test_no_reset_signal_returns_none():
    err = SimpleNamespace(message="Error code: 403 - You've reached your monthly usage limit for this billing cycle.")
    assert pqg.reset_seconds_from_error(err) is None


# ------------------------------------------------------------------ memo

def test_record_writes_entry_and_remaining_reads_it(guard_env):
    delay = pqg.record_provider_exhaustion("openai-codex", "gpt-5.6-sol", api_error=_CodexError(3600))
    assert delay == pytest.approx(3600, abs=2)
    remaining = pqg.provider_exhaustion_remaining("OpenAI-Codex")  # key is case-insensitive
    assert remaining is not None and 3590 < remaining <= 3600
    state = json.loads((guard_env / "rate_limits" / "providers.json").read_text(encoding="utf-8"))
    assert state["openai-codex"]["model"] == "gpt-5.6-sol"
    assert state["openai-codex"]["reason"] == "rate_limit"
    assert state["openai-codex"]["reset_at_iso"].endswith("+00:00")


def test_record_ignores_short_resets_and_errors_without_a_reset(guard_env):
    assert pqg.record_provider_exhaustion("openai-codex", "m", api_error=_CodexError(30)) is None
    assert pqg.record_provider_exhaustion("kimi-coding", "m", api_error=RuntimeError("HTTP 403: monthly usage limit")) is None
    assert pqg.provider_exhaustion_remaining("openai-codex") is None
    assert not (guard_env / "rate_limits" / "providers.json").exists()


def test_record_caps_absurd_resets(guard_env):
    delay = pqg.record_provider_exhaustion("p", "m", api_error=_CodexError(10 ** 9))
    assert delay == pytest.approx(pqg.MAX_RESET_SECONDS, abs=2)


def test_second_record_never_shortens_the_window(guard_env):
    pqg.record_provider_exhaustion("p", "m", api_error=_CodexError(7200))
    pqg.record_provider_exhaustion("p", "m", api_error=_CodexError(600))
    remaining = pqg.provider_exhaustion_remaining("p")
    assert remaining is not None and remaining > 7100


def test_expired_entries_are_pruned_on_read(guard_env, monkeypatch):
    pqg.record_provider_exhaustion("p", "m", api_error=_CodexError(120))
    real_time = time.time
    monkeypatch.setattr(pqg.time, "time", lambda: real_time() + 121)
    assert pqg.provider_exhaustion_remaining("p") is None
    assert not (guard_env / "rate_limits" / "providers.json").exists()


def test_clear_removes_only_that_provider(guard_env):
    pqg.record_provider_exhaustion("p", "m", api_error=_CodexError(600))
    pqg.record_provider_exhaustion("q", "m", api_error=_CodexError(600))
    pqg.clear_provider_exhaustion("p")
    assert pqg.provider_exhaustion_remaining("p") is None
    assert pqg.provider_exhaustion_remaining("q") is not None
    pqg.clear_provider_exhaustion("missing")  # no-op, never raises


def test_unreadable_state_fails_open(guard_env):
    path = guard_env / "rate_limits" / "providers.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert pqg.provider_exhaustion_remaining("p") is None


# ------------------------------------------------------------------ pre-call divert

def _guard_kwargs():
    return {
        "_retry": SimpleNamespace(), "api_messages": [], "messages": [], "conversation_history": [],
        "active_system_prompt": "system", "retry_count": 3, "compression_attempts": 1, "api_call_count": 1,
    }


def _agent(provider="openai-codex", chain_len=1, activate=True):
    agent = SimpleNamespace(
        provider=provider, model="gpt-5.6-sol", _fallback_index=0,
        _fallback_chain=[{"provider": "opencode-go", "model": "deepseek-v4-pro"}] * chain_len,
        _rate_limited_until=0.0, _buffer_vprint=MagicMock(), _buffer_status=MagicMock(),
        _flush_status_buffer=MagicMock(), _persist_session=MagicMock(),
    )

    def _activate(reason=None, **_):
        if not activate:
            return False
        agent._fallback_index += 1
        agent.provider, agent.model = "opencode-go", "deepseek-v4-pro"
        return True

    agent._try_activate_fallback = MagicMock(side_effect=_activate)
    return agent


def test_guard_diverts_an_exhausted_primary_before_calling_it(guard_env, monkeypatch):
    pqg.record_provider_exhaustion("openai-codex", "gpt-5.6-sol", api_error=_CodexError(377072))
    agent = _agent()
    monkeypatch.setattr("agent.conversation_loop._arm_fallback_restart", lambda a, m, p, r: "rebuilt")

    verdict = turn_api_call.nous_rate_limit_guard(agent, **_guard_kwargs())

    assert verdict.action == "break"
    assert verdict.active_system_prompt == "rebuilt"
    assert verdict.retry_count == 0 and verdict.compression_attempts == 0
    assert agent._try_activate_fallback.call_count == 1
    assert agent.provider == "opencode-go"
    # The rate_limit reason is what makes the real try_activate_fallback consult the memo,
    # extend _rate_limited_until to the recorded reset and word the notice accordingly
    # (covered in tests/run_agent/test_provider_fallback.py).
    from agent.error_classifier import FailoverReason
    assert agent._try_activate_fallback.call_args.kwargs == {"reason": FailoverReason.rate_limit}
    assert "usage limit reached" in agent._buffer_status.call_args[0][0]


def test_guard_falls_through_when_nothing_is_recorded(guard_env):
    agent = _agent()
    assert turn_api_call.nous_rate_limit_guard(agent, **_guard_kwargs()).action == "fallthrough"
    agent._try_activate_fallback.assert_not_called()


def test_guard_falls_through_when_no_fallback_remains(guard_env):
    pqg.record_provider_exhaustion("openai-codex", "gpt-5.6-sol", api_error=_CodexError(3600))
    agent = _agent(chain_len=0)
    assert turn_api_call.nous_rate_limit_guard(agent, **_guard_kwargs()).action == "fallthrough"
    agent._try_activate_fallback.assert_not_called()


def test_guard_falls_through_when_activation_fails(guard_env, monkeypatch):
    pqg.record_provider_exhaustion("openai-codex", "gpt-5.6-sol", api_error=_CodexError(3600))
    agent = _agent(activate=False)
    assert turn_api_call.nous_rate_limit_guard(agent, **_guard_kwargs()).action == "fallthrough"
    assert agent.provider == "openai-codex"


def test_guard_never_breaks_the_loop_on_internal_error(guard_env, monkeypatch):
    monkeypatch.setattr(pqg, "provider_exhaustion_remaining", MagicMock(side_effect=RuntimeError("disk")))
    agent = _agent()
    assert turn_api_call.nous_rate_limit_guard(agent, **_guard_kwargs()).action == "fallthrough"


# ------------------------------------------------------------------ memo write from the handler

def test_handler_records_exhaustion_for_a_classified_rate_limit(guard_env):
    from agent.error_classifier import FailoverReason

    api_error = _CodexError(377072)
    agent = SimpleNamespace(provider="openai-codex", model="gpt-5.6-sol", log_prefix="", session_id="s",
                            thinking_callback=None, _fallback_index=0, _interrupt_requested=False)
    agent._extract_api_error_context = MagicMock(return_value={})
    agent._invoke_api_request_error_hook = MagicMock()
    agent._touch_activity = MagicMock()
    classified = SimpleNamespace(reason=FailoverReason.rate_limit, status_code=429, retryable=True,
                                 should_compress=False, should_rotate_credential=False, should_fallback=True)
    kwargs = {
        "api_error": api_error, "_retry": SimpleNamespace(), "thinking_spinner": None, "messages": [],
        "api_messages": [], "api_kwargs": {}, "system_message": None, "active_system_prompt": "system",
        "conversation_history": [], "approx_tokens": 0, "retry_count": 0, "max_retries": 1,
        "compression_attempts": 0, "max_compression_attempts": 1, "api_call_count": 1,
        "api_request_id": "r", "api_start_time": time.time(), "effective_task_id": "t", "turn_id": "turn",
    }
    with (
        patch.object(turn_api_error, "_report_agent_loop_fault"),
        patch.object(turn_api_error, "recover_before_classification", return_value=(False, "system")),
        patch.object(turn_api_error, "classify_api_error", return_value=classified),
        patch("tools.interpreter_shutdown.interpreter_shutting_down", return_value=False),
        # Stop right after the memo write; the rest of the handler is covered elsewhere.
        patch.object(turn_api_error, "recover_after_classification", side_effect=RuntimeError("stop")),
    ):
        with pytest.raises(RuntimeError, match="stop"):
            turn_api_error.handle_api_error(agent, **kwargs)

    remaining = pqg.provider_exhaustion_remaining("openai-codex")
    assert remaining is not None and remaining > 377000
