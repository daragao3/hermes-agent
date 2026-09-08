"""A post-scan worker that raises must say so, exactly once per fault.

Regression pins for 2026-09-08.  ``_run_post_scan_worker`` caught every
exception from all four post-scan workers with a bare ``except Exception`` whose
only body was ``self._record_error_code(error_code)`` -- an in-memory ring the
operator cannot read.  No log line, no durable row.

Measured cost: ``DesktopRegistrySyncWorker`` was down for 1h53m on 2026-09-07
(22:36:50 -> 00:29:36) because ``build_registry_sync_plan`` raised
``ValueError: baseline references missing record <name>`` on the first of 101
registry records that had vanished from every enrolled root while their
baselines stood.  ``run_once`` guards only its two ``scan_desktop_registry_roots``
calls, so the ValueError escaped into this handler and was swallowed.
``_last_run_at`` is assigned before the raise, so the worker re-armed and
re-raised every 300s indefinitely.  Because the heartbeat is the last line of
``run_once`` and run rows are staged only past the raise point, BOTH stopped
together and the leg read as a coordinator stall -- it was not one; both scan
loops indexed sessions throughout.  Root cause was identified only by extracting
the pre-fix planner and re-running it offline against production data.

The anti-flood half is not a nicety.  ``catalog_scan_seconds`` defaults to 3, so
an unthrottled line here emits a full traceback roughly every three seconds --
about 28,800 a day per worker, into a log already carrying ~1 line/sec, which
would bury the very diagnostic it emits.  Suppression is therefore pinned in
both directions: repeats stay quiet, but a CHANGED fault and an elapsed repeat
window must both break through.

Record: loops sessionbridge-provider-call-stall-20260831; MemPalace
session-bridge/registry-worker-silent-valueerror-was-not-a-stall-2026-09-08.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from session_bridge.coordinator import (
    _POST_SCAN_DIAGNOSTIC_REPEAT_SECONDS,
    SessionBridgeCoordinator,
)
from session_bridge.config import BridgeConfig

_LOGGER = "session_bridge.coordinator"
_CODE = "desktop_registry_sync_failed"


class _FakeClock:
    """Injectable monotonic source; the throttle must never read the wall."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class DesktopRegistrySyncWorker:
    """Named after the real worker so the log line's identity is checkable."""

    def __init__(self, *errors: BaseException | None) -> None:
        self._errors = list(errors)
        self.calls = 0

    def run_once(self) -> dict[str, int]:
        error = self._errors[min(self.calls, len(self._errors) - 1)]
        self.calls += 1
        if error is not None:
            raise error
        return {}


def _coordinator(clock: _FakeClock) -> SessionBridgeCoordinator:
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=object(),
        adapters={},
        monotonic=clock,
    )


def _diagnostics(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "post_scan_worker_diagnostic" in record.getMessage()
    ]


def _recoveries(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "post_scan_worker_recovered" in record.getMessage()
    ]


# ------------------------------------------------------------------- it fires

@pytest.mark.asyncio
async def test_a_raising_worker_is_named_with_its_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole point: type, message, worker and a traceback reach the log."""
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(
        ValueError("baseline references missing record local_06f75f85.json")
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await coordinator._run_post_scan_worker(worker, _CODE)

    lines = _diagnostics(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert "worker=DesktopRegistrySyncWorker" in line
    assert f"code={_CODE}" in line
    assert "exc=ValueError" in line
    assert "baseline references missing record local_06f75f85.json" in line
    # The pre-fix shape emitted nothing at all; a line carrying no frames would
    # name the fault but not locate it, which is what made this undiagnosable.
    assert "tb=(" in line
    assert "run_once" in line


@pytest.mark.asyncio
async def test_the_exception_is_still_swallowed_and_still_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scope is the report, not the control flow.

    Without this, a diagnostic that also let the exception escape would pass
    every assertion above while breaking the scan loop it is meant to explain.
    """
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(ValueError("boom"))

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await coordinator._run_post_scan_worker(worker, _CODE)

    assert coordinator._recent_error_codes[-1] == _CODE
    assert _diagnostics(caplog)


