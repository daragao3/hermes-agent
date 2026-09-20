"""A spawned bridge that has not bound gets KILLED AND REPLACED, not waited on.

EVIDENCE (loops ``whatsapp-httpup-budget-live-proof-20260920``, MemPalace drawer
``hermes/whatsapp-httpup-budget-verdict-2026-09-20``). 1f12f8d8c4 widened phase 1 of
``_wait_for_bridge`` from a hardcoded 15 polls to the declared connect budget (55 s at
``connect_timeout_secs`` 90), on the 2026-09-18 reading that node was merely slow to bind under
load. The FIRST production episode after it armed disproved that premise, local EDT, gateway pid
50268 on code_sha 9634af177b:

  23:39:42.925  bridge process exited unexpectedly (code 15 = terminated, not a crash)
  23:41:29      Bridge found        -> 23:42:28  "did not start in 55s"     attempt 1 FAILED (59 s)
  23:43:24      Bridge found        -> 23:43:36.2 "Bridge ready (connected)" attempt 2 OK (11.3 s)

Same host load for both (commit 90.5-92.3 %, phys_free 8.0-9.0 GB). ``profiles/main/whatsapp/bridge.log``
is opened in append mode and contains NOTHING from the failed child -- it jumps straight to the successful
"WhatsApp bridge listening on port 3000" banner, and that banner is the bridge's FIRST output. So the failed
child never reached listen() at all.

THE FAILURE IS BIMODAL, NOT SLOW: fast bind, or never. A 90 s or 120 s phase would most likely have waited
90-120 s and still failed, DELAYING recovery instead of producing it. Attempt 2 succeeding in 11.3 s under
the identical load is the evidence that a prompt respawn is what recovers. The 2026-09-18 reading of
"27-55 s spawn->listen" conflated slow-but-successful binds with never-binds; the one measured success that
day (15:52:31 -> 15:52:58) counts "Bridge found" -> listen, which includes up to ~17 s of pre-spawn probes.

WHAT IS PINNED HERE, as code paths rather than wall-clocks:

* ``_bind_attempt_budget_s()`` is one spawn's slice and is far below ``_http_up_budget_s()``, so several
  attempts fit inside the SAME declared connect budget -- the budget is re-spent, not widened.
* A child alive but not listening at the end of its slice is force-killed and replaced; its pidfile goes
  with it. The total across attempts never exceeds the declared budget.
* A CRASHED child is still reported within ~1 s and is NOT respawned: ``poll()`` gives a deterministic exit
  code (bad creds, EADDRINUSE, broken install) and three identical crashes are noise.
* ``connect()`` really wires the respawn through; the first spawn stays synchronous (22529b8622).
* The final failure sentence still carries the TOTAL budget. ``~/.hermes/bin/whatsapp_httpup_watch.py``
  parses that number and calls anything <= 15 s "OLD-CODE", i.e. "the fix never armed" -- so a per-attempt
  number there, or a respawn note phrased like the failure sentence, would silently poison that detector.
* Each respawn logs a line that matches that tool's SPAWN anchor, so its spawn->ready delta is measured
  against the child that actually bound. Without it the tool keeps the first "Bridge found at" and reports
  the 09-20 recovery as a ~30 s bind instead of 11.3 s.
* The child handle is cleared BEFORE the kill, so this design's deliberate kills cannot be reported as
  crashes by ``_check_managed_bridge_exit`` -- see test_a_discard_never_reads_as_a_crash for why that
  ordering, and not the intentional-exit allowlist, is what holds on Windows.

Mutant checks. Every one was applied to the adapter and MEASURED red before this file was called
meaningful; the named test is the one that must go red, and any collateral is listed because a mutant
that only ever kills one test by accident is not evidence. Eight are surgical, three revert the design.

  surgical:
  - drop ``WHATSAPP_BRIDGE_BIND_ATTEMPT_TIMEOUT``       -> TestAttemptBudgetFitsTheDeclaredBudget::test_env_override_wins
  - ``_terminate_bridge_process(..., force=False)``     -> TestDiscardingAnUnboundChild::test_the_kill_is_forced
  - drop ``_unlink_quietly`` of bridge.pid              -> TestDiscardingAnUnboundChild::test_the_pidfile_goes_with_the_child
  - the failure sentence reports the per-attempt slice  -> TestFailureMessageStaysClassifiable::test_the_sentence_carries_the_total
  - ``connect()`` passes a respawn that never spawns    -> TestConnectWiresTheRespawn::test_connect_spawns_a_fresh_child_per_attempt
  - respawn a CRASHED child too (drop the early return) -> TestCrashedChildIsNotRespawned::test_a_dead_child_is_reported_not_replaced
        (also kills test_whatsapp_bridge_http_up_budget.py::TestDeadBridgeStillReportedImmediately, which is
         the point: the ~1 s crash report is inherited behaviour and must survive this file's arrival)
  - drop the per-respawn watcher anchor note            -> TestFailureMessageStaysClassifiable::test_each_respawn_re_anchors_the_watcher
  - clear ``_bridge_process`` AFTER the kill, not before -> TestDiscardingAnUnboundChild::test_a_discard_never_reads_as_a_crash
        (also kills that class's test_a_kill_that_cannot_reach_the_child_is_reported_not_raised, which
         asserts the handle is gone even when the kill itself failed)
  design reverts, listed with their full blast radius:
  - ``attempts = 1`` at the whole budget, i.e. 1f12f8d8c4 -> 7 red: TestNonBindingChildIsReplaced (both),
        TestARespawnedChildRecovers, TestFailureMessageStaysClassifiable (all three), TestConnectWiresTheRespawn
  - ``_bind_attempt_budget_s`` returns ``_http_up_budget_s()`` -> 5 red, adding
        TestAttemptBudgetFitsTheDeclaredBudget::test_one_attempt_is_a_fraction_of_the_total
  - respawn WITHOUT the discard                          -> 2 red: TestNonBindingChildIsReplaced::
        test_a_child_that_never_binds_is_killed_and_respawned, TestARespawnedChildRecovers

"""

