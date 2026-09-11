"""Tests for hermes_cli.gateway_windows."""

import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import hermes_cli.gateway as gateway
import hermes_cli.gateway_windows as gateway_windows
import hermes_cli.install_root as install_root
import hermes_cli.setup as setup


_BREAKAWAY_MARKER = "_HERMES_GATEWAY_BREAKAWAY"




def test_schtasks_encoding_falls_back_to_utf8(monkeypatch):
    """A broken/empty locale must not leave us without a decoder (issue #38172)."""

    monkeypatch.setattr(gateway_windows.locale, "getpreferredencoding", lambda *a, **k: "")
    assert gateway_windows._schtasks_encoding() == "utf-8"

    def _boom(*args, **kwargs):
        raise RuntimeError("locale exploded")

    monkeypatch.setattr(gateway_windows.locale, "getpreferredencoding", _boom)
    assert gateway_windows._schtasks_encoding() == "utf-8"




@pytest.mark.windows_only
def test_build_gateway_argv_keeps_venv_console_python_for_uv_venv(monkeypatch, tmp_path):
    """No pythonw / base-interpreter detour: the venv console python.exe is
    launched hidden (CREATE_NO_WINDOW) so descendants inherit its hidden
    console instead of flashing their own (#54220/#56747).

    Windows-only: ``_build_gateway_argv()`` asserts the host is Windows and the
    argv/env overlay it returns is built from real Windows path separators and
    ``Scripts/python.exe`` layout — a patched ``sys.platform`` covered the
    branch but not any of that.
    """

    project = tmp_path / "project"
    scripts = project / "venv" / "Scripts"
    site_packages = project / "venv" / "Lib" / "site-packages"
    hermes_home = tmp_path / "hermes-home"
    base = tmp_path / "uv" / "python" / "cpython-3.11-windows-x86_64-none"
    scripts.mkdir(parents=True)
    site_packages.mkdir(parents=True)
    hermes_home.mkdir()
    base.mkdir(parents=True)

    venv_python = scripts / "python.exe"
    venv_pythonw = scripts / "pythonw.exe"
    base_pythonw = base / "pythonw.exe"
    for exe in (venv_python, venv_pythonw, base_pythonw):
        exe.write_text("", encoding="utf-8")
    (project / "venv" / "pyvenv.cfg").write_text(
        f"home = {base}\nimplementation = CPython\nuv = 0.11.14\nversion_info = 3.11.15\n",
        encoding="utf-8",
    )

    import hermes_cli.gateway as gateway

    monkeypatch.setattr(gateway, "PROJECT_ROOT", project)
    monkeypatch.setattr(gateway, "get_python_path", lambda: str(venv_python))
    monkeypatch.setattr(gateway, "_profile_arg", lambda hermes_home: "")
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: str(hermes_home))

    # The install root, not HERMES_HOME and not `__file__`: see
    # TestSpawnPinsTheInstalledCheckoutNotTheCallerCwd.
    monkeypatch.setattr(
        gateway_windows, "find_installed_package_root", lambda: project
    )
    monkeypatch.setattr(gateway_windows, "installed_package_root", lambda: project)

    argv, cwd, env_overlay = gateway_windows._build_gateway_argv()

    assert argv[:3] == [str(venv_python), "-m", "hermes_cli.main"]
    assert cwd == str(project)
    assert env_overlay["VIRTUAL_ENV"] == str(project / "venv")
    assert str(project) in env_overlay["PYTHONPATH"].split(gateway_windows.os.pathsep)


@pytest.mark.windows_only
def test_spawn_detached_marks_primary_breakaway_success(monkeypatch, tmp_path, caplog):
    """A successful breakaway spawn reports true without a warning."""
    argv = ["python.exe", "-m", "hermes_cli.main", "gateway", "run"]
    cwd = str(tmp_path)
    calls = []

    def fake_popen(call_argv, **kwargs):
        calls.append((call_argv, kwargs))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(
        gateway_windows,
        "_build_gateway_argv",
        lambda: (argv, cwd, {"HERMES_GATEWAY_DETACHED": "1"}),
    )
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(gateway_windows.subprocess, "Popen", fake_popen)
    caplog.set_level(logging.WARNING, logger=gateway_windows.__name__)

    assert gateway_windows._spawn_detached() == 12345
    assert len(calls) == 1
    actual_argv, kwargs = calls[0]
    assert actual_argv == argv
    assert kwargs["cwd"] == cwd
    assert kwargs["creationflags"] == gateway_windows.windows_detach_flags()
    assert kwargs["env"][_BREAKAWAY_MARKER] == "1"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is kwargs["stderr"]
    assert not caplog.records


@pytest.mark.windows_only
def test_spawn_detached_warns_and_marks_no_breakaway_fallback(
    monkeypatch, tmp_path, caplog
):
    """A denied breakaway retries once with private false metadata."""
    argv = ["python.exe", "-m", "hermes_cli.main", "gateway", "run"]
    cwd = str(tmp_path)
    calls = []

    def fake_popen(call_argv, **kwargs):
        calls.append((call_argv, kwargs))
        if len(calls) == 1:
            error = OSError(13, "Access is denied")
            error.winerror = 5
            raise error
        return SimpleNamespace(pid=23456)

    monkeypatch.setattr(
        gateway_windows,
        "_build_gateway_argv",
        lambda: (
            argv,
            cwd,
            {"HERMES_GATEWAY_DETACHED": "1", "SECRET_SENTINEL": "do-not-log"},
        ),
    )
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(gateway_windows.subprocess, "Popen", fake_popen)
    caplog.set_level(logging.WARNING, logger=gateway_windows.__name__)

    assert gateway_windows._spawn_detached() == 23456
    assert len(calls) == 2
    (argv_primary, primary), (argv_fallback, fallback) = calls
    assert argv_primary == argv_fallback == argv
    assert primary["cwd"] == fallback["cwd"] == cwd
    assert primary["creationflags"] == gateway_windows.windows_detach_flags()
    assert (
        fallback["creationflags"]
        == gateway_windows.windows_detach_flags_without_breakaway()
    )
    assert primary["stdin"] is fallback["stdin"] is subprocess.DEVNULL
    assert primary["stdout"] is primary["stderr"]
    assert fallback["stdout"] is fallback["stderr"]
    assert Path(primary["stdout"].name) == Path(fallback["stdout"].name)
    assert primary["close_fds"] is fallback["close_fds"] is True
    assert primary["env"] is not fallback["env"]
    assert primary["env"][_BREAKAWAY_MARKER] == "1"
    assert fallback["env"][_BREAKAWAY_MARKER] == "0"
    assert {
        key: value for key, value in primary["env"].items() if key != _BREAKAWAY_MARKER
    } == {
        key: value for key, value in fallback["env"].items() if key != _BREAKAWAY_MARKER
    }

    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "5" in warnings[0].getMessage()
    assert "do-not-log" not in warnings[0].getMessage()
    assert str(tmp_path) not in warnings[0].getMessage()


