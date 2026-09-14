"""The soft deadline measures EXECUTION; time queued behind job isolation is
its own, non-failing budget, and ``cron_started`` marks the acquire.

Measured 2026-09-13: a 53-minute agent reader held the read lock, a */30
writer queued behind it in ``acquire_write``, every later reader queued behind
the writer, all four pool slots filled, and each queued job was reported as a
1800 s soft-deadline ``cron_failed`` (readers) or overdue (the writer) without
one of them having started. Everything completed within seconds once the long
reader released. None of the jobs hung.
"""
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from cron import scheduler
from events.schema import EventType, Priority


@pytest.fixture
def emitter(monkeypatch):
    emitter = MagicMock()
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    return emitter


@pytest.fixture
def held_write_lock():
    """Hold the global writer so every reader queues inside ``acquire_read``."""
    scheduler._terminal_cwd_lock.acquire_write()
    released = threading.Event()

    def release():
        if not released.is_set():
            released.set()
            scheduler._terminal_cwd_lock.release_write()

    try:
        yield release
    finally:
        release()


@pytest.fixture
def silent_run(monkeypatch):
    monkeypatch.setattr(
        scheduler, "_run_job_impl", lambda *args, **kwargs: (True, "", "[SILENT]", None))


def _run_under_deadline(job, *, _abandoned=None, _deadline_box=None):
    """Mirror tick()'s process_job: bind the watchdog box before run_job."""
    token = scheduler._deadline_current.set((_abandoned, _deadline_box))
    try:
        return scheduler.run_job(job)[0]
    finally:
        scheduler._deadline_current.reset(token)


_reader = _run_under_deadline


def test_deadline_clock_starts_after_isolation_acquired(emitter, held_write_lock, silent_run, monkeypatch):
    """A reader queued for longer than its timeout is NOT abandoned: the clock
    starts when it acquires the lock, and it then finishes well inside it."""
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 1)
    job = {"id": "queued-reader", "name": "reader", "isolation_wait_seconds": 30}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            scheduler._run_callable_with_deadline, job, _reader, True, contextvars.copy_context())
        try:
            time.sleep(2.5)  # more than twice the timeout, still queued
            assert not future.done(), "the watchdog abandoned a job that had not started"
        finally:
            held_write_lock()
        assert future.result(timeout=15) is True
    emitter.on_job_completed.assert_not_called()  # no cron_failed with a fake duration
    emitter.bus.emit.assert_not_called()  # inside the isolation budget: no diagnostic either


def test_queued_reader_reports_isolation_wait_not_cron_failed(emitter, held_write_lock, silent_run, monkeypatch):
    """Past the isolation budget the queued reader surfaces as a distinct,
    NORMAL-priority ``overdue_running``/``isolation_wait`` observation, once,
    and the watchdog keeps waiting for the lock instead of abandoning it."""
    observed = threading.Event()
    emitter.bus.emit.side_effect = lambda **kwargs: observed.set()
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 1)
    job = {"id": "queued-reader", "name": "reader", "execution_id": "attempt-1",
           "isolation_wait_seconds": 1.5}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            scheduler._run_callable_with_deadline, job, _reader, True, contextvars.copy_context())
        try:
            assert observed.wait(15)
            assert not future.done()
            kwargs = emitter.bus.emit.call_args.kwargs
            assert kwargs["event_type"] == EventType.CRON_STALE
            assert kwargs["priority"] is Priority.NORMAL
            payload = kwargs["payload"]
            assert payload["state"] == "overdue_running"
            assert payload["reason"] == "isolation_wait"
            assert payload["stage"] == "isolation_wait"
            assert payload["execution_id"] == "attempt-1"
            assert payload["threshold_seconds"] == 1.5
            assert payload["age_seconds"] >= 1.5
            assert any(row["function"] == "acquire_read" for row in payload["worker_stack"])
            emitter.on_job_completed.assert_not_called()
        finally:
            held_write_lock()
        assert future.result(timeout=15) is True
    emitter.on_job_completed.assert_not_called()
    assert emitter.bus.emit.call_count == 1, "the queued observation is reported once, then waited out"


