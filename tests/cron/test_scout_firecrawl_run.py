import threading
import time
from unittest.mock import MagicMock

import pytest

import cron.scheduler as scheduler
from agent import firecrawl_run_state as state
from events.schema import EventType

# Captured at import so a test can put the REAL registration back after
# _patch_execution_pipeline stubs it out.
_REAL_TRY_REGISTER = scheduler._try_register_in_flight


def _block_until_deadline(limit_s=5.0):
    """Return once the deadline watchdog has decided this run is late (read through
    the worker's own contextvar), so the stubbed run crosses the deadline INSIDE
    run_job regardless of host load. A 10ms deadline against a fixed sleep fired
    before the worker had even claimed the fire on a loaded box; the run then
    exited at the pre-claim gate and the finalizer under test never ran."""
    end = time.monotonic() + limit_s
    while not scheduler._current_deadline_elapsed() and time.monotonic() < end:
        time.sleep(0.01)


class RecordingBus:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def emit(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def _emitter(bus=None):
    emitter = MagicMock()
    emitter.bus = bus or RecordingBus()
    return emitter


def _scout_job(**overrides):
    job = {"id": "scout-1", "name": "jobflow-scout"}
    job.update(overrides)
    return job


def _install_open_run():
    run, token = state.install_firecrawl_run()
    state.record_firecrawl_credits_exhausted()
    return run, token


def test_install_state_only_for_canonical_agent_scout():
    run, token = scheduler._install_scout_firecrawl_run(_scout_job())
    try:
        assert run is state.current_firecrawl_run()
    finally:
        scheduler._reset_scout_firecrawl_run(token)

    for job in (
        {"id": "tracker", "name": "jobflow-tracker-cycle"},
        {"id": "substring", "name": "custom-scout-report"},
        _scout_job(no_agent=True),
    ):
        run, token = scheduler._install_scout_firecrawl_run(job)
        assert run is None
        assert token is None
        assert state.current_firecrawl_run() is None


def test_valid_marker_is_augmented_with_one_credits_action():
    emitter = _emitter()
    run, token = _install_open_run()
    response = (
        '<AGENT_ITERATION_JSON>{"agent":"scout","summary":"done"}'
        "</AGENT_ITERATION_JSON>"
    )
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), response, success=True, firecrawl_state=run
        )
    finally:
        state.reset_firecrawl_run(token)

    assert len(emitter.bus.calls) == 1
    call = emitter.bus.calls[0]
    assert call["event_type"] == EventType.AGENT_ITERATION
    assert call["payload"]["action_required"] is True
    assert call["payload"]["action_kind"] == "credits"
    assert call["payload"]["provider_error"] == "provider_credits_exhausted"
    assert call["payload"]["provider_scope"] == "account"


def test_missing_marker_synthesizes_one_credits_iteration():
    emitter = _emitter()
    run, token = _install_open_run()
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), "plain response", success=True,
            firecrawl_state=run,
        )
    finally:
        state.reset_firecrawl_run(token)

    assert len(emitter.bus.calls) == 1
    payload = emitter.bus.calls[0]["payload"]
    assert payload["synthesized"] is True
    assert payload["action_kind"] == "credits"


def test_malformed_marker_keeps_error_then_synthesizes_credits_iteration():
    emitter = _emitter()
    run, token = _install_open_run()
    malformed = "<AGENT_ITERATION_JSON>{bad json}</AGENT_ITERATION_JSON>"
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), malformed, success=True,
            firecrawl_state=run,
        )
    finally:
        state.reset_firecrawl_run(token)

    assert [call["event_type"] for call in emitter.bus.calls] == [
        EventType.AGENT_ERROR,
        EventType.AGENT_ITERATION,
    ]
    assert emitter.bus.calls[1]["payload"]["action_kind"] == "credits"


