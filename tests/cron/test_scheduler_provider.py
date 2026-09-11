"""Characterization tests for the cron trigger before/after the provider refactor.

These lock the CURRENT in-process-ticker contract (Phase 0 of the pluggable
CronScheduler plan, .hermes/plans/cron-scheduler-provider-interface.md). They
must pass unchanged on `main` now, and after every subsequent phase of the
refactor — they are the regression harness that proves the built-in firing
behavior is byte-for-byte preserved when the ticker is moved behind the
CronScheduler provider interface.

No production code is exercised beyond the two ticker entry points:
  - gateway/run.py::_start_cron_ticker        (production gateway ticker)
  - hermes_cli/web_server.py::_start_desktop_cron_ticker  (desktop fallback)

Both call `cron.scheduler.tick(...)` on a loop and exit when their stop_event
is set. We patch `cron.scheduler.tick` (both tickers import it locally as
`cron_tick`, so the module-attribute patch is observed) and assert the loop
drives it and stops promptly.
"""
import threading
import time
from datetime import timedelta
from unittest.mock import patch


def _wait_until(predicate, timeout=10.0, interval=0.005):
    """Block until ``predicate()`` is truthy or ``timeout`` elapses.

    Returns the predicate's final value. Used instead of a fixed
    ``time.sleep`` before asserting that a background ticker thread has called
    tick()/heartbeat() at least N times — under loaded CI the worker thread may
    not be scheduled within a short fixed sleep, which made these tests flake
    (``assert 0 >= 1`` / ``provider never called tick()``).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def test_ticker_calls_tick_at_least_once_then_stops():
    """The gateway in-process ticker loop calls cron.scheduler.tick repeatedly
    and exits promptly once the stop_event is set."""
    from gateway.run import _start_cron_ticker

    calls = []
    stop = threading.Event()

    def fake_tick(*args, **kwargs):
        calls.append(kwargs)
        return 0

    with patch("cron.scheduler.tick", side_effect=fake_tick):
        # interval=0 keeps the loop tight; stop after the first observed tick.
        t = threading.Thread(
            target=_start_cron_ticker,
            args=(stop,),
            kwargs={"interval": 0},
            daemon=True,
        )
        t.start()
        assert _wait_until(lambda: len(calls) >= 1), "ticker never called tick()"
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive(), "ticker did not exit after stop_event was set"
    assert len(calls) >= 1, "ticker never called tick()"
    # Contract: the ticker invokes tick with sync=False (fire-and-forget from
    # the background thread, never the synchronous CLI path).
    assert calls[0].get("sync") is False


def test_desktop_ticker_calls_tick_then_stops():
    """The desktop dashboard ticker loop calls cron.scheduler.tick and exits
    once the stop_event is set. Desktop has no live adapters, so it ticks with
    no adapters/loop."""
    from hermes_cli.web_server import _start_desktop_cron_ticker

    calls = []
    stop = threading.Event()

    def fake_tick(*args, **kwargs):
        calls.append(kwargs)
        return 0

    with patch("cron.scheduler.tick", side_effect=fake_tick):
        t = threading.Thread(
            target=_start_desktop_cron_ticker,
            args=(stop,),
            kwargs={"interval": 0},
            daemon=True,
        )
        t.start()
        assert _wait_until(lambda: len(calls) >= 1), "desktop ticker never called tick()"
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive(), "desktop ticker did not exit after stop_event was set"
    assert len(calls) >= 1, "desktop ticker never called tick()"
    assert calls[0].get("sync") is False


# ── Phase 1: CronScheduler ABC + InProcessCronScheduler ──────────────────────


def test_cronscheduler_is_abstract():
    """name + start are abstract — the bare ABC can't be instantiated."""
    import pytest
    from cron.scheduler_provider import CronScheduler

    with pytest.raises(TypeError):
        CronScheduler()


def test_abc_growth_stays_additive():
    """The provider interface stays source-compatible with existing plugins.

    ``start`` must be the only required implementation hook: future optional
    behavior belongs in non-abstract default methods so custom plugins do not
    break on import after an upgrade.
    """
    from cron.scheduler_provider import CronScheduler

    abstract = set(getattr(CronScheduler, "__abstractmethods__", set()))
    assert abstract == {"name", "start"}, (
        f"CronScheduler abstractmethods changed to {abstract}; growth must be "
        "additive (optional methods with defaults), not new abstract methods."
    )


def test_force_fire_capability_detects_legacy_override():
    from cron.scheduler_provider import CronScheduler

    class Current(CronScheduler):
        @property
        def name(self):
            return "current"

        def start(self, stop_event, **kw):
            pass

    class Legacy(Current):
        def fire_due(  # type: ignore[invalid-method-override]
            self, job_id, *, adapters=None, loop=None
        ):
            return True

    class PositionalOnly(Current):
        def fire_due(  # type: ignore[invalid-method-override]
            self, job_id, force=False, /
        ):
            return True

    class KeywordSink(Current):
        def fire_due(self, job_id, **kwargs):
            return True

    assert Current().supports_force_fire is True
    assert Legacy().supports_force_fire is False
    assert PositionalOnly().supports_force_fire is False
    assert KeywordSink().supports_force_fire is True


def test_inprocess_provider_ticks_and_stops():
    """The built-in provider drives cron.scheduler.tick(sync=False) on a loop
    and exits promptly when stop_event is set — same contract as the raw
    ticker characterized above."""
    from cron.scheduler_provider import InProcessCronScheduler

    calls = []
    stop = threading.Event()
    prov = InProcessCronScheduler()
    assert prov.name == "builtin"

    with patch("cron.scheduler.tick", side_effect=lambda *a, **k: calls.append(k) or 0):
        t = threading.Thread(
            target=prov.start, args=(stop,), kwargs={"interval": 0}, daemon=True
        )
        t.start()
        # Wait for the loop to actually call tick() at least once rather than
        # sleeping a fixed window — under loaded CI the worker thread may not be
        # scheduled within a short sleep, which made this flake (assert 0 >= 1).
        assert _wait_until(lambda: len(calls) >= 1), "provider never called tick()"
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive(), "provider did not exit after stop_event was set"
    assert len(calls) >= 1, "provider never called tick()"
    assert calls[0].get("sync") is False


# ── Phase 2: config key, discovery, resolver ─────────────────────────────────


def test_default_config_cron_provider_is_empty():
    """The new cron.provider key defaults to empty (= built-in)."""
    from hermes_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["cron"]["provider"] == ""


