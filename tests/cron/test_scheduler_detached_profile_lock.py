"""A timed-out model thread must retain its process-environment isolation."""
import contextvars
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.parametrize("profile", [None, "test-profile"])
def test_detached_model_holds_profile_isolation_until_it_really_finishes(tmp_path, monkeypatch, profile):
    from cron import scheduler
    from hermes_cli import profiles

    entered, release, successor_entered = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(profiles, "resolve_profile_env", lambda name: str(tmp_path))
    monkeypatch.setattr(scheduler, "_resolve_cron_activity_policy", lambda job: None)
    monkeypatch.setenv("HERMES_TEST_DETACHED_PROFILE", "original")
    with ThreadPoolExecutor(max_workers=1) as model_pool, ThreadPoolExecutor(max_workers=2) as callers:
        def model():
            entered.set()
            assert release.wait(10)
            if profile:
                assert os.environ["HERMES_TEST_DETACHED_PROFILE"] == "profile-value"

        def run_impl(job, **kwargs):
            if job["id"] == "successor":
                successor_entered.set()
                return True, "", "[SILENT]", None
            if profile:
                os.environ["HERMES_TEST_DETACHED_PROFILE"] = "profile-value"
            future = model_pool.submit(model)
            state = kwargs.get("_worker_state")
            if state is not None:
                state["future"] = future
            assert entered.wait(5)
            return False, "timeout", "", "TimeoutError"

        monkeypatch.setattr(scheduler, "_run_job_impl", run_impl)
        first = callers.submit(contextvars.copy_context().run, scheduler.run_job,
                               {"id": "first", "profile": profile})
        try:
            assert entered.wait(5)
            if profile is None:
                assert first.result(timeout=5)[0] is False
            successor = callers.submit(contextvars.copy_context().run, scheduler.run_job,
                                       {"id": "successor", "workdir": str(tmp_path)})
            assert not successor_entered.wait(0.25)
            if profile:
                assert not first.done()
                assert os.environ["HERMES_TEST_DETACHED_PROFILE"] == "profile-value"
        finally:
            release.set()
        assert first.result(timeout=5)[0] is False
        assert successor.result(timeout=5)[0] is True
        assert os.environ["HERMES_TEST_DETACHED_PROFILE"] == "original"
