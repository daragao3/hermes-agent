"""CronScheduler provider interface (Axis B — the trigger). EXPERIMENTAL: shape MAY change until a
second provider validates it; growth MUST be additive (optional method with a default), never a
changed start() signature or new abstractmethod. Providers decide only *when* a job fires —
execution + delivery stay in cron.scheduler.run_job / _deliver_result; never reimplement them.
"""
from __future__ import annotations

import re

import contextlib
import inspect
import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

#: Shape of the state.db session id ``cron/scheduler.py::run_job`` creates:
#: ``cron_<job_id>_<YYYYmmdd_HHMMSS>``. Only ids of this shape are ever
#: considered by the orphan-session recovery below; anything else is left alone.
_CRON_SESSION_ID_RE = re.compile(r"^cron_(?P<job_id>.+)_\d{8}_\d{6}$")

#: ``end_reason`` stamped on a cron session whose owning process died before
#: ``run_job``'s own ``end_session(..., "cron_complete")`` could run. Distinct
#: from ``cron_complete`` (the run finished) and from the 24h
#: ``reaped_stale`` reaper (``scripts/hermes-postgres-bridge.py``), so a
#: consumer can tell "interrupted, closed by the successor" from either.
CRON_SESSION_INTERRUPTED_REASON = "cron_interrupted"

from jobflow_dispatch.quarantine_control import (
    default_control_store,
    retain_dispatch_admission,
)

logger = logging.getLogger(__name__)

# Cap for exponential tick backoff during fd exhaustion (interval doubled per failure).
_EMFILE_BACKOFF_MAX_SECONDS = 15 * 60
DEFAULT_MISFIRE_GRACE_MINUTES = 10


# Cap for the exponential tick backoff applied while consecutive ticks fail with fd exhaustion
# (EMFILE/ENFILE, #87644). Base is the tick interval (60s by default); each consecutive EMFILE failure
# doubles the wait, capped here so a still-alive-but-exhausted gateway never sleeps longer than this between
# recovery attempts.
def _backoff_wait_seconds(interval: float, consecutive_failures: int) -> float:
    """Plain ``interval`` while healthy; doubles per fd-exhaustion failure, capped.

    Exponential tick backoff shared by both ticker loops (#87644).
    """
    if consecutive_failures <= 0:
        return interval
    return min(interval * (2 **(consecutive_failures - 1)), _EMFILE_BACKOFF_MAX_SECONDS)


def _note_tick_failure(exc: BaseException, consecutive_failures: int) -> int:
    """On fd exhaustion: reclaim fds and bump the backoff counter; any other failure resets it —
    backoff is reserved for the EMFILE storm.

    Shared by both ticker loops (#87644): on fd exhaustion, attempt reclamation (gc.collect + raise the soft
    nofile limit) so the NEXT tick can succeed, and bump the counter so ``_backoff_wait_seconds`` backs off
    exponentially while the process has no chance of making progress.
    """
    from cron.scheduler import _is_fd_exhaustion, _reclaim_fds_best_effort

    if _is_fd_exhaustion(exc):
        _reclaim_fds_best_effort()
        return consecutive_failures + 1
    return 0


def _profile_entry(entry) -> tuple:
    """Normalize a ``profile_homes`` entry (``(name, home)`` tuple or bare home) to ``(name,
    home)``."""
    return entry if isinstance(entry, tuple) else (None, entry)


def _existing_profile_homes(profile_homes: list) -> list:
    """Drop homes no longer on disk: ticking/heartbeating a deleted home would recreate its
    ``cron/`` workspace and silently resurrect the profile.

    Ticking or heartbeating a deleted home recreates its ``cron/`` workspace (``record_ticker_heartbeat`` ->
    ``ensure_dirs`` -> ``mkdir(parents=True)``) on every 60s cycle, so the "deleted" profile silently comes
    back on disk and in ``hermes profile list`` (#47368). Filtering on directory existence leaves a deleted
    profile's home untouched, which is the correct invariant: a home that does not exist cannot hold jobs to
    fire.
    """
    return [entry for entry in profile_homes if Path(_profile_entry(entry)[1]).is_dir()]


@contextlib.contextmanager
def _profile_cron_scope(home):
    """Scope the calling thread to one profile's home + cron store for the block."""
    from cron.jobs import use_cron_store
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    # Record per-profile heartbeat after each tick cycle. Distinguish a COMPLETED cycle (``_tick_error``
    # unset) — where each profile's beat reflects its own outcome, so a yielding profile does not darken
    # healthy siblings — from an aborted one (exception), where no profile completed and all beats are
    # unsuccessful (#32612).
    home_token = set_hermes_home_override(str(home))
    try:
        with use_cron_store(home):
            yield
    finally:
        reset_hermes_home_override(home_token)


