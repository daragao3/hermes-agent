"""Dashboard cron helpers: per-profile scheduler I/O, job validation/normalisation, cron fire and
gateway forwarding.
"""

import contextlib
import json
import os
import time
import logging
import inspect
import re
from fastapi import HTTPException
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from hermes_cli.config import cfg_get
from hermes_cli.web_models import CronJobCreate

# Same logger the code used before extraction (record parity).
_log = logging.getLogger("hermes_cli.web_server")


def _cron_optional_text(value: Any, *, strip_trailing_slash: bool = False) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if strip_trailing_slash:
        text = text.rstrip("/")
    return text or None


def _cron_string_list(value: Any) -> Optional[List[str]]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]", value)
    elif isinstance(value, (list, tuple)):
        raw_items = value
    else:
        return None
    items = [str(item).strip() for item in raw_items if str(item).strip()]
    return items or None


def _normalize_dashboard_cron_script(value: Any, profile_home: Path) -> Optional[str]:
    """Validate a dashboard-selected cron script against the profile sandbox."""
    text = _cron_optional_text(value)
    if not text:
        return None
    scripts_root = (profile_home / "scripts").resolve()
    raw_path = Path(text).expanduser()
    candidate = raw_path.resolve() if raw_path.is_absolute() else (scripts_root / raw_path).resolve()
    try:
        relative = candidate.relative_to(scripts_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"script must be inside {scripts_root}") from exc
    if not candidate.exists():
        raise HTTPException(status_code=400, detail=f"script does not exist: {candidate}")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"script is not a file: {candidate}")
    return str(relative)


def _validate_dashboard_cron_effective_job(job: Dict[str, Any]) -> None:
    prompt = _cron_optional_text(job.get("prompt"))
    script = _cron_optional_text(job.get("script"))
    skills = _cron_string_list(job.get("skills")) or _cron_string_list(job.get("skill"))
    if job.get("no_agent"):
        if not script:
            raise HTTPException(status_code=400, detail="no_agent=True requires a script")
        return
    if not (prompt or skills or script):
        raise HTTPException(status_code=400, detail="agent cron jobs require a prompt, skill, or script")


def _validate_dashboard_cron_context_from(refs: Optional[List[str]], profile_name: str) -> None:
    for ref in refs or ():
        # "self" (the continuity toggle) resolves to the job's own id at run time — it can't be
        # validated against the store (create precedes the job's existence).
        if isinstance(ref, str) and ref.strip().lower() == "self":
            continue
        if not _call_cron_for_profile(profile_name, "get_job", ref):
            raise HTTPException(
                status_code=400,
                detail=f"context_from job '{ref}' not found in profile '{profile_name}'")


def _cron_profile_dicts() -> List[Dict[str, Any]]:
    """Minimal profile records (callers only consume ``name``); avoids ``list_profiles()``,
    whose config parsing, gateway probes and skill counts are GIL pressure on large pools."""
    from hermes_cli.web_server_profiles import _fallback_profile_dicts
    from hermes_cli import profiles as profiles_mod
    try:
        return [
            {"name": name, "path": str(home), "is_default": name == "default"}
            for name, home in profiles_mod.profiles_to_serve(multiplex=True)]
    except Exception:
        _log.exception("Failed to list profiles for cron dashboard; falling back to directory scan")
        return _fallback_profile_dicts(profiles_mod)


def _cron_default_profile() -> str:
    """Profile to target when a cron request carries no explicit ``profile``.

    A desktop pool backend runs one process per profile, but these endpoints route storage through
    the profiles tree via ``_cron_profile_home`` — a hardcoded "default" would write a non-default
    profile's job into ~/.hermes. ``custom`` (HERMES_HOME outside the profiles tree) has no
    profile-dir equivalent, so it keeps the legacy "default" fallback.
    """
    try:
        from hermes_cli.profiles import get_active_profile_name
        name = get_active_profile_name()
    except Exception:
        return "default"
    return "default" if name in ("default", "custom") else name


