"""POSIX-path predicates must not depend on the host's ``os.path.isabs``.

CPython 3.13 changed ``ntpath.isabs`` so a drive-less rooted path
(``/workspace``, ``/dev/zero``, ``/etc/passwd``) is no longer absolute on
Windows. Product sites whose value is a POSIX path BY CONTRACT (an in-sandbox
container cwd, a device path, a git-relative checkpoint path, a '/'-separated
credential path) therefore have to test with ``posixpath`` -- otherwise, on a
Windows host, every container cwd reads as "unusable" and gets discarded, and
``/dev/zero`` is anchored onto the task cwd and slips past the device blocklist.

The mechanism tests below hold on every host: they swap the module-level ``os``
for a proxy whose ``path.isabs`` is 3.13-ntpath-shaped (False for a POSIX root)
or a loud failure, while the module's real ``posixpath`` binding stays intact.
The ``windows_only`` tests pin the real host predicate where the regression
was observed (venv 3.13.15, 2026-09-18).

``TestContainerPathPredicate`` covers the RELATE seam of the same family: a
POSIX-contract value RELATED to (or normalized against) the host -- here
``os.path.abspath`` -- comes back drive-prefixed on Windows, so a POSIX-spelled
prefix test on the result can never match and the guard stops refusing. Its
proxy replaces ``path.abspath`` rather than ``path.isabs``; no ``isabs`` grep
can reach this seam, which is why it needed its own sweep (2026-09-20).
"""

import json
import logging
import os

import pytest

from tools import (
    checkpoint_manager, credential_files, file_tools, file_tools_paths,
    terminal_tool, terminal_tool_config,
)


class _PathProxy:
    def __init__(self, isabs=None, **ops):
        if isabs is not None:
            ops["isabs"] = isabs
        self._ops = ops

    def __getattr__(self, name):
        try:
            return self._ops[name]
        except KeyError:
            return getattr(os.path, name)


class _OsProxy:
    """``os`` with selected ``path.*`` ops replaced; everything else forwards."""

    def __init__(self, isabs=None, **ops):
        self.path = _PathProxy(isabs, **ops)

    def __getattr__(self, name):
        return getattr(os, name)


def _host_isabs_forbidden(*_args, **_kwargs):
    raise AssertionError("host os.path.isabs consulted for a POSIX-contract path")


def _host_isabs_313_ntpath(path):
    """ntpath.isabs on CPython 3.13: only drive- or UNC-rooted paths are absolute."""
    text = os.fspath(path).replace("\\", "/")
    return (len(text) >= 3 and text[1] == ":" and text[2] == "/") or text.startswith("//")


def _host_abspath_ntpath(path):
    """ntpath.abspath on Windows: a drive-less rooted path is completed with the
    cwd's DRIVE, so ``/workspace/proj`` comes back as ``C:\\workspace\\proj``."""
    text = os.fspath(path)
    if text.startswith("/"):
        return "C:" + text.replace("/", chr(92))
    return os.path.abspath(text)


class TestContainerPathPredicate:
    """The RELATE seam: the in-container test must see the value as GIVEN.

    ``_is_container_path`` is what ``tools/terminal_tool`` consults before deciding
    that a cwd names a host directory to mount. Handing it ``os.path.abspath(...)``
    on a Windows host is the defect: the drive letter makes the prefix test fail
    and ``_is_host_cwd`` match, so an in-container cwd is mounted as a host path.
    """

    def test_container_roots_detected_on_the_raw_value(self):
        for cwd in ("/workspace", "/workspace/proj", "/root", "/root/app"):
            assert terminal_tool_config._is_container_path(cwd) is True, cwd
        for cwd in ("/home/me/proj", "/Users/me/proj", "C:/workspace", "rel/dir", "", None):
            assert terminal_tool_config._is_container_path(cwd) is False, cwd

    def test_abspath_destroys_the_prefix_the_guard_tests(self, monkeypatch):
        """The mechanism, pinned on every host: abspath first => the guard fails OPEN."""
        monkeypatch.setattr(terminal_tool_config, "os", _OsProxy(abspath=_host_abspath_ntpath))
        for cwd in ("/workspace/proj", "/root/app"):
            spoiled = terminal_tool_config.os.path.abspath(cwd)
            assert spoiled.startswith(("/workspace", "/root")) is False, spoiled
            # _is_host_cwd matches the injected drive, so the whole branch short-circuits.
            assert terminal_tool_config._is_host_cwd(spoiled) is True, spoiled
            # The predicate under test is immune because it reads the value as given.
            assert terminal_tool_config._is_container_path(cwd) is True, cwd

    @pytest.mark.windows_only
    def test_windows_host_abspath_really_drive_prefixes_a_container_cwd(self):
        """The observed regression on the real host predicate (venv 3.13.15)."""
        spoiled = os.path.abspath("/workspace/proj")
        assert spoiled.startswith(("/workspace", "/root")) is False, spoiled
        assert terminal_tool_config._is_host_cwd(spoiled) is True
        assert terminal_tool_config._is_container_path("/workspace/proj") is True