class CronScheduler(ABC):
    """Decides WHEN a due cron job fires. Only ``name`` + ``start`` are required; keep every other
    hook NON-abstract with a safe default (``test_abc_growth_stays_additive``)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'builtin', 'chronos'."""

    def is_available(self) -> bool:
        """Whether this provider can run here. MUST NOT make network calls; False → built-in."""
        return True

    @abstractmethod
    def start(
        self, stop_event: threading.Event, *, adapters: Any = None, loop: Any = None,
        interval: int = 60,
    ) -> None:
        """Begin firing due jobs. Built-in BLOCKS until stop_event is set (run in a daemon thread);
        an external provider may return immediately but must still honor stop_event."""

    def stop(self) -> None:
        """Optional eager teardown; stop_event is the primary signal."""
        return None

    # Optional hooks for external providers — default-safe; keep NON-abstract.

    def on_jobs_changed(self) -> None:
        """After a successful store mutation; external providers reconcile. Built-in: no-op."""
        return None

    def register_job(self, job: dict[str, Any]) -> None:
        """Register the external trigger for a newly persisted job (must complete before callers
        report it as scheduled). Built-in: no-op."""
        return None

    def recover_interrupted(self) -> int:
        """Run profile-local attempt recovery for every provider lifecycle.

        Also carries each recovered verdict onto the job record. jobs.json's
        ``last_run_at`` is written only by ``mark_job_run()`` at the end of a
        run, so an owner that dies mid-run leaves the job reporting its
        previous clean completion — with ``next_run_at`` already advanced, that
        reads as "never ran" indefinitely for anything less frequent than the
        restart cadence. The ledger knows better; propagate it.
        """
        import logging

        from cron.executions import recover_interrupted_execution_records
        from cron.jobs import mark_job_interrupted

        logger = logging.getLogger("cron.scheduler_provider")
        records = recover_interrupted_execution_records()
        for record in records:
            # started_at is when the side effects began; a claimed-but-
            # never-started attempt only has claimed_at.
            ran_at = record.get("started_at") or record["claimed_at"]
            try:
                mark_job_interrupted(
                    record["job_id"],
                    ran_at=ran_at,
                    error=record.get("error"),
                )
            except Exception as e:
                # One unwritable job record must not abandon the rest of the
                # pass — the ledger is already correct either way.
                logger.warning(
                    "Could not stamp interrupted run onto job %s: %s",
                    record.get("job_id"), e,
                )
            # Independent of the stamp above: an unwritable jobs.json must not
            # also cost the notification layer its only record of the kill.
            self._emit_interrupted_cron_stale(record, ran_at=ran_at)
        # The ledger and jobs.json now say the run is over; state.db must not
        # keep reporting its session as RUNNING for the next 24h (see below).
        self._close_orphaned_cron_sessions()
        return len(records)

    @classmethod
    def _close_orphaned_cron_sessions(cls) -> int:
        """End state.db cron sessions that no process is running any more.

        ``run_job`` ends its session only in its own ``finally``
        (``end_session(..., "cron_complete")``, ``cron/scheduler.py``), so a
        process that dies mid-run -- a force-killed gateway, a ``hermes cron
        run`` whose terminal closed -- leaves the row ``ended_at NULL``.
        Nothing else closed it: the execution ledger got its ``unknown`` verdict
        and jobs.json its stamp at the next scheduler start, but the session
        row read RUNNING until ``hermes-postgres-bridge.py``'s 24h idle reaper
        stamped it ``reaped_stale`` (measured 2026-09-06/07: a 12:00 run whose
        gateway was replaced at 12:10 stayed open until 12:15 the next day).

        WHY "no non-terminal ledger row for the job" IS PROOF OF ORPHANHOOD.
        Every run claims its execution row BEFORE ``run_job`` creates the
        session (``create_execution`` precedes dispatch on both the builtin
        path, ``_submit_with_guard``, and the direct path, ``run_one_job``),
        and the row stays ``claimed``/``running`` until the run's own teardown
        -- which ends the session first. So while any process is inside a run
        of job J, the ledger holds a non-terminal row for J. This runs AFTER
        :func:`recover_interrupted_execution_records` has flipped every
        dead-owner row to ``unknown``; what is still non-terminal is owned by a
        live process, an unprovable one, or this very process, and every such
        job is left alone -- a live run elsewhere (e.g. the desktop ticker or a
        CLI run) keeps its session open. The check is per JOB rather than per
        session, so in the rare case where a job has both an orphan and a live
        run, the orphan waits for the next pass rather than risk the live one.

        Only ids of the ``cron_<job>_<stamp>`` shape are touched, only rows with
        ``source='cron'``, and only through :meth:`SessionDB.end_session`, which
        is first-reason-wins and no-ops on an already-ended row. Never raises:
        this sits on the ticker's startup path, where an exception would cost
        the gateway its scheduler (the 2026-08-11 outage); a failure here only
        costs the rows their prompt close.
        """
        import logging

        logger = logging.getLogger("cron.scheduler_provider")
        try:
            from cron.executions import nonterminal_execution_job_ids
            from hermes_state import SessionDB

            protected = nonterminal_execution_job_ids()
            db = SessionDB()
            closed: list[str] = []
            try:
                for session_id in db.list_open_session_ids("cron"):
                    match = _CRON_SESSION_ID_RE.match(session_id)
                    if match is None or match.group("job_id") in protected:
                        continue
                    db.end_session(session_id, CRON_SESSION_INTERRUPTED_REASON)
                    closed.append(session_id)
            finally:
                try:
                    db.close()
                except Exception:
                    pass
            if closed:
                logger.warning(
                    "Closed %d orphaned cron session(s) whose run no longer "
                    "exists (end_reason=%s): %s",
                    len(closed), CRON_SESSION_INTERRUPTED_REASON,
                    ", ".join(closed[:10]) + (" ..." if len(closed) > 10 else ""),
                )
            return len(closed)
        except Exception:
            logger.warning(
                "Orphaned cron session close failed; rows stay open until the "
                "stale-session reaper", exc_info=True,
            )
            return 0

    @staticmethod
    def _shutdown_attribution_exists(bus: Any, job_id: str, ran_at: str) -> bool:
        """Has the bus-query reconstruction already reported this run?

        ``CronStaleMonitor.startup()`` (main ``517cc56c97``) rebuilds shutdown
        attributions from durable bus rows and emits ``scope='gateway_stopped'``
        for every run a GATEWAY_STOPPED named. It covers the common force-kill,
        because the in-flight snapshot is taken early in ``_stop_impl_body`` —
        before the drain — so the event is usually out before the kill lands.
        This ledger path is for the deaths that leave no GATEWAY_STOPPED at all:
        a crash, an OOM, a power-off, or a kill preceding the emit.

        The window floor is THIS run's start, so an attribution belonging to an
        earlier run of the same job cannot swallow this one's report.

        **``ran_at`` must be converted to UTC first.** The ledger stamps local
        wall-clock with a local offset (``cron/executions.py`` via
        ``hermes_time.now()`` -> ``datetime.now().astimezone()``, ``-04:00``
        here) while every bus row is ``datetime.now(timezone.utc).isoformat()``
        (``+00:00``), and ``query(since=...)`` compares them as STRINGS. Passing
        the raw value widens the window by the offset — four hours on this box.
        """
        from datetime import datetime, timezone

        from events.schema import EventType

        try:
            # A naive stamp (offset lost somewhere upstream) is interpreted as
            # local by astimezone(), which is what it was.
            since = datetime.fromisoformat(ran_at).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            # Cannot bound the window, so cannot prove this is a duplicate.
            # Report it: a duplicate is noisy, a miss loses the only record
            # that this run was killed at all.
            return False

        for event in bus.query(event_type=EventType.CRON_STALE, since=since):
            payload = event.payload
            if (payload.get("scope") == "gateway_stopped"
                    and payload.get("job_id") == job_id):
                return True
        return False

    @classmethod
    def _emit_interrupted_cron_stale(cls, record: dict[str, Any], *, ran_at: str) -> None:
        """Announce one recovered run on the event bus. Never raises.

        CronStaleMonitor attributes a killed cron only when the dying gateway
        both emits GATEWAY_STOPPED and lives long enough for
        ``events/gateway_integration.py:shutdown()`` to flush the reports it
        staged. On Windows neither is guaranteed: ``hermes gateway stop`` hands
        the gateway ``_windows_stop_drain_timeout()`` — clamped to 30s at
        ``hermes_cli/gateway_windows.py:1593`` — and then force-kills the PID,
        while the flush runs in ``start_gateway()``'s teardown tail, well past
        the drain. A cron mid-LLM-call routinely needs more than 30s, so the
        kill lands first and the staged report dies with the process. The
        2026-08-12 census recorded 3 of 6 shutdowns emitting no GATEWAY_STOPPED
        at all, and 2026-08-17 lost three staged runs exactly this way.

        This is the successor's backstop and the only path that survives that
        kill, because it runs in the NEXT process off durable state. It needs no
        deduplication of its own: ``recover_interrupted_execution_records()``
        flips each row under ``WHERE id=? AND status IN ('claimed','running')``
        and returns only rows whose UPDATE changed something, so a run is
        recovered — and therefore announced — exactly once.

        ``age_seconds`` is deliberately absent. Its sibling on the
        ``gateway_stopped`` attribution means "how far into the run did the
        shutdown land", measured against the shutdown event. Nothing here can
        reconstruct that: the only clock available is now-minus-``ran_at``,
        which silently includes however long the box was down. An omitted field
        is honest; a redefined one is not. ``ran_at`` is carried instead.
        """
        import logging

        logger = logging.getLogger("cron.scheduler_provider")
        try:
            from events.gateway_integration import get_bus
            from events.schema import EventType, Priority

            bus = get_bus()
            if bus is None:
                # Recovery also runs from `hermes cron` CLI paths and from
                # Chronos, where no gateway EventBus exists. The ledger and
                # jobs.json are already correct; silence is the right answer.
                return

            job_id = record["job_id"]
            if cls._shutdown_attribution_exists(bus, job_id, ran_at):
                # Already reported by CronStaleMonitor.startup()'s bus-query
                # reconstruction (main 517cc56c97), which the gateway runs
                # BEFORE the cron ticker — runner.start() at gateway/run.py:23733
                # vs cron_thread.start() at :23818. Emitting again would
                # deterministically double-report every force-kill that still
                # managed to emit GATEWAY_STOPPED.
                return

            try:
                from cron.jobs import get_job

                job = get_job(job_id)
            except Exception:
                job = None
            job_name = (job or {}).get("name") or job_id

            bus.emit(
                event_type=EventType.CRON_STALE,
                source="cron-recovery",
                payload={
                    "job_id": job_id,
                    "job_name": job_name,
                    # Distinct from 'gateway_stopped' (a shutdown that reported
                    # its own kills) and from the generic wedge alert. All this
                    # claims is that the owner died without a terminal state —
                    # whether a stop, a crash, or an OOM did it is unknown, and
                    # so is whether the side effects ran.
                    "scope": "owner_exited",
                    "execution_id": record.get("id"),
                    "ran_at": ran_at,
                    "error": record.get("error"),
                },
                # An interrupted run explained by a restart is not a wedge
                # emergency — matches the gateway_stopped attribution, which is
                # deliberately quieter than the HIGH generic alert.
                priority=Priority.NORMAL,
            )
            logger.warning(
                "Cron '%s' (%s) was interrupted at %s and recovered by this "
                "process — reported to the event bus as scope=owner_exited",
                job_name, job_id, ran_at,
            )
        except Exception:
            # This runs on the ticker startup path, where a raised exception
            # costs the gateway its entire scheduler (the 2026-08-11 5h08m
            # outage). Recovery is already durable in the ledger before the
            # emit is attempted, so losing the announcement is the cheap half.
            logger.warning(
                "Could not announce interrupted run for job %s on the event bus",
                record.get("job_id"), exc_info=True,
            )

    @property
    def supports_force_fire(self) -> bool:
        """Whether ``fire_due`` accepts ``force`` (signature-detected for older providers)."""
        return provider_supports_force_fire(self)

    def fire_due(
        self, job_id: str, *, adapters: Any = None, loop: Any = None, force: bool = False,
    ) -> bool:
        """Run one job NOW (inbound fire webhook entry). Store CAS claim (multi-machine
        at-most-once) then shared ``run_one_job``. True if THIS caller claimed and processed the
        attempt (even if the job failed); False if the claim was lost or the job is gone."""
        claimed_job = self.claim_fire(job_id, force=force)
        if claimed_job is None:
            return False
        return self.fire_claimed(claimed_job, adapters=adapters, loop=loop)

    def claim_fire(self, job_id: str, *, force: bool = False) -> dict | None:
        """Durably claim one fire + create its audit attempt. Transports call this synchronously
        before acknowledging, then pass the exact snapshot to ``fire_claimed`` off-thread."""
        from cron.executions import create_execution, finish_execution, set_execution_occurrence
        from cron.jobs import claim_job_for_fire

        with default_control_store().dispatch_section(boundary="external-provider-claim"):
            execution = create_execution(job_id, source=self.name)
            claim_kwargs = {"return_job": True}
            if force:
                claim_kwargs["force"] = True
            try:
                claimed_job = claim_job_for_fire(job_id, **claim_kwargs)
                if isinstance(claimed_job, dict):
                    set_execution_occurrence(execution["id"], claimed_job.get("_scheduled_instant"))
            except BaseException as exc:
                finish_execution(
                    execution["id"], success=False,
                    error=f"Fire claim failed before dispatch: {type(exc).__name__}: {exc}",
                )
                raise
            if not isinstance(claimed_job, dict):
                finish_execution(execution["id"], success=False, error="Fire claim was not acquired")
                return None
            claimed_job["execution_id"] = execution["id"]
            return claimed_job

    def fire_claimed(
        self, claimed_job: dict, *, adapters: Any = None, loop: Any = None,
        cancel_event: Any = None,
    ) -> bool:
        """Run an exact ``claim_fire`` snapshot; ``cancel_event`` lets the transport stop it
        cooperatively (e.g. dashboard lifespan drain)."""
        try:
            admission = retain_dispatch_admission(
                default_control_store(), boundary="external-provider-fire"
            )
        except Exception as exc:
            # A transport may have claimed before quarantine was installed.
            # Settle only this attempt; a successor's job verdict is owner-fenced.
            from cron.executions import finish_execution
            from cron.jobs import mark_job_run

            error = f"Dispatch admission refused before execution: {exc}"
            claim = claimed_job.get("fire_claim")
            owner = str(claim.get("by") or "") if isinstance(claim, dict) else ""
            if owner:
                try:
                    mark_job_run(claimed_job["id"], False, error,
                                 expected_fire_owner=owner)
                except Exception:
                    logger.exception("Could not settle refused provider job %s", claimed_job["id"])
            if claimed_job.get("execution_id"):
                try:
                    finish_execution(claimed_job["execution_id"], success=False, error=error)
                except Exception:
                    logger.exception("Could not settle refused provider execution %s",
                                     claimed_job["execution_id"])
            raise
        try:
            from cron.scheduler import run_one_job

            run_one_job(claimed_job, adapters=adapters, loop=loop,
                        cancel_event=cancel_event, _dispatch_admission=admission)
            return True
        finally:
            admission.release()

    def reconcile(self) -> None:
        """Converge the external registry toward jobs.json (desired state). Built-in: no-op."""
        return None


