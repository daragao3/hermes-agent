"""Tests for hermes_cli.managed_uv — one path, no guessing."""

from __future__ import annotations
import os

import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Host-native managed-uv binary name: managed_uv_path() installs `uv` on
# POSIX and `uv.exe` on Windows. Fixtures must build what the real host
# resolves — no platform fake.
_UV_BINARY_NAME = "uv.exe" if sys.platform == "win32" else "uv"


def _make_executable(path: Path) -> None:
    """Create a minimal fake uv binary at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho uv 0.1.2\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _runtime_info(
    executable: Path,
    sqlite_version: tuple[int, int, int],
    python_version: tuple[int, int, int] = (3, 11, 15),
    platform: str = "linux",
):
    """A probe result for tests. ``platform`` is pinned (not the host's) so the SQLite-themed
    tests read the same on Windows, where a 3.11 interpreter would also carry the WMI reason."""
    from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

    return SQLiteRuntimeInfo(
        executable=executable,
        base_prefix=executable.parent.parent,
        python_version=python_version,
        sqlite_version=sqlite_version,
        sqlite_version_string=".".join(str(part) for part in sqlite_version),
        sqlite_source_id=f"source-{sqlite_version}",
        platform=platform,
    )


def _RRR(status):
    """not-applicable RuntimeRepairResult for tests that neutralize the
    repair hook. ensure_uv()/update_managed_uv() invoke runtime repair as a
    side effect; unmocked, it probes the REAL checkout's venv/.venv — on CI
    the repo .venv links vulnerable SQLite, so repair fires for real and
    re-invokes _install_uv (uv-refresh retry), breaking call-count asserts.
    """
    from hermes_cli.managed_uv import RuntimeRepairResult

    return RuntimeRepairResult(status)


def _make_runtime_install(
    tmp_path: Path,
    *,
    windows: bool = False,
) -> tuple[Path, Path, Path]:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    live = root / "venv"
    bin_dir = live / ("Scripts" if windows else "bin")
    bin_dir.mkdir(parents=True)
    python = bin_dir / ("python.exe" if windows else "python")
    python.write_text("live interpreter", encoding="utf-8")
    sentinel = live / "sentinel"
    sentinel.write_text("live", encoding="utf-8")
    return root, live, sentinel


def _park_backup(root: Path, live: Path, *, epoch: int, mtime: float | None = None) -> Path:
    """A parked venv next to *live*, named the way ``_cut_over_candidate`` names it
    (``<live>.stale.runtime-<epoch>-<pid>-<hex8>``). *epoch* is the parking time the
    sweep must read; *mtime* (default: now) is the directory stat, which on a real
    parked venv is the build time and says nothing about when it was parked."""
    import os

    backup = root / f"{live.name}.stale.runtime-{epoch}-{os.getpid()}-{'%08x' % epoch}"
    (backup / "bin").mkdir(parents=True)
    if mtime is not None:
        os.utime(backup, (mtime, mtime))
    return backup


# ---------------------------------------------------------------------------
# managed_uv_path
# ---------------------------------------------------------------------------

class TestManagedUvPath:
    # POSIX arm of the name mapping; the Windows arm (uv.exe) is exercised
    # for real by TestEnsureUvWindowsSafe on the Windows lane.
    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: bin/uv name")
    def test_posix(self, tmp_path):
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path):
            from hermes_cli.managed_uv import managed_uv_path
            assert managed_uv_path() == tmp_path / "bin" / "uv"


class TestMacOSManagedPythonSigning:
    def test_signs_with_stable_identifier_and_verifies(self, tmp_path, monkeypatch):
        import hermes_cli.managed_uv as managed_uv

        python = tmp_path / "generation" / "bin" / "python3.11"
        python.parent.mkdir(parents=True)
        python.touch()
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(managed_uv, "host_system", lambda: "Darwin")
        monkeypatch.setattr(managed_uv.shutil, "which", lambda name: "/usr/bin/codesign")
        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)

        assert managed_uv._macos_sign_managed_python(python) is True
        assert calls[0][0] == [
            "/usr/bin/codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--timestamp=none",
            "--identifier",
            "com.nousresearch.hermes.managed-python",
            "--requirements",
            '=designated => identifier "com.nousresearch.hermes.managed-python"',
            str(python),
        ]
        assert calls[1][0] == [
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            str(python),
        ]

    def test_is_non_blocking_when_signing_fails(self, tmp_path, monkeypatch):
        import hermes_cli.managed_uv as managed_uv

        python = tmp_path / "python3.11"
        monkeypatch.setattr(managed_uv, "host_system", lambda: "Darwin")
        monkeypatch.setattr(managed_uv.shutil, "which", lambda name: "/usr/bin/codesign")
        monkeypatch.setattr(
            managed_uv.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(
                returncode=1, stdout="", stderr="not signable"
            ),
        )

        assert managed_uv._macos_sign_managed_python(python) is False

    def test_skips_non_macos(self, tmp_path, monkeypatch):
        import hermes_cli.managed_uv as managed_uv

        monkeypatch.setattr(managed_uv, "host_system", lambda: "Linux")
        monkeypatch.setattr(
            managed_uv.subprocess,
            "run",
            lambda *args, **kwargs: pytest.fail("codesign must not run on Linux"),
        )

        assert managed_uv._macos_sign_managed_python(tmp_path / "python") is False


# ---------------------------------------------------------------------------
# resolve_uv
# ---------------------------------------------------------------------------

class TestResolveUv:

    def test_existing_executable(self, tmp_path):
        uv = tmp_path / "bin" / _UV_BINARY_NAME
        _make_executable(uv)
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path):
            from hermes_cli.managed_uv import resolve_uv
            result = resolve_uv()
            assert result == str(uv)

    def test_non_executable_file_returns_none(self, tmp_path):
        uv = tmp_path / "bin" / "uv"
        uv.parent.mkdir(parents=True)
        uv.write_text("not a binary", encoding="utf-8")
        # Ensure no execute bit
        uv.chmod(0o644)
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path):
            from hermes_cli.managed_uv import resolve_uv
            assert resolve_uv() is None


# ---------------------------------------------------------------------------
# ensure_uv
# ---------------------------------------------------------------------------

class TestEnsureUv:

    def test_installs_if_missing(self, tmp_path):
        uv = tmp_path / "bin" / _UV_BINARY_NAME
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime", return_value=_RRR("not-applicable")), \
             patch("hermes_cli.managed_uv._uv_version", return_value="uv 0.1.2"), \
             patch("hermes_cli.managed_uv._install_uv") as mock_install:
            # Simulate the installer creating the binary (host-native name:
            # uv.exe on Windows, uv on POSIX).
            def fake_install(target):
                _make_executable(target)
            mock_install.side_effect = fake_install

            from hermes_cli.managed_uv import ensure_uv
            path = ensure_uv()
            assert path == str(uv)
            mock_install.assert_called_once()

    def test_install_reports_runtime_repair_to_observer(self, tmp_path):
        from hermes_cli.managed_uv import (
            RuntimeRepairResult,
            ensure_uv,
        )

        repair = RuntimeRepairResult(
            "repaired",
            sqlite_before="3.50.4",
            sqlite_after="3.53.1",
        )

        def fake_install(target):
            _make_executable(target)

        observed = []
        with patch(
            "hermes_cli.managed_uv.get_hermes_home",
            return_value=tmp_path,
        ), patch(
            "hermes_cli.managed_uv._install_uv",
            side_effect=fake_install,
        ), patch(
            "hermes_cli.managed_uv._uv_version",
            return_value="uv 0.1.2",
        ), patch(
            "hermes_cli.managed_uv.repair_vulnerable_runtime",
            return_value=repair,
        ):
            path = ensure_uv(repair_observer=observed.append)

        assert path == str(tmp_path / "bin" / _UV_BINARY_NAME)
        assert observed == [repair]


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only: the _UvResult dual contract is not offered on Windows")
class TestEnsureUvUpdateBoundary:
    """``ensure_uv()`` must answer to both the single-value and the legacy
    ``(path, fresh_bootstrap)`` call conventions — **on POSIX**.

    ``hermes update`` runs the call site from the old, already-imported
    ``hermes_cli.main`` against the freshly pulled ``managed_uv``. A release
    parked on a ``(path, fresh)`` tuple runs ``uv_bin, fresh = ensure_uv()``
    against the single-value module; the path is an iterable ``str`` so the
    2-target unpack walked its characters and raised
    ``ValueError: too many values to unpack (expected 2)`` (root cause behind
    PR #39763), or ``TypeError`` on the ``None`` failure path. On POSIX the
    result must therefore be usable as a bare path *and* unpackable as a
    2-tuple, in both the success and failure cases.

    The dual contract is intentionally **not** offered on Windows — see
    ``TestEnsureUvWindowsSafe`` for why — so these tests are POSIX-only: the
    host's real ``host_system()`` selects the wrapper branch, nothing is
    faked.
    """

    def test_success_usable_as_single_value(self, tmp_path):
        _make_executable(tmp_path / "bin" / "uv")
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime", return_value=_RRR("not-applicable")):
            from hermes_cli.managed_uv import ensure_uv
            uv_bin = ensure_uv()
            assert uv_bin == str(tmp_path / "bin" / "uv")
            assert bool(uv_bin) is True

    def test_success_unpacks_as_legacy_two_tuple(self, tmp_path):
        _make_executable(tmp_path / "bin" / "uv")
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime", return_value=_RRR("not-applicable")):
            from hermes_cli.managed_uv import ensure_uv
            uv_bin, fresh = ensure_uv()  # old: uv_bin, fresh_bootstrap = ensure_uv()
            assert uv_bin == str(tmp_path / "bin" / "uv")
            assert fresh is False

    def test_failure_unpacks_without_raising(self, tmp_path):
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime", return_value=_RRR("not-applicable")), \
             patch("hermes_cli.managed_uv._install_uv", side_effect=RuntimeError("network down")):
            from hermes_cli.managed_uv import ensure_uv
            uv_bin, fresh = ensure_uv()
            assert uv_bin is None
            assert fresh is False


class TestEnsureUvWindowsSafe:
    """On Windows ``ensure_uv()`` must return a plain ``str``/``None``.

    ``subprocess`` on Windows serializes argv through
    ``subprocess.list2cmdline``, which iterates every entry *as a string*
    (``for c in arg``). The dependency installer feeds uv straight into the
    command list (``[uv_bin, "pip", "install", ...]``). A ``str`` subclass
    whose ``__iter__`` yields ``(path, fresh_bootstrap)`` instead of characters
    therefore injects the bool into the command line and crashes the install
    with ``TypeError: sequence item 1: expected str instance, bool found``
    (a real field report on a 10-commits-behind Windows install). A single
    return value cannot serve both the legacy 2-tuple unpack and Windows
    char-iteration — both use the iterator protocol — so Windows opts out of
    the wrapper entirely.
    """

    def test_uvresult_would_break_windows_list2cmdline(self):
        # Canary: this is *why* the wrapper is gated off Windows. If a future
        # change makes _UvResult char-iterable (and thus list2cmdline-safe),
        # the gate may be revisited.
        import subprocess
        from hermes_cli.managed_uv import _UvResult
        with pytest.raises(TypeError):
            subprocess.list2cmdline([_UvResult("C:\\hermes\\uv.exe"), "pip"])

    @pytest.mark.windows_only
    def test_windows_returns_plain_str_safe_for_subprocess(self, tmp_path):
        """``windows_only``: the subject is the real Windows opt-out branch and
        ``subprocess.list2cmdline`` — the faked ``platform.system`` only ever
        proved the branch existed, not that the field crash was fixed on the
        host that reported it."""
        import subprocess
        # On Windows the managed binary is uv.exe.
        _make_executable(tmp_path / "bin" / "uv.exe")
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime", return_value=_RRR("not-applicable")):
            from hermes_cli.managed_uv import _UvResult, ensure_uv
            uv_bin = ensure_uv()
            assert type(uv_bin) is str and not isinstance(uv_bin, _UvResult)
            # The exact operation that crashed in the field must now succeed.
            cmdline = subprocess.list2cmdline([uv_bin, "pip", "install", "-e", "."])
            assert "pip" in cmdline and "install" in cmdline


# ---------------------------------------------------------------------------
# update_managed_uv
# ---------------------------------------------------------------------------

class TestUpdateManagedUv:



    def test_fresh_stamp_skips_network_self_update_but_not_repair(self, tmp_path):
        """A recent success stamp must skip `uv self update` entirely while the
        vulnerable-runtime repair probe still runs (CVE repair is never gated)."""
        import time

        from hermes_cli.managed_uv import RuntimeRepairResult, update_managed_uv

        uv = tmp_path / "bin" / _UV_BINARY_NAME
        _make_executable(uv)
        # The stamp reader imports get_hermes_home separately from the binary
        # resolver. Give both paths the same explicit test root.
        stamp = tmp_path / "cache" / ".uv_self_update_stamp"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        # File timestamps can lead time.time() briefly on Windows. Stay well
        # inside the freshness window instead of racing its age >= 0 boundary.
        recent = time.time() - 60
        os.utime(stamp, (recent, recent))

        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv._uv_self_update_stamp", return_value=stamp), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime",
                   return_value=RuntimeRepairResult("skipped")) as mock_repair, \
             patch("hermes_cli.managed_uv.subprocess.run") as mock_run:
            result = update_managed_uv()

        assert result == str(uv)
        assert mock_run.call_count == 0, "fresh stamp must skip the network self-update"
        mock_repair.assert_called_once_with(str(uv))


    def test_stale_stamp_runs_self_update_and_refreshes_stamp(self, tmp_path):
        import os as _os
        import time as _time

        from hermes_cli.managed_uv import UV_SELF_UPDATE_INTERVAL_SECONDS, update_managed_uv

        uv = tmp_path / "bin" / _UV_BINARY_NAME
        _make_executable(uv)
        # Keep the stamp and binary resolver in the same test root.
        stamp = tmp_path / "cache" / ".uv_self_update_stamp"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        old = _time.time() - UV_SELF_UPDATE_INTERVAL_SECONDS - 60
        _os.utime(stamp, (old, old))

        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv._uv_self_update_stamp", return_value=stamp), \
             patch("hermes_cli.managed_uv.repair_vulnerable_runtime", return_value=_RRR("not-applicable")), \
             patch("hermes_cli.managed_uv._uv_version", return_value="uv 0.2.0"), \
             patch("hermes_cli.managed_uv.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="uv 0.2.0")
            update_managed_uv()

        assert mock_run.call_args_list[0][0][0] == [str(uv), "self", "update"]
        assert stamp.stat().st_mtime > old + 30, "successful self-update must refresh the stamp"




class TestManagedPythonStore:
    def test_store_is_checkout_scoped_across_profiles(self, tmp_path, monkeypatch):
        from hermes_cli.managed_uv import managed_python_install_dir

        checkout = tmp_path / "checkout"
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "alpha"))
        alpha = managed_python_install_dir(checkout)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "beta"))
        beta = managed_python_install_dir(checkout)

        expected = checkout / ".hermes-runtime" / "python"
        assert alpha == expected
        assert beta == expected

    def test_environment_is_private_and_sanitized(self, tmp_path):
        from hermes_cli.managed_uv import managed_python_env

        checkout = tmp_path / "checkout"
        base_env = {
            "KEEP_ME": "yes",
            "CONDA_DEFAULT_ENV": "poison",
            "CONDA_PREFIX": "/poison/conda",
            "UV_PROJECT_ENVIRONMENT": "/poison/project",
            "UV_NO_MANAGED_PYTHON": "1",
            "UV_PYTHON": "/poison/python",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_SYSTEM_PYTHON": "1",
            "VIRTUAL_ENV": "/poison/venv",
            "PYTHONHOME": "/poison/home",
            "PYTHONPATH": "/poison/path",
        }

        env = managed_python_env(checkout, base_env=base_env)

        assert env["KEEP_ME"] == "yes"
        assert env["UV_MANAGED_PYTHON"] == "1"
        assert env["UV_NO_CONFIG"] == "1"
        assert env["UV_PYTHON_INSTALL_BIN"] == "0"
        assert env["UV_PYTHON_INSTALL_REGISTRY"] == "0"
        assert env["UV_PYTHON_INSTALL_DIR"] == str(
            checkout / ".hermes-runtime" / "python"
        )
        for key in (
            "CONDA_DEFAULT_ENV",
            "CONDA_PREFIX",
            "UV_PROJECT_ENVIRONMENT",
            "UV_NO_MANAGED_PYTHON",
            "UV_PYTHON",
            "UV_PYTHON_DOWNLOADS",
            "UV_SYSTEM_PYTHON",
            "VIRTUAL_ENV",
            "PYTHONHOME",
            "PYTHONPATH",
        ):
            assert key not in env
        assert base_env["PYTHONHOME"] == "/poison/home"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only: fixtures build the bin/ (not Scripts/) venv layout")
class TestRuntimeRepair:
    def test_safe_runtime_is_a_noop(self, tmp_path):
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path)
        current = _runtime_info(live / "bin" / "python", (3, 53, 1))
        with patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 return_value=current,
             ), \
             patch(
                 "hermes_cli.managed_uv._install_safe_python_generation"
             ) as mock_install:
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "safe"
        assert result.sqlite_before == "3.53.1"
        assert result.sqlite_after == "3.53.1"
        assert sentinel.read_text(encoding="utf-8") == "live"
        assert not (root / ".hermes-runtime").exists()
        mock_install.assert_not_called()

    def test_failed_candidate_preserves_live_venv(self, tmp_path):
        from hermes_cli.managed_uv import (
            _acquire_repair_lock,
            _release_repair_lock,
            repair_vulnerable_runtime,
        )

        root, live, sentinel = _make_runtime_install(tmp_path)
        current = _runtime_info(live / "bin" / "python", (3, 50, 4))
        generation = root / ".hermes-runtime" / "python" / "generation-test"
        candidate_python = generation / "bin" / "python"
        candidate_python.parent.mkdir(parents=True)
        candidate_python.write_text("candidate interpreter", encoding="utf-8")
        fixed = _runtime_info(candidate_python, (3, 53, 1))

        with patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 side_effect=[current, current],
             ), \
             patch(
                 "hermes_cli.managed_uv._install_safe_python_generation",
                 return_value=(generation, candidate_python, fixed),
             ), \
             patch(
                 "hermes_cli.managed_uv._stage_candidate_venv",
                 return_value=None,
             ):
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "failed"
        assert "replacement environment" in result.detail
        assert sentinel.read_text(encoding="utf-8") == "live"
        assert (live / "bin" / "python").read_text(encoding="utf-8") == (
            "live interpreter"
        )
        assert not generation.exists()
        reacquired = _acquire_repair_lock(root / ".hermes-runtime")
        assert reacquired is not None
        _release_repair_lock(reacquired)

    def test_safe_runtime_sweeps_old_stale_backups(self, tmp_path):
        """A fixed runtime reclaims aged venv.stale.runtime-* leftovers
        (issue #73109) but leaves fresh ones (possible in-flight repair).

        "Aged" and "fresh" are the token epoch in the NAME (what ``_cut_over_candidate``
        mints at parking time), not directory mtime -- see the class of tests below."""
        import time as _time

        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path)
        old_backup = _park_backup(root, live, epoch=int(_time.time()) - 7200)
        (old_backup / "bin" / "python").write_text("old", encoding="utf-8")

        fresh_backup = _park_backup(root, live, epoch=int(_time.time()))

        current = _runtime_info(live / "bin" / "python", (3, 53, 1))
        with patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 return_value=current,
             ):
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "safe"
        assert not old_backup.exists(), "aged stale backup must be reclaimed"
        assert fresh_backup.exists(), "fresh backup may be an in-flight repair"
        assert sentinel.read_text(encoding="utf-8") == "live"

    def test_successful_repair_removes_parked_backup(self, tmp_path):
        """After a successful cutover the parked venv is removed instead of
        leaking ~1 GB at the project root forever (issue #73109)."""
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path)
        current = _runtime_info(live / "bin" / "python", (3, 50, 4))
        generation = root / ".hermes-runtime" / "python" / "generation-test"
        candidate_python = generation / "bin" / "python"
        candidate_python.parent.mkdir(parents=True)
        candidate_python.write_text("candidate interpreter", encoding="utf-8")
        fixed = _runtime_info(candidate_python, (3, 53, 1))
        candidate_venv = root / ".hermes-runtime" / "venv-candidate"
        (candidate_venv / "bin").mkdir(parents=True)
        (candidate_venv / "bin" / "python").write_text(
            "candidate venv interpreter", encoding="utf-8"
        )

        with patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 side_effect=[current, current],
             ), \
             patch(
                 "hermes_cli.managed_uv._install_safe_python_generation",
                 return_value=(generation, candidate_python, fixed),
             ), \
             patch(
                 "hermes_cli.managed_uv._stage_candidate_venv",
                 return_value=candidate_venv,
             ), \
             patch(
                 "hermes_cli.managed_uv._smoke_candidate_venv",
                 return_value=(True, "", fixed),
             ):
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "repaired"
        assert result.backup_venv is not None
        assert not result.backup_venv.exists(), (
            "parked venv must be removed after a successful repair"
        )
        leftovers = list(root.glob(f"{live.name}.stale.runtime-*"))
        assert leftovers == [], f"no stale markers may remain: {leftovers}"


class TestStaleBackupAgeIsTheParkingTime:
    """The sweep's age gate reads the token epoch in the backup's NAME, never directory stat.

    A rename preserves ``st_mtime`` (NTFS also keeps ``st_ctime`` = creation time), so the
    parked copy of a venv built weeks ago stats as weeks old the moment it is parked. Measured
    2026-09-18: the rollback backup of a 3.12->3.13 cut-over, parked at 00:50, was reaped by
    a 24 h-gated sweep at 03:52 with a reported age of 52 days. The token epoch is minted by
    ``_token()`` at parking time and is the only record of it.
    """

    def test_fresh_token_with_old_directory_mtime_survives(self, tmp_path):
        """THE 2026-09-18 CASE: built long ago, parked just now -> still a rollback path."""
        import time as _time

        from hermes_cli.managed_uv import _sweep_stale_runtime_backups

        root, live, _sentinel = _make_runtime_install(tmp_path)
        weeks_ago = _time.time() - 52 * 86400
        backup = _park_backup(root, live, epoch=int(_time.time()), mtime=weeks_ago)
        assert _time.time() - backup.stat().st_mtime > 24 * 3600, "fixture must stat as old"

        _sweep_stale_runtime_backups(live, root=root, min_age_seconds=24 * 3600)

        assert backup.is_dir(), "a backup parked seconds ago was reaped on its directory mtime"

    def test_old_token_with_fresh_directory_mtime_is_reclaimed(self, tmp_path):
        """The converse: parked days ago, touched since (an rmtree that gave up half-way,
        a scan writing a marker) -> still a leftover; mtime must not resurrect it."""
        import time as _time

        from hermes_cli.managed_uv import _sweep_stale_runtime_backups

        root, live, _sentinel = _make_runtime_install(tmp_path)
        backup = _park_backup(root, live, epoch=int(_time.time()) - 3 * 86400, mtime=_time.time())

        _sweep_stale_runtime_backups(live, root=root, min_age_seconds=24 * 3600)

        assert not backup.exists(), "an old backup was kept because its directory mtime was fresh"

    def test_unparseable_name_falls_back_to_the_stat_rule(self, tmp_path, monkeypatch):
        """A hand-named ``.stale.runtime-<something>`` has no epoch to read: the NEWEST of
        st_mtime/st_ctime decides. Old on both -> reclaimed; old mtime but a newer ctime
        (POSIX: the rename itself bumps ctime) -> kept.

        The stat is a seam here, not the filesystem: ``os.utime`` cannot age st_ctime on any
        host (NTFS reports creation time there; POSIX resets it to now on the utime call),
        so the aged directory cannot be built for real. The freshly created one can."""
        import os
        import time as _time

        from hermes_cli.managed_uv import _sweep_stale_runtime_backups

        root, live, _sentinel = _make_runtime_install(tmp_path)
        old = root / f"{live.name}.stale.runtime-manual-old"
        touched = root / f"{live.name}.stale.runtime-manual-touched"
        fresh = root / f"{live.name}.stale.runtime-manual-fresh"
        for d in (old, touched, fresh):
            (d / "bin").mkdir(parents=True)
        now = _time.time()
        days3 = now - 3 * 86400
        stamps = {old: (days3, days3), touched: (days3, now)}  # (st_mtime, st_ctime)
        real_stat = Path.stat

        def stat_with_stamps(self, *args, **kwargs):
            st = real_stat(self, *args, **kwargs)
            if self not in stamps:
                return st
            mtime, ctime = stamps[self]
            return os.stat_result(tuple(st)[:7] + (st.st_atime, mtime, ctime))

        monkeypatch.setattr(Path, "stat", stat_with_stamps)
        _sweep_stale_runtime_backups(live, root=root, min_age_seconds=24 * 3600)

        assert not old.exists(), "unparseable + old on both stat fields must be reclaimed"
        assert touched.is_dir(), "a newer st_ctime must win over an old st_mtime"
        assert fresh.is_dir(), "unparseable + fresh stat must be kept"

    def test_parked_at_reads_exactly_the_token_shape(self, tmp_path):
        """``_token()``'s own output parses to its epoch; anything looser (a date-like
        ``2026-09-18-manual``) must NOT be read as an epoch, or a hand-parked backup
        would count as 56 years old."""
        import time as _time

        from hermes_cli.managed_uv import _stale_backup_parked_at, _token

        root, live, _sentinel = _make_runtime_install(tmp_path)
        before = int(_time.time())
        token = _token()
        minted = root / f"{live.name}.stale.runtime-{token}"
        minted.mkdir()
        assert before <= _stale_backup_parked_at(minted, live.name) <= _time.time()

        datelike = root / f"{live.name}.stale.runtime-2026-09-18-manual"
        datelike.mkdir()
        assert _stale_backup_parked_at(datelike, live.name) >= before, (
            "a date-like name was parsed as an epoch")

        missing = root / f"{live.name}.stale.runtime-gone"
        assert _stale_backup_parked_at(missing, live.name) >= before, (
            "an unstat-able candidate must read as fresh, never as reapable")

    def test_keep_still_exempts_the_backup_this_repair_created(self, tmp_path):
        """``keep=`` semantics are untouched by the age source: exempt even when old."""
        import time as _time

        from hermes_cli.managed_uv import _sweep_stale_runtime_backups

        root, live, _sentinel = _make_runtime_install(tmp_path)
        kept = _park_backup(root, live, epoch=int(_time.time()) - 3 * 86400)

        _sweep_stale_runtime_backups(live, root=root, keep=kept, min_age_seconds=24 * 3600)

        assert kept.is_dir()


class TestStageCandidateVenvCrossPlatform:
    """Candidate sync preserves project config and streams progress on every host."""

    def test_sync_keeps_uv_project_config_and_merges_stderr(self, tmp_path):
        import subprocess

        from hermes_cli.managed_uv import _stage_candidate_venv

        root = tmp_path / "checkout"
        root.mkdir()
        (root / "uv.lock").write_text("# lock\n", encoding="utf-8")
        generation = root / ".hermes-runtime" / "python" / "gen"
        python = generation / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("py", encoding="utf-8")

        calls = []

        def fake_run(argv, **kwargs):
            calls.append((list(argv), kwargs))
            return MagicMock(returncode=0)

        with patch("hermes_cli.managed_uv.subprocess.run", side_effect=fake_run), \
             patch(
                 "hermes_cli.managed_uv._smoke_candidate_venv",
                 return_value=(True, "", None),
             ):
            candidate = _stage_candidate_venv(
                "uv",
                project_root=root,
                generation=generation,
                python=python,
            )

        assert candidate is not None
        assert len(calls) == 2
        venv_argv, venv_kwargs = calls[0]
        sync_argv, sync_kwargs = calls[1]
        assert venv_argv[:2] == ["uv", "venv"]
        assert "--no-config" in venv_argv
        assert venv_kwargs["env"].get("UV_NO_CONFIG") == "1"
        assert sync_argv[:2] == ["uv", "sync"]
        assert "--locked" in sync_argv
        assert "--no-config" not in sync_argv
        assert "UV_NO_CONFIG" not in sync_kwargs["env"]
        assert sync_kwargs["stderr"] == subprocess.STDOUT


class TestRuntimeCutover:
    def test_os_lock_blocks_concurrent_repair_and_releases(self, tmp_path):
        from hermes_cli.managed_uv import _acquire_repair_lock, _release_repair_lock

        runtime_root = tmp_path / ".hermes-runtime"
        first = _acquire_repair_lock(runtime_root)
        assert first is not None
        assert _acquire_repair_lock(runtime_root) is None

        _release_repair_lock(first)
        second = _acquire_repair_lock(runtime_root)
        assert second is not None
        _release_repair_lock(second)



    def test_post_swap_smoke_failure_rolls_back_live_venv(self, tmp_path):
        from hermes_cli.managed_uv import _cut_over_candidate

        root, live, sentinel = _make_runtime_install(tmp_path)
        runtime_root = root / ".hermes-runtime"
        candidate = runtime_root / "venv-candidate-test"
        candidate.mkdir(parents=True)
        (candidate / "sentinel").write_text("candidate", encoding="utf-8")
        rejected_info = _runtime_info(candidate / "bin" / "python", (3, 50, 4))

        with patch(
            "hermes_cli.managed_uv._smoke_candidate_venv",
            return_value=(False, "core import smoke failed", rejected_info),
        ):
            ok, backup, info, detail = _cut_over_candidate(
                candidate,
                project_root=root,
            )

        assert ok is False
        assert backup is None
        assert info == rejected_info
        assert "post-cutover smoke failed" in detail
        assert sentinel.read_text(encoding="utf-8") == "live"
        assert (live / "bin" / "python").read_text(encoding="utf-8") == (
            "live interpreter"
        )
        assert not candidate.exists()
        assert not list(runtime_root.glob("venv-rejected-*"))




# ---------------------------------------------------------------------------
# _install_uv internals
# ---------------------------------------------------------------------------

class TestInstallUvInternals:
    def test_installer_uses_host_branch_and_managed_directory(self, tmp_path):
        """The native installer receives the managed directory, not a PATH default."""
        import hermes_cli.managed_uv as managed_uv

        target = tmp_path / "bin" / _UV_BINARY_NAME
        with patch("hermes_cli.managed_uv._install_uv_posix") as mock_posix, \
             patch("hermes_cli.managed_uv._install_uv_windows") as mock_windows:
            managed_uv._install_uv(target)

        host_installer, other_installer = (
            (mock_windows, mock_posix) if sys.platform == "win32"
            else (mock_posix, mock_windows))
        host_installer.assert_called_once()
        other_installer.assert_not_called()
        call_env = host_installer.call_args[0][0]
        assert call_env["UV_INSTALL_DIR"] == str(tmp_path / "bin")
        if sys.platform != "win32":
            assert call_env["UV_UNMANAGED_INSTALL"] == str(tmp_path / "bin")


class TestRuntimeRequestMinorLine:
    """The repair must request the CPython minor line, not the exact patch.

    Real-world constraint (verified live, July 2026): every published
    python-build-standalone artifact for 3.11.14 links vulnerable SQLite
    3.50.4 — even with --reinstall. The fixed SQLite (3.53.1) only exists
    from 3.11.15. An exact-patch pin makes the repair permanently
    impossible on such installs.
    """

    def test_requests_minor_line(self):
        from hermes_cli.managed_uv import _runtime_request

        info = _runtime_info(Path("/venv/bin/python"), (3, 50, 4))
        assert _runtime_request(info) == "3.11"

    @staticmethod
    def _run_generation(tmp_path, monkeypatch, current_version, candidate_version):
        """Drive _install_safe_python_generation with fakes; return result."""
        import hermes_cli.managed_uv as managed_uv
        from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

        state = {}

        def fake_run(cmd, **kwargs):
            if "install" in cmd:
                state["generation"] = Path(kwargs["env"]["UV_PYTHON_INSTALL_DIR"])
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            # uv python find → a path inside the generation dir
            python = state["generation"] / "cpython" / "bin" / "python3"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.touch()
            return SimpleNamespace(returncode=0, stdout=str(python), stderr="")

        def fake_probe(python, **kwargs):
            return SQLiteRuntimeInfo(
                executable=Path(python),
                base_prefix=Path(python).parent.parent,
                python_version=candidate_version,
                sqlite_version=(3, 53, 1),
                sqlite_version_string="3.53.1",
                sqlite_source_id="fixed", platform="linux",
            )

        current = SQLiteRuntimeInfo(
            executable=Path("/venv/bin/python"),
            base_prefix=Path("/venv"),
            python_version=current_version,
            sqlite_version=(3, 50, 4),
            sqlite_version_string="3.50.4",
            sqlite_source_id="old", platform="linux",
        )
        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", fake_probe)
        return managed_uv._install_safe_python_generation(
            "uv", project_root=tmp_path, current=current
        )

    def test_accepts_newer_patch_same_minor(self, tmp_path, monkeypatch):
        result = self._run_generation(
            tmp_path, monkeypatch, (3, 11, 14), (3, 11, 15)
        )
        assert result is not None
        _, _, candidate = result
        assert candidate.python_version == (3, 11, 15)


class TestPatchRetryOnVulnerableCandidate:
    """Regression tests for issue #71250: when the bare minor-line request
    (e.g. "3.11") resolves to a candidate that's still vulnerable -- because
    uv's default resolution for that host picked an older cached/indexed
    patch even though a newer non-vulnerable one is available -- the
    provisioner must query the available patches and retry with explicit
    newer versions, rather than giving up after the first attempt.
    """

    @staticmethod
    def _versioned_probe_run(vulnerable_versions, sqlite_fixed=(3, 53, 1)):
        """Build a fake subprocess.run where the install/find/probe cycle
        resolves to a DIFFERENT candidate Python version depending on which
        exact version string was requested, so retries with explicit
        patches can be distinguished from the initial bare-minor attempt."""
        from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

        state = {"requested": None}

        def fake_run(cmd, **kwargs):
            if "install" in cmd:
                # cmd = [uv, "python", "install", <request>, ...]
                state["requested"] = cmd[3]
                state["generation"] = Path(kwargs["env"]["UV_PYTHON_INSTALL_DIR"])
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "list" in cmd:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            # uv python find → a path inside the generation dir, tagged with
            # which request produced it so the probe below can look it up.
            python = state["generation"] / "cpython" / "bin" / "python3"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text(state["requested"] or "", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout=str(python), stderr="")

        def fake_probe(python, **kwargs):
            requested = Path(python).read_text(encoding="utf-8")
            # Bare minor request ("3.11") always resolves to the FIRST
            # (worst-case / already-known-vulnerable) version in the list.
            if requested in vulnerable_versions or requested == "3.11":
                version = (3, 11, 14) if requested == "3.11" else tuple(
                    int(p) for p in requested.split(".")
                )
                return SQLiteRuntimeInfo(
                    executable=Path(python), base_prefix=Path(python).parent.parent,
                    python_version=version, sqlite_version=(3, 50, 4),
                    sqlite_version_string="3.50.4", sqlite_source_id="vulnerable", platform="linux",
                )
            version = tuple(int(p) for p in requested.split("."))
            return SQLiteRuntimeInfo(
                executable=Path(python), base_prefix=Path(python).parent.parent,
                python_version=version, sqlite_version=sqlite_fixed,
                sqlite_version_string=".".join(str(p) for p in sqlite_fixed),
                sqlite_source_id="fixed", platform="linux",
            )

        return fake_run, fake_probe

    def _run(self, tmp_path, monkeypatch, *, vulnerable_versions, patch_list):
        import hermes_cli.managed_uv as managed_uv
        from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

        fake_run, fake_probe = self._versioned_probe_run(vulnerable_versions)
        current = SQLiteRuntimeInfo(
            executable=Path("/venv/bin/python"), base_prefix=Path("/venv"),
            python_version=(3, 11, 14), sqlite_version=(3, 50, 4),
            sqlite_version_string="3.50.4", sqlite_source_id="old", platform="linux",
        )
        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", fake_probe)
        monkeypatch.setattr(
            managed_uv, "_list_available_patches", lambda *a, **kw: patch_list
        )
        return managed_uv._install_safe_python_generation(
            "uv", project_root=tmp_path, current=current
        )

    def test_retries_and_succeeds_with_explicit_newer_patch(self, tmp_path, monkeypatch):
        """The exact #71250 scenario: bare '3.11' resolves to vulnerable
        3.11.14, but 3.11.15 (fixed) is available and gets tried explicitly."""
        result = self._run(
            tmp_path, monkeypatch,
            vulnerable_versions={"3.11"},
            patch_list=[(3, 11, 15), (3, 11, 14), (3, 11, 13), (3, 11, 12)],
        )
        assert result is not None, "Must recover via explicit-patch retry"
        _, _, candidate = result
        assert candidate.python_version == (3, 11, 15)
        assert not candidate.wal_reset_vulnerable





    def test_retry_is_bounded_by_max_retries_constant(self, tmp_path, monkeypatch):
        """A very long patch list must not result in unbounded retries -- capped at
        _MAX_PATCH_RETRIES attempts.  After exhausting same-minor retries the
        fallback tries the next minor line, which may succeed."""
        import hermes_cli.managed_uv as managed_uv

        from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

        current = SQLiteRuntimeInfo(
            executable=Path("/venv/bin/python"), base_prefix=Path("/venv"),
            python_version=(3, 11, 14), sqlite_version=(3, 50, 4),
            sqlite_version_string="3.50.4", sqlite_source_id="old", platform="linux",
        )
        # 20 vulnerable patches -- far more than _MAX_PATCH_RETRIES.
        huge_patch_list = [(3, 11, v) for v in range(30, 10, -1)]
        all_vulnerable = {f"3.11.{v}" for v in range(30, 10, -1)} | {"3.11"}
        fake_run2, fake_probe2 = self._versioned_probe_run(all_vulnerable)

        install_calls = []

        def counting_fake_run(cmd, **kwargs):
            if "install" in cmd:
                install_calls.append(cmd[3])
            return fake_run2(cmd, **kwargs)

        monkeypatch.setattr(managed_uv.subprocess, "run", counting_fake_run)
        monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", fake_probe2)
        monkeypatch.setattr(
            managed_uv, "_list_available_patches", lambda *a, **kw: huge_patch_list
        )
        result = managed_uv._install_safe_python_generation(
            "uv", project_root=tmp_path, current=current
        )
        # The same-minor retries are bounded, but the minor-line fallback
        # (3.11 → 3.12) succeeds because the mock returns a fixed build.
        assert result is not None, (
            "Minor-line fallback should find a fixed 3.12 build"
        )
        # 1 initial bare-minor attempt + at most _MAX_PATCH_RETRIES retries.
        assert managed_uv._MAX_PATCH_RETRIES <= 5, (
            "sanity: constant should stay small since each attempt is a "
            "real download+install+probe cycle"
        )
        same_minor_explicit = [
            call for call in install_calls if call.startswith("3.11.")
        ]
        assert len(same_minor_explicit) <= managed_uv._MAX_PATCH_RETRIES, (
            f"same-minor explicit retries must be capped: {same_minor_explicit}"
        )
        assert install_calls[0] == "3.11"
        # The run ends the moment the bare next-minor fallback succeeds.
        assert install_calls[-1] == "3.12"
        assert install_calls.count("3.12") == 1


class TestMinorLineFallForward:
    """Regression tests for issue #76106: when EVERY build on the current
    minor line (e.g. all of 3.11 on Windows) links a vulnerable SQLite,
    the provisioner must fall forward to the next supported minor line
    (3.12, then 3.13) -- first via a bare minor request, then via explicit
    patches on that line -- instead of leaving the user stuck on every
    `hermes update` with no path to a fixed runtime.
    """

    @staticmethod
    def _mapped_run(resolutions, fixed_versions, install_calls):
        """Fake subprocess.run/probe pair driven by explicit tables:

        - *resolutions*: request string -> python_version tuple the probe
          reports for that request (bare minors resolve like uv would).
        - *fixed_versions*: set of version tuples that link FIXED SQLite;
          everything else probes as vulnerable 3.50.4.
        - *install_calls*: list collecting each `uv python install` request,
          in order, so tests can assert the actual request sequence.
        """
        from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

        state: dict = {"requested": None}

        def fake_run(cmd, **kwargs):
            if "install" in cmd:
                # cmd = [uv, "python", "install", <request>, ...]
                state["requested"] = cmd[3]
                state["generation"] = Path(kwargs["env"]["UV_PYTHON_INSTALL_DIR"])
                install_calls.append(cmd[3])
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "list" in cmd:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            # uv python find → a path inside the generation dir, tagged with
            # the request that produced it so the probe can look it up.
            python = state["generation"] / "cpython" / "bin" / "python3"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text(state["requested"] or "", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout=str(python), stderr="")

        def fake_probe(python, **kwargs):
            requested = Path(python).read_text(encoding="utf-8")
            version = resolutions[requested]
            if version in fixed_versions:
                return SQLiteRuntimeInfo(
                    executable=Path(python),
                    base_prefix=Path(python).parent.parent,
                    python_version=version, sqlite_version=(3, 53, 1),
                    sqlite_version_string="3.53.1", sqlite_source_id="fixed", platform="linux",
                )
            return SQLiteRuntimeInfo(
                executable=Path(python),
                base_prefix=Path(python).parent.parent,
                python_version=version, sqlite_version=(3, 50, 4),
                sqlite_version_string="3.50.4", sqlite_source_id="vulnerable", platform="linux",
            )

        return fake_run, fake_probe

    @staticmethod
    def _current_3_11_14():
        from hermes_cli.sqlite_runtime import SQLiteRuntimeInfo

        return SQLiteRuntimeInfo(
            executable=Path("/venv/bin/python"), base_prefix=Path("/venv"),
            python_version=(3, 11, 14), sqlite_version=(3, 50, 4),
            sqlite_version_string="3.50.4", sqlite_source_id="old", platform="linux",
        )

    def test_explicit_patch_fallback_when_bare_next_minor_is_vulnerable(
        self, tmp_path, monkeypatch
    ):
        """The review-gap scenario from #76252: the bare '3.12' request
        resolves to a VULNERABLE 3.12 build, but an explicit 3.12 patch
        links fixed SQLite -- the `_list_available_patches(..., '3.12', ...)`
        fallback branch must run, skip the already-tried bare resolution,
        and succeed via the explicit patch."""
        import hermes_cli.managed_uv as managed_uv

        install_calls = []
        fake_run, fake_probe = self._mapped_run(
            resolutions={
                "3.11": (3, 11, 14),      # bare current minor: vulnerable
                "3.12": (3, 12, 11),      # bare next minor: ALSO vulnerable
                "3.12.10": (3, 12, 10),   # explicit patch: fixed
            },
            fixed_versions={(3, 12, 10)},
            install_calls=install_calls,
        )
        patch_lists = {
            # No newer 3.11 patch exists (the Windows #76106 reality).
            "3.11": [(3, 11, 14), (3, 11, 13)],
            # Newest 3.12 is the same build the bare request resolved to.
            "3.12": [(3, 12, 11), (3, 12, 10)],
        }
        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", fake_probe)
        monkeypatch.setattr(
            managed_uv, "_list_available_patches",
            lambda uv_bin, minor, **kw: patch_lists[minor],
        )

        result = managed_uv._install_safe_python_generation(
            "uv", project_root=tmp_path, current=self._current_3_11_14()
        )
        assert result is not None, (
            "Explicit-patch fallback on the next minor line must recover"
        )
        _, _, candidate = result
        assert candidate.python_version == (3, 12, 10)
        assert not candidate.wal_reset_vulnerable
        # The actual uv-install request sequence: bare current minor, then
        # bare next minor, then STRAIGHT to the fixed explicit patch --
        # 3.12.11 must NOT be re-requested explicitly, because the bare
        # '3.12' attempt already resolved to (and rejected) that build.
        assert install_calls == ["3.11", "3.12", "3.12.10"]

    def test_returns_none_with_bounded_attempts_when_all_minors_exhausted(
        self, tmp_path, monkeypatch
    ):
        """When every build on every supported minor line (3.11-3.13) is
        vulnerable, the provisioner must give up with None -- and the total
        install workload must stay bounded by _MAX_PATCH_RETRIES per line."""
        import hermes_cli.managed_uv as managed_uv

        install_calls = []
        resolutions = {"3.11": (3, 11, 14), "3.12": (3, 12, 30), "3.13": (3, 13, 30)}
        patch_lists = {}
        for minor in (11, 12, 13):
            versions = [(3, minor, v) for v in range(30, 10, -1)]  # 20 patches
            patch_lists[f"3.{minor}"] = versions
            for version in versions:
                resolutions[".".join(str(p) for p in version)] = version

        fake_run, fake_probe = self._mapped_run(
            resolutions=resolutions, fixed_versions=set(),
            install_calls=install_calls,
        )
        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", fake_probe)
        monkeypatch.setattr(
            managed_uv, "_list_available_patches",
            lambda uv_bin, minor, **kw: patch_lists[minor],
        )

        result = managed_uv._install_safe_python_generation(
            "uv", project_root=tmp_path, current=self._current_3_11_14()
        )
        assert result is None, "Nothing fixed anywhere: must give up cleanly"

        cap = managed_uv._MAX_PATCH_RETRIES
        # Per line: one bare request + at most _MAX_PATCH_RETRIES explicit
        # patches; three lines total (3.11, 3.12, 3.13) and nothing beyond
        # 3.13 (requires-python is <3.14).
        assert install_calls.count("3.11") == 1
        assert install_calls.count("3.12") == 1
        assert install_calls.count("3.13") == 1
        assert not any(call.startswith("3.14") for call in install_calls)
        for minor in (11, 12, 13):
            explicit = [
                call for call in install_calls
                if call.startswith(f"3.{minor}.")
            ]
            assert len(explicit) <= cap, (
                f"3.{minor} explicit retries must be capped at {cap}: {explicit}"
            )
        assert len(install_calls) <= 3 * (1 + cap)


class TestListAvailablePatches:
    """Direct unit tests for _list_available_patches()'s JSON parsing,
    against realistic `uv python list --all-versions --output-format json`
    output (captured from a real uv 0.11.7 invocation)."""

    SAMPLE_OUTPUT = (
        '[{"key":"cpython-3.11.15-linux-x86_64-gnu","version":"3.11.15",'
        '"version_parts":{"major":3,"minor":11,"patch":15},"path":null,'
        '"symlink":null,"url":"https://example/cpython-3.11.15.tar.gz",'
        '"os":"linux","variant":"default","implementation":"cpython",'
        '"arch":"x86_64","libc":"gnu"},'
        '{"key":"cpython-3.11.14-linux-x86_64-gnu","version":"3.11.14",'
        '"version_parts":{"major":3,"minor":11,"patch":14},"path":null,'
        '"symlink":null,"url":"https://example/cpython-3.11.14.tar.gz",'
        '"os":"linux","variant":"default","implementation":"cpython",'
        '"arch":"x86_64","libc":"gnu"},'
        '{"key":"pypy-3.11.15-linux-x86_64-gnu","version":"3.11.15",'
        '"version_parts":{"major":3,"minor":11,"patch":15},"path":null,'
        '"symlink":null,"url":"https://example/pypy-3.11.15.tar.gz",'
        '"os":"linux","variant":"default","implementation":"pypy",'
        '"arch":"x86_64","libc":"gnu"}]'
    )

    def test_parses_and_sorts_newest_first(self, tmp_path, monkeypatch):
        import hermes_cli.managed_uv as managed_uv

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout=self.SAMPLE_OUTPUT, stderr="")

        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        result = managed_uv._list_available_patches(
            "uv", "3.11", cwd=tmp_path, env={}
        )
        assert result == [(3, 11, 15), (3, 11, 14)]


    def test_subprocess_exception_returns_empty_list(self, tmp_path, monkeypatch):
        import hermes_cli.managed_uv as managed_uv

        def fake_run(cmd, **kwargs):
            raise OSError("uv binary not found")

        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        assert managed_uv._list_available_patches("uv", "3.11", cwd=tmp_path, env={}) == []


# ---------------------------------------------------------------------------
# _refresh_managed_uv_catalog + provisioning retry (issue #72093)
# ---------------------------------------------------------------------------

class TestRefreshManagedUvCatalog:
    """The managed uv is UV_UNMANAGED_INSTALL'd, so `uv self update` is
    disabled and its python-build-standalone catalog freezes at bootstrap
    age. python-build-standalone re-releases the same patch versions with
    fixed SQLite, so a stale catalog makes provisioning fail forever with
    no newer patch number to retry (issue #72093)."""


    def test_version_change_reports_true(self, tmp_path):
        import hermes_cli.managed_uv as managed_uv

        versions = iter(["uv 0.1.0", "uv 0.2.0"])
        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch("hermes_cli.managed_uv._install_uv"), \
             patch(
                 "hermes_cli.managed_uv._uv_version_string",
                 side_effect=lambda _uv: next(versions),
             ):
            # Host-native path: the refresh only acts on the managed binary,
            # so the fixture must live at the real host's managed_uv_path()
            # (uv on POSIX, uv.exe on Windows) — no platform fake needed.
            uv_path = managed_uv.managed_uv_path()
            _make_executable(uv_path)
            assert managed_uv._refresh_managed_uv_catalog(str(uv_path)) is True


    def test_installer_failure_reports_false(self, tmp_path):
        import hermes_cli.managed_uv as managed_uv

        with patch("hermes_cli.managed_uv.get_hermes_home", return_value=tmp_path), \
             patch(
                 "hermes_cli.managed_uv._install_uv",
                 side_effect=RuntimeError("network down"),
             ):
            uv_path = managed_uv.managed_uv_path()
            _make_executable(uv_path)
            assert managed_uv._refresh_managed_uv_catalog(str(uv_path)) is False


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only: fixtures build the bin/ (not Scripts/) venv layout")
class TestRepairRetriesAfterUvRefresh:
    def _run_repair(self, tmp_path, *, refresh_result, second_attempt):
        """Drive repair with the first provisioning attempt failing."""
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path)
        current = _runtime_info(live / "bin" / "python", (3, 50, 4))

        attempts = []

        def fake_install(uv_bin, *, project_root, current):
            attempts.append(uv_bin)
            if len(attempts) == 1:
                return None
            return second_attempt(project_root)

        with patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 return_value=current,
             ), \
             patch(
                 "hermes_cli.managed_uv._install_safe_python_generation",
                 side_effect=fake_install,
             ), \
             patch(
                 "hermes_cli.managed_uv._refresh_managed_uv_catalog",
                 return_value=refresh_result,
             ) as mock_refresh, \
             patch(
                 "hermes_cli.managed_uv._stage_candidate_venv",
                 return_value=None,
             ):
            result = repair_vulnerable_runtime("uv", project_root=root)
        return result, attempts, mock_refresh, sentinel

    def test_no_retry_when_refresh_did_not_change_uv(self, tmp_path):
        result, attempts, mock_refresh, sentinel = self._run_repair(
            tmp_path,
            refresh_result=False,
            second_attempt=lambda root: None,
        )
        assert result.status == "failed"
        assert len(attempts) == 1
        mock_refresh.assert_called_once_with("uv")
        assert sentinel.read_text(encoding="utf-8") == "live"

    def test_retries_once_after_successful_refresh(self, tmp_path):
        result, attempts, mock_refresh, sentinel = self._run_repair(
            tmp_path,
            refresh_result=True,
            second_attempt=lambda root: None,
        )
        # Second attempt ran (and also failed) — exactly one retry, no loop.
        assert result.status == "failed"
        assert len(attempts) == 2
        mock_refresh.assert_called_once_with("uv")
        assert sentinel.read_text(encoding="utf-8") == "live"

    def test_retry_success_proceeds_to_staging(self, tmp_path):
        def second_attempt(root):
            generation = root / ".hermes-runtime" / "python" / "generation-retry"
            candidate_python = generation / "bin" / "python"
            candidate_python.parent.mkdir(parents=True)
            candidate_python.write_text("candidate", encoding="utf-8")
            return generation, candidate_python, _runtime_info(
                candidate_python, (3, 53, 1)
            )

        result, attempts, mock_refresh, sentinel = self._run_repair(
            tmp_path,
            refresh_result=True,
            second_attempt=second_attempt,
        )
        # Provisioning succeeded on retry; staging (mocked to None) is what
        # failed — proving the retry result flows into the normal pipeline.
        assert result.status == "failed"
        assert "replacement environment" in result.detail
        assert len(attempts) == 2
        assert sentinel.read_text(encoding="utf-8") == "live"