class TestContainerCwdIsNotMountedAsAHostPath:
    """The call sites: an in-container cwd must stay the container cwd.

    These are what actually regress. ``TestContainerPathPredicate`` only proves the
    predicate is sound; these prove the call sites consult it on the RAW value. Revert
    either site to testing the abspath'd form and both go red with the defect's
    signature -- host_cwd set to a drive-prefixed path that does not exist.
    """

    def _docker_config_cwd(self, monkeypatch, raw):
        monkeypatch.setattr(terminal_tool, "os", _OsProxy(abspath=_host_abspath_ntpath))
        monkeypatch.setattr(terminal_tool, "_tenv",
                            lambda name, default="": raw if name == "TERMINAL_CWD" else default)
        return terminal_tool._resolve_config_cwd("docker", mount_docker_cwd=True)

    @pytest.mark.parametrize("raw", ["/workspace", "/workspace/proj", "/root/app"])
    def test_container_cwd_mounts_nothing_and_is_kept(self, monkeypatch, raw):
        cwd, host_cwd = self._docker_config_cwd(monkeypatch, raw)
        assert host_cwd is None, f"in-container {raw!r} was mounted as host {host_cwd!r}"
        assert cwd == raw

    def test_host_cwd_still_mounts(self, monkeypatch, tmp_path):
        """Control: the fix must not stop a real host cwd from mounting."""
        monkeypatch.setattr(terminal_tool, "_tenv",
                            lambda name, default="": str(tmp_path) if name == "TERMINAL_CWD" else default)
        cwd, host_cwd = terminal_tool._resolve_config_cwd("docker", mount_docker_cwd=True)
        assert host_cwd == os.path.abspath(str(tmp_path))
        assert cwd == "/workspace"

    @pytest.mark.windows_only
    def test_windows_host_keeps_container_cwd_unmounted(self, monkeypatch):
        """The observed regression on the real host abspath (venv 3.13.15)."""
        monkeypatch.setattr(terminal_tool, "_tenv",
                            lambda name, default="": "/workspace/proj" if name == "TERMINAL_CWD" else default)
        cwd, host_cwd = terminal_tool._resolve_config_cwd("docker", mount_docker_cwd=True)
        assert host_cwd is None, f"mounted {host_cwd!r} for an in-container cwd"
        assert cwd == "/workspace/proj"


class TestSessionMountSourceRejectsContainerCwd:
    """``_resolve_task_host_cwd``: a per-session override naming an in-container
    directory must not become a host bind-mount source."""

    def _mount_source(self, monkeypatch, raw, *, abspath=None, force_isdir=False):
        """``force_isdir``: without it the drive-prefixed path simply does not exist and
        ``os.path.isdir`` refuses first, so the test would pass with the guard reverted --
        vacuous. Pinning the prefix check means removing that short-circuit."""
        ops = {}
        if abspath is not None:
            ops["abspath"] = abspath
        if force_isdir:
            ops["isdir"] = lambda _p: True
        if ops:
            monkeypatch.setattr(terminal_tool, "os", _OsProxy(**ops))
        monkeypatch.setattr(terminal_tool, "_docker_session_isolation_enabled", lambda: True)
        monkeypatch.setattr(terminal_tool, "_resolve_container_task_id", lambda task_id: task_id)
        monkeypatch.setattr(terminal_tool, "resolve_task_overrides", lambda task_id: {"cwd": raw})
        return terminal_tool._resolve_task_host_cwd(
            {"env_type": "docker", "docker_mount_cwd_to_workspace": True}, "task42")

    @pytest.mark.parametrize("raw", ["/workspace", "/workspace/proj", "/root/app"])
    def test_container_override_is_refused(self, monkeypatch, raw):
        out = self._mount_source(monkeypatch, raw,
                                 abspath=_host_abspath_ntpath, force_isdir=True)
        assert out is None, f"in-container {raw!r} became mount source {out!r}"

    def test_real_host_dir_still_mounts(self, monkeypatch, tmp_path):
        """Control: a genuine host override still resolves."""
        out = self._mount_source(monkeypatch, str(tmp_path))
        assert out == os.path.abspath(str(tmp_path))

    @pytest.mark.windows_only
    def test_windows_host_refuses_container_override(self, monkeypatch):
        """Real host abspath; only the existence short-circuit is removed."""
        out = self._mount_source(monkeypatch, "/workspace/proj", force_isdir=True)
        assert out is None, f"in-container cwd became mount source {out!r}"


