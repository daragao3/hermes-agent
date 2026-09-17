"""Progress-aware timeout around in-agent compress_context (#72016).

In-loop / preflight / manual ``/compress`` paths historically waited on
``compress_context`` with no host-level inactivity budget. Gateway session
hygiene already had a progress-aware wait; these tests pin the same contract
for the owned wrapper used when callers do not pass a ``commit_fence``.
"""

from __future__ import annotations

import concurrent.futures
import socket
import threading
import time
from unittest.mock import MagicMock

import pytest

import agent.conversation_compression as cc
from agent.conversation_compression import (
    CompressionCommitFence,
    context_compression_timed_out,
    mark_context_compression_timed_out,
    reset_context_compression_timeout_outcome,
    resolve_context_compression_timeouts,
    run_compress_context_with_progress_timeout,
)

# Wait budgets (AGENTS.md flake policy: wall-clock bounds >= 2 s, event-based sync). Every
# positive wait returns the instant its Event is set, so a generous bound costs nothing green.
#   _HANDOFF_S  -- a signal between two threads that are BOTH already running: the floor.
#   _PICKUP_S   -- a signal that first needs a thread or pool worker to be SCHEDULED
#                  (Thread.start / executor.submit). A loaded -j 12 runner has left such
#                  threads unstarted past 0.1 s (2026-09-17, F6 BrokenBarrierError), so the
#                  budget is well above the floor.
#   _START_WINDOW_S -- idle/ceiling windows a test's worker must START inside. The idle
#                  clock runs from fence creation, so a pickup slower than the window makes
#                  the host cancel pre-commit and the pre-start gate skips the worker: the
#                  test then fails exactly as a product bug would. Never below the floor.
#   _HANG_NET_S -- a worker-side cap on an event the TEST releases only after the host has
#                  returned. It must outlast the host's whole timeout path under load (1.4 s
#                  measured loaded against the old 2 s cap), not race it; pytest-timeout is
#                  the real backstop, and a host that never times out still fails the test
#                  once the net expires and the worker's late result reaches the assertions.
_HANDOFF_S = 2.0
_PICKUP_S = 5.0
_START_WINDOW_S = 2.0
_HANG_NET_S = 30.0


