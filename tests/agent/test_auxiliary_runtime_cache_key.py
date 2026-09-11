"""Regression coverage for implicit live-runtime auxiliary cache keys.

#49151/#49156 is specifically the ``provider='auto'`` path where callers omit
``main_runtime`` after a mid-session model switch.  This is distinct from
#56889, which isolates callers that pass different explicit ``model=`` values.
"""

import asyncio as asyncio
from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
from threading import Barrier as Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock as AsyncMock, MagicMock as MagicMock, patch

import pytest

import agent.auxiliary_client as aux


@pytest.fixture(autouse=True)
def _clean_aux_state():
    aux.shutdown_cached_clients()
    aux.clear_runtime_main()
    yield
    aux.shutdown_cached_clients()
    aux.clear_runtime_main()


def _runtime(model: str, *, provider: str = "custom:llama-swap") -> dict:
    return {
        "provider": provider,
        "model": model,
        "base_url": "http://llama-swap.test/v1",
        "api_key": "local-key",
        "api_mode": "chat_completions",
        "auth_mode": "api_key",
    }




def test_implicit_runtime_cache_key_covers_full_connection_and_auth_surface():
    """Provider/endpoint/credential/wire/auth changes all isolate auto clients."""
    base = _runtime("same-model")
    variants = [
        {**base, "provider": "custom:other"},
        {**base, "base_url": "https://other.test/v1"},
        {**base, "api_key": "other-key"},
        {**base, "api_mode": "codex_responses"},
        {**base, "auth_mode": "entra_id", "api_key": lambda: "token"},
    ]

    aux.set_runtime_main(**base)
    baseline = aux._client_cache_key("auto", async_mode=False)
    keys = []
    for variant in variants:
        aux.set_runtime_main(**variant)
        keys.append(aux._client_cache_key("auto", async_mode=False))

    assert all(key != baseline for key in keys)
    assert len(set(keys)) == len(keys)






def test_runtime_context_token_restores_previous_value_after_turn():
    """Turn-scoped runtime binding must not leak into later work in the same context."""
    token = aux.set_runtime_main(**_runtime("turn-model"))
    assert aux._normalize_main_runtime(None)["model"] == "turn-model"

    aux.reset_runtime_main(token)

    assert aux._normalize_main_runtime(None) == {}


def test_aiagent_wrapper_resets_runtime_context_after_turn():
    """Every production run_conversation exit restores the caller's Context."""
    from run_agent import AIAgent

    agent = SimpleNamespace(
        _conversation_root_id=lambda: "root-session",
        _session_db=None,
        session_id="session-id",
        # Added by cf43413896 (2026-07-30), which made run_conversation publish
        # the accounting context with source=self._session_source_for_persistence().
        # This stub predates that commit, so it raised AttributeError on every
        # run. Real AIAgent instances always have the method (run_agent.py:616)
        # — only this duck-typed stub could lack it, so the stub is what was
        # stale, not the call site.
        _session_source_for_persistence=lambda: "cli",
    )

    def fake_turn(*_args, **_kwargs):
        aux.set_runtime_main(**_runtime("wrapped-turn"))
        return {"final_response": "ok"}

    with patch("agent.conversation_loop.run_conversation", side_effect=fake_turn):
        result = AIAgent.run_conversation(agent, "hello")

    assert result["final_response"] == "ok"
    assert aux._normalize_main_runtime(None) == {}






def test_explicit_model_cache_isolation_remains_independent_of_runtime_key():
    """#56889 remains covered: explicit model values isolate non-auto clients."""
    first = aux._client_cache_key(
        "openrouter", async_mode=False, model="anthropic/claude-opus-4.8"
    )
    second = aux._client_cache_key(
        "openrouter", async_mode=False, model="openai/gpt-5.5"
    )

    assert first != second










def test_unhashable_callable_runtime_api_keys_are_safe_secret_free_discriminators():
    """Callable token providers remain cacheable without leaking returned tokens."""

    class TokenProvider(list):
        def __init__(self, token: str):
            super().__init__()
            self.token = token

        def __call__(self) -> str:
            return self.token

    first_provider = TokenProvider("first-super-secret-token")
    second_provider = TokenProvider("second-super-secret-token")

    first = aux._client_cache_key(
        "auto", async_mode=False, main_runtime={**_runtime("same"), "api_key": first_provider}
    )
    second = aux._client_cache_key(
        "auto", async_mode=False, main_runtime={**_runtime("same"), "api_key": second_provider}
    )

    hash(first)
    hash(second)
    assert first != second
    rendered = repr((first, second))
    assert "first-super-secret-token" not in rendered
    assert "second-super-secret-token" not in rendered


def test_string_api_keys_are_not_retained_in_cache_key_repr():
    """String credentials discriminate clients without living in cache-key memory."""
    first_secret = "first-literal-super-secret"
    second_secret = "second-literal-super-secret"
    first = aux._client_cache_key(
        "auto",
        async_mode=False,
        api_key=first_secret,
        main_runtime={**_runtime("same"), "api_key": first_secret},
    )
    second = aux._client_cache_key(
        "auto",
        async_mode=False,
        api_key=second_secret,
        main_runtime={**_runtime("same"), "api_key": second_secret},
    )

    assert first != second
    rendered = repr((first, second))
    assert first_secret not in rendered
    assert second_secret not in rendered