class TestStableWindowsGatewayWorkingDir:
    def test_installed_checkout_beats_hermes_home(self, tmp_path, monkeypatch):
        """HERMES_HOME is a stable anchor but the WRONG one.

        `python -m` makes cwd sys.path[0], so the cwd a gateway is spawned with
        decides which copy of the source tree it imports. That has to be the
        checkout the venv was installed from.
        """
        home = tmp_path / ".hermes"
        home.mkdir()
        checkout = tmp_path / "agent-src"
        monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
        monkeypatch.setattr(
            gateway_windows, "find_installed_package_root", lambda: checkout
        )

        assert gateway_windows._stable_gateway_working_dir(
            tmp_path / "worktree"
        ) == str(checkout)

    def test_stable_gateway_working_dir_uses_hermes_home(self, tmp_path, monkeypatch):
        """With no install record, HERMES_HOME still beats a transient checkout.

        A Scheduled Task / Startup entry whose `cd /d` names a deleted worktree
        fails before Python loads, so the on-boot self-heal never runs.
        """
        home = tmp_path / ".hermes"
        home.mkdir()
        monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: home)
        monkeypatch.setattr(gateway_windows, "find_installed_package_root", lambda: None)
        assert gateway_windows._stable_gateway_working_dir(tmp_path / "checkout") == str(home.resolve())

    def test_stable_gateway_working_dir_falls_back_to_project_root(self, tmp_path, monkeypatch):
        missing = tmp_path / "missing" / ".hermes"
        project = tmp_path / "checkout"
        monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: missing)
        monkeypatch.setattr(gateway_windows, "find_installed_package_root", lambda: None)
        assert gateway_windows._stable_gateway_working_dir(project) == str(project)


def test_write_task_script_anchors_cmd_cd_at_hermes_home(monkeypatch, tmp_path):
    """No install record → HERMES_HOME, not a checkout that may be transient."""
    project = tmp_path / "project"
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    python_exe = project / "venv" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")
    script_path = tmp_path / "gateway.cmd"

    monkeypatch.setattr(gateway_windows, "find_installed_package_root", lambda: None)
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway, "PROJECT_ROOT", project)
    monkeypatch.setattr(gateway, "get_python_path", lambda: str(python_exe))
    monkeypatch.setattr(gateway, "_profile_arg", lambda hermes_home: "")
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: str(hermes_home))
    monkeypatch.setattr(gateway_windows, "get_task_script_path", lambda: script_path)

    written = gateway_windows._write_task_script()
    content = script_path.read_text(encoding="utf-8")

    assert written == script_path
    assert f"cd /d {gateway_windows._quote_cmd_script_arg(str(hermes_home.resolve()))}" in content
    assert f"cd /d {gateway_windows._quote_cmd_script_arg(str(project))}" not in content


def _arrange_startup_fallback(monkeypatch, tmp_path, running_pids):
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    startup_entry = tmp_path / "Startup" / "Hermes_Gateway_alice.cmd"
    calls = []

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "_write_task_script", lambda: script_path)
    monkeypatch.setattr(
        gateway_windows,
        "_install_scheduled_task",
        lambda task_name, script_path: (
            False,
            "schtasks /Create failed (code 1): ERROR: Access is denied.",
        ),
    )
    monkeypatch.setattr(gateway_windows, "_should_fall_back", lambda code, detail: True)
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: True)
    monkeypatch.setattr(
        gateway_windows,
        "_launch_elevated_install",
        lambda force=False, start_now=None, start_on_login=None: calls.append(("elevate", force, start_now, start_on_login)) or True,
    )

    def fake_install_startup_entry(path: Path) -> Path:
        calls.append(("install_startup", path))
        return startup_entry

    monkeypatch.setattr(gateway_windows, "_install_startup_entry", fake_install_startup_entry)
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda path=None, **_kw: calls.append(("spawn", path)) or 12345)
    monkeypatch.setattr(gateway_windows, "_report_gateway_start", lambda via: calls.append(("report_start", via)))
    monkeypatch.setattr(gateway_windows, "_print_next_steps", lambda: calls.append(("next_steps", None)))
    monkeypatch.setattr(gateway, "find_gateway_pids", lambda: running_pids)
    monkeypatch.setattr(gateway, "_profile_arg", lambda: "--profile alice")
    return script_path, calls




@pytest.mark.windows_only
def test_elevated_gateway_command_uses_hidden_console_python(monkeypatch):
    """UAC handoff launches console python with SW_HIDE — a single hidden
    console, not console-less pythonw (#54220/#56747), and no visible
    elevated cmd.exe window left open.

    Windows-only: the code path runs behind ``_assert_windows()`` and goes
    through ``ctypes.windll.shell32``, neither of which exists on a faked
    host. ShellExecuteW itself stays mocked — it would raise a real UAC
    prompt — but the host identity is genuine.
    """
    calls = []

    class FakeShell32:
        def ShellExecuteW(self, hwnd, verb, executable, params, cwd, show):
            calls.append((hwnd, verb, executable, params, cwd, show))
            return 33

    class FakeWindll:
        shell32 = FakeShell32()

    monkeypatch.setattr(gateway_windows, "_current_profile_cli_args", lambda: ["--profile", "alice"])
    monkeypatch.setattr(gateway_windows.sys, "executable", r"C:\Hermes\venv\Scripts\python.exe")
    monkeypatch.setattr(gateway_windows.ctypes, "windll", FakeWindll(), raising=False)

    assert gateway_windows._launch_elevated_gateway_command("install", ["--start-now", "--elevated-handoff"])

    assert len(calls) == 1
    _hwnd, verb, executable, params, cwd, show = calls[0]
    assert verb == "runas"
    assert executable == r"C:\Hermes\venv\Scripts\python.exe"
    assert "--profile alice gateway install --start-now --elevated-handoff" in params
    assert show == 0
    assert cwd


