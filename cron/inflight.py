"""In-flight cron accessors for the gateway shutdown path.

``gateway/run.py`` has imported :func:`current_inflight_correlation_ids` from
this module since 2026-04-30 (M1, the GATEWAY_STARTED / GATEWAY_STOPPED
lifecycle events), inside a ``try/except`` that falls back to ``[]``. The module
never existed, so every GATEWAY_STOPPED event ever emitted carried an empty
``inflight_cron_correlation_ids`` list — a restart could not say which crons it
had killed, and a cron cut short by a shutdown was indistinguishable from one
that wedged (it surfaced ~20 minutes later as a generic CRON_STALE, if at all).

This module supplies the missing answer. It deliberately does NOT own a
registry of its own: ``cron/scheduler.py`` already maintains ``_in_flight``
(the Guard #3 same-job concurrency registry, added 2026-04-30), whose
``_InFlightRecord`` carries exactly the field needed. That comment in
``scheduler.py`` says the registry shape was chosen to "also support Guard #1,
cron_aborted on shutdown, which needs to enumerate currently-running jobs" —
this is that consumer.

**Why we read ``sys.modules`` instead of importing the scheduler.**
``cron.scheduler`` is a large module and this runs on the shutdown path, where
a first-time import would be both slow and pointless: if the scheduler was
never imported in this process, no cron can be in flight, so the correct answer
is ``[]``. Reading the already-loaded module keeps the query free and side
effect free.

The correlation id is the ``cron_started`` event_id, matching the existing
``prior_cron_started_event_id`` convention used by ``cron_skipped_duplicate``.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEDULER_MODULE = "cron.scheduler"

# ---------------------------------------------------------------------------
# Operator stop requests (added 2026-09-07)
#
# ``hermes cron pause`` sets enabled=False and stops SCHEDULING. It has never
# touched a run already in flight: on 2026-09-06 job b74186b2eaa5 was paused
# at 18:14:34 while its 18:00 run was 14 minutes in, and that run kept calling
# tools for 44 more minutes and published 184 proposals (116 of them
# fabricated) at 18:58 -- an hour after the operator believed the lane was
# stopped. Nothing told the pausing session a run was in flight, and nothing
# could stop it short of killing the whole gateway.
#
# The scheduler's in-flight registry (``cron.scheduler._in_flight``) and its
# ``agent.interrupt()`` kill path both live INSIDE the gateway process, so a
# CLI cannot reach them directly. This file-based signal bridges that gap:
# the CLI writes ``<CRON_DIR>/stop-requests/<job_id>.json`` naming the session
# it wants stopped, and the run's watchdog poll loop (which already wakes every
# few seconds to service the inactivity and wall-clock limits) consumes it and
# interrupts the agent exactly the way a timeout would.
#
# Targeting is by SESSION id, not just job id: a request names the
# ``cron_<job>_<stamp>`` session row the operator saw, so a request left over
# from an earlier run can never kill the next one -- the scheduler also clears
# any stale file when a new run opens its session. A request with no session
# id stops whichever run of that job is in flight.
# ---------------------------------------------------------------------------

STOP_REQUESTS_DIRNAME = "stop-requests"


class CronRunStoppedByOperator(RuntimeError):
    """Raised inside the run when an operator stop request is honoured.

    A plain ``RuntimeError`` subclass so the scheduler's generic failure
    path records it as ``CronRunStoppedByOperator: ...`` in ``last_status``,
    the run output document, and the cron_failed event -- legible as a
    deliberate stop, not as a timeout or a crash.
    """


def _stop_requests_dir() -> Path:
    """``<CRON_DIR>/stop-requests``, resolved at call time.

    Reads ``cron.jobs.CRON_DIR`` through the module attribute (not a bound
    import) so a test that monkeypatches the cron dir redirects this too, and
    so the CLI and the gateway -- which resolve the same ``jobs.json`` --
    also resolve the same request directory.
    """
    from cron import jobs as _jobs

    return Path(_jobs.CRON_DIR) / STOP_REQUESTS_DIRNAME


def stop_request_path(job_id: str) -> Path:
    return _stop_requests_dir() / f"{job_id}.json"


def request_stop(
    job_id: str,
    *,
    session_id: Optional[str] = None,
    by: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask the scheduler to interrupt the in-flight run of ``job_id``.

    Writes the request atomically and returns the payload written. The
    scheduler honours it on its next watchdog poll (a few seconds). This
    does NOT verify a run is in flight -- callers decide that from the
    sessions table -- and it never blocks on the gateway.
    """
    if not job_id:
        raise ValueError("job_id is required")
    payload: Dict[str, Any] = {
        "job_id": str(job_id),
        "session_id": str(session_id) if session_id else None,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "by": by,
        "reason": reason,
    }
    path = stop_request_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return payload


def read_stop_request(job_id: str) -> Optional[Dict[str, Any]]:
    """Return the pending request for ``job_id``, or None. Never raises."""
    path = stop_request_path(job_id)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("unreadable stop request %s", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def clear_stop_request(job_id: str) -> bool:
    """Remove any pending request for ``job_id``. True if one was removed."""
    path = stop_request_path(job_id)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logger.debug("could not clear stop request %s", path, exc_info=True)
        return False


def consume_stop_request(job_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    """Take the pending request if it targets THIS run, else leave it.

    Called from the scheduler's watchdog loop. Returns the request (and
    deletes the file) when its ``session_id`` matches ``session_id`` or is
    empty; returns None -- leaving the file in place -- when it names a
    different session, so a request aimed at an earlier run cannot stop a
    later one. Never raises: a failure to read must not abort the run.
    """
    request = read_stop_request(job_id)
    if request is None:
        return None
    target = request.get("session_id")
    if target and str(target) != str(session_id):
        return None
    clear_stop_request(job_id)
    return request


def current_inflight_correlation_ids() -> List[str]:
    """``cron_started`` event ids for every cron currently in flight.

    Returns an empty list — never raises — when the scheduler was never
    loaded, when nothing is running, or when the registry cannot be read.
    Callers are on the gateway shutdown path: a failure to answer must not
    abort the GATEWAY_STOPPED emission.

    Records whose ``cron_started_event_id`` is still ``None`` are skipped.
    A job registers its in-flight slot *before* ``on_job_started`` returns, so
    there is a real window in which no correlation id exists yet; emitting a
    ``None`` into the payload would be a null entry, not a correlation.
    """
    module = sys.modules.get(_SCHEDULER_MODULE)
    if module is None:
        return []
    try:
        lock = module._in_flight_lock
        registry = module._in_flight
        with lock:
            # Copy under the lock; callers iterate outside it.
            records = list(registry.values())
    except Exception:
        logger.debug("current_inflight_correlation_ids failed", exc_info=True)
        return []

    ids: List[str] = []
    for record in records:
        event_id = getattr(record, "cron_started_event_id", None)
        if event_id:
            ids.append(event_id)
    return ids
