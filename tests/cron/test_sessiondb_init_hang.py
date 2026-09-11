"""Regression test for a hung SessionDB() init permanently wedging a cron job.

Real-world incident: a cron job's ``SessionDB()`` construction inside
``run_job`` blocked forever (a wedged sqlite3.connect against state.db, no
other process holding a competing lock by the time it was diagnosed). Because
that call had no timeout of its own — unlike the agent's run_conversation,
which is already bounded by HERMES_CRON_TIMEOUT — the worker thread submitted
by ``_submit_with_guard`` never returned. Its ``finally`` block, which is the
only thing that discards the job ID from ``_running_job_ids``, never ran.
Every later tick logged "already running — skipping" and the job never fired
again until the whole gateway process was restarted days later.

These tests prove ``run_job`` now bounds the SessionDB init with its own
timeout (HERMES_CRON_SESSION_DB_TIMEOUT, default 10s) so a hang there can
never again wedge the job past that bound, and — end to end — that the
dispatch guard is released and the job becomes dispatchable again afterward.

Assertions capture the timeout passed to ``Future.result(timeout=...)`` (and
optionally force an immediate ``TimeoutError``) — no wall-clock waits, so the
suite stays free of timing flakes under parallel load.
"""

import concurrent.futures
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cron.scheduler import run_job

# Hold the real class: patching cron.scheduler.concurrent.futures.ThreadPoolExecutor
# also replaces concurrent.futures.ThreadPoolExecutor (same module object).
_REAL_TPE = concurrent.futures.ThreadPoolExecutor

_RUNTIME = {
    "api_key": "test-key",
    "base_url": "https://example.invalid/v1",
    "provider": "openrouter",
    "api_mode": "chat_completions",
}


def _session_db_executor(timeouts: list, *, instant_timeout: bool = True):
    """Wrap ``ThreadPoolExecutor`` so SessionDB's ``result(timeout=...)`` is observable.

    ``run_job`` is the only caller that passes a timeout to ``Future.result`` on
    this path (``submit(SessionDB).result(timeout=...)``). Other pools used by
    ``tick`` / the agent inactivity watchdog call ``result()`` with no timeout
    and are left alone. When ``instant_timeout`` is True, the timed wait raises
    immediately instead of sleeping — the production hang path without a clock.
    """

    def factory(max_workers=1, *args, **kwargs):
        real = _REAL_TPE(max_workers=max_workers)
        orig_submit = real.submit

        def submit(fn, *a, **k):
            fut = orig_submit(fn, *a, **k)
            orig_result = fut.result

            def result(*ra, **rk):
                timeout = ra[0] if ra else rk.get("timeout")
                if timeout is not None:
                    timeouts.append(timeout)
                    if instant_timeout:
                        raise concurrent.futures.TimeoutError()
                return orig_result(*ra, **rk)

            fut.result = result
            return fut

        real.submit = submit
        return real

    return factory