class TestDefaultLiveVenv:
    """_default_live_venv() must cover BOTH install layouts (venv/ and .venv/).

    Historically repair hardcoded venv/, so uv-default/.venv checkouts got
    'not-applicable' on every hermes update and stayed on journal_mode=DELETE
    (2,600x slower state.db appends) while the WAL warning promised repair.
    """

    def _checkout(self, tmp_path, *dirs):
        root = tmp_path / "checkout"
        root.mkdir()
        (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        # Host-native venv layout: bin/python on POSIX, Scripts/python.exe on
        # Windows — what _venv_python() resolves on the real host.
        if sys.platform == "win32":
            bin_dir_name, python_name = "Scripts", "python.exe"
        else:
            bin_dir_name, python_name = "bin", "python"
        for d in dirs:
            bin_dir = root / d / bin_dir_name
            bin_dir.mkdir(parents=True)
            (bin_dir / python_name).write_text("py", encoding="utf-8")
        return root

    def test_dot_venv_only_is_targeted(self, tmp_path):
        from hermes_cli.managed_uv import _default_live_venv

        root = self._checkout(tmp_path, ".venv")
        assert _default_live_venv(root) == root / ".venv"

    def test_managed_venv_takes_precedence(self, tmp_path):
        from hermes_cli.managed_uv import _default_live_venv

        root = self._checkout(tmp_path, "venv", ".venv")
        assert _default_live_venv(root) == root / "venv"

    def test_neither_layout_keeps_not_applicable(self, tmp_path):
        from hermes_cli.managed_uv import (
            _default_live_venv,
            repair_vulnerable_runtime,
        )

        root = self._checkout(tmp_path)
        # Neither venv nor .venv has an interpreter -> repair is not applicable.
        assert _default_live_venv(root) == root / "venv"
        result = repair_vulnerable_runtime("uv", project_root=root)
        assert result.status == "not-applicable"


class TestVenvPythonUpdateBoundary:
    """``_venv_python`` must survive a hermes_constants predating its symbol.

    ``hermes update`` imports hermes_constants from the OLD checkout, ``git
    pull`` replaces that file, and the freshly-pulled managed_uv then runs its
    lazy ``from hermes_constants import venv_python_path`` against the module
    object already cached in ``sys.modules``. That cached module has no such
    symbol, so the import raises — while naming the NEW file on disk, which
    plainly contains it, which is what made the error so confusing:

        cannot import name 'venv_python_path' from 'hermes_constants'
        (~/.hermes/hermes-agent/hermes_constants.py)

    It aborted the managed-Python runtime repair on the first update from any
    release older than the symbol. Same class as the ``ensure_uv()`` arity skew
    documented on ``_UvResult``.
    """

    def test_recovers_when_the_cached_module_predates_the_symbol(self, monkeypatch):
        import hermes_constants

        from hermes_cli.managed_uv import _venv_python

        # The stale in-memory module: the symbol the new code wants is absent,
        # exactly as on an install that booted the pre-upgrade checkout. The
        # file on disk is the current one, so a reload recovers the real helper.
        monkeypatch.delattr(hermes_constants, "venv_python_path", raising=False)

        # Host-native: the subject is the reload-recovery seam, not the
        # bin/Scripts mapping — assert whatever layout the real host resolves.
        expected = Path("/opt/hermes/venv/Scripts/python.exe") \
            if sys.platform == "win32" else Path("/opt/hermes/venv/bin/python")
        assert _venv_python(Path("/opt/hermes/venv")) == expected

    def test_recovery_uses_the_shared_helper_not_a_second_copy(self, monkeypatch):
        """The reload must resolve through hermes_constants, not open-code it.

        Hand-rolling `Scripts`/`bin` here is what #76105 deduped away and what
        `test_no_open_coded_venv_layout_remains_in_hermes_cli` bans.
        """
        import hermes_constants

        from hermes_cli.managed_uv import _venv_python

        monkeypatch.delattr(hermes_constants, "venv_python_path", raising=False)

        sentinel = Path("/sentinel/from/shared/helper")
        real_reload = __import__("importlib").reload

        def _reload_with_marker(module):
            fresh = real_reload(module)
            monkeypatch.setattr(
                fresh, "venv_python_path", lambda *a, **k: sentinel, raising=False
            )
            return fresh

        monkeypatch.setattr("importlib.reload", _reload_with_marker)
        assert _venv_python(Path("/opt/hermes/venv")) == sentinel

    def test_uses_the_real_helper_when_it_is_importable(self, monkeypatch):
        """The normal path never reloads — recovery stays a fallback."""
        from hermes_cli.managed_uv import _venv_python

        def _no_reload(module):  # pragma: no cover - must not run
            raise AssertionError("reload must not run when the import succeeds")

        monkeypatch.setattr("importlib.reload", _no_reload)

        expected = Path("/opt/hermes/venv/Scripts/python.exe") \
            if sys.platform == "win32" else Path("/opt/hermes/venv/bin/python")
        assert _venv_python(Path("/opt/hermes/venv")) == expected



class TestWindowsRuntimeSelfLock:
    """The repair pre-flight must see the ONE holder the generic scan hides:
    the updater itself (#93032).

    A CLI ``hermes update`` runs from the venv's own python, and
    ``_detect_venv_python_processes`` excludes the calling process and its
    ancestors on purpose (correct for the dependency-sync path).  For the
    whole-venv park rename that exemption is fatal on Windows: a directory
    containing an executable mapped by a running process cannot be renamed,
    so the cutover retries burn out against a lock that cannot be released
    while the updater lives.  The repair must detect the self-lock and defer
    with honest guidance instead of provisioning a candidate for a doomed
    rename.
    """

    def _checkout(self, tmp_path):
        root, live, sentinel = _make_runtime_install(tmp_path)
        # Windows-layout interpreter so sys.executable can point inside the
        # live venv on any host (the detector only string-compares paths).
        scripts_python = live / "Scripts" / "python.exe"
        scripts_python.parent.mkdir(parents=True, exist_ok=True)
        scripts_python.write_text("live interpreter", encoding="utf-8")
        return root, live, sentinel, scripts_python

    def test_self_lock_defers_repair_before_provisioning(
        self, tmp_path, monkeypatch, capsys
    ):
        """Regression for #93032: pre-fix, the repair walks straight into the
        doomed rename (provisioning + cutover) whenever the updater itself
        maps the live venv; the park then fails with WinError 5 and the user
        gets the misleading 'next update will retry' message forever."""
        from hermes_cli import managed_uv
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel, scripts_python = self._checkout(tmp_path)
        current = _runtime_info(scripts_python, (3, 50, 4))
        monkeypatch.setattr(managed_uv, "host_system", lambda: "Windows")
        monkeypatch.setattr(sys, "executable", str(scripts_python))

        with patch(
                 "hermes_cli.managed_uv._windows_runtime_holders",
                 return_value=(False, ""),
             ), \
             patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 return_value=current,
             ), \
             patch(
                 "hermes_cli.managed_uv._install_safe_python_generation"
             ) as mock_install:
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "skipped"
        assert "live venv" in result.detail
        assert mock_install.call_count == 0, (
            "a self-locked updater must not provision a candidate it can "
            "never cut over"
        )
        assert sentinel.read_text(encoding="utf-8") == "live"
        assert not (root / ".hermes-runtime").exists()

        out = capsys.readouterr().out
        assert "runtime repair deferred" in out
        assert "will retry" not in out, (
            "the structural self-lock must not promise that retrying helps"
        )
        assert "outside" in out, "the deferral must point at an escape hatch"

    def test_non_self_locked_repair_proceeds(self, tmp_path, monkeypatch):
        """The guard must fail OPEN when the updater runs from outside the
        venv — an always-firing deferral would recreate the never-converging
        loop this fix removes (#86735 class)."""
        from hermes_cli import managed_uv
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel, scripts_python = self._checkout(tmp_path)
        current = _runtime_info(scripts_python, (3, 50, 4))
        monkeypatch.setattr(managed_uv, "host_system", lambda: "Windows")
        monkeypatch.setattr(
            sys, "executable", str(tmp_path / "outside" / "python.exe")
        )

        with patch(
                 "hermes_cli.managed_uv._windows_runtime_holders",
                 return_value=(False, ""),
             ), \
             patch(
                 "hermes_cli.managed_uv.probe_sqlite_runtime",
                 return_value=current,
             ), \
             patch(
                 "hermes_cli.managed_uv._install_safe_python_generation",
                 return_value=None,
             ) as mock_install:
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "failed"
        assert "provision" in result.detail
        mock_install.assert_called_once()
        assert sentinel.read_text(encoding="utf-8") == "live"

    def test_self_lock_is_a_noop_off_windows(self, tmp_path, monkeypatch):
        """POSIX renames work while the updater maps the venv, so the guard
        must stay Windows-only."""
        from hermes_cli import managed_uv

        root, live, sentinel, scripts_python = self._checkout(tmp_path)
        monkeypatch.setattr(managed_uv, "host_system", lambda: "Linux")
        monkeypatch.setattr(sys, "executable", str(scripts_python))

        locked, detail = managed_uv._windows_runtime_self_lock(live)
        assert (locked, detail) == (False, "")

    def test_venv_launcher_ancestor_is_a_self_lock(self, tmp_path, monkeypatch):
        r"""The venv\Scripts\hermes.exe shim stays mapped while it waits for
        this child — an ancestor running from the venv blocks the rename too."""
        from hermes_cli import managed_uv

        root, live, sentinel, scripts_python = self._checkout(tmp_path)
        monkeypatch.setattr(managed_uv, "host_system", lambda: "Windows")
        monkeypatch.setattr(
            sys, "executable", str(tmp_path / "outside" / "python.exe")
        )

        class _FakeProc:
            def __init__(self, pid, exe):
                self.pid = pid
                self._exe = exe

            def exe(self):
                return self._exe

        fake_psutil = SimpleNamespace(
            Process=lambda: SimpleNamespace(
                parents=lambda: [_FakeProc(999, str(scripts_python))],
            ),
        )
        with patch.dict(sys.modules, {"psutil": fake_psutil}):
            locked, detail = managed_uv._windows_runtime_self_lock(live)

        assert locked
        assert "999" in detail


