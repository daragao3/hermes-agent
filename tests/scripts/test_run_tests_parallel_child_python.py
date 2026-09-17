"""scripts/run_tests_parallel.py::_child_python -- which interpreter the per-file
pytest children run under.

Under the Windows cron overlay the harness itself runs under the venv's BASE
CPython with ``VIRTUAL_ENV`` + ``PYTHONPATH`` overlaid; a child spawned as
``[sys.executable, "-m", "pytest"]`` inherits the raw PYTHONPATH and never
processes the venv's ``.pth`` files (no pywin32 -> concurrent-log-handler cannot
lock -> every file-log emit silently dropped). The helper hands children the
venv launcher instead, and only then.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_tests_parallel.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("run_tests_parallel_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "venv" / "Scripts" / "python.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"")
    return launcher


def test_no_virtual_env_means_sys_executable(harness, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(harness.sys, "platform", "win32")
    assert harness._child_python() == sys.executable


def test_posix_never_substitutes(harness, monkeypatch, tmp_path):
    launcher = _launcher(tmp_path)
    monkeypatch.setenv("VIRTUAL_ENV", str(launcher.parents[1]))
    monkeypatch.setattr(harness.sys, "platform", "linux")
    assert harness._child_python() == sys.executable


def test_windows_overlay_hands_children_the_venv_launcher(harness, monkeypatch, tmp_path):
    launcher = _launcher(tmp_path)
    monkeypatch.setenv("VIRTUAL_ENV", str(launcher.parents[1]))
    monkeypatch.setattr(harness.sys, "platform", "win32")
    # We are "the base interpreter": anything that is not the launcher.
    monkeypatch.setattr(harness.sys, "executable", str(tmp_path / "base" / "python.exe"))
    assert harness._child_python() == str(launcher)


def test_already_the_launcher_stays_put(harness, monkeypatch, tmp_path):
    launcher = _launcher(tmp_path)
    monkeypatch.setenv("VIRTUAL_ENV", str(launcher.parents[1]))
    monkeypatch.setattr(harness.sys, "platform", "win32")
    monkeypatch.setattr(harness.sys, "executable", str(launcher))
    assert harness._child_python() == str(launcher)


def test_missing_launcher_falls_back(harness, monkeypatch, tmp_path):
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "no-such-venv"))
    monkeypatch.setattr(harness.sys, "platform", "win32")
    assert harness._child_python() == sys.executable