def _cron_profile_home(profile: Optional[str]) -> Tuple[str, Path]:
    """Resolve a profile query value to (profile_name, HERMES_HOME)."""
    from hermes_cli import profiles as profiles_mod
    raw = (profile or _cron_default_profile()).strip() or "default"
    try:
        canon = profiles_mod.normalize_profile_name(raw)
        profiles_mod.validate_profile_name(canon)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not profiles_mod.profile_exists(canon):
        raise HTTPException(status_code=404, detail=f"Profile '{canon}' does not exist.")
    return canon, profiles_mod.get_profile_dir(canon)


def _annotate_cron_job(job: Dict[str, Any], profile: str, home: Path) -> Dict[str, Any]:
    return {
        **job,
        "profile": profile,
        "profile_name": profile,
        "hermes_home": str(home),
        "is_default_profile": profile == "default"}


@contextlib.contextmanager
def _cron_store_scope(home: Path):
    """Point HERMES_HOME and the cron.jobs store at one profile's home for the block.

    The dashboard is a single process inspecting many profiles; cron.jobs' execution-context
    override keeps these calls from retargeting a concurrent desktop ticker's load/save.
    """
    from cron import jobs as cron_jobs
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    token = set_hermes_home_override(str(home))
    try:
        with cron_jobs.use_cron_store(home):
            yield cron_jobs
    finally:
        reset_hermes_home_override(token)


def _call_cron_for_profile(target_profile: Optional[str], func_name: str, *args, **kwargs):
    """Run a cron.jobs helper against the selected profile's cron directory."""
    profile_name, home = _cron_profile_home(target_profile)
    with _cron_store_scope(home) as cron_jobs:
        if func_name == "create_job":
            from cron.scheduler import create_job_with_scheduler_registration
            result = create_job_with_scheduler_registration(*args, **kwargs)
        else:
            result = getattr(cron_jobs, func_name)(*args, **kwargs)
    if isinstance(result, list):
        return [_annotate_cron_job(j, profile_name, home) for j in result]
    if isinstance(result, dict):
        return _annotate_cron_job(result, profile_name, home)
    return result


def _notify_cron_provider_for_profile(target_profile: Optional[str]) -> None:
    """Best-effort provider reconcile against one profile's job store.

    Fail-closed for external providers on a multi-profile dashboard: an external ``reconcile``
    converges its REMOTE (non-profile-scoped) registry toward one profile's jobs.json and cancels
    every remote entry absent from it, so reconciling profile B would disarm profile A's one-shots.
    Until the provider contract carries a profile identity, skip unscoped external reconciles; the
    affected profile re-arms on its next fire/start (idempotent via dedup_key). The built-in
    provider re-reads jobs.json each tick and stays a no-op here.
    """
    try:
        _profile_name, home = _cron_profile_home(target_profile)
        from cron.scheduler_provider import InProcessCronScheduler, resolve_cron_scheduler
        with _cron_store_scope(home):
            provider = resolve_cron_scheduler()
            external = not isinstance(provider, InProcessCronScheduler)
            if external and sum(1 for p in _cron_profile_dicts() if p.get("name")) > 1:
                _log.warning(
                    "Skipping cron provider reconcile for profile %s: "
                    "external provider '%s' reconcile is not "
                    "profile-scoped and would disarm other profiles' "
                    "armed one-shots. The mutated profile re-arms "
                    "idempotently on its next fire/start.", target_profile, provider.name,
                )
                return
            provider.on_jobs_changed()
    except Exception:
        _log.debug("Cron provider reconciliation failed for profile %s", target_profile, exc_info=True)


def _mutate_cron_for_profile(target_profile: Optional[str], func_name: str, *args, **kwargs):
    """Apply a cron store mutation and reconcile its scheduler provider."""
    result = _call_cron_for_profile(target_profile, func_name, *args, **kwargs)
    if result:
        _notify_cron_provider_for_profile(target_profile)
    return result


def _find_cron_job_profile(job_id: str) -> Optional[str]:
    for profile in _cron_profile_dicts():
        name = str(profile.get("name") or "")
        if not name:
            continue
        jobs = _call_cron_for_profile(name, "list_jobs", True)
        if any(j.get("id") == job_id or j.get("name") == job_id for j in jobs):
            return name
    return None


