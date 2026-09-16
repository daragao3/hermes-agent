"""The bash a test spawns runs on the host, not inside a WSL distro.

Contract for :mod:`tests.bash_support`.  The failure it pins was measured on
2026-09-15: ``subprocess.run(["bash", ...])`` on Windows resolves through
``CreateProcess``'s search order to ``%SystemRoot%\\System32\\bash.exe`` -- the
WSL launcher -- so five test files were booting the Ubuntu distro on every
run, and each teardown's hung ``systemd poweroff`` escalated to
``reboot(RB_POWER_OFF)`` on the utility VM Docker Desktop shares.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.bash_support import BASH, resolve_bash


@pytest.mark.windows_only
def test_resolved_bash_is_not_the_wsl_launcher() -> None:
    """Whatever bash we pick, it must not be the one under %SystemRoot%."""
    path = Path(resolve_bash())
    assert path.is_absolute(), "on Windows a bare name re-enters the System32 search order"
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    assert not path.resolve().is_relative_to(system_root), (
        f"{path} is the WSL launcher; a spawn would boot the default distro"
    )


@pytest.mark.windows_only
def test_spawned_bash_runs_on_the_host_not_in_wsl() -> None:
    """A WSL bash exports WSL_DISTRO_NAME and reports a microsoft kernel."""
    proc = subprocess.run(
        [BASH, "-c", 'printf "%s|%s" "${WSL_DISTRO_NAME-}" "$(uname -r 2>/dev/null)"'],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    distro, kernel = proc.stdout.split("|", 1)
    assert distro == "", f"bash ran inside WSL distro {distro!r}"
    assert "microsoft" not in kernel.lower(), f"bash ran on a WSL kernel: {kernel!r}"
