"""Inline ``!`cmd``` skill snippets run on the host, never inside a WSL distro.

On Windows ``subprocess`` resolves a bare ``bash`` through ``CreateProcess``,
which searches ``System32`` before ``PATH`` -- and ``System32\bash.exe`` is the
WSL launcher.  ``shutil.which("bash")`` (PATH-only) reports Git Bash for the
same name, so nothing else in the process notices.  Measured 2026-09-16 from
the agent-src venv: ``subprocess.run(["bash", "-c", "uname -r"])`` printed
``microsoft-standard-WSL2`` with ``WSL_DISTRO_NAME=Ubuntu`` after a 12 s
distro boot.  ``run_inline_shell`` now spawns the bash ``_host_bash`` resolves.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent import skill_preprocessing


def test_host_bash_is_a_plain_name_off_windows(monkeypatch):
    monkeypatch.setattr(skill_preprocessing.sys, "platform", "linux")
    assert skill_preprocessing._host_bash() == "bash"


def test_inline_shell_reports_missing_bash_instead_of_spawning(monkeypatch):
    spawned = []
    monkeypatch.setattr(skill_preprocessing, "_host_bash", lambda: None)
    monkeypatch.setattr(skill_preprocessing, "run_text_capture", lambda *a, **k: spawned.append(a))
    assert skill_preprocessing.run_inline_shell("echo ok", None, 5) == "[inline-shell error: bash not found]"
    assert spawned == []


@pytest.mark.windows_only
def test_host_bash_is_not_the_wsl_launcher():
    resolved = skill_preprocessing._host_bash()
    assert resolved, "no Git Bash found -- the inline-shell snippet has nothing to run under"
    path = Path(resolved)
    assert path.is_absolute(), "a bare name re-enters the System32-first search order"
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    assert not path.resolve().is_relative_to(system_root), f"{path} is the WSL launcher"


@pytest.mark.windows_only
def test_inline_shell_runs_on_the_host_not_in_wsl():
    out = skill_preprocessing.run_inline_shell(
        'printf "%s|%s" "${WSL_DISTRO_NAME-}" "$(uname -r 2>/dev/null)"', None, 60)
    assert not out.startswith("[inline-shell"), out
    distro, kernel = out.split("|", 1)
    assert distro == "", f"snippet ran inside WSL distro {distro!r}"
    assert "microsoft" not in kernel.lower(), f"snippet ran on a WSL kernel: {kernel!r}"