def provider_supports_force_fire(provider: Any) -> bool:
    """Return whether a provider can safely receive ``fire_due(force=...)`` (signature-detected)."""
    try:
        parameters = inspect.signature(provider.fire_due).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        or (
            p.name == "force"
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        )
        for p in parameters
    )


def provider_supports_split_fire(provider: Any) -> bool:
    """Whether a provider implements the two-phase fire contract. A legacy provider overriding only
    ``fire_due`` must keep being driven through it — routing around the override would drop its
    custom claim/re-arm/telemetry behavior."""
    cls = type(provider)

    def overrides(name: str) -> bool:
        impl = getattr(cls, name, None)
        return impl is not None and impl is not getattr(CronScheduler, name)

    if overrides("claim_fire") or overrides("fire_claimed"):
        return True
    return not overrides("fire_due")


def _misfire_grace_minutes() -> float:
    """``cron.misfire_grace_minutes`` from config; non-positive disables the catch-up sweep."""
    try:
        from hermes_cli.config import cfg_get, load_config

        config = load_config()
        return float(
            cfg_get(config, "cron", "misfire_grace_minutes", default=DEFAULT_MISFIRE_GRACE_MINUTES)
        )
    except Exception:
        return float(DEFAULT_MISFIRE_GRACE_MINUTES)