def test_install_scheduled_task_recreates_instead_of_change(monkeypatch, tmp_path):
    """Install must delete+create so stale minute-repeat task settings are not preserved.

    Host-agnostic on purpose: ``_install_scheduled_task`` only renders the task
    XML and shells out through ``_exec_schtasks`` (mocked here as the genuine
    external dependency), so no platform fake is needed.
    """
    calls = []
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    xml_seen = {}

    monkeypatch.setattr(gateway_windows, "_resolve_task_user", lambda: r"DOMAIN\\alice")

    def fake_schtasks(args):
        calls.append(tuple(args))
        if args[0] == "/Delete":
            return (0, "SUCCESS", "")
        if args[0] == "/Create":
            xml_path = Path(args[args.index("/XML") + 1])
            xml_seen["text"] = xml_path.read_text(encoding="utf-16")
            return (0, "SUCCESS", "")
        raise AssertionError(f"unexpected schtasks args: {args}")

    monkeypatch.setattr(gateway_windows, "_exec_schtasks", fake_schtasks)
    ok, detail = gateway_windows._install_scheduled_task("Hermes_Gateway_alice", script_path)

    assert ok is True
    assert "/Change" not in [arg for call in calls for arg in call]
    assert calls[0][:4] == ("/Delete", "/F", "/TN", "Hermes_Gateway_alice")
    assert calls[1][0] == "/Create"
    assert "/XML" in calls[1]
    assert "/SC" not in calls[1]
    assert "<Delay>PT30S</Delay>" in xml_seen["text"]
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml_seen["text"]
    assert "<StopOnIdleEnd>false</StopOnIdleEnd>" in xml_seen["text"]
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml_seen["text"]
    assert "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml_seen["text"]
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml_seen["text"]
    assert "<RestartOnFailure>" in xml_seen["text"]
    assert "<Count>999</Count>" in xml_seen["text"]
    # Scheduled Task launches the console-less .vbs via wscript.exe, never cmd.exe
    # (issue #45599 fix A: no console -> no logon CTRL_CLOSE_EVENT / 0xC000013A).
    assert "<Command>wscript.exe</Command>" in xml_seen["text"]
    assert "//B //Nologo" in xml_seen["text"]
    assert "Hermes_Gateway_alice.vbs" in xml_seen["text"]
    assert "cmd.exe" not in xml_seen["text"]


def test_gateway_vbs_script_is_console_less(monkeypatch):
    """The .vbs launcher must avoid cmd.exe entirely and Run pythonw hidden
    (issue #45599 fix A: no console -> no logon CTRL_CLOSE_EVENT / 0xC000013A)."""
    monkeypatch.setattr(
        gateway_windows,
        "_resolve_detached_python",
        lambda exe: (r"C:\venv\Scripts\pythonw.exe", Path(r"C:\venv"), []),
    )
    content = gateway_windows._build_gateway_vbs_script(
        r"C:\venv\Scripts\python.exe",
        r"C:\Hermes",
        r"C:\Hermes",
        "--profile work",
    )
    assert "cmd.exe" not in content.lower()
    assert 'CreateObject("WScript.Shell")' in content
    assert "pythonw.exe" in content
    assert "hermes_cli.main" in content
    assert "gateway run" in content
    assert ", 0, False" in content  # hidden window, detached/async
    for var in ("HERMES_HOME", "PYTHONIOENCODING", "HERMES_GATEWAY_DETACHED", "VIRTUAL_ENV", "PYTHONPATH"):
        assert var in content
    assert "--profile" in content and "work" in content
    assert content.endswith("\r\n")








def test_install_scheduled_task_success_start_now_uses_direct_spawn_not_task_run(monkeypatch, tmp_path, capsys):
    """Install start-now should not /Run the task; that preserved old restart loops."""
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    calls = []

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (True, True))
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: True)
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "_write_task_script", lambda: script_path)
    monkeypatch.setattr(
        gateway_windows,
        "_install_scheduled_task",
        lambda task_name, script_path: (True, "Created Scheduled Task 'Hermes_Gateway_alice'"),
    )
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(gateway_windows, "_exec_schtasks", lambda args: calls.append(("schtasks", tuple(args))) or (0, "", ""))
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda path=None, **_kw: calls.append(("spawn", path)) or 12345)
    monkeypatch.setattr(gateway_windows, "_report_gateway_start", lambda via: calls.append(("report_start", via)))
    monkeypatch.setattr(gateway_windows, "_print_next_steps", lambda: calls.append(("next_steps", None)))

    gateway_windows.install(force=False)

    assert not any(call[0] == "schtasks" and "/Run" in call[1] for call in calls)
    assert ("spawn", None) in calls
    assert any(call[0] == "report_start" for call in calls)
    out = capsys.readouterr().out
    assert "auto-start installed for Windows login" in out


def test_install_scheduled_task_success_does_not_auto_start(monkeypatch, tmp_path, capsys):
    """Install should register/update the task only; start is explicit."""
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    calls = []

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: True)
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "_write_task_script", lambda: script_path)
    monkeypatch.setattr(
        gateway_windows,
        "_install_scheduled_task",
        lambda task_name, script_path: (True, "Created Scheduled Task 'Hermes_Gateway_alice'"),
    )
    monkeypatch.setattr(gateway_windows, "_exec_schtasks", lambda args: calls.append(("schtasks", tuple(args))) or (0, "", ""))
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda path=None, **_kw: calls.append(("spawn", path)) or 12345)
    monkeypatch.setattr(gateway_windows, "_report_gateway_start", lambda via: calls.append(("report_start", via)))
    monkeypatch.setattr(gateway_windows, "_print_next_steps", lambda: calls.append(("next_steps", None)))

    gateway_windows.install(force=False)

    assert not any(call[0] == "schtasks" and "/Run" in call[1] for call in calls)
    assert not any(call[0] == "spawn" for call in calls)
    assert not any(call[0] == "report_start" for call in calls)
    assert ("next_steps", None) in calls
    out = capsys.readouterr().out
    assert "auto-start installed for Windows login" in out


