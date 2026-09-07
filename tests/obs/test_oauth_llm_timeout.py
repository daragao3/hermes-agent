"""The per-call wall-clock bound on codex_structured_invoke (2026-09-07).

Measured before the fix: 34 sequential graphs.invoke() calls, 33 in 12.9-34.1 s,
ONE blocked 24,158.8 s (6.7 h) across a provider outage and then returned a
valid verdict, so the batch reported 34/34 scored, 0 errors. The SDK default
(600 s httpx read timeout, 2 retries) did not bound it: a read timeout only
measures SILENCE, and a stream that keeps trickling bytes resets it forever.

Both directions are pinned here, entirely against a stubbed ``openai.OpenAI``:

* a FAST client is unaffected -- one attempt, parsed result, and the client is
  built with the bound and SDK retries OFF;
* a SLOW client raises CodexTimeoutError within the bound -- for BOTH hang
  shapes, the trickling stream (watchdog) and the silent one (httpx timeout
  surfaced as openai.APITimeoutError) -- and a timeout is never retried;
* every other failure keeps the pre-existing retry loop.

No network: ``openai.OpenAI`` is replaced for the duration of each test and
``_get_oauth_token`` is stubbed, so nothing here can reach chatgpt.com.
"""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

import obs.oauth_llm as oauth_llm


class _Out(BaseModel):
    x: int


# --- stubs ------------------------------------------------------------------


class _Event(SimpleNamespace):
    pass


class _FakeStream:
    """Stand-in for openai's ResponseStream: iterable events + close()."""

    def __init__(self, events, *, trickle_every: float | None = None):
        self._events = list(events)
        self._trickle_every = trickle_every
        self.closed = threading.Event()
        self.yielded = 0

    def __iter__(self):
        if self._trickle_every is None:
            for ev in self._events:
                yield ev
            return
        # Trickle: emit a non-delta event forever, on a cadence, until closed.
        # Models a server that keeps the connection warm with keepalives, the
        # one shape a read timeout can never bound.
        while not self.closed.is_set():
            time.sleep(self._trickle_every)
            self.yielded += 1
            yield _Event(type="response.in_progress")
        raise httpx.StreamClosed()

    def close(self):
        self.closed.set()

    def get_final_response(self):
        return SimpleNamespace(output_text="")


class _FakeStreamCM:
    def __init__(self, stream, *, enter_raises=None):
        self._stream = stream
        self._enter_raises = enter_raises

    def __enter__(self):
        if self._enter_raises is not None:
            raise self._enter_raises
        return self._stream

    def __exit__(self, *exc):
        self._stream.close()
        return False


class _FakeOpenAI:
    """Records constructor kwargs and hands out one stream per .stream() call."""

    instances: list["_FakeOpenAI"] = []
    # Global, not per instance: every retry attempt builds a FRESH client
    # (the token may have rotated), so a per-instance count would always be 1.
    total_stream_calls = 0

    def __init__(self, *, stream_factory, **kwargs):
        self.kwargs = kwargs
        self.stream_calls = 0
        self._stream_factory = stream_factory
        _FakeOpenAI.instances.append(self)
        self.responses = SimpleNamespace(stream=self._stream)

    def _stream(self, **request_kwargs):
        self.stream_calls += 1
        _FakeOpenAI.total_stream_calls += 1
        self.last_request = request_kwargs
        return self._stream_factory(_FakeOpenAI.total_stream_calls)


@pytest.fixture(autouse=True)
def _no_network_and_no_sleep(monkeypatch):
    monkeypatch.setattr(oauth_llm, "_get_oauth_token", lambda: "tok")
    # The retry loop sleeps 0.5 s then 1.0 s between attempts; keep the suite fast.
    monkeypatch.setattr(oauth_llm.time, "sleep", lambda s: None)
    _FakeOpenAI.instances.clear()
    _FakeOpenAI.total_stream_calls = 0
    yield
    _FakeOpenAI.instances.clear()
    _FakeOpenAI.total_stream_calls = 0


def _install_client(monkeypatch, stream_factory):
    def _ctor(**kwargs):
        return _FakeOpenAI(stream_factory=stream_factory, **kwargs)

    monkeypatch.setattr(openai, "OpenAI", _ctor)