class TestContextCompressionTimeoutState:
    """Thread-safe typed timeout state (#98741, on top of #98424's flag)."""

    def test_timeout_state_first_use_is_atomic(self, monkeypatch):
        from types import SimpleNamespace

        agent = SimpleNamespace()
        reset_constructor_entered = threading.Event()
        marker_constructor_finished = threading.Event()
        release_reset_constructor = threading.Event()
        reset_finished = threading.Event()
        marker_finished = threading.Event()
        seen = {}
        original_local = threading.local

        class DelayedLocal(original_local):
            def __new__(cls):
                state = super().__new__(cls)
                if threading.current_thread().name == "timeout-resetter":
                    reset_constructor_entered.set()
                    # Released only after the main thread has STARTED mark_thread.
                    assert release_reset_constructor.wait(timeout=_PICKUP_S)
                else:
                    marker_constructor_finished.set()
                return state

        monkeypatch.setattr(cc.threading, "local", DelayedLocal)

        def resetter():
            reset_context_compression_timeout_outcome(agent)
            reset_finished.set()
            assert marker_finished.wait(timeout=_HANDOFF_S)
            seen["resetter"] = context_compression_timed_out(agent)

        def marker():
            mark_context_compression_timed_out(agent)
            marker_finished.set()
            assert reset_finished.wait(timeout=_HANDOFF_S)
            seen["marker"] = context_compression_timed_out(agent)

        reset_thread = threading.Thread(target=resetter, name="timeout-resetter")
        mark_thread = threading.Thread(target=marker, name="timeout-marker")
        reset_thread.start()
        assert reset_constructor_entered.wait(timeout=_PICKUP_S)
        mark_thread.start()

        # A fixed implementation publishes the initialization lock before
        # constructing the state. The old implementation lets the marker
        # publish a competing state while the resetter is paused here.
        if "_context_compression_timeout_state_lock" not in vars(agent):
            assert marker_constructor_finished.wait(timeout=_PICKUP_S)
        release_reset_constructor.set()

        reset_thread.join(timeout=_PICKUP_S)
        mark_thread.join(timeout=_PICKUP_S)

        assert not reset_thread.is_alive()
        assert not mark_thread.is_alive()
        assert seen == {"resetter": False, "marker": True}

    def test_timeout_outcome_is_isolated_between_overlapping_entrypoints(self):
        from types import SimpleNamespace

        agent = SimpleNamespace()
        worker_marked = threading.Event()
        main_reset = threading.Event()
        seen = {}

        def worker():
            reset_context_compression_timeout_outcome(agent)
            mark_context_compression_timed_out(agent)
            worker_marked.set()
            assert main_reset.wait(timeout=_HANDOFF_S)
            seen["worker"] = context_compression_timed_out(agent)

        thread = threading.Thread(target=worker)
        thread.start()
        assert worker_marked.wait(timeout=_PICKUP_S)

        reset_context_compression_timeout_outcome(agent)
        seen["main"] = context_compression_timed_out(agent)
        main_reset.set()
        thread.join(timeout=_PICKUP_S)

        assert not thread.is_alive()
        assert seen == {"main": False, "worker": True}

    def test_attribute_fallback_for_minimal_doubles(self):
        class Slotted:
            __slots__ = ("_last_compression_timed_out",)

        agent = Slotted()
        mark_context_compression_timed_out(agent)
        assert context_compression_timed_out(agent) is True
        reset_context_compression_timeout_outcome(agent)
        assert context_compression_timed_out(agent) is False


class TestResolveContextCompressionTimeouts:
    def test_defaults_when_empty_cfg(self):
        idle, ceiling = resolve_context_compression_timeouts({})
        assert idle == 120.0
        assert ceiling == 600.0

    def test_zero_idle_disables_wrapper(self):
        idle, ceiling = resolve_context_compression_timeouts(
            {"context_timeout_seconds": 0}
        )
        assert idle == 0.0
        assert ceiling == 600.0

    def test_ceiling_clamped_to_idle(self):
        idle, ceiling = resolve_context_compression_timeouts(
            {
                "context_timeout_seconds": 90,
                "context_total_ceiling_seconds": 30,
            }
        )
        assert idle == 90.0
        assert ceiling == 90.0