def test_malformed_marker_claims_immediately_before_credits_emit(monkeypatch):
    order = []

    class OrderingBus(RecordingBus):
        def emit(self, **kwargs):
            order.append(("emit", kwargs["event_type"]))
            super().emit(**kwargs)

    emitter = _emitter(OrderingBus())
    run, token = _install_open_run()
    original_claim = scheduler._claim_credits_iteration
    original_fields = scheduler._credits_iteration_fields

    def recording_claim(firecrawl_state):
        order.append(("claim", firecrawl_state._credits_action_claimed))
        return original_claim(firecrawl_state)

    def recording_fields():
        order.append(("build", run._credits_action_claimed))
        return original_fields()

    monkeypatch.setattr(scheduler, "_claim_credits_iteration", recording_claim)
    monkeypatch.setattr(scheduler, "_credits_iteration_fields", recording_fields)
    malformed = "<AGENT_ITERATION_JSON>{bad json}</AGENT_ITERATION_JSON>"
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), malformed, success=True,
            firecrawl_state=run,
        )
    finally:
        state.reset_firecrawl_run(token)

    assert order == [
        ("emit", EventType.AGENT_ERROR),
        ("build", False),
        ("claim", False),
        ("emit", EventType.AGENT_ITERATION),
    ]


def test_failed_run_emits_credits_but_failed_without_402_emits_nothing():
    credits_emitter = _emitter()
    run, token = _install_open_run()
    try:
        scheduler._finalize_agent_iteration_event(
            credits_emitter, _scout_job(), "", success=False,
            firecrawl_state=run,
        )
    finally:
        state.reset_firecrawl_run(token)
    assert len(credits_emitter.bus.calls) == 1
    assert credits_emitter.bus.calls[0]["payload"]["action_kind"] == "credits"
    assert credits_emitter.bus.calls[0]["payload"]["summary"] == (
        "scout failed with Firecrawl credits exhausted"
    )

    ordinary_emitter = _emitter()
    scheduler._finalize_agent_iteration_event(
        ordinary_emitter, _scout_job(), "", success=False,
        firecrawl_state=None,
    )
    assert ordinary_emitter.bus.calls == []


def test_two_records_and_two_finalizers_attempt_credits_once():
    emitter = _emitter()
    run, token = state.install_firecrawl_run()
    try:
        assert state.record_firecrawl_credits_exhausted() is True
        assert state.record_firecrawl_credits_exhausted() is False
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), "", success=False, firecrawl_state=run
        )
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), "", success=False, firecrawl_state=run
        )
    finally:
        state.reset_firecrawl_run(token)
    assert len(emitter.bus.calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        '<AGENT_ITERATION_JSON>{"agent":"scout","summary":"done"}'
        "</AGENT_ITERATION_JSON>",
        "plain response",
        "<AGENT_ITERATION_JSON>{bad json}</AGENT_ITERATION_JSON>",
    ],
    ids=["valid", "missing", "malformed"],
)
def test_successful_finalizer_retry_is_silent_after_ambiguous_credits_emit(
    response,
):
    class FailCreditsOnceBus(RecordingBus):
        def emit(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["payload"].get("action_kind") == "credits":
                raise RuntimeError("ambiguous credits failure")

    bus = FailCreditsOnceBus()
    emitter = _emitter(bus)
    run, token = _install_open_run()
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), response, success=True, firecrawl_state=run
        )
        calls_after_first = len(bus.calls)
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), response, success=True, firecrawl_state=run
        )
    finally:
        state.reset_firecrawl_run(token)

    assert len(bus.calls) == calls_after_first


def test_malformed_error_emit_failure_still_attempts_credits_once():
    class FailErrorBus(RecordingBus):
        def emit(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["event_type"] == EventType.AGENT_ERROR:
                raise RuntimeError("diagnostic emit failure")

    bus = FailErrorBus()
    emitter = _emitter(bus)
    run, token = _install_open_run()
    malformed = "<AGENT_ITERATION_JSON>{bad json}</AGENT_ITERATION_JSON>"
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), malformed, success=True, firecrawl_state=run
        )
    finally:
        state.reset_firecrawl_run(token)

    assert [call["event_type"] for call in bus.calls] == [
        EventType.AGENT_ERROR,
        EventType.AGENT_ITERATION,
    ]
    assert bus.calls[1]["payload"]["action_kind"] == "credits"


