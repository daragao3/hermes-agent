"""tools.send_message_senders: a never-connected Telegram send is retried; a timeout is not.

The retry classifier used to retry only 5xx/429. A ``ConnectError`` -- the
connection was never established, so nothing can have been delivered -- fell
through as final, and on 2026-09-17 the cron delivery lane lost five messages
to one-second Wi-Fi blips the poller itself recovered from immediately.
"""

from __future__ import annotations

import asyncio

import pytest

import tools.send_message_senders as senders


class _NetworkError(Exception):
    """Shape of telegram.error.NetworkError wrapping an httpx.ConnectError."""


# The classifier keys on the CLASS NAME (httpx.ConnectError); give the stand-in the real name.
_ConnectError = type("ConnectError", (Exception,), {})


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_NetworkError("httpx.ConnectError: "), 1.0),           # PTB's wrap: class name in text, empty inner
        (_ConnectError(""), 1.0),                                # the raw httpx class
        (_NetworkError("Connection refused"), 1.0),
        (_NetworkError("[Errno 11001] getaddrinfo failed"), 1.0),
        (_NetworkError("Timed out"), None),                      # may have gone through: never retried
        (_NetworkError("Pool timeout: all connections busy"), None),
        (_NetworkError("Bad Gateway (502)"), 1.0),               # unchanged 5xx path
        (_NetworkError("Forbidden: bot was blocked"), None),
    ],
)
def test_retry_classification(exc, expected):
    assert senders._telegram_retry_delay(exc, 0) == expected


def test_connect_failure_backs_off_exponentially():
    exc = _NetworkError("httpx.ConnectError: ")
    assert [senders._telegram_retry_delay(exc, a) for a in range(3)] == [1.0, 2.0, 4.0]


def test_chained_connect_error_counts():
    inner = _ConnectError("")
    outer = _NetworkError("transport failure")
    outer.__cause__ = inner
    assert senders._telegram_retry_delay(outer, 0) == 1.0


def test_send_with_retry_recovers_from_one_connect_blip(monkeypatch):
    calls = {"n": 0}

    class _Bot:
        async def send_message(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _NetworkError("httpx.ConnectError: ")
            return {"message_id": 7, **kwargs}

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(senders.asyncio, "sleep", _no_sleep)
    out = asyncio.run(senders._send_telegram_message_with_retry(_Bot(), chat_id=1, text="x"))
    assert out["message_id"] == 7 and calls["n"] == 2


def test_send_with_retry_still_gives_up_on_a_timeout(monkeypatch):
    calls = {"n": 0}

    class _Bot:
        async def send_message(self, **kwargs):
            calls["n"] += 1
            raise _NetworkError("Timed out")

    with pytest.raises(_NetworkError):
        asyncio.run(senders._send_telegram_message_with_retry(_Bot(), chat_id=1, text="x"))
    assert calls["n"] == 1, "a timed-out send may have been delivered; never resend it"