class TestContainerCwdPredicate:
    def test_in_sandbox_cwd_is_usable_without_host_isabs(self, monkeypatch):
        monkeypatch.setattr(terminal_tool_config, "os", _OsProxy(_host_isabs_forbidden))
        for cwd in ("/workspace", "/workspace/task42", "/root/proj", "/srv/app"):
            assert terminal_tool_config._is_unusable_container_cwd(cwd) is False, cwd
        for cwd in ("relative/dir", "./x", "/Users/me/proj", "/home/me/proj", "C:\\Users\\me", "D:/proj"):
            assert terminal_tool_config._is_unusable_container_cwd(cwd) is True, cwd

    @pytest.mark.windows_only
    def test_windows_host_keeps_container_cwd(self):
        """The observed regression: ntpath.isabs('/workspace') is False on 3.13."""
        assert terminal_tool_config._is_unusable_container_cwd("/workspace") is False
        assert terminal_tool_config._is_unusable_container_cwd("/workspace/task42") is False
        assert terminal_tool_config._is_unusable_container_cwd("C:\\Users\\me") is True


class TestRootedPredicate:
    def test_posix_rooted_when_host_isabs_says_no(self, monkeypatch):
        monkeypatch.setattr(file_tools_paths, "os", _OsProxy(_host_isabs_313_ntpath))
        assert file_tools_paths._is_rooted("/workspace/x") is True
        assert file_tools_paths._is_rooted("/dev/zero") is True
        assert file_tools_paths._is_rooted("C:/Users/me") is True
        assert file_tools_paths._is_rooted("rel/x") is False
        assert file_tools_paths._is_rooted("") is False

    def test_host_absolute_still_rooted(self, tmp_path):
        assert file_tools_paths._is_rooted(str(tmp_path)) is True
        assert file_tools_paths._is_rooted(tmp_path) is True

    @pytest.mark.windows_only
    def test_windows_host_treats_posix_root_as_rooted(self):
        assert file_tools_paths._is_rooted("/workspace/task42") is True
        assert file_tools_paths._is_rooted("C:\\Users\\me") is True

    def test_container_cwd_override_survives(self, monkeypatch):
        monkeypatch.setattr(file_tools_paths, "os", _OsProxy(_host_isabs_313_ntpath))
        assert file_tools_paths._sentinel_free_abs_cwd("/workspace/task42") == "/workspace/task42"
        assert file_tools_paths._sentinel_free_abs_cwd("relative/dir") is None
        assert file_tools_paths._sentinel_free_abs_cwd(".") is None


class TestDeviceGuardBase:
    def test_device_path_not_anchored_onto_base(self, tmp_path):
        assert file_tools._is_blocked_device("/dev/zero", base_dir=tmp_path) is True
        assert file_tools._is_blocked_device("/proc/self/fd/0", base_dir=tmp_path) is True
        assert file_tools._is_blocked_device("notes.txt", base_dir=tmp_path) is False

    def test_device_path_not_anchored_when_host_isabs_says_no(self, tmp_path, monkeypatch):
        monkeypatch.setattr(file_tools_paths, "os", _OsProxy(_host_isabs_313_ntpath))
        assert file_tools._is_blocked_device("/dev/zero", base_dir=tmp_path) is True

    @pytest.mark.windows_only
    def test_windows_host_read_file_tool_refuses_device(self):
        result = json.loads(file_tools.read_file_tool("/dev/zero", task_id="win313_dev"))
        assert "device file" in result["error"]


class TestCheckpointFilePath:
    def test_posix_absolute_refused_as_absolute(self, tmp_path, monkeypatch):
        monkeypatch.setattr(checkpoint_manager, "os", _OsProxy(_host_isabs_313_ntpath))
        err = checkpoint_manager._validate_file_path("/etc/passwd", str(tmp_path))
        assert err is not None and "got absolute path" in err
        assert checkpoint_manager._validate_file_path("main.py", str(tmp_path)) is None

    @pytest.mark.windows_only
    def test_windows_host_refuses_posix_absolute_as_absolute(self, tmp_path):
        err = checkpoint_manager._validate_file_path("/etc/passwd", str(tmp_path))
        assert "got absolute path" in err
        err = checkpoint_manager._validate_file_path(str(tmp_path / "x"), str(tmp_path))
        assert "got absolute path" in err


class TestCredentialFilePath:
    def test_posix_absolute_refused_with_absolute_message(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setattr(credential_files, "os", _OsProxy(_host_isabs_313_ntpath))
        with caplog.at_level(logging.WARNING, logger="tools.credential_files"):
            out = credential_files._contained_host_path(
                "/etc/passwd", tmp_path, "ABS-MSG %r", "TRAVERSAL-MSG %r (%s)")
        assert out is None
        assert "ABS-MSG" in caplog.text
        assert "TRAVERSAL-MSG" not in caplog.text
