"""Per-execution stage evidence; never reads worker locals or waits on its locks."""
from __future__ import annotations

import contextvars
import logging
import sys
import time
from pathlib import Path
from traceback import format_exception

from agent.redact import redact_sensitive_text

logger = logging.getLogger(__name__)
_current = contextvars.ContextVar("cron_stage_evidence", default=None)


def format_run_error(exc: BaseException) -> str:
    """Retain chained causes without capturing locals or exposing URL credentials."""
    traceback_text = redact_sensitive_text(
        "".join(format_exception(exc)), force=True, redact_url_credentials=True,
    )
    return f"## Error\n\n```\n{traceback_text}\n```\n"


def set_stage(stage: str) -> None:
    evidence = _current.get()
    if evidence is None:
        return
    now = time.monotonic()
    previous, started = evidence["stage"]
    evidence["stage"] = (stage, now)
    logger.info("Cron execution %s job %s stage=%s elapsed=%.3fs next=%s",
                evidence["execution_id"], evidence["job_id"], previous, now - started, stage)


def run_with_evidence(evidence, run, job, kwargs):
    token = _current.set(evidence)
    try:
        return run(job, **kwargs)
    finally:
        set_stage("worker_exited")
        _current.reset(token)


def snapshot(evidence, worker) -> dict:
    """Capture only this owned thread's code locations, without source/locals/linecache I/O."""
    stage, started = evidence["stage"]
    frames = []
    frame = None
    try:
        frame = sys._current_frames().get(worker.ident) if worker.ident is not None else None
        while frame is not None and len(frames) < 16:
            frames.append({"file": Path(frame.f_code.co_filename).name,
                           "function": frame.f_code.co_name, "line": frame.f_lineno})
            frame = frame.f_back
    except Exception:
        # Audit hooks/platform restrictions must not defeat deadline bookkeeping.
        logger.debug("Cron worker stack unavailable", exc_info=True)
    finally:
        del frame
    return {"stage": stage, "stage_elapsed_seconds": round(time.monotonic() - started, 3),
            "worker_stack": frames}


def emit_overdue(emitter, job, duration, evidence) -> None:
    """A soft deadline observation is not a terminal failure or a failure streak."""
    from events.schema import EventType, Priority

    if emitter is None:
        return
    try:
        emitter.bus.emit(
            event_type=EventType.CRON_STALE, source=job.get("name") or job["id"],
            priority=Priority.HIGH,
            payload={"job_id": job["id"], "job_name": job.get("name") or job["id"],
                     "execution_id": job.get("execution_id"), "state": "overdue_running",
                     "reason": "soft_deadline", "age_seconds": round(duration, 1),
                     "threshold_seconds": round(duration, 1), **evidence})
    except Exception:
        logger.warning("Could not emit cron overdue observation for %s", job["id"], exc_info=True)


def emit_isolation_wait(emitter, job, waited_seconds, budget_seconds, evidence) -> None:
    """Still queued behind job isolation: not started, not failed, not a streak.

    Distinct from :func:`emit_overdue` (``reason=soft_deadline``, HIGH): the
    job has not begun executing, so nothing about it is overdue except the
    pool convoy in front of it. NORMAL priority keeps it out of the paging
    path while the ``execution_id`` still lets the notifier coalesce it with
    a later observation for the same run.
    """
    from events.schema import EventType, Priority

    if emitter is None:
        return
    try:
        emitter.bus.emit(
            event_type=EventType.CRON_STALE, source=job.get("name") or job["id"],
            priority=Priority.NORMAL,
            payload={"job_id": job["id"], "job_name": job.get("name") or job["id"],
                     "execution_id": job.get("execution_id"), "state": "overdue_running",
                     "reason": "isolation_wait", "age_seconds": round(waited_seconds, 1),
                     "threshold_seconds": round(budget_seconds, 1), **evidence})
    except Exception:
        logger.warning("Could not emit cron isolation-wait observation for %s", job["id"],
                       exc_info=True)
