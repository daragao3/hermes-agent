"""Frozen local Windows lifecycle carries, isolated during upstream integration."""

import pytest

import hermes_cli.gateway as gateway

import hermes_cli.gateway_windows as gateway_windows


def test_generated_launchers_pin_install_and_preserve_spawn_attribution(tmp_path, monkeypatch):
    installed = tmp_path / "installed"
    installed.mkdir()
    monkeypatch.setattr(gateway_windows, "find_installed_package_root", lambda: installed)
    monkeypatch.setattr(gateway_windows, "installed_package_root", lambda: installed)
    monkeypatch.setattr(
        gateway_windows, "_resolve_detached_python",
        lambda p: (str(tmp_path / "python.exe"), tmp_path / "venv", []),
    )
    assert gateway_windows._stable_gateway_working_dir(tmp_path / "transient") == str(installed)
    args = (str(tmp_path / "python.exe"), str(installed), str(tmp_path / "profile"), "")
    cmd = gateway_windows._build_gateway_cmd_script(*args)
    vbs = gateway_windows._build_gateway_vbs_script(*args)
    startup = gateway_windows._build_startup_launcher(tmp_path / "gateway.cmd")
    assert str(installed) in cmd and str(installed) in vbs
    assert "pythonw.exe" not in cmd and "pythonw.exe" not in vbs
    assert "--replace" not in cmd and "--replace" not in vbs
    assert "HERMES_SUPERVISED_CHILD" in cmd and "HERMES_SUPERVISED_CHILD" in vbs
    assert "windows-task-script" in cmd and "windows-task-script" in vbs
    assert 'If Len(env.Item("HERMES_GATEWAY_SPAWN_SITE")) = 0 Then' in vbs
    assert "windows-startup-folder" in startup


def test_detached_spawn_retains_breakaway_retry_and_scoped_reason(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(gateway_windows, "_build_gateway_argv", lambda: (
        ["python.exe", "-m", "hermes_cli.main", "gateway", "run"],
        str(tmp_path), {"HERMES_HOME": str(tmp_path)},
    ))
    monkeypatch.setenv(gateway_windows.GATEWAY_SPAWN_SITE_ENV, "parent-site")

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        if len(calls) == 1:
            raise PermissionError("fixture job forbids breakaway")
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(gateway_windows.subprocess, "Popen", popen)
    assert gateway_windows._spawn_detached(reason="cli:restart") == 12345
    assert len(calls) == 2
    for _, kwargs in calls:
        assert kwargs["env"]["HERMES_HOME"] == str(tmp_path)
        assert kwargs["env"][gateway_windows.GATEWAY_SPAWN_SITE_ENV] == "cli:restart"
        assert kwargs["stdout"].closed
        assert kwargs["creationflags"] & 0x08000000  # CREATE_NO_WINDOW
        assert not kwargs["creationflags"] & 0x00000008  # DETACHED_PROCESS
    assert calls[0][1]["creationflags"] & 0x01000000
    assert not calls[1][1]["creationflags"] & 0x01000000

def test_restart_does_not_spawn_on_top_of_a_concurrent_starter(monkeypatch, capsys):
    """A gateway raced in during the drain window must not get a twin.

    ``_wait_for_gateway_absent`` already proved the OLD gateway is gone, so a
    live PID at this point is a replacement started by the watchdog or
    laptop-start.ps1. Before this guard, restart() spawned unconditionally and
    the loser of the runtime-lock race exited nonzero -- which reads as a
    failed restart even though the survivor is healthy.
    """
    calls = []

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(
        gateway_windows, "_wait_for_gateway_absent", lambda **kwargs: True
    )
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [33333])
    monkeypatch.setattr(
        gateway_windows,
        "_spawn_detached",
        lambda *a, **k: pytest.fail("must not spawn on top of a live gateway"),
    )
    monkeypatch.setattr(
        gateway_windows,
        "_wait_for_gateway_ready",
        lambda **kwargs: pytest.fail("must return before the readiness wait"),
    )

    gateway_windows.restart()

    assert calls == ["stop"]
    out = capsys.readouterr().out
    assert "33333" in out
    assert "not spawning a second one" in out

