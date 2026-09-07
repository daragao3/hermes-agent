"""Per-call cancellation of an in-flight tool (tools.inflight_call, 2026-09-07).

The cron scheduler's operator stop and timeouts could already interrupt a
tool that polls ``is_interrupted()`` and kill one blocked in a subprocess.
A tool doing blocking network I/O, an MCP call, or an async handler awaiting
a socket was aborted by nothing: the run was recorded failed and its session
closed while the worker thread's call ran to completion and its side effects
landed. These tests cover the call-frame registry that closes that gap and
the two places it is wired: ``ToolRegistry.dispatch`` (frame per call) and
``model_tools._run_async`` (abort hook cancels the awaited task).
"""

import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.inflight_call import (  # noqa: E402
    InflightCall,
    add_abort_hook,
    cancel_inflight_calls,
    current_call,
    inflight_call,
    inflight_call_threads,
    inflight_calls,
    is_call_cancelled,
    shutdown_client_sockets,
)
from tools.interrupt import is_interrupted  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402


def _me() -> int:
    return threading.current_thread().ident


def _wait_until(pred, timeout=5.0, step=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


# ---------------------------------------------------------------------------
# Registry semantics
# ---------------------------------------------------------------------------

class TestFrames:
    def test_frame_exists_for_exactly_the_with_body(self):
        assert current_call() is None
        assert _me() not in inflight_call_threads()
        with inflight_call("demo") as frame:
            assert isinstance(frame, InflightCall)
            assert current_call() is frame
            assert frame.tool_name == "demo"
            assert frame.thread_id == _me()
            assert _me() in inflight_call_threads()
            assert not frame.is_cancelled()
        assert current_call() is None
        assert _me() not in inflight_call_threads()

    def test_frame_is_popped_on_base_exception(self):
        class _Boom(BaseException):
            pass

        with pytest.raises(_Boom):
            with inflight_call("demo"):
                raise _Boom()
        assert current_call() is None

    def test_nested_dispatch_stacks_and_inherits_cancel(self):
        with inflight_call("outer") as outer:
            with inflight_call("inner") as inner:
                assert current_call() is inner
                assert cancel_inflight_calls({_me()}, reason="stop") == 2
                assert outer.is_cancelled() and inner.is_cancelled()
                assert is_call_cancelled()
            # Inner popped; outer still cancelled.
            assert current_call() is outer
            assert is_call_cancelled()
        assert not is_call_cancelled()

    def test_cancel_is_a_noop_with_nothing_in_flight(self):
        assert cancel_inflight_calls({_me()}) == 0
        assert cancel_inflight_calls(set()) == 0
        assert cancel_inflight_calls(None) == 0
        # Non-int ids (MagicMock attributes, bools) are ignored.
        assert cancel_inflight_calls({True, "12", 3.0, object()}) == 0

    def test_cancel_marks_reason_runs_hooks_once_and_swallows_hook_errors(self):
        fired = []

        def _bad():
            fired.append("bad")
            raise RuntimeError("hook blew up")

        with inflight_call("demo") as frame:
            assert add_abort_hook(_bad) is True
            assert add_abort_hook(lambda: fired.append("good")) is True
            assert cancel_inflight_calls({_me()}, reason="operator stop") == 1
            assert frame.cancel_reason == "operator stop"
            assert fired == ["bad", "good"]
            # Already cancelled: a second cancel finds nothing new.
            assert cancel_inflight_calls({_me()}, reason="again") == 0
            assert frame.cancel_reason == "operator stop"
            assert fired == ["bad", "good"]

    def test_hook_registered_after_cancel_runs_immediately(self):
        """A cancel racing the call's own setup must not be lost."""
        fired = []
        with inflight_call("demo"):
            cancel_inflight_calls({_me()})
            add_abort_hook(lambda: fired.append(1))
            assert fired == [1]

    def test_add_abort_hook_outside_a_call_is_refused(self):
        assert current_call() is None
        assert add_abort_hook(lambda: None) is False

    def test_snapshot_helpers(self):
        with inflight_call("a"):
            frames = inflight_calls({_me()})
            assert [f.tool_name for f in frames] == ["a"]
            assert any(f.tool_name == "a" for f in inflight_calls())
        assert inflight_calls({_me()}) == []


class TestInterruptBridge:
    def test_is_interrupted_reports_a_cancelled_frame_and_clears_on_unwind(self):
        """The recycled-tid property: the signal dies with the call."""
        assert not is_interrupted()
        with inflight_call("demo"):
            assert not is_interrupted()
            cancel_inflight_calls({_me()})
            assert is_interrupted()
        # Same thread ident, no frame: nothing leaks to the next call.
        assert not is_interrupted()
        with inflight_call("next"):
            assert not is_interrupted()

    def test_cancel_is_scoped_to_the_named_threads(self):
        """Another thread's call -- another session in the gateway -- is
        never reached by a cancel aimed at this one."""
        other_in = threading.Event()
        release = threading.Event()
        other_seen = {}

        def _other():
            with inflight_call("other_session_tool"):
                other_in.set()
                release.wait(timeout=10)
                other_seen["cancelled"] = is_call_cancelled()
                other_seen["interrupted"] = is_interrupted()

        t = threading.Thread(target=_other, daemon=True)
        t.start()
        assert other_in.wait(timeout=5)
        try:
            with inflight_call("mine"):
                assert cancel_inflight_calls({_me()}) == 1
                assert is_call_cancelled()
                assert not is_call_cancelled(t.ident)
        finally:
            release.set()
            t.join(timeout=5)
        assert other_seen == {"cancelled": False, "interrupted": False}


# ---------------------------------------------------------------------------
# Wiring: ToolRegistry.dispatch
# ---------------------------------------------------------------------------

def _dispatch_on_thread(reg: ToolRegistry, name: str, args=None):
    """Run ``reg.dispatch`` on a fresh thread; return (thread, box)."""
    box = {}

    def _run():
        box["started"] = time.monotonic()
        box["result"] = reg.dispatch(name, args or {})
        box["ended"] = time.monotonic()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t, box


class TestRegistryDispatchFrame:
    def test_sync_handler_polling_is_interrupted_unblocks_on_cancel(self):
        reg = ToolRegistry()
        entered = threading.Event()

        def _slow(args, **kwargs):
            entered.set()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if is_interrupted():
                    return json.dumps({"stopped": True})
                time.sleep(0.02)
            return json.dumps({"stopped": False})

        reg.register(name="slow_poll", toolset="t", schema={"name": "slow_poll"}, handler=_slow)
        t, box = _dispatch_on_thread(reg, "slow_poll")
        assert entered.wait(timeout=5)
        assert t.ident in inflight_call_threads()
        assert cancel_inflight_calls({t.ident}, reason="test") == 1
        t.join(timeout=5)
        assert not t.is_alive(), "handler did not unblock after the cancel"
        assert json.loads(box["result"]) == {"stopped": True}
        assert t.ident not in inflight_call_threads()
        assert box["ended"] - box["started"] < 5

    def test_handler_can_register_its_own_abort_hook(self):
        reg = ToolRegistry()
        entered = threading.Event()
        stop = threading.Event()

        def _blocking(args, **kwargs):
            # A tool that blocks on something only IT can unblock (a socket,
            # a queue) exposes the unblock as an abort hook.
            assert add_abort_hook(stop.set) is True
            entered.set()
            return json.dumps({"released": stop.wait(timeout=20)})

        reg.register(name="hooked", toolset="t", schema={"name": "hooked"}, handler=_blocking)
        t, box = _dispatch_on_thread(reg, "hooked")
        assert entered.wait(timeout=5)
        assert cancel_inflight_calls({t.ident}) == 1
        t.join(timeout=5)
        assert not t.is_alive()
        assert json.loads(box["result"]) == {"released": True}

    def test_dispatch_frame_is_gone_after_a_raising_handler(self):
        reg = ToolRegistry()

        def _raises(args, **kwargs):
            assert current_call() is not None and current_call().tool_name == "raiser"
            raise ValueError("nope")

        reg.register(name="raiser", toolset="t", schema={"name": "raiser"}, handler=_raises)
        out = reg.dispatch("raiser", {})
        assert "nope" in out
        assert current_call() is None


# ---------------------------------------------------------------------------
# Wiring: model_tools._run_async (async handlers)
# ---------------------------------------------------------------------------

def _async_registry():
    reg = ToolRegistry()
    entered = threading.Event()

    async def _sleeps(args, **kwargs):
        entered.set()
        await asyncio.sleep(60)
        return json.dumps({"finished": True})

    reg.register(
        name="async_sleep", toolset="t", schema={"name": "async_sleep"},
        handler=_sleeps, is_async=True,
    )
    return reg, entered


class TestRunAsyncAbortHook:
    def test_async_handler_on_a_worker_thread_is_cancelled(self):
        """Cron's sequential tools run on the pool worker, a non-main thread:
        the per-thread persistent loop branch of ``_run_async``."""
        reg, entered = _async_registry()
        t, box = _dispatch_on_thread(reg, "async_sleep")
        assert entered.wait(timeout=5)
        t0 = time.monotonic()
        assert cancel_inflight_calls({t.ident}, reason="operator stop") == 1
        t.join(timeout=5)
        assert not t.is_alive(), "async handler kept running after the cancel"
        assert time.monotonic() - t0 < 5
        payload = json.loads(box["result"])
        assert "error" in payload
        assert "InterruptedError" in payload["error"]
        assert "tool call cancelled: operator stop" in payload["error"]
        assert t.ident not in inflight_call_threads()

    def test_async_handler_on_the_main_thread_is_cancelled(self):
        """The shared tool loop branch (CLI / main thread)."""
        if threading.current_thread() is not threading.main_thread():
            pytest.skip("needs the main thread")
        reg, entered = _async_registry()
        me = _me()

        def _cancel_when_entered():
            entered.wait(timeout=5)
            time.sleep(0.05)
            cancel_inflight_calls({me}, reason="wall-clock timeout")

        c = threading.Thread(target=_cancel_when_entered, daemon=True)
        c.start()
        t0 = time.monotonic()
        out = reg.dispatch("async_sleep", {})
        c.join(timeout=5)
        assert time.monotonic() - t0 < 5
        payload = json.loads(out)
        assert "InterruptedError" in payload["error"]
        assert "wall-clock timeout" in payload["error"]
        assert current_call() is None

    def test_async_handler_under_a_running_loop_is_cancelled(self):
        """Dispatch from inside an event loop uses the fresh-thread branch;
        the hook cancels the tasks inside that worker's loop."""
        reg, entered = _async_registry()
        box = {}

        async def _driver():
            me = _me()

            def _cancel_when_entered():
                entered.wait(timeout=5)
                time.sleep(0.05)
                box["cancelled"] = cancel_inflight_calls({me}, reason="inactivity timeout")

            threading.Thread(target=_cancel_when_entered, daemon=True).start()
            # Synchronous dispatch from a coroutine: exactly what a tool
            # invoked inside the gateway's async stack does.
            return reg.dispatch("async_sleep", {})

        t0 = time.monotonic()
        out = asyncio.run(_driver())
        assert time.monotonic() - t0 < 10
        assert box.get("cancelled") == 1
        payload = json.loads(out)
        assert "InterruptedError" in payload["error"]
        assert "inactivity timeout" in payload["error"]

    def test_uncancelled_async_handler_completes_normally(self):
        reg = ToolRegistry()

        async def _quick(args, **kwargs):
            await asyncio.sleep(0.01)
            return json.dumps({"ok": True})

        reg.register(name="quick", toolset="t", schema={"name": "quick"}, handler=_quick, is_async=True)
        t, box = _dispatch_on_thread(reg, "quick")
        t.join(timeout=5)
        assert json.loads(box["result"]) == {"ok": True}
        assert reg.dispatch("quick", {}) == json.dumps({"ok": True})


# ---------------------------------------------------------------------------
# Wiring: a blocking HTTP request with the socket-shutdown hook
# ---------------------------------------------------------------------------

@pytest.fixture()
def silent_http_server():
    """A TCP server that accepts and never answers -- a stalled upstream."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(0.2)
    accepted = []
    stop = threading.Event()

    def _accept_loop():
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            accepted.append(conn)

    t = threading.Thread(target=_accept_loop, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}/"
    finally:
        stop.set()
        t.join(timeout=2)
        for c in accepted:
            try:
                c.close()
            except Exception:
                pass
        srv.close()


class TestHttpClientSocketAbort:
    # Measured 2026-09-07 on Windows 11 (agent-src .venv, Python 3.12): a
    # thread already blocked in a sync ``recv`` is NOT woken by
    # ``shutdown(SHUT_RDWR)`` from another thread -- nor by CancelIoEx or
    # CancelSynchronousIo -- and even a fresh ``recv`` after the shutdown
    # blocks until its timeout. Only ``close()`` wakes it, and that is
    # forbidden from a stranger thread (#29507). So on Windows the hook
    # guarantees the call returns no later than the client's READ TIMEOUT;
    # on POSIX the shutdown wakes the read immediately. The client timeout
    # below is what bounds this test on Windows.
    _READ_TIMEOUT = 3.0

    def test_shutdown_hook_aborts_a_stalled_httpx_request(self, silent_http_server):
        httpx = pytest.importorskip("httpx")
        reg = ToolRegistry()
        entered = threading.Event()
        seen = {}

        def _post(args, **kwargs):
            client = httpx.Client(timeout=self._READ_TIMEOUT)
            add_abort_hook(lambda: seen.setdefault("shut", shutdown_client_sockets(client)))
            entered.set()
            try:
                with client:
                    r = client.get(silent_http_server)
                    return json.dumps({"status": r.status_code})
            except Exception as exc:  # the abort surfaces as a transport error
                return json.dumps({"aborted": type(exc).__name__})

        reg.register(name="stalled_http", toolset="t", schema={"name": "stalled_http"}, handler=_post)
        t, box = _dispatch_on_thread(reg, "stalled_http")
        assert entered.wait(timeout=5)
        # Give the request time to connect and block in recv.
        time.sleep(0.5)
        t0 = time.monotonic()
        assert cancel_inflight_calls({t.ident}, reason="operator stop") == 1
        t.join(timeout=self._READ_TIMEOUT + 5)
        assert not t.is_alive(), "request did not unblock after socket shutdown"
        assert time.monotonic() - t0 < self._READ_TIMEOUT + 5
        assert seen.get("shut", 0) >= 1, "no pool socket was found to shut down"
        assert "aborted" in json.loads(box["result"])
        if sys.platform != "win32":
            # POSIX: the shutdown itself wakes the read, well inside the timeout.
            assert box["ended"] - t0 < self._READ_TIMEOUT

    def test_shutdown_helper_is_a_noop_on_a_client_with_no_connections(self):
        httpx = pytest.importorskip("httpx")
        with httpx.Client() as client:
            assert shutdown_client_sockets(client) == 0
        assert shutdown_client_sockets(object()) == 0
        assert shutdown_client_sockets(None) == 0