class TestSessionDbInitTimeout:
    def test_sessiondb_init_preserves_multiplex_profile_context(
        self, tmp_path, monkeypatch
    ):
        """The timeout worker must construct SessionDB under the active profile."""
        from hermes_constants import (
            get_hermes_home,
            reset_hermes_home_override,
            set_hermes_home_override,
        )

        default_home = tmp_path / "default"
        profile_home = tmp_path / "profiles" / "jobsearch"
        monkeypatch.setenv("HERMES_HOME", str(default_home))
        observed_homes = []
        fake_db = MagicMock()

        def make_session_db(*args, **kwargs):
            observed_homes.append(get_hermes_home())
            return fake_db

        job = {"id": "profile-sessiondb", "name": "test", "prompt": "hello"}
        profile_token = set_hermes_home_override(profile_home)
        try:
            with patch("cron.scheduler._hermes_home", None), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire", side_effect=make_session_db), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value=_RUNTIME,
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "ok"}
                mock_agent_cls.return_value = mock_agent

                success, _output, final_response, error = run_job(job)
        finally:
            reset_hermes_home_override(profile_token)

        assert success is True
        assert error is None
        assert final_response == "ok"
        assert observed_homes == [profile_home]

    def test_run_job_does_not_hang_when_sessiondb_init_wedges(self, tmp_path, monkeypatch):
        """run_job proceeds without a session store when SessionDB init times out."""
        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "0.2")
        job = {"id": "wedged-sessiondb", "name": "test", "prompt": "hello"}
        timeouts: list = []

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire"), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value=_RUNTIME,
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls, \
             patch(
                 "cron.scheduler.concurrent.futures.ThreadPoolExecutor",
                 side_effect=_session_db_executor(timeouts),
             ):
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            success, output, final_response, error = run_job(job)

        # Env-resolved bound was passed to Future.result — not the 10s default,
        # and not an unbounded call.
        assert timeouts == [0.2]
        assert success is True
        assert final_response == "ok"
        assert mock_agent_cls.call_args.kwargs["session_db"] is None

    def test_timeout_log_renders_the_fractional_bound(self, tmp_path, monkeypatch, caplog):
        """The timeout message must print the ACTUAL bound, not round it to 0.

        ``%.0f`` rendered a 0.2s bound as "did not return within 0s". That is
        not merely imprecise — 0 is this very function's sentinel for
        *unlimited* (see the ``if _session_db_timeout > 0`` branch), so an
        operator reading that line concludes no timeout was in force at the
        exact moment one fired. Observed live 2026-08-11.
        """
        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "0.2")
        wedge = _WedgedSessionDb()
        job = {"id": "wedged-sessiondb", "name": "test", "prompt": "hello"}

        try:
            with patch("cron.scheduler._hermes_home", tmp_path), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire", side_effect=wedge), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value=_RUNTIME,
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls:
                mock_agent_cls.return_value.run_conversation.return_value = {
                    "final_response": "ok"
                }
                with caplog.at_level("ERROR"):
                    run_job(job)

        finally:
            wedge.release.set()

        rendered = [
            rec.getMessage()
            for rec in caplog.records
            if "SessionDB init did not return" in rec.getMessage()
        ]
        assert rendered, (
            "Expected the SessionDB init timeout to be logged; got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )
        line = rendered[0]
        assert "0.2s" in line, f"Timeout bound not rendered faithfully: {line!r}"
        # The specific inversion: 0 is the sentinel for UNLIMITED, so this
        # exact substring tells the operator the opposite of what happened.
        assert "within 0s" not in line, (
            f"Sub-second bound rendered as the unlimited sentinel: {line!r}"
        )

    def test_invalid_timeout_env_falls_back_to_default(self, tmp_path, monkeypatch, caplog):
        """A malformed HERMES_CRON_SESSION_DB_TIMEOUT logs a warning and still
        bounds the call (mirrors HERMES_CRON_TIMEOUT's own fallback)."""
        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "not-a-number")
        fake_db = MagicMock()
        job = {"id": "bad-timeout-env", "name": "test", "prompt": "hello"}
        timeouts: list = []

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value=_RUNTIME,
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls, \
             patch(
                 "cron.scheduler.concurrent.futures.ThreadPoolExecutor",
                 side_effect=_session_db_executor(timeouts, instant_timeout=False),
             ):
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            with caplog.at_level("WARNING"):
                success, output, final_response, error = run_job(job)

        # Invalid env → fall back to default 10s bound (still passed to result).
        assert timeouts == [10.0]
        assert success is True
        assert mock_agent_cls.call_args.kwargs["session_db"] is fake_db
        assert any(
            "HERMES_CRON_SESSION_DB_TIMEOUT" in rec.message
            for rec in caplog.records
        ), f"Expected warning about invalid timeout env var; got: {[r.message for r in caplog.records]}"

    def test_timeout_resolved_from_config_yaml(self, tmp_path, monkeypatch):
        """cron.session_db_timeout_seconds in config.yaml is respected when
        the env var is not set — the canonical config-first resolution path."""
        import yaml

        monkeypatch.delenv("HERMES_CRON_SESSION_DB_TIMEOUT", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"cron": {"session_db_timeout_seconds": 0.2}})
        )
        job = {"id": "config-timeout", "name": "test", "prompt": "hello"}
        timeouts: list = []

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire"), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value=_RUNTIME,
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls, \
             patch(
                 "cron.scheduler.concurrent.futures.ThreadPoolExecutor",
                 side_effect=_session_db_executor(timeouts),
             ):
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            success, output, final_response, error = run_job(job)

        # Config value was passed through — not the 10s default.
        assert timeouts == [0.2]
        assert success is True
        assert mock_agent_cls.call_args.kwargs["session_db"] is None