async def _run_cron_dashboard_io(func, *args, **kwargs):
    """Run cron dashboard profile/job I/O outside the FastAPI event loop."""
    from starlette.concurrency import run_in_threadpool
    if inspect.iscoroutinefunction(func):
        raise TypeError("_run_cron_dashboard_io only accepts sync callables")
    result = await run_in_threadpool(func, *args, **kwargs)
    if inspect.isawaitable(result):
        raise TypeError("_run_cron_dashboard_io sync callable returned an awaitable")
    return result


def _raise_if_cron_registration_error(e: Exception) -> None:
    """Re-raise a cron partial failure (job saved, external scheduler registration failed) as
    HTTP 424 with the structured envelope. Shared by every dashboard cron-create surface."""
    from cron.scheduler import CronSchedulerRegistrationError
    if isinstance(e, CronSchedulerRegistrationError):
        raise HTTPException(status_code=424, detail=e.to_dict()) from e


def _create_cron_job_sync(body: CronJobCreate, profile: Optional[str] = None):
    try:
        profile_name, profile_home = _cron_profile_home(profile)
        script = _normalize_dashboard_cron_script(body.script, profile_home)
        skills = _cron_string_list(body.skills)
        context_from = _cron_string_list(body.context_from)
        _validate_dashboard_cron_context_from(context_from, profile_name)
        no_agent = bool(body.no_agent)
        _validate_dashboard_cron_effective_job(
            {"prompt": body.prompt, "skills": skills, "script": script, "no_agent": no_agent})
        return _mutate_cron_for_profile(
            profile_name,
            "create_job",
            prompt=body.prompt or "",
            schedule=body.schedule,
            name=body.name,
            deliver=_cron_optional_text(body.deliver) or "local",
            skills=skills,
            model=_cron_optional_text(body.model),
            provider=_cron_optional_text(body.provider),
            base_url=_cron_optional_text(body.base_url, strip_trailing_slash=True),
            script=script,
            context_from=context_from,
            enabled_toolsets=_cron_string_list(body.enabled_toolsets),
            workdir=_cron_optional_text(body.workdir),
            no_agent=no_agent,
            **{key: getattr(body, key) for key in ("paused", "paused_reason")
               if key in body.model_fields_set})
    except HTTPException:
        raise
    except Exception as e:
        _raise_if_cron_registration_error(e)
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e))


def _fire_cron_job_for_profile(profile: str, job_id: str, *, force: bool = False) -> bool:
    """Run ONE due cron job for ``profile`` via the scheduler provider's ``fire_due``.

    DEPRECATED for NAS webhook fires — superseded by :func:`_forward_cron_fire_to_gateway`, since
    fires must run in the GATEWAY process (it owns the live adapters; the standalone path here
    cannot serve relay-fronted platforms or E2EE rooms). Retained for the dashboard trigger path
    and external callers on the web_deps late-binding seam; do not add new uses.
    """
    _profile_name, home = _cron_profile_home(profile)
    from cron.scheduler_provider import provider_supports_force_fire, resolve_cron_scheduler
    with _cron_store_scope(home):
        provider = resolve_cron_scheduler()
        if force:
            if not provider_supports_force_fire(provider):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Cron provider '{getattr(provider, 'name', 'custom')}' "
                        "does not support atomic forced firing of paused jobs"))
            return bool(provider.fire_due(job_id, adapters=None, loop=None, force=True))
        return bool(provider.fire_due(job_id, adapters=None, loop=None))


