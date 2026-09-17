"""Resolve the ``bash`` a test should spawn -- never the WSL launcher.

On Windows ``subprocess.run(["bash", ...])`` does NOT resolve ``bash`` the way
``shutil.which("bash")`` does.  ``CreateProcess`` searches the application
directory, the current directory and ``%SystemRoot%\\System32`` *before*
``PATH``, and System32 carries ``bash.exe``: the WSL launcher.  So a bare
``bash`` from Python boots the default WSL distro (Ubuntu here) and runs the
script inside Linux, while ``shutil.which`` reports Git's bash.  Measured
2026-09-15: ``subprocess.run(["bash", "-c", "uname -a"])`` printed
``Linux ... microsoft-standard-WSL2 ... WSL_DISTRO_NAME=Ubuntu`` while
``shutil.which("bash")`` was ``C:\\Program Files\\Git\\usr\\bin\\bash.EXE``.

That detour is not free.  Every such spawn boots the Ubuntu instance; when the
script exits WSL terminates the instance, its systemd ``poweroff`` hangs and
WSL escalates to ``reboot(RB_POWER_OFF)`` on the utility VM that Docker
Desktop's ``docker-desktop`` distro shares -- which took the Docker engine
(and gbrain's Postgres) down mid-operation on 2026-09-15 21:51Z.  Nine such
escalations were logged that day, one per test invocation.  Record: MemPalace
``hermes/gbrain-token-store-503-2026-09-15``.

Usage::

    from tests.bash_support import BASH

    subprocess.run([BASH, "-c", script])

:data:`BASH` is ``"bash"`` on POSIX (there is no System32 trap) and, on
Windows, an absolute path to a non-WSL bash: the one ``shutil.which`` finds
unless that lives under ``%SystemRoot%``, else Git for Windows' copy.  When no
usable bash exists the value is still ``"bash"`` so the calling test fails
the way it always did (``FileNotFoundError``) rather than silently skipping.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _under_system_root(path: str) -> bool:
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def resolve_bash() -> str:
    """Path to a bash that runs on the host, not inside WSL.  Pure of side effects."""
    if sys.platform != "win32":
        return "bash"
    found = shutil.which("bash")
    if found and not _under_system_root(found):
        return found
    program_files = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files",
    ]
    for base in program_files:
        if not base:
            continue
        for candidate in (
            Path(base) / "Git" / "bin" / "bash.exe",
            Path(base) / "Git" / "usr" / "bin" / "bash.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return "bash"


def bash_path(path: "str | Path") -> str:
    """Spell *path* the way ``BASH`` expects it inside a script or argv.

    On Windows ``BASH`` is Git's MSYS bash, which mounts drives as ``/c/...``; a raw
    ``C:\\Users\\...`` interpolated into ``bash -c`` loses its backslashes as escapes
    (``C:UsersdiegoAppData...: No such file or directory``). Elsewhere the path is
    returned unchanged. The WSL launcher's ``/mnt/c/...`` form is never produced.
    """
    path = Path(path)
    if os.name != "nt":
        return str(path)
    drive = path.drive.rstrip(":").lower()
    tail = path.as_posix().split(":", 1)[1].lstrip("/")
    return f"/{drive}/{tail}"


BASH = resolve_bash()

# A ``pwd`` whose output a test can hand to ``os.path.realpath``. Git's MSYS bash
# answers in mount form -- ``/tmp/x`` for %TEMP% (where every ``tmp_path`` lives),
# ``/c/Users/x`` for a drive -- and Python resolves ``/tmp`` against ``C:\``, so
# the comparison fails on a command that ran exactly where it should. ``-W`` is
# the MSYS extension that prints the native spelling; ``-P -W`` in that order
# (the last flag wins) keeps it physical, and the fallback covers a bash without
# ``-W``. Elsewhere it is plain ``pwd``, unchanged.
NATIVE_PWD = "pwd -P -W 2>/dev/null || pwd -P" if os.name == "nt" else "pwd"
