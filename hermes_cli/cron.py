"""
Cron subcommand for hermes CLI.

Handles standalone cron management commands like list, show, create, edit,
pause/resume/run/remove, status, and tick.
"""

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from hermes_cli.colors import Colors, color

# Gateway-lifecycle command detection lives in ``cron.lifecycle_guard`` so it
# can be shared across every job-creation path (CLI + the agent's ``cronjob``
# model tool via ``cron.jobs.create_job``) without a circular import. Re-export
# ``_contains_gateway_lifecycle_command`` here for back-compat: ``tools/
# terminal_tool.py`` imports it from this module to hard-block the same
# commands at execution time when ``_HERMES_GATEWAY=1``.
from cron.lifecycle_guard import (  # noqa: F401  (re-exported for terminal_tool)
    contains_gateway_lifecycle_command as _contains_gateway_lifecycle_command,
)


def _normalize_skills(single_skill=None, skills: Optional[Iterable[str]] = None) -> Optional[List[str]]:
    if skills is None:
        if single_skill is None:
            return None
        raw_items = [single_skill]
    else:
        raw_items = list(skills)

    normalized: List[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _cron_api(**kwargs):
    from tools.cronjob_tools import cronjob as cronjob_tool

    return json.loads(cronjob_tool(**kwargs))


def _active_cron_provider_name() -> str:
    """Name of the resolved cron scheduler provider ('builtin', 'chronos', …).

    Best-effort + offline (``resolve_cron_scheduler`` reads config and the
    provider's ``is_available()`` contract forbids network). Returns 'builtin'
    on any failure so callers fall back to the historical ticker-based checks.
    """
    try:
        from cron.scheduler_provider import resolve_cron_scheduler

        return resolve_cron_scheduler().name or "builtin"
    except Exception:
        return "builtin"


def _warn_if_gateway_not_running() -> None:
    """Warn that scheduled jobs won't fire unless the gateway is running.

    The cron ticker only runs inside the gateway (``_start_cron_ticker`` in
    gateway/run.py); there is no standalone cron daemon. Without a running
    gateway, ``next_run_at`` passes but jobs never fire and ``last_run_at``
    stays null — the most common cron support report (#51038). Surfacing this
    at create/list time, when the user is right there, prevents it.

    An external provider (e.g. Chronos) fires jobs via a NAS-mediated webhook,
    NOT the in-process ticker, so a momentarily-absent gateway process does not
    mean jobs won't fire — the warning would be a false alarm. Stay quiet for
    any non-builtin provider; the gateway-process heuristic only speaks to the
    built-in ticker's trigger.
    """
    try:
        if _active_cron_provider_name() != "builtin":
            return

        from hermes_cli.gateway import find_gateway_pids

        if find_gateway_pids():
            return
    except Exception:
        # If we can't determine gateway state, stay quiet rather than nag.
        return

    print(color("  ⚠  Gateway is not running — jobs won't fire automatically.", Colors.YELLOW))
    print(color("     Start it with: hermes gateway install", Colors.DIM))
    print(color("                    sudo hermes gateway install --system  # Linux servers", Colors.DIM))
    print(color("     Check status:  hermes cron status", Colors.DIM))


# A containment reason is written to be READ — the 2026-08-25 Gate-2 incident
# happened because nobody saw one. So the listing shows as much of it as fits on
# a line and, when it clips, names the command that prints the rest verbatim.
# Never clip silently: a truncated barrier text that looks complete is worse
# than no text at all.
_PAUSE_REASON_LIST_LIMIT = 160


def _clip_pause_reason(reason: str, limit: int = _PAUSE_REASON_LIST_LIMIT):
    """Return ``(shown, was_clipped)`` for a one-line rendering of ``reason``.

    Newlines collapse to spaces so a multi-line reason cannot break the
    listing's alignment.
    """
    flat = " ".join(str(reason).split())
    if len(flat) <= limit:
        return flat, False
    return flat[: limit - 1].rstrip() + "…", True


def cron_list(show_all: bool = False):
    """List all scheduled jobs."""
    from cron.jobs import list_jobs

    jobs = list_jobs(include_disabled=show_all)

    if not jobs:
        print(color("No scheduled jobs.", Colors.DIM))
        print(color("Create one with 'hermes cron create ...' or the /cron command in chat.", Colors.DIM))
        return

    print()
    print(color("┌─────────────────────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│                         Scheduled Jobs                                  │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────────────────────┘", Colors.CYAN))
    print()

    for job in jobs:
        job_id = job.get("id", "?")
        name = job.get("name", "(unnamed)")
        schedule = job.get("schedule_display", job.get("schedule", {}).get("value", "?"))
        state = job.get("state", "scheduled" if job.get("enabled", True) else "paused")
        next_run = job.get("next_run_at", "?")

        # `repeat` may be present-but-null in the job record (e.g. a one-shot
        # job persisted with "repeat": null), so coalesce to {} rather than
        # relying on the dict-default, which only applies to a missing key.
        repeat_info = job.get("repeat") or {}
        repeat_times = repeat_info.get("times")
        repeat_completed = repeat_info.get("completed", 0)
        repeat_str = f"{repeat_completed}/{repeat_times}" if repeat_times else "∞"

        # `deliver` may be present-but-null in the job record (same pitfall as
        # `repeat` above), so coalesce to the default rather than relying on the
        # dict-default, which only applies to a missing key. A null value would
        # otherwise reach `", ".join(None)` and crash the whole listing (#32896).
        deliver = job.get("deliver") or ["local"]
        if isinstance(deliver, str):
            deliver = [deliver]
        deliver_str = ", ".join(deliver)

        skills = job.get("skills") or ([job["skill"]] if job.get("skill") else [])
        if state == "paused":
            status = color("[paused]", Colors.YELLOW)
        elif state == "completed":
            status = color("[completed]", Colors.BLUE)
        elif job.get("enabled", True):
            status = color("[active]", Colors.GREEN)
        else:
            status = color("[disabled]", Colors.RED)

        print(f"  {color(job_id, Colors.YELLOW)} {status}")
        print(f"    Name:           {name}")
        if state == "paused":
            raw_reason = job.get("paused_reason")
            paused_at = job.get("paused_at")
            suffix = f" (since {paused_at})" if paused_at else ""
            if raw_reason:
                shown, clipped = _clip_pause_reason(raw_reason)
                print(f"    Paused:         {shown}{suffix}")
                if clipped:
                    print(color(
                        f"               full reason: hermes cron show {job_id}",
                        Colors.DIM,
                    ))
            else:
                print(f"    Paused:         (no reason recorded){suffix}")
        print(f"    Schedule:       {schedule}")
        print(f"    Repeat:         {repeat_str}")
        print(f"    Next run:       {next_run}")
        print(f"    Deliver:        {deliver_str}")

        # The per-job inference pin. This is the highest-precedence and most
        # durable model override on the box — it beats HERMES_MODEL and
        # config.yaml, is re-read from storage every tick, and lives in the
        # untracked cron store, so no git checkout can revert it. Rendering it
        # here is the only way an operator can SEE which jobs are pinned; a
        # job silently running on a stale pin is otherwise indistinguishable
        # from one following the global default. base_url is shown alongside
        # because provider+base_url is a single security-relevant pair (F8),
        # not two independent fields.
        model = job.get("model")
        provider = job.get("provider")
        base_url = job.get("base_url")
        if model:
            print(f"    Model:          {model}")
        if provider:
            print(f"    Provider:       {provider}")
        if base_url:
            print(f"    Base URL:       {base_url}")

        if skills:
            print(f"    Skills:         {', '.join(skills)}")
        script = job.get("script")
        if script:
            print(f"    Script:         {script}")
        if job.get("no_agent"):
            print(f"    Mode:           {color('no-agent', Colors.DIM)} (script stdout delivered directly)")
        workdir = job.get("workdir")
        if workdir:
            print(f"    Workdir:        {workdir}")

        # Execution history
        last_status = job.get("last_status")
        if last_status:
            last_run = job.get("last_run_at", "?")
            if last_status == "ok":
                status_display = color("ok", Colors.GREEN)
            else:
                status_display = color(f"{last_status}: {job.get('last_error', '?')}", Colors.RED)
            print(f"    Last completed: {last_run}  {status_display}")

        latest_execution = job.get("latest_execution")
        if latest_execution:
            print(
                f"    Execution:      {latest_execution.get('status', '?')}  "
                f"{latest_execution.get('id', '?')}"
            )

        delivery_err = job.get("last_delivery_error")
        if delivery_err:
            print(f"    {color('⚠ Delivery failed:', Colors.YELLOW)} {delivery_err}")

        print()

    _warn_if_gateway_not_running()


def cron_show(job_id: str) -> int:
    """Print one job in full — including the UNTRUNCATED pause reason.

    ``cron list`` clips a long ``paused_reason`` to keep the listing readable;
    this is where the whole text lives, so clipping never loses it.
    """
    from cron.jobs import get_job

    job = get_job(job_id)
    if job is None:
        print(color(f"No such job: {job_id}", Colors.RED))
        return 1

    state = job.get("state", "scheduled" if job.get("enabled", True) else "paused")
    print()
    print(f"{color(job.get('id', job_id), Colors.YELLOW)}  {job.get('name', '(unnamed)')}")
    print(f"  State:     {state}")
    print(f"  Enabled:   {job.get('enabled', True)}")
    print(f"  Schedule:  {job.get('schedule_display', job.get('schedule', {}).get('value', '?'))}")
    print(f"  Next run:  {job.get('next_run_at', '?')}")

    paused_at = job.get("paused_at")
    if paused_at:
        print(f"  Paused at: {paused_at}")
    reason = job.get("paused_reason")
    if reason:
        print("  Paused because:")
        for line in str(reason).splitlines() or [""]:
            print(f"    {line}")
    elif state == "paused" or not job.get("enabled", True):
        print(color("  Paused because: (no reason recorded)", Colors.DIM))

    history = job.get("paused_history") or []
    if history:
        print(f"  Earlier pauses ({len(history)}):")
        for entry in history:
            past_reason = entry.get("paused_reason") or "(no reason recorded)"
            resumed = entry.get("resumed_at") or "?"
            print(f"    {entry.get('paused_at', '?')} → {resumed}: {past_reason}")
    print()
    return 0


def cron_tick():
    """Run due jobs once and exit."""
    from cron.scheduler import tick
    tick(verbose=True)


def cron_runs(job_id: Optional[str] = None, limit: int = 20):
    """Show indexed durable cron execution history."""
    from cron.executions import list_executions

    records = list_executions(job_id=job_id, limit=limit)
    if not records:
        print("No cron execution attempts recorded.")
        return
    for record in records:
        print(
            f"{record.get('id', '?')}  {record.get('status', '?'):<9}  "
            f"job={record.get('job_id', '?')}  source={record.get('source', '?')}  "
            f"{record.get('claimed_at', '?')}"
        )
        if record.get("error"):
            print(f"    {record['error']}")


def cron_status():
    """Show cron execution status."""
    from cron.jobs import list_jobs
    from hermes_cli.gateway import find_gateway_pids

    print()

    provider = _active_cron_provider_name()
    if provider != "builtin":
        # An external provider (e.g. Chronos) does NOT run the in-process 60s
        # ticker — it arms one external one-shot per job and is fired by a
        # NAS-mediated webhook, so between fires there is intentionally NO
        # ticker thread and NO heartbeat file. Reporting the ticker-heartbeat
        # staleness here would always say "stalled / not firing" on a perfectly
        # healthy Chronos instance. Report the provider instead and skip the
        # ticker-liveness heuristics entirely.
        print(color(
            f"✓ Cron provider: {provider} — jobs fire via the managed scheduler, "
            "not the in-process ticker.",
            Colors.GREEN,
        ))
        print(color(
            "  (No ticker heartbeat is expected for an external provider; "
            "due jobs are delivered by an authenticated webhook.)",
            Colors.DIM,
        ))
        print()
        _print_active_jobs_summary(list_jobs(include_disabled=False))
        print()
        return

    pids = find_gateway_pids()
    if pids:
        # The gateway PROCESS is alive — but the cron ticker THREAD inside it
        # can die silently, or stay alive while every tick fails. Check both
        # the liveness heartbeat and the last-successful-tick marker so we
        # don't report "will fire" when the ticker is dead or failing
        # (#32612, #32895).
        from cron.jobs import (
            get_ticker_heartbeat_age,
            get_ticker_success_age,
            TICKER_INTERVAL_SECONDS,
        )

        # Allow ~3 missed ticker iterations (+ a little slack) before declaring
        # trouble. Derived from the shared interval constant so this threshold
        # tracks the ticker cadence instead of assuming a hardcoded 60s.
        STALE_AFTER = TICKER_INTERVAL_SECONDS * 3 + 20  # = 200s at the 60s default
        hb_age = get_ticker_heartbeat_age()
        ok_age = get_ticker_success_age()

        if hb_age is not None and hb_age > STALE_AFTER:
            # No heartbeat at all → the ticker thread is gone.
            print(color(
                "⚠ Gateway is running but the cron ticker looks STALLED — "
                f"no heartbeat for {int(hb_age)}s (expected every ~60s).",
                Colors.YELLOW,
            ))
            print(f"  PID: {', '.join(map(str, pids))}")
            print("  Cron jobs may NOT be firing. Restart: hermes gateway restart")
        elif hb_age is not None and ok_age is not None and ok_age > STALE_AFTER:
            # Loop is alive (fresh heartbeat) but no tick has SUCCEEDED in a
            # long time → ticks are failing every iteration.
            print(color(
                "⚠ Gateway and cron ticker are running, but no tick has "
                f"succeeded in {int(ok_age)}s — ticks may be failing.",
                Colors.YELLOW,
            ))
            print(f"  PID: {', '.join(map(str, pids))}")
            print("  Check the gateway log for 'Cron tick error'.")
        else:
            print(color("✓ Gateway is running — cron jobs will fire automatically", Colors.GREEN))
            print(f"  PID: {', '.join(map(str, pids))}")
            if hb_age is not None:
                print(f"  Ticker heartbeat: {int(hb_age)}s ago")
    else:
        print(color("✗ Gateway is not running — cron jobs will NOT fire", Colors.RED))
        print()
        print("  To enable automatic execution:")
        print("    hermes gateway install    # Install as a user service")
        print("    sudo hermes gateway install --system  # Linux servers: boot-time system service")
        print("    hermes gateway            # Or run in foreground")

    print()

    _print_active_jobs_summary(list_jobs(include_disabled=False))

    print()


def _print_active_jobs_summary(jobs) -> None:
    """Print the '<N> active job(s)' + next-run line shared by every status
    path (built-in ticker AND external provider)."""
    if jobs:
        next_runs = [j.get("next_run_at") for j in jobs if j.get("next_run_at")]
        print(f"  {len(jobs)} active job(s)")
        if next_runs:
            print(f"  Next run: {min(next_runs)}")
    else:
        print("  No active jobs")


def cron_create(args):
    # The gateway-lifecycle guard lives in cron.jobs.create_job so it fires on
    # every job-creation path (this CLI subcommand AND the agent's `cronjob`
    # model tool, which calls create_job directly). When it blocks, create_job
    # raises GatewayLifecycleBlocked, the `cronjob` tool wrapper catches it and
    # returns it as result["error"], and the `if not result.get("success")`
    # branch below prints it in red and exits 1 — same UX as before.
    result = _cron_api(
        action="create",
        schedule=args.schedule,
        prompt=args.prompt,
        name=getattr(args, "name", None),
        deliver=getattr(args, "deliver", None),
        repeat=getattr(args, "repeat", None),
        skill=getattr(args, "skill", None),
        skills=_normalize_skills(getattr(args, "skill", None), getattr(args, "skills", None)),
        script=getattr(args, "script", None),
        workdir=getattr(args, "workdir", None),
        no_agent=getattr(args, "no_agent", False) or None,
        # Pin at creation. Beyond setting the override, a pinned axis carries no
        # provider_snapshot/model_snapshot (cron.jobs._compute_provider_model_snapshots),
        # so the job is exempt from the unpinned-drift guard that otherwise
        # refuses to fire once global inference config moves.
        model=getattr(args, "model", None),
        provider=getattr(args, "provider", None),
    )
    if not result.get("success"):
        print(color(f"Failed to create job: {result.get('error', 'unknown error')}", Colors.RED))
        return 1
    print(color(f"Created job: {result['job_id']}", Colors.GREEN))
    print(f"  Name: {result['name']}")
    print(f"  Schedule: {result['schedule']}")
    if result.get("skills"):
        print(f"  Skills: {', '.join(result['skills'])}")
    job_data = result.get("job", {})
    if job_data.get("model"):
        print(f"  Model: {job_data['model']}")
    if job_data.get("provider"):
        print(f"  Provider: {job_data['provider']}")
    if job_data.get("base_url"):
        print(f"  Base URL: {job_data['base_url']}")
    if job_data.get("script"):
        print(f"  Script: {job_data['script']}")
    if job_data.get("no_agent"):
        print("  Mode: no-agent (script stdout delivered directly)")
    if job_data.get("workdir"):
        print(f"  Workdir: {job_data['workdir']}")
    print(f"  Next run: {result['next_run_at']}")
    _warn_if_gateway_not_running()
    return 0


def cron_edit(args):
    from cron.jobs import AmbiguousJobReference, resolve_job_ref

    try:
        job = resolve_job_ref(args.job_id)
    except AmbiguousJobReference as exc:
        print(color(str(exc), Colors.RED))
        for m in exc.matches:
            print(f"  {m['id']}  (name: {m.get('name')!r})")
        return 1
    if not job:
        print(color(f"Job not found: {args.job_id}", Colors.RED))
        return 1

    existing_skills = list(job.get("skills") or ([] if not job.get("skill") else [job.get("skill")]))
    replacement_skills = _normalize_skills(getattr(args, "skill", None), getattr(args, "skills", None))
    add_skills = _normalize_skills(None, getattr(args, "add_skills", None)) or []
    remove_skills = set(_normalize_skills(None, getattr(args, "remove_skills", None)) or [])

    final_skills = None
    if getattr(args, "clear_skills", False):
        final_skills = []
    elif replacement_skills is not None:
        final_skills = replacement_skills
    elif add_skills or remove_skills:
        final_skills = [skill for skill in existing_skills if skill not in remove_skills]
        for skill in add_skills:
            if skill not in final_skills:
                final_skills.append(skill)

    result = _cron_api(
        action="update",
        job_id=args.job_id,
        schedule=getattr(args, "schedule", None),
        prompt=getattr(args, "prompt", None),
        name=getattr(args, "name", None),
        deliver=getattr(args, "deliver", None),
        repeat=getattr(args, "repeat", None),
        skills=final_skills,
        script=getattr(args, "script", None),
        workdir=getattr(args, "workdir", None),
        no_agent=getattr(args, "no_agent", None),
        # The per-job model/provider pin. `cronjob` treats None as "not
        # supplied" and an empty string as "clear", so the argparse default
        # leaves an existing pin untouched. Routing through the tool (rather
        # than update_job directly) is deliberate: `action="update"` re-runs
        # _validate_cron_base_url on the EFFECTIVE provider/base_url pair, so a
        # provider change on a job that already carries a base_url cannot
        # quietly create a credential-exfil pair (F8).
        model=getattr(args, "model", None),
        provider=getattr(args, "provider", None),
    )
    if not result.get("success"):
        print(color(f"Failed to update job: {result.get('error', 'unknown error')}", Colors.RED))
        return 1

    updated = result["job"]
    print(color(f"Updated job: {updated['job_id']}", Colors.GREEN))
    print(f"  Name: {updated['name']}")
    print(f"  Schedule: {updated['schedule']}")
    if updated.get("skills"):
        print(f"  Skills: {', '.join(updated['skills'])}")
    else:
        print("  Skills: none")
    # Echo the inference pin whenever THIS edit touched it, even when the new
    # value is empty. A clear that printed nothing would be indistinguishable
    # from a no-op, and this is the pin that survives a git checkout — the
    # operator needs to read back what the store now holds, not what was typed.
    if getattr(args, "model", None) is not None or updated.get("model"):
        print(f"  Model: {updated.get('model') or '(inherited from env/config)'}")
    if getattr(args, "provider", None) is not None or updated.get("provider"):
        print(f"  Provider: {updated.get('provider') or '(inherited from env/config)'}")
    if updated.get("base_url"):
        print(f"  Base URL: {updated['base_url']}")
    if updated.get("script"):
        print(f"  Script: {updated['script']}")
    if updated.get("no_agent"):
        print("  Mode: no-agent (script stdout delivered directly)")
    if updated.get("workdir"):
        print(f"  Workdir: {updated['workdir']}")
    return 0


def _clean_reason(raw: Optional[str]) -> Optional[str]:
    """Normalize a ``--reason`` value: whitespace is not a reason."""
    return (raw or "").strip() or None


# --- In-flight run reporting for `hermes cron pause` (2026-09-07) -----------
#
# Pause sets enabled=False and stops SCHEDULING. It does not touch a run that
# is already executing inside the gateway: on 2026-09-06 job b74186b2eaa5 was
# paused at 18:14:34 while its 18:00 run was 14 minutes in, and that run kept
# calling tools for 44 more minutes and published 184 proposals -- 116 of
# them fabricated -- an hour after the operator believed the lane was stopped.
# The pausing session had no way to know. These helpers make the pause say so,
# from the one place the CLI can see a live run without the gateway's help:
# the sessions table, where a cron run holds a row `cron_<job>_<stamp>` with
# ended_at NULL for as long as it executes.

_LIKE_ESCAPE = "!"


def _like_escape(text: str) -> str:
    """Escape LIKE metacharacters in ``text`` using ``_LIKE_ESCAPE``."""
    out = []
    for ch in text:
        if ch in (_LIKE_ESCAPE, "%", "_"):
            out.append(_LIKE_ESCAPE)
        out.append(ch)
    return "".join(out)


def _inflight_sessions(job_id: str) -> List[Dict[str, Any]]:
    """Open session rows (``ended_at IS NULL``) for runs of ``job_id``.

    Reads ``state.db`` through a plain read-only sqlite connection: no schema
    setup, no write lock, no contention with the gateway that owns the file.
    Never raises -- a report that cannot be produced must not turn a
    successful pause into a failure -- and an unreadable database yields an
    empty list, which the caller renders as "nothing in flight". That is a
    known failure-toward-quiet: it is why the report also names the owning
    execution from the cron executions store when one is running.
    """
    try:
        import hermes_state

        db_path = Path(hermes_state._default_db_path())
        if not db_path.exists():
            return []
        conn = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=1.0
        )
        try:
            conn.row_factory = sqlite3.Row
            pattern = f"cron{_LIKE_ESCAPE}_{_like_escape(str(job_id))}{_LIKE_ESCAPE}_%"
            rows = conn.execute(
                "SELECT id, started_at, tool_call_count, message_count "
                "FROM sessions "
                f"WHERE id LIKE ? ESCAPE '{_LIKE_ESCAPE}' AND ended_at IS NULL "
                "ORDER BY started_at DESC",
                (pattern,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


def _inflight_execution(job_id: str) -> Optional[Dict[str, Any]]:
    """Newest ``claimed``/``running`` execution record for ``job_id``, if any.

    The executions store carries the owning process's pid, which the sessions
    row does not. Best effort; None on any failure.
    """
    try:
        from cron.executions import list_executions

        for record in list_executions(job_id=job_id, limit=5):
            if record.get("status") in {"claimed", "running"}:
                return record
    except Exception:
        pass
    return None


def _format_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _format_started(started_at: Any) -> str:
    try:
        ts = float(started_at)
    except (TypeError, ValueError):
        return f"started {started_at!r}"
    local = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return f"started {local} ({_format_age(time.time() - ts)} ago)"


def _stop_inflight_command(job_id: str, reason: Optional[str]) -> str:
    cmd = f"hermes cron pause {job_id} --stop-inflight"
    if reason:
        cmd += f' --reason "{reason}"'
    return cmd


def _report_inflight(
    job_id: str,
    *,
    reason: Optional[str],
    stop_inflight: bool,
    caller: str,
) -> List[Dict[str, Any]]:
    """After a successful pause, say whether a run is still executing.

    Prints nothing when no run is in flight and ``stop_inflight`` is off, so
    the ordinary pause output is unchanged. With ``stop_inflight`` a stop
    request is filed for each open session (``cron.inflight.request_stop``);
    the scheduler honours it on its next watchdog poll. Returns the open rows.
    """
    sessions = _inflight_sessions(job_id)
    if not sessions:
        if stop_inflight:
            print(color("  No run in flight for this job; nothing to stop.", Colors.DIM))
        return []

    print(color(
        "  WARNING: a run of this job is STILL EXECUTING. Pause stops future "
        "fires; it does not stop a run already in flight.",
        Colors.YELLOW,
    ))
    for row in sessions:
        print(color(
            f"    session {row.get('id')}  {_format_started(row.get('started_at'))}  "
            f"tool calls {row.get('tool_call_count') or 0}  "
            f"messages {row.get('message_count') or 0}",
            Colors.YELLOW,
        ))
    execution = _inflight_execution(job_id)
    if execution:
        print(color(
            f"    owner: execution {execution.get('id')}  pid {execution.get('pid')}  "
            f"status {execution.get('status')}  claimed {execution.get('claimed_at')}",
            Colors.DIM,
        ))

    if not stop_inflight:
        print(color(
            "  It will keep calling tools and publishing until it finishes on its own.",
            Colors.YELLOW,
        ))
        print(f"  To stop it now:  {_stop_inflight_command(job_id, reason)}")
        return sessions

    from cron.inflight import request_stop

    for row in sessions:
        try:
            request_stop(job_id, session_id=row.get("id"), by=caller, reason=reason)
        except Exception as exc:  # pragma: no cover - filesystem failure
            print(color(f"  Failed to file a stop request: {exc}", Colors.RED))
            continue
        print(color(f"  Stop requested for session {row.get('id')}.", Colors.GREEN))
    print(color(
        "  The scheduler honours it on its next watchdog poll (a few seconds): "
        "the agent is interrupted and the run is recorded as failed with "
        "'stopped by operator'.",
        Colors.DIM,
    ))
    print(color(f"  Verify with:  hermes cron runs {job_id}", Colors.DIM))
    return sessions


def _existing_paused_reason(job_id: str) -> Optional[str]:
    """The reason already recorded on a paused job, if any.

    ``pause_job`` overwrites ``paused_reason`` with whatever is passed, so a
    second ``hermes cron pause <id> --stop-inflight`` issued without
    ``--reason`` -- the exact command the in-flight report prints -- would
    otherwise wipe the reason the first pause recorded.
    """
    try:
        result = _cron_api(action="list", include_disabled=True)
        for job in result.get("jobs") or []:
            if job_id in {job.get("job_id"), job.get("name")}:
                return (job.get("paused_reason") or "").strip() or None
    except Exception:
        pass
    return None


def _job_action(
    action: str,
    job_id: str,
    success_verb: str,
    *,
    reason: Optional[str] = None,
    caller: Optional[str] = None,
    stop_inflight: bool = False,
) -> int:
    kwargs = {"action": action, "job_id": job_id}
    if reason is not None:
        kwargs["reason"] = reason
    if caller is not None:
        kwargs["caller"] = caller
    result = _cron_api(**kwargs)
    if not result.get("success"):
        print(color(f"Failed to {action} job: {result.get('error', 'unknown error')}", Colors.RED))
        return 1
    job = result.get("job") or result.get("removed_job") or {}
    print(color(f"{success_verb} job: {job.get('name', job_id)} ({job_id})", Colors.GREEN))
    if action == "pause":
        paused_reason = job.get("paused_reason")
        if paused_reason:
            print(f"  Reason: {paused_reason}")
        else:
            print(color("  Reason: (none recorded - pass --reason next time)", Colors.DIM))
        _report_inflight(
            job.get("job_id") or job_id,
            reason=paused_reason,
            stop_inflight=stop_inflight,
            caller=caller or "hermes_cli:cron_pause",
        )
    if action in {"resume", "run"} and result.get("job", {}).get("next_run_at"):
        print(f"  Next run: {result['job']['next_run_at']}")
    if action == "run":
        job = result.get("job", {})
        if job.get("executed"):
            outcome = "succeeded" if job.get("execution_success") else "failed"
            print(f"  Ran now: {outcome}.")
        elif job.get("execution_skipped"):
            print(f"  {job['execution_skipped']}")
        else:
            print("  It will run on the next scheduler tick.")
    return 0


def cron_barrier(args) -> int:
    """Show / set / clear a job's resume authorization barrier.

    The operator surface for the fence added 2026-08-26. Without it the only
    way to set a barrier is an in-process call, which is precisely the shape
    of access that produced the bypass in the first place - the sanctioned
    path has to be the convenient one or nobody uses it.

    ``--caller`` is required for both mutating modes and is NOT defaulted to a
    fixed "hermes_cli:..." string the way pause/resume are. Those record which
    SURFACE acted, which is enough for a routine pause; a barrier lift needs to
    record which PERSON or script decided the condition was met, and a constant
    cannot carry that.
    """
    job_id = args.job_id
    setting = getattr(args, "barrier_set", False)
    clearing = getattr(args, "barrier_clear", False)
    reason = _clean_reason(getattr(args, "reason", None))
    caller = (getattr(args, "caller", None) or "").strip()

    if not setting and not clearing:
        result = _cron_api(action="list", include_disabled=True)
        jobs = result.get("jobs") or []
        match = next(
            (j for j in jobs if job_id in {j.get("job_id"), j.get("name")}), None
        )
        if match is None:
            print(color(f"No job matching '{job_id}'.", Colors.RED))
            return 1
        barrier = match.get("resume_barrier")
        label = f"{match.get('name')} ({match.get('job_id')})"
        if not barrier:
            print(f"{label}: no resume barrier.")
            return 0
        print(color(f"{label}: RESUME BARRIER SET", Colors.YELLOW))
        print(f"  Reason:  {barrier.get('reason')}")
        print(f"  Set by:  {barrier.get('set_by')}")
        print(f"  Set at:  {barrier.get('set_at')}")
        print(color("  This job will not resume, trigger, or be admitted by the", Colors.DIM))
        print(color("  scheduler until it is cleared.", Colors.DIM))
        return 0

    if not reason:
        verb = "set" if setting else "clear"
        print(color(f"--reason is required to {verb} a barrier.", Colors.RED))
        return 1
    if not caller:
        print(color("--caller is required to set or clear a barrier.", Colors.RED))
        return 1

    action = "barrier_set" if setting else "barrier_clear"
    result = _cron_api(action=action, job_id=job_id, reason=reason, caller=caller)
    if not result.get("success"):
        print(color(f"Failed: {result.get('error', 'unknown error')}", Colors.RED))
        return 1
    job = result.get("job") or {}
    label = f"{job.get('name', job_id)} ({job.get('job_id', job_id)})"
    if setting:
        print(color(f"Resume barrier SET on {label}", Colors.YELLOW))
        print(f"  Reason: {reason}")
        print(color("  It will not run again until the barrier is cleared.", Colors.DIM))
    else:
        print(color(f"Resume barrier CLEARED on {label}", Colors.GREEN))
        print(f"  Justification: {reason}")
        print(color("  The job is NOT resumed - run 'hermes cron resume' separately.", Colors.DIM))
    return 0


def cron_command(args):
    """Handle cron subcommands."""
    subcmd = getattr(args, 'cron_command', None)

    if subcmd is None or subcmd == "list":
        show_all = getattr(args, 'all', False)
        cron_list(show_all)
        return 0

    if subcmd in {"show", "detail"}:
        return cron_show(args.job_id)

    if subcmd == "status":
        cron_status()
        return 0

    if subcmd == "tick":
        cron_tick()
        return 0

    if subcmd in {"runs", "history"}:
        cron_runs(getattr(args, "job_id", None), getattr(args, "limit", 20))
        return 0

    if subcmd in {"create", "add"}:
        return cron_create(args)

    if subcmd == "edit":
        return cron_edit(args)

    if subcmd == "pause":
        stop_inflight = bool(getattr(args, "stop_inflight", False))
        reason = _clean_reason(getattr(args, "reason", None))
        if stop_inflight and reason is None:
            # Re-pausing to stop a run must not erase the reason the first
            # pause recorded (see _existing_paused_reason).
            reason = _existing_paused_reason(args.job_id)
        return _job_action(
            "pause",
            args.job_id,
            "Paused",
            reason=reason,
            caller="hermes_cli:cron_pause",
            stop_inflight=stop_inflight,
        )

    if subcmd == "resume":
        return _job_action(
            "resume",
            args.job_id,
            "Resumed",
            caller="hermes_cli:cron_resume",
        )

    if subcmd == "barrier":
        return cron_barrier(args)

    if subcmd == "run":
        return _job_action(
            "run",
            args.job_id,
            "Triggered",
            reason=_clean_reason(getattr(args, "reason", None)),
            caller="hermes_cli:cron_run",
        )

    if subcmd in {"remove", "rm", "delete"}:
        return _job_action("remove", args.job_id, "Removed")

    print(f"Unknown cron command: {subcmd}")
    print("Usage: hermes cron [list|show|create|edit|pause|resume|barrier|run|remove|status|runs|tick]")
    sys.exit(1)
