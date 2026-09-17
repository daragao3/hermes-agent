"""Hook callbacks may run concurrently up to a cap; the cap and the post-timeout
suppression still bound a hung or slow callback (2026-09-17).

Before this, ``_hook_running_callbacks`` held ONE token per callback, so two
tool calls completing in the same second on different cron jobs made the
second ``post_tool_call`` fire skip -- 32 skips a day on the observer hooks
with zero actual timeouts behind them.
"""

from __future__ import annotations

import threading
import time

import pytest

from hermes_cli.plugins import PluginManager
from hermes_cli.plugins_dispatch import _HOOK_MAX_CONCURRENT_RUNS, _HOOK_SKIPPED


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr("hermes_cli.plugins._resolve_hook_callback_timeout", lambda: 5.0)
    return PluginManager()


def _slow_callback(hold: threading.Event, started: threading.Semaphore):
    def cb(**_kw):
        started.release()
        hold.wait(timeout=10.0)
        return "done"
    return cb


def test_concurrent_fires_of_one_callback_all_run_up_to_the_cap(mgr):
    hold = threading.Event()
    started = threading.Semaphore(0)
    cb = _slow_callback(hold, started)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(mgr._run_hook_callback_bounded("post_tool_call", cb, {}, 5.0)))
        for _ in range(_HOOK_MAX_CONCURRENT_RUNS)
    ]
    for t in threads:
        t.start()
    for _ in range(_HOOK_MAX_CONCURRENT_RUNS):
        assert started.acquire(timeout=2.0), "a fire under the cap was skipped"
    # All slots live: the NEXT fire is the one that skips.
    assert mgr._run_hook_callback_bounded("post_tool_call", cb, {}, 5.0) is _HOOK_SKIPPED
    hold.set()
    for t in threads:
        t.join(timeout=5.0)
    assert results == ["done"] * _HOOK_MAX_CONCURRENT_RUNS
    assert ("post_tool_call", id(cb)) not in mgr._hook_running_callbacks, "slots released"


def test_two_overlapping_fires_both_run(mgr):
    """The 2026-09-17 shape: a second fire while the first is still in flight."""
    hold = threading.Event()
    started = threading.Semaphore(0)
    cb = _slow_callback(hold, started)
    first = threading.Thread(target=lambda: mgr._run_hook_callback_bounded("post_tool_call", cb, {}, 5.0))
    first.start()
    assert started.acquire(timeout=2.0)
    second = {}
    t2 = threading.Thread(target=lambda: second.setdefault("r", mgr._run_hook_callback_bounded("post_tool_call", cb, {}, 5.0)))
    t2.start()
    assert started.acquire(timeout=2.0), "the second fire skipped while the first was still running"
    hold.set()
    first.join(timeout=5.0); t2.join(timeout=5.0)
    assert second["r"] == "done"


def test_a_timed_out_callback_is_still_suppressed_afterwards(mgr, monkeypatch):
    """The concurrency cap does not weaken #6622: after a timeout the callback
    is suppressed for the suppression window regardless of free slots."""
    monkeypatch.setattr(mgr, "_hook_timeout_suppression_seconds", 60.0)
    hold = threading.Event()

    def hung(**_kw):
        hold.wait(timeout=10.0)

    t0 = time.monotonic()
    assert mgr._run_hook_callback_bounded("post_tool_call", hung, {}, 0.1) is _HOOK_SKIPPED
    assert time.monotonic() - t0 < 2.0
    assert mgr._run_hook_callback_bounded("post_tool_call", hung, {}, 0.1) is _HOOK_SKIPPED, "suppressed"
    hold.set()


def test_slots_are_released_on_exception(mgr):
    def boom(**_kw):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        mgr._run_hook_callback_bounded("post_tool_call", boom, {}, 5.0)
    assert ("post_tool_call", id(boom)) not in mgr._hook_running_callbacks
