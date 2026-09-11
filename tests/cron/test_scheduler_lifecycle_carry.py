"""Integrated cron lifecycle guards through a real temporary job and execution store."""
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest


def test_concurrent_direct_runs_emit_one_start_and_completion(tmp_path, monkeypatch):
    from cron import jobs, scheduler

    from events.bus import EventBus
    from events.producers.cron_emitter import CronEventEmitter
    from events.schema import EventType as EventType
    bus = EventBus(db_path=tmp_path / "events.db")
    emitter = MagicMock(wraps=CronEventEmitter(bus))
    emitter.bus = bus
    entered = threading.Event()
    release = threading.Event()
    def run(job, **kwargs):
        entered.set()
        assert release.wait(10)
        return True, "output", "[SILENT]", None
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_launch_external_cron_worker", lambda job: False)
    monkeypatch.setattr(scheduler, "run_job", run)
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="concurrency", schedule="every 1h")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(contextvars.copy_context().run, scheduler.run_one_job, dict(job))
            try:
                assert entered.wait(10)
                assert scheduler.run_one_job(dict(job)) is False
            finally:
                release.set()
            assert future.result(timeout=10) is True
        assert emitter.on_job_started.call_count == 1
        assert emitter.on_job_completed.call_count == 1
        assert emitter.on_job_skipped_duplicate.call_count == 1
        assert job["id"] not in scheduler._in_flight
        assert jobs.get_job(job["id"])["last_status"] == "ok"


@pytest.mark.parametrize("reason,expected", [("no_work", "ok"), ("error", "error")])
def test_iteration_workload_verdict_reaches_ledger_and_event(tmp_path, monkeypatch, reason, expected):
    import json
    from cron import jobs, executions, scheduler

    from events.bus import EventBus
    from events.producers.cron_emitter import CronEventEmitter
    from events.schema import EventType
    bus = EventBus(db_path=tmp_path / "events.db")
    emitter = MagicMock(wraps=CronEventEmitter(bus))
    emitter.bus = bus
    response = "<AGENT_ITERATION_JSON>" + json.dumps({
        "agent": "test", "summary": "workload result", "reason": reason,
    }) + "</AGENT_ITERATION_JSON>"
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_launch_external_cron_worker", lambda job: False)
    monkeypatch.setattr(scheduler, "run_job", lambda job, **kw: (True, "output", response, None))
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="iteration", schedule="every 1h", deliver="local")
        assert scheduler.run_one_job(job) is True
        assert jobs.get_job(job["id"])["last_status"] == expected
        row = executions.get_execution(job["execution_id"])
        assert row["status"] == ("completed" if expected == "ok" else "failed")
        assert emitter.on_job_completed.call_args.kwargs["success"] is (expected == "ok")
        assert len(bus.query(event_type=EventType.AGENT_ITERATION)) == 1


def test_tick_worker_minimum_gap_rejects_without_rewriting_prior_verdict(tmp_path, monkeypatch):
    from datetime import timedelta
    from cron import jobs, executions, scheduler
    from events.bus import EventBus
    from events.producers.cron_emitter import CronEventEmitter
    from events.schema import EventType

    bus = EventBus(db_path=tmp_path / "events.db")
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: CronEventEmitter(bus))
    run = MagicMock(side_effect=AssertionError("minimum gap must prevent execution"))
    monkeypatch.setattr(scheduler, "run_job", run)
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="minimum gap", schedule="every 1h")
        job.update(min_seconds_between_fires=60,
                   last_run_at=(jobs._hermes_now() - timedelta(seconds=5)).isoformat(),
                   last_status="ok")
        jobs.save_jobs([job])
        prior = jobs.get_job(job["id"])
        job["execution_id"] = executions.create_execution(job["id"], source="builtin")["id"]
        assert scheduler._process_due_job(job, None, None, False) is False
        assert jobs.get_job(job["id"]) == prior
        assert executions.get_execution(job["execution_id"])["status"] == "failed"
        assert not run.called
        assert len(bus.query(event_type=EventType.CRON_SKIPPED_MIN_INTERVAL)) == 1


@pytest.mark.parametrize("idle_samples, expected_polls", [([120, 125], 2), ([120, 1, 11], 3)])
def test_inactivity_watchdog_discounts_suspend_until_fresh_activity(monkeypatch, idle_samples, expected_polls):
    from types import SimpleNamespace
    from cron import scheduler

    times = iter([0, 120, 125, 130])
    monkeypatch.setattr(scheduler, "time", SimpleNamespace(monotonic=lambda: next(times)))
    samples = iter(idle_samples)
    waits = []
    class Stop:
        def wait(self, interval):
            waits.append(interval)
            return len(waits) > expected_polls
    assert scheduler._inactivity_watchdog_loop(
        get_idle_seconds=lambda: next(samples), limit_s=10, poll_s=5,
        stop=Stop(), future_done=lambda: False,
    ) is True
    assert len(waits) == expected_polls