def test_install_access_denied_launches_elevated_install_before_startup_fallback(monkeypatch, tmp_path, capsys):
    """Non-admin Scheduled Task access denied should hand off to UAC elevation."""
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    calls = []

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "_write_task_script", lambda: script_path)
    monkeypatch.setattr(
        gateway_windows,
        "_install_scheduled_task",
        lambda task_name, script_path: (
            False,
            "schtasks /Create failed (code 1): ERROR: Access is denied.",
        ),
    )
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: False)
    monkeypatch.setattr(
        gateway_windows,
        "_launch_elevated_install",
        lambda force=False, start_now=None, start_on_login=None: calls.append(("elevate", force, start_now, start_on_login)) or True,
    )
    monkeypatch.setattr(setup, "prompt_yes_no", lambda prompt, default=True: calls.append(("prompt", prompt, default)) or True)
    monkeypatch.setattr(gateway_windows, "_install_startup_entry", lambda path: calls.append(("install_startup", path)) or path)
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda path=None, **_kw: calls.append(("spawn", path)) or 12345)

    gateway_windows.install(force=True)

    assert calls == [("prompt", "  Open the UAC prompt now?", False), ("elevate", True, False, True)]
    out = capsys.readouterr().out
    assert "administrator approval" in out
    assert "UAC is Windows' admin approval prompt" in out
    assert "Launched elevated Hermes gateway install prompt" in out


def test_install_prompts_start_choices_before_uac(monkeypatch, tmp_path, capsys):
    """Windows install asks start-now and auto-start before any UAC handoff."""
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    calls = []
    answers = iter([True, True, True])

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "_write_task_script", lambda: script_path)
    monkeypatch.setattr(
        gateway_windows,
        "_install_scheduled_task",
        lambda task_name, script_path: (
            False,
            "schtasks /Create failed (code 1): ERROR: Access is denied.",
        ),
    )
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: False)
    monkeypatch.setattr(setup, "prompt_yes_no", lambda prompt, default=True: calls.append(("prompt", prompt, default)) or next(answers))
    monkeypatch.setattr(
        gateway_windows,
        "_launch_elevated_install",
        lambda force=False, start_now=None, start_on_login=None: calls.append(("elevate", force, start_now, start_on_login)) or True,
    )

    gateway_windows.install(force=False)

    assert calls == [
        ("prompt", "Start the gateway now after install?", True),
        ("prompt", "Start the gateway automatically on Windows login with a Scheduled Task?", True),
        ("prompt", "  Open the UAC prompt now?", False),
        ("elevate", False, True, True),
    ]
    out = capsys.readouterr().out
    assert "elevated install will start the gateway afterwards" in out


def test_install_start_now_without_login_autostart_never_escalates(monkeypatch, capsys):
    """If auto-start is declined, install can start directly without touching schtasks/UAC."""
    calls = []
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (True, False))
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda path=None, **_kw: calls.append(("spawn", path)) or 12345)
    monkeypatch.setattr(gateway_windows, "_report_gateway_start", lambda via: calls.append(("report_start", via)))
    monkeypatch.setattr(gateway_windows, "_install_scheduled_task", lambda *args, **kwargs: calls.append(("install_task", args)) or (True, "should not happen"))
    monkeypatch.setattr(gateway_windows, "_launch_elevated_install", lambda *args, **kwargs: calls.append(("elevate", args, kwargs)) or True)

    gateway_windows.install(force=False)

    assert not any(call[0] in {"install_task", "elevate"} for call in calls)
    assert ("spawn", None) in calls
    assert any(call[0] == "report_start" for call in calls)
    out = capsys.readouterr().out
    assert "Skipped Windows login auto-start install" in out


def test_start_noops_when_gateway_already_running(monkeypatch, capsys):
    """Repeated start should not invoke schtasks /Run or spawn another process."""
    calls = []
    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [27128])
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: calls.append("task_check") or True)
    monkeypatch.setattr(gateway_windows, "_exec_schtasks", lambda args: calls.append(("schtasks", tuple(args))) or (0, "", ""))
    monkeypatch.setattr(gateway_windows, "_spawn_detached", lambda path=None, **_kw: calls.append(("spawn", path)) or 12345)

    gateway_windows.start()

    assert calls == []
    out = capsys.readouterr().out
    assert "already running" in out
    assert "27128" in out


def test_restart_relaunches_manual_gateway_without_persistence(monkeypatch):
    """Restarting a manual gateway must not create Windows login persistence."""
    calls = []

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(
        gateway_windows,
        "_wait_for_gateway_absent",
        lambda **kwargs: calls.append(("wait_absent", kwargs)) or True,
    )
    monkeypatch.setattr(
        gateway_windows.time,
        "sleep",
        lambda seconds: calls.append(("sleep", seconds)),
    )
    monkeypatch.setattr(
        gateway_windows,
        "_gateway_pids",
        lambda: calls.append("concurrent_check") or [],
    )
    monkeypatch.setattr(
        gateway_windows,
        "_spawn_detached",
        lambda *_a, **_kw: calls.append("spawn") or 12345,
    )
    monkeypatch.setattr(
        gateway_windows,
        "_report_gateway_start",
        lambda via: calls.append(("report_start", via)),
    )
    monkeypatch.setattr(
        gateway_windows,
        "_wait_for_gateway_ready",
        lambda **kwargs: calls.append(("wait_ready", kwargs)) or [12345],
    )

    monkeypatch.setattr(
        gateway_windows,
        "start",
        lambda: pytest.fail("restart must launch directly, not call start()"),
    )
    monkeypatch.setattr(
        gateway_windows,
        "install",
        lambda *args, **kwargs: pytest.fail("restart must not install persistence"),
    )
    monkeypatch.setattr(
        gateway_windows,
        "is_task_registered",
        lambda: pytest.fail("restart must not query the Scheduled Task"),
    )
    monkeypatch.setattr(
        gateway_windows,
        "is_startup_entry_installed",
        lambda: pytest.fail("restart must not query the Startup folder"),
    )
    monkeypatch.setattr(
        setup,
        "prompt_yes_no",
        lambda *args, **kwargs: pytest.fail("restart must not prompt for install"),
    )

    gateway_windows.restart()

    assert calls == [
        "stop",
        ("wait_absent", {"timeout_s": 30.0}),
        ("sleep", 1.0),
        "concurrent_check",
        "spawn",
        ("report_start", "direct spawn (PID 12345)"),
        ("wait_ready", {"timeout_s": 15.0}),
    ]


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


