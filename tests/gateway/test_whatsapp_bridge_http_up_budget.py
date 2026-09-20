"""``_wait_for_bridge``'s HTTP-up phase must be sized from the declared connect budget, not a hardcoded 15 polls.

Observed 2026-09-18 (loops ``whatsapp-bridge-startup-exceeds-http-up-phase-20260918``; gateway pid 452 on
9dc5bac533, i.e. WITH the prespawn fix 22529b8622, host at 100% CPU): every reconnect attempt 2-9
(16:58:55..17:38:07) logged "Bridge found" 17-47 s after "Reconnecting", spawned bridge.js, and then failed
52-55 s later with :3000 never listening and bridge.log untouched -- node had not yet reached its listen
banner. Security 4689 shows the child (e.g. pid 50976) exiting status 0xf **1 s after** the failure line: the
adapter's own disconnect killed the bridge it had just spawned. The pre-fix spawn at 15:52 already measured
27 s spawn->listen. WhatsApp was down 17:29:58Z -> ~09-19T15:19Z and 22 escalations failed with "Cannot
connect to host localhost:3000".

Root cause is arithmetic, not timing luck: ``WhatsAppAdapter.connect_timeout_secs`` declares 90 s (sized in
22529b8622 from connect()'s own phases) but ``_poll_bridge_health`` looped ``range(15)`` at 1 s, so phase 1
could never spend more than ~15 s of it however long node took.

Pinned here as code paths, never a wall-clock:

* ``_http_up_budget_s()`` derives phase 1 from ``connect_timeout_secs`` minus phase 2 and the pre-spawn
  reserve (90 - 15 - 20 = 55 s), never below ``_BRIDGE_HTTP_UP_FLOOR_S``, with an env override.
* ``_poll_bridge_health`` polls to a deadline it is handed, and still returns within ~1 s when the child dies.
* ``_bridge_note`` mirrors the bridge-wait diagnostics to the logger, because a watchdog-launched gateway's
  stdout is nowhere and that is why the 90 s attempt-1 failure left no explanation on disk.

Mutant checks (each reverts one change; the named test goes red):
  - ``_poll_bridge_health`` back to ``for attempt in range(15)``     -> TestHttpUpPhaseSpendsTheBudget
  - ``_http_up_budget_s`` returning a constant 15                    -> TestBudgetDerivedFromConnectTimeout
  - drop the ``poll()`` check from the loop                          -> TestDeadBridgeStillReportedImmediately
  - ``_bridge_died``/``_bridge_note`` back to bare ``print``         -> TestDiagnosticsReachTheLogger
"""

import asyncio
import logging
from unittest.mock import Mock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.whatsapp import adapter as wa


def _adapter(tmp_path, *, connect_budget: float | None = None):
    adapter = wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={
        "session_path": str(tmp_path / "session"),
        "bridge_script": str(tmp_path / "bridge.js"),
        "bridge_port": 3999}))
    if connect_budget is not None:
        adapter.connect_timeout_secs = connect_budget
    adapter._bridge_log = tmp_path / "bridge.log"
    adapter._close_bridge_log = Mock()
    return adapter


class _Clock:
    """Drives asyncio.sleep instantly while advancing the loop clock the code reads."""

    def __init__(self, monkeypatch):
        self.t = 0.0
        self.slept = 0.0
        real_sleep = asyncio.sleep

        async def fake_sleep(delay, *a, **kw):
            self.t += delay
            self.slept += delay
            await real_sleep(0)

        monkeypatch.setattr(wa.asyncio, "sleep", fake_sleep)
        loop = asyncio.get_event_loop_policy().new_event_loop()
        monkeypatch.setattr(wa.asyncio, "get_running_loop", lambda: self)
        self._loop = loop

    def time(self):
        return self.t


class TestBudgetDerivedFromConnectTimeout:
    def test_budget_is_connect_timeout_minus_phase2_and_prespawn(self, tmp_path):
        adapter = _adapter(tmp_path, connect_budget=90.0)

        assert adapter._http_up_budget_s() == pytest.approx(
            90.0 - wa._BRIDGE_CONNECTED_BUDGET_S - wa._BRIDGE_PRESPAWN_RESERVE_S)
        # The phase that actually failed on 2026-09-18 must now cover the measured
        # 27-55 s node startup. A hardcoded 15 fails this.
        assert adapter._http_up_budget_s() >= 55.0

    def test_a_small_budget_never_drops_below_the_floor(self, tmp_path):
        adapter = _adapter(tmp_path, connect_budget=20.0)

        assert adapter._http_up_budget_s() == wa._BRIDGE_HTTP_UP_FLOOR_S

    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHATSAPP_BRIDGE_HTTP_UP_TIMEOUT", "7")
        adapter = _adapter(tmp_path, connect_budget=90.0)

        assert adapter._http_up_budget_s() == 7.0


class TestHttpUpPhaseSpendsTheBudget:
    def test_a_bridge_that_binds_at_40s_is_accepted(self, tmp_path, monkeypatch):
        """The 2026-09-18 case: node alive throughout, listening well after 15 s."""
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=None))
        clock = _Clock(monkeypatch)

        async def probe():
            if clock.t < 40:
                raise ConnectionRefusedError("not listening yet")
            return True, {"status": "connected"}

        adapter._probe_bridge_health = probe

        assert asyncio.run(adapter._wait_for_bridge()) is True
        assert clock.slept >= 40

    def test_still_gives_up_at_the_budget(self, tmp_path, monkeypatch):
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=None))
        clock = _Clock(monkeypatch)

        async def never():
            raise ConnectionRefusedError("never listens")

        adapter._probe_bridge_health = never

        assert asyncio.run(adapter._wait_for_bridge()) is False
        assert clock.slept == pytest.approx(adapter._http_up_budget_s(), abs=1.5)


class TestDeadBridgeStillReportedImmediately:
    def test_a_crashed_child_is_reported_within_a_poll(self, tmp_path, monkeypatch):
        """Waiting longer for a LIVE bridge must not slow down reporting a dead one."""
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=1), returncode=1)
        clock = _Clock(monkeypatch)

        async def never():
            raise ConnectionRefusedError("dead")

        adapter._probe_bridge_health = never

        assert asyncio.run(adapter._wait_for_bridge()) is False
        assert clock.slept <= 2


class TestDiagnosticsReachTheLogger:
    def test_bridge_death_is_logged_not_only_printed(self, tmp_path, monkeypatch, caplog):
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=None))
        _Clock(monkeypatch)

        async def never():
            raise ConnectionRefusedError("never listens")

        adapter._probe_bridge_health = never

        with caplog.at_level(logging.INFO, logger=wa.logger.name):
            asyncio.run(adapter._wait_for_bridge())

        assert any("did not start in" in record.getMessage() for record in caplog.records)