def _patch_execution_pipeline(monkeypatch, emitter):
    monkeypatch.setattr(scheduler, "_get_event_emitter", lambda: emitter)
    monkeypatch.setattr(
        scheduler, "create_execution",
        lambda *a, **k: {"id": "execution-1"},
    )
    # 0.21.1 ownership gates: run_one_job skips a run whose claimed->running CAS
    # returns None, and the deadline watchdog records/finalizes only when
    # finish_execution returns the finalized row. Answer like the real ledger.
    monkeypatch.setattr(
        scheduler, "finish_execution", lambda *a, **k: {"id": "execution-1"},
    )
    monkeypatch.setattr(
        scheduler, "mark_execution_running",
        lambda *a, **k: {"id": "execution-1", "status": "running"},
    )
    monkeypatch.setattr(scheduler, "claim_dispatch", lambda *a, **k: True)
    # The tick worker claims the fire before run_one_job; on the per-test empty
    # store an unpatched claim loses silently and tick() never reaches run_job.
    monkeypatch.setattr(scheduler, "claim_job_for_fire", lambda *a, **k: True)
    monkeypatch.setattr(scheduler, "live_execution_for_job", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "save_job_output", lambda *a, **k: "output")
    monkeypatch.setattr(scheduler, "_deliver_result", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "mark_job_run", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_teardown_cron_agent", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_try_register_in_flight", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "_release_in_flight", lambda *a, **k: None)


def test_run_one_job_installs_only_for_scout_and_resets(monkeypatch):
    emitter = _emitter()
    _patch_execution_pipeline(monkeypatch, emitter)
    seen = []

    def fake_run_job(job, **kwargs):
        run = state.current_firecrawl_run()
        seen.append((job["name"], run is not None))
        if run is not None:
            state.record_firecrawl_credits_exhausted()
        return True, "output", "plain response", None

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    assert scheduler.run_one_job(_scout_job()) is True
    assert scheduler.run_one_job(
        {"id": "tracker", "name": "jobflow-tracker-cycle"}
    ) is True

    assert seen == [("jobflow-scout", True), ("jobflow-tracker-cycle", False)]
    assert state.current_firecrawl_run() is None
    credit_calls = [
        call for call in emitter.bus.calls
        if call["event_type"] == EventType.AGENT_ITERATION
        and call["payload"].get("action_kind") == "credits"
    ]
    assert len(credit_calls) == 1


def test_run_one_job_resets_and_finalizes_when_run_job_raises(monkeypatch):
    emitter = _emitter()
    _patch_execution_pipeline(monkeypatch, emitter)

    def fake_run_job(job, **kwargs):
        assert state.current_firecrawl_run() is not None
        state.record_firecrawl_credits_exhausted()
        raise RuntimeError("after genuine 402")

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    assert scheduler.run_one_job(_scout_job()) is False
    assert state.current_firecrawl_run() is None
    assert len(emitter.bus.calls) == 1
    assert emitter.bus.calls[0]["payload"]["action_kind"] == "credits"


def test_run_one_job_releases_slot_when_finalizer_raises_base_exception(
    monkeypatch,
):
    emitter = _emitter()
    _patch_execution_pipeline(monkeypatch, emitter)
    # 0.21.1 releases the slot inline, identity-checked against the record THIS
    # run registered (a successor's fresh record must survive), not through
    # _release_in_flight. Observe the registry itself: register for real, prove
    # the slot was held during the run, then prove it is gone once the
    # finalizer's BaseException escapes.
    monkeypatch.setattr(scheduler, "_try_register_in_flight", _REAL_TRY_REGISTER)
    with scheduler._in_flight_lock:
        scheduler._in_flight.pop("scout-1", None)
    held_during_run = []

    def fake_run_job(job, **kwargs):
        with scheduler._in_flight_lock:
            held_during_run.append("scout-1" in scheduler._in_flight)
        return True, "output", "plain response", None

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    monkeypatch.setattr(
        scheduler,
        "_finalize_agent_iteration_event",
        MagicMock(side_effect=KeyboardInterrupt("finalizer interrupted")),
    )

    with pytest.raises(KeyboardInterrupt, match="finalizer interrupted"):
        scheduler.run_one_job(_scout_job())

    assert held_during_run == [True], "positive control: the slot was never registered"
    with scheduler._in_flight_lock:
        assert "scout-1" not in scheduler._in_flight
    assert state.current_firecrawl_run() is None