def _profile_env_value(home: Path, key: str) -> str:
    """Best-effort read of one KEY=VALUE line from a profile's .env file."""
    try:
        env_path = home / ".env"
        if not env_path.is_file():
            return ""
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _gateway_fire_endpoint(profile: str, home: Path) -> str:
    """Loopback URL of the gateway api_server's cron-fire route.

    Port resolution mirrors gateway/config.py's api_server load order for the LISTENER-OWNER
    profile: ``platforms.api_server.extra.port`` in its config.yaml, then ``API_SERVER_PORT``
    (process env for the active profile, the profile's own .env otherwise), then 8642. Loopback
    is safe: dashboard and gateway share a network namespace in every supported deployment.

    In multiplex mode only the DEFAULT profile's api_server is bound and exposes per-profile
    mirrors under ``/p/<profile>/…``, so a non-default profile's port must be read from the
    default home (a secondary's own API_SERVER_PORT is a port nothing listens on).
    """
    from hermes_cli.config import load_config
    import os as _os
    multiplex = False
    try:
        from gateway.config import _env_multiplex_profiles_override
        multiplex = bool(cfg_get(load_config(), "gateway", "multiplex_profiles", default=False))
        env_flag = _env_multiplex_profiles_override()
        if env_flag is not None:
            multiplex = env_flag
    except Exception:
        _log.debug("cron fire: multiplex detection failed; assuming single-profile", exc_info=True)

    listener_profile, listener_home = profile, home
    if multiplex and profile != "default":
        from hermes_constants import get_default_hermes_root
        listener_profile, listener_home = "default", get_default_hermes_root()
        _log.info(
            "cron fire: multiplex gateway — resolving api_server port for %s "
            "from the default profile's listener (%s)", profile, listener_home,
        )

    port = 0
    try:
        # Profile-scoped read through the CANONICAL loader (managed-scope overlay, ${ENV_VAR}
        # expansion) — never a raw yaml.safe_load (tests/hermes_cli/test_config_read_guard.py).
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        token = set_hermes_home_override(str(listener_home))
        try:
            profile_cfg = load_config()
        finally:
            reset_hermes_home_override(token)
        raw = cfg_get(profile_cfg, "platforms", "api_server", "extra", "port", default=None)
        if raw:
            port = int(raw)
    except Exception:
        port = 0
    if not port:
        raw = (
            _os.getenv("API_SERVER_PORT", "")
            if listener_profile == _cron_default_profile()
            else _profile_env_value(listener_home, "API_SERVER_PORT"))
        try:
            port = int(raw) if raw else 0
        except ValueError:
            port = 0
    port = port or 8642
    if multiplex and profile != "default":
        return f"http://127.0.0.1:{port}/p/{profile}/api/cron/fire"
    return f"http://127.0.0.1:{port}/api/cron/fire"


