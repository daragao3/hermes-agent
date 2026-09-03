from __future__ import annotations

import inspect
import logging
from collections.abc import Iterator

import pytest

from session_bridge import cli


@pytest.fixture(autouse=True)
def _restore_logger_levels() -> Iterator[None]:
    """Save and restore the levels this module mutates.

    `_quiet_noisy_third_party_loggers` sets levels on the GLOBAL logging tree,
    which outlives the test. Without this fixture a run of this file would
    silence watchfiles for every test that follows it in the same process.
    """
    saved = {
        name: logging.getLogger(name).level
        for name in cli._NOISY_THIRD_PARTY_LOGGERS
    }
    saved_root = logging.getLogger().level
    try:
        yield
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)
        logging.getLogger().setLevel(saved_root)


def test_watchfiles_is_the_logger_being_quieted() -> None:
    """Pin the target. If this list changes, the tests below silently stop
    covering watchfiles while still passing."""
    assert "watchfiles" in cli._NOISY_THIRD_PARTY_LOGGERS


def test_info_is_suppressed_after_quieting() -> None:
    # Reproduce the service's logging tree. FastMCP calls logging.basicConfig
    # with level=INFO on the ROOT logger, and watchfiles carries no level of its
    # own, so it INHERITS INFO. A bare pytest process has root at WARNING, under
    # which watchfiles is already quiet and this test would pass vacuously.
    logging.getLogger().setLevel(logging.INFO)
    watchfiles = logging.getLogger("watchfiles")
    watchfiles.setLevel(logging.NOTSET)
    assert watchfiles.isEnabledFor(logging.INFO), "precondition: INFO passes first"

    cli._quiet_noisy_third_party_loggers()

    assert not watchfiles.isEnabledFor(logging.INFO)


def test_no_record_reaches_a_handler_at_info() -> None:
    """The level check must short-circuit BEFORE a record is created.

    This is the property that matters: the cost being avoided is the rich
    render in the handler, so it is not enough that output is discarded
    somewhere downstream -- the record must never reach a handler at all.
    """

    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    logging.getLogger().setLevel(logging.INFO)
    watchfiles = logging.getLogger("watchfiles")
    watchfiles.setLevel(logging.NOTSET)
    handler = _Capture()
    watchfiles.addHandler(handler)
    try:
        cli._quiet_noisy_third_party_loggers()
        # the exact call watchfiles makes at main.py:308
        watchfiles.info("%d change%s detected", 1, "")
        assert handler.records == []
    finally:
        watchfiles.removeHandler(handler)


def test_warning_and_above_still_pass() -> None:
    """Quieting must not blind us to real problems from the same library."""

    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.levels: list[int] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.levels.append(record.levelno)

    logging.getLogger().setLevel(logging.INFO)
    watchfiles = logging.getLogger("watchfiles")
    watchfiles.setLevel(logging.NOTSET)
    handler = _Capture()
    watchfiles.addHandler(handler)
    try:
        cli._quiet_noisy_third_party_loggers()
        watchfiles.warning("something worth knowing")
        watchfiles.error("something worse")
        assert handler.levels == [logging.WARNING, logging.ERROR]
    finally:
        watchfiles.removeHandler(handler)


def test_it_is_idempotent() -> None:
    cli._quiet_noisy_third_party_loggers()
    first = logging.getLogger("watchfiles").level
    cli._quiet_noisy_third_party_loggers()
    assert logging.getLogger("watchfiles").level == first


def test_serve_actually_calls_it() -> None:
    """Wiring guard.

    Every behavioural test above calls the function directly, so all of them
    pass even if `serve` never invokes it -- the same blind spot that let four
    `locally_owned` tests exercise the wrong scan path for weeks. Asserting on
    the source is crude, but it is the cheap half of the check that the others
    structurally cannot make.
    """
    source = inspect.getsource(cli.ProductionBackend.serve)
    assert "_quiet_noisy_third_party_loggers()" in source