def _arrange_windows_restart_fallthrough(monkeypatch, running_pids, exc=None):
    """Drive ``_gateway_command_inner('restart')`` down the Windows branch.

    ``gateway_windows.restart()`` raises, so the generic recovery path below it
    is reachable. Everything that path could use to tear down / relaunch a
    gateway is stubbed to record instead of act.

    ``exc`` overrides the exception ``restart()`` raises so the caller can
    verify which failure types the recovery arm actually catches.
    """
    calls = []

    monkeypatch.setattr(gateway, "is_windows", lambda: True)
    monkeypatch.setattr(gateway, "is_macos", lambda: False)
    monkeypatch.setattr(gateway, "supports_systemd_services", lambda: False)
    monkeypatch.setattr(gateway, "_dispatch_via_service_manager_if_s6", lambda _a: False)
    monkeypatch.setattr(gateway, "_dispatch_all_via_service_manager_if_s6", lambda _a: False)
    monkeypatch.setattr(gateway_windows, "is_installed", lambda: False)

    def _boom():
        calls.append("windows_restart")
        raise exc or RuntimeError(
            "Gateway restart did not produce a running gateway process."
        )

    monkeypatch.setattr(gateway_windows, "restart", _boom)
    monkeypatch.setattr(gateway, "find_gateway_pids", lambda *a, **k: list(running_pids))
    monkeypatch.setattr(
        gateway,
        "stop_profile_gateway",
        lambda: calls.append("stop_profile_gateway") or True,
    )
    monkeypatch.setattr(
        gateway,
        "_wait_for_gateway_exit",
        lambda **kwargs: calls.append("wait_exit"),
    )
    monkeypatch.setattr(
        gateway,
        "cleanup_gateway_state_files",
        lambda: calls.append("cleanup_state_files") or [],
    )
    monkeypatch.setattr(
        gateway,
        "launch_gateway_detached",
        lambda *a, **k: calls.append("launch_detached") or 4242,
    )
    return calls


def test_windows_restart_failure_does_not_tear_down_a_live_gateway(monkeypatch):
    """A slow-but-healthy restart must not be stopped and relaunched again.

    ``gateway_windows.restart()`` spawns the replacement BEFORE it waits for
    readiness, so a slow boot makes it raise while a healthy gateway is coming
    up. Falling through to the generic recovery path then stops that gateway,
    deletes its lock/pid, and launches a third one -- observed on this machine
    as pairs of detached gateways fighting over :8642.
    """
    calls = _arrange_windows_restart_fallthrough(monkeypatch, running_pids=[10588])

    gateway._gateway_command_inner(
        SimpleNamespace(gateway_command="restart", all=False, system=False, detached=None)
    )

    assert calls == ["windows_restart"], (
        "a live gateway must be left alone after gateway_windows.restart() raises"
    )


def test_windows_restart_subprocess_timeout_reaches_the_recovery_arm(monkeypatch):
    """A ``TimeoutExpired`` escaping restart() must not bypass recovery.

    The recovery arm caught ``(CalledProcessError, RuntimeError, OSError)``.
    ``TimeoutExpired`` is a *sibling* of ``CalledProcessError`` under
    ``SubprocessError`` — not a subclass — so it sailed past this handler too,
    which is why the 2026-08-11 outage was not caught by the existing net.
    """
    import subprocess

    calls = _arrange_windows_restart_fallthrough(
        monkeypatch,
        running_pids=[],
        exc=subprocess.TimeoutExpired(["taskkill", "/PID", "47264", "/T", "/F"], 10),
    )

    gateway._gateway_command_inner(
        SimpleNamespace(gateway_command="restart", all=False, system=False, detached=None)
    )

    assert calls == [
        "windows_restart",
        "stop_profile_gateway",
        "wait_exit",
        "cleanup_state_files",
        "launch_detached",
    ]


def test_windows_restart_timeout_leaves_a_surviving_gateway_alone(monkeypatch):
    """The survivor check must also apply to a subprocess timeout."""
    import subprocess

    calls = _arrange_windows_restart_fallthrough(
        monkeypatch,
        running_pids=[10588],
        exc=subprocess.TimeoutExpired(["taskkill", "/PID", "47264", "/T", "/F"], 10),
    )

    gateway._gateway_command_inner(
        SimpleNamespace(gateway_command="restart", all=False, system=False, detached=None)
    )

    assert calls == ["windows_restart"]


def test_windows_restart_failure_still_recovers_when_nothing_is_running(monkeypatch):
    """The generic fallback must remain reachable when the restart truly failed."""
    calls = _arrange_windows_restart_fallthrough(monkeypatch, running_pids=[])

    gateway._gateway_command_inner(
        SimpleNamespace(gateway_command="restart", all=False, system=False, detached=None)
    )

    assert calls == [
        "windows_restart",
        "stop_profile_gateway",
        "wait_exit",
        "cleanup_state_files",
        "launch_detached",
    ]


def test_install_startup_fallback_does_not_spawn_when_gateway_already_running(monkeypatch, tmp_path, capsys):
    """Repeated Windows fallback installs should not spawn duplicate gateways."""
    script_path, calls = _arrange_startup_fallback(monkeypatch, tmp_path, [24476])

    gateway_windows.install(force=False)

    assert ("install_startup", script_path) in calls
    assert not any(call[0] == "spawn" for call in calls)
    assert not any(call[0] == "report_start" for call in calls)
    assert ("next_steps", None) in calls
    out = capsys.readouterr().out
    assert "already running" in out
    assert "24476" in out