class TestRunCompressContextWithProgressTimeout:
    def test_deadline_before_worker_start_uses_timeout_fallback(self, monkeypatch):
        original = [{"role": "user", "content": "keep-me"}]
        worker = MagicMock()
        fallback = MagicMock(return_value="fallback-prompt")
        timeouts = []

        class _ExpiredBeforeStartExecutor:
            def submit(self, fn, fence):
                fence._deadline = time.monotonic() - 1.0
                future = concurrent.futures.Future()
                try:
                    future.set_result(fn(fence))
                except BaseException as exc:
                    future.set_exception(exc)
                return future

        monkeypatch.setattr(
            cc,
            "_get_compress_timeout_executor",
            _ExpiredBeforeStartExecutor,
        )

        result_msgs, result_prompt = run_compress_context_with_progress_timeout(
            worker=worker,
            messages=original,
            system_prompt_fallback=fallback,
            idle_timeout_seconds=1.0,
            total_ceiling_seconds=1.0,
            on_timeout=lambda idle, waited, since: timeouts.append(
                (idle, waited, since)
            ),
            stall_fallback=False,
        )

        worker.assert_not_called()
        fallback.assert_called_once_with()
        assert result_msgs is original
        assert result_prompt == "fallback-prompt"
        assert len(timeouts) == 1

    def test_silent_worker_times_out_and_preserves_messages(self):
        original = [{"role": "user", "content": "keep-me"}]
        started = threading.Event()
        release = threading.Event()
        commit_attempted = threading.Event()

        def worker(fence: CompressionCommitFence):
            started.set()
            # Released by the test only after the host has returned; under load the
            # old 2 s cap expired first (2026-09-17), which let the worker race the
            # host's cancel instead of provably following it.
            assert release.wait(timeout=_HANG_NET_S)
            if not fence.begin_commit():
                return ([{"role": "assistant", "content": "should-not-land"}], "x")
            try:
                commit_attempted.set()
                return ([{"role": "assistant", "content": "too-late"}], "x")
            finally:
                fence.finish_commit()

        warnings = []

        result_msgs, result_prompt = run_compress_context_with_progress_timeout(
            worker=worker,
            messages=original,
            system_prompt_fallback="fallback-prompt",
            # The worker must START inside the idle window (the idle clock runs
            # from fence creation) or the pre-start gate skips it and `started`
            # is never set; the ceiling stays well above idle so this case keeps
            # exercising inactivity cancellation, not the total-ceiling path.
            idle_timeout_seconds=_START_WINDOW_S,
            total_ceiling_seconds=5 * _START_WINDOW_S,
            on_timeout=lambda idle, waited, since: warnings.append(
                (idle, waited, since)
            ),
        )

        assert started.wait(timeout=_PICKUP_S)
        # Give the waiter time to cancel before releasing the worker.
        time.sleep(0.15)
        release.set()
        # Worker may still be winding down; fence cancel must have won.
        deadline = time.time() + 1.0
        while time.time() < deadline and not commit_attempted.is_set():
            time.sleep(0.01)

        assert result_msgs is original
        assert result_prompt == "fallback-prompt"
        assert warnings, "timeout callback should fire"
        assert not commit_attempted.is_set(), (
            "cancelled fence must block late session mutation"
        )

    def test_progress_extends_idle_budget_until_success(self):
        original = [{"role": "user", "content": "a"}]
        compressed = [{"role": "user", "content": "summarized"}]
        fence_holder: dict = {}

        def worker(fence: CompressionCommitFence):
            fence_holder["fence"] = fence
            # Keep ticking within each idle window so the waiter extends.
            # Round-2 #8 (FLAKY policy): the old 0.1s-idle/0.04s-tick shape
            # left only ~60ms of slack per tick — one slow scheduler pass on
            # a loaded CI box let the idle budget lapse mid-loop. The idle
            # window is now the policy floor (20x margin per 0.1s tick, and
            # the window the worker must START inside), so the loop runs
            # past one full window to keep exercising the extension.
            for _ in range(int(1.5 * _START_WINDOW_S / 0.1)):
                time.sleep(0.1)
                fence.touch_progress()
            if not fence.begin_commit():
                return (original, "aborted")
            try:
                return (compressed, "ok-prompt")
            finally:
                fence.finish_commit()

        result_msgs, result_prompt = run_compress_context_with_progress_timeout(
            worker=worker,
            messages=original,
            system_prompt_fallback="fallback",
            idle_timeout_seconds=_START_WINDOW_S,
            total_ceiling_seconds=5 * _START_WINDOW_S,
        )

        assert result_msgs == compressed
        assert result_prompt == "ok-prompt"
        assert "fence" in fence_holder

    def test_commit_started_before_timeout_returns_worker_result(self):
        original = [{"role": "user", "content": "a"}]
        compressed = [{"role": "assistant", "content": "done"}]
        entered = threading.Event()

        def worker(fence: CompressionCommitFence):
            assert fence.begin_commit()
            entered.set()
            try:
                # Hold the commit until the ceiling has provably passed (the
                # deadline is shared with the host), instead of a fixed sleep
                # racing a sub-floor ceiling.
                while not fence.deadline_exceeded:
                    time.sleep(0.01)
                return (compressed, "committed")
            finally:
                fence.finish_commit()

        result_msgs, result_prompt = run_compress_context_with_progress_timeout(
            worker=worker,
            messages=original,
            system_prompt_fallback="fallback",
            idle_timeout_seconds=_START_WINDOW_S,
            total_ceiling_seconds=_START_WINDOW_S,
        )

        assert entered.wait(timeout=_PICKUP_S)
        assert result_msgs == compressed
        assert result_prompt == "committed"

    def test_never_finishing_commit_waits_past_pre_commit_ceiling(self):
        """Once begin_commit() wins, the commit is waited on to completion —
        but NOT silently.

        context_total_ceiling_seconds bounds the pre-commit (summary) phase.
        A hung SessionDB commit cannot be fence-cancelled; returning early
        would diverge live messages from durable session state. The guarantee
        is: summary phase bounded by ceiling; commit phase logged + surfaced
        (on_commit_overrun + escalating log) if it exceeds it. This pins both
        halves: the waiter blocks past the ceiling AND the overrun is loudly
        reported, never silent.
        """
        import logging

        original = [{"role": "user", "content": "a"}]
        compressed = [{"role": "assistant", "content": "late-commit"}]
        entered = threading.Event()
        release = threading.Event()
        overrun_fired = threading.Event()

        def worker(fence: CompressionCommitFence):
            assert fence.begin_commit()
            entered.set()
            try:
                assert release.wait(timeout=_HANG_NET_S)
                return (compressed, "committed-late")
            finally:
                fence.finish_commit()

        # The worker must begin its commit INSIDE the ceiling (a pickup slower
        # than the ceiling is fence-cancelled pre-commit and never enters).
        ceiling = _START_WINDOW_S
        started = time.monotonic()
        done = {}
        overruns = []

        def on_overrun(waited, ceil):
            overruns.append((waited, ceil))
            overrun_fired.set()

        def run():
            done["result"] = run_compress_context_with_progress_timeout(
                worker=worker,
                messages=original,
                system_prompt_fallback="fallback",
                idle_timeout_seconds=ceiling,
                total_ceiling_seconds=ceiling,
                on_commit_overrun=on_overrun,
            )

        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        comp_logger = logging.getLogger("agent.conversation_compression")
        handler = _Capture(level=logging.WARNING)
        comp_logger.addHandler(handler)
        try:
            t = threading.Thread(target=run, name="commit-hang-waiter")
            t.start()
            assert entered.wait(timeout=_PICKUP_S)
            # Still blocked past the pre-commit ceiling while commit holds
            # the fence: the overrun callback fires only once the ceiling has
            # passed with the commit in flight, so waiting for it (instead of
            # sleeping past the ceiling) is the event this assertion needs.
            assert overrun_fired.wait(timeout=ceiling + _PICKUP_S)
            assert t.is_alive(), (
                "waiter must block on an in-flight commit past ceiling"
            )
            release.set()
            t.join(timeout=_PICKUP_S)
            assert not t.is_alive()
        finally:
            comp_logger.removeHandler(handler)

        waited = time.monotonic() - started
        # Blocking PAST the ceiling is pinned by the overrun callback having fired
        # with the waiter still alive (above); the clock only confirms the host
        # did not return early.
        assert waited >= ceiling
        assert done["result"][0] == compressed
        assert done["result"][1] == "committed-late"
        # The over-ceiling commit wait must NOT be silent: the overrun
        # callback fires exactly once and a WARNING+ log line reports the
        # in-flight commit running past the ceiling.
        assert len(overruns) == 1, overruns
        assert overruns[0][1] == pytest.approx(ceiling)
        assert overruns[0][0] >= ceiling
        overrun_logs = [
            r
            for r in records
            if r.levelno >= logging.WARNING
            and "past the total ceiling" in r.getMessage()
        ]
        assert overrun_logs, (
            "expected a WARNING+ log surfacing the commit-phase ceiling "
            f"overrun; got: {[r.getMessage() for r in records]}"
        )

    def test_commit_overrun_callback_failure_does_not_break_wait(self):
        """A raising on_commit_overrun callback must not abort the commit wait."""
        original = [{"role": "user", "content": "a"}]
        compressed = [{"role": "assistant", "content": "ok"}]
        release = threading.Event()

        overrun_reported = threading.Event()

        def worker(fence: CompressionCommitFence):
            assert fence.begin_commit()
            try:
                assert release.wait(timeout=_HANG_NET_S)
                return (compressed, "done")
            finally:
                fence.finish_commit()

        def boom(waited, ceiling):
            overrun_reported.set()
            raise RuntimeError("callback exploded")

        done = {}

        def run():
            done["result"] = run_compress_context_with_progress_timeout(
                worker=worker,
                messages=original,
                system_prompt_fallback="fallback",
                idle_timeout_seconds=_START_WINDOW_S,
                total_ceiling_seconds=_START_WINDOW_S,
                on_commit_overrun=boom,
            )

        t = threading.Thread(target=run)
        t.start()
        # Release only once the raising callback has provably run (a fixed
        # sleep shorter than the ceiling would release first and never
        # exercise the callback at all).
        assert overrun_reported.wait(timeout=_START_WINDOW_S + _PICKUP_S)
        release.set()
        t.join(timeout=_PICKUP_S)
        assert not t.is_alive()
        assert done["result"] == (compressed, "done")

    def test_rejects_non_positive_idle(self):
        with pytest.raises(ValueError):
            run_compress_context_with_progress_timeout(
                worker=lambda fence: ([], ""),
                messages=[],
                system_prompt_fallback="",
                idle_timeout_seconds=0,
                total_ceiling_seconds=1,
            )


    def test_propagates_conversation_context_into_worker(self):
        from agent.portal_tags import (
            get_conversation_context,
            reset_conversation_context,
            set_conversation_context,
        )

        seen = {}
        token = set_conversation_context("conv-timeout-ctx")
        try:
            def worker(fence: CompressionCommitFence):
                seen["ctx"] = get_conversation_context()
                if not fence.begin_commit():
                    return ([], "")
                try:
                    return ([{"role": "user", "content": "ok"}], "p")
                finally:
                    fence.finish_commit()

            msgs, prompt = run_compress_context_with_progress_timeout(
                worker=worker,
                messages=[{"role": "user", "content": "x"}],
                system_prompt_fallback="fallback",
                idle_timeout_seconds=_START_WINDOW_S,
                total_ceiling_seconds=_START_WINDOW_S,
            )
        finally:
            reset_conversation_context(token)

        assert seen.get("ctx") == "conv-timeout-ctx"
        assert prompt == "p"
        assert msgs[0]["content"] == "ok"

    def test_runs_worker_off_caller_thread(self):
        """Mirror gateway run_in_executor: compress work must leave the caller thread."""
        caller = threading.current_thread().ident
        seen = {}

        def worker(fence: CompressionCommitFence):
            seen["worker"] = threading.current_thread().ident
            if not fence.begin_commit():
                return ([], "")
            try:
                return ([{"role": "user", "content": "ok"}], "p")
            finally:
                fence.finish_commit()

        msgs, prompt = run_compress_context_with_progress_timeout(
            worker=worker,
            messages=[],
            system_prompt_fallback="",
            idle_timeout_seconds=_START_WINDOW_S,
            total_ceiling_seconds=_START_WINDOW_S,
        )
        assert seen.get("worker") is not None
        assert seen["worker"] != caller
        assert prompt == "p"
        assert msgs[0]["content"] == "ok"

    def test_reuses_module_shared_executor(self):
        from tools.daemon_pool import DaemonThreadPoolExecutor
        from agent import conversation_compression as mod

        first = mod._get_compress_timeout_executor()
        second = mod._get_compress_timeout_executor()
        assert first is second
        assert isinstance(first, DaemonThreadPoolExecutor)


