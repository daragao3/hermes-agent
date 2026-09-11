"""Local dashboard contracts survive upstream's helper extraction."""

import os
import subprocess

import pytest


def test_provider_setup_uses_bounded_capture(monkeypatch):
    from hermes_cli import web_server_memory as memory
    from hermes_cli import _subprocess_compat

    calls = []
    expected = subprocess.CompletedProcess("setup", 0, "ok", "")

    def capture(command, **kwargs):
        calls.append((command, kwargs))
        return expected

    monkeypatch.setattr(_subprocess_compat, "run_text_capture", capture)
    monkeypatch.setattr(memory, "_memory_provider_setup_env", lambda: {"TASK_ENV": "test"})
    monkeypatch.setattr(memory.subprocess, "run", lambda *a, **k: pytest.fail("unbounded setup capture"))
    assert memory._run_setup_command("setup", display="setup", shell=True, timeout=17) is expected
    assert calls == [("setup", {
        "shell": True,
        "executable": None if os.name == "nt" else "/bin/bash",
        "env": {"TASK_ENV": "test"},
        "timeout": 17,
    })]


def test_hosted_root_compares_resolved_paths(monkeypatch, tmp_path):
    from hermes_cli import web_server_files as files
    import hermes_constants

    root = tmp_path / "hosted"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setattr(hermes_constants, "get_default_hermes_root", lambda: root)
    monkeypatch.setattr(files, "_HOSTED_MANAGED_FILES_ROOT", root / ".." / "hosted")
    assert files._default_hermes_root_is_opt_data()
    monkeypatch.setattr(files, "_HOSTED_MANAGED_FILES_ROOT", tmp_path / "elsewhere")
    assert not files._default_hermes_root_is_opt_data()