def test_writer_keeps_soft_deadline_semantics_once_executing(emitter, held_write_lock, monkeypatch):
    """A writer that acquires and then overruns still gets the HIGH
    ``soft_deadline`` overdue observation, measured from the acquire."""
    observed, release = threading.Event(), threading.Event()
    emitter.bus.emit.side_effect = lambda **kwargs: observed.set()
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 1)

    def slow_impl(*args, **kwargs):
        assert release.wait(15)
        return True, "", "[SILENT]", None

    monkeypatch.setattr(scheduler, "_run_job_impl", slow_impl)
    job = {"id": "slow-writer", "name": "writer", "workdir": ".", "isolation_wait_seconds": 30}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            scheduler._run_callable_with_deadline, job,
            _run_under_deadline, False, contextvars.copy_context())
        try:
            time.sleep(1.5)  # queued past the timeout: no observation yet
            assert not observed.is_set()
            held_write_lock()
            assert observed.wait(15)
            kwargs = emitter.bus.emit.call_args.kwargs
            assert kwargs["priority"] is Priority.HIGH
            assert kwargs["payload"]["reason"] == "soft_deadline"
            assert kwargs["payload"]["stage"] == "job_execution"
            assert not future.done()
        finally:
            # Unblock the worker on ANY failure, or the pool's __exit__ waits
            # on a thread queued behind a lock the fixture releases only later.
            held_write_lock()
            release.set()
        assert future.result(timeout=15) is True
    emitter.on_job_completed.assert_not_called()


def _patch_run_one_job_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "save_job_output", lambda jid, out: str(tmp_path / f"{jid}.txt"))
    monkeypatch.setattr(scheduler, "_deliver_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler, "mark_job_run", lambda *args, **kwargs: None)


def test_cron_started_is_emitted_only_after_isolation_acquired(emitter, held_write_lock, monkeypatch, tmp_path):
    """The cron-stale monitor ages a run from the ``cron_started`` timestamp,
    so the event is emitted at the acquire and the run's duration is measured
    from there: queue time is invisible to both."""
    from cron import jobs

    monkeypatch.setattr(
        scheduler, "_run_job_impl", lambda *args, **kwargs: (True, "out", "final response", None))
    _patch_run_one_job_pipeline(monkeypatch, tmp_path)
    order = []
    emitter.on_job_started.side_effect = (
        lambda **kwargs: order.append(("started", time.monotonic())) or "evt-started")
    emitter.on_job_completed.side_effect = (
        lambda **kwargs: order.append(("completed", time.monotonic())))
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="queued fixture", schedule="every 1h")
        worker = threading.Thread(target=lambda: scheduler.run_one_job(job), daemon=True)
        worker.start()
        time.sleep(1.0)
        emitter.on_job_started.assert_not_called()
        released_at = time.monotonic()
        held_write_lock()
        worker.join(timeout=30)
    assert not worker.is_alive()
    assert [name for name, _ in order] == ["started", "completed"]
    assert order[0][1] >= released_at
    assert emitter.on_job_started.call_args.kwargs["execution_id"]
    completed = emitter.on_job_completed.call_args.kwargs
    assert completed["success"] is True
    assert completed["duration"] < 1.0, "duration must not include the second spent queued"


def test_cron_started_still_emitted_once_when_run_job_never_reports_isolation(emitter, monkeypatch, tmp_path):
    """A stubbed/external ``run_job`` that never calls the hook keeps the
    lifecycle intact: exactly one ``cron_started``, before the terminal event."""
    from cron import jobs

    monkeypatch.setattr(
        scheduler, "run_job", lambda job, **kwargs: (True, "out", "final response", None))
    _patch_run_one_job_pipeline(monkeypatch, tmp_path)
    order = []
    emitter.on_job_started.side_effect = lambda **kwargs: order.append("started") or "evt-started"
    emitter.on_job_completed.side_effect = lambda **kwargs: order.append("completed")
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="stubbed fixture", schedule="every 1h")
        assert scheduler.run_one_job(job) is True
    assert order == ["started", "completed"]


def test_isolation_wait_budget_sources():
    assert scheduler._isolation_wait_budget_seconds({}, 900.0) == 1800.0
    assert scheduler._isolation_wait_budget_seconds({"isolation_wait_seconds": 45}, 900.0) == 45.0
    assert scheduler._isolation_wait_budget_seconds({"isolation_wait_seconds": 0}, 900.0) == 1800.0
    assert scheduler._isolation_wait_budget_seconds({"isolation_wait_seconds": "x"}, 900.0) == 1800.0