def test_force_terminate_survives_a_taskkill_timeout(monkeypatch):
    """A ``TimeoutExpired`` from the kill primitive must not abort the sweep.

    ``subprocess.TimeoutExpired`` is a ``SubprocessError``, NOT an ``OSError``
    — so the ``except OSError`` arm below it never caught this, and a slow kill
    took the whole stop/restart chain down with it (2026-08-11 outage).
    """
    import subprocess

    from gateway import status as status_mod

    monkeypatch.setattr(status_mod, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(status_mod, "get_process_start_time", lambda pid: 123.0)
    monkeypatch.setattr(gateway_windows, "write_diag", lambda *a, **k: None)

    def fake_terminate_pid(target_pid, force=False, expected_start_time=None):
        raise subprocess.TimeoutExpired(
            ["taskkill", "/PID", str(target_pid), "/T", "/F"], 10
        )

    monkeypatch.setattr(status_mod, "terminate_pid", fake_terminate_pid)

    # Must not propagate; the sweep reports it killed nothing it could confirm.
    killed = gateway_windows._force_terminate_known_gateway_pids([47264])

    assert killed == 0

def test_restart_still_spawns_when_stop_raises(monkeypatch, capsys):
    """THE regression: a failing ``stop()`` must never skip the relaunch.

    2026-08-11 ~12:00Z — ``taskkill`` exceeded its 10s cap on a loaded box
    (87.8% commit, six concurrent pytest runs). The kill SUCCEEDED, PID 47264
    died, and the ``TimeoutExpired`` then propagated out of ``stop()`` and out
    of ``restart()`` before ``_launch_detached_gateway()`` ran. :8642 was left
    with no listener for ~5 minutes until a manual relaunch.

    A slow-but-successful kill must leave a running gateway behind.
    """
    import subprocess

    calls = []

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)

    def boom():
        calls.append("stop")
        raise subprocess.TimeoutExpired(["taskkill", "/PID", "47264", "/T", "/F"], 10)

    monkeypatch.setattr(gateway_windows, "stop", boom)
    # The kill landed: nothing is alive afterwards.
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_absent", lambda **_kw: True)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        gateway_windows,
        "_launch_detached_gateway",
        lambda **_kw: calls.append("launch"),
    )
    monkeypatch.setattr(
        gateway_windows, "_wait_for_gateway_ready", lambda **_kw: [4242]
    )

    gateway_windows.restart()

    assert calls == ["stop", "launch"], (
        f"restart() must relaunch even when stop() raises (calls={calls})"
    )

def test_restart_reports_the_stop_error_when_the_relaunch_fails(monkeypatch):
    """Swallowing the stop error is only acceptable if a gateway comes back.

    If the relaunch also fails we are genuinely down, so the original stop
    failure must not be lost — it is the most useful diagnostic.
    """
    import subprocess

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)

    original = subprocess.TimeoutExpired(["taskkill", "/PID", "47264", "/T", "/F"], 10)

    def boom():
        raise original

    monkeypatch.setattr(gateway_windows, "stop", boom)
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_absent", lambda **_kw: True)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gateway_windows, "_launch_detached_gateway", lambda **_kw: None)
    # Nothing came up.
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", lambda **_kw: [])

    with pytest.raises(RuntimeError) as excinfo:
        gateway_windows.restart()

    assert excinfo.value.__cause__ is original, (
        "the stop-phase failure must be chained onto the restart failure"
    )

def test_restart_does_not_spawn_a_duplicate_when_stop_raises_and_pid_survives(
    monkeypatch,
):
    """Resilience must not become recklessness.

    When ``stop()`` fails AND the old gateway is genuinely still alive, the
    pre-existing refusal to start a second gateway on :8642 still applies.
    """
    import subprocess

    calls = []

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)

    def boom():
        raise subprocess.TimeoutExpired(["taskkill", "/PID", "47264", "/T", "/F"], 10)

    monkeypatch.setattr(gateway_windows, "stop", boom)
    # The old gateway refuses to die.
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_absent", lambda **_kw: False)
    monkeypatch.setattr(
        gateway_windows,
        "_force_terminate_known_gateway_pids",
        lambda pids: calls.append("force") or 0,
    )
    monkeypatch.setattr(gateway_windows, "_collect_gateway_stop_pids", lambda *_a: [47264])
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        gateway_windows,
        "_launch_detached_gateway",
        lambda **_kw: calls.append("launch"),
    )

    with pytest.raises(RuntimeError, match="refusing to start a duplicate"):
        gateway_windows.restart()

    assert "launch" not in calls, (
        f"must not spawn on top of a surviving gateway (calls={calls})"
    )