import asyncio
import re
from unittest.mock import Mock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.whatsapp import adapter as wa

# Verbatim from ~/.hermes/bin/whatsapp_httpup_watch.py (HTTP_FAIL). Copied rather than imported:
# that tool lives outside this repo, and a test may not depend on ~/.hermes being checked out.
WATCHER_HTTP_FAIL = re.compile(r"\[Whatsapp\] Bridge HTTP server did not start in (\d+)s")
WATCHER_SPAWN = re.compile(r"\[Whatsapp\] (?:Bridge found at|Bridge started on port)")
WATCHER_OLD_CAP_S = 15


class _Clock:
    """Drives asyncio.sleep instantly while advancing the loop clock the code reads.

    Both bounds in ``_poll_bridge_health`` matter here: the tick count is what terminates the
    loop when ``asyncio.sleep`` is stubbed (tests/gateway/test_whatsapp_connect.py does exactly
    that with an AsyncMock, and a deadline-only loop hangs there), and the deadline is what
    stops a slow probe from overshooting the slice.
    """

    def __init__(self, monkeypatch):
        self.t = 0.0
        self.slept = 0.0
        real_sleep = asyncio.sleep

        async def fake_sleep(delay, *a, **kw):
            self.t += delay
            self.slept += delay
            await real_sleep(0)

        monkeypatch.setattr(wa.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(wa.asyncio, "get_running_loop", lambda: self)

    def time(self):
        return self.t


class _FakeChild:
    """A node child that binds ``binds_at`` seconds after ITS OWN spawn, or never."""

    def __init__(self, pid, spawned_at, binds_at):
        self.pid = pid
        self.spawned_at = spawned_at
        self.binds_at = binds_at
        self.returncode = None

    def poll(self):
        return self.returncode


class _Bench:
    """A sequence of children plus an ordered spawn/kill trace.

    ``binds_at[i]`` is how long child *i* takes to answer /health, or None for the 09-20 child
    that never reaches its listen banner. The health probe is answered from the child the
    adapter currently holds, so a test cannot accidentally credit child N's bind to child N-1.
    """

    def __init__(self, adapter, clock, binds_at, monkeypatch, *, dies_with=None):
        self.adapter, self.clock = adapter, clock
        self.binds_at = list(binds_at)
        self.dies_with = dies_with
        self.children = []
        self.events = []
        self.kill_forced = []
        adapter._probe_bridge_health = self._probe
        monkeypatch.setattr(wa, "_terminate_bridge_process", self._terminate)
        monkeypatch.setattr(wa, "_port_is_free", lambda _port: True)
        self.spawn()  # connect() spawns the first child before _wait_for_bridge sees it

    def spawn(self):
        index = len(self.children)
        binds_at = self.binds_at[index] if index < len(self.binds_at) else None
        child = _FakeChild(pid=1000 + index, spawned_at=self.clock.t, binds_at=binds_at)
        if self.dies_with is not None:
            child.returncode = self.dies_with
        self.children.append(child)
        self.adapter._bridge_process = child
        self.events.append(("spawn", child.pid))

    def _terminate(self, proc, *, force=False):
        proc.returncode = -9
        self.kill_forced.append(force)
        self.events.append(("kill", proc.pid))

    async def _probe(self):
        child = self.adapter._bridge_process
        if child is None or child.binds_at is None:
            raise ConnectionRefusedError("never listens")
        if self.clock.t - child.spawned_at < child.binds_at:
            raise ConnectionRefusedError("not listening yet")
        return True, {"status": "connected"}


def _adapter(tmp_path, *, connect_budget: float = 90.0):
    adapter = wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={
        "session_path": str(tmp_path / "session"),
        "bridge_script": str(tmp_path / "bridge.js"),
        "bridge_port": 3999}))
    adapter.connect_timeout_secs = connect_budget
    adapter._bridge_log = tmp_path / "bridge.log"
    adapter._close_bridge_log = Mock()
    (tmp_path / "session").mkdir(parents=True, exist_ok=True)
    return adapter


