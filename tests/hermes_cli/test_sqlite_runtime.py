"""Behavioral tests for exact-interpreter SQLite runtime inspection."""

from __future__ import annotations

import json
import os
import shlex
import sqlite3
import sys
from pathlib import Path

import pytest

from hermes_cli.sqlite_runtime import (
    REPAIR_REASON_SQLITE_WAL_RESET,
    REPAIR_REASON_WMI_STRAY_THREAD,
    SQLiteRuntimeInfo,
    WMI_STRAY_THREAD_FIXED,
    is_platform_wmi_stray_thread_vulnerable,
    is_sqlite_wal_reset_vulnerable,
    probe_sqlite_runtime,
)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((3, 6, 23), False),
        ((3, 7, 0), True),
        ((3, 44, 5), True),
        ((3, 44, 6), False),
        ((3, 45, 0), True),
        ((3, 50, 6), True),
        ((3, 50, 7), False),
        ((3, 51, 2), True),
        ((3, 51, 3), False),
        ((3, 53, 1), False),
    ],
)
def test_wal_reset_vulnerability_matrix(
    version: tuple[int, ...],
    expected: bool,
) -> None:
    assert is_sqlite_wal_reset_vulnerable(version) is expected


def test_probe_reports_the_requested_interpreters_linked_sqlite() -> None:
    info = probe_sqlite_runtime(sys.executable)

    assert info is not None
    assert info.executable.resolve() == Path(sys.executable).resolve()
    assert info.base_prefix.resolve() == Path(sys.base_prefix).resolve()
    assert info.python_version == sys.version_info[:3]
    assert info.platform == sys.platform
    assert info.sqlite_version == sqlite3.sqlite_version_info
    assert info.sqlite_version_string == sqlite3.sqlite_version

    with sqlite3.connect(":memory:") as conn:
        source_id = conn.execute("SELECT sqlite_source_id()").fetchone()[0]
    assert info.sqlite_source_id == source_id


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX executable probe stub")
def test_probe_uses_child_payload_and_sanitizes_python_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_python = tmp_path / "reported-python"
    payload = {
        "base_prefix": str(tmp_path / "reported-base"),
        "executable": str(fake_python),
        "python_version": [3, 11, 15],
        "sqlite_version": [9, 8, 7],
        "sqlite_version_string": "9.8.7-child",
        "sqlite_source_id": "child-source-id",
        "platform": "child-platform",
    }
    fake_python.write_text(
        "\n".join([
            "#!/bin/sh",
            '[ "$1" = "-I" ] && [ "$2" = "-c" ] || exit 10',
            '[ -z "${PYTHONHOME+x}" ] || exit 11',
            '[ -z "${PYTHONPATH+x}" ] || exit 12',
            f"printf '%s\\n' {shlex.quote(json.dumps(payload))}",
        ])
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "poison-home"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "poison-path"))

    info = probe_sqlite_runtime(fake_python)

    assert info is not None
    assert info.executable == fake_python
    assert info.base_prefix == tmp_path / "reported-base"
    assert info.sqlite_version == (9, 8, 7)
    assert info.sqlite_version_string == "9.8.7-child"
    assert info.sqlite_source_id == "child-source-id"
    assert info.platform == "child-platform"


@pytest.mark.parametrize(
    ("version", "platform", "expected"),
    [
        ((3, 11, 9), "win32", True),
        ((3, 12, 13), "win32", True),
        ((3, 13, 3), "win32", True),
        ((3, 13, 4), "win32", False),
        ((3, 13, 15), "win32", False),
        ((3, 14, 0), "win32", False),
        ((3, 12, 13), "linux", False),
        ((3, 12, 13), "darwin", False),
    ],
)
def test_platform_wmi_stray_thread_matrix(
    version: tuple[int, ...], platform: str, expected: bool,
) -> None:
    """CPython gh-130727: only Windows builds carry ``_wmi``, and only 3.13.4+ copies the query
    struct before the abandoned thread can touch the caller's handles."""
    assert WMI_STRAY_THREAD_FIXED == (3, 13, 4)
    assert is_platform_wmi_stray_thread_vulnerable(version, platform=platform) is expected


def test_platform_default_is_the_callers_host() -> None:
    expected = sys.platform == "win32" and sys.version_info[:3] < WMI_STRAY_THREAD_FIXED
    assert is_platform_wmi_stray_thread_vulnerable(sys.version_info[:3]) is expected
    info = SQLiteRuntimeInfo(
        executable=Path(sys.executable), base_prefix=Path(sys.base_prefix),
        python_version=sys.version_info[:3], sqlite_version=(3, 53, 1),
        sqlite_version_string="3.53.1", sqlite_source_id="fixed")
    assert info.platform == ""
    assert info.wmi_stray_thread_vulnerable is expected


def _info(python_version, sqlite_version, platform):
    return SQLiteRuntimeInfo(
        executable=Path("/venv/bin/python"), base_prefix=Path("/venv"),
        python_version=python_version, sqlite_version=sqlite_version,
        sqlite_version_string=".".join(map(str, sqlite_version)), sqlite_source_id="x",
        platform=platform)


def test_repair_reasons_combine_both_defects_in_report_order() -> None:
    assert _info((3, 12, 13), (3, 50, 4), "win32").repair_reasons == (
        REPAIR_REASON_SQLITE_WAL_RESET, REPAIR_REASON_WMI_STRAY_THREAD)
    assert _info((3, 12, 13), (3, 53, 1), "win32").repair_reasons == (
        REPAIR_REASON_WMI_STRAY_THREAD,)
    assert _info((3, 12, 13), (3, 50, 4), "linux").repair_reasons == (
        REPAIR_REASON_SQLITE_WAL_RESET,)
    fixed = _info((3, 13, 15), (3, 53, 1), "win32")
    assert fixed.repair_reasons == ()
    assert fixed.needs_repair is False
    assert fixed.python_version_string == "3.13.15"
