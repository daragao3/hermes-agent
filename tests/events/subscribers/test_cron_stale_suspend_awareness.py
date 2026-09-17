"""Host-suspend awareness in CronStaleMonitor / CronStaleResponder (2026-09-17).

Replays the 2026-09-17 shape: the host entered Modern Standby 18:30:40Z and
resumed 01:49:33Z (7h19m). 15s after resume the monitor emitted CRON_STALE for
postgres-sync / jobflow-approved-release / tracker-operator-drain at 26330s and
for the ticker at 26330s, and the responder stopped all three as "still running
26329s with no terminal event" -- runs that could not have progressed for a
second of that time. The gateway watchdog handled the identical signal
correctly ("host was suspended, not a dead gateway; skipping restart"); these
tests pin the same rule for cron ages.

The rule is the scheduler's own (cron/scheduler.py::suspended_seconds): a poll
gap under 60s is jitter and counts in full; above it, everything but one poll
interval is time the loop -- and the host -- was not running.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from events.bus import EventBus
from events.schema import Event, EventType
from events.subscribers import cron_stale_monitor as monitor_mod
from events.subscribers.cron_stale_monitor import CronStaleMonitor, _suspended_seconds
from events.subscribers.cron_stale_responder import CronStaleResponder

SUSPEND = timedelta(hours=7, minutes=19)


@pytest.fixture
def bus(tmp_path):
    b = EventBus(db_path=tmp_path / "event_bus.db")
    yield b
    b.close()


def _stale_events(bus):
    return [e for e in bus.query() if e.event_type == EventType.CRON_STALE]


def _monitor(bus) -> CronStaleMonitor:
    m = CronStaleMonitor(bus)
    bus._execute(
        "INSERT OR REPLACE INTO subscriber_cursors "
        "(subscriber_id, last_rowid, updated_at) VALUES (?, 0, datetime('now'))",
        (m.subscriber_id,),
    )
    return m


def _start(bus, job_id: str, started_at: datetime) -> None:
    eid = bus.emit(
        event_type=EventType.CRON_STARTED, source="scheduler",
        payload={"job_id": job_id, "job_name": job_id, "execution_id": f"x-{job_id}"},
    )
    import sqlite3
    conn = sqlite3.connect(str(bus.db_path))
    conn.execute("UPDATE events SET timestamp = ? WHERE event_id = ?", (started_at.isoformat(), eid))
    conn.commit(); conn.close()


def _patch_ticker_age(monkeypatch, value):
    import cron.jobs
    monkeypatch.setattr(cron.jobs, "get_ticker_heartbeat_age", lambda: value)


# --- the gap rule itself ------------------------------------------------------


def test_gap_rule_matches_the_scheduler():
    """Kept in step with cron.scheduler.suspended_seconds by construction."""
    from cron.scheduler import _CRON_SUSPEND_GAP_SECS, suspended_seconds

    assert monitor_mod._SUSPEND_GAP_SECS == _CRON_SUSPEND_GAP_SECS
    for gap, poll in ((0.0, 60.0), (59.0, 60.0), (60.0, 60.0), (61.0, 5.0), (26330.0, 60.0), (300.0, 300.0)):
        assert _suspended_seconds(gap, poll) == suspended_seconds(gap, poll)
    assert _suspended_seconds(26330.0, 60.0) == 26270.0
    assert _suspended_seconds(45.0, 60.0) == 0.0, "jitter under the threshold counts in full"


# --- monitor: open runs -------------------------------------------------------


def test_a_run_open_across_a_suspend_is_not_stale_on_resume(bus, monkeypatch):
    """15s after a 7h19m standby, a run started 60s before the standby has
    ~75s of ACTIVE age, not 26330s."""
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, 5.0)
    t_sleep = datetime.now(timezone.utc) - SUSPEND - timedelta(seconds=15)
    _start(bus, "postgres-sync", t_sleep - timedelta(seconds=60))
    # The poll just before the host slept.
    mon._credit_suspend_gap(t_sleep - timedelta(seconds=30))
    mon.poll()  # 15s after resume, wall clock
    assert _stale_events(bus) == [], "a suspend was read as a wedged run"
    # abs=10: the two now() reads (t_sleep here, poll() inside) are seconds apart
    # under the parallel suite, and that wall-clock drift lands in the credit.
    assert mon._suspend_credit["postgres-sync"] == pytest.approx(
        _suspended_seconds(SUSPEND.total_seconds() + 45, 60.0), abs=10.0
    )


def test_a_run_that_was_already_wedged_still_alerts_after_the_suspend(bus, monkeypatch):
    """Discount the suspend, not the wedge: 1300s of active age before the
    host slept is still over the 1200s default threshold afterwards."""
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, 5.0)
    t_sleep = datetime.now(timezone.utc) - SUSPEND - timedelta(seconds=15)
    _start(bus, "wedged", t_sleep - timedelta(seconds=1300))
    mon._credit_suspend_gap(t_sleep - timedelta(seconds=30))
    mon.poll()
    stale = _stale_events(bus)
    assert len(stale) == 1 and stale[0].payload["job_id"] == "wedged"
    # And the reported age is ACTIVE time: ~1345s, nowhere near 27k.
    assert 1300 <= stale[0].payload["age_seconds"] < 1500


def test_a_run_started_after_the_resume_gets_no_credit(bus, monkeypatch):
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, 5.0)
    mon._credit_suspend_gap(datetime.now(timezone.utc) - SUSPEND)
    mon.poll()  # the gap is observed here, with nothing open
    _start(bus, "fresh", datetime.now(timezone.utc))
    mon.poll()
    assert mon._suspend_credit.get("fresh", 0.0) == 0.0


def test_credit_is_dropped_when_the_run_finishes(bus, monkeypatch):
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, 5.0)
    t_sleep = datetime.now(timezone.utc) - SUSPEND
    _start(bus, "j", t_sleep - timedelta(seconds=10))
    mon._credit_suspend_gap(t_sleep)
    mon.poll()
    assert "j" in mon._suspend_credit
    bus.emit(event_type=EventType.CRON_COMPLETED, source="scheduler",
             payload={"job_id": "j", "job_name": "j", "execution_id": "x-j"})
    mon.poll()
    assert "j" not in mon._suspend_credit and "j" not in mon._open_jobs


def test_ordinary_poll_jitter_is_charged_in_full(bus, monkeypatch):
    """A 45s gap on a loaded host is not a suspend; the run really did age."""
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, 5.0)
    now = datetime.now(timezone.utc)
    _start(bus, "j", now - timedelta(seconds=10))
    mon._credit_suspend_gap(now - timedelta(seconds=45))
    mon.poll()
    assert mon._suspend_credit.get("j", 0.0) == 0.0


# --- monitor: the ticker -----------------------------------------------------


def test_ticker_heartbeat_aged_by_a_suspend_is_not_a_dead_ticker(bus, monkeypatch):
    """The ticker thread cannot beat while the host sleeps; its heartbeat
    reads 26330s old on the first poll after resume and must not page."""
    mon = _monitor(bus)
    resume_age = SUSPEND.total_seconds() + 15
    _patch_ticker_age(monkeypatch, resume_age)
    mon._credit_suspend_gap(datetime.now(timezone.utc) - SUSPEND - timedelta(seconds=15))
    mon.poll()
    assert _stale_events(bus) == []


def test_ticker_dead_before_the_suspend_still_pages(bus, monkeypatch):
    """A heartbeat that was already 400s stale when the host slept is still
    400s stale (over the 300s threshold) after the suspend is discounted."""
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, SUSPEND.total_seconds() + 400)
    mon._credit_suspend_gap(datetime.now(timezone.utc) - SUSPEND)
    mon.poll()
    stale = _stale_events(bus)
    assert len(stale) == 1 and stale[0].payload["scope"] == "ticker"


def test_ticker_credit_retires_once_the_heartbeat_advances(bus, monkeypatch):
    mon = _monitor(bus)
    _patch_ticker_age(monkeypatch, SUSPEND.total_seconds() + 15)
    mon._credit_suspend_gap(datetime.now(timezone.utc) - SUSPEND)
    mon.poll()
    assert mon._ticker_suspend_credit > 0
    _patch_ticker_age(monkeypatch, 5.0)  # the ticker beat again
    mon.poll()
    assert mon._ticker_suspend_credit == 0.0
    # ...so a LATER genuine stall earns its own alert.
    _patch_ticker_age(monkeypatch, 400.0)
    mon.poll()
    assert len(_stale_events(bus)) == 1


# --- responder ---------------------------------------------------------------


def _stale_event(job_id="jobflow-approved-release", age=0, execution_id="e1") -> Event:
    return Event.create(
        event_type=EventType.CRON_STALE, source="cron-stale-monitor",
        payload={"job_id": job_id, "job_name": job_id, "age_seconds": age,
                 "threshold_seconds": 2400, "execution_id": execution_id},
    )


@pytest.fixture
def stops(monkeypatch):
    calls = []
    import cron.inflight

    def _fake(job_id, *, session_id=None, by=None, reason=None):
        calls.append({"job_id": job_id, "reason": reason})
        return True

    monkeypatch.setattr(cron.inflight, "request_stop", _fake)
    return calls


def _running(monkeypatch):
    import cron.executions
    monkeypatch.setattr(cron.executions, "get_execution", lambda *_a, **_k: {"status": "running"})


def test_responder_does_not_stop_a_run_the_host_slept_through(bus, stops, monkeypatch):
    """Tracked at 0s, host sleeps 7h19m, first poll 15s after resume: the run
    has 15s of active age against a 7200s bound. On 2026-09-17 this stopped
    three healthy runs."""
    _running(monkeypatch)
    r = CronStaleResponder(bus)
    r.handle(_stale_event(age=0))
    rec = r._stale_runs["jobflow-approved-release"]
    rec["alert_seen_at"] = datetime.now(timezone.utc) - SUSPEND - timedelta(seconds=15)
    r._credit_suspend_gap(rec["alert_seen_at"])          # the poll right after the alert
    r._credit_suspend_gap(datetime.now(timezone.utc))     # the first poll after resume
    r._check_remediate()
    assert stops == [], "stopped a run that was asleep with the host"
    assert r._run_age_seconds(rec, datetime.now(timezone.utc)) < 120


def test_responder_still_stops_a_run_wedged_for_the_bound_of_active_time(bus, stops, monkeypatch):
    """The discount is exactly the suspend: 7000s of active age before the
    sleep plus 300s after it crosses the 7200s bound."""
    _running(monkeypatch)
    r = CronStaleResponder(bus)
    r.handle(_stale_event(age=7000))
    rec = r._stale_runs["jobflow-approved-release"]
    now = datetime.now(timezone.utc)
    rec["alert_seen_at"] = now - SUSPEND - timedelta(seconds=300)
    r._credit_suspend_gap(rec["alert_seen_at"])            # the poll at the alert
    r._credit_suspend_gap(now - timedelta(seconds=300))    # first poll after resume: the 7h19m gap
    for back in range(240, -1, -60):                       # ordinary 60s polls while awake
        r._credit_suspend_gap(now - timedelta(seconds=back))
    r._check_remediate()
    assert len(stops) == 1
    assert "26" not in stops[0]["reason"].split("still running ")[1][:3], stops[0]["reason"]


def test_responder_ignores_jitter_gaps(bus, stops, monkeypatch):
    _running(monkeypatch)
    r = CronStaleResponder(bus)
    r.handle(_stale_event(age=7150))
    rec = r._stale_runs["jobflow-approved-release"]
    rec["alert_seen_at"] = datetime.now(timezone.utc) - timedelta(seconds=55)
    r._credit_suspend_gap(rec["alert_seen_at"])
    r._credit_suspend_gap(datetime.now(timezone.utc))  # a 55s gap: jitter, charged in full
    r._check_remediate()
    assert len(stops) == 1, "a 55s gap is not a suspend; the run genuinely reached the bound"