def test_discover_cron_schedulers_returns_list():
    """Discovery returns bundled non-default providers.

    The built-in is core, not discovered here.
    """
    from plugins.cron_providers import discover_cron_schedulers

    result = discover_cron_schedulers()
    assert isinstance(result, list)
    assert any(name == "chronos" for name, _desc, _available in result)


def test_load_unknown_cron_scheduler_returns_none():
    from plugins.cron_providers import load_cron_scheduler

    assert load_cron_scheduler("does-not-exist-xyz") is None


def test_cron_provider_package_does_not_shadow_core_cron_package(monkeypatch):
    """Putting plugins/ first on sys.path must not hide the core cron package."""
    from importlib.machinery import PathFinder
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]

    monkeypatch.syspath_prepend(str(repo_root))
    monkeypatch.syspath_prepend(str(repo_root / "plugins"))

    cron_spec = PathFinder.find_spec("cron")
    assert cron_spec is not None
    assert Path(cron_spec.origin).resolve() == repo_root / "cron" / "__init__.py"

    jobs_spec = PathFinder.find_spec("cron.jobs", [str(repo_root / "cron")])
    assert jobs_spec is not None
    assert Path(jobs_spec.origin).resolve() == repo_root / "cron" / "jobs.py"


def test_resolve_defaults_to_builtin(monkeypatch):
    """Empty cron.provider → built-in."""
    import hermes_cli.config as cfg
    from cron import scheduler_provider as sp

    monkeypatch.setattr(cfg, "load_config", lambda: {"cron": {"provider": ""}})
    prov = sp.resolve_cron_scheduler()
    assert prov.name == "builtin"


def test_resolve_no_cron_section_falls_back_to_builtin(monkeypatch):
    """Config with no cron section at all → built-in (cfg_get returns default)."""
    import hermes_cli.config as cfg
    from cron import scheduler_provider as sp

    monkeypatch.setattr(cfg, "load_config", lambda: {})
    prov = sp.resolve_cron_scheduler()
    assert prov.name == "builtin"


def test_resolve_unknown_provider_falls_back_to_builtin(monkeypatch):
    """A named provider that doesn't exist → built-in (cron never dies)."""
    import hermes_cli.config as cfg
    from cron import scheduler_provider as sp

    monkeypatch.setattr(cfg, "load_config", lambda: {"cron": {"provider": "nope-not-real"}})
    prov = sp.resolve_cron_scheduler()
    assert prov.name == "builtin"


def test_resolve_unavailable_provider_falls_back(monkeypatch):
    """A provider that loads but reports is_available()==False → built-in."""
    import hermes_cli.config as cfg
    import plugins.cron_providers as pc
    from cron import scheduler_provider as sp
    from cron.scheduler_provider import CronScheduler

    class Unavailable(CronScheduler):
        @property
        def name(self):
            return "unavailable"

        def is_available(self):
            return False

        def start(self, stop_event, **kw):
            pass

    monkeypatch.setattr(cfg, "load_config", lambda: {"cron": {"provider": "unavailable"}})
    monkeypatch.setattr(pc, "load_cron_scheduler", lambda n: Unavailable())
    prov = sp.resolve_cron_scheduler()
    assert prov.name == "builtin"


def test_resolve_available_provider_is_used(monkeypatch):
    """A provider that loads and is available is returned (not the fallback)."""
    import hermes_cli.config as cfg
    import plugins.cron_providers as pc
    from cron import scheduler_provider as sp
    from cron.scheduler_provider import CronScheduler

    class Fake(CronScheduler):
        @property
        def name(self):
            return "fake"

        def is_available(self):
            return True

        def start(self, stop_event, **kw):
            pass

    monkeypatch.setattr(cfg, "load_config", lambda: {"cron": {"provider": "fake"}})
    monkeypatch.setattr(pc, "load_cron_scheduler", lambda n: Fake())
    prov = sp.resolve_cron_scheduler()
    assert prov.name == "fake"


def test_external_provider_falls_back_to_builtin_under_multiplex():
    from cron.scheduler_provider import (
        CronScheduler,
        InProcessCronScheduler,
        scheduler_for_profile_mode,
    )

    class External(CronScheduler):
        @property
        def name(self):
            return "external"

        def start(self, stop_event, **kwargs):
            return None

    external = External()

    assert scheduler_for_profile_mode(external, multiplex_profiles=False) is external
    assert isinstance(
        scheduler_for_profile_mode(external, multiplex_profiles=True),
        InProcessCronScheduler,
    )


# ── Phase 4B: additive hooks (on_jobs_changed / fire_due / reconcile) ────────


def test_hooks_did_not_change_required_surface():
    """The additive hooks must NOT become abstractmethods — the Phase-1 guard
    still holds (required surface is exactly name + start)."""
    from cron.scheduler_provider import CronScheduler

    assert set(CronScheduler.__abstractmethods__) == {"name", "start"}


def test_builtin_inherits_hook_defaults():
    """The built-in inherits no-op defaults for the new hooks (it never needs
    to override them)."""
    from cron.scheduler_provider import InProcessCronScheduler

    p = InProcessCronScheduler()
    assert p.on_jobs_changed() is None
    assert p.reconcile() is None
    # built-in does not override fire_due; it simply isn't called for built-in.
    assert hasattr(p, "fire_due")


def test_fire_due_default_claims_then_runs(monkeypatch):
    """The default fire_due runs the exact owner-bearing CAS snapshot."""
    import cron.jobs as jobs
    import cron.scheduler as sched
    from cron.scheduler_provider import InProcessCronScheduler

    ran = []
    claims = []
    monkeypatch.setattr(
        jobs,
        "claim_job_for_fire",
        lambda jid, **kw: claims.append((jid, kw))
        or {"id": jid, "name": "t", "fire_claim": {"by": "exact-owner"}},
        raising=False,
    )
    monkeypatch.setattr(
        sched,
        "run_one_job",
        lambda job, **kw: ran.append((job["id"], job["fire_claim"]["by"])) or True,
    )

    assert InProcessCronScheduler().fire_due("j1") is True
    assert claims == [("j1", {"return_job": True})]
    assert ran == [("j1", "exact-owner")]


