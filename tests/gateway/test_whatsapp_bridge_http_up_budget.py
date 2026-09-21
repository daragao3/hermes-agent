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

WHAT 2026-09-20 CHANGED HERE, and why two tests in this file were rewritten rather than preserved (loops
``whatsapp-httpup-budget-live-proof-20260920``): the first production episode under the widened phase spent
the full 55 s on a child that never bound, and the NEXT attempt -- same host, 90.5-92.3 % commit, 52 s later
-- bound in 11.3 s. The failure is bimodal, not slow, so "wait longer on THIS child" is the wrong lever and
this file no longer asserts it. The budget arithmetic below is unchanged and still correct; what it now buys
is several bounded spawn attempts (``tests/gateway/test_whatsapp_bridge_failfast_respawn.py``) instead of one
long wait, and ``_wait_for_bridge`` therefore takes a required ``respawn`` callable.

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
from unittest.mock import AsyncMock, Mock

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
    # This file is about the BUDGET; the kill-and-replace mechanics it now sits on top of are
    # pinned in test_whatsapp_bridge_failfast_respawn.py. Stubbing the discard keeps the mocked
    # child alive across attempts, which is exactly the "alive but never listening" case here.
    adapter._discard_unbound_bridge = AsyncMock()
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
    def test_a_bridge_that_binds_at_40s_is_still_accepted(self, tmp_path, monkeypatch):
        """The 2026-09-18 case re-read after 09-20: 40 s is inside the budget, on a LATER child.

        What changed is that no single child is waited on for 40 s. What did NOT change, and is
        what this test protects, is that the declared budget is really spent before giving up --
        a hardcoded 15-poll phase 1 fails this whether or not it respawns.
        """
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=None))
        clock = _Clock(monkeypatch)

        async def probe():
            if clock.t < 40:
                raise ConnectionRefusedError("not listening yet")
            return True, {"status": "connected"}

        adapter._probe_bridge_health = probe

        assert asyncio.run(adapter._wait_for_bridge(Mock())) is True
        assert clock.slept >= 40

    def test_still_gives_up_at_the_budget(self, tmp_path, monkeypatch):
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=None))
        clock = _Clock(monkeypatch)

        async def never():
            raise ConnectionRefusedError("never listens")

        adapter._probe_bridge_health = never

        assert asyncio.run(adapter._wait_for_bridge(Mock())) is False
        attempts = max(1, int(adapter._http_up_budget_s() // adapter._bind_attempt_budget_s()))
        assert clock.slept == pytest.approx(attempts * adapter._bind_attempt_budget_s(), abs=1.5)


class TestDeadBridgeStillReportedImmediately:
    def test_a_crashed_child_is_reported_within_a_poll(self, tmp_path, monkeypatch):
        """Waiting longer for a LIVE bridge must not slow down reporting a dead one."""
        adapter = _adapter(tmp_path, connect_budget=90.0)
        adapter._bridge_process = Mock(poll=Mock(return_value=1), returncode=1)
        clock = _Clock(monkeypatch)

        async def never():
            raise ConnectionRefusedError("dead")

        adapter._probe_bridge_health = never

        assert asyncio.run(adapter._wait_for_bridge(Mock())) is False
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
            asyncio.run(adapter._wait_for_bridge(Mock()))

        assert any("did not start in" in record.getMessage() for record in caplog.records)


class TestBridgeLifecycleDecisionsReachTheLogger:
    """The pre-spawn decisions (adopt / restart-because-not-connected / restart-because-stale) and
    the post-spawn "Bridge started" line were still bare print() after 1f12f8d8c4 routed the
    bridge-WAIT diagnostics. On 2026-09-18 attempt 1 spawned nothing for 90 s and the reason
    could only have been on one of these lines, which never reached disk."""

    async def _probe(self, data):
        return True, data

    def test_not_connected_bridge_decision_is_logged(self, tmp_path, caplog):
        adapter = _adapter(tmp_path)
        adapter._probe_bridge_health = lambda: self._probe({"status": "close"})

        with caplog.at_level(logging.INFO, logger=wa.logger.name):
            assert asyncio.run(adapter._reuse_running_bridge(tmp_path / "bridge.js")) is False

        assert any("Bridge found but not connected" in r.getMessage() for r in caplog.records)

    def test_stale_bridge_decision_is_logged(self, tmp_path, caplog):
        adapter = _adapter(tmp_path)
        bridge_path = tmp_path / "bridge.js"
        bridge_path.write_text("// on-disk bridge", encoding="utf-8")
        adapter._probe_bridge_health = lambda: self._probe({"status": "connected", "scriptHash": "not-the-disk-hash"})

        with caplog.at_level(logging.INFO, logger=wa.logger.name):
            assert asyncio.run(adapter._reuse_running_bridge(bridge_path)) is False

        assert any("Running bridge is stale" in r.getMessage() for r in caplog.records)

    def test_adopted_bridge_decision_is_logged(self, tmp_path, caplog, monkeypatch):
        adapter = _adapter(tmp_path)
        bridge_path = tmp_path / "bridge.js"
        bridge_path.write_text("// on-disk bridge", encoding="utf-8")
        adapter._probe_bridge_health = lambda: self._probe(
            {"status": "connected", "scriptHash": wa._file_content_hash(bridge_path),
             "sendReadReceipts": adapter._send_read_receipts})
        adapter._attach_to_bridge = Mock()
        adapter._wire_plugin_handlers = Mock()

        with caplog.at_level(logging.INFO, logger=wa.logger.name):
            assert asyncio.run(adapter._reuse_running_bridge(bridge_path)) is True

        assert any("Using existing bridge" in r.getMessage() for r in caplog.records)

    _LIFECYCLE_METHODS = (
        "_ensure_bridge_deps", "_reuse_running_bridge", "_bridge_died", "_discard_unbound_bridge",
        "_poll_bridge_health", "_wait_for_bridge", "connect", "_report_bridge_exit", "disconnect",
    )

    def test_no_bare_print_in_bridge_lifecycle_methods(self):
        """Source contract: no bridge-lifecycle method calls print() directly; each goes through
        _bridge_note, which mirrors to the logger. Reverting any one site goes red here, and a
        renamed method fails loudly instead of silently leaving the contract vacuous."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(wa))
        methods = {node.name: node for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in self._LIFECYCLE_METHODS if name not in methods]
        assert not missing, f"lifecycle methods renamed or gone: {missing}"
        offenders = [(name, call.lineno) for name in self._LIFECYCLE_METHODS
                     for call in ast.walk(methods[name])
                     if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print"]
        assert not offenders, f"bare print() in a bridge-lifecycle method: {offenders}"
