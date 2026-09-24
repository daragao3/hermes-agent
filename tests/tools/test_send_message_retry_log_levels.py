"""Log level of tools.send_message_senders' retry line (2026-09-24): a first-try connect
failure -- the off-box api.telegram.org handshake stall the retry heals -- is INFO; flood
control and any second failure stay WARNING."""
from __future__ import annotations

import asyncio
import logging

from tools.send_message_senders import _send_telegram_message_with_retry


class _NetworkError(Exception):
    pass


class _RetryAfter(Exception):
    def __init__(self, seconds):
        super().__init__(f"Flood control exceeded. Retry in {seconds} seconds")
        self.retry_after = seconds


class _Bot:
    def __init__(self, failures):
        self.failures = list(failures)

    async def send_message(self, **kwargs):
        if self.failures:
            raise self.failures.pop(0)
        return "sent"


def _levels(caplog, failures, monkeypatch):
    async def _no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="tools.send_message_tool"):
        result = asyncio.run(_send_telegram_message_with_retry(_Bot(failures), chat_id=1, text="x"))
    assert result == "sent"
    return [r.levelno for r in caplog.records if "Transient Telegram send failure" in r.getMessage()]


def test_first_connect_failure_is_info(caplog, monkeypatch):
    assert _levels(caplog, [_NetworkError("httpx.ConnectError: ")], monkeypatch) == [logging.INFO]


def test_second_connect_failure_warns(caplog, monkeypatch):
    errs = [_NetworkError("httpx.ConnectError: "), _NetworkError("httpx.ConnectError: ")]
    assert _levels(caplog, errs, monkeypatch) == [logging.INFO, logging.WARNING]


def test_flood_control_always_warns(caplog, monkeypatch):
    assert _levels(caplog, [_RetryAfter(0)], monkeypatch) == [logging.WARNING]
