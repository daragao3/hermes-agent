"""A self-healing Telegram transport blip must not flood the gateway console.

Measured 2026-09-22 on this box: 1-13 VPN/TLS drops per hour (SSLWantReadError on
connect), every one recovered by attempt 2-3, and zero failed outbound sends. Each
blip still printed two WARNING lines, and a failed first reconnect added PTB's own
ERROR with a ~90-line traceback for the SAME NetworkError the adapter had already
logged. What is pinned here: PTB's retry-loop record is demoted to a one-line INFO
for transient transport classes only (BadRequest subclasses NetworkError in PTB and
stays loud), and the adapter's own lines escalate to WARNING only from attempt 2.
"""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[2] / "plugins" / "platforms" / "telegram" / "adapter.py"
pytest.importorskip("telegram")
from plugins.platforms.telegram import adapter as tg  # noqa: E402


def _ptb_record(exc: BaseException, level: int = logging.ERROR) -> logging.LogRecord:
    try:
        raise exc
    except BaseException:
        exc_info = sys.exc_info()
    # Exactly PTB's shape: the prefix travels as an ARG, not in the format string.
    return logging.LogRecord(
        "telegram.ext", level, __file__, 1, "%s Failed run number %s of %s. Aborting.",
        ("Network Retry Loop (Bootstrap delete Webhook):", 0, 0), exc_info)


def _named(name: str) -> BaseException:
    return type(name, (Exception,), {})("httpx.ConnectError: ")


@pytest.mark.parametrize("cls", ["NetworkError", "TimedOut"])
def test_transient_retry_loop_error_becomes_one_info_line(cls):
    record = _ptb_record(_named(cls))
    assert tg._PtbRetryLoopNetworkNoise().filter(record) is True
    assert record.levelno == logging.INFO and record.levelname == "INFO"
    assert record.exc_info is None and record.exc_text is None
    message = record.getMessage()
    assert message.startswith("Network Retry Loop (Bootstrap delete Webhook): Failed run number 0 of 0.")
    assert cls in message and "adapter handles the reconnect" in message


@pytest.mark.parametrize("cls", ["BadRequest", "InvalidToken", "Forbidden", "RuntimeError"])
def test_non_transient_errors_stay_loud(cls):
    record = _ptb_record(_named(cls))
    tg._PtbRetryLoopNetworkNoise().filter(record)
    assert record.levelno == logging.ERROR and record.exc_info is not None


def test_other_ptb_messages_untouched():
    record = _ptb_record(_named("NetworkError"))
    record.msg, record.args = "Exception happened while polling for updates.", ()
    tg._PtbRetryLoopNetworkNoise().filter(record)
    assert record.levelno == logging.ERROR and record.exc_info is not None


def test_filter_is_installed_once_on_the_ptb_logger():
    import importlib

    importlib.reload(tg)
    filters = [f for f in logging.getLogger("telegram.ext").filters
               if type(f).__name__ == "_PtbRetryLoopNetworkNoise"]
    assert len(filters) >= 1


def test_updater_stop_cleanup_error_is_demoted():
    """2026-09-23 11:30: PTB's Updater logs its stop-time get_updates failure at ERROR (with a traceback)
    while the adapter is already reconnecting from the same blip."""
    try:
        raise _named("NetworkError")
    except BaseException:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "telegram.ext.Updater", logging.ERROR, __file__, 1,
        "Error while calling `get_updates` one more time to mark all fetched updates. Suppressing error "
        "to ensure graceful shutdown.", (), exc_info)
    tg._PtbRetryLoopNetworkNoise().filter(record)
    assert record.levelno == logging.INFO and record.exc_info is None


def test_filter_is_on_the_updater_child_logger_too():
    """Logger filters do not propagate to children, so "telegram.ext" alone never saw the Updater record."""
    assert any(type(f).__name__ == "_PtbRetryLoopNetworkNoise"
               for f in logging.getLogger("telegram.ext.Updater").filters)


def _log_calls(fragment: str):
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and fragment in a.value
                        for a in node.args)):
            yield node


def test_scheduling_reconnect_line_is_info():
    calls = list(_log_calls("Telegram network error, scheduling reconnect"))
    assert calls and all(c.func.attr == "info" for c in calls)


def test_attempt_line_escalates_only_after_the_first_attempt():
    calls = list(_log_calls("Telegram network error (attempt %d/%d)"))
    assert len(calls) == 1 and calls[0].func.attr == "log"
    level = ast.unparse(calls[0].args[0])
    assert level == "logging.WARNING if attempt > 1 else logging.INFO"


def test_heartbeat_degraded_line_is_info():
    """The ladder it spawns escalates to WARNING from attempt 2; the degraded notice itself was
    6 WARNINGs a night for blips that all healed (2026-09-22)."""
    calls = list(_log_calls("Telegram polling degraded (%s)"))
    assert len(calls) == 1 and calls[0].func.attr == "info"