class TestNoTimeoutIsRenderedAsTheUnlimitedSentinel:
    """Sweep for the sibling instances of the ``%.0f``-on-a-timeout defect.

    ``run_job``'s three timeouts all document ``0 = unlimited``
    (HERMES_CRON_SESSION_DB_TIMEOUT at the ``> 0`` branch,
    HERMES_CRON_TIMEOUT, HERMES_CRON_HARD_TIMEOUT). Any renderer that
    truncates toward zero therefore turns a live sub-second bound into the
    sentinel meaning *no bound* — the operator reads the opposite of what
    happened.

    The wall-clock and inactivity messages are emitted from a monitor thread
    that a unit test cannot reach cheaply, so this asserts on the format
    strings themselves. Anchored on the message text, not line numbers, so it
    survives edits above it.
    """

    @staticmethod
    def _source() -> str:
        import cron.scheduler

        return Path(cron.scheduler.__file__).read_text(encoding="utf-8")

    def test_inactivity_owner_preserves_fractional_log_and_exception(self, caplog):
        from cron.scheduler import _raise_inactivity_timeout
        agent = MagicMock()
        agent.get_activity_summary.return_value = {"seconds_since_activity": 0.3}
        with pytest.raises(TimeoutError) as raised:
            _raise_inactivity_timeout(agent, "fractional", 0.2, already_interrupted=True)
        assert "idle for 0.3s" in str(raised.value)
        assert "limit 0.2s" in str(raised.value)
        assert "idle for 0.3s" in caplog.text
        assert "inactivity limit 0.2s" in caplog.text

    @pytest.mark.parametrize(
        "anchor",
        [
            "SessionDB init did not return",
            "exceeded wall-clock limit",
            "idle for",
        ],
    )
    def test_timeout_render_does_not_truncate_to_zero(self, anchor):
        source = self._source()
        offenders = [
            line.strip()
            for line in source.splitlines()
            if anchor in line and "%.0f" in line
        ]
        assert not offenders, (
            f"{anchor!r} still renders a timeout with %.0f, which prints any "
            f"sub-second bound as the '0 = unlimited' sentinel: {offenders}"
        )

    @pytest.mark.parametrize(
        "expr",
        ["int(_cron_hard_limit)", "int(_cron_inactivity_limit)"],
    )
    def test_raised_timeout_message_does_not_truncate_the_limit(self, expr):
        """The TimeoutError text an operator sees in the job record has the
        same hazard as the log line it accompanies."""
        assert expr not in self._source(), (
            f"{expr} truncates a sub-second limit to the '0 = unlimited' "
            "sentinel in the raised TimeoutError message"
        )