def test_claim_fire_persists_attempt_before_fire_claimed(monkeypatch):
    import cron.executions as executions
    import cron.jobs as jobs
    import cron.scheduler as sched
    from cron.scheduler_provider import InProcessCronScheduler

    events = []
    monkeypatch.setattr(
        jobs,
        "claim_job_for_fire",
        lambda jid, **kwargs: events.append("claim")
        or {"id": jid, "fire_claim": {"by": "owner"}},
    )
    monkeypatch.setattr(
        executions,
        "create_execution",
        lambda jid, source, _create=executions.create_execution:
        events.append("ledger") or _create(jid, source=source),
    )
    monkeypatch.setattr(
        sched,
        "run_one_job",
        lambda job, **kwargs: events.append(("run", job["execution_id"])) or True,
    )

    provider = InProcessCronScheduler()
    claimed = provider.claim_fire("j1")

    assert events == ["ledger", "claim"]
    assert claimed is not None
    assert executions.get_execution(claimed["execution_id"])["status"] == "claimed"
    assert provider.fire_claimed(claimed) is True
    assert events == ["ledger", "claim", ("run", claimed["execution_id"])]


def test_fire_due_forwards_manual_force_to_store_claim(monkeypatch):
    import cron.jobs as jobs
    import cron.scheduler as sched
    from cron.scheduler_provider import InProcessCronScheduler

    claims = []
    monkeypatch.setattr(
        jobs,
        "claim_job_for_fire",
        lambda jid, **kw: claims.append((jid, kw))
        or {"id": jid, "name": "t", "fire_claim": {"by": "manual-owner"}},
    )
    monkeypatch.setattr(sched, "run_one_job", lambda job, **kw: True)

    assert InProcessCronScheduler().fire_due("j1", force=True) is True
    assert claims == [("j1", {"force": True, "return_job": True})]


def test_fire_due_lost_claim_does_not_run(monkeypatch):
    """If the CAS claim is lost (another machine/retry won), fire_due returns
    False and never runs the job."""
    import cron.jobs as jobs
    import cron.scheduler as sched
    from cron.scheduler_provider import InProcessCronScheduler

    ran = []
    monkeypatch.setattr(
        jobs,
        "claim_job_for_fire",
        lambda jid, **kw: False,
        raising=False,
    )
    monkeypatch.setattr(sched, "run_one_job", lambda job, **kw: ran.append(job["id"]) or True)

    assert InProcessCronScheduler().fire_due("j1") is False
    assert ran == []


def test_fire_due_missing_job_does_not_run(monkeypatch):
    """If the job vanished before atomic claim, fire_due does not run it."""
    import cron.jobs as jobs
    import cron.scheduler as sched
    from cron.scheduler_provider import InProcessCronScheduler

    ran = []
    monkeypatch.setattr(
        jobs,
        "claim_job_for_fire",
        lambda jid, **kw: False,
        raising=False,
    )
    monkeypatch.setattr(sched, "run_one_job", lambda job, **kw: ran.append(job["id"]) or True)

    assert InProcessCronScheduler().fire_due("gone") is False
    assert ran == []


# ── F2a: ticker liveness — survival, heartbeat, honest status (#32612, #32895) ──


