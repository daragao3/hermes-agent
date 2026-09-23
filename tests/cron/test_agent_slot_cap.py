"""Long AGENT jobs may never occupy every cron pool worker.

THE 2026-09-18 STARVATION (13:03-14:03 local, profiles/main/cron/executions.db): with
HERMES_CRON_MAX_PARALLEL=4 all four workers were held by long agent jobs (tailor, applier, scout,
ats-url-resolve, researcher, daytime-relay, inbox-sweeper; scout and ats-url-resolve ran to the
3600 s wall clock), and short no_agent scripts -- claimed on time -- waited 1,063-2,003 s to start.

Rule under test: with a bounded pool of N >= 2, at most N-1 agent jobs are handed to the pool; an
agent job over the cap waits WITHOUT holding a worker and starts, FIFO, when an agent run returns;
nothing is dropped; unbounded and N == 1 are ungated.
"""

import concurrent.futures
import threading
import time

import pytest


@pytest.fixture
def gate(monkeypatch):
    """Isolated gate state + stubbed ledger; jobs block until their event is set."""
    import cron.scheduler as sched

    monkeypatch.setattr(sched, "_agent_slots_in_use", 0)
    monkeypatch.setattr(sched, "_agent_gate_cap", None)
    monkeypatch.setattr(sched, "_agent_waiting", [])
    monkeypatch.setattr(sched, "create_execution",
                        lambda job_id, **_kw: {"id": f"{job_id}-exec"})
    finished = []
    monkeypatch.setattr(sched, "finish_execution",
                        lambda eid, **kw: finished.append((eid, kw)))

    started = []          # job ids in the order their deadline wrapper (== real start) ran
    deadline_calls = []   # proves the deadline clock starts only when the job starts
    release = {}
    lock = threading.Lock()

    def fake_deadline(job, process_fn, _abandon, _ctx, **_kw):
        with lock:
            deadline_calls.append(job["id"])
        return process_fn(job)

    monkeypatch.setattr(sched, "_run_callable_with_deadline", fake_deadline)

    def process_job(job, **_kw):
        with lock:
            started.append(job["id"])
        release[job["id"]].wait(timeout=10)
        return job["id"]

    def submit(pool, job_id, *, no_agent=False, cap):
        release.setdefault(job_id, threading.Event())
        job = {"id": job_id, "name": job_id, "no_agent": no_agent}
        return sched._submit_with_guard(job, pool, process_job, agent_cap=cap)

    ns = type("G", (), {})()
    ns.sched, ns.started, ns.deadline_calls, ns.release = sched, started, deadline_calls, release
    ns.submit, ns.finished = submit, finished
    yield ns
    for ev in release.values():
        ev.set()


def _wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _uid(tag):
    import uuid
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def test_cap_is_n_minus_1_for_saturating_agent_jobs(gate):
    """N=4, four long agent jobs submitted: exactly three run, the fourth waits."""
    cap = gate.sched._agent_slot_cap(4)
    assert cap == 3
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        ids = [_uid("agent") for _ in range(4)]
        futs = [gate.submit(pool, i, cap=cap) for i in ids]
        assert all(f is not None for f in futs)
        assert _wait_for(lambda: len(gate.started) == 3)
        time.sleep(0.3)
        assert len(gate.started) == 3, f"agent jobs filled every worker: {gate.started}"
        assert ids[3] not in gate.started
        for i in ids:
            gate.release[i].set()
        assert [f.result(timeout=10) for f in futs] == ids


