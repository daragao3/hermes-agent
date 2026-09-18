"""Post-update reporting for unresolved SQLite WAL-reset risk."""

from pathlib import Path
from types import SimpleNamespace

from hermes_cli import update_cmd
import hermes_cli.update_cmd_maint as update_cmd_maint
import hermes_cli.update_cmd_deps as update_cmd_deps


def test_runtime_status_probes_running_venv_outside_checkout(tmp_path, monkeypatch):
    running_python = tmp_path / "venv312" / "bin" / "python"
    observed = []
    vulnerable = SimpleNamespace(wal_reset_vulnerable=True)
    monkeypatch.setattr("hermes_constants.project_venv_dir", lambda _root: None)
    monkeypatch.setattr(update_cmd.sys, "executable", str(running_python))
    monkeypatch.setattr(
        "hermes_cli.sqlite_runtime.probe_sqlite_runtime",
        lambda python: observed.append(Path(python)) or vulnerable,
    )

    safe, info = update_cmd._post_update_sqlite_runtime_status()

    assert observed == [running_python]
    assert safe is False
    assert info is vulnerable


def test_summary_withholds_success_when_sqlite_remediation_failed(capsys, monkeypatch):
    monkeypatch.setattr(
        update_cmd,
        "_post_update_sqlite_runtime_status",
        lambda: (False, SimpleNamespace(sqlite_version_string="3.46.1")),
        raising=False,
    )
    monkeypatch.setattr(
        update_cmd_maint,
        "_post_update_sqlite_runtime_status",
        lambda: (False, SimpleNamespace(sqlite_version_string="3.46.1")),
        raising=False,
    )
    monkeypatch.setattr(
        update_cmd,
        "_update_complete_message",
        lambda _version: "✓ Update complete! (v0.20.5)",
    )
    monkeypatch.setattr(
        update_cmd_maint,
        "_update_complete_message",
        lambda _version: "✓ Update complete! (v0.20.5)",
    )

    complete = update_cmd._print_update_summary(
        node_failures=[],
        desktop_build_ok=True,
        pre_update_version="0.20.4",
    )

    out = capsys.readouterr().out
    assert complete is False
    assert "Update complete" not in out
    assert "SQLite 3.46.1" in out
    assert "WAL-reset" in out
    assert "uv-managed Python" in out
    assert "hermes doctor" in out


def test_current_checkout_completion_is_verified_before_success(capsys, monkeypatch):
    monkeypatch.setattr(
        update_cmd,
        "_post_update_sqlite_runtime_status",
        lambda: (False, SimpleNamespace(sqlite_version_string="3.46.1")),
    )
    monkeypatch.setattr(
        update_cmd_maint,
        "_post_update_sqlite_runtime_status",
        lambda: (False, SimpleNamespace(sqlite_version_string="3.46.1")),
    )

    complete = update_cmd._print_verified_update_completion("✓ Already up to date!")

    out = capsys.readouterr().out
    assert complete is False
    assert "Already up to date" not in out
    assert "SQLite 3.46.1" in out


def test_current_checkout_repair_returns_verified_completion_result(monkeypatch):
    monkeypatch.setattr(update_cmd, "_update_node_dependencies", lambda: [])
    monkeypatch.setattr(update_cmd_deps, "_update_node_dependencies", lambda: [])
    monkeypatch.setattr(update_cmd._m(), "_build_web_ui", lambda _path: None)
    monkeypatch.setattr(
        update_cmd,
        "_rebuild_desktop_after_update",
        lambda _dir, **_kwargs: True,
    )
    monkeypatch.setattr(
        update_cmd_deps,
        "_rebuild_desktop_after_update",
        lambda _dir, **_kwargs: True,
    )

    complete = update_cmd._repair_node_deps_on_current_checkout(
        lambda _message: False
    )

    assert complete is False


def _fixed_sqlite_on_windows_312() -> SimpleNamespace:
    """A probe result with safe SQLite whose interpreter still carries CPython gh-130727."""
    return SimpleNamespace(
        wal_reset_vulnerable=False, wmi_stray_thread_vulnerable=True,
        sqlite_version_string="3.53.1", python_version_string="3.12.13")


def test_wmi_thread_defect_is_advisory_not_blocking(capsys, monkeypatch):
    """The interpreter defect is provisioned on by the runtime repair and reported here, but it
    must not demote the update (which feeds ``sys.exit(1)`` and the gateway exit-code marker):
    that would strand every Windows 3.12 install's automated updates."""
    for module in (update_cmd, update_cmd_maint):
        monkeypatch.setattr(
            module, "_post_update_sqlite_runtime_status",
            lambda: (True, _fixed_sqlite_on_windows_312()), raising=False)
        monkeypatch.setattr(
            module, "_update_complete_message", lambda _version: "✓ Update complete! (v0.21.1)")

    complete = update_cmd._print_update_summary(
        node_failures=[], desktop_build_ok=True, pre_update_version="0.21.0")

    out = capsys.readouterr().out
    assert complete is True
    assert "Update complete" in out
    assert "Python 3.12.13" in out and "gh-130727" in out
    assert "hermes doctor" in out
    assert "partially complete" not in out


def test_verified_completion_carries_the_wmi_advisory(capsys, monkeypatch):
    for module in (update_cmd, update_cmd_maint):
        monkeypatch.setattr(
            module, "_post_update_sqlite_runtime_status",
            lambda: (True, _fixed_sqlite_on_windows_312()))

    complete = update_cmd._print_verified_update_completion("✓ Already up to date!")

    out = capsys.readouterr().out
    assert complete is True
    assert "Already up to date" in out
    assert "gh-130727" in out


def test_no_advisory_on_a_fixed_interpreter(capsys, monkeypatch):
    fixed = SimpleNamespace(
        wal_reset_vulnerable=False, wmi_stray_thread_vulnerable=False,
        sqlite_version_string="3.53.1", python_version_string="3.13.15")
    for module in (update_cmd, update_cmd_maint):
        monkeypatch.setattr(
            module, "_post_update_sqlite_runtime_status", lambda: (True, fixed))

    assert update_cmd._print_verified_update_completion("✓ Already up to date!") is True
    assert "gh-130727" not in capsys.readouterr().out
