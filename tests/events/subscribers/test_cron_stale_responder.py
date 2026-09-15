"""CronStaleResponder — the consumer that acts on CRON_STALE.

Before this subscriber, CRON_STALE had no consumer at all: the alert sat in the
bus at ``status='pending'`` and the wedged run kept going.  jobflow-notifier was
flagged stale 1213s into a run whose median is 450s and then ran another 7.8
hours (29,288s total), stalling every financier-profile job for 7.75h behind the
read lock it never released.

This subscriber can TERMINATE work, so most of what is asserted here is
restraint: the cases where it must NOT act.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from events.bus import EventBus
from events.schema import Event, EventType
from events.subscribers.cron_stale_responder import CronStaleResponder


@pytest.fixture
def bus(tmp_path):
    b = EventBus(db_path=tmp_path / "event_bus.db")
    yield b
    b.close()


def _stale_event(job_id="j1", job_name="jobflow-notifier", age=1213, execution_id="e1"):
    return Event.create(
        event_type=EventType.CRON_STALE,
        source="cron-stale-monitor",
        payload={
            "job_id": job_id,
            "job_name": job_name,
            "age_seconds": age,
            "threshold_seconds": 1200,
            "execution_id": execution_id,
        },
    )


def _terminal_event(kind, job_id="j1", job_name="jobflow-notifier"):
    return Event.create(event_type=kind, source="cron", payload={
        "job_id": job_id, "job_name": job_name})


@pytest.fixture
def responder(bus):
    return CronStaleResponder(bus, remediate_after_seconds=7200)


@pytest.fixture
def stops(monkeypatch):
    """Capture request_stop calls without writing to the real cron dir."""
    calls = []

    def _fake_request_stop(job_id, *, session_id=None, by=None, reason=None):
        calls.append({"job_id": job_id, "by": by, "reason": reason})
        return {"job_id": job_id}

    import cron.inflight

    monkeypatch.setattr(cron.inflight, "request_stop", _fake_request_stop)
    return calls


def _set_execution_status(monkeypatch, status):
    import cron.executions

    monkeypatch.setattr(
        cron.executions, "get_execution",
        lambda execution_id: {"id": execution_id, "status": status})


def _age_the_alert(responder, job_id, seconds):
    """Backdate the tracked alert so the next poll sees ``seconds`` of run age."""
    rec = responder._stale_runs[job_id]
    rec["alert_seen_at"] = datetime.now(timezone.utc) - timedelta(
        seconds=seconds - rec["age_at_alert"])


class TestRestraint:
    """Everything this must NOT do. These are the load-bearing assertions."""

    def test_a_fresh_stale_alert_stops_nothing(self, responder, stops, monkeypatch):
        """The stale threshold is near the normal band; killing there destroys
        healthy work. jobflow-scout fired at 2403s against 2400 on a run that
        finished fine at 2900s."""
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event(age=1213))
        responder._check_remediate()
        assert stops == [], "stopped a run that had only just gone stale"

    def test_a_run_that_finishes_on_its_own_is_never_stopped(
            self, responder, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event())
        responder.handle(_terminal_event(EventType.CRON_COMPLETED))
        _age_the_alert(responder, "j1", 99999) if responder._stale_runs else None
        responder._check_remediate()
        assert stops == []
        assert responder._stale_runs == {}

    def test_a_failed_run_is_dropped_too(self, responder, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event())
        responder.handle(_terminal_event(EventType.CRON_FAILED))
        responder._check_remediate()
        assert stops == []

    def test_it_will_not_stop_a_LATER_run_of_the_same_job(
            self, responder, stops, monkeypatch):
        """THE interlock. request_stop with no session id stops whichever run of
        the job is in flight, so acting on a stale alert whose own execution has
        already finished would kill an innocent successor."""
        responder.handle(_stale_event(execution_id="e1"))
        _age_the_alert(responder, "j1", 99999)
        _set_execution_status(monkeypatch, "completed")   # e1 is over; e2 may be live
        responder._check_remediate()
        assert stops == [], "stopped a job whose stale execution had already ended"
        assert responder._stale_runs == {}, "should stop tracking a finished execution"

    def test_an_unreadable_execution_refuses_to_act(self, responder, stops, monkeypatch):
        import cron.executions

        def _boom(execution_id):
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr(cron.executions, "get_execution", _boom)
        responder.handle(_stale_event())
        _age_the_alert(responder, "j1", 99999)
        responder._check_remediate()
        assert stops == [], "acted without being able to prove which run it was"

    def test_a_stale_alert_without_an_execution_id_never_stops(
            self, responder, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event(execution_id=None))
        _age_the_alert(responder, "j1", 99999)
        responder._check_remediate()
        assert stops == []

    def test_a_non_positive_bound_disables_remediation(self, bus, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        r = CronStaleResponder(bus, remediate_after_seconds=0)
        r.handle(_stale_event())
        _age_the_alert(r, "j1", 999999)
        r._check_remediate()
        assert stops == [], "remediation ran while disabled"

    def test_one_stop_per_execution(self, responder, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event())
        _age_the_alert(responder, "j1", 99999)
        responder._check_remediate()
        responder._check_remediate()
        responder._check_remediate()
        assert len(stops) == 1, f"asked {len(stops)} times"


class TestRemediation:
    def test_a_genuinely_wedged_run_is_stopped_past_the_bound(
            self, responder, stops, monkeypatch):
        """The jobflow-notifier case: still running, no terminal event, far past
        any sane bound."""
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event(age=1213))
        _age_the_alert(responder, "j1", 29288)      # the real hang's duration
        responder._check_remediate()
        assert len(stops) == 1
        assert stops[0]["job_id"] == "j1"
        assert stops[0]["by"] == "cron-stale-responder"
        assert "29288" in stops[0]["reason"] or "2928" in stops[0]["reason"]

    def test_the_bound_is_honoured_exactly(self, responder, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event(age=1213))
        _age_the_alert(responder, "j1", 7199)
        responder._check_remediate()
        assert stops == [], "fired one second early"
        _age_the_alert(responder, "j1", 7201)
        responder._check_remediate()
        assert len(stops) == 1

    def test_a_per_job_override_applies(self, bus, stops, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        r = CronStaleResponder(
            bus, remediate_after_seconds=7200,
            per_job_remediate={"jobflow-notifier": 1800})
        r.handle(_stale_event(age=1213))
        _age_the_alert(r, "j1", 1801)
        r._check_remediate()
        assert len(stops) == 1, "per-job override was ignored"

    def test_the_stop_is_reported_on_the_bus(self, responder, stops, bus, monkeypatch):
        _set_execution_status(monkeypatch, "running")
        responder.handle(_stale_event())
        _age_the_alert(responder, "j1", 99999)
        responder._check_remediate()
        reported = [e for e in bus.query()
                    if e.event_type is EventType.AGENT_ERROR
                    and (e.payload or {}).get("action") == "stop_requested"]
        assert len(reported) == 1, "stopped a run without telling anyone"
        assert reported[0].payload["job_name"] == "jobflow-notifier"

    def test_a_failing_request_stop_does_not_mark_it_stopped(
            self, responder, bus, monkeypatch):
        """If the stop could not be written, leave it for the operator and stay
        eligible to retry -- do not silently record success."""
        _set_execution_status(monkeypatch, "running")
        import cron.inflight

        def _boom(job_id, **kw):
            raise OSError("read-only cron dir")

        monkeypatch.setattr(cron.inflight, "request_stop", _boom)
        responder.handle(_stale_event())
        _age_the_alert(responder, "j1", 99999)
        responder._check_remediate()
        assert responder._stale_runs["j1"]["stop_requested"] is False


class TestRoster:
    def test_the_responder_is_in_the_canonical_roster(self):
        """startup() asserts registered subscribers against this file and emits
        an AGENT_ERROR on any mismatch, so a missing entry breaks every boot."""
        from pathlib import Path

        roster = json.loads(
            (Path(__file__).resolve().parents[3] / "events" / "subscriber_roster.json")
            .read_text(encoding="utf-8"))
        entry = next((s for s in roster["subscribers"]
                      if s.get("id") == CronStaleResponder.subscriber_id), None)
        assert entry is not None, "not in the roster -- the next boot emits AGENT_ERROR"
        assert entry["status"] == "live"
