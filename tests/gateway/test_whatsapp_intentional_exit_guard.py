"""A bridge WE killed is not a crash -- and on Windows the old allowlist could never say so.

THE DEFECT (loops ``whatsapp-bridge-kill-attribution-20260920``, cross-noted on
``whatsapp-bridge-failfast-respawn-20260920``). ``_check_managed_bridge_exit`` suppressed the
fatal only when ``returncode in {0, -2, -15}`` -- the POSIX "killed by signal N -> -N"
convention. On Windows ``Popen.poll()`` returns the raw ``TerminateProcess`` code, and every
kill this adapter issues runs ``_terminate_bridge_process`` -> ``windows_kill_popen_tree`` ->
``windows_kill_pid`` -> ``psutil.Process.kill()``. MEASURED on this box, both directions:

    psutil kill()                            -> Popen.poll() == 15
    psutil terminate()                       -> Popen.poll() == 15
    windows_kill_popen_tree                  -> Popen.poll() == 15
    _terminate_bridge_process(force=True)    -> Popen.poll() == 15
    _terminate_bridge_process(force=False)   -> Popen.poll() == 15
    Popen.terminate() / Popen.kill()         -> Popen.poll() == 1     (the fallback branches)

The adapter produced +15 and the allowlist tested for -15, so the branch was DEAD CODE here
and every planned shutdown logged ERROR "[Whatsapp] WhatsApp bridge process exited
unexpectedly (code 15)", set the ``whatsapp_bridge_exited`` fatal, fired
``_notify_fatal_error()`` and queued a background reconnect -- while ``_shutting_down`` was
True and ``disconnect()`` was running normally. Four such lines in
``profiles/main/logs/errors-gateway.log`` on 2026-09-19/20, each matching a gateway
``--replace``; the 2026-09-19 23:39:42 one is attributed in full on that claim.

WHY THE TESTS HERE SPAWN REAL CHILDREN. A unit test that hands the guard a hand-written
``-15`` passes on trunk and proves nothing: that number is exactly what this platform never
produces. So every suppression test below kills a REAL ``subprocess.Popen`` through the
adapter's OWN primitive and reads back whatever ``poll()`` actually returns. The tests are
platform-neutral by construction -- they assert on behaviour, not on a number -- and
``test_the_old_allowlist_could_never_match_what_we_produce`` pins the platform fact itself so
the numbers above stay falsifiable rather than remaining a claim in a docstring.

THE FIX IS A NARROWER GATE, NOT A WIDER SET. ``_shutting_down`` alone decides; the exit code
is logged and never filtered on. Rationale in ``_check_managed_bridge_exit``'s docstring, in
one line here: normalising by sign (``abs(returncode) in {0, 2, 15}``) swaps one arbitrary set
for another -- it is still blind to the exit-1 fallback branches, and 15 and 1 are not
reserved to us, so a node child dying of EADDRINUSE could match it. THAT is where
over-suppression would come from. The flag cannot over-suppress in any way that costs
anything, because it is one-way per instance (set only at the top of ``disconnect()``, never
reset) and a queued platform reconnects through a FRESH adapter from ``_create_adapter``
(gateway/run_adapters.py) -- so while it is True this adapter is terminal, and the three
things suppressed are a fatal flag, a user notification and a reconnect queued for a platform
the gateway is deliberately shutting down.

NOT COVERED, DELIBERATELY: the fail-fast respawn path. ``_discard_unbound_bridge`` kills with
``_shutting_down`` FALSE, so this gate never fires for it -- its safety is that it clears
``self._bridge_process`` BEFORE killing. ``TestTheRespawnPathStillRidesOnOrdering`` pins that
the ordering is still the entire protection there, so nobody reads this fix as licence to
drop it. ``test_whatsapp_bridge_failfast_respawn.py::TestDiscardingAnUnboundChild::
test_a_discard_never_reads_as_a_crash`` stays green either way -- it asserts the handle is
already None -- and is unchanged by this commit.

Mutant checks. Each was applied to the adapter and MEASURED red against its named test;
collateral is listed, because a mutant that kills one test by accident is not evidence.

  - restore ``and returncode in {0, -2, -15}``        -> TestAKillWeIssuedIsNotACrash::
        test_a_real_kill_through_the_adapters_own_primitive_is_suppressed   (Windows)
        (also kills that class's test_the_graceful_direction_is_suppressed_too,
         test_a_fallback_kill_is_suppressed_too and
         test_nothing_is_queued_for_reconnect_during_a_teardown -- all four are real kills)
  - normalise by sign, ``abs(returncode) in {0, 2, 15}`` -> TestAKillWeIssuedIsNotACrash::
        test_a_fallback_kill_is_suppressed_too   (Windows: the fallback yields 1, not 15)
  - drop the ``_shutting_down`` gate (suppress always) -> TestACrashIsStillFatal (all three)
        (also kills TestTheRespawnPathStillRidesOnOrdering::test_this_gate_does_not_cover_a_discard,
         which is the point: that test asserts the gate stays SILENT outside a teardown)
  - clear ``_bridge_process`` AFTER the kill in ``_discard_unbound_bridge``
        -> TestTheRespawnPathStillRidesOnOrdering::test_the_ordering_is_the_entire_protection
        (also kills test_whatsapp_bridge_failfast_respawn.py::TestDiscardingAnUnboundChild::
         test_a_discard_never_reads_as_a_crash, which is the point: that ordering is shared.
         THAT collateral is the only reason this mutant was caught at all on the first sweep --
         the first draft of test_the_ordering_is_the_entire_protection SURVIVED it by asserting
         the end state; see that test's docstring.)
"""