class TestWmiStrayThreadTrigger:
    """The interpreter itself is the second reason a managed runtime gets replaced.

    Windows CPython before 3.13.4 abandons ``platform.uname()``'s WMI query thread after a 100 ms
    timeout and lets it close a random live handle of the process (CPython gh-130727, never
    backported to 3.12); under host load that kills bare children with ``0xC000070A``. The
    ``hermes_bootstrap`` stub only covers bootstrapped entry points, so the repair must provision
    a fixed interpreter even when SQLite is already fine -- and it must request the fixed minor
    line directly, because no 3.12 patch can ever pass the probe.
    """

    @staticmethod
    def _win_info(python: Path, python_version, sqlite=(3, 53, 1)):
        return _runtime_info(python, sqlite, python_version=python_version, platform="win32")

    def test_reasons_are_reported_independently(self):
        from hermes_cli.sqlite_runtime import (
            REPAIR_REASON_SQLITE_WAL_RESET, REPAIR_REASON_WMI_STRAY_THREAD)

        python = Path("/venv/Scripts/python.exe")
        both = self._win_info(python, (3, 12, 13), sqlite=(3, 50, 4))
        assert both.repair_reasons == (
            REPAIR_REASON_SQLITE_WAL_RESET, REPAIR_REASON_WMI_STRAY_THREAD)
        only_wmi = self._win_info(python, (3, 12, 13))
        assert only_wmi.repair_reasons == (REPAIR_REASON_WMI_STRAY_THREAD,)
        assert only_wmi.needs_repair
        fixed = self._win_info(python, (3, 13, 15))
        assert fixed.repair_reasons == ()
        assert not fixed.needs_repair
        posix = _runtime_info(Path("/venv/bin/python"), (3, 53, 1), python_version=(3, 12, 13))
        assert posix.repair_reasons == ()

    def test_request_starts_at_the_fixed_minor_line(self):
        from hermes_cli.managed_uv import _runtime_request

        python = Path("/venv/Scripts/python.exe")
        assert _runtime_request(self._win_info(python, (3, 12, 13))) == "3.13"
        # Both reasons at once: the interpreter reason wins the request line.
        assert _runtime_request(self._win_info(python, (3, 11, 14), sqlite=(3, 50, 4))) == "3.13"
        # A 3.13 patch below the fix stays on its own line (newer patches carry it).
        assert _runtime_request(self._win_info(python, (3, 13, 3))) == "3.13"
        # Off Windows the same interpreter keeps the SQLite behaviour: pin the current minor.
        posix = _runtime_info(Path("/venv/bin/python"), (3, 50, 4), python_version=(3, 12, 13))
        assert _runtime_request(posix) == "3.12"

    def test_generation_skips_the_current_minor_line(self, tmp_path, monkeypatch):
        """No 3.12 build can carry the fix, so the first uv request is the fixed minor with the
        minor-upgrade guard relaxed -- not five certain rejections on 3.12 first."""
        import hermes_cli.managed_uv as managed_uv

        install_calls = []
        fake_run, fake_probe = TestMinorLineFallForward._mapped_run(
            resolutions={"3.13": (3, 13, 15)}, fixed_versions={(3, 13, 15)},
            install_calls=install_calls)
        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        monkeypatch.setattr(managed_uv, "probe_sqlite_runtime", fake_probe)
        monkeypatch.setattr(
            managed_uv, "_list_available_patches",
            lambda uv_bin, minor, **kw: pytest.fail(f"no patch retry expected on {minor}"))

        current = self._win_info(Path("/venv/Scripts/python.exe"), (3, 12, 13))
        result = managed_uv._install_safe_python_generation(
            "uv", project_root=tmp_path, current=current)

        assert result is not None
        _, _, candidate = result
        assert candidate.python_version == (3, 13, 15)
        assert install_calls == ["3.13"]

    def test_candidate_below_the_fix_is_rejected(self, tmp_path, monkeypatch, caplog):
        """A caller-pinned request (or a uv resolution off the line) that lands below 3.13.4 is
        refused like a vulnerable SQLite: the fix is a property of the interpreter."""
        import logging

        import hermes_cli.managed_uv as managed_uv

        def fake_run(cmd, **kwargs):
            if "install" in cmd:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            python = Path(kwargs["env"]["UV_PYTHON_INSTALL_DIR"]) / "cpython" / "python.exe"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.touch()
            return SimpleNamespace(returncode=0, stdout=str(python), stderr="")

        monkeypatch.setattr(managed_uv.subprocess, "run", fake_run)
        monkeypatch.setattr(
            managed_uv, "probe_sqlite_runtime",
            lambda python, **kw: self._win_info(Path(python), (3, 13, 3)))
        current = self._win_info(Path("/venv/Scripts/python.exe"), (3, 12, 13))
        python_root = tmp_path / ".hermes-runtime" / "python"

        with caplog.at_level(logging.WARNING, logger="hermes_cli.managed_uv"):
            result = managed_uv._attempt_install_generation(
                "uv", "3.13.3", project_root=tmp_path, python_root=python_root,
                current=current, allow_minor_upgrade=True)

        assert result is None
        assert "abandons platform.uname()" in caplog.text
        assert not list(python_root.glob("generation-*")), "a rejected generation is removed"

    def test_smoke_refuses_a_candidate_below_the_fix(self, tmp_path, monkeypatch):
        import hermes_cli.managed_uv as managed_uv

        monkeypatch.setattr(
            managed_uv, "probe_sqlite_runtime",
            lambda python, **kw: self._win_info(Path(python), (3, 12, 13)))
        healthy, detail, info = managed_uv._smoke_candidate_venv(tmp_path / "venv")

        assert not healthy
        assert "WMI thread" in detail
        assert info is not None and info.wmi_stray_thread_vulnerable

    def test_repair_runs_for_the_interpreter_reason_alone(self, tmp_path, capsys):
        """Safe SQLite no longer means 'safe': a Windows 3.12 interpreter provisions."""
        from hermes_cli.managed_uv import repair_vulnerable_runtime
        from hermes_cli.sqlite_runtime import REPAIR_REASON_WMI_STRAY_THREAD

        root, live, sentinel = _make_runtime_install(tmp_path, windows=sys.platform == "win32")
        live_python = next(live.rglob("python*"))
        current = self._win_info(live_python, (3, 12, 13))
        with patch("hermes_cli.managed_uv.probe_sqlite_runtime", return_value=current), \
             patch("hermes_cli.managed_uv._repair_windows_preflight", return_value=None), \
             patch("hermes_cli.managed_uv._install_safe_python_generation",
                   return_value=None) as mock_install:
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "failed"
        assert result.reasons == (REPAIR_REASON_WMI_STRAY_THREAD,)
        mock_install.assert_called_once()
        assert mock_install.call_args.kwargs["current"] is current
        assert sentinel.read_text(encoding="utf-8") == "live"
        out = capsys.readouterr().out
        assert "gh-130727" in out
        assert "WAL-reset" not in out, "the SQLite reason must not be claimed when absent"

    def test_same_interpreter_off_windows_is_safe(self, tmp_path):
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path, windows=sys.platform == "win32")
        live_python = next(live.rglob("python*"))
        current = _runtime_info(live_python, (3, 53, 1), python_version=(3, 12, 13))
        with patch("hermes_cli.managed_uv.probe_sqlite_runtime", return_value=current), \
             patch("hermes_cli.managed_uv._install_safe_python_generation") as mock_install:
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "safe"
        assert result.reasons == ()
        mock_install.assert_not_called()

    def test_failure_report_names_the_interim_protection_per_reason(self, capsys):
        from hermes_cli.managed_uv import RuntimeRepairResult, _report_runtime_repair_failure
        from hermes_cli.sqlite_runtime import (
            REPAIR_REASON_SQLITE_WAL_RESET, REPAIR_REASON_WMI_STRAY_THREAD)

        _report_runtime_repair_failure(RuntimeRepairResult(
            "failed", "could not provision", reasons=(REPAIR_REASON_WMI_STRAY_THREAD,)))
        wmi_only = capsys.readouterr().out
        assert "WMI queries stubbed" in wmi_only
        assert "WAL mode" not in wmi_only
        assert "will retry" in wmi_only

        _report_runtime_repair_failure(RuntimeRepairResult(
            "failed", "could not provision",
            reasons=(REPAIR_REASON_SQLITE_WAL_RESET, REPAIR_REASON_WMI_STRAY_THREAD)))
        both = capsys.readouterr().out
        assert "WAL mode" in both and "WMI queries stubbed" in both