def _plan(adapter):
    """(attempts, attempt_budget) the adapter will use, derived the way the code derives it."""
    total = adapter._http_up_budget_s()
    attempt_budget = min(adapter._bind_attempt_budget_s(), total)
    return max(1, int(total // attempt_budget)), attempt_budget


class TestAttemptBudgetFitsTheDeclaredBudget:
    def test_one_attempt_is_a_fraction_of_the_total(self, tmp_path):
        """Several attempts must fit the SAME budget -- this is a re-spend, not a widening."""
        adapter = _adapter(tmp_path)
        attempts, attempt_budget = _plan(adapter)

        assert attempt_budget < adapter._http_up_budget_s()
        assert attempts >= 2
        # 09-20 bound in 11.3 s and 09-18's one measured success was under ~27 s including
        # pre-spawn probes; a slice below that would evict children that were going to work.
        assert 12.0 <= attempt_budget <= 20.0

    def test_the_attempts_never_overrun_the_declared_budget(self, tmp_path):
        adapter = _adapter(tmp_path)
        attempts, attempt_budget = _plan(adapter)

        assert attempts * attempt_budget <= adapter._http_up_budget_s()

    def test_a_floor_sized_budget_degrades_to_a_single_attempt(self, tmp_path):
        """At the floor there is no room to divide; one attempt of the whole floor is correct."""
        adapter = _adapter(tmp_path, connect_budget=20.0)
        attempts, attempt_budget = _plan(adapter)

        assert (attempts, attempt_budget) == (1, wa._BRIDGE_HTTP_UP_FLOOR_S)

    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHATSAPP_BRIDGE_BIND_ATTEMPT_TIMEOUT", "5")
        adapter = _adapter(tmp_path)

        assert adapter._bind_attempt_budget_s() == 5.0


class TestNonBindingChildIsReplaced:
    def test_a_child_that_never_binds_is_killed_and_respawned(self, tmp_path, monkeypatch):
        """The 09-20 attempt-1 shape, three times over: kill, replace, kill, replace."""
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None, None, None], monkeypatch)
        attempts, attempt_budget = _plan(adapter)

        assert asyncio.run(adapter._wait_for_bridge(bench.spawn)) is False

        assert len(bench.children) == attempts
        # Each child is killed before its replacement is spawned; the last one is left for
        # the caller's disconnect, exactly as before this change.
        assert bench.events == [
            ("spawn", 1000), ("kill", 1000), ("spawn", 1001), ("kill", 1001), ("spawn", 1002)]
        assert clock.slept == pytest.approx(attempts * attempt_budget, abs=1.5)

    def test_no_single_child_is_waited_on_for_the_whole_budget(self, tmp_path, monkeypatch):
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None, None, None], monkeypatch)
        _attempts, attempt_budget = _plan(adapter)

        asyncio.run(adapter._wait_for_bridge(bench.spawn))

        killed_at = [c.spawned_at for c in bench.children[1:]]
        waited = [end - start for start, end in zip([c.spawned_at for c in bench.children], killed_at)]
        assert waited and all(w == pytest.approx(attempt_budget, abs=1.5) for w in waited)