def test_no_agent_job_starts_immediately_while_n_minus_1_agents_run(gate):
    """THE 09-18 SYMPTOM: a short script must not wait behind long agents -- and the queued
    fourth agent must not be holding the worker it needs."""
    cap = gate.sched._agent_slot_cap(4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        agents = [_uid("agent") for _ in range(4)]
        futs = [gate.submit(pool, i, cap=cap) for i in agents]
        assert _wait_for(lambda: len(gate.started) == 3)
        script = _uid("script")
        sfut = gate.submit(pool, script, no_agent=True, cap=cap)
        assert _wait_for(lambda: script in gate.started, timeout=2), (
            "no_agent job did not get the reserved worker -- the 09-18 starvation")
        gate.release[script].set()
        assert sfut.result(timeout=5) == script
        for i in agents:
            gate.release[i].set()
        for f in futs:
            f.result(timeout=10)


def test_queued_agent_starts_when_an_agent_slot_frees_and_its_deadline_starts_then(gate):
    cap = gate.sched._agent_slot_cap(4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        agents = [_uid("agent") for _ in range(4)]
        futs = [gate.submit(pool, i, cap=cap) for i in agents]
        assert _wait_for(lambda: len(gate.started) == 3)
        queued = agents[3]
        assert queued not in gate.deadline_calls, "deadline clock started while still queued"
        assert not futs[3].done()
        gate.release[agents[0]].set()
        assert _wait_for(lambda: queued in gate.started), "queued agent never started"
        assert queued in gate.deadline_calls
        for i in agents:
            gate.release[i].set()
        assert [f.result(timeout=10) for f in futs] == agents


def test_no_job_is_lost_and_duplicates_are_still_refused(gate):
    """Ten agent jobs through a cap of 1 (N=2): every one runs exactly once; re-submitting a
    QUEUED job is refused as already running, exactly like a pool-queued job."""
    cap = gate.sched._agent_slot_cap(2)
    assert cap == 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ids = [_uid("agent") for _ in range(10)]
        futs = [gate.submit(pool, i, cap=cap) for i in ids]
        assert _wait_for(lambda: len(gate.started) == 1)
        assert gate.submit(pool, ids[5], cap=cap) is None, "a queued job was dispatched twice"
        for i in ids:
            gate.release[i].set()
        assert [f.result(timeout=10) for f in futs] == ids
    assert sorted(gate.started) == sorted(ids)
    assert len(gate.started) == len(set(gate.started)) == 10
    assert gate.sched._agent_slots_in_use == 0 and gate.sched._agent_waiting == []


@pytest.mark.parametrize("max_workers", [None, 1])
def test_unbounded_and_single_worker_are_ungated(gate, max_workers):
    assert gate.sched._agent_slot_cap(max_workers) is None
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers or 4) as pool:
        ids = [_uid("agent") for _ in range(max_workers or 4)]
        futs = [gate.submit(pool, i, cap=None) for i in ids]
        assert _wait_for(lambda: len(gate.started) == len(ids)), "ungated agents were held back"
        assert gate.sched._agent_waiting == []
        for i in ids:
            gate.release[i].set()
        for f in futs:
            f.result(timeout=10)


def test_queued_waiter_whose_dispatch_fails_is_released_not_lost_silently(gate):
    """A waiter the pool refuses (shutdown) releases its claim and finishes its execution."""
    cap = gate.sched._agent_slot_cap(2)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    first, second = _uid("agent"), _uid("agent")
    f1 = gate.submit(pool, first, cap=cap)
    assert _wait_for(lambda: first in gate.started)
    f2 = gate.submit(pool, second, cap=cap)
    assert not f2.done()
    pool.shutdown(wait=False)
    gate.release[first].set()
    f1.result(timeout=5)
    assert _wait_for(f2.done)
    with pytest.raises(RuntimeError):
        f2.result()
    assert any(eid == f"{second}-exec" and kw.get("success") is False for eid, kw in gate.finished)
    assert gate.sched.try_register_running_job(second), "claim leaked for a job that never ran"
    gate.sched.release_running_job(second)
    assert gate.sched._agent_slots_in_use == 0


def test_tick_passes_the_n_minus_1_cap(monkeypatch):
    """The wiring: tick() derives agent_cap from max_parallel."""
    import cron.scheduler as sched

    seen = []
    monkeypatch.setattr(sched, "_resolve_max_parallel_workers", lambda: 4)
    monkeypatch.setattr(sched, "get_due_and_skipped_jobs",
                        lambda: ([{"id": "j1", "name": "j1"}], []))
    monkeypatch.setattr(sched, "advance_next_runs", lambda *_a, **_kw: None)
    monkeypatch.setattr(sched, "_submit_with_guard",
                        lambda job, pool, fn, **kw: seen.append(kw.get("agent_cap")))
    sched.tick(verbose=False, sync=True)
    assert seen == [3]