@pytest.mark.asyncio
async def test_a_changed_fault_breaks_through_suppression(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Suppression must never hide a NEW fault behind a standing one."""
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(
        ValueError("first fault"),
        ValueError("first fault"),
        RuntimeError("second fault"),
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(3):
            await coordinator._run_post_scan_worker(worker, _CODE)
            clock.advance(3.0)

    lines = _diagnostics(caplog)
    assert len(lines) == 2
    assert "exc=ValueError" in lines[0] and "first fault" in lines[0]
    assert "exc=RuntimeError" in lines[1] and "second fault" in lines[1]


@pytest.mark.asyncio
async def test_a_standing_fault_is_restated_once_the_window_elapses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log rotates on every restart, so a permanent fault must recur.

    It also carries the suppressed count and the age, which is how a reader
    learns the outage's duration from a single line.
    """
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(ValueError("standing fault"))

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await coordinator._run_post_scan_worker(worker, _CODE)
        for _ in range(10):
            clock.advance(_POST_SCAN_DIAGNOSTIC_REPEAT_SECONDS / 10.0)
            await coordinator._run_post_scan_worker(worker, _CODE)

    lines = _diagnostics(caplog)
    assert len(lines) == 2
    assert "failures=11" in lines[1]
    assert "suppressed=9" in lines[1]
    assert f"since={int(_POST_SCAN_DIAGNOSTIC_REPEAT_SECONDS)}s" in lines[1]


@pytest.mark.asyncio
async def test_recovery_closes_the_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A silent outage that ends silently is still unattributable."""
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(ValueError("transient"), None)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await coordinator._run_post_scan_worker(worker, _CODE)
        clock.advance(42.0)
        await coordinator._run_post_scan_worker(worker, _CODE)

    recoveries = _recoveries(caplog)
    assert len(recoveries) == 1
    assert "worker=DesktopRegistrySyncWorker" in recoveries[0]
    assert "failures=1" in recoveries[0]
    assert "over=42s" in recoveries[0]


# ------------------------------------------------------------- it stays quiet

@pytest.mark.asyncio
async def test_a_healthy_worker_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The control that stops this line firing continuously on this box.

    ``catalog_scan_seconds`` is 3, so a diagnostic that also fired on success
    would emit ~28,800 lines a day per worker.  The ``calls`` assertion keeps
    the control from passing vacuously on a worker that never ran.
    """
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(None)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(5):
            await coordinator._run_post_scan_worker(worker, _CODE)
            clock.advance(3.0)

    assert worker.calls == 5
    assert _diagnostics(caplog) == []
    assert _recoveries(caplog) == []


@pytest.mark.asyncio
async def test_repeated_identical_faults_do_not_flood(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The anti-flood property, stated as its own pin.

    Twenty cycles at the real 3s cadence is one minute of production time and
    must cost exactly one line.
    """
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    worker = DesktopRegistrySyncWorker(ValueError("same fault every cycle"))

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        for _ in range(20):
            await coordinator._run_post_scan_worker(worker, _CODE)
            clock.advance(3.0)

    assert worker.calls == 20
    assert len(_diagnostics(caplog)) == 1


@pytest.mark.asyncio
async def test_two_workers_do_not_suppress_each_other(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """State is keyed per error code; a shared key would hide three workers."""
    clock = _FakeClock()
    coordinator = _coordinator(clock)
    registry = DesktopRegistrySyncWorker(ValueError("registry fault"))
    mirror = DesktopRegistrySyncWorker(ValueError("mirror fault"))

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await coordinator._run_post_scan_worker(registry, _CODE)
        await coordinator._run_post_scan_worker(mirror, "mirror_float_failed")

    lines = _diagnostics(caplog)
    assert len(lines) == 2
    assert "registry fault" in lines[0]
    assert "mirror fault" in lines[1]


@pytest.mark.asyncio
async def test_cancellation_still_propagates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The shield/cancel path predates this change and must be untouched.

    A diagnostic that swallowed CancelledError would turn shutdown into a hang.
    """
    clock = _FakeClock()
    coordinator = _coordinator(clock)

    started = asyncio.Event()

    class _Blocking:
        def run_once(self) -> None:
            started.set()

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        task = asyncio.ensure_future(
            coordinator._run_post_scan_worker(_Blocking(), _CODE)
        )
        await asyncio.wait_for(started.wait(), timeout=5.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert _diagnostics(caplog) == []