class TestARespawnedChildRecovers:
    def test_the_second_child_binds_and_is_adopted(self, tmp_path, monkeypatch):
        """The measured 09-20 recovery: child 1 never binds, child 2 binds in 11.3 s."""
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None, 11.3], monkeypatch)

        assert asyncio.run(adapter._wait_for_bridge(bench.spawn)) is True

        assert len(bench.children) == 2
        assert adapter._bridge_process is bench.children[1]
        assert bench.children[0].returncode is not None, "the child that never bound must be killed"
        # Recovered strictly inside the budget the old design spent entirely on the dead child.
        assert clock.slept < adapter._http_up_budget_s()


class TestCrashedChildIsNotRespawned:
    def test_a_dead_child_is_reported_not_replaced(self, tmp_path, monkeypatch):
        """``poll()`` answers in ~1 s and the exit code is deterministic; retrying it is noise."""
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None, None, None], monkeypatch, dies_with=1)

        assert asyncio.run(adapter._wait_for_bridge(bench.spawn)) is False

        assert len(bench.children) == 1
        assert bench.events == [("spawn", 1000)]
        assert clock.slept <= 2


class TestDiscardingAnUnboundChild:
    def _discard(self, tmp_path, monkeypatch):
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None], monkeypatch)
        (adapter._session_path / "bridge.pid").write_text("1000\n1.0", encoding="utf-8")

        asyncio.run(adapter._discard_unbound_bridge())
        return adapter, bench

    def test_the_kill_is_forced(self, tmp_path, monkeypatch):
        """There is nothing graceful to wait for: this child never produced a listen banner."""
        _adapter_, bench = self._discard(tmp_path, monkeypatch)

        assert bench.kill_forced == [True]

    def test_the_pidfile_goes_with_the_child(self, tmp_path, monkeypatch):
        adapter, _bench = self._discard(tmp_path, monkeypatch)

        assert not (adapter._session_path / "bridge.pid").exists()
        assert adapter._bridge_process is None

    def test_a_discard_never_reads_as_a_crash(self, tmp_path, monkeypatch):
        """The handle is cleared BEFORE the kill, so nothing can report our own kill as a crash.

        Cross-note on loops whatsapp-bridge-kill-attribution-20260920, verified here against
        the code rather than taken on report: ``_check_managed_bridge_exit`` suppresses an
        intentional exit only for ``{0, -2, -15}``, but on Windows this adapter kills through
        psutil and ``Popen.poll()`` then returns **+15** -- so that allowlist can never match a
        bridge this adapter killed, and a deliberate kill sets a fatal error, notifies, and
        queues a background reconnect. A fail-fast design kills on purpose several times per
        connect, so it would trip that every time.

        What saves it is ordering, not the allowlist: the ``poll()`` in that check is guarded by
        ``self._bridge_process is not None``, and ``_discard_unbound_bridge`` clears the handle
        first. Fixing the sign belongs to that other claim; this test pins the ordering the
        respawn loop depends on regardless of how that is resolved.
        """
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None], monkeypatch)
        seen = []

        def terminate(proc, *, force=False):
            seen.append(adapter._bridge_process)
            proc.returncode = 15  # what psutil kill() actually yields on Windows

        monkeypatch.setattr(wa, "_terminate_bridge_process", terminate)

        asyncio.run(adapter._discard_unbound_bridge())

        assert seen == [None], "the handle must be cleared before the kill, not after"
        assert asyncio.run(adapter._check_managed_bridge_exit()) is None
        assert not adapter.has_fatal_error
        assert bench.children[0].returncode == 15

    def test_a_kill_that_cannot_reach_the_child_is_reported_not_raised(self, tmp_path, monkeypatch):
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None], monkeypatch)
        monkeypatch.setattr(wa, "_terminate_bridge_process",
                            Mock(side_effect=OSError("tree kill did not reach bridge PID 1000")))
        notes = []
        adapter._bridge_note = notes.append

        asyncio.run(adapter._discard_unbound_bridge())

        assert any("Could not kill the unbound bridge" in note for note in notes)
        assert adapter._bridge_process is None
        assert bench.children[0].returncode is None