class TestDispatchGuardReleasedAfterHang:
    """End-to-end: the real bug symptom was every later tick silently
    skipping the job forever. Confirm the fix actually clears that path."""

    def test_guard_is_released_and_job_refires_after_sessiondb_hang(self, tmp_path, monkeypatch):
        import cron.scheduler as sched

        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "0.2")
        sched._parallel_pool = None
        sched._parallel_pool_max_workers = None
        sched._running_job_ids.clear()

        job = {
            "id": "guard-sessiondb-hang",
            "name": "guard-sessiondb-hang",
            "prompt": "hello",
            "schedule": "every 5m",
            "enabled": True,
            "next_run_at": "2020-01-01T00:00:00",
            "deliver": "local",
        }
        timeouts: list = []

        try:
            with patch("cron.scheduler._hermes_home", tmp_path), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire"), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value=_RUNTIME,
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls, \
                 patch(
                     "cron.scheduler.concurrent.futures.ThreadPoolExecutor",
                     side_effect=_session_db_executor(timeouts),
                 ), \
                 patch.object(sched, "get_due_and_skipped_jobs", return_value=([job], [])), \
                 patch.object(sched, "claim_job_for_fire", return_value=True), \
                 patch.object(sched, "save_job_output", return_value="/tmp/out"), \
                 patch.object(sched, "mark_job_run"), \
                 patch.object(sched, "_deliver_result", return_value=None):
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "ok"}
                mock_agent_cls.return_value = mock_agent

                n = sched.tick(verbose=False)  # sync=True by default: waits for the job
                assert n == 1
                assert timeouts == [0.2]

                # Without the fix this would still contain the job ID forever.
                assert "guard-sessiondb-hang" not in sched.get_running_job_ids()

                # A second tick can dispatch the same job again — before the
                # fix this would log "already running — skipping" and
                # return 0.
                n2 = sched.tick(verbose=False)
                assert n2 == 1
        finally:
            sched._running_job_ids.discard("guard-sessiondb-hang")
            sched._shutdown_parallel_pool()


# ===========================================================================
# Bug #72782: late SessionDB result leaks FDs after timeout abandonment
# ===========================================================================

class TestCloseLateSessionDbResult:
    """Unit tests for the done-callback that closes a SessionDB whose
    constructor completed after run_job's timeout."""

    def test_closes_db_from_completed_future(self):
        """A completed future holding a SessionDB is closed."""
        import concurrent.futures
        from cron.scheduler import _close_late_session_db_result

        mock_db = MagicMock()
        fut = concurrent.futures.Future()
        fut.set_result(mock_db)

        _close_late_session_db_result(fut)

        mock_db.close.assert_called_once()

    def test_safe_when_result_is_none(self):
        """No error when the future's result is None."""
        import concurrent.futures
        from cron.scheduler import _close_late_session_db_result

        fut = concurrent.futures.Future()
        fut.set_result(None)
        _close_late_session_db_result(fut)  # must not raise

    def test_safe_when_future_raised(self):
        """No error when the future itself raised (e.g. connect failed)."""
        import concurrent.futures
        from cron.scheduler import _close_late_session_db_result

        fut = concurrent.futures.Future()
        fut.set_exception(RuntimeError("connect failed"))
        _close_late_session_db_result(fut)  # must not raise


class TestLateSessionDbClosedAfterTimeout:
    """End-to-end: when SessionDB init times out but later completes inside the
    abandoned worker, the orphaned result must be closed (#72782)."""

    def test_late_session_db_result_is_closed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "0.2")
        never_set = threading.Event()
        late_db_holder = []  # captures the SessionDB returned by the late init

        def _hanging_then_capture():
            never_set.wait(timeout=30)
            db = MagicMock()
            late_db_holder.append(db)
            return db

        job = {"id": "late-close-test", "name": "test", "prompt": "hello"}

        try:
            with patch("cron.scheduler._hermes_home", tmp_path), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire", side_effect=_hanging_then_capture), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value={
                         "api_key": "test-key",
                         "base_url": "https://example.invalid/v1",
                         "provider": "openrouter",
                         "api_mode": "chat_completions",
                     },
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "ok"}
                mock_agent_cls.return_value = mock_agent

                success, output, final_response, error = run_job(job)
                # run_job returned promptly after the timeout; session_db is None
                assert success is True

                # Release the hanging init so the abandoned worker completes.
                never_set.set()
                # Wait for the done-callback to fire and close the late result.
                for _ in range(50):
                    if late_db_holder and late_db_holder[0].close.called:
                        break
                    time.sleep(0.1)
        finally:
            never_set.set()

        assert len(late_db_holder) == 1, "SessionDB() should have completed once"
        late_db_holder[0].close.assert_called_once(), (
            "The SessionDB that completed after the timeout must be closed by "
            "the done-callback — otherwise its SQLite FDs leak until process exit (#72782)"
        )