def test_tick_installs_and_finalizes_same_scout_lifecycle(monkeypatch):
    emitter = _emitter()
    _patch_execution_pipeline(monkeypatch, emitter)
    monkeypatch.setattr(
        scheduler, "get_due_and_skipped_jobs", lambda: ([_scout_job()], [])
    )
    monkeypatch.setattr(scheduler, "advance_next_runs", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "load_config", lambda: {})
    monkeypatch.setattr(scheduler, "_sweep_mcp_orphans", lambda: None, raising=False)

    def fake_run_job(job, **kwargs):
        assert state.current_firecrawl_run() is not None
        state.record_firecrawl_credits_exhausted()
        return True, "output", "plain response", None

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    assert scheduler.tick(verbose=False, sync=True) == 1
    assert state.current_firecrawl_run() is None
    credit_calls = [
        call for call in emitter.bus.calls
        if call["event_type"] == EventType.AGENT_ITERATION
        and call["payload"].get("action_kind") == "credits"
    ]
    assert len(credit_calls) == 1


def test_tick_abandoned_scout_emits_credits_once_without_late_iteration(monkeypatch):
    emitter = _emitter()
    _patch_execution_pipeline(monkeypatch, emitter)
    monkeypatch.setattr(
        scheduler, "get_due_and_skipped_jobs", lambda: ([_scout_job()], [])
    )
    monkeypatch.setattr(scheduler, "advance_next_runs", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "load_config", lambda: {})
    monkeypatch.setattr(scheduler, "_sweep_mcp_orphans", lambda: None, raising=False)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 0.5)
    worker_finished = threading.Event()
    worker_context_after_reset = []
    original_reset = scheduler._reset_scout_firecrawl_run

    def recording_reset(token):
        original_reset(token)
        worker_context_after_reset.append(state.current_firecrawl_run())
        worker_finished.set()

    monkeypatch.setattr(scheduler, "_reset_scout_firecrawl_run", recording_reset)

    def fake_run_job(job, **kwargs):
        assert state.current_firecrawl_run() is not None
        state.record_firecrawl_credits_exhausted()
        _block_until_deadline()
        return True, "output", "plain response", None

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    assert scheduler.tick(verbose=False, sync=True) == 0
    assert worker_finished.wait(1)

    assert state.current_firecrawl_run() is None
    assert worker_context_after_reset == [None]
    credit_calls = [
        call for call in emitter.bus.calls
        if call["event_type"] == EventType.AGENT_ITERATION
        and call["payload"].get("action_kind") == "credits"
    ]
    assert len(credit_calls) == 1
    assert credit_calls[0]["payload"]["summary"] == (
        "scout failed with Firecrawl credits exhausted"
    )
    assert not any(
        call["event_type"] == EventType.AGENT_ITERATION
        and call["payload"].get("action_kind") != "credits"
        for call in emitter.bus.calls
    )


def test_tick_abandoned_scout_finalizes_credits_recorded_after_deadline(monkeypatch):
    emitter = _emitter()
    _patch_execution_pipeline(monkeypatch, emitter)
    monkeypatch.setattr(
        scheduler, "get_due_and_skipped_jobs", lambda: ([_scout_job()], [])
    )
    monkeypatch.setattr(scheduler, "advance_next_runs", lambda *a, **k: None)
    monkeypatch.setattr(scheduler, "load_config", lambda: {})
    monkeypatch.setattr(scheduler, "_sweep_mcp_orphans", lambda: None, raising=False)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda job: 0.5)
    worker_finished = threading.Event()

    def fake_run_job(job, **kwargs):
        _block_until_deadline()
        state.record_firecrawl_credits_exhausted()
        return False, "output", "", "credits"

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    original_reset = scheduler._reset_scout_firecrawl_run

    def recording_reset(token):
        original_reset(token)
        worker_finished.set()

    monkeypatch.setattr(scheduler, "_reset_scout_firecrawl_run", recording_reset)

    assert scheduler.tick(verbose=False, sync=True) == 0
    assert worker_finished.wait(1)
    credits = [
        call for call in emitter.bus.calls
        if call["event_type"] == EventType.AGENT_ITERATION
        and call["payload"].get("action_kind") == "credits"
    ]
    assert len(credits) == 1


def test_emit_failure_after_claim_is_not_retried():
    bus = RecordingBus(error=RuntimeError("ambiguous bus failure"))
    emitter = _emitter(bus)
    run, token = _install_open_run()
    try:
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), "", success=False, firecrawl_state=run
        )
        scheduler._finalize_agent_iteration_event(
            emitter, _scout_job(), "", success=False, firecrawl_state=run
        )
    finally:
        state.reset_firecrawl_run(token)
    assert len(bus.calls) == 1