def fire_overdue_jobs(
    provider: "CronScheduler", *, adapters: Any = None, loop: Any = None, now: Any = None,
) -> int:
    """Misfire backstop (gateway housekeeping loop): fire jobs whose external HTTP fire never
    arrived, else ``next_run_at`` stays parked in the past forever. No-op for the built-in (its tick
    loop self-heals). Routes through the provider's own two-phase path so re-arm logic runs and a
    concurrent late external retry is de-duplicated by the store CAS; waits out
    ``cron.misfire_grace_minutes`` so the external retry gets first right. Returns jobs dispatched.
    """
    from datetime import datetime

    if isinstance(provider, InProcessCronScheduler):
        return 0

    grace_minutes = _misfire_grace_minutes()
    if grace_minutes <= 0:
        return 0

    from cron.jobs import (
        ONESHOT_GRACE_SECONDS, _ensure_aware, _hermes_now, is_job_runnable, load_jobs,
    )

    if now is None:
        now = _hermes_now()

    fired = 0
    for job in load_jobs():
        if not is_job_runnable(job):
            continue
        next_run_at = job.get("next_run_at")
        if not next_run_at:
            continue
        try:
            due_dt = _ensure_aware(datetime.fromisoformat(next_run_at))
        except (ValueError, TypeError):
            continue
        overdue_seconds = (now - due_dt).total_seconds()
        if overdue_seconds < grace_minutes * 60:
            continue
        job_id = str(job.get("id") or "")
        # One-shots past ONESHOT_GRACE_SECONDS "will never fire"; don't resurrect them hours late.
        # One-shot jobs share the module-wide policy: more than ONESHOT_GRACE_SECONDS past their run time
        # means "will never fire" (create/update/resume/recovery and, since #89571, the due-scan all enforce
        # it). The misfire backstop must not resurrect them hours late after downtime — that's #93526.
        schedule = job.get("schedule") or {}
        if str(schedule.get("kind") or "") == "once" and overdue_seconds > ONESHOT_GRACE_SECONDS:
            logger.warning(
                "Misfire catch-up: one-shot job %s (%s) was due %s "
                "(%.0f min overdue) — outside the %ss one-shot grace "
                "window, not firing.",
                job_id,
                job.get("name") or "unnamed",
                next_run_at,
                overdue_seconds / 60,
                ONESHOT_GRACE_SECONDS,
            )
            continue
        logger.warning(
            "Misfire catch-up: job %s (%s) was due %s (%.0f min overdue) and "
            "no external fire arrived — firing locally.",
            job_id,
            job.get("name") or "unnamed",
            next_run_at,
            overdue_seconds / 60,
        )
        try:
            # Claim synchronously (CAS loss = external retry beat us), run off-thread: never block.
            claimed = provider.claim_fire(job_id)
            if claimed is None:
                continue
            threading.Thread(
                target=provider.fire_claimed, args=(claimed,),
                kwargs={"adapters": adapters, "loop": loop}, daemon=True,
                name=f"cron-misfire-{job_id[:12]}",
            ).start()
            fired += 1
        except Exception as exc:
            logger.warning(
                "Misfire catch-up failed for job %s: %s: %s",
                job_id, type(exc).__name__, exc,
            )
    return fired


