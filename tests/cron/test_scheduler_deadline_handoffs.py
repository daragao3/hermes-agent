"""Deadline callback and late event handoffs preserve the next run's ownership."""
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("override", [{"profile": "test-profile"}, {"workdir": "test-directory"}])
def test_global_override_soft_deadline_alerts_and_keeps_waiting(monkeypatch, override):
    from cron import scheduler
    release, alert = threading.Event(), threading.Event()
    emitter = MagicMock()
    emitter.on_job_completed.side_effect = lambda **kw: alert.set()
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 0.1)
    monkeypatch.setattr(scheduler, "mark_job_run", MagicMock(side_effect=AssertionError("alert must not overwrite verdict")))
    job = {"id": "sequential-deadline", **override}

    def worker(job, *, _abandoned, _deadline_box):
        assert release.wait(5)
        assert not _abandoned.is_set()
        assert not scheduler._deadline_has_elapsed(_abandoned, _deadline_box)
        return True

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(scheduler._run_callable_with_deadline, job, worker,
            not scheduler._job_mutates_process_globals(job), contextvars.copy_context())
        try:
            assert alert.wait(5)
            assert not future.done()
        finally:
            release.set()
        assert future.result(timeout=5) is True
    assert emitter.on_job_completed.call_count == 1


def test_forwarding_callback_receives_deadline_identity(monkeypatch):
    from cron import scheduler
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 2)
    def forward(job, **kwargs):
        assert "_deadline_box" in kwargs
        assert "deadline_finalized" in kwargs["_deadline_box"]
        return True
    assert scheduler._run_callable_with_deadline(
        {"id": "forwarded"}, forward, True, contextvars.copy_context()) is True


def test_expired_job_cannot_start_after_acquiring_isolation(monkeypatch):
    from cron import scheduler
    abandoned = threading.Event()
    abandoned.set()
    run = MagicMock(side_effect=AssertionError("expired job reached model/script setup"))
    monkeypatch.setattr(scheduler, "_run_job_impl", run)
    token = scheduler._deadline_current.set((abandoned, None))
    try:
        assert scheduler.run_job({"id": "expired"})[0] is False
        run.assert_not_called()
    finally:
        scheduler._deadline_current.reset(token)


def test_stale_started_event_cannot_attach_to_successor():
    from cron import scheduler
    job_id = "started-event-handoff-test"
    assert scheduler._try_register_in_flight(job_id, "old") is None
    old = scheduler._in_flight[job_id]
    scheduler._release_in_flight(job_id)
    assert scheduler._try_register_in_flight(job_id, "successor") is None
    try:
        scheduler._attach_started_event_id(job_id, "stale-event", expected_record=old)
        assert scheduler._in_flight[job_id].cron_started_event_id is None
        successor = scheduler._in_flight[job_id]
        scheduler._attach_started_event_id(job_id, "successor-event", expected_record=successor)
        assert successor.cron_started_event_id == "successor-event"
    finally:
        scheduler._release_in_flight(job_id)
