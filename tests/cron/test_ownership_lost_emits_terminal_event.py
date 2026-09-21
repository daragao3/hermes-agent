"""The ownership-lost teardown path must emit the terminal event it records.

Both branches of _record_fire_ownership_lost write a terminal state to
executions.db. Before 2026-09-21 neither emitted anything on the event bus, so
every such execution looked -- to the bus -- like a job that started and never
ended. Measured 2026-09-20: 8 of 8 executions ever carrying "Interrupted by
shutdown before terminal completion." had an executions.db row and NO
cron_completed/cron_failed event. cron-stale-monitor, the dashboards and the
daily triage all read the bus, not the store.
"""
import pytest

from cron import scheduler


@pytest.fixture
def spy(monkeypatch):
    """Neutralise the store writes; capture what reaches the emitter."""
    seen = {"emitted": [], "finished": [], "marked": []}

    class _Emitter:
        def on_job_completed(self, job_id, job_name, **kwargs):
            seen["emitted"].append({"job_id": job_id, "job_name": job_name, **kwargs})
            return "evt-1"

    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: _Emitter())
    monkeypatch.setattr(scheduler, "finish_execution",
                        lambda execution_id, **kw: seen["finished"].append((execution_id, kw)))
    monkeypatch.setattr(scheduler, "mark_job_run",
                        lambda *a, **kw: seen["marked"].append((a, kw)))
    return seen


JOB = {"id": "abc123", "name": "tracker-identity-repair"}


def test_the_owner_fenced_branch_emits_cron_failed(spy, monkeypatch):
    """THE 2026-09-20 DEFECT: this branch recorded the outcome and told nobody."""
    monkeypatch.setattr(scheduler, "heartbeat_fire_claim", lambda *a, **kw: True)

    scheduler._record_fire_ownership_lost(JOB, "owner-1", "exec-1", duration=90.5)

    assert spy["marked"], "the store write must still happen"
    assert spy["finished"], "finish_execution must still be called"
    assert len(spy["emitted"]) == 1, "exactly one terminal event"
    ev = spy["emitted"][0]
    assert ev["job_id"] == "abc123"
    assert ev["job_name"] == "tracker-identity-repair"
    assert ev["success"] is False
    assert ev["duration"] == 90.5
    assert ev["execution_id"] == "exec-1"
    assert "Interrupted by shutdown" in ev["error"]


def test_the_discard_branch_also_emits(spy, monkeypatch):
    """The else-branch has the same gap and the same fix."""
    monkeypatch.setattr(scheduler, "heartbeat_fire_claim", lambda *a, **kw: False)

    scheduler._record_fire_ownership_lost(JOB, None, "exec-2", duration=3.0)

    assert not spy["marked"], "the discard branch must not write last_status"
    assert len(spy["emitted"]) == 1
    assert "stale result was discarded" in spy["emitted"][0]["error"]


def test_an_emitter_fault_never_escapes(spy, monkeypatch):
    """This runs on a teardown path that has already lost its fire claim. An
    emitter fault must not convert a recorded outcome into an exception."""
    monkeypatch.setattr(scheduler, "heartbeat_fire_claim", lambda *a, **kw: True)

    class _Boom:
        def on_job_completed(self, *a, **kw):
            raise RuntimeError("bus down")

    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: _Boom())

    scheduler._record_fire_ownership_lost(JOB, "owner-1", "exec-3", duration=1.0)

    assert spy["finished"], "the store write must survive an emitter fault"


def test_a_missing_emitter_is_not_an_error(spy, monkeypatch):
    """_get_event_emitter returns None in a process with no bus (the cached
    False sentinel). That is a normal state, not a failure."""
    monkeypatch.setattr(scheduler, "heartbeat_fire_claim", lambda *a, **kw: True)
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: None)

    scheduler._record_fire_ownership_lost(JOB, "owner-1", "exec-4", duration=1.0)

    assert spy["finished"]
    assert spy["emitted"] == []