class TestFailureMessageStaysClassifiable:
    def _notes(self, tmp_path, monkeypatch):
        adapter = _adapter(tmp_path)
        clock = _Clock(monkeypatch)
        bench = _Bench(adapter, clock, [None, None, None], monkeypatch)
        notes = []
        adapter._bridge_note = notes.append

        asyncio.run(adapter._wait_for_bridge(bench.spawn))
        return adapter, [f"[Whatsapp] {note}" for note in notes]

    def test_the_sentence_carries_the_total(self, tmp_path, monkeypatch):
        """whatsapp_httpup_watch.py reads this number; the per-attempt slice would misreport it."""
        adapter, notes = self._notes(tmp_path, monkeypatch)
        attempts, attempt_budget = _plan(adapter)

        matched = [int(m.group(1)) for m in (WATCHER_HTTP_FAIL.search(n) for n in notes) if m]
        assert matched == [attempts * attempt_budget]
        assert matched[0] > WATCHER_OLD_CAP_S, "the watcher would read this as OLD-CODE"

    def test_a_respawn_note_is_not_mistaken_for_the_failure(self, tmp_path, monkeypatch):
        """Two respawn notes matching HTTP_FAIL would post two phantom BUDGET-SHORT verdicts."""
        _adapter_, notes = self._notes(tmp_path, monkeypatch)

        respawns = [n for n in notes if "respawning" in n]
        assert len(respawns) == 2
        assert not any(WATCHER_HTTP_FAIL.search(n) for n in respawns)

    def test_each_respawn_re_anchors_the_watcher(self, tmp_path, monkeypatch):
        """The tool measures spawn->ready from its last SPAWN line.

        With no fresh anchor it keeps the first "Bridge found at" and credits the dead
        child's whole slice to the child that actually bound -- reporting a 30 s bind for
        the 11.3 s recovery this design exists to produce.
        """
        adapter, notes = self._notes(tmp_path, monkeypatch)
        attempts, _attempt_budget = _plan(adapter)

        anchors = [n for n in notes if WATCHER_SPAWN.search(n)]
        assert len(anchors) == attempts - 1
        for index, note in enumerate(anchors, start=2):
            assert f"attempt {index} of {attempts}" in note


class TestConnectWiresTheRespawn:
    @pytest.mark.asyncio
    async def test_connect_spawns_a_fresh_child_per_attempt(self, tmp_path, monkeypatch):
        """End to end through connect(): the respawn it passes must really Popen again."""
        adapter = _adapter(tmp_path)
        (tmp_path / "bridge.js").write_text("// bridge", encoding="utf-8")
        (tmp_path / "session" / "creds.json").write_text("{}", encoding="utf-8")
        clock = _Clock(monkeypatch)
        attempts, _attempt_budget = _plan(adapter)

        spawned = []

        def fake_popen(argv, **kwargs):
            child = _FakeChild(pid=2000 + len(spawned), spawned_at=clock.t, binds_at=None)
            spawned.append(child)
            return child

        async def never():
            raise ConnectionRefusedError("never listens")

        adapter._probe_bridge_health = never
        monkeypatch.setattr(wa.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(wa, "_terminate_bridge_process", lambda proc, *, force=False: None)
        monkeypatch.setattr(wa, "_port_is_free", lambda _port: True)
        monkeypatch.setattr(wa, "_kill_stale_bridge_by_pidfile", lambda _session: None)
        monkeypatch.setattr(wa, "check_whatsapp_requirements", lambda: True)
        monkeypatch.setattr(wa, "find_node_executable", lambda _name: "node")
        monkeypatch.setattr(adapter, "_ensure_bridge_deps", lambda _dir: True)
        monkeypatch.setattr(adapter, "_acquire_platform_lock", lambda *a, **k: True)
        monkeypatch.setattr(adapter, "_release_platform_lock", lambda *a, **k: None)

        assert await adapter.connect() is False
        assert len(spawned) == attempts
