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
"""

import json
import logging
import os

import pytest

from tools import checkpoint_manager, credential_files, file_tools, file_tools_paths, terminal_tool_config


class _PathProxy:
    def __init__(self, isabs):
        self.isabs = isabs

    def __getattr__(self, name):
        return getattr(os.path, name)


class _OsProxy:
    """``os`` with only ``path.isabs`` replaced; everything else forwards."""

    def __init__(self, isabs):
        self.path = _PathProxy(isabs)

    def __getattr__(self, name):
        return getattr(os, name)


def _host_isabs_forbidden(*_args, **_kwargs):
    raise AssertionError("host os.path.isabs consulted for a POSIX-contract path")


def _host_isabs_313_ntpath(path):
    """ntpath.isabs on CPython 3.13: only drive- or UNC-rooted paths are absolute."""
    text = os.fspath(path).replace("\\", "/")
    return (len(text) >= 3 and text[1] == ":" and text[2] == "/") or text.startswith("//")


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