class TestWindowsStopDrainTimeout:
    """The grace period the stopper gives a gateway before it force-kills it.

    2026-08-17: this was ``min(configured, 30.0)``, which silently halved this
    box's configured 60s drain. The gateway was therefore *structurally*
    guaranteed to be shot mid-drain whenever an in-flight cron needed more
    than 30s — which a live LLM turn routinely does. 3 of 3 teardowns with
    crons in flight died at shutdown phase 1; 0 of 2 without any did.
    """

    @staticmethod
    def _configured(monkeypatch, value):
        monkeypatch.setattr(
            gateway, "_get_restart_drain_timeout", lambda: value, raising=False
        )

    def test_grace_outlasts_the_drain_budget_the_gateway_is_told_it_has(
        self, monkeypatch
    ):
        """A gateway granted less than its own drain budget dies mid-drain.

        ``agent.restart_drain_timeout`` is handed to the gateway's phase-2
        drain (``gateway/run.py``), so a stopper that gives less than that can
        never let the drain finish.
        """
        self._configured(monkeypatch, 60.0)

        assert gateway_windows._windows_stop_drain_timeout() > 60.0

    def test_grace_outlasts_the_internal_shutdown_watchdog_leash(self, monkeypatch):
        """The LOUD killer must win the race against the silent one.

        ``gateway/shutdown_watchdog.py`` force-exits at ``drain + 60s`` after
        logging CRITICAL and writing an all-thread dump. The external
        ``taskkill`` leaves no trace at all. If the stopper fires first the
        watchdog is unreachable and a genuine wedge is undiagnosable — which
        is why "Shutdown watchdog fired" appears zero times on this box.
        """
        from gateway.shutdown_watchdog import resolve_shutdown_watchdog_delay

        self._configured(monkeypatch, 60.0)

        assert gateway_windows._windows_stop_drain_timeout() > (
            resolve_shutdown_watchdog_delay(60.0)
        )

    def test_grace_is_still_bounded_for_an_absurd_configured_drain(
        self, monkeypatch
    ):
        """``stop`` must not wedge forever; the ceiling only has to be sane."""
        self._configured(monkeypatch, 86400.0)

        assert gateway_windows._windows_stop_drain_timeout() <= 600.0

    def test_grace_survives_an_unreadable_config(self, monkeypatch):
        """A broken config must not produce a zero-or-negative grace period."""

        def _boom():
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(
            gateway, "_get_restart_drain_timeout", _boom, raising=False
        )

        assert gateway_windows._windows_stop_drain_timeout() >= 1.0

    def test_zero_drain_is_honoured_rather_than_read_as_unset(self, monkeypatch):
        """0 is a real configured value here, not a missing one.

        ``agent.restart_drain_timeout`` defaults to 0 and documents it as the
        deliberate choice — "no drain, interrupt immediately" (see
        ``hermes_cli/config.py``) — and every other consumer honours it:
        ``parse_restart_drain_timeout`` clamps to ``>= 0`` and
        ``resolve_shutdown_watchdog_delay(0.0)`` is still a real 60s leash.
        A falsy ``or`` test here would make 0 inexpressible, so both an
        operator who asked for no drain and one who never set the key at all
        would silently be costed as if 30s had been configured.
        """
        from gateway.shutdown_watchdog import resolve_shutdown_watchdog_delay

        self._configured(monkeypatch, 0.0)

        assert gateway_windows._windows_stop_drain_timeout() == pytest.approx(
            resolve_shutdown_watchdog_delay(0.0)
            + gateway_windows._STOP_ESCALATION_MARGIN_S
        )

    def test_zero_drain_still_outlasts_the_shutdown_watchdog_leash(self, monkeypatch):
        """Honouring 0 must not collapse the escalation ordering.

        "No drain" is not "no shutdown": the watchdog still gets its full
        grace to fire, log CRITICAL, and dump. The stopper stays behind it.
        """
        from gateway.shutdown_watchdog import resolve_shutdown_watchdog_delay

        self._configured(monkeypatch, 0.0)

        assert gateway_windows._windows_stop_drain_timeout() > (
            resolve_shutdown_watchdog_delay(0.0)
        )

    def test_unset_config_key_gets_the_documented_zero_not_thirty(
        self, monkeypatch
    ):
        """The default path, through the real resolver rather than a stub.

        With no env override and no ``agent.restart_drain_timeout`` in
        config.yaml, ``_get_restart_drain_timeout`` returns the shared default,
        which is 0. The stopper must cost that as the 0 it is.
        """
        from gateway.shutdown_watchdog import resolve_shutdown_watchdog_delay

        monkeypatch.delenv("HERMES_RESTART_DRAIN_TIMEOUT", raising=False)
        monkeypatch.setattr(gateway, "read_raw_config", lambda: {}, raising=False)

        assert gateway._get_restart_drain_timeout() == 0.0
        assert gateway_windows._windows_stop_drain_timeout() == pytest.approx(
            resolve_shutdown_watchdog_delay(0.0)
            + gateway_windows._STOP_ESCALATION_MARGIN_S
        )

    def test_only_a_missing_drain_value_falls_back_to_the_default(self, monkeypatch):
        """The fallback is for an ABSENT lookup result, not a falsy one."""
        from gateway.shutdown_watchdog import resolve_shutdown_watchdog_delay

        self._configured(monkeypatch, None)

        assert gateway_windows._windows_stop_drain_timeout() == pytest.approx(
            resolve_shutdown_watchdog_delay(
                gateway_windows._STOP_FALLBACK_DRAIN_TIMEOUT_S
            )
            + gateway_windows._STOP_ESCALATION_MARGIN_S
        )