import asyncio
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.whatsapp import adapter as wa

IS_WINDOWS = sys.platform == "win32"

# The exact set the guard used to require. Named so the tests below can say what they disprove.
OLD_POSIX_ONLY_ALLOWLIST = {0, -2, -15}


def _adapter(tmp_path):
    adapter = wa.WhatsAppAdapter(PlatformConfig(enabled=True, extra={
        "session_path": str(tmp_path / "session"),
        "bridge_script": str(tmp_path / "bridge.js"),
        "bridge_port": 3999}))
    (tmp_path / "session").mkdir(parents=True, exist_ok=True)
    adapter._close_bridge_log = Mock()
    adapter._write_runtime_status_safe = Mock()  # no status-file writes from a unit test
    adapter.notified = []
    adapter.set_fatal_error_handler(lambda a: adapter.notified.append(a.fatal_error_message))
    return adapter


def _spawn_real_child(body: str = "import time; time.sleep(120)") -> subprocess.Popen:
    """A real OS process, so ``poll()`` returns whatever this platform really produces."""
    return subprocess.Popen([sys.executable, "-c", body],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _reaped(proc: subprocess.Popen, timeout_s: float = 15.0) -> int:
    """Block until ``poll()`` reports; returns the code the OS actually gave us."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            return rc
        time.sleep(0.05)
    proc.kill()
    raise AssertionError("child pid %s never exited within %ss" % (proc.pid, timeout_s))


def _adapter_over_a_dead_child(tmp_path, proc, shutting_down):
    adapter = _adapter(tmp_path)
    adapter._bridge_process = proc
    adapter._shutting_down = shutting_down
    adapter._running = True  # _set_fatal_error() clears this, so it witnesses whether the fatal ran
    return adapter


class TestAKillWeIssuedIsNotACrash:
    """Every kill here is a REAL one through the adapter's own primitive, never a literal."""

    def test_a_real_kill_through_the_adapters_own_primitive_is_suppressed(self, tmp_path):
        proc = _spawn_real_child()
        wa._terminate_bridge_process(proc, force=True)
        rc = _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, True)

        assert asyncio.run(adapter._check_managed_bridge_exit()) is None, (
            "a kill we issued ourselves was reported as a crash (poll() == %s)" % rc)
        assert not adapter.has_fatal_error
        assert adapter.notified == []

    def test_the_graceful_direction_is_suppressed_too(self, tmp_path):
        """``disconnect()`` tries force=False first; on Windows that is the same TerminateProcess."""
        proc = _spawn_real_child()
        wa._terminate_bridge_process(proc, force=False)
        rc = _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, True)

        assert asyncio.run(adapter._check_managed_bridge_exit()) is None, "poll() == %s" % rc
        assert not adapter.has_fatal_error

    def test_a_fallback_kill_is_suppressed_too(self, tmp_path, monkeypatch):
        """The walk can fail, and both fallbacks land on ``Popen.terminate()``/``kill()``.

        ``_terminate_bridge_process`` falls back when ``windows_kill_popen_tree`` raises, and
        ``_terminate_bridge`` falls back on ProcessLookupError/PermissionError. On Windows those
        yield **1**, not 15 -- which is why ``abs(returncode) in {0, 2, 15}`` would still be a
        guess. Driven through the real fallback branch on Windows, not simulated.
        """
        proc = _spawn_real_child()
        if IS_WINDOWS:
            import hermes_cli._subprocess_compat as compat
            monkeypatch.setattr(compat, "windows_kill_popen_tree",
                                Mock(side_effect=OSError("snapshot unavailable")))
            wa._terminate_bridge_process(proc, force=True)
        else:
            proc.terminate()
        rc = _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, True)

        assert asyncio.run(adapter._check_managed_bridge_exit()) is None, (
            "the fallback kill path reported as a crash (poll() == %s)" % rc)
        assert not adapter.has_fatal_error

    def test_nothing_is_queued_for_reconnect_during_a_teardown(self, tmp_path):
        """The live symptom: a fatal + a notification + a reconnect, all during a planned stop.

        ``_queue_retryable_fatal_platform`` runs off ``adapter.fatal_error_retryable``, but only
        for an adapter that HAS a fatal error -- and ``fatal_error_retryable`` defaults to True,
        so asserting it is False here would be asserting the wrong thing. The faithful assertion
        is that ``_set_fatal_error`` never ran at all, witnessed three independent ways: no
        message, no notification, and ``_running`` still True (that method clears it).
        """
        proc = _spawn_real_child()
        wa._terminate_bridge_process(proc, force=True)
        _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, True)

        assert asyncio.run(adapter._check_managed_bridge_exit()) is None
        assert adapter.fatal_error_message is None
        assert adapter.notified == []
        assert adapter._running is True

    @pytest.mark.skipif(not IS_WINDOWS, reason="the sign convention under test is Windows-specific")
    def test_the_old_allowlist_could_never_match_what_we_produce(self, tmp_path):
        """The defect itself, as an executable fact rather than a claim in a docstring."""
        proc = _spawn_real_child()
        wa._terminate_bridge_process(proc, force=True)
        rc = _reaped(proc)

        assert rc == 15, "expected psutil's TerminateProcess code, got %s" % rc
        assert rc not in OLD_POSIX_ONLY_ALLOWLIST, (
            "the POSIX allowlist would have matched -- re-read this file's header before "
            "concluding the sign fix is unnecessary")