class TestWindowsRuntimeHoldersPolicy:
    """The holders gate names WHICH holders block, and only structural ones block under
    ``transient-ok``. Measured 2026-09-18 (rename_probe.py, loops pbs-cpython-313-cutover-20260917):
    an NTFS directory rename succeeds under a running child; the cut-over swapped under 14
    transient pytest holders by hand. The default stays strict (any holder defers)."""

    VENV = r"C:\hermes\venv"
    PY = VENV + r"\Scripts\python.exe"
    GATEWAY = (1, "python.exe", f'"{PY}" -m hermes_cli.main --profile main gateway run --replace')
    SERVE = (2, "python.exe", f"{PY} -m hermes_cli.main serve --host 127.0.0.1 --port 0")
    BRIDGE = (3, "hermes-session-bridge.exe", r"C:\hermes\venv\Scripts\hermes-session-bridge.exe serve")
    PYTEST = (4, "python.exe", f"{PY} -m pytest tests/hermes_cli/test_managed_uv.py -q")
    RUNNER = (5, "python.exe", f"{PY} C:/hermes/scripts/run_tests_parallel.py tests/agent")
    BARE = (6, "python.exe", f"{PY} -")

    @pytest.fixture(autouse=True)
    def _windows(self, monkeypatch):
        from hermes_cli import managed_uv

        monkeypatch.setattr(managed_uv, "host_system", lambda: "Windows")
        monkeypatch.delenv(managed_uv._RUNTIME_HOLDER_POLICY_ENV, raising=False)
        # Real pids mean nothing here: no holder has a cwd inside the venv unless a test says so.
        monkeypatch.setattr(managed_uv, "_holder_cwd", lambda pid: "")

    @staticmethod
    def _holders(*rows):
        return lambda: list(rows)

    def test_classification_of_structural_and_transient_holders(self):
        from hermes_cli import managed_uv

        prefix = self.VENV.lower() + "\\"
        classify = lambda row, **kw: managed_uv._classify_runtime_holder(*row, live_prefix=prefix, **kw)

        assert classify(self.GATEWAY) == "long-lived `hermes gateway`"
        assert classify(self.SERVE) == "long-lived `hermes serve`"
        assert classify(self.BRIDGE).startswith("service launcher hermes-session-bridge")
        assert classify(self.PYTEST) is None
        assert classify(self.RUNNER) is None
        assert classify(self.BARE) is None
        # (b) a cwd inside the venv holds a directory handle open: structural whatever the argv.
        inside = classify(self.PYTEST, cwd_of=lambda pid: self.VENV.lower() + r"\lib\site-packages")
        assert inside is not None and "cwd inside the venv" in inside
        assert classify(self.PYTEST, cwd_of=lambda pid: r"c:\hermes") is None

    def test_strict_default_defers_on_transient_only_and_names_the_escape_hatch(self):
        from hermes_cli import managed_uv

        blocked, detail = managed_uv._windows_runtime_holders(
            Path(self.VENV), detector=self._holders(self.PYTEST, self.RUNNER))

        assert blocked is True
        assert "0 structural, 2 transient" in detail
        assert "transient PID 4, 5" in detail
        assert f"{managed_uv._RUNTIME_HOLDER_POLICY_ENV}=transient-ok" in detail
        assert "rename succeeds" in detail and "lazy imports may fail" in detail

    def test_structural_holder_defers_under_every_policy(self, monkeypatch):
        from hermes_cli import managed_uv

        monkeypatch.setenv(managed_uv._RUNTIME_HOLDER_POLICY_ENV, "transient-ok")
        blocked, detail = managed_uv._windows_runtime_holders(
            Path(self.VENV), detector=self._holders(self.PYTEST, self.GATEWAY, self.BRIDGE))

        assert blocked is True
        assert "2 structural, 1 transient" in detail
        assert "PID 1: long-lived `hermes gateway`" in detail
        assert "PID 3: service launcher hermes-session-bridge.exe" in detail
        assert "transient-ok would let" not in detail, "no escape hatch is offered for structural holders"

    def test_transient_ok_swaps_under_transient_holders_with_a_warning(self, monkeypatch):
        from hermes_cli import managed_uv

        monkeypatch.setenv(managed_uv._RUNTIME_HOLDER_POLICY_ENV, "transient-ok")
        blocked, detail = managed_uv._windows_runtime_holders(
            Path(self.VENV), detector=self._holders(self.PYTEST, self.BARE))

        assert blocked is False
        assert "2 transient holder(s)" in detail and "PID 4, 6" in detail
        assert "lazily" in detail and "measured 2026-09-18" in detail

    def test_unknown_policy_value_is_strict(self, monkeypatch):
        from hermes_cli import managed_uv

        monkeypatch.setenv(managed_uv._RUNTIME_HOLDER_POLICY_ENV, "yes-please")
        blocked, _ = managed_uv._windows_runtime_holders(
            Path(self.VENV), detector=self._holders(self.PYTEST))
        assert blocked is True

    def test_no_holders_and_off_windows_are_unchanged(self, monkeypatch):
        from hermes_cli import managed_uv

        assert managed_uv._windows_runtime_holders(Path(self.VENV), detector=self._holders()) == (False, "")
        monkeypatch.setattr(managed_uv, "host_system", lambda: "Linux")
        assert managed_uv._windows_runtime_holders(Path(self.VENV), detector=self._holders(self.GATEWAY)) == (
            False, "")

    def test_preflight_prints_the_transient_warning_and_proceeds(self, tmp_path, monkeypatch, capsys):
        """Through the preflight: transient-ok prints the hazard, does not defer, and the repair
        continues to provisioning (which this test declines) — live venv untouched."""
        from hermes_cli import managed_uv
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path, windows=True)
        live_python = next(live.rglob("python*"))
        current = _runtime_info(live_python, (3, 50, 4))
        monkeypatch.setenv(managed_uv._RUNTIME_HOLDER_POLICY_ENV, "transient-ok")
        monkeypatch.setattr(sys, "executable", str(tmp_path / "outside" / "python.exe"))
        seen: list[Path | None] = []
        real_holders = managed_uv._windows_runtime_holders

        def holders(live_arg=None, **kw):
            seen.append(live_arg)
            return real_holders(live_arg, detector=self._holders(self.PYTEST))

        with patch("hermes_cli.managed_uv._windows_runtime_holders", side_effect=holders), \
             patch("hermes_cli.managed_uv.probe_sqlite_runtime", return_value=current), \
             patch("hermes_cli.managed_uv._install_safe_python_generation",
                   return_value=None) as mock_install:
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert seen == [live], "the preflight must hand the live venv to the classifier"
        assert result.status == "failed" and "provision" in result.detail
        mock_install.assert_called_once()
        out = capsys.readouterr().out
        assert "swapping the venv under 1 transient holder(s)" in out
        assert "repair deferred" not in out
        assert sentinel.read_text(encoding="utf-8") == "live"


