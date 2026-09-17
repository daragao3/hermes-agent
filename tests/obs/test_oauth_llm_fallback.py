"""codex_structured_invoke: the route past a Codex quota wall (2026-09-17).

Before this, ``obs/oauth_llm.py`` had exactly one route -- Codex OAuth -- so
when the ChatGPT free plan returned ``429 usage_limit_reached`` with a reset
28 days out, the matcher-shadow scorer and every Critic graph failed on every
fire (10 cron_failed + 10 Telegram pages a day). The contract now:

* a Codex wall recorded by ``agent.provider_quota_guard`` skips Codex with NO
  round trip and goes straight to ``fallback_providers``;
* a quota-class Codex failure (429/402, RateLimitError, ``usage_limit_reached``
  text) leaves the Codex retry loop at once and walks the chain;
* the chain skips walled hops without calling them, skips non-chat-completions
  surfaces, tries each remaining hop once in JSON mode, and when nothing
  serves, raises with the PRIMARY (Codex) error first;
* everything that was not a quota wall is untouched: timeouts stay terminal,
  other failures keep their retries and never fall back.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

import obs.oauth_llm as oauth_llm


class _Out(BaseModel):
    x: int


def _rate_limit_error(body: dict | None = None) -> openai.RateLimitError:
    body = body or {"error": {"type": "usage_limit_reached", "plan_type": "free", "resets_in_seconds": 2457143}}
    request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
    response = httpx.Response(429, request=request, json=body)
    return openai.RateLimitError("Error code: 429 - " + str(body), response=response, body=body)


class _FakeChatClient:
    """Stands in for the OpenAI-compatible client of ONE fallback hop."""

    built: list[dict] = []
    calls: list[dict] = []

    def __init__(self, *, reply, api_key, base_url, timeout_s):
        self._reply = reply
        _FakeChatClient.built.append({"api_key": api_key, "base_url": base_url, "timeout_s": timeout_s})
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        _FakeChatClient.calls.append({"base_url": _FakeChatClient.built[-1]["base_url"], **kwargs})
        if isinstance(self._reply, BaseException):
            raise self._reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._reply))])


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(oauth_llm, "_get_oauth_token", lambda: "tok")
    monkeypatch.setattr(oauth_llm.time, "sleep", lambda s: None)
    # Nothing recorded on any provider unless a test says so.
    monkeypatch.setattr(oauth_llm, "_quota_wall_remaining", lambda provider: None)
    _FakeChatClient.built.clear()
    _FakeChatClient.calls.clear()
    yield
    _FakeChatClient.built.clear()
    _FakeChatClient.calls.clear()


def _codex(monkeypatch, outcome):
    """Script the Codex leg: a str is a reply, an exception is raised, and the
    call count is returned for assertions."""
    calls = {"n": 0}

    def _stream(**kwargs):
        calls["n"] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(oauth_llm, "_codex_stream_text_bounded", _stream)
    return calls


def _chain(monkeypatch, entries, replies: dict[str, object], runtimes: dict[str, dict] | None = None):
    """Install fallback_providers ``entries`` with per-provider scripted replies."""
    monkeypatch.setattr(oauth_llm, "_fallback_chain", lambda: [dict(e) for e in entries])
    runtimes = runtimes or {}

    def _resolve(provider, model):
        if provider in runtimes:
            return dict(runtimes[provider])
        return {"provider": provider, "api_mode": "chat_completions", "api_key": f"key-{provider}",
                "base_url": f"https://{provider}.example/v1"}

    monkeypatch.setattr(oauth_llm, "_resolve_fallback_runtime", _resolve)

    def _build(api_key, base_url, timeout_s):
        provider = base_url.split("//", 1)[1].split(".", 1)[0]
        return _FakeChatClient(reply=replies[provider], api_key=api_key, base_url=base_url, timeout_s=timeout_s)

    monkeypatch.setattr(oauth_llm, "_build_chat_client", _build)


# --- the wall skips Codex without a round trip ------------------------------


def test_recorded_codex_wall_skips_codex_and_serves_from_the_chain(monkeypatch):
    codex = _codex(monkeypatch, '{"x": 1}')
    monkeypatch.setattr(
        oauth_llm, "_quota_wall_remaining",
        lambda provider: 2_000_000.0 if provider == "openai-codex" else None,
    )
    _chain(monkeypatch, [{"provider": "deepseek", "model": "deepseek-v4-pro"}], {"deepseek": '{"x": 7}'})

    out = oauth_llm.codex_structured_invoke(_Out, instructions="score it", user="job", timeout_s=9.0)

    assert out == _Out(x=7)
    assert codex["n"] == 0, "a recorded wall must not cost a Codex round trip"
    call = _FakeChatClient.calls[0]
    assert call["model"] == "deepseek-v4-pro"
    assert call["response_format"] == {"type": "json_object"}
    assert call["messages"][0]["role"] == "system" and "JSON Schema" in call["messages"][0]["content"]
    assert call["messages"][1] == {"role": "user", "content": "job"}
    assert _FakeChatClient.built[0]["timeout_s"] == 9.0


# --- a quota-class Codex failure leaves the retry loop at once ---------------


def test_codex_429_usage_limit_falls_back_without_retrying_codex(monkeypatch):
    codex = _codex(monkeypatch, _rate_limit_error())
    _chain(monkeypatch, [{"provider": "deepseek", "model": "deepseek-v4-pro"}], {"deepseek": '{"x": 3}'})

    out = oauth_llm.codex_structured_invoke(
        _Out, instructions="i", user="u", max_retries=2, timeout_s=5.0
    )

    assert out == _Out(x=3)
    assert codex["n"] == 1, "a wall does not clear in 0.5 s; no Codex retries"


def test_plain_runtime_error_naming_usage_limit_is_quota_class(monkeypatch):
    # The matcher-shadow log line: RuntimeError text carrying the 429 body.
    err = RuntimeError("Error code: 429 - {'error': {'type': 'usage_limit_reached', 'plan_type': 'free'}}")
    codex = _codex(monkeypatch, err)
    _chain(monkeypatch, [{"provider": "deepseek", "model": "deepseek-v4-pro"}], {"deepseek": '{"x": 4}'})

    assert oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0) == _Out(x=4)
    assert codex["n"] == 1


# --- what does NOT fall back --------------------------------------------------


def test_non_quota_failures_keep_retrying_codex_and_never_touch_the_chain(monkeypatch):
    codex = _codex(monkeypatch, RuntimeError("boom"))
    _chain(monkeypatch, [{"provider": "deepseek", "model": "deepseek-v4-pro"}], {"deepseek": '{"x": 9}'})

    with pytest.raises(RuntimeError, match="failed after retries: boom"):
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", max_retries=2, timeout_s=5.0)

    assert codex["n"] == 3
    assert _FakeChatClient.calls == []


def test_timeout_stays_terminal_and_never_falls_back(monkeypatch):
    codex = _codex(monkeypatch, oauth_llm.CodexTimeoutError("Codex request exceeded 5s bound"))
    _chain(monkeypatch, [{"provider": "deepseek", "model": "deepseek-v4-pro"}], {"deepseek": '{"x": 9}'})

    with pytest.raises(oauth_llm.CodexTimeoutError):
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", max_retries=2, timeout_s=5.0)

    assert codex["n"] == 1
    assert _FakeChatClient.calls == []


# --- walking the chain --------------------------------------------------------


def test_chain_skips_walled_and_foreign_surface_hops_and_lands_on_the_first_live_one(monkeypatch):
    _codex(monkeypatch, _rate_limit_error())
    monkeypatch.setattr(
        oauth_llm, "_quota_wall_remaining",
        lambda provider: 300_000.0 if provider == "opencode-go" else None,
    )
    _chain(
        monkeypatch,
        [
            {"provider": "openai-codex", "model": "gpt-5.6-sol"},   # the primary, never a hop
            {"provider": "opencode-go", "model": "deepseek-v4-pro"},  # walled -> no call
            {"provider": "kimi-coding", "model": "kimi-for-coding"},  # anthropic wire -> skipped
            {"provider": "deepseek", "model": "deepseek-v4-pro"},     # serves
        ],
        {"opencode-go": '{"x": 1}', "kimi-coding": '{"x": 2}', "deepseek": '{"x": 5}'},
        runtimes={"kimi-coding": {"provider": "kimi-coding", "api_mode": "anthropic_messages",
                                  "api_key": "k", "base_url": "https://kimi-coding.example/v1"}},
    )

    out = oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0)

    assert out == _Out(x=5)
    assert [c["base_url"] for c in _FakeChatClient.calls] == ["https://deepseek.example/v1"]


def test_a_failing_hop_is_footnoted_and_the_next_hop_serves(monkeypatch):
    _codex(monkeypatch, _rate_limit_error())
    _chain(
        monkeypatch,
        [{"provider": "opencode-go", "model": "deepseek-v4-pro"}, {"provider": "deepseek", "model": "deepseek-v4-pro"}],
        {"opencode-go": RuntimeError("GoUsageLimitError weekly"), "deepseek": '{"x": 6}'},
    )

    assert oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0) == _Out(x=6)
    assert [c["base_url"] for c in _FakeChatClient.calls] == [
        "https://opencode-go.example/v1", "https://deepseek.example/v1",
    ]


def test_exhausted_chain_raises_with_the_primary_error_first(monkeypatch):
    _codex(monkeypatch, _rate_limit_error())
    _chain(
        monkeypatch,
        [{"provider": "deepseek", "model": "deepseek-v4-pro"}],
        {"deepseek": RuntimeError("insufficient balance")},
    )

    with pytest.raises(RuntimeError) as info:
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0)

    text = str(info.value)
    assert text.startswith("codex_structured_invoke failed after retries: RateLimitError")
    assert "fallback_providers exhausted: deepseek/deepseek-v4-pro: RuntimeError: insufficient balance" in text
    assert isinstance(info.value.__cause__, openai.RateLimitError)


def test_no_chain_configured_raises_the_primary_error(monkeypatch):
    _codex(monkeypatch, _rate_limit_error())
    monkeypatch.setattr(oauth_llm, "_fallback_chain", lambda: [])

    with pytest.raises(RuntimeError, match="no fallback_providers are configured"):
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0)


def test_fallback_reply_in_code_fences_is_tolerated_and_garbage_is_a_hop_failure(monkeypatch):
    _codex(monkeypatch, _rate_limit_error())
    _chain(
        monkeypatch,
        [{"provider": "opencode-go", "model": "m"}, {"provider": "deepseek", "model": "m"}],
        {"opencode-go": "not json at all", "deepseek": '```json\n{"x": 8}\n```'},
    )

    assert oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0) == _Out(x=8)


# --- the pieces the fakes replaced --------------------------------------------


def test_fallback_chain_reads_fallback_providers_from_config(monkeypatch):
    import hermes_cli.config as config

    monkeypatch.setattr(
        config, "load_config",
        lambda: {"fallback_providers": [{"provider": "deepseek", "model": "deepseek-v4-pro"}, "kimi-coding", 7, {}]},
    )
    assert oauth_llm._fallback_chain() == [
        {"provider": "deepseek", "model": "deepseek-v4-pro"},
        {"provider": "kimi-coding", "model": None},
    ]


def test_chat_client_is_bounded_with_sdk_retries_off(monkeypatch):
    captured = {}

    def _ctor(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(openai, "OpenAI", _ctor)
    oauth_llm._build_chat_client("k", "https://api.deepseek.com/v1", 45.0)

    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://api.deepseek.com/v1"
    assert captured["timeout"].read == 45.0
    assert captured["timeout"].connect == oauth_llm._CONNECT_TIMEOUT_CAP_S


@pytest.mark.parametrize(
    "exc, expected",
    [
        (RuntimeError("Error code: 429 - {'type': 'usage_limit_reached'}"), True),
        (RuntimeError("Weekly usage limit reached. Resets in 3 days."), True),
        (RuntimeError("Codex returned empty response text"), False),
        (RuntimeError("1 validation error for _Out"), False),
        (SimpleNamespace, False),
    ],
)
def test_quota_class_detection(exc, expected):
    if exc is SimpleNamespace:
        exc = openai.APIStatusError(
            "boom", response=httpx.Response(500, request=httpx.Request("POST", "https://x")), body=None
        )
    assert oauth_llm._is_quota_error(exc) is expected
