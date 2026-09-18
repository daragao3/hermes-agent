"""Import-safe helpers for inspecting a Python interpreter's linked SQLite and interpreter build.

This module intentionally depends only on the standard library. Installer and update code must be
able to use it before Hermes' third-party dependencies are healthy.

Two independent reasons make an interpreter one the managed-runtime repair must replace, and both
are answered from the same probe so ``managed_uv``, ``hermes doctor`` and ``hermes update`` cannot
disagree about the verdict:

* the linked SQLite carries the WAL-reset bug (``wal_reset_vulnerable``);
* the interpreter is a Windows CPython before 3.13.4, whose ``platform.uname()`` abandons its WMI
  query thread after a 100 ms timeout and lets that thread close a random live handle of the
  process (CPython gh-130727 / PR #134313, in 3.13.4 and 3.14.0b2, never backported to 3.12).
  Under host load that kills children with ``0xC000070A``; the ``hermes_bootstrap`` stub covers
  bootstrapped entry points only, so the real cure is the interpreter (``wmi_stray_thread_vulnerable``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# First CPython release that copies ``platform._wmi_query``'s stack struct before the query thread
# runs, so a timed-out query can no longer close the caller's handles (gh-130727).
WMI_STRAY_THREAD_FIXED = (3, 13, 4)

REPAIR_REASON_SQLITE_WAL_RESET = "sqlite-wal-reset"
REPAIR_REASON_WMI_STRAY_THREAD = "wmi-stray-thread"


def _version_tuple(parts: Iterable[object]) -> tuple[int, int, int]:
    values = [int(part) for part in parts]
    values.extend([0] * (3 - len(values)))
    return tuple(values[:3])


def is_sqlite_wal_reset_vulnerable(version_info: tuple[int, ...]) -> bool:
    """Return whether *version_info* contains SQLite's WAL-reset bug."""
    info = _version_tuple(version_info)
    return not (
        info < (3, 7, 0)
        or info >= (3, 51, 3)
        or (3, 50, 7) <= info < (3, 51, 0)
        or (3, 44, 6) <= info < (3, 45, 0))


def is_platform_wmi_stray_thread_vulnerable(
    python_version: tuple[int, ...], *, platform: str | None = None) -> bool:
    """Return whether a CPython *python_version* on *platform* (``sys.platform`` spelling, default
    the caller's) abandons ``platform.uname()``'s WMI thread (gh-130727). Only Windows builds carry
    the ``_wmi`` extension, so every other platform is safe regardless of version."""
    host = sys.platform if platform is None else platform
    return host == "win32" and _version_tuple(python_version) < WMI_STRAY_THREAD_FIXED


@dataclass(frozen=True)
class SQLiteRuntimeInfo:
    """SQLite and interpreter details reported by one exact Python executable."""

    executable: Path
    base_prefix: Path
    python_version: tuple[int, int, int]
    sqlite_version: tuple[int, int, int]
    sqlite_version_string: str
    sqlite_source_id: str
    # ``sys.platform`` of the probed interpreter; "" (older callers / hand-built infos) means the
    # caller's own platform, which is always the same host.
    platform: str = ""

    @property
    def wal_reset_vulnerable(self) -> bool:
        return is_sqlite_wal_reset_vulnerable(self.sqlite_version)

    @property
    def wmi_stray_thread_vulnerable(self) -> bool:
        return is_platform_wmi_stray_thread_vulnerable(
            self.python_version, platform=self.platform or None)

    @property
    def repair_reasons(self) -> tuple[str, ...]:
        """Every reason the managed-runtime repair must replace this interpreter, in the order the
        repair reports them; empty when the runtime is fine."""
        reasons = []
        if self.wal_reset_vulnerable:
            reasons.append(REPAIR_REASON_SQLITE_WAL_RESET)
        if self.wmi_stray_thread_vulnerable:
            reasons.append(REPAIR_REASON_WMI_STRAY_THREAD)
        return tuple(reasons)

    @property
    def needs_repair(self) -> bool:
        return bool(self.repair_reasons)

    @property
    def python_version_string(self) -> str:
        return ".".join(str(part) for part in self.python_version)


_PROBE_SCRIPT = """
import json, sqlite3, sys
conn = sqlite3.connect(":memory:")
try:
    row = conn.execute("SELECT sqlite_source_id()").fetchone()
finally:
    conn.close()
print(json.dumps({
    "base_prefix": sys.base_prefix, "executable": sys.executable,
    "python_version": list(sys.version_info[:3]), "sqlite_version": list(sqlite3.sqlite_version_info),
    "sqlite_version_string": sqlite3.sqlite_version,
    "sqlite_source_id": str(row[0]) if row and row[0] is not None else "",
    "platform": sys.platform,
}))
"""


def isolated_interpreter_env() -> dict[str, str]:
    """Copy of ``os.environ`` with conda/uv/venv/PYTHON* overrides stripped, so a child interpreter
    reports its *own* runtime rather than the caller's."""
    env = dict(os.environ)
    for key in ("CONDA_DEFAULT_ENV", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT",
                "UV_PYTHON", "VIRTUAL_ENV"):
        env.pop(key, None)
    return env


def probe_sqlite_runtime(python: str | Path, *, timeout: float = 30.0) -> SQLiteRuntimeInfo | None:
    """Probe SQLite in *python*, never the caller's linked SQLite."""
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", _PROBE_SCRIPT], capture_output=True, text=True, timeout=timeout,
            check=False, env=isolated_interpreter_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        return SQLiteRuntimeInfo(
            executable=Path(str(payload["executable"])), base_prefix=Path(str(payload["base_prefix"])),
            python_version=_version_tuple(payload["python_version"]),
            sqlite_version=_version_tuple(payload["sqlite_version"]),
            sqlite_version_string=str(payload["sqlite_version_string"]),
            sqlite_source_id=str(payload.get("sqlite_source_id", "")),
            platform=str(payload.get("platform", "")))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