class _InlineExecutor:
    """Runs the pooled worker synchronously so its exception is already on the future when the host waits."""

    def submit(self, fn, fence):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(fence))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class TestWorkerTimeoutErrorIsNotAWaitTimeout:
    """Since 3.11 ``concurrent.futures.TimeoutError`` IS the builtin ``TimeoutError`` (so also
    ``socket.timeout``). A worker that *raises* one used to be read by every waiter as "the wait ran out":
    the host looped on an already-finished future for the whole idle budget (a hot spin, reported as a
    stall), the bounded join called the dead worker "did not exit within grace" and kept its lease, and the
    commit-overrun wait would have looped forever."""

    def test_worker_timeout_error_propagates_instead_of_spinning_out_the_idle_budget(self, monkeypatch):
        monkeypatch.setattr(cc, "_get_compress_timeout_executor", _InlineExecutor)

        def worker(_fence):
            raise socket.timeout("The read operation timed out")

        started = time.monotonic()
        with pytest.raises(TimeoutError, match="read operation timed out"):
            run_compress_context_with_progress_timeout(
                worker=worker,
                messages=[{"role": "user", "content": "keep-me"}],
                system_prompt_fallback="fallback-prompt",
                idle_timeout_seconds=4.0,
                total_ceiling_seconds=8.0,
                stall_fallback=False,
            )
        # A dead worker is an exit, not four seconds of silence.
        assert time.monotonic() - started < 2.0

    def test_pre_start_deadline_gate_is_an_exit_so_the_lease_is_released(self, monkeypatch):
        """The host's own gate raises too; that worker never ran, so nothing can outlive it."""

        class _ExpiredBeforeStartExecutor(_InlineExecutor):
            def submit(self, fn, fence):
                fence._deadline = time.monotonic() - 1.0
                return super().submit(fn, fence)

        monkeypatch.setattr(cc, "_get_compress_timeout_executor", _ExpiredBeforeStartExecutor)
        fence = CompressionCommitFence()
        release = MagicMock()
        fence.register_cancelled_lock_release(release)
        causes = []

        result_msgs, _ = run_compress_context_with_progress_timeout(
            worker=MagicMock(),
            messages=[{"role": "user", "content": "keep-me"}],
            system_prompt_fallback="fallback-prompt",
            idle_timeout_seconds=1.0,
            total_ceiling_seconds=1.0,
            on_timeout_cause=lambda total, progress: causes.append(total),
            fence=fence,
            stall_fallback=False,
        )

        assert result_msgs[0]["content"] == "keep-me"
        assert causes == [True], "the gate fires on the total-ceiling path"
        release.assert_called_once_with()

    def test_join_reports_exit_for_a_worker_that_raised_timeout_error(self):
        future = concurrent.futures.Future()
        future.set_exception(socket.timeout("dead"))
        assert cc._join_cancelled_worker(future, 0.5) is True

    def test_committing_worker_timeout_error_ends_the_overrun_wait(self):
        future = concurrent.futures.Future()
        future.set_exception(socket.timeout("dead mid-commit"))
        with pytest.raises(TimeoutError, match="dead mid-commit"):
            cc._await_in_flight_commit(
                future, ceiling=0.05, wait_started=time.monotonic(), on_commit_overrun=None
            )