def resolve_cron_scheduler() -> "CronScheduler":
    """Resolve ``cron.provider``; missing/failing/unavailable providers fall back to the built-in
    with a warning — cron must never be left without a trigger."""
    name = ""
    try:
        from hermes_cli.config import cfg_get, load_config
        name = (cfg_get(load_config(), "cron", "provider", default="") or "").strip()
    except Exception:
        pass

    if not name or name in ("builtin", "in-process", "inprocess"):
        return InProcessCronScheduler()

    try:
        from plugins.cron_providers import load_cron_scheduler
        provider = load_cron_scheduler(name)
        if provider is None:
            logger.warning("cron.provider '%s' not found; using built-in ticker", name)
            return InProcessCronScheduler()
        if not provider.is_available():
            logger.warning("cron.provider '%s' not available; using built-in ticker", name)
            return InProcessCronScheduler()
        logger.info("Using cron scheduler provider: %s", provider.name)
        return provider
    except Exception as e:
        logger.warning("Failed to load cron.provider '%s' (%s); using built-in ticker", name, e)
        return InProcessCronScheduler()


def scheduler_for_profile_mode(
    provider: "CronScheduler", *, multiplex_profiles: bool
) -> "CronScheduler":
    """External providers own one unscoped remote registry and cannot reconcile several profile
    stores: fail closed to the built-in multiplex ticker until the API carries profile identity."""
    if not multiplex_profiles or isinstance(provider, InProcessCronScheduler):
        return provider
    logger.warning(
        "cron.provider '%s' does not support multiplex_profiles; using built-in ticker",
        provider.name,
    )
    return InProcessCronScheduler()


