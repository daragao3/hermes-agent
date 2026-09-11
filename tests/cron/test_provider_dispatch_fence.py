"""A queued provider claim must settle if quarantine starts before its worker."""
import pytest

@pytest.mark.parametrize("successor_claim", [False, True])
def test_queued_claim_settles_when_dispatch_is_fenced(tmp_path, monkeypatch, successor_claim):
    from cron import jobs, executions, scheduler_provider
    from jobflow_dispatch.quarantine_control import QuarantineControlStore

    store = QuarantineControlStore(tmp_path / "dispatch.db")
    monkeypatch.setattr(scheduler_provider, "default_control_store", lambda: store)
    provider = scheduler_provider.InProcessCronScheduler()
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="test queued admission", schedule="every 1h")
        claimed = provider.claim_fire(job["id"], force=True)
        assert claimed is not None
        execution_id = claimed["execution_id"]
        if successor_claim:
            rows = jobs.load_jobs()
            rows[0]["fire_claim"]["by"] = "successor-owner"
            jobs.save_jobs(rows)
        before = jobs.get_job(job["id"])
        with store.acquire_dispatch_barrier(reason="test queued admission") as barrier:
            store.activate_fence(barrier_token=barrier.token,
                                 authorization_request_id="test-only", required=True)
        with pytest.raises(RuntimeError, match="dispatch fenced"):
            provider.fire_claimed(claimed)
        execution = executions.get_execution(execution_id)
        assert execution["status"] == "failed"
        assert "dispatch fenced" in execution["error"]
        after = jobs.get_job(job["id"])
        if successor_claim:
            assert after == before
        else:
            assert after["last_status"] == "error"
            assert "dispatch fenced" in after["last_error"]


def test_event_wake_claim_keeps_cadence_and_does_not_claim_future_occurrence(tmp_path):
    from cron import jobs

    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="wake cadence", schedule="every 1h")
        next_run = job["next_run_at"]
        claimed = jobs.claim_job_for_fire(job["id"], return_job=True, preserve_schedule=True)
        assert claimed["_scheduled_instant"] is None
        assert jobs.get_job(job["id"])["next_run_at"] == next_run
        assert jobs.claim_job_for_fire(job["id"], preserve_schedule=True) is False


def test_event_wake_claim_cannot_resume_paused_job(tmp_path):
    from cron import jobs

    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="paused wake", schedule="every 1h")
        jobs.pause_job(job["id"], reason="operator paused")
        before = jobs.get_job(job["id"])
        assert jobs.claim_job_for_fire(job["id"], preserve_schedule=True) is False
        assert jobs.get_job(job["id"]) == before
