"""The adopted worker owns deadline persistence and waits for its late teardown."""
import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock


def test_adopted_payload_records_deadline_then_real_late_outcome(tmp_path, monkeypatch):
    from cron import jobs, executions, scheduler
    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")

    entered, release, deadline = threading.Event(), threading.Event(), threading.Event()
    emitter = MagicMock()
    emitter.on_job_completed.side_effect = lambda **kw: deadline.set() if not kw["success"] else None
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 8)
    deliver = MagicMock(return_value=None)
    monkeypatch.setattr(scheduler, "_deliver_result", deliver)

    def run(job, **kwargs):
        entered.set()
        assert release.wait(20)
        return True, "output", "late report", None

    monkeypatch.setattr(scheduler, "run_job", run)
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="adopted deadline", schedule="every 1h")
        claimed = jobs.claim_job_for_fire(job["id"], return_job=True)
        row = executions.create_execution(job["id"], source="builtin")
        claimed["execution_id"] = row["id"]
        assert executions.mark_execution_handoff_pending(row["id"])
        payload, ack = tmp_path / "payload.json", tmp_path / "ack.json"
        payload.write_text(json.dumps({"job": claimed, "profile_home": str(tmp_path)}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=1) as callers:
            future = callers.submit(contextvars.copy_context().run,
                scheduler._run_external_worker_payload, payload, ack)
            try:
                assert entered.wait(10)
                assert ack.exists()
                assert deadline.wait(12)
                assert executions.get_execution(row["id"])["status"] == "failed"
                assert not future.done(), "owning process must retain the late worker until teardown"
            finally:
                release.set()
            assert future.result(timeout=10) is True
        assert executions.get_execution(row["id"])["status"] == "completed"
        assert jobs.get_job(job["id"])["last_status"] == "ok"
        assert not deliver.called
        assert emitter.on_job_completed.call_count == 1
