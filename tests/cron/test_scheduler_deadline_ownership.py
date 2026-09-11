"""Soft deadline persistence must respect real fire and execution ownership."""
import contextvars
import threading

import pytest


@pytest.mark.parametrize("state", ["owned", "successor", "foreign", "terminal", "handoff"])
def test_deadline_only_amends_its_exact_attempt(tmp_path, monkeypatch, state):
    from cron import executions, jobs, scheduler
    from unittest.mock import MagicMock

    release = threading.Event()
    done = threading.Event()
    box_seen = []
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 0.1)
    emitter = MagicMock()
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="deadline ownership", schedule="every 1h")
        claimed = jobs.claim_job_for_fire(job["id"], return_job=True)
        attempt = executions.create_execution(job["id"], source="deadline-test")
        job["execution_id"] = claimed["execution_id"] = attempt["id"]
        if state == "successor":
            rows = jobs.load_jobs()
            rows[0]["fire_claim"]["by"] = "successor-owner"
            jobs.save_jobs(rows)
        elif state == "foreign":
            # Exercise the real SQL owner CAS after another process adopted the row.
            with executions._transaction() as conn:
                conn.execute("UPDATE executions SET process_id=? WHERE id=?",
                             ("foreign-worker", attempt["id"]))
        elif state == "terminal":
            executions.finish_execution(attempt["id"], success=True)
        elif state == "handoff":
            executions.mark_execution_handoff_pending(attempt["id"])
        before = jobs.get_job(job["id"])
        before_execution = executions.get_execution(attempt["id"])

        def worker(snapshot, *, _abandoned, _deadline_box):
            _deadline_box["claimed_job"] = claimed
            box_seen.append(_deadline_box)
            try:
                assert release.wait(10)
                scheduler._amend_late_deadline_outcome(
                    claimed, success=True, error=None, deadline_box=_deadline_box)
                return True
            finally:
                done.set()

        try:
            assert scheduler._run_callable_with_deadline(
                job, worker, True, contextvars.copy_context()) is False
            if state == "owned":
                provisional = jobs.get_job(job["id"])
                assert provisional["last_status"] == "error"
                assert box_seen[0]["deadline_last_run_at"] == provisional["last_run_at"]
                assert isinstance(box_seen[0]["deadline_last_run_at"], str)
            else:
                assert jobs.get_job(job["id"]) == before
            if state in {"foreign", "terminal", "handoff"}:
                assert executions.get_execution(attempt["id"]) == before_execution
        finally:
            release.set()
            assert done.wait(10)
        if state == "owned":
            assert jobs.get_job(job["id"])["last_status"] == "ok"
        else:
            assert jobs.get_job(job["id"]) == before
        if state in {"foreign", "terminal", "handoff"}:
            assert executions.get_execution(attempt["id"]) == before_execution
        else:
            assert executions.get_execution(attempt["id"])["status"] == "completed"
        assert emitter.on_job_completed.call_count == (1 if state in {"owned", "successor"} else 0)


@pytest.mark.parametrize("phase", ["model", "save", "error", "successor"])
def test_pool_deadline_suppresses_late_effects_and_amends_real_result(tmp_path, monkeypatch, phase):
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock
    from cron import jobs, executions as executions, scheduler

    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    emitter = MagicMock()
    deliver = MagicMock()
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 8)
    monkeypatch.setattr(scheduler, "_launch_external_cron_worker", lambda job: False)
    monkeypatch.setattr(scheduler, "_deliver_result", deliver)
    original_save = scheduler.save_job_output

    def wait_for_release():
        entered.set()
        assert release.wait(30)

    def run(job, **kwargs):
        if phase != "save":
            wait_for_release()
        if phase == "error":
            raise RuntimeError("real late failure")
        return True, "late output", "late report", None

    def save(job_id, output):
        wait_for_release()
        return original_save(job_id, output)

    monkeypatch.setattr(scheduler, "run_job", run)
    if phase == "save":
        monkeypatch.setattr(scheduler, "save_job_output", save)

    def process(job, *, _abandoned=None, _deadline_box=None):
        try:
            return scheduler._process_due_job(job, None, None, False,
                _abandoned=_abandoned, _deadline_box=_deadline_box)
        finally:
            done.set()

    with jobs.use_cron_store(tmp_path), ThreadPoolExecutor(max_workers=1) as pool:
        job = jobs.create_job(prompt="deadline journey", schedule="every 1h", deliver="local")
        successor = None
        future = scheduler._submit_with_guard(job, pool, process)
        try:
            assert entered.wait(15)
            # Output-save holds the upstream side-effect fence. Release it
            # after the deadline decision, allowing persistence to finish.
            if phase == "save":
                import time
                time.sleep(8.2)
                release.set()
            assert future.result(timeout=10) is False
            if phase != "save":
                assert jobs.get_job(job["id"])["last_status"] == "error"
            if phase == "successor":
                successor = jobs.claim_job_for_fire(job["id"], return_job=True)
                assert successor
                assert jobs.mark_job_run(job["id"], True,
                    expected_fire_owner=successor["fire_claim"]["by"])
                successor = jobs.get_job(job["id"])
                assert scheduler._try_register_in_flight(job["id"], "successor") is None
        finally:
            release.set()
            assert done.wait(10)
        result = jobs.get_job(job["id"])
        assert result["last_status"] == ("error" if phase == "error" else "ok")
        if phase == "error":
            assert result["last_error"] == "real late failure"
        assert not deliver.called
        assert emitter.on_job_completed.call_count == 1
        assert emitter.on_job_completed.call_args.kwargs["success"] is False
        if phase == "successor":
            try:
                assert result == successor
                assert scheduler._in_flight[job["id"]].job_name == "successor"
            finally:
                scheduler._release_in_flight(job["id"])
        else:
            assert job["id"] not in scheduler._in_flight