async def _forward_cron_fire_to_gateway(
    profile: str, job_id: str, authorization: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Forward a Chronos fire callback byte-preserved to the gateway api_server on loopback.

    The dashboard is the hosted deployment's only public HTTP door, but cron execution belongs to
    the GATEWAY process (live adapters → relay-fronted platforms and E2EE rooms work). Same job_id
    and NAS bearer; the gateway re-verifies the JWT itself.

    Returns ``(status_code, body)``, or ``None`` when the gateway is unreachable (scale-to-zero
    wake, restart, api_server disabled). The caller maps None to 503 so NAS retries (store CAS
    de-dupes a double fire) — unless :func:`_gateway_intentionally_stopped`, in which case it
    drops the fire with 200: retrying into an operator-stopped gateway can never succeed.
    """
    _profile_name, home = _cron_profile_home(profile)
    url = _gateway_fire_endpoint(_profile_name, home)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"job_id": job_id}, headers={"Authorization": authorization})
    except Exception as exc:
        _log.warning("cron fire forward to %s failed (%s: %s); returning 503 for NAS retry", url, type(exc).__name__, exc)
        return None
    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:500]}
    if not isinstance(body, dict):
        body = {"raw": body}
    return resp.status_code, body


def _gateway_intentionally_stopped(profile: Optional[str]) -> bool:
    """True when the profile's gateway is stopped BY OPERATOR INTENT.

    Reads the durable ``desired_state`` of gateway_state.json, written only by the s6 lifecycle
    commands (``gateway stop`` persists "stopped"; start/restart persist "running") and never
    during transient windows (crash loops, drains, wakes) — so it splits "retry will eventually
    succeed" from "retry can never succeed". Deliberately does NOT fall back to the volatile
    ``gateway_state`` runtime field: a legacy/crashed file must stay on the retryable-503 path.
    Any resolution or parse failure returns False (fail open toward retry).
    """
    import json as _json
    try:
        data = _json.loads((_cron_profile_home(profile)[1] / "gateway_state.json").read_text(encoding="utf-8"))
        return isinstance(data, dict) and data.get("desired_state") == "stopped"
    except Exception:
        return False


_GATEWAY_HEARTBEAT_FRESH_SECONDS = 180
_GATEWAY_SILENT_OWNER_HOLD_TICKS = 5


def _start_desktop_cron_ticker(stop_event, interval=60, owner_hold_ticks=_GATEWAY_SILENT_OWNER_HOLD_TICKS):
    """Run provider lifecycle with desktop heartbeat and per-profile ownership gates."""
    mode = (os.getenv("HERMES_DESKTOP_CRON") or "").strip()
    if mode == "0":
        _log.info("Desktop cron ticker disabled (HERMES_DESKTOP_CRON=0)")
        return

    from cron.scheduler_provider import InProcessCronScheduler, resolve_cron_scheduler

    provider = resolve_cron_scheduler()
    if not isinstance(provider, InProcessCronScheduler):
        provider.start(stop_event, interval=interval)
        return

    from hermes_cli.profiles import profiles_to_serve, _check_gateway_running
    from hermes_constants import get_hermes_home

    try:
        homes = list(profiles_to_serve(multiplex=True))
    except Exception:
        _log.exception("Desktop cron: profile enumeration failed; ticking active profile only")
        homes = []
    if not homes:
        homes = [(None, get_hermes_home())]
    if len(homes) > 1:
        from hermes_logging import enable_profile_log_routing

        enable_profile_log_routing(homes)

    states = {}
    silent_ticks = {}

    def gate(name, home):
        key = str(home)
        # Explicit always-tick retains the local override, with upstream multiplex scope.
        if mode == "1":
            return True
        if _machine_gateway_alive():
            silent_ticks[key] = 0
            state = "deferring"
        elif silent_ticks.get(key, 0) < owner_hold_ticks and _gateway_heartbeat_owner_alive():
            silent_ticks[key] = silent_ticks.get(key, 0) + 1
            state = "holding"
        elif _check_gateway_running(Path(home)):
            state = "profile-owned"
        else:
            state = "active"
        if states.get(key) != state:
            _log.info("Desktop cron ticker %s for profile %s", state, name)
            states[key] = state
        return state == "active"

    # Even one home needs the multiplex gate: single-store provider.start has no gate.
    provider.start(stop_event, interval=interval, profile_homes=homes, profile_gate=gate)

def _machine_gateway_alive(threshold_seconds: float = _GATEWAY_HEARTBEAT_FRESH_SECONDS) -> bool:
    """Whether a machine gateway wrote its liveness heartbeat recently.

    Missing file, unreadable file, or any resolver error counts as NOT alive —
    the safe default is to keep ticking (a desktop-only install has no
    gateway and no heartbeat file at all).
    """
    try:
        from events.paths import gateway_heartbeat_path

        return (time.time() - gateway_heartbeat_path().stat().st_mtime) < threshold_seconds
    except Exception:
        return False


def _gateway_heartbeat_owner_alive() -> bool:
    """Whether the pid recorded IN the gateway heartbeat file is still running.

    The heartbeat payload (``events.gateway_integration._write_heartbeat``)
    carries the writer's pid. Liveness is probed the way
    ``cron/executions.py::_owner_is_live`` does, through
    ``gateway.status._pid_exists`` -- never ``os.kill(pid, 0)``, which sends
    Ctrl+C to the target's console group on Windows.

    Missing file, non-JSON payload (older writers; tests that only touch the
    mtime), a missing or invalid ``pid``, or any probe error all count as NOT
    alive, so the ticker then behaves exactly as it did before this check
    existed: a stale heartbeat means take over. Failing toward "dead" keeps
    the legacy fallback reachable; it can never make the ticker defer to a
    gateway that is not there.
    """
    try:
        from events.paths import gateway_heartbeat_path
        from gateway.status import _pid_exists

        payload = json.loads(gateway_heartbeat_path().read_text(encoding="utf-8"))
        pid = payload.get("pid") if isinstance(payload, dict) else None
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return False
        return bool(_pid_exists(pid))
    except Exception:
        return False
