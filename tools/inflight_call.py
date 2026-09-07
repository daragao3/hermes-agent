"""Per-thread registry of tool calls in flight, with a cancel that self-sweeps.

Companion to :mod:`tools.interrupt` (added 2026-09-07). ``interrupt`` is a
per-THREAD bit: ``AIAgent.interrupt()`` sets it on the agent's execution
thread and its concurrent-tool workers, tools poll ``is_interrupted()``, and
the agent clears its own bits at the turn boundary. That design has one hard
rule: nobody but the agent may set a bit, because thread idents are recycled
and the set is never swept -- a bit set on a dead worker tid by an outside
party would fire a spurious ``[Command interrupted]`` on whatever unrelated
tool the OS next schedules onto that ident.

The cron scheduler's operator-stop and timeout paths need exactly that
outside-party power: stop THIS run's in-flight tool call, whatever it is,
without depending on the agent to propagate anything. ``cron.inflight.
kill_run_tool_subprocesses`` already covers the subprocess-backed tools
through the per-thread registry in ``tools.environments.base``; this module
covers everything else -- an HTTP request, an MCP call, an async handler
awaiting a socket, a plugin loop -- by keying the cancel on a CALL FRAME
rather than a thread bit:

* ``ToolRegistry.dispatch`` pushes an :class:`InflightCall` frame for the
  current thread around every handler invocation and pops it in ``finally``.
  A frame therefore exists for exactly the duration of the call, so a cancel
  can never outlive the call it was aimed at and never touches the thread's
  next occupant. That is the whole reason this is not a second thread bit.
* :func:`cancel_inflight_calls` marks every frame on the given threads
  cancelled and runs the frame's ABORT HOOKS -- callables the running call
  registered to make itself return promptly: cancel the asyncio task an
  async handler is awaiting (``model_tools._run_async`` does this for every
  async tool), ``shutdown(SHUT_RDWR)`` an httpx client's sockets
  (:func:`shutdown_client_sockets`), set an event a batch loop polls.
* :func:`is_call_cancelled` reports whether the current thread's call has
  been cancelled, and ``tools.interrupt.is_interrupted()`` ORs it in, so
  every existing poll site -- the terminal wait loop, the MCP wait loop,
  ``code_execution``, the web providers -- honours a scheduler cancel with
  no per-tool change and with no recycled-tid hazard.

Scoping is by thread ident, exactly like the subprocess registry: the
scheduler passes the run's pool worker (where sequential tools execute), the
agent's execution thread, and its concurrent-tool workers. Other sessions'
calls sit on other threads and are never reached. Everything here is a
no-op when nothing is in flight, and nothing here raises.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterable, Iterator, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# thread ident -> stack of frames (innermost last); a thread whose handler
# dispatches another tool synchronously has more than one.
_frames: dict[int, list["InflightCall"]] = {}


class InflightCall:
    """One tool call in flight on one thread. Created by :func:`inflight_call`."""

    __slots__ = (
        "thread_id", "tool_name", "started_at",
        "cancelled", "cancel_reason", "_hooks",
    )

    def __init__(self, thread_id: int, tool_name: str):
        self.thread_id = thread_id
        self.tool_name = tool_name
        self.started_at = time.monotonic()
        self.cancelled = False
        self.cancel_reason: Optional[str] = None
        self._hooks: list[Callable[[], None]] = []

    def is_cancelled(self) -> bool:
        return self.cancelled

    def add_abort_hook(self, hook: Callable[[], None]) -> None:
        """Register a callable that makes this call return promptly.

        Hooks run on the CANCELLING thread, once, in registration order, and
        must therefore be thread-safe with respect to the running call:
        ``loop.call_soon_threadsafe(task.cancel)``, ``socket.shutdown`` (never
        ``close`` -- see :func:`shutdown_client_sockets`), ``Event.set``. A
        hook registered after the cancel already landed runs immediately, so
        a cancel that races the call's own setup is not lost.
        """
        run_now = False
        with _lock:
            if self.cancelled:
                run_now = True
            else:
                self._hooks.append(hook)
        if run_now:
            _run_hook(hook, self)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<InflightCall {self.tool_name!r} tid={self.thread_id} "
            f"cancelled={self.cancelled}>"
        )


def _run_hook(hook: Callable[[], None], frame: InflightCall) -> None:
    try:
        hook()
    except Exception:
        logger.debug(
            "abort hook for %s on thread %s failed",
            frame.tool_name, frame.thread_id, exc_info=True,
        )


@contextmanager
def inflight_call(tool_name: str) -> Iterator[InflightCall]:
    """Mark a tool call in flight on the current thread for the ``with`` body.

    The frame is removed on every exit path, including ``BaseException``
    (``CancelledError``, ``KeyboardInterrupt``), which is what makes a cancel
    unable to leak onto the thread's next call.
    """
    tid = threading.current_thread().ident
    frame = InflightCall(tid, tool_name)
    with _lock:
        _frames.setdefault(tid, []).append(frame)
    try:
        yield frame
    finally:
        with _lock:
            entries = _frames.get(tid)
            if entries:
                for i in range(len(entries) - 1, -1, -1):
                    if entries[i] is frame:
                        del entries[i]
                        break
                if not entries:
                    _frames.pop(tid, None)


def current_call() -> Optional[InflightCall]:
    """The innermost call in flight on the current thread, or None."""
    tid = threading.current_thread().ident
    with _lock:
        entries = _frames.get(tid)
        return entries[-1] if entries else None


def add_abort_hook(hook: Callable[[], None]) -> bool:
    """Attach ``hook`` to the current thread's in-flight call.

    Returns False -- and does not retain ``hook`` -- when the current thread
    has no call in flight (a tool invoked outside ``ToolRegistry.dispatch``,
    e.g. directly from a test or a CLI helper).
    """
    frame = current_call()
    if frame is None:
        return False
    frame.add_abort_hook(hook)
    return True


def is_call_cancelled(thread_id: Optional[int] = None) -> bool:
    """True when any call in flight on the thread has been cancelled.

    Defaults to the current thread. Any frame on the stack counts: a nested
    dispatch inherits its parent's cancel.
    """
    tid = thread_id if thread_id is not None else threading.current_thread().ident
    with _lock:
        entries = _frames.get(tid)
        if not entries:
            return False
        return any(f.cancelled for f in entries)


def inflight_call_threads() -> frozenset[int]:
    """Thread idents that currently have a tool call in flight."""
    with _lock:
        return frozenset(_frames)


def inflight_calls(thread_ids: Optional[Iterable[int]] = None) -> list[InflightCall]:
    """Snapshot of frames in flight, optionally restricted to ``thread_ids``."""
    with _lock:
        if thread_ids is None:
            return [f for entries in _frames.values() for f in entries]
        out: list[InflightCall] = []
        for tid in thread_ids:
            out.extend(_frames.get(tid, ()))
        return out


def cancel_inflight_calls(thread_ids: Iterable[int], *, reason: str = "") -> int:
    """Cancel every tool call in flight on the given threads.

    Marks each not-yet-cancelled frame, then runs its abort hooks outside
    the lock. Returns the number of frames newly cancelled: 0 when none of
    the threads is inside a dispatch, which is the common case and costs
    one dict lookup per thread. Non-int ids (a MagicMock attribute, a bool)
    are ignored. Never raises.
    """
    wanted: set[int] = set()
    for tid in thread_ids or ():
        if isinstance(tid, int) and not isinstance(tid, bool):
            wanted.add(tid)
    if not wanted:
        return 0
    targets: list[tuple[InflightCall, list[Callable[[], None]]]] = []
    with _lock:
        for tid in wanted:
            for frame in _frames.get(tid, ()):
                if frame.cancelled:
                    continue
                frame.cancelled = True
                frame.cancel_reason = reason or None
                hooks = list(frame._hooks)
                frame._hooks.clear()
                targets.append((frame, hooks))
    for frame, hooks in targets:
        for hook in hooks:
            _run_hook(hook, frame)
    return len(targets)


# ---------------------------------------------------------------------------
# Abort hook helpers
# ---------------------------------------------------------------------------

def _iter_client_sockets(client) -> Iterator[object]:
    """Yield the raw sockets of an httpx-backed client's connection pool.

    Accepts a bare ``httpx.Client`` or an SDK wrapper exposing one as
    ``._client`` (OpenAI/Anthropic). Mirrors the traversal in
    ``agent.agent_runtime_helpers._iter_pool_sockets`` without importing the
    agent package: httpcore stores the concrete connection under
    ``conn._connection`` and the socket under the network stream's ``_sock``.
    Defensive throughout -- these are private transport internals.
    """
    try:
        http_client = getattr(client, "_client", None) or client
        transport = getattr(http_client, "_transport", None)
        pool = getattr(transport, "_pool", None)
        if pool is None:
            return
        connections = (
            getattr(pool, "_connections", None)
            or getattr(pool, "_pool", None)
            or []
        )
        connections = list(connections)
    except Exception:
        return
    seen: set[int] = set()
    for conn in connections:
        candidates = [conn]
        inner = getattr(conn, "_connection", None)
        if inner is not None:
            candidates.append(inner)
        for candidate in candidates:
            stream = (
                getattr(candidate, "_network_stream", None)
                or getattr(candidate, "_stream", None)
            )
            if stream is None:
                continue
            sock = getattr(stream, "_sock", None)
            if sock is None:
                wrapped = getattr(stream, "stream", None)
                if wrapped is not None:
                    sock = getattr(wrapped, "_sock", None)
            if sock is None or not hasattr(sock, "shutdown"):
                continue
            marker = id(sock)
            if marker in seen:
                continue
            seen.add(marker)
            yield sock


def shutdown_client_sockets(client) -> int:
    """Abort an httpx client's in-flight I/O from another thread.

    ``shutdown(SHUT_RDWR)`` breaks the owning thread's pending ``recv``/
    ``send`` with EOF/``EPIPE`` so its request unwinds now instead of at the
    kernel timeout. It deliberately never calls ``close()``: releasing the
    FD from a stranger thread lets the kernel recycle the integer under a
    still-live SSL BIO, which then writes a TLS record into whatever file
    next got that number (agent-src #29507 corrupted a SQLite header that
    way). The owning thread closes the client from its own context.

    PLATFORM LIMIT (measured 2026-09-07, Windows 11 / Python 3.12): on
    Windows a thread already blocked in ``recv`` is NOT woken by a
    cross-thread ``shutdown`` (nor by ``CancelIoEx`` / ``CancelSynchronousIo``),
    so there the abort takes effect at the client's read timeout rather than
    immediately. Give scheduler-facing clients a short read timeout and poll
    :func:`is_call_cancelled` (or ``tools.interrupt.is_interrupted``) between
    requests; on POSIX the shutdown wakes the read at once.

    Returns the number of sockets shut down. Typical use inside a handler::

        client = httpx.Client(timeout=60)
        add_abort_hook(lambda: shutdown_client_sockets(client))
        with client:
            return client.post(url, json=payload).text
    """
    import socket as _socket

    count = 0
    for sock in _iter_client_sockets(client):
        try:
            sock.shutdown(_socket.SHUT_RDWR)
        except OSError:
            pass  # not connected / already shut down -- benign
        except Exception:
            logger.debug("shutdown_client_sockets: shutdown failed", exc_info=True)
            continue
        count += 1
    return count


__all__ = [
    "InflightCall",
    "add_abort_hook",
    "cancel_inflight_calls",
    "current_call",
    "inflight_call",
    "inflight_call_threads",
    "inflight_calls",
    "is_call_cancelled",
    "shutdown_client_sockets",
]
