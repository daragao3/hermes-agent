"""Subprocess bounds and session execution context survive TUI extraction."""
import subprocess

from tui_gateway import server


def test_cli_exec_uses_resolved_python_and_bounded_capture(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "real_executable", lambda: "resolved-python.exe")

    def capture(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "hello", "")

    monkeypatch.setattr("hermes_cli._subprocess_compat.run_text_capture", capture)
    response = server._methods["cli.exec"]("probe", {"argv": ["--version"], "timeout": 900})
    assert response["result"]["code"] == 0
    assert seen[0][0][:3] == ["resolved-python.exe", "-m", "hermes_cli.main"]
    assert seen[0][1]["timeout"] == 600


def test_quick_command_timeout_is_rpc_error(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"quick_commands": {"probe": {"type": "exec", "command": "probe"}}})

    def timeout(cmd, **kwargs):
        assert kwargs["timeout"] == 30
        assert kwargs["shell"] is True
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr("hermes_cli._subprocess_compat.run_text_capture", timeout)
    response = server._dispatch_quick("probe", {}, {}, "probe", "")
    assert response["error"]["code"] == 5002


def test_shell_capture_runs_real_child_with_bounded_output():
    response = server._captured_exec(
        "probe", [server.real_executable(), "-c", "print('bounded-child')"], 10,
        on_result=lambda result: result.stdout.strip(), timeout_err=(5002, "timeout"), fail_code=5003)
    assert response == "bounded-child"


def test_desktop_default_cwd_is_persisted_without_inventing_one(tmp_path):
    import sqlite3

    for key, cwd in [("resolved", "C:/workspace"), ("unset", " ")]:
        assert server._ensure_session_db_row({
            "session_key": key, "profile_home": str(tmp_path), "source": "desktop",
            "cwd": cwd, "explicit_cwd": False,
        }) is True
    with sqlite3.connect(tmp_path / "state.db") as db:
        rows = dict(db.execute("SELECT id, cwd FROM sessions"))
    assert rows == {"resolved": "C:/workspace", "unset": None}