def _delta_events(text: str):
    return [
        _Event(type="response.created"),
        _Event(type="response.output_text.delta", delta=text[: len(text) // 2]),
        _Event(type="response.output_text.delta", delta=text[len(text) // 2 :]),
        _Event(type="response.completed"),
    ]


def _api_timeout_error():
    return openai.APITimeoutError(request=httpx.Request("POST", "https://x/responses"))


# --- fast client: unaffected ------------------------------------------------


def test_fast_client_returns_parsed_result_in_one_attempt(monkeypatch):
    _install_client(monkeypatch, lambda n: _FakeStreamCM(_FakeStream(_delta_events('{"x": 7}'))))

    t0 = time.monotonic()
    out = oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0)
    elapsed = time.monotonic() - t0

    assert out == _Out(x=7)
    assert elapsed < 1.0
    assert len(_FakeOpenAI.instances) == 1
    assert _FakeOpenAI.instances[0].stream_calls == 1


def test_client_is_built_with_the_bound_and_sdk_retries_off(monkeypatch):
    """The two load-bearing kwargs. With max_retries left at the SDK default
    the bound would silently become 3x; with no timeout the watchdog alone
    could not bound a SILENT hang."""
    _install_client(monkeypatch, lambda n: _FakeStreamCM(_FakeStream(_delta_events('{"x": 1}'))))

    oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=42.0)

    kwargs = _FakeOpenAI.instances[0].kwargs
    assert kwargs["max_retries"] == 0
    assert kwargs["base_url"] == oauth_llm.CODEX_BASE_URL
    assert kwargs["api_key"] == "tok"
    t = kwargs["timeout"]
    assert isinstance(t, httpx.Timeout)
    assert t.read == 42.0 and t.write == 42.0 and t.pool == 42.0
    assert t.connect == oauth_llm._CONNECT_TIMEOUT_CAP_S  # capped below the budget


def test_connect_timeout_never_exceeds_the_budget(monkeypatch):
    _install_client(monkeypatch, lambda n: _FakeStreamCM(_FakeStream(_delta_events('{"x": 1}'))))

    oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=2.0)

    assert _FakeOpenAI.instances[0].kwargs["timeout"].connect == 2.0


def test_watchdog_timer_is_cancelled_after_a_fast_call(monkeypatch):
    """A cancelled timer must not fire later and close an unrelated stream."""
    _install_client(monkeypatch, lambda n: _FakeStreamCM(_FakeStream(_delta_events('{"x": 1}'))))
    live_timers: list[threading.Timer] = []
    real_timer = threading.Timer

    def _spy(interval, fn):
        t = real_timer(interval, fn)
        live_timers.append(t)
        return t

    monkeypatch.setattr(oauth_llm.threading, "Timer", _spy)

    oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=0.2)

    assert len(live_timers) == 1
    live_timers[0].join(timeout=1.0)
    assert not live_timers[0].is_alive()
    assert live_timers[0].finished.is_set()


# --- slow client: raises within the bound -----------------------------------


def test_trickling_stream_raises_within_the_bound_and_is_closed(monkeypatch):
    """The 6.7 h shape: bytes keep arriving, so no read timeout ever fires.
    Only the watchdog can end this, and it must do so by closing the stream."""
    streams: list[_FakeStream] = []

    def _factory(n):
        s = _FakeStream([], trickle_every=0.01)
        streams.append(s)
        return _FakeStreamCM(s)

    _install_client(monkeypatch, _factory)

    bound = 0.3
    t0 = time.monotonic()
    with pytest.raises(oauth_llm.CodexTimeoutError) as ei:
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=bound)
    elapsed = time.monotonic() - t0

    assert elapsed < bound + 1.0, f"took {elapsed:.2f}s against a {bound}s bound"
    assert streams and streams[0].closed.is_set()
    assert streams[0].yielded > 0, "the stub never trickled; the test proved nothing"
    assert isinstance(ei.value, TimeoutError)
    assert f"exceeded {bound:g}s bound" in str(ei.value)


def test_silent_hang_surfaced_by_sdk_is_translated(monkeypatch):
    """httpx connect/read timeout: the SDK raises APITimeoutError before any
    stream exists. It must become CodexTimeoutError, not a retried RuntimeError."""
    _install_client(
        monkeypatch,
        lambda n: _FakeStreamCM(_FakeStream([]), enter_raises=_api_timeout_error()),
    )

    with pytest.raises(oauth_llm.CodexTimeoutError) as ei:
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=5.0)

    assert isinstance(ei.value.__cause__, openai.APITimeoutError)