# ===========================================================================
# #96290: gated runs must not open the session store at all
# ===========================================================================

class TestSessionDbInitAfterEarlyReturns:
    """SessionDB init moved AFTER the wake-gate / prompt-validation early
    returns (#96290): a run that never reaches the agent must never open
    state.db, so there is no handle for a gated return path to abandon."""

    def test_wake_gate_false_never_opens_session_db(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HERMES_CRON_SESSION_DB_TIMEOUT", raising=False)
        job = {
            "id": "gated-no-db",
            "name": "gated-no-db",
            "prompt": "hello",
            "script": "gate.py",
        }

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire") as mock_db_cls, \
             patch(
                 "cron.scheduler._run_job_script_with_claim_heartbeat",
                 return_value=(True, '{"wakeAgent": false}'),
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            success, output, final_response, error = run_job(job)

        assert success is True
        mock_db_cls.assert_not_called()
        mock_agent_cls.assert_not_called()


_HANG_SECONDS = 30.0

class _WedgedSessionDb:
    """Stand-in for ``hermes_state.SessionDB()`` that blocks until released.

    Like the real incident's wedged ``sqlite3.connect``, but bounded so the
    test process can still exit cleanly once the assertions are done.

    ``returned`` is the load-independent evidence these tests run on. It is set
    ONLY if this call ran to completion — i.e. if ``run_job`` sat and waited the
    wedge out. If ``run_job``'s own timeout did its job, ``run_job`` returns
    while this call is still parked inside ``wait()`` and ``returned`` is still
    clear.

    This replaces a wall-clock assertion (``elapsed < N``) that repeatedly
    failed on correct code. ``run_job`` does a lot besides construct a
    SessionDB, all of it inside the measured region, and that cost scales with
    machine load: 6.83s standalone on 2026-08-11 against a 5.0s budget, and
    18.39s in the shared checkout with a sibling suite running — while the
    third test in this file, identical shape and identical 0.2s bound but
    running warm on an idle box, measured 1.8s. Every one of those runs had a
    working timeout. A stopwatch cannot separate "the wedge was abandoned" from
    "the machinery was slow"; this flag can, exactly, at any load.
    """

    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.returned = threading.Event()

    def __call__(self, *args, **kwargs):
        self.entered.set()
        self.release.wait(timeout=_HANG_SECONDS)
        self.returned.set()
        return MagicMock()


class TestSessionDbInitTimeoutRealWorker:

    def test_run_job_does_not_hang_when_sessiondb_init_wedges(self, tmp_path, monkeypatch):
        """run_job returns promptly even if SessionDB() never returns."""
        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "0.2")
        wedge = _WedgedSessionDb()
        job = {"id": "wedged-sessiondb", "name": "test", "prompt": "hello"}

        try:
            with patch("cron.scheduler._hermes_home", tmp_path), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire", side_effect=wedge), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value={
                         "api_key": "test-key",
                         "base_url": "https://example.invalid/v1",
                         "provider": "openrouter",
                         "api_mode": "chat_completions",
                     },
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "ok"}
                mock_agent_cls.return_value = mock_agent

                success, output, final_response, error = run_job(job)
                # Sample BEFORE the finally releases the wedge.
                assert wedge.entered.is_set(), "registry acquisition never started"
                abandoned = not wedge.returned.is_set()
        finally:
            wedge.release.set()

        # run_job gave up on the init instead of waiting it out: the stand-in
        # was still parked inside its wait() when run_job returned.
        assert abandoned, (
            "run_job waited out the wedged SessionDB init instead of "
            "abandoning it at the 0.2s HERMES_CRON_SESSION_DB_TIMEOUT"
        )
        # The run still completes successfully without a session store.
        assert success is True
        assert final_response == "ok"
        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["session_db"] is None

    def test_timeout_resolved_from_config_yaml(self, tmp_path, monkeypatch):
        """cron.session_db_timeout_seconds in config.yaml is respected when
        the env var is not set — the canonical config-first resolution path."""
        import yaml

        monkeypatch.delenv("HERMES_CRON_SESSION_DB_TIMEOUT", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"cron": {"session_db_timeout_seconds": 0.2}})
        )
        wedge = _WedgedSessionDb()
        job = {"id": "config-timeout", "name": "test", "prompt": "hello"}

        try:
            with patch("cron.scheduler._hermes_home", tmp_path), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire", side_effect=wedge), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value={
                         "api_key": "test-key",
                         "base_url": "https://example.invalid/v1",
                         "provider": "openrouter",
                         "api_mode": "chat_completions",
                     },
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls:
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "ok"}
                mock_agent_cls.return_value = mock_agent

                success, output, final_response, error = run_job(job)
                # Sample BEFORE the finally releases the wedge.
                assert wedge.entered.is_set(), "registry acquisition never started"
                abandoned = not wedge.returned.is_set()
        finally:
            wedge.release.set()

        # Config value 0.2s bounded the init, not the 10s default: run_job
        # returned while the stand-in was still parked in its wait().
        assert abandoned, (
            "run_job waited out the wedged SessionDB init instead of "
            "abandoning it at cron.session_db_timeout_seconds=0.2"
        )
        assert success is True
        assert mock_agent_cls.call_args.kwargs["session_db"] is None