def test_install_startup_fallback_does_not_auto_spawn_when_gateway_stopped(monkeypatch, tmp_path, capsys):
    """Startup fallback install should only install login item, not launch pythonw."""
    script_path, calls = _arrange_startup_fallback(monkeypatch, tmp_path, [])

    gateway_windows.install(force=False)

    assert ("install_startup", script_path) in calls
    assert not any(call[0] == "spawn" for call in calls)
    assert not any(call[0] == "report_start" for call in calls)
    assert ("next_steps", None) in calls
    out = capsys.readouterr().out
    assert "gateway not started now" in out
    assert "hermes --profile alice gateway start" in out


def test_install_access_denied_declined_elevation_uses_startup_fallback(monkeypatch, tmp_path, capsys):
    """Install should ask before UAC; declining keeps the non-jarring fallback path."""
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    calls = []

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "_write_task_script", lambda: script_path)
    monkeypatch.setattr(
        gateway_windows,
        "_install_scheduled_task",
        lambda task_name, script_path: (
            False,
            "schtasks /Create failed (code 1): ERROR: Access is denied.",
        ),
    )
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: False)
    monkeypatch.setattr(setup, "prompt_yes_no", lambda prompt, default=True: calls.append(("prompt", prompt, default)) or False)
    monkeypatch.setattr(
        gateway_windows,
        "_launch_elevated_install",
        lambda force=False, start_now=None, start_on_login=None: calls.append(("elevate", force, start_now, start_on_login)) or True,
    )
    monkeypatch.setattr(gateway_windows, "_install_startup_entry", lambda path: calls.append(("install_startup", path)) or path)
    monkeypatch.setattr(gateway, "find_gateway_pids", lambda: [])
    monkeypatch.setattr(gateway, "_profile_arg", lambda: "--profile alice")
    monkeypatch.setattr(gateway_windows, "_print_next_steps", lambda: calls.append(("next_steps", None)))

    gateway_windows.install(force=False)

    assert ("prompt", "  Open the UAC prompt now?", False) in calls
    assert not any(call[0] == "elevate" for call in calls)
    assert ("install_startup", script_path) in calls
    out = capsys.readouterr().out
    assert "Skipped elevation" in out
    assert "UAC is Windows' admin approval prompt" in out


def test_uninstall_access_denied_prompts_before_elevating(monkeypatch, tmp_path, capsys):
    """Uninstall should hand off to an elevated uninstall only after user consent."""
    calls = []
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    startup_entry = tmp_path / "Startup" / "Hermes_Gateway_alice.cmd"

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "get_task_script_path", lambda: script_path)
    monkeypatch.setattr(gateway_windows, "get_startup_entry_path", lambda: startup_entry)
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: True)
    monkeypatch.setattr(
        gateway_windows,
        "_exec_schtasks",
        lambda args: calls.append(("schtasks", tuple(args))) or (1, "", "ERROR: Access is denied."),
    )
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: False)
    monkeypatch.setattr(setup, "prompt_yes_no", lambda prompt, default=True: calls.append(("prompt", prompt, default)) or True)
    monkeypatch.setattr(gateway_windows, "_launch_elevated_gateway_command", lambda command: calls.append(("elevate_uninstall", None)) or command == "uninstall")

    gateway_windows.uninstall()

    assert ("prompt", "  Open the UAC prompt now?", False) in calls
    assert ("elevate_uninstall", None) in calls
    out = capsys.readouterr().out
    assert "uninstall needs administrator approval" in out
    assert "UAC is Windows' admin approval prompt" in out
    assert "Launched elevated Hermes gateway uninstall prompt" in out


def test_uninstall_access_denied_declined_keeps_task_and_cleans_files(monkeypatch, tmp_path, capsys):
    """Declining UAC should not surprise the user, but should still remove user-writable artifacts."""
    calls = []
    script_path = tmp_path / "Hermes_Gateway_alice.cmd"
    startup_entry = tmp_path / "Startup" / "Hermes_Gateway_alice.cmd"
    startup_entry.parent.mkdir(parents=True)
    script_path.write_text("task", encoding="utf-8")
    startup_entry.write_text("startup", encoding="utf-8")

    monkeypatch.setattr(gateway_windows, "_prompt_install_choices", lambda *args, **kwargs: (False, True))
    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "get_task_name", lambda: "Hermes_Gateway_alice")
    monkeypatch.setattr(gateway_windows, "get_task_script_path", lambda: script_path)
    monkeypatch.setattr(gateway_windows, "get_startup_entry_path", lambda: startup_entry)
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: True)
    monkeypatch.setattr(
        gateway_windows,
        "_exec_schtasks",
        lambda args: calls.append(("schtasks", tuple(args))) or (1, "", "ERROR: Access is denied."),
    )
    monkeypatch.setattr(gateway_windows, "_is_running_as_admin", lambda: False)
    monkeypatch.setattr(setup, "prompt_yes_no", lambda prompt, default=True: calls.append(("prompt", prompt, default)) or False)
    monkeypatch.setattr(gateway_windows, "_launch_elevated_gateway_command", lambda command: calls.append(("elevate_uninstall", None)) or command == "uninstall")

    gateway_windows.uninstall()

    assert not any(call[0] == "elevate_uninstall" for call in calls)
    assert not script_path.exists()
    assert not startup_entry.exists()
    out = capsys.readouterr().out
    assert "Skipped elevation" in out
    assert "UAC is Windows' admin approval prompt" in out
    assert "Scheduled Task still registered" in out


# ---------------------------------------------------------------------------
# stop() drain semantics — issue #33778
#
# Background: on Windows, asyncio.add_signal_handler raises NotImplementedError,
# so the gateway's SIGTERM handler (which drains in-flight agents and writes
# resume_pending=True) never fires when `hermes gateway stop` kills the
# process. The fix: stop() writes the planned_stop_marker first, waits for
# the gateway's marker-watcher thread to drain + exit cleanly, then escalates
# to taskkill if drain times out.
# ---------------------------------------------------------------------------








