"""Standalone Telegram sends (event-bus notifier, cron delivery, send_message) must use the
live adapter's HTTP timeouts, not PTB's 5 s defaults.

Measured 2026-09-22: a 20-event (~10.7 KB, 3-chunk) notifier batch for one topic failed
"Timed out" ~6 s into every attempt for 25+ minutes while a fresh getMe took 0.5 s; the live
adapter had long since moved to read/write 20 s, connect 10 s, pool 8 s for exactly this reason.
"""

import pytest

pytest.importorskip("telegram")
from tools import send_message_senders as senders  # noqa: E402


def _timeouts(request):
    # PTB keeps the per-request defaults on the HTTPXRequest instance.
    return request._client_kwargs["timeout"]


def test_direct_bot_uses_adapter_timeouts(monkeypatch):
    for name in ("HERMES_TELEGRAM_HTTP_READ_TIMEOUT", "HERMES_TELEGRAM_HTTP_WRITE_TIMEOUT",
                 "HERMES_TELEGRAM_HTTP_CONNECT_TIMEOUT", "HERMES_TELEGRAM_HTTP_POOL_TIMEOUT", "TELEGRAM_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("gateway.platforms.base.resolve_proxy_url", lambda *a, **k: None)
    bot = senders._telegram_bot("123:abc")
    t = _timeouts(bot._request[1])
    assert (t.read, t.write, t.connect, t.pool) == (20.0, 20.0, 10.0, 8.0)


def test_env_overrides_are_honoured(monkeypatch):
    monkeypatch.setenv("HERMES_TELEGRAM_HTTP_READ_TIMEOUT", "33")
    monkeypatch.setattr("gateway.platforms.base.resolve_proxy_url", lambda *a, **k: None)
    assert _timeouts(senders._telegram_bot("123:abc")._request[1]).read == 33.0


def test_proxy_bot_keeps_the_same_timeouts(monkeypatch):
    monkeypatch.delenv("HERMES_TELEGRAM_HTTP_READ_TIMEOUT", raising=False)
    monkeypatch.setattr("gateway.platforms.base.resolve_proxy_url", lambda *a, **k: "http://127.0.0.1:9")
    bot = senders._telegram_bot("123:abc")
    assert _timeouts(bot._request[1]).read == 20.0
