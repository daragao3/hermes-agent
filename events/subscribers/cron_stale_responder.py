"""CronStaleResponder — the consumer that acts on CRON_STALE.

``CronStaleMonitor`` DETECTS a cron run that started and never finished and
emits ``CRON_STALE``.  Until this subscriber existed nothing consumed that
event: the alert sat in the bus at ``status='pending'`` and the wedged run kept
running.

That is not theoretical.  On 2026-09-14 ``jobflow-notifier`` was flagged stale
at 11:20:46Z — 1213s into a run whose median is 450s — and then ran for another
**7.8 hours**, ending 19:08:41Z with ``RuntimeError: Hermes can't reach the
model provider`` after 29,288s (8.14h).  It held its readers-writer READ lock
the whole time, and every ``profile`` job is a writer, so the financier profile
stalled behind it for 7.75 hours.  The alert was correct, timely, and
completely inert.

WHAT THIS DOES — two stages, deliberately far apart:

1. ESCALATE, on the CRON_STALE itself: record the run and log it, and let the
   base class mark the event handled instead of leaving it pending forever.
2. REMEDIATE, only after a SECOND and much larger bound: ask the scheduler to
   stop the run through the same operator path ``hermes cron stop`` uses —
   :func:`cron.inflight.request_stop`.  That writes
   ``<CRON_DIR>/stop-requests/<job_id>.json``; the run's own watchdog poll
   consumes it and interrupts the agent exactly the way a timeout would,
   raising ``CronRunStoppedByOperator`` so the outcome reads as a deliberate
   stop rather than a crash.

This subscriber invents NO new kill mechanism and holds no new authority: it
triggers an action an operator could already take by hand.

WHY THE SECOND BOUND IS LARGE, NOT A SMALL MULTIPLE

The stale threshold answers "is this run worth looking at", and
``cron_stale_thresholds.json`` asks for a value just above the observed maximum
completion — so healthy runs sit NEAR it and a CRON_STALE is routinely a false
alarm (``jobflow-scout`` fired at 2403s against 2400s on a run that finished
fine at 2900s).  Killing at that boundary would destroy healthy work.  The
remediation bound answers a different question — "is this run ever coming
back" — so it defaults to 7200s (2h): above every observed healthy completion
on this box (max 3468s) and above the largest configured ``timeout_seconds``
(6600s).  It would have stopped the jobflow-notifier hang at 2h, not 8.14h.

SAFETY INTERLOCKS — this subscriber terminates work; each of these is load-bearing:

* **Same-execution check.**  A stop is issued only while the *same*
  ``execution_id`` that went stale is still non-terminal, read from the
  executions ledger.  Without it, a slow alert could stop a LATER, healthy run
  of the same job — ``request_stop`` with no session id stops whichever run is
  in flight.
* **Once per execution.**  A stopped run is never asked twice.
* **Terminal events clear state**, so a job that recovers on its own is never
  touched.
* **Never fatal.**  Every path is wrapped: a bug here must not take down the
  gateway or the shared poll loop.
* **Disablable.**  A non-positive bound turns remediation off and leaves
  escalation running.

Config — ``~/.hermes/notifications/cron_stale_thresholds.json``, loaded once at
gateway startup like the thresholds beside it::

    "remediate_after_seconds": 7200,            # default; <= 0 disables
    "per_job_remediate": {"jobflow-scout": 9000}

Roster id: ``cron-stale-responder`` (events/subscriber_roster.json).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from events.bus import EventBus
from events.schema import Event, EventType, Priority
from events.subscribers.base import BaseSubscriber

logger = logging.getLogger(__name__)


class CronStaleResponder(BaseSubscriber):
    subscriber_id = "cron-stale-responder"

    #: Default second bound, in seconds.  See the module docstring for why this
    #: is far above the stale threshold rather than a small multiple of it.
    REMEDIATE_AFTER_SECONDS = 7200

    def __init__(
        self,
        bus: EventBus,
        remediate_after_seconds: Optional[int] = None,
        per_job_remediate: Optional[Dict[str, int]] = None,
    ):
        super().__init__(bus)
        # job_id -> tracking record for the run that went stale.  Bounded by
        # the number of concurrently-stale runs; entries drop on the terminal
        # event, once a stop is issued, and when the execution is gone.
        self._stale_runs: Dict[str, Dict[str, Any]] = {}
        self._remediate_after = (
            remediate_after_seconds
            if remediate_after_seconds is not None
            else self.REMEDIATE_AFTER_SECONDS
        )
        self._per_job_remediate = dict(per_job_remediate or {})
        # Host-suspend awareness (2026-09-17): a poll gap far above the poll
        # cadence is time the host slept, and a run cannot wedge while the
        # host is asleep. The monitor already discounts suspends BEFORE the
        # alert (its age_seconds is active time); this covers a suspend that
        # lands AFTER the alert, which is exactly the 2026-09-17 shape --
        # jobflow-approved-release was tracked at 0s, the host slept 7h19m,
        # and it was stopped 15s after resume as "still running 26329s".
        self._last_poll_at: Optional[datetime] = None

    # ----------------------------------------------------------------- config

    def _remediate_after_for(self, job_name: str) -> int:
        if job_name and job_name in self._per_job_remediate:
            return self._per_job_remediate[job_name]
        return self._remediate_after

    # ----------------------------------------------------------------- events

    def handle(self, event: Event) -> None:
        try:
            if event.event_type is EventType.CRON_STALE:
                self._on_stale(event)
            elif event.event_type in (EventType.CRON_COMPLETED, EventType.CRON_FAILED):
                self._on_terminal(event)
        except Exception:
            # A responder that breaks the shared poll loop is worse than one
            # that misses a run.
            logger.exception(
                "CronStaleResponder: handling %s failed",
                getattr(event, "event_type", "?"))

    def _on_stale(self, event: Event) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        job_id = payload.get("job_id")
        if not job_id:
            return
        job_name = payload.get("job_name") or str(job_id)
        record = {
            "job_id": str(job_id),
            "job_name": job_name,
            "execution_id": payload.get("execution_id"),
            # Age is measured from CRON_STARTED (isolation acquire), which is
            # this run's duration origin — carry it forward rather than
            # re-deriving it from a different clock.
            "age_at_alert": float(payload.get("age_seconds") or 0.0),
            "alert_seen_at": datetime.now(timezone.utc),
            "stop_requested": False,
            # Seconds of host suspend observed since the alert (discounted).
            "suspend_credit": 0.0,
        }
        self._stale_runs[str(job_id)] = record
        logger.warning(
            "CronStaleResponder: tracking stale run job=%s execution=%s age=%.0fs; "
            "will request a stop if it is still running at %ss",
            job_name, record["execution_id"], record["age_at_alert"],
            self._remediate_after_for(job_name))

    def _on_terminal(self, event: Event) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        job_id = payload.get("job_id")
        if job_id is not None:
            # Came back on its own, or the stop landed. Either way, done.
            self._stale_runs.pop(str(job_id), None)

    # ------------------------------------------------------------------- poll

    def poll(self) -> int:
        count = super().poll()
        try:
            self._credit_suspend_gap(datetime.now(timezone.utc))
            self._check_remediate()
        except Exception:
            logger.exception("CronStaleResponder: remediation pass failed")
        return count

    def _credit_suspend_gap(self, now: datetime) -> None:
        """Charge a poll gap above the suspend threshold to every tracked run."""
        from events.subscribers.cron_stale_monitor import _suspended_seconds

        last = self._last_poll_at
        self._last_poll_at = now
        if last is None or not self._stale_runs:
            return
        credit = _suspended_seconds((now - last).total_seconds(), float(self.poll_interval_seconds))
        if credit <= 0:
            return
        for record in self._stale_runs.values():
            record["suspend_credit"] = record.get("suspend_credit", 0.0) + credit
        logger.info(
            "CronStaleResponder: poll gap read as a host suspend; discounting %.0fs "
            "from %d tracked run(s)", credit, len(self._stale_runs),
        )

    def _run_age_seconds(self, record: Dict[str, Any], now: datetime) -> float:
        raw = record["age_at_alert"] + (now - record["alert_seen_at"]).total_seconds()
        return max(0.0, raw - record.get("suspend_credit", 0.0))

    def _execution_still_running(self, execution_id: Optional[str]) -> bool:
        """True only if this exact execution is still non-terminal.

        The interlock that stops a slow alert from killing a LATER run of the
        same job.  An unknown or unreadable execution id returns False: refuse
        to act rather than guess which run would be stopped.
        """
        if not execution_id:
            return False
        try:
            from cron.executions import get_execution

            row = get_execution(str(execution_id))
        except Exception:
            logger.exception(
                "CronStaleResponder: could not read execution %s; not stopping",
                execution_id)
            return False
        if not row:
            return False
        return str(row.get("status")) in ("claimed", "running")

    def _check_remediate(self) -> None:
        now = datetime.now(timezone.utc)
        for job_id, record in list(self._stale_runs.items()):
            if record.get("stop_requested"):
                continue
            bound = self._remediate_after_for(record["job_name"])
            if bound <= 0:
                continue
            if self._run_age_seconds(record, now) < bound:
                continue
            if not self._execution_still_running(record.get("execution_id")):
                # Finished, or we cannot prove which run this is.
                self._stale_runs.pop(job_id, None)
                continue
            self._request_stop(record, self._run_age_seconds(record, now), bound)

    def _request_stop(self, record: Dict[str, Any], age: float, bound: int) -> None:
        job_name = record["job_name"]
        reason = (
            f"cron-stale-responder: still running {int(age)}s with no terminal "
            f"event (remediation bound {bound}s)")
        try:
            from cron.inflight import request_stop

            request_stop(record["job_id"], by=self.subscriber_id, reason=reason)
        except Exception:
            logger.exception(
                "CronStaleResponder: request_stop failed for %s; leaving it to the operator",
                job_name)
            return

        record["stop_requested"] = True
        logger.warning(
            "CronStaleResponder: requested stop of wedged cron run %s (%s)", job_name, reason)
        try:
            self.bus.emit(
                event_type=EventType.AGENT_ERROR,
                source=self.subscriber_id,
                payload={
                    "error": (
                        f"Stopped wedged cron run '{job_name}' after {int(age)}s with "
                        f"no terminal event (bound {bound}s)."),
                    "job_id": record["job_id"],
                    "job_name": job_name,
                    "execution_id": record.get("execution_id"),
                    "age_seconds": int(age),
                    "remediate_after_seconds": bound,
                    "action": "stop_requested",
                },
                priority=Priority.HIGH,
            )
        except Exception:
            logger.exception(
                "CronStaleResponder: stopped %s but could not report it", job_name)