class TestSmokeTimeoutIsNotAVerdict:
    """A timed-out import smoke is host load, never a rejection of the candidate.

    Measured 2026-09-18 (loops pbs-cpython-313-cutover-20260917): the same import list took
    46.6 s cold / 51.7 s warm on 3.13 with the host at 100 % CPU, at parity with 3.12 under the
    same load; the fixed 90 s bound tripped and ``_reject`` deleted a fully synced candidate.
    """

    @staticmethod
    def _safe_info(python: Path):
        return _runtime_info(python, (3, 53, 1), python_version=(3, 13, 15))

    def _real_interpreter(self, monkeypatch, tmp_path, script: str) -> Path:
        """Point the smoke at the REAL interpreter running *script* in place of the import list."""
        from hermes_cli import managed_uv

        venv = tmp_path / "venv-candidate-1-2-abcd"
        venv.mkdir()
        monkeypatch.setattr(managed_uv, "_venv_python", lambda venv_dir: Path(sys.executable))
        monkeypatch.setattr(managed_uv, "_SMOKE_IMPORT_CHECK", script)
        monkeypatch.setattr(
            managed_uv, "probe_sqlite_runtime", lambda python, **kw: self._safe_info(Path(python)))
        return venv

    def test_one_timeout_is_retried_at_a_longer_bound(self, tmp_path, monkeypatch, capsys):
        """First attempt sleeps past the bound and is killed; the retry (marker present) passes."""
        from hermes_cli import managed_uv

        marker = tmp_path / "second-attempt"
        script = (
            "import os, sys, time\n"
            f"p = {marker.as_posix()!r}\n"
            "if os.path.exists(p):\n"
            "    sys.exit(0)\n"
            "open(p, 'w').close()\n"
            "time.sleep(30)\n")
        venv = self._real_interpreter(monkeypatch, tmp_path, script)

        # 3 s: interpreter start-up alone can exceed 1 s on a loaded host, and the first attempt
        # must get as far as writing the marker before it is killed.
        healthy, detail, info = managed_uv._smoke_candidate_venv(venv, timeout_s=3.0)

        assert (healthy, detail) == (True, "")
        assert info is not None and info.python_version == (3, 13, 15)
        assert marker.exists(), "the first attempt must have run (and been killed) for real"
        out = capsys.readouterr().out
        assert "did not finish within 3 s" in out and "retrying once with 6 s" in out

    def test_two_timeouts_are_inconclusive_not_a_rejection(self, tmp_path, monkeypatch):
        """A real child that never finishes: the smoke raises, it does NOT return ``False``."""
        from hermes_cli import managed_uv

        venv = self._real_interpreter(monkeypatch, tmp_path, "import time\ntime.sleep(30)\n")

        with pytest.raises(managed_uv.CandidateSmokeInconclusive) as excinfo:
            managed_uv._smoke_candidate_venv(venv, timeout_s=0.5)

        exc = excinfo.value
        assert exc.venv_dir == venv
        assert exc.info is not None and exc.info.python_version == (3, 13, 15)
        assert "timed out twice" in exc.detail and "0 s, then 1 s" in exc.detail

    def test_a_real_import_failure_is_still_a_verdict(self, tmp_path, monkeypatch):
        """The discriminator: a child that FAILS (not stalls) keeps the old ``(False, detail)`` shape."""
        from hermes_cli import managed_uv

        venv = self._real_interpreter(
            monkeypatch, tmp_path, "import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n")

        healthy, detail, info = managed_uv._smoke_candidate_venv(venv, timeout_s=5.0)

        assert healthy is False and detail == "boom"

    def test_stage_keeps_the_synced_candidate_on_an_inconclusive_smoke(self, tmp_path, caplog):
        """Pre-fix, ``_reject`` removed the tree on any ``(False, ...)`` — including a timeout."""
        import logging

        from hermes_cli import managed_uv

        root = tmp_path / "checkout"
        root.mkdir()
        (root / "uv.lock").write_text("# lock\n", encoding="utf-8")
        generation = root / ".hermes-runtime" / "python" / "gen"
        python = generation / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("py", encoding="utf-8")
        created: list[Path] = []

        def fake_uv(argv, **kwargs):
            if argv[:2] == ["uv", "venv"]:
                candidate = Path(argv[2])
                candidate.mkdir(parents=True)
                (candidate / "sentinel").write_text("synced", encoding="utf-8")
                created.append(candidate)
            return MagicMock(returncode=0)

        def inconclusive(venv_dir, **kw):
            raise managed_uv.CandidateSmokeInconclusive(
                "core import smoke timed out twice (90 s, then 180 s)", venv_dir=venv_dir, info=None)

        with patch("hermes_cli.managed_uv.subprocess.run", side_effect=fake_uv), \
             patch("hermes_cli.managed_uv._smoke_candidate_venv", side_effect=inconclusive), \
             caplog.at_level(logging.WARNING, logger="hermes_cli.managed_uv"), \
             pytest.raises(managed_uv.CandidateSmokeInconclusive) as excinfo:
            managed_uv._stage_candidate_venv(
                "uv", project_root=root, generation=generation, python=python)

        (candidate,) = created
        assert excinfo.value.venv_dir == candidate
        assert (candidate / "sentinel").read_text(encoding="utf-8") == "synced", (
            "an inconclusive smoke must not delete the ~6 min uv sync")
        assert "keeping" in caplog.text

        # Control: a real verdict still rejects and removes (the old contract is intact).
        created.clear()
        with patch("hermes_cli.managed_uv.subprocess.run", side_effect=fake_uv), \
             patch("hermes_cli.managed_uv._smoke_candidate_venv",
                   return_value=(False, "ImportError: no module named yaml", None)):
            result = managed_uv._stage_candidate_venv(
                "uv", project_root=root, generation=generation, python=python)
        assert result is None
        assert not created[0].exists(), "a genuine import failure still rejects the candidate"

    def test_repair_reports_inconclusive_as_deferred_and_keeps_the_generation(
            self, tmp_path, capsys):
        """End to end: status ``skipped`` (not ``failed``), candidate + generation on disk, live untouched."""
        from hermes_cli import managed_uv
        from hermes_cli.managed_uv import repair_vulnerable_runtime

        root, live, sentinel = _make_runtime_install(tmp_path, windows=sys.platform == "win32")
        current = _runtime_info(next(live.rglob("python*")), (3, 50, 4))
        generation = root / ".hermes-runtime" / "python" / "generation-1-2-cafe"
        candidate_python = generation / "bin" / "python"
        candidate_python.parent.mkdir(parents=True)
        candidate_python.write_text("candidate interpreter", encoding="utf-8")
        fixed = _runtime_info(candidate_python, (3, 53, 1))
        candidate = root / ".hermes-runtime" / "venv-candidate-1-2-beef"

        def stage(uv_bin, *, project_root, generation, python):
            candidate.mkdir(parents=True)
            raise managed_uv.CandidateSmokeInconclusive(
                "core import smoke timed out twice (90 s, then 180 s)", venv_dir=candidate, info=fixed)

        with patch("hermes_cli.managed_uv.probe_sqlite_runtime", return_value=current), \
             patch("hermes_cli.managed_uv._repair_windows_preflight", return_value=None), \
             patch("hermes_cli.managed_uv._install_safe_python_generation",
                   return_value=(generation, candidate_python, fixed)), \
             patch("hermes_cli.managed_uv._stage_candidate_venv", side_effect=stage):
            result = repair_vulnerable_runtime("uv", project_root=root)

        assert result.status == "skipped", result
        assert str(candidate) in result.detail and str(generation) in result.detail
        assert candidate.is_dir(), "the synced candidate is kept for a quiet-window retry"
        assert generation.is_dir(), "its interpreter generation must survive with it"
        assert sentinel.read_text(encoding="utf-8") == "live"
        out = capsys.readouterr().out
        assert "runtime repair deferred" in out and "host load" in out
        assert str(candidate) in out

    def test_post_cutover_inconclusive_rolls_back_but_keeps_the_tree(self, tmp_path):
        """Through the real path the smoke stalls: live is restored, the demoted tree survives."""
        from hermes_cli import managed_uv
        from hermes_cli.managed_uv import _cut_over_candidate

        root, live, sentinel = _make_runtime_install(tmp_path)
        runtime_root = root / ".hermes-runtime"
        candidate = runtime_root / "venv-candidate-test"
        candidate.mkdir(parents=True)
        (candidate / "sentinel").write_text("candidate", encoding="utf-8")
        info = _runtime_info(candidate / "bin" / "python", (3, 53, 1))

        def inconclusive(venv_dir, **kw):
            raise managed_uv.CandidateSmokeInconclusive(
                "core import smoke timed out twice (90 s, then 180 s)", venv_dir=venv_dir, info=info)

        with patch("hermes_cli.managed_uv._smoke_candidate_venv", side_effect=inconclusive), \
             pytest.raises(managed_uv.CandidateSmokeInconclusive) as excinfo:
            _cut_over_candidate(candidate, project_root=root)

        assert sentinel.read_text(encoding="utf-8") == "live", "live venv must be restored"
        assert not list(root.glob(f"{live.name}.stale.runtime-*")), "no parked backup lingers"
        kept = excinfo.value.venv_dir
        assert kept.parent == runtime_root and kept.name.startswith("venv-rejected-")
        assert (kept / "sentinel").read_text(encoding="utf-8") == "candidate"
        assert "live venv restored" in excinfo.value.detail

    def test_retained_candidates_are_reclaimed_by_token_age(self, tmp_path):
        """Aged by the token epoch (a rename preserves st_mtime); the live generation is spared."""
        import time as _time

        from hermes_cli import managed_uv

        runtime_root = tmp_path / ".hermes-runtime"
        python_root = runtime_root / "python"
        old_epoch = int(_time.time() - 2 * 24 * 3600)
        fresh_epoch = int(_time.time() - 60)

        def make(name: str, generation: str) -> tuple[Path, Path]:
            gen = python_root / generation
            home = gen / "cpython-3.13-x" / "bin"
            home.mkdir(parents=True, exist_ok=True)
            cand = runtime_root / name
            cand.mkdir(parents=True)
            (cand / "pyvenv.cfg").write_text(f"home = {home}\nversion_info = 3.13\n", encoding="utf-8")
            return cand, gen

        old, old_gen = make(f"venv-candidate-{old_epoch}-1-aaaa", "generation-1-1-aaaa")
        fresh, fresh_gen = make(f"venv-candidate-{fresh_epoch}-1-bbbb", "generation-1-1-bbbb")
        shared, live_gen = make(f"venv-candidate-{old_epoch}-1-cccc", "generation-1-1-cccc")
        odd = runtime_root / "venv-candidate-not-a-token"
        odd.mkdir()

        managed_uv._sweep_retained_candidates(
            runtime_root, python_root=python_root,
            live_home=live_gen / "cpython-3.13-x")

        assert not old.exists() and not old_gen.exists(), "aged candidate goes with its generation"
        assert fresh.exists() and fresh_gen.exists(), "a fresh candidate may be mid-repair"
        assert not shared.exists() and live_gen.exists(), (
            "the generation the live venv runs from is never removed")
        assert odd.exists(), "an unparseable token is never aged"