def test_stop_no_running_gateway_skips_drain(monkeypatch):
    """When no gateway PID file is running, skip drain but clear known strays."""
    events = []
    stray_pid = 42424

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: False)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [stray_pid])

    from gateway import status as status_mod
    monkeypatch.setattr(status_mod, "get_running_pid", lambda: None)

    def fake_write_marker(target_pid):
        events.append(("write_marker", target_pid))
        return True
    monkeypatch.setattr(status_mod, "write_planned_stop_marker", fake_write_marker)
    monkeypatch.setattr(status_mod, "_pid_exists", lambda check_pid: check_pid == stray_pid)

    def fake_terminate_pid(target_pid, force=False, expected_start_time=None):
        events.append(("terminate", target_pid, force))

    monkeypatch.setattr(status_mod, "terminate_pid", fake_terminate_pid)
    monkeypatch.setattr("hermes_cli.gateway._get_restart_drain_timeout", lambda: 5.0)

    gateway_windows.stop()

    # With no PID to drain, no marker is written. The bounded profile scan can
    # still find and terminate a known stray without falling back to a broad
    # process sweep.
    assert ("write_marker", None) not in events
    assert all(e[0] != "write_marker" for e in events), (
        f"Should not write marker when no PID is running (events={events})"
    )
    assert events == [("terminate", stray_pid, True)]


def test_drain_helper_handles_invalid_pid(monkeypatch):
    """_drain_gateway_pid returns False for invalid PIDs without crashing."""
    assert gateway_windows._drain_gateway_pid(0, 5.0) is False
    assert gateway_windows._drain_gateway_pid(-1, 5.0) is False


def test_drain_helper_returns_true_when_pid_exits_quickly(monkeypatch):
    """_drain_gateway_pid polls _pid_exists until it returns False."""
    pid = 66666
    poll_count = [0]

    def fake_pid_exists(check_pid):
        poll_count[0] += 1
        return poll_count[0] < 3  # alive twice, then gone

    from gateway import status as status_mod
    monkeypatch.setattr(status_mod, "write_planned_stop_marker", lambda p: True)
    monkeypatch.setattr(status_mod, "_pid_exists", fake_pid_exists)

    assert gateway_windows._drain_gateway_pid(pid, drain_timeout=5.0) is True


def test_drain_helper_returns_false_on_timeout(monkeypatch):
    """_drain_gateway_pid returns False when the PID never exits."""
    from gateway import status as status_mod
    monkeypatch.setattr(status_mod, "write_planned_stop_marker", lambda p: True)
    monkeypatch.setattr(status_mod, "_pid_exists", lambda check_pid: True)

    assert gateway_windows._drain_gateway_pid(55555, drain_timeout=1.0) is False


def test_drain_helper_still_waits_if_marker_write_fails(monkeypatch):
    """Marker-write failures are swallowed; drain still polls for PID exit.

    If the marker can't be written (disk full, permission error), the
    gateway can't drain — but the wait still happens so a slow-shutdown
    gateway from a different code path (e.g. SIGTERM working on this
    platform after all) still gets observed cleanly.
    """
    pid = 44444
    def fake_write(target_pid):
        raise OSError("disk full")

    from gateway import status as status_mod
    monkeypatch.setattr(status_mod, "write_planned_stop_marker", fake_write)
    monkeypatch.setattr(status_mod, "_pid_exists", lambda check_pid: False)

    # Returns True because _pid_exists immediately says "gone".
    assert gateway_windows._drain_gateway_pid(pid, drain_timeout=5.0) is True


# ── spawn label -> boot_reason round trip ────────────────────────────────────
#
# tests/hermes_cli/test_gateway_start_diag_attribution.py already pins that
# `start()` passes "cli:start" and `restart()` passes "cli:restart" by stubbing
# `_spawn_detached`. That leaves the seam untested: the label is only worth
# anything if it survives the real spawn into the child env AND is read back as
# the `boot_reason` an operator sees in ~/.hermes/events/audit.jsonl. Stubbing
# either end would let the two halves drift apart while both files stayed green.


@pytest.mark.parametrize(
    "entry, expected_boot_reason",
    [
        ("start", "cli:start"),
        ("restart", "cli:restart"),
    ],
)
def test_cli_entrypoint_label_survives_into_boot_reason(
    monkeypatch, tmp_path, entry, expected_boot_reason
):
    """A restart must be distinguishable from a plain start in the audit trail.

    Drives the real `_spawn_detached` (only `Popen` is faked) so the assertion
    covers the actual env hand-off, then evaluates `_detect_boot_reason` under
    exactly the environment the child would have inherited.
    """
    import sys as _sys

    from gateway.run import GatewayRunner
    from hermes_cli import gateway_diag

    monkeypatch.setattr(gateway_windows, "_assert_windows", lambda: None)
    monkeypatch.setattr(gateway_windows, "_report_gateway_start", lambda via: None)
    monkeypatch.setattr(gateway_windows, "_gateway_pids", lambda: [])
    monkeypatch.setattr(gateway_windows, "is_task_registered", lambda: True)
    monkeypatch.setattr(gateway_windows, "is_startup_entry_installed", lambda: False)
    monkeypatch.setattr(gateway_windows, "stop", lambda: None)
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_absent", lambda **k: True)
    monkeypatch.setattr(gateway_windows, "_wait_for_gateway_ready", lambda **k: True)
    monkeypatch.setattr(gateway_windows.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        gateway_windows,
        "_build_gateway_argv",
        lambda: (["pythonw.exe", "-m", "hermes_cli.main", "gateway", "run"], str(tmp_path), {}),
    )
    monkeypatch.setattr(gateway_windows, "windows_detach_flags", lambda: 0)
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: tmp_path)

    captured: dict[str, dict] = {}

    class _FakePopen:
        pid = 4242

        def __init__(self, argv, **kwargs):
            captured["env"] = kwargs["env"]

    monkeypatch.setattr(gateway_windows.subprocess, "Popen", _FakePopen)

    getattr(gateway_windows, entry)()

    # The producer half: the child really was handed the label.
    child_env = captured["env"]
    assert child_env[gateway_diag.SPAWN_SITE_ENV] == expected_boot_reason

    # The consumer half: that child classifies its own boot from the label.
    monkeypatch.setattr(_sys, "argv", ["hermes", "gateway", "run"])
    monkeypatch.setenv(gateway_diag.SPAWN_SITE_ENV, child_env[gateway_diag.SPAWN_SITE_ENV])
    assert GatewayRunner._detect_boot_reason(None) == expected_boot_reason