class TestDispatchGuardReleasedAfterHangRealWorker:

    def test_guard_is_released_and_job_refires_after_sessiondb_hang(self, tmp_path, monkeypatch):
        import cron.scheduler as sched

        monkeypatch.setenv("HERMES_CRON_SESSION_DB_TIMEOUT", "0.2")
        sched._parallel_pool = None
        sched._parallel_pool_max_workers = None
        sched._running_job_ids.clear()

        wedge = _WedgedSessionDb()
        job = {
            "id": "guard-sessiondb-hang",
            "name": "guard-sessiondb-hang",
            "prompt": "hello",
            "schedule": "every 5m",
            "enabled": True,
            "next_run_at": "2020-01-01T00:00:00",
            "deliver": "local",
        }

        try:
            with patch("cron.scheduler._hermes_home", tmp_path), \
                 patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
                 patch("hermes_cli.env_loader.load_hermes_dotenv"), \
                 patch("hermes_cli.env_loader.reset_secret_source_cache"), \
                 patch("hermes_state_registry.acquire", side_effect=wedge), \
                 patch(
                     "hermes_cli.runtime_provider.resolve_runtime_provider",
                     return_value={
                         "api_key": "test-key",
                         "base_url": "https://example.invalid/v1",
                         "provider": "openrouter",
                         "api_mode": "chat_completions",
                     },
                 ), \
                 patch("run_agent.AIAgent") as mock_agent_cls, \
                 patch.object(sched, "get_due_and_skipped_jobs", return_value=([job], [])), \
                 patch.object(sched, "claim_job_for_fire", return_value=True), \
                 patch.object(sched, "save_job_output", return_value="/tmp/out"), \
                 patch.object(sched, "mark_job_run"), \
                 patch.object(sched, "_deliver_result", return_value=None):
                mock_agent = MagicMock()
                mock_agent.run_conversation.return_value = {"final_response": "ok"}
                mock_agent_cls.return_value = mock_agent

                n = sched.tick(verbose=False)  # sync=True by default: waits for the job
                assert n == 1

                # Without the fix this would still contain the job ID forever.
                assert "guard-sessiondb-hang" not in sched.get_running_job_ids()

                # A second tick can dispatch the same job again — before the
                # fix this would log "already running — skipping" and
                # return 0.
                n2 = sched.tick(verbose=False)
                assert n2 == 1
        finally:
            wedge.release.set()
            sched._running_job_ids.discard("guard-sessiondb-hang")
            sched._shutdown_parallel_pool()
