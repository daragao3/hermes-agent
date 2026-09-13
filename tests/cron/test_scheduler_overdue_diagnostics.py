"""A serialized job remains running until its actual terminal result."""
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("success", [True, False])
def test_sequential_deadline_is_nonterminal(tmp_path, monkeypatch, success):
    from cron import executions, jobs, scheduler
    from events.schema import EventType

    emitter = MagicMock()
    overdue, release = threading.Event(), threading.Event()
    emitter.bus.emit.side_effect = lambda **kwargs: overdue.set()
    # Also release the observer on the old, incorrect terminal callback so
    # the regression fails on semantics rather than timing out.
    emitter.on_job_completed.side_effect = lambda **kwargs: overdue.set()
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 2)
    with jobs.use_cron_store(tmp_path):
        job = jobs.create_job(prompt="serialized fixture", schedule="every 1h")
        attempt = executions.create_execution(job["id"], source="overdue-test")
        job["execution_id"] = attempt["id"]

        def worker(snapshot, **kwargs):
            assert release.wait(15)
            executions.finish_execution(attempt["id"], success=success)
            emitter.on_job_completed(job_id=job["id"], success=success)
            return success

        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(scheduler._run_callable_with_deadline, job, worker, False, ctx)
            try:
                assert overdue.wait(10)
                assert not future.done()
                assert emitter.on_job_completed.call_count == 0
                assert executions.get_execution(attempt["id"])["status"] not in {"completed", "failed"}
                payload = emitter.bus.emit.call_args.kwargs
                assert payload["event_type"] == EventType.CRON_STALE
                assert payload["payload"]["state"] == "overdue_running"
                assert payload["payload"]["execution_id"] == attempt["id"]
                assert payload["payload"]["worker_stack"]
            finally:
                release.set()
            assert future.result(timeout=10) is success
        assert emitter.on_job_completed.call_count == 1
        assert emitter.on_job_completed.call_args.kwargs["success"] is success


def test_overdue_locates_isolation_wait_without_releasing_global_guard(tmp_path, monkeypatch):
    from cron import scheduler

    emitter, observed = MagicMock(), threading.Event()
    emitter.bus.emit.side_effect = lambda **kwargs: observed.set()
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 2)
    monkeypatch.setattr(scheduler, "_run_job_impl", lambda *args, **kwargs: (True, "", "[SILENT]", None))
    job = {"id": "waiting-for-isolation", "workdir": str(tmp_path)}
    scheduler._terminal_cwd_lock.acquire_write()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(scheduler._run_callable_with_deadline, job,
                             lambda job: scheduler.run_job(job)[0], False, contextvars.copy_context())
        try:
            assert observed.wait(15)
            payload = emitter.bus.emit.call_args.kwargs["payload"]
            assert payload["stage"] == "isolation_wait"
            assert payload["stage_elapsed_seconds"] >= 1
            assert not future.done()
            assert any(row["function"] == "acquire_write" for row in payload["worker_stack"])
        finally:
            scheduler._terminal_cwd_lock.release_write()
        assert future.result(timeout=15)


def test_real_script_timeout_reaps_owned_child_and_records_stages(tmp_path, monkeypatch):
    from cron import scheduler, scheduler_diagnostics as diagnostics, scheduler_script

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "stall.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(scheduler, "_hermes_home", tmp_path)
    spawned, stages = [], []
    original_popen = scheduler_script.subprocess.Popen
    original_stage = diagnostics.set_stage

    def popen(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    def stage(name):
        stages.append(name)
        original_stage(name)

    monkeypatch.setattr(scheduler_script.subprocess, "Popen", popen)
    monkeypatch.setattr(diagnostics, "set_stage", stage)
    evidence = {"job_id": "child-fixture", "execution_id": "fixture", "stage": ("dispatch", time.monotonic())}
    ok, error = diagnostics.run_with_evidence(
        evidence, lambda job: scheduler_script._run_job_script("stall.py", timeout_s=2), {}, {})
    assert not ok
    assert "timed out" in error
    assert spawned and all(proc.poll() is not None for proc in spawned)
    assert stages.index("script_spawn") < stages.index("script_wait") < stages.index("script_timeout_cleanup")
    assert evidence["stage"][0] == "worker_exited"


@pytest.mark.parametrize("success", [True, False])
def test_terminal_callback_retains_execution_identity(monkeypatch, success):
    from cron import scheduler

    emitter = MagicMock()
    job = {"id": "same-job", "execution_id": "exact-attempt"}
    monkeypatch.setattr(scheduler, "load_jobs", lambda: [{"id": "same-job", "consecutive_errors": 2}])
    scheduler._emit_cron_completion(emitter, job, success, None, "", time.monotonic())
    payload = emitter.on_job_completed.call_args.kwargs
    assert payload["execution_id"] == job["execution_id"]
    assert payload["success"] is success
    assert payload["consecutive_errors"] == 2