class InProcessCronScheduler(CronScheduler):
    """Default in-process 60s ticker; ``start()`` blocks until ``stop_event``. ``can_dispatch`` is
    an optional drain gate; skipped ticks leave due jobs intact for the next allowed tick."""

    @property
    def name(self) -> str:
        return "builtin"

    def start(
        self, stop_event, *, adapters=None, loop=None, interval=60, can_dispatch=None,
        profile_homes=None, profile_adapters=None, default_profile=None, profile_gate=None,
    ):
        from cron.scheduler import CronTickYielded
        from cron.scheduler import tick as cron_tick
        from cron.jobs import (
            get_ticker_authority_counts,
            record_ticker_heartbeat,
            record_ticker_state,
        )
        from cron.jobs import clear_ticker_error, record_ticker_error

        logger.info("In-process cron scheduler started (interval=%ds)", interval)

        # Multiplex: tick EACH profile's store every cycle, heartbeats/recovery scoped per profile.
        # ── Multiplex profiles ──────────────────────────────────────────── When profile_homes is set
        # (multiplex_profiles on), tick EACH profile's cron store on every tick cycle so secondary-profile
        # jobs actually fire instead of languishing in a store no ticker owns (#69377). Without this, only
        # the process-global HERMES_HOME (the default profile) is ticked. Heartbeats and recovery are also
        # scoped per profile so `hermes cron status` reflects liveness for every profile independently.
        if profile_homes:
            self._start_multiplex(
                stop_event, profile_homes=profile_homes, adapters=adapters, loop=loop,
                interval=interval, can_dispatch=can_dispatch, profile_adapters=profile_adapters,
                default_profile=default_profile, profile_gate=profile_gate,
            )
            return

        # Startup-phase recovery must NEVER be able to kill this thread. It runs
        # BEFORE the tick loop, so the loop's own `except BaseException` guard
        # does not cover it — on 2026-08-11 a transiently half-applied checkout
        # made this raise ImportError, the daemon thread died before its first
        # tick, and the gateway ran for 5h08m with NO scheduler while logging a
        # clean "In-process cron scheduler started" line one statement earlier.
        # Zero of 69 jobs fired. A failed recovery pass only costs interrupted
        # runs their `unknown` stamp; losing the ticker stops cron entirely, so
        # degrade to the former and always enter the loop.
        try:
            recovered = self.recover_interrupted()
        except BaseException as e:
            logger.error(
                "Cron startup recovery failed — continuing WITHOUT it so the "
                "ticker still runs (interrupted runs keep their stale status): %s",
                e, exc_info=True,
            )
            recovered = 0
        if recovered:
            logger.warning(
                "Marked %d interrupted cron execution(s) unknown after restart", recovered
            )
        # Heartbeat before the first sleep so `hermes cron status` sees a live ticker immediately.
        record_ticker_heartbeat()
        ticker_started_at = time.time()
        last_success_at = None
        record_ticker_state(
            "idle",
            ticker_started_at_epoch=ticker_started_at,
            last_success_at_epoch=last_success_at,
            **get_ticker_authority_counts(),
        )
        resume_gap = 0.0

        # EMFILE backoff: don't hammer the store while fds are exhausted; a clean tick resets it.
        consecutive_failures = 0
        while not stop_event.is_set():
            # Publish the preceding wait's oversized gap BEFORE cron_tick enters
            # catch-up. Windows monotonic time advances through Modern Standby,
            # while some platforms' monotonic clocks do not, so use the larger
            # wall/monotonic wait and subtract the one expected interval. Timing
            # only stop_event.wait excludes a slow cron_tick from suspend time.
            counts = get_ticker_authority_counts()
            record_ticker_state(
                "dispatching",
                resume_gap_seconds=resume_gap,
                ticker_started_at_epoch=ticker_started_at,
                last_success_at_epoch=last_success_at,
                **counts,
            )
            ok = False
            try:
                if can_dispatch is not None and not can_dispatch():
                    logger.debug("Cron dispatch paused while gateway drains existing work")
                else:
                    cron_tick(
                        verbose=False, adapters=adapters, loop=loop, sync=False,
                        can_dispatch=can_dispatch,
                    )
                ok = True
            except BaseException as e:
                # BaseException, not Exception: a SystemExit must not silently kill the ticker;
                # KeyboardInterrupt is caught on purpose — shutdown is driven by stop_event.
                # Catch BaseException (not just Exception) so a SystemExit from a misbehaving provider SDK /
                # agent retry path does not kill the ticker thread silently (#32612). KeyboardInterrupt is
                # intentionally caught here too — gateway shutdown is driven by stop_event (set by the main
                # thread's signal handler), not by an exception in this daemon thread, so swallowing it and
                # re-checking stop_event keeps shutdown clean.
                if isinstance(e, CronTickYielded):
                    # Expected while a fresh gateway owns the lock; still recorded for status.
                    logger.info("Cron tick yielded: %s", e)
                else:
                    logger.error("Cron tick error: %s", e, exc_info=True)
                # Persist the reason so `hermes cron status` (separate process) shows WHY.
                record_ticker_error(f"{type(e).__name__}: {e}")
                consecutive_failures = _note_tick_failure(e, consecutive_failures)
            # Liveness every iteration; success marker only on a clean tick.
            # EMFILE: reclaim fds + back off exponentially so the exhausted process stops hammering the
            # store while it has no chance of making progress (#87644).
            # Record liveness every iteration; bump the success marker only on a clean tick, so status can
            # tell "alive but failing every tick" from "actually firing jobs" (#32612, #32895).
            record_ticker_heartbeat(success=ok)
            if ok:
                clear_ticker_error()
                consecutive_failures = 0
                last_success_at = time.time()
            record_ticker_state(
                "completed" if ok else "failed",
                resume_gap_seconds=resume_gap,
                ticker_started_at_epoch=ticker_started_at,
                last_success_at_epoch=last_success_at,
                **get_ticker_authority_counts(),
            )
            wait_seconds = _backoff_wait_seconds(interval, consecutive_failures)
            wait_wall = time.time()
            wait_monotonic = time.monotonic()
            stop_event.wait(wait_seconds)
            wall_wait = max(0.0, time.time() - wait_wall)
            monotonic_wait = max(0.0, time.monotonic() - wait_monotonic)
            resume_gap = max(0.0, max(wall_wait, monotonic_wait) - wait_seconds)

    def _start_multiplex(
        self, stop_event, *, profile_homes, adapters=None, loop=None, interval=60,
        can_dispatch=None, profile_adapters=None, default_profile=None, profile_gate=None,
    ):
        """Tick every profile's store, each scoped via ``_profile_cron_scope``. ``profile_gate(name,
        home)``, when given, is consulted every cycle; a rejected profile is neither ticked nor
        heartbeated."""
        from cron.scheduler import tick as cron_tick
        from cron.scheduler import CronTickYielded, _is_fd_exhaustion
        from cron.scheduler_preflight import (
            SharedRouteAdapters, _primary_profile_routes_for_current_home,
        )
        from cron.jobs import (clear_ticker_error, record_ticker_error, record_ticker_heartbeat,
                               record_ticker_state, get_ticker_authority_counts)

        logger.info(
            "Multiplex cron scheduler started for %d profile(s): %s",
            len(profile_homes),
            [p[0] if isinstance(p, tuple) else p for p in profile_homes],
        )

        def tick_adapters_for(profile_name):
            # Deliver via the profile's OWN adapters; NEVER fall back to the default profile's
            # (wrong bot). A credentialless satellite may ride the PRIMARY adapter only for targets
            # an exact enabled route maps here; else fail closed (delivery skipped this tick).
            if profile_name is None or profile_name == default_profile:
                return adapters
            tick_adapters = (profile_adapters or {}).get(profile_name) or {}
            if not tick_adapters and adapters:
                return SharedRouteAdapters(adapters, _primary_profile_routes_for_current_home())
            return tick_adapters

        ticker_started_at = time.time()
        last_success_at = {}
        resume_gap = 0.0

        # Gated desktop profiles must remain untouched until ownership is admitted.
        # Recovery runs once on first admission, before dispatch, not on every tick.
        initialized_homes = set()

        def initialize_profile(home):
            key = str(home)
            if key in initialized_homes:
                return
            initialized_homes.add(key)
            try:
                with _profile_cron_scope(home):
                    recovered = self.recover_interrupted()
                    if recovered:
                        logger.warning(
                            "Marked %d interrupted cron execution(s) for profile at %s",
                            recovered, home,
                        )
                    record_ticker_heartbeat()
                    record_ticker_state("idle", ticker_started_at_epoch=ticker_started_at,
                                        **get_ticker_authority_counts())
            except BaseException as e:
                logger.error(
                    "Cron startup recovery error for profile at %s: %s", home, e, exc_info=True
                )

        # Preserve eager startup for gateway schedulers without a desktop gate.
        # Never recreate a profile deleted since the original snapshot (#47368).
        if profile_gate is None:
            for entry in _existing_profile_homes(profile_homes):
                _, home = _profile_entry(entry)
                initialize_profile(home)

        consecutive_failures = 0
        while not stop_event.is_set():
            ok = False
            _tick_error = None
            _profile_errors: dict[str, str] = {}
            # Worst failure this cycle (fd exhaustion wins); backoff applied once per cycle.
            # See #87644.
            _cycle_exc: BaseException | None = None
            cycle_homes = [_profile_entry(e) for e in _existing_profile_homes(profile_homes)]
            if profile_gate is not None:
                cycle_homes = [
                    (name, home) for name, home in cycle_homes if profile_gate(name, home)
                ]
                for _, home in cycle_homes:
                    initialize_profile(home)
            try:
                if can_dispatch is not None and not can_dispatch():
                    logger.debug("Cron dispatch paused while gateway drains existing work")
                else:
                    for _pname, home in cycle_homes:
                        try:
                            with _profile_cron_scope(home):
                                record_ticker_state(
                                    "dispatching", resume_gap_seconds=resume_gap,
                                    ticker_started_at_epoch=ticker_started_at,
                                    last_success_at_epoch=last_success_at.get(str(home)),
                                    **get_ticker_authority_counts(),
                                )
                                cron_tick(
                                    verbose=False, adapters=tick_adapters_for(_pname), loop=loop,
                                    sync=False, can_dispatch=can_dispatch,
                                )
                        except CronTickYielded as e:
                            # Yield for THIS profile only; one fresh gateway must not stop others.
                            logger.info("Cron tick yielded for profile at %s: %s", home, e)
                            _profile_errors[str(home)] = f"{type(e).__name__}: {e}"
                        except BaseException as e:
                            # THIS profile only; BaseException as in the single-profile loop.
                            logger.error(
                                "Cron tick error for profile at %s: %s", home, e, exc_info=True
                            )
                            _profile_errors[str(home)] = f"{type(e).__name__}: {e}"
                            if _cycle_exc is None or _is_fd_exhaustion(e):
                                _cycle_exc = e
                    ok = not _profile_errors
                    if _cycle_exc is not None:
                        consecutive_failures = _note_tick_failure(_cycle_exc, consecutive_failures)
            except BaseException as e:
                logger.error("Cron tick error: %s", e, exc_info=True)
                _tick_error = f"{type(e).__name__}: {e}"
                # EMFILE: reclaim fds + exponential backoff (#87644).
                consecutive_failures = _note_tick_failure(e, consecutive_failures)
            # Completed cycle: each profile's own outcome; aborted cycle: all beats unsuccessful.
            for _, home in cycle_homes:
                with _profile_cron_scope(home):
                    _home_ok = _tick_error is None and str(home) not in _profile_errors
                    record_ticker_heartbeat(success=_home_ok)
                    if _home_ok:
                        last_success_at[str(home)] = time.time()
                        clear_ticker_error()
                    elif str(home) in _profile_errors:
                        record_ticker_error(_profile_errors[str(home)])
                    elif _tick_error:
                        record_ticker_error(_tick_error)
                    record_ticker_state(
                        "completed" if _home_ok else "failed", resume_gap_seconds=resume_gap,
                        ticker_started_at_epoch=ticker_started_at,
                        last_success_at_epoch=last_success_at.get(str(home)),
                        **get_ticker_authority_counts(),
                    )
            if ok:
                consecutive_failures = 0
            wait_seconds = _backoff_wait_seconds(interval, consecutive_failures)
            wait_wall = time.time()
            wait_monotonic = time.monotonic()
            stop_event.wait(wait_seconds)
            resume_gap = max(0.0, max(time.time() - wait_wall,
                                      time.monotonic() - wait_monotonic) - wait_seconds)


# ---- BEGIN PLUGIN-COMPAT (revert-scheduled; see COMPAT_MANIFEST.md) ----
# Names external plugins imported from this module before the Sep 2026 decomposition.
# Internal code MUST NOT use these (scripts/check_compat_pointers.py fails CI if it does).
# The whole block is removed by reverting the commit that added it.

def provider_supports_fire_cancel(provider: Any) -> bool:
    """Return whether ``fire_claimed`` accepts a ``cancel_event`` kwarg."""
    try:
        parameters = inspect.signature(provider.fire_claimed).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.name == "cancel_event"
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        )
        for parameter in parameters
    )
# ---- END PLUGIN-COMPAT ----