def test_timeout_is_terminal_never_retried(monkeypatch):
    """max_retries=2 would mean 3 attempts for any other failure. A timeout is
    the bound itself; retrying would triple it."""
    _install_client(
        monkeypatch,
        lambda n: _FakeStreamCM(_FakeStream([]), enter_raises=_api_timeout_error()),
    )

    with pytest.raises(oauth_llm.CodexTimeoutError):
        oauth_llm.codex_structured_invoke(
            _Out, instructions="i", user="u", max_retries=2, timeout_s=5.0
        )

    assert len(_FakeOpenAI.instances) == 1
    assert _FakeOpenAI.instances[0].stream_calls == 1


def test_a_failure_after_the_deadline_is_reported_as_the_timeout(monkeypatch):
    """Closing the stream from the watchdog makes the reader fail with whatever
    the transport raises. Because the flag was set first, the caller sees the
    timeout, not an opaque transport error."""

    class _RaisesAfterClose(_FakeStream):
        def __iter__(self):
            self.closed.wait(timeout=5.0)
            raise RuntimeError("connection reset by peer")

    stream = _RaisesAfterClose([])
    _install_client(monkeypatch, lambda n: _FakeStreamCM(stream))

    with pytest.raises(oauth_llm.CodexTimeoutError) as ei:
        oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u", timeout_s=0.2)

    assert isinstance(ei.value.__cause__, RuntimeError)


# --- other failures keep the retry loop -------------------------------------


def test_non_timeout_failures_still_retry_then_succeed(monkeypatch):
    def _factory(n):
        if n < 3:
            return _FakeStreamCM(_FakeStream([]), enter_raises=RuntimeError(f"boom {n}"))
        return _FakeStreamCM(_FakeStream(_delta_events('{"x": 3}')))

    _install_client(monkeypatch, _factory)

    out = oauth_llm.codex_structured_invoke(
        _Out, instructions="i", user="u", max_retries=2, timeout_s=5.0
    )

    assert out == _Out(x=3)
    assert sum(c.stream_calls for c in _FakeOpenAI.instances) == 3


def test_non_timeout_failures_exhaust_into_runtime_error(monkeypatch):
    _install_client(
        monkeypatch, lambda n: _FakeStreamCM(_FakeStream([]), enter_raises=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="failed after retries"):
        oauth_llm.codex_structured_invoke(
            _Out, instructions="i", user="u", max_retries=1, timeout_s=5.0
        )

    assert sum(c.stream_calls for c in _FakeOpenAI.instances) == 2


# --- the bound's resolution -------------------------------------------------


def test_default_bound_is_120s(monkeypatch):
    monkeypatch.delenv(oauth_llm.LLM_TIMEOUT_ENV, raising=False)
    assert oauth_llm.resolve_llm_timeout_s() == 120.0
    assert oauth_llm.DEFAULT_LLM_TIMEOUT_S == 120.0


def test_env_overrides_default(monkeypatch):
    monkeypatch.setenv(oauth_llm.LLM_TIMEOUT_ENV, "45")
    assert oauth_llm.resolve_llm_timeout_s() == 45.0


def test_explicit_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv(oauth_llm.LLM_TIMEOUT_ENV, "45")
    assert oauth_llm.resolve_llm_timeout_s(7) == 7.0


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "   ", "nan"])
def test_malformed_or_non_positive_env_falls_back_never_disarms(monkeypatch, caplog, raw):
    monkeypatch.setenv(oauth_llm.LLM_TIMEOUT_ENV, raw)
    with caplog.at_level(logging.WARNING, logger="obs.oauth_llm"):
        assert oauth_llm.resolve_llm_timeout_s() == 120.0
    if raw.strip():
        assert any(oauth_llm.LLM_TIMEOUT_ENV in r.getMessage() for r in caplog.records)


def test_explicit_non_positive_falls_back(monkeypatch):
    monkeypatch.delenv(oauth_llm.LLM_TIMEOUT_ENV, raising=False)
    assert oauth_llm.resolve_llm_timeout_s(0) == 120.0
    assert oauth_llm.resolve_llm_timeout_s(-1) == 120.0


def test_invoke_reads_the_env_when_no_explicit_bound(monkeypatch):
    monkeypatch.setenv(oauth_llm.LLM_TIMEOUT_ENV, "33")
    _install_client(monkeypatch, lambda n: _FakeStreamCM(_FakeStream(_delta_events('{"x": 1}'))))

    oauth_llm.codex_structured_invoke(_Out, instructions="i", user="u")

    assert _FakeOpenAI.instances[0].kwargs["timeout"].read == 33.0