# ── which checkout the spawned gateway actually runs ─────────────────────────
#
# 2026-08-17 (observed live): `hermes gateway restart` launched from an agent
# worktree deployed THAT worktree. `python -m hermes_cli.main` puts the caller's
# cwd on sys.path[0], so `hermes_cli` resolved from the worktree, `PROJECT_ROOT`
# (derived from `__file__`) became the worktree, and the spawn handed the new
# gateway that root as its cwd/PYTHONPATH. Proof was gateway.pid's argv[0]:
#   ...\.claude\worktrees\wizardly-pasteur-947fe1\hermes_cli\main.py
# The worktree was ~10 commits behind main and is reaper-deletable (the module
# root can be removed from under the running gateway), yet every health check
# passed — a worktree is a real checkout. Agent sessions almost always run from
# one, so this is the DEFAULT hazard on this box, not an edge case.


class _FakeEditableFinder:
    """Stand-in for setuptools' generated ``__editable___*_finder``."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self.MAPPING = mapping

    def find_spec(self, fullname, path=None, target=None):
        return None


class TestSpawnPinsTheInstalledCheckoutNotTheCallerCwd:
    @staticmethod
    def _arrange(monkeypatch, tmp_path) -> tuple[Path, Path]:
        """Editable install at <checkout>, but this process runs the worktree."""
        checkout = tmp_path / "agent-src"
        worktree = checkout / ".claude" / "worktrees" / "wizardly-pasteur-947fe1"
        for root in (checkout, worktree):
            (root / "hermes_cli").mkdir(parents=True)
            (root / "hermes_cli" / "__init__.py").write_text("", encoding="utf-8")
        scripts = checkout / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        for name in ("python.exe", "pythonw.exe"):
            (scripts / name).write_text("", encoding="utf-8")
        hermes_home = tmp_path / "hermes-home" / "profiles" / "main"
        hermes_home.mkdir(parents=True)

        monkeypatch.setattr(gateway_windows.sys, "platform", "win32")
        monkeypatch.chdir(worktree)
        monkeypatch.setattr(gateway, "PROJECT_ROOT", worktree)
        monkeypatch.setattr(
            gateway, "get_python_path", lambda: str(scripts / "python.exe")
        )
        monkeypatch.setattr(gateway, "_profile_arg", lambda *a, **k: "")
        monkeypatch.setattr(
            "hermes_cli.config.get_hermes_home", lambda: str(hermes_home)
        )
        monkeypatch.setattr(install_root, "_running_package_root", lambda: worktree)
        monkeypatch.setattr(
            install_root.sys,
            "meta_path",
            [
                _FakeEditableFinder({"hermes_cli": str(checkout / "hermes_cli")}),
                *(f for f in install_root.sys.meta_path
                  if install_root._finder_mapping(f) is None),
            ],
        )
        return checkout, worktree

    def test_build_gateway_argv_returns_the_checkout_as_working_dir(
        self, monkeypatch, tmp_path
    ):
        checkout, worktree = self._arrange(monkeypatch, tmp_path)

        _argv, working_dir, env_overlay = gateway_windows._build_gateway_argv()

        assert working_dir == str(checkout)
        pythonpath = env_overlay["PYTHONPATH"].split(gateway_windows.os.pathsep)
        assert pythonpath[0] == str(checkout)
        assert str(worktree) not in pythonpath

    def test_spawn_detached_popen_gets_the_checkout_as_cwd(
        self, monkeypatch, tmp_path
    ):
        """Assert on the ARGUMENT handed to Popen, not on a live spawn."""
        checkout, worktree = self._arrange(monkeypatch, tmp_path)
        captured: dict[str, object] = {}

        class _FakePopen:
            pid = 4242

            def __init__(self, argv, **kwargs):
                captured["argv"] = argv
                captured.update(kwargs)

        monkeypatch.setattr(gateway_windows.subprocess, "Popen", _FakePopen)
        monkeypatch.setattr(gateway_windows, "windows_detach_flags", lambda: 0)

        assert gateway_windows._spawn_detached(reason="cli:restart") == 4242

        assert captured["cwd"] == str(checkout)
        pythonpath = captured["env"]["PYTHONPATH"].split(gateway_windows.os.pathsep)
        assert pythonpath[0] == str(checkout)
        assert str(worktree) not in pythonpath

    def test_replace_respawn_spec_is_pinned_too(self, monkeypatch, tmp_path):
        """`gateway run --replace` respawns must not inherit the worktree either."""
        checkout, worktree = self._arrange(monkeypatch, tmp_path)
        argv = [
            str(checkout / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "hermes_cli.main",
            "gateway",
            "run",
            "--replace",
        ]

        _new_argv, working_dir, env_overlay = (
            gateway_windows.windowless_gateway_restart_spec(argv)
        )

        assert working_dir == str(checkout)
        pythonpath = env_overlay["PYTHONPATH"].split(gateway_windows.os.pathsep)
        assert pythonpath[0] == str(checkout)
        assert str(worktree) not in pythonpath

    def test_task_script_cd_and_pythonpath_are_the_checkout(
        self, monkeypatch, tmp_path
    ):
        """The Scheduled Task / Startup wrapper is generated from a worktree too."""
        checkout, worktree = self._arrange(monkeypatch, tmp_path)
        script_path = tmp_path / "gateway.cmd"
        monkeypatch.setattr(gateway_windows, "get_task_script_path", lambda: script_path)

        gateway_windows._write_task_script()
        content = script_path.read_text(encoding="utf-8")

        assert f"cd /d {gateway_windows._quote_cmd_script_arg(str(checkout))}" in content
        assert f'set "PYTHONPATH={checkout};' in content
        assert str(worktree) not in content
        # The generated wrapper outlives every worktree it could be written from.
        assert ".claude" not in content, "a worktree path leaked into the launcher"


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