class TestACrashIsStillFatal:
    """The control. Without these, a guard that suppresses everything passes the class above."""

    def test_a_child_that_dies_on_its_own_is_still_reported(self, tmp_path):
        proc = _spawn_real_child("import sys; sys.exit(3)")
        rc = _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, False)

        message = asyncio.run(adapter._check_managed_bridge_exit())
        assert message and ("code %s" % rc) in message
        assert adapter.has_fatal_error
        assert adapter.notified == [message]
        assert adapter._running is False  # the control for the teardown test's _running assertion

    def test_the_very_code_we_produce_is_fatal_when_we_are_not_shutting_down(self, tmp_path):
        """A bridge killed by someone ELSE looks identical on the wire; only the flag differs.

        This is what stops the fix from becoming "suppress 15 everywhere": the exact kill that
        ``test_a_real_kill_through_the_adapters_own_primitive_is_suppressed`` waves through must
        still be fatal outside a teardown.
        """
        proc = _spawn_real_child()
        wa._terminate_bridge_process(proc, force=True)
        rc = _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, False)

        message = asyncio.run(adapter._check_managed_bridge_exit())
        assert message and ("code %s" % rc) in message
        assert adapter.has_fatal_error

    def test_a_clean_exit_zero_is_still_fatal_when_not_shutting_down(self, tmp_path):
        """0 was in the old set, but the flag always gated it too; the gate did not move."""
        proc = _spawn_real_child("import sys; sys.exit(0)")
        _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, False)

        assert asyncio.run(adapter._check_managed_bridge_exit())
        assert adapter.has_fatal_error


class TestTheRespawnPathStillRidesOnOrdering:
    """This fix does NOT cover ``_discard_unbound_bridge``; pin that, so nobody assumes it does."""

    def test_this_gate_does_not_cover_a_discard(self, tmp_path):
        """A respawn kill happens with ``_shutting_down`` False, so the new gate is silent for it."""
        proc = _spawn_real_child()
        wa._terminate_bridge_process(proc, force=True)
        _reaped(proc)
        adapter = _adapter_over_a_dead_child(tmp_path, proc, False)

        assert asyncio.run(adapter._check_managed_bridge_exit()), (
            "if this ever starts returning None, the discard ordering below became untested")

    def test_the_ordering_is_the_entire_protection(self, tmp_path, monkeypatch):
        """Clearing the handle BEFORE the kill is what a real discard relies on.

        THE END STATE IS NOT ENOUGH TO PIN THIS, and the first draft of this test got it wrong:
        whichever order ``_discard_unbound_bridge`` uses, the handle is None by the time it
        returns, so an end-state assertion sails past a mutant that clears it AFTER the kill
        (measured -- that draft SURVIVED the mutant it was written to catch). So observe the
        handle AT KILL TIME, while still killing a real child through the real primitive.
        """
        adapter = _adapter(tmp_path)
        adapter._shutting_down = False
        adapter._running = True
        adapter._bridge_process = proc = _spawn_real_child()
        (adapter._session_path / "bridge.pid").write_text(str(proc.pid), encoding="utf-8")
        real_terminate = wa._terminate_bridge_process
        seen = []

        def observing_terminate(p, *, force=False):
            seen.append(adapter._bridge_process)
            return real_terminate(p, force=force)

        monkeypatch.setattr(wa, "_terminate_bridge_process", observing_terminate)

        asyncio.run(adapter._discard_unbound_bridge())
        _reaped(proc)

        assert seen == [None], "the handle must be cleared BEFORE the kill, not after"
        assert adapter._bridge_process is None
        assert asyncio.run(adapter._check_managed_bridge_exit()) is None
        assert not adapter.has_fatal_error
        assert adapter._running is True