class TestCompressContextForwarderOwnsTimeout:
    """AIAgent._compress_context wraps when no caller fence is supplied."""

    def test_owned_timeout_skips_hung_compress(self, monkeypatch):
        from run_agent import AIAgent

        agent = object.__new__(AIAgent)
        agent.session_id = "s1"
        agent._cached_system_prompt = "sys"
        agent._emit_warning = MagicMock()
        agent._touch_activity = MagicMock()
        agent._build_system_prompt = MagicMock(return_value="sys")
        agent._conversation_root_id = MagicMock(return_value=None)
        agent.context_compressor = MagicMock()
        agent.context_compressor._consecutive_timeout_failures = 0
        # Use the real record_timeout_failure method so the cooldown ladder
        # is exercised end-to-end (not auto-mocked by MagicMock).
        from agent.context_compressor import ContextCompressor
        agent.context_compressor.record_timeout_failure = (
            ContextCompressor.record_timeout_failure.__get__(
                agent.context_compressor, MagicMock
            )
        )
        agent.context_compressor._record_compression_failure_cooldown = MagicMock()

        hang = threading.Event()
        calls = {"n": 0}

        def fake_compress(agent_obj, messages, system_message, **kwargs):
            calls["n"] += 1
            fence = kwargs.get("commit_fence")
            assert fence is not None
            hang.wait(timeout=_HANG_NET_S)
            if not fence.begin_commit():
                return messages, "sys"
            try:
                return ([{"role": "assistant", "content": "nope"}], "sys")
            finally:
                fence.finish_commit()

        monkeypatch.setattr(
            "agent.conversation_compression.compress_context",
            fake_compress,
        )
        # (idle, ceiling): the fake compress must START inside the idle window
        # (calls["n"] == 1 below), and idle stays well under the ceiling so the
        # host still takes the inactivity path this test pins.
        monkeypatch.setattr(
            "agent.conversation_compression.resolve_context_compression_timeouts",
            lambda compression_cfg=None: (_START_WINDOW_S, 4 * _START_WINDOW_S),
        )
        monkeypatch.setattr(
            "agent.portal_tags.get_conversation_context",
            lambda: object(),
        )

        original = [{"role": "user", "content": "stay"}]
        out_msgs, out_prompt = AIAgent._compress_context(
            agent, original, "sys"
        )
        hang.set()

        assert out_msgs is original
        assert out_prompt == "sys"
        assert agent._last_compression_timed_out is True
        assert calls["n"] == 1
        agent._emit_warning.assert_called_once()
        assert agent.context_compressor._consecutive_timeout_failures == 1
        agent.context_compressor._record_compression_failure_cooldown.assert_called_once()
        cooldown_args = (
            agent.context_compressor._record_compression_failure_cooldown.call_args[0]
        )
        assert cooldown_args[0] == 60.0
        assert "host compress_context timeout" in cooldown_args[1]
        from agent.session_activity import ActivityProvenance

        agent._touch_activity.assert_called_with(
            "context compression timed out",
            provenance=ActivityProvenance.AGENT_COMPRESSION_TIMEOUT,
        )

    def test_owned_total_ceiling_reports_progress_accurately(self, monkeypatch):
        from run_agent import AIAgent
        from agent.context_compressor import ContextCompressor

        agent = object.__new__(AIAgent)
        agent.session_id = "s1"
        agent._cached_system_prompt = "sys"
        agent._emit_warning = MagicMock()
        agent._touch_activity = MagicMock()
        agent._build_system_prompt = MagicMock(return_value="sys")
        agent._conversation_root_id = MagicMock(return_value=None)
        agent.context_compressor = MagicMock()
        agent.context_compressor._consecutive_timeout_failures = 0
        agent.context_compressor.record_timeout_failure = (
            ContextCompressor.record_timeout_failure.__get__(
                agent.context_compressor, MagicMock
            )
        )
        agent.context_compressor._record_compression_failure_cooldown = MagicMock()

        release = threading.Event()

        def streaming_compress(agent_obj, messages, system_message, **kwargs):
            fence = kwargs["commit_fence"]
            while not fence.deadline_exceeded:
                fence.touch_progress()
                time.sleep(0.005)
            release.wait(timeout=_HANG_NET_S)
            return messages, "sys"

        monkeypatch.setattr(
            "agent.conversation_compression.compress_context",
            streaming_compress,
        )
        # The streaming worker must START inside the idle window; once running its
        # progress touches keep idle from firing, so the ceiling is the path taken.
        monkeypatch.setattr(
            "agent.conversation_compression.resolve_context_compression_timeouts",
            lambda compression_cfg=None: (_START_WINDOW_S, _START_WINDOW_S),
        )
        monkeypatch.setattr(
            "agent.conversation_compression.resolve_compression_fallback_route",
            lambda: None,
        )
        monkeypatch.setattr(
            "agent.portal_tags.get_conversation_context",
            lambda: object(),
        )

        original = [{"role": "user", "content": "stay"}]
        try:
            out_msgs, out_prompt = AIAgent._compress_context(
                agent, original, "sys"
            )
        finally:
            release.set()

        assert out_msgs is original
        assert out_prompt == "sys"
        warning = agent._emit_warning.call_args.args[0]
        assert "total ceiling" in warning
        assert "summary output was observed" in warning
        assert "no output" not in warning
        cooldown_error = (
            agent.context_compressor._record_compression_failure_cooldown
            .call_args.args[1]
        )
        assert "total ceiling exhausted" in cooldown_error

    def test_fallback_prompt_resolved_lazily_on_timeout(self, monkeypatch):
        """Eager prompt rebuild must not run before compression starts."""
        from run_agent import AIAgent

        agent = object.__new__(AIAgent)
        agent.session_id = "s1"
        agent._cached_system_prompt = None
        agent._emit_warning = MagicMock()
        agent._touch_activity = MagicMock()
        agent._conversation_root_id = MagicMock(return_value=None)
        agent.context_compressor = MagicMock()
        agent.context_compressor._consecutive_timeout_failures = 0
        agent.context_compressor._record_compression_failure_cooldown = MagicMock()
        builds = {"n": 0}

        def boom_build(*_a, **_kw):
            builds["n"] += 1
            raise RuntimeError("prompt rebuild boom")

        agent._build_system_prompt = boom_build

        hang = threading.Event()

        def fake_compress(agent_obj, messages, system_message, **kwargs):
            hang.wait(timeout=_HANG_NET_S)
            fence = kwargs.get("commit_fence")
            if fence is not None and not fence.begin_commit():
                return messages, "sys"
            return messages, "sys"

        monkeypatch.setattr(
            "agent.conversation_compression.compress_context",
            fake_compress,
        )
        monkeypatch.setattr(
            "agent.conversation_compression.resolve_context_compression_timeouts",
            lambda compression_cfg=None: (_START_WINDOW_S, 4 * _START_WINDOW_S),
        )
        monkeypatch.setattr(
            "agent.portal_tags.get_conversation_context",
            lambda: object(),
        )

        original = [{"role": "user", "content": "stay"}]
        out_msgs, out_prompt = AIAgent._compress_context(
            agent, original, "sys"
        )
        hang.set()

        assert out_msgs is original
        assert out_prompt == "sys"
        # Fallback rebuild runs only on the timeout return path.
        assert builds["n"] == 1
        agent._emit_warning.assert_called_once()

    def test_caller_fence_bypasses_owned_wrapper(self, monkeypatch):
        from run_agent import AIAgent

        agent = object.__new__(AIAgent)
        agent.session_id = "s1"
        agent._cached_system_prompt = "sys"
        agent._conversation_root_id = MagicMock(return_value=None)

        seen = {}

        def fake_compress(agent_obj, messages, system_message, **kwargs):
            seen["fence"] = kwargs.get("commit_fence")
            return ([{"role": "assistant", "content": "ok"}], "sys")

        monkeypatch.setattr(
            "agent.conversation_compression.compress_context",
            fake_compress,
        )
        # If the owned wrapper ran, this would raise — prove we never call it.
        monkeypatch.setattr(
            "agent.conversation_compression.run_compress_context_with_progress_timeout",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("owned wrapper must not run")
            ),
        )
        monkeypatch.setattr(
            "agent.portal_tags.get_conversation_context",
            lambda: object(),
        )

        fence = CompressionCommitFence()
        msgs, prompt = AIAgent._compress_context(
            agent,
            [{"role": "user", "content": "x"}],
            "sys",
            commit_fence=fence,
        )
        assert seen["fence"] is fence
        assert agent._last_compression_timed_out is False
        assert prompt == "sys"
        assert msgs[0]["content"] == "ok"