def test_ticker_survives_baseexception_from_tick():
    """A BaseException (e.g. SystemExit from a provider SDK) raised by tick()
    must NOT kill the ticker loop — it logs and keeps looping (#32612)."""
    from cron.scheduler_provider import InProcessCronScheduler

    calls = []

    def _boom(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise SystemExit("provider SDK called sys.exit")
        return 0

    stop = threading.Event()
    prov = InProcessCronScheduler()
    with patch("cron.scheduler.tick", side_effect=_boom), \
         patch("cron.jobs.record_ticker_heartbeat"):
        t = threading.Thread(target=prov.start, args=(stop,), kwargs={"interval": 0}, daemon=True)
        t.start()
        # Survive the BaseException AND keep ticking: wait for ≥2 calls.
        assert _wait_until(lambda: len(calls) >= 2), \
            "ticker did not keep ticking after the BaseException"
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive(), "ticker thread died on BaseException instead of surviving"
    assert len(calls) >= 2, "ticker did not keep ticking after the BaseException"


def test_ticker_survives_startup_recover_interrupted_failure():
    """A failure in the pre-loop ``recover_interrupted()`` must NOT kill the
    ticker thread — it logs and still enters the tick loop.

    Regression for the 2026-08-11 silent 5h scheduler outage: ``start()`` calls
    ``self.recover_interrupted()`` BEFORE the ``while not stop_event.is_set()``
    loop, so the ``except BaseException`` guard inside that loop did not cover
    it. A transiently half-applied checkout raised

        ImportError: cannot import name 'recover_interrupted_execution_records'
                     from 'cron.executions'

    which killed the daemon thread before its first tick. The gateway parent
    process kept running with NO cron scheduler at all, and — because line 211
    logs "In-process cron scheduler started" immediately BEFORE the fatal call
    — the log read like a clean startup. Zero of 69 jobs fired for 5h08m.
    """
    from cron.scheduler_provider import InProcessCronScheduler

    calls = []
    stop = threading.Event()
    prov = InProcessCronScheduler()

    def _boom():
        raise ImportError(
            "cannot import name 'recover_interrupted_execution_records' "
            "from 'cron.executions'"
        )

    with patch.object(InProcessCronScheduler, "recover_interrupted", side_effect=_boom), \
         patch("cron.scheduler.tick", side_effect=lambda *a, **k: calls.append(1)), \
         patch("cron.jobs.record_ticker_heartbeat"):
        t = threading.Thread(target=prov.start, args=(stop,), kwargs={"interval": 0}, daemon=True)
        t.start()
        assert _wait_until(lambda: len(calls) >= 1), \
            "ticker never reached the tick loop after recover_interrupted() raised"
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive(), "ticker thread died during startup recovery"
    assert len(calls) >= 1, "ticker never ticked after a failing recover_interrupted()"


def test_recover_interrupted_emits_cron_stale_for_each_recovered_run(tmp_path):
    """A run whose owner died without reporting must still reach the event bus.

    CronStaleMonitor's shutdown attribution only fires when the dying gateway
    emits GATEWAY_STOPPED *and* survives long enough for
    ``events/gateway_integration.py:shutdown()`` to flush the staged reports.
    On Windows neither is guaranteed: ``hermes gateway stop`` gives the gateway
    ``_windows_stop_drain_timeout()`` (clamped to 30s at
    ``hermes_cli/gateway_windows.py:1593``) and then force-kills the PID, while
    the flush lives in ``start_gateway()``'s teardown tail — far past the drain.
    A cron mid-LLM-call routinely needs longer than 30s, so the kill lands first
    and the staged CRON_STALE dies with the process. The 2026-08-12 census had 3
    of 6 shutdowns emitting no GATEWAY_STOPPED at all.

    The successor already reconstructs those runs: the execution ledger is
    liveness-verified and ``recover_interrupted_execution_records()`` flips each
    abandoned row to ``unknown`` under a status-guarded UPDATE, so it reports
    each run exactly once no matter how many times recovery runs. That verdict
    was reaching jobs.json and nothing else. Carry it to the bus too.
    """
    from cron.scheduler_provider import InProcessCronScheduler
    from events.bus import EventBus
    from events.schema import EventType, Priority

    bus = EventBus(db_path=tmp_path / "events.db")
    record = {
        "id": "exec-1",
        "job_id": "jobflow-scout",
        "claimed_at": "2026-08-17T17:00:00+00:00",
        "started_at": "2026-08-17T17:00:05+00:00",
        "error": "owner exited before a durable terminal state",
    }

    with patch("cron.executions.recover_interrupted_execution_records",
               return_value=[record]), \
         patch("cron.jobs.mark_job_interrupted", return_value=True), \
         patch("events.gateway_integration.get_bus", return_value=bus):
        recovered = InProcessCronScheduler().recover_interrupted()

    assert recovered == 1, "the ledger recovery itself must still be reported"

    stale = bus.query(event_type=EventType.CRON_STALE)
    assert len(stale) == 1, (
        "the recovered run must reach the event bus — this is the only path "
        "that survives a force-kill past the drain"
    )
    payload = stale[0].payload
    assert payload["job_id"] == "jobflow-scout"
    assert payload["scope"] == "owner_exited", (
        "must be distinguishable from both the graceful 'gateway_stopped' "
        "attribution and the generic wedge alert — the owner died without "
        "saying why, which is a weaker claim than either"
    )
    assert payload["execution_id"] == "exec-1"
    assert stale[0].priority == Priority.NORMAL, (
        "an interrupted run explained by a restart is not a wedge emergency; "
        "mirrors the gateway_stopped attribution's priority"
    )


def test_recover_interrupted_survives_an_unavailable_event_bus(tmp_path):
    """The ledger verdict must land even when the bus cannot take the event.

    ``recover_interrupted()`` runs on the cron ticker's startup path, where a
    raised exception costs the gateway its entire scheduler (the 2026-08-11
    5h08m outage). The bus is best-effort here: recovery is already durable in
    the ledger and jobs.json before the emit is attempted.
    """
    from cron.scheduler_provider import InProcessCronScheduler

    record = {
        "id": "exec-2",
        "job_id": "postgres-sync",
        "claimed_at": "2026-08-17T17:00:00+00:00",
        "started_at": None,
        "error": None,
    }
    marked = []

    with patch("cron.executions.recover_interrupted_execution_records",
               return_value=[record]), \
         patch("cron.jobs.mark_job_interrupted",
               side_effect=lambda *a, **k: marked.append(a) or True), \
         patch("events.gateway_integration.get_bus", return_value=None):
        recovered = InProcessCronScheduler().recover_interrupted()

    assert recovered == 1
    assert marked, "jobs.json must still be stamped when the bus is absent"


def _emit_shutdown_attribution(bus, job_id, *, at=None):
    """Emit the CRON_STALE that CronStaleMonitor's reconstruction would write.

    ``at`` backdates the stored row, mirroring ``_emit_started`` in
    tests/events/subscribers/test_cron_stale_monitor.py.
    """
    from events.schema import EventType, Priority

    eid = bus.emit(
        event_type=EventType.CRON_STALE,
        source="cron-stale-monitor",
        payload={"job_id": job_id, "job_name": job_id, "scope": "gateway_stopped",
                 "age_seconds": 12, "gateway_stopped_event_id": "gs-1",
                 "cron_started_event_id": "cs-1"},
        priority=Priority.NORMAL,
    )
    if at is not None:
        import sqlite3
        conn = sqlite3.connect(str(bus.db_path))
        conn.execute("UPDATE events SET timestamp = ? WHERE event_id = ?", (at, eid))
        conn.commit()
        conn.close()
    return eid


def test_a_run_already_attributed_by_the_shutdown_reconstruction_is_not_reported_twice(tmp_path):
    """The ledger path must stand down when the bus path already reported.

    main's ``517cc56c97`` rebuilds shutdown attributions in
    ``CronStaleMonitor.startup()``, which the gateway runs BEFORE the cron
    ticker starts (``runner.start()`` at gateway/run.py:23733 vs
    ``cron_thread.start()`` at :23818). So on any force-kill that still managed
    to emit GATEWAY_STOPPED — the common case, since the in-flight snapshot is
    taken early in ``_stop_impl_body``, before the drain — that pass has already
    emitted a ``scope='gateway_stopped'`` report by the time recovery runs here.
    Emitting again would give the operator two CRON_STALE events for one run,
    deterministically rather than occasionally.

    The ledger path exists for the deaths that pass CANNOT see: a crash, an OOM,
    a power-off, or a kill landing before the GATEWAY_STOPPED emit.
    """
    from cron.scheduler_provider import InProcessCronScheduler
    from events.bus import EventBus
    from events.schema import EventType

    bus = EventBus(db_path=tmp_path / "events.db")
    _emit_shutdown_attribution(bus, "jobflow-scout")

    record = {
        "id": "exec-1", "job_id": "jobflow-scout",
        "claimed_at": "2026-08-17T13:00:00-04:00",
        "started_at": "2026-08-17T13:00:05-04:00",
        "error": "owner exited before a durable terminal state",
    }

    with patch("cron.executions.recover_interrupted_execution_records",
               return_value=[record]), \
         patch("cron.jobs.mark_job_interrupted", return_value=True), \
         patch("events.gateway_integration.get_bus", return_value=bus):
        InProcessCronScheduler().recover_interrupted()

    owner_exited = [e for e in bus.query(event_type=EventType.CRON_STALE)
                    if e.payload.get("scope") == "owner_exited"]
    assert owner_exited == [], (
        "this run was already attributed by the shutdown reconstruction — a "
        "second report is a duplicate, not extra coverage"
    )


def test_an_attribution_for_an_earlier_run_of_the_same_job_does_not_suppress_a_later_one(tmp_path):
    """The dedupe window is bounded by THIS run's start, in UTC.

    Pins a timezone trap. The execution ledger stamps LOCAL wall-clock with a
    local offset (``cron/executions.py`` uses ``hermes_time.now()``, which
    returns ``datetime.now().astimezone()`` — ``-04:00`` on this box), while
    every bus row is ``datetime.now(timezone.utc).isoformat()`` (``+00:00``,
    events/schema.py:589). ``EventBus.query(since=...)`` compares those as
    STRINGS, so passing ``ran_at`` through unconverted widens the window by the
    UTC offset — four hours here — and an attribution belonging to an EARLIER
    run of the same job silently swallows this one's report.

    Here the earlier attribution is at 14:00Z and this run started at
    12:00-04:00 = 16:00Z. Compared correctly the attribution predates the run
    and is irrelevant; compared as raw strings ``"…T14:00:00+00:00" >=
    "…T12:00:00-04:00"`` matches and wrongly suppresses.
    """
    from cron.scheduler_provider import InProcessCronScheduler
    from events.bus import EventBus
    from events.schema import EventType

    bus = EventBus(db_path=tmp_path / "events.db")
    _emit_shutdown_attribution(bus, "jobflow-scout", at="2026-08-17T14:00:00+00:00")

    record = {
        "id": "exec-2", "job_id": "jobflow-scout",
        "claimed_at": "2026-08-17T12:00:00-04:00",
        "started_at": "2026-08-17T12:00:00-04:00",
        "error": None,
    }

    with patch("cron.executions.recover_interrupted_execution_records",
               return_value=[record]), \
         patch("cron.jobs.mark_job_interrupted", return_value=True), \
         patch("events.gateway_integration.get_bus", return_value=bus):
        InProcessCronScheduler().recover_interrupted()

    owner_exited = [e for e in bus.query(event_type=EventType.CRON_STALE)
                    if e.payload.get("scope") == "owner_exited"]
    assert len(owner_exited) == 1, (
        "the earlier run's attribution predates this run and must not suppress "
        "it — the window floor is this run's start converted to UTC"
    )


def test_ticker_records_heartbeat_each_iteration():
    """The loop records a liveness heartbeat on start and after each tick,
    bumping the success marker only on a clean tick."""
    from cron.scheduler_provider import InProcessCronScheduler

    beats = []  # (success,) per call
    stop = threading.Event()
    prov = InProcessCronScheduler()
    with patch("cron.scheduler.tick", side_effect=lambda *a, **k: 0), \
         patch("cron.jobs.record_ticker_heartbeat",
               side_effect=lambda success=False: beats.append(success)):
        t = threading.Thread(target=prov.start, args=(stop,), kwargs={"interval": 0}, daemon=True)
        t.start()
        # Wait for the pre-loop liveness beat AND at least one successful
        # post-tick beat before stopping (was a fixed 0.2s sleep → flaky).
        assert _wait_until(lambda: any(b is True for b in beats[1:])), \
            "successful tick did not bump success marker"
        stop.set()
        t.join(timeout=5)

    # one pre-loop liveness beat (success=False) + post-tick beats with success=True
    assert len(beats) >= 2, "ticker did not record heartbeats"
    assert beats[0] is False, "pre-loop beat should be liveness-only"
    assert any(b is True for b in beats[1:]), "successful tick did not bump success marker"


def test_failing_tick_records_liveness_but_not_success():
    """A tick that raises bumps the liveness heartbeat but NOT the success
    marker — so status can distinguish 'alive but failing' from 'firing'."""
    from cron.scheduler_provider import InProcessCronScheduler

    beats = []
    stop = threading.Event()
    prov = InProcessCronScheduler()
    with patch("cron.scheduler.tick", side_effect=RuntimeError("every tick fails")), \
         patch("cron.jobs.record_ticker_heartbeat",
               side_effect=lambda success=False: beats.append(success)):
        t = threading.Thread(target=prov.start, args=(stop,), kwargs={"interval": 0}, daemon=True)
        t.start()
        # Wait for the pre-loop beat + at least one post-tick beat (was flaky
        # with a fixed 0.2s sleep under loaded CI).
        assert _wait_until(lambda: len(beats) >= 2), "ticker did not record heartbeats"
        stop.set()
        t.join(timeout=5)

    # every post-tick beat must be success=False (ticks always failed)
    assert len(beats) >= 2
    assert all(b is False for b in beats), "a failing tick wrongly bumped the success marker"


def test_heartbeat_roundtrip_and_age(tmp_path, monkeypatch):
    """record_ticker_heartbeat writes fresh timestamps atomically; the age
    getters read them back as small positive ages."""
    import cron.jobs as jobs

    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(jobs, "TICKER_HEARTBEAT_FILE", cron_dir / "ticker_heartbeat")
    monkeypatch.setattr(jobs, "TICKER_SUCCESS_FILE", cron_dir / "ticker_last_success")

    # No files yet -> unknown (None), NOT "dead"
    assert jobs.get_ticker_heartbeat_age() is None
    assert jobs.get_ticker_success_age() is None

    # liveness-only: heartbeat set, success still unknown
    jobs.record_ticker_heartbeat(success=False)
    hb = jobs.get_ticker_heartbeat_age()
    assert hb is not None and 0.0 <= hb < 5.0
    assert jobs.get_ticker_success_age() is None

    # success: both set
    jobs.record_ticker_heartbeat(success=True)
    ok = jobs.get_ticker_success_age()
    assert ok is not None and 0.0 <= ok < 5.0


def test_structured_ticker_state_roundtrip_is_bounded_and_atomic(tmp_path, monkeypatch):
    """The independent scheduler signal carries phase + bounded authority counts.

    The legacy epoch heartbeat stays intact for older status readers; the
    structured artifact is the watchdog's independent evidence that catch-up is
    progressing rather than merely that the HTTP/event-bus process exists.
    """
    import cron.jobs as jobs

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert jobs.get_ticker_state() is None

    jobs.record_ticker_state(
        "dispatching",
        due_count=3,
        claimed_count=2,
        running_count=1,
        resume_gap_seconds=3600.0,
    )

    state = jobs.get_ticker_state()
    assert state is not None
    assert state["phase"] == "dispatching"
    assert state["ticker_started_at_epoch"] <= state["updated_at_epoch"]
    assert state["last_success_at_epoch"] is None
    assert state["counts"] == {"due": 3, "claimed": 2, "running": 1}
    assert state["resume_gap_seconds"] == 3600.0
    assert 0.0 <= jobs.get_ticker_state_age() < 5.0
    assert not list((tmp_path / "cron").glob(".ticker_state_*.tmp"))


def test_structured_ticker_state_clamps_untrusted_counts(tmp_path, monkeypatch):
    import cron.jobs as jobs

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    jobs.record_ticker_state(
        "completed",
        due_count=-9,
        claimed_count=10**12,
        running_count="malformed",
        resume_gap_seconds=float("inf"),
    )
    state = jobs.get_ticker_state()
    assert state["counts"] == {"due": 0, "claimed": 100_000, "running": 0}
    assert state["resume_gap_seconds"] == 0.0


def test_ticker_authority_due_count_matches_dispatch_admission(monkeypatch):
    """Disabled and resume-barriered rows are not reported as dispatchable due work."""
    import cron.jobs as jobs

    now = jobs._hermes_now()
    overdue = (now - timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(
        jobs,
        "load_jobs",
        lambda: [
            {"id": "due", "enabled": True, "next_run_at": overdue},
            {"id": "disabled", "enabled": False, "next_run_at": overdue},
            {
                "id": "barriered",
                "enabled": True,
                "next_run_at": overdue,
                "resume_barrier": {
                    "reason": "operator hold",
                    "set_at": now.isoformat(),
                    "set_by": "test",
                },
            },
        ],
    )
    monkeypatch.setattr(
        "cron.executions.nonterminal_execution_counts",
        lambda: {"claimed": 2, "running": 1},
    )

    assert jobs.get_ticker_authority_counts() == {
        "due_count": 1,
        "claimed_count": 2,
        "running_count": 1,
    }


def test_ticker_publishes_resume_before_second_catchup_dispatch(monkeypatch):
    """A Modern-Standby wall jump is visible before cron_tick enters catch-up."""
    from cron.scheduler_provider import InProcessCronScheduler

    wall = [1000.0]
    mono = [500.0]
    waits = [0]
    phases = []
    ticks = []

    class _TwoTicks:
        def is_set(self):
            return waits[0] >= 2

        def wait(self, _interval):
            waits[0] += 1
            if waits[0] == 1:
                # Windows monotonic time advances through Modern Standby too.
                # The resume signature is therefore the oversized loop gap,
                # not a wall-minus-monotonic delta (which stays near zero).
                wall[0] += 3600.0
                mono[0] += 3600.0
            return False

    monkeypatch.setattr("cron.scheduler_provider.time.time", lambda: wall[0])
    monkeypatch.setattr("cron.scheduler_provider.time.monotonic", lambda: mono[0])
    monkeypatch.setattr(
        "cron.jobs.record_ticker_state",
        lambda phase, **evidence: phases.append((phase, dict(evidence))),
    )
    monkeypatch.setattr("cron.jobs.record_ticker_heartbeat", lambda **_kwargs: None)
    monkeypatch.setattr("cron.jobs.get_ticker_authority_counts", lambda: {
        "due_count": 4, "claimed_count": 1, "running_count": 1,
    })
    monkeypatch.setattr(
        "cron.scheduler.tick",
        lambda *a, **k: ticks.append(len(phases)) or 0,
    )
    monkeypatch.setattr(InProcessCronScheduler, "recover_interrupted", lambda _self: 0)

    InProcessCronScheduler().start(_TwoTicks(), interval=60)

    assert len(ticks) == 2
    resume_dispatch = [
        evidence for phase, evidence in phases
        if phase == "dispatching" and evidence.get("resume_gap_seconds", 0) > 3000
    ]
    assert len(resume_dispatch) == 1
    assert phases.index(("dispatching", resume_dispatch[0])) < ticks[1]
    assert resume_dispatch[0]["due_count"] == 4


def test_heartbeat_age_detects_staleness(tmp_path, monkeypatch):
    """A heartbeat written far in the past reads back as a large age."""
    import cron.jobs as jobs

    # cron.jobs resolves the heartbeat file dynamically from HERMES_HOME, so
    # point HERMES_HOME at tmp_path and write to the resolved location.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir(parents=True)
    hb = cron_dir / "ticker_heartbeat"

    import time as _t
    hb.write_text(str(_t.time() - 10_000), encoding="utf-8")
    age = jobs.get_ticker_heartbeat_age()
    assert age is not None and age > 9_000


def test_heartbeat_write_failure_is_silent(tmp_path, monkeypatch):
    """A real atomic-write failure must be swallowed AND leave no temp file.

    Point CRON_DIR at a path that cannot be created (its parent is a regular
    file), so ensure_dirs()/mkstemp inside _atomic_write_epoch genuinely fail.
    record_ticker_heartbeat must not raise, and no stray .hb_*.tmp may leak.
    """
    import cron.jobs as jobs

    blocker = tmp_path / "not_a_dir"
    blocker.write_text("i am a file, not a directory")
    # Point HERMES_HOME *under a regular file* so the dynamically-resolved cron
    # dir (<home>/cron) cannot be created and mkdir/mkstemp genuinely fail.
    monkeypatch.setenv("HERMES_HOME", str(blocker))

    jobs.record_ticker_heartbeat(success=True)  # must not raise

    # The write never succeeded, so no heartbeat is recorded...
    assert jobs.get_ticker_heartbeat_age() is None
    # ...and no stray temp file leaked anywhere under tmp_path.
    assert not list(tmp_path.rglob(".hb_*.tmp")), "atomic write leaked a temp file on failure"


def test_cron_status_reports_alive_but_failing(tmp_path, monkeypatch, capsys):
    """cron_status warns when the ticker is alive (fresh heartbeat) but no tick
    has succeeded recently (#32612: alive-but-failing must not look healthy)."""
    import cron.jobs as jobs
    from hermes_cli import cron as cron_cli

    monkeypatch.setattr("hermes_cli.gateway.find_gateway_pids", lambda: [4321])
    monkeypatch.setattr(jobs, "get_ticker_heartbeat_age", lambda: 5.0)      # fresh
    monkeypatch.setattr(jobs, "get_ticker_success_age", lambda: 9_999.0)    # stale
    monkeypatch.setattr("cron.jobs.list_jobs", lambda **k: [])

    cron_cli.cron_status()
    out = capsys.readouterr().out
    assert "no tick has succeeded" in out
    assert "will fire automatically" not in out


def test_cron_status_healthy_when_both_fresh(tmp_path, monkeypatch, capsys):
    import cron.jobs as jobs
    from hermes_cli import cron as cron_cli

    monkeypatch.setattr("hermes_cli.gateway.find_gateway_pids", lambda: [4321])
    monkeypatch.setattr(jobs, "get_ticker_heartbeat_age", lambda: 5.0)
    monkeypatch.setattr(jobs, "get_ticker_success_age", lambda: 5.0)
    monkeypatch.setattr("cron.jobs.list_jobs", lambda **k: [])

    cron_cli.cron_status()
    out = capsys.readouterr().out
    assert "will fire automatically" in out


def test_cron_status_reports_stalled_when_no_heartbeat(tmp_path, monkeypatch, capsys):
    import cron.jobs as jobs
    from hermes_cli import cron as cron_cli

    monkeypatch.setattr("hermes_cli.gateway.find_gateway_pids", lambda: [4321])
    monkeypatch.setattr(jobs, "get_ticker_heartbeat_age", lambda: 9_999.0)  # dead
    monkeypatch.setattr(jobs, "get_ticker_success_age", lambda: 9_999.0)
    monkeypatch.setattr("cron.jobs.list_jobs", lambda **k: [])

    cron_cli.cron_status()
    out = capsys.readouterr().out
    assert "STALLED" in out
    assert "will fire automatically" not in out


# ── F8: runtime backstop — never resolve a stored pair that exfiltrates a key ──


class TestGuardJobCredentialExfil:
    """run_job() must fail closed before provider resolution when a job's stored
    provider/base_url pair would ship a named provider's stored credential to an
    off-host endpoint — covering jobs persisted before the create/update guard
    or written directly to the store (F8 stored-job path; CWE-200/CWE-522)."""

    def test_named_registry_provider_offhost_is_blocked(self):
        import pytest
        from cron.scheduler import _guard_job_credential_exfil

        job = {"id": "j1", "provider": "anthropic",
               "base_url": "https://evil.example/v1"}
        with pytest.raises(RuntimeError) as exc:
            _guard_job_credential_exfil(job)
        assert "blocked for safety" in str(exc.value)


    def test_bare_custom_is_allowed(self):
        from cron.scheduler import _guard_job_credential_exfil

        job = {"id": "j4", "provider": "custom",
               "base_url": "https://anything.example/v1"}
        assert _guard_job_credential_exfil(job) is None

    def test_no_base_url_is_allowed(self):
        from cron.scheduler import _guard_job_credential_exfil

        assert _guard_job_credential_exfil({"id": "j5", "provider": "anthropic"}) is None
        assert _guard_job_credential_exfil({"id": "j6"}) is None

    def test_validator_exception_with_base_url_fails_closed(self, monkeypatch):
        # If the validator/import unexpectedly raises, this last-resort backstop
        # must NOT allow a base_url-bearing job through to provider resolution
        # (it cannot prove the stored pair is safe). Regression for the
        # fail-open `except Exception: err = None` path.
        import pytest
        import tools.cronjob_tools as ct
        from cron.scheduler import _guard_job_credential_exfil

        def _boom(provider, base_url):
            raise RuntimeError("validator blew up")

        monkeypatch.setattr(ct, "_validate_cron_base_url", _boom)
        job = {"id": "j7", "provider": "custom:legit",
               "base_url": "https://evil.example/v1"}
        with pytest.raises(RuntimeError) as exc:
            _guard_job_credential_exfil(job)
        assert "blocked for safety" in str(exc.value)


# ── Multiplex profiles: cron per secondary profile (issue #69377) ─────────


def test_multiplex_ticker_ticks_each_profile_once(tmp_path, monkeypatch):
    """The multiplex cron scheduler calls tick() once per profile home,
    scoped via use_cron_store, so secondary-profile jobs actually fire
    instead of languishing in an unticked store."""
    from cron.scheduler_provider import InProcessCronScheduler

    # Set up two profile directories.
    p1 = tmp_path / "default"
    p2 = tmp_path / "home-ops"
    for d in (p1, p2):
        (d / "cron").mkdir(parents=True)

    profile_homes = [("default", p1), ("home-ops", p2)]

    # Count tick() calls — should be called once per profile per iteration.
    tick_count: list[int] = []

    def _tracking_tick(*args, **kwargs):
        tick_count.append(1)
        return 0

    stop = threading.Event()
    prov = InProcessCronScheduler()

    with patch("cron.scheduler.tick", side_effect=_tracking_tick), \
         patch("cron.jobs.record_ticker_heartbeat", lambda **kw: None):
        t = threading.Thread(
            target=prov.start,
            args=(stop,),
            kwargs={"interval": 0, "profile_homes": profile_homes},
            daemon=True,
        )
        t.start()
        # Wait for at least len(profile_homes) tick calls (one full cycle).
        deadline = time.monotonic() + 10
        while len(tick_count) < len(profile_homes) and time.monotonic() < deadline:
            time.sleep(0.005)
        # Give one more cycle to ensure it keeps ticking.
        deadline = time.monotonic() + 3
        while len(tick_count) < len(profile_homes) * 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive()
    # The ticker called tick() at least once per profile per iteration.
    # With 2 profiles and multiple iterations, we should have seen at least 2 calls.
    assert len(tick_count) >= len(profile_homes), \
        f"Expected >= {len(profile_homes)} tick calls, got {len(tick_count)}"


def test_multiplex_ticker_skips_deleted_profile_from_startup_snapshot(tmp_path):
    """A stale profile_homes entry must not recreate a deleted profile."""
    import cron.jobs as jobs
    from cron.scheduler_provider import InProcessCronScheduler

    default_home = tmp_path / "default"
    (default_home / "cron").mkdir(parents=True)
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    deleted_home = profiles_dir / "deleted"
    profile_homes = [("default", default_home), ("deleted", deleted_home)]

    ticked_homes = []
    stop = threading.Event()

    def _tracking_tick(*args, **kwargs):
        ticked_homes.append(jobs._current_cron_store().cron_dir.parent)
        stop.set()
        return 0

    provider = InProcessCronScheduler()
    with patch("cron.scheduler.tick", side_effect=_tracking_tick):
        thread = threading.Thread(
            target=provider.start,
            args=(stop,),
            kwargs={"interval": 0, "profile_homes": profile_homes},
            daemon=True,
        )
        thread.start()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert ticked_homes == [default_home.resolve()]
    assert not deleted_home.exists()


def test_existing_profile_homes_filters_deleted(tmp_path):
    """The existence filter keeps live homes and drops deleted ones, whether
    entries are (name, path) tuples or bare paths."""
    from cron.scheduler_provider import _existing_profile_homes

    live = tmp_path / "live"
    deleted = tmp_path / "deleted"
    live.mkdir(parents=True)
    # deleted intentionally not created

    as_tuples = _existing_profile_homes([("live", live), ("deleted", deleted)])
    assert [p[0] for p in as_tuples] == ["live"]

    as_paths = _existing_profile_homes([live, deleted])
    assert [p for p in as_paths] == [live]


def _run_multiplex_capture(tmp_path, *, profile_adapters, shared_adapters):
    """Run the multiplex ticker one full cycle and return the ``adapters``
    object passed to ``tick()`` for the default profile and the secondary
    profile (in ``profile_homes`` order: default first, secondary second)."""
    from cron.scheduler_provider import InProcessCronScheduler

    p_default = tmp_path / "default"
    p_sec = tmp_path / "home-ops"
    for d in (p_default, p_sec):
        (d / "cron").mkdir(parents=True)
    profile_homes = [("default", p_default), ("home-ops", p_sec)]

    captured: list = []  # adapters seen per tick call; order follows profile_homes

    def _capturing_tick(*args, **kwargs):
        captured.append(kwargs.get("adapters"))
        return 0

    stop = threading.Event()
    prov = InProcessCronScheduler()
    with patch("cron.scheduler.tick", side_effect=_capturing_tick), \
         patch("cron.jobs.record_ticker_heartbeat", lambda **kw: None):
        t = threading.Thread(
            target=prov.start,
            args=(stop,),
            kwargs={
                "interval": 0,
                "profile_homes": profile_homes,
                "adapters": shared_adapters,
                "profile_adapters": profile_adapters,
                "default_profile": "default",
            },
            daemon=True,
        )
        t.start()
        deadline = time.monotonic() + 10
        while len(captured) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        stop.set()
        t.join(timeout=5)

    assert not t.is_alive()
    assert len(captured) >= 2, f"expected >= 2 tick calls, got {len(captured)}"
    return captured[0], captured[1]  # (default, secondary) of the first cycle


def test_multiplex_default_profile_uses_shared_adapters(tmp_path):
    """The default profile's cron is delivered via the shared ``adapters`` set
    (which belongs to the default profile)."""
    shared = {"kind": "shared"}
    default_ad, _ = _run_multiplex_capture(
        tmp_path, profile_adapters={"home-ops": {"kind": "secondary"}},
        shared_adapters=shared,
    )
    assert default_ad is shared


def test_multiplex_connected_secondary_uses_its_own_adapters(tmp_path):
    """A connected secondary is delivered via ITS OWN adapters, not the shared
    default-profile set."""
    shared = {"kind": "shared"}
    sec = {"kind": "secondary"}
    default_ad, sec_ad = _run_multiplex_capture(
        tmp_path, profile_adapters={"home-ops": sec}, shared_adapters=shared,
    )
    assert default_ad is shared
    assert sec_ad is sec


def test_multiplex_empty_secondary_does_not_fall_back_to_shared(tmp_path):
    """A secondary whose adapter map is present-but-empty (its bot has not
    connected yet) must NOT fall back to the default profile's shared adapters
    — otherwise its cron output ships through the wrong bot. It receives an
    empty adapter set and simply does not deliver this tick."""
    shared = {"kind": "shared"}
    default_ad, sec_ad = _run_multiplex_capture(
        tmp_path, profile_adapters={"home-ops": {}}, shared_adapters=shared,
    )
    assert default_ad is shared
    assert sec_ad is not shared
    assert not sec_ad  # empty → no delivery, not the default bot


def test_multiplex_missing_secondary_does_not_fall_back_to_shared(tmp_path):
    """A secondary absent from profile_adapters entirely (its adapter map has
    not been created yet) also must not fall back to the shared adapters."""
    shared = {"kind": "shared"}
    default_ad, sec_ad = _run_multiplex_capture(
        tmp_path, profile_adapters={}, shared_adapters=shared,
    )
    assert default_ad is shared
    assert sec_ad is not shared
    assert not sec_ad


def test_multiplex_ticker_isolates_profile_failures(tmp_path):
    """A failing profile's tick must not skip healthy siblings in the same
    cycle, nor darken their status (#74878)."""
    from cron.jobs import get_ticker_last_error, record_ticker_error, use_cron_store
    from cron.scheduler_provider import InProcessCronScheduler
    from hermes_constants import get_hermes_home

    failing_home = tmp_path / "failing"
    healthy_home = tmp_path / "healthy"
    for home in (failing_home, healthy_home):
        (home / "cron").mkdir(parents=True)
        with use_cron_store(home):
            record_ticker_error("RuntimeError: stale failure")

    stop = threading.Event()
    tick_homes: list[str] = []

    def _tick(*args, **kwargs):
        home = str(get_hermes_home())
        tick_homes.append(home)
        if home == str(failing_home):
            raise RuntimeError("profile-local failure")
        stop.set()
        return 0

    provider = InProcessCronScheduler()
    with patch("cron.scheduler.tick", side_effect=_tick):
        thread = threading.Thread(
            target=provider.start,
            args=(stop,),
            kwargs={
                "interval": 0,
                "profile_homes": [("failing", failing_home), ("healthy", healthy_home)],
            },
            daemon=True,
        )
        thread.start()
        thread.join(timeout=5)
        stop.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert str(healthy_home) in tick_homes, "healthy sibling was skipped"
    assert not (failing_home / "cron" / "ticker_last_success").exists()
    assert (healthy_home / "cron" / "ticker_last_success").exists()
    with use_cron_store(failing_home):
        assert get_ticker_last_error() == "RuntimeError: profile-local failure"
    with use_cron_store(healthy_home):
        assert get_ticker_last_error() is None


def test_multiplex_recovery_isolates_profile_failures(tmp_path):
    """A startup-recovery error in one profile's ledger must not kill the
    ticker thread before it ever ticks (#74878)."""
    import sqlite3

    from cron.scheduler_provider import InProcessCronScheduler
    from hermes_constants import get_hermes_home

    failing_home = tmp_path / "failing"
    healthy_home = tmp_path / "healthy"
    for home in (failing_home, healthy_home):
        (home / "cron").mkdir(parents=True)

    stop = threading.Event()
    recovery_homes: list[str] = []
    tick_homes: list[str] = []

    def _recover():
        home = str(get_hermes_home())
        recovery_homes.append(home)
        if home == str(failing_home):
            raise sqlite3.OperationalError("unable to open database file")
        return 0

    def _tick(*args, **kwargs):
        tick_homes.append(str(get_hermes_home()))
        if len(tick_homes) >= 2:
            stop.set()
        return 0

    provider = InProcessCronScheduler()
    with (
        patch.object(provider, "recover_interrupted", side_effect=_recover),
        patch("cron.scheduler.tick", side_effect=_tick),
    ):
        thread = threading.Thread(
            target=provider.start,
            args=(stop,),
            kwargs={
                "interval": 0,
                "profile_homes": [("failing", failing_home), ("healthy", healthy_home)],
            },
            daemon=True,
        )
        thread.start()
        thread.join(timeout=5)
        stop.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert recovery_homes == [str(failing_home), str(healthy_home)]
    # The failing profile stays in rotation: its ledger may still hold jobs.
    assert set(tick_homes) == {str(failing_home), str(healthy_home)}
