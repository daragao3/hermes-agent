"""``_ensure_tui_node`` never spawns a bare ``bash`` on Windows.

``scripts/lib/node-bootstrap.sh`` is POSIX-only, and on Windows a bare ``bash``
argv resolves through ``CreateProcess`` to ``System32\bash.exe`` -- the WSL
launcher -- so the old code booted the default Linux distro just to fail
``source``-ing a ``C:\`` path.  Windows now takes ``hermes_constants``'
portable-zip bootstrap, the same split ``bootstrap_hermes_managed_node`` makes.
"""

from __future__ import annotations

import os

import pytest

import hermes_constants
from hermes_cli import main_tui_launch


@pytest.fixture
def no_node_on_path(monkeypatch):
    monkeypatch.delenv("HERMES_SKIP_NODE_BOOTSTRAP", raising=False)
    monkeypatch.setattr(main_tui_launch.shutil, "which", lambda name: None)

    def refuse_spawn(*args, **kwargs):
        raise AssertionError(f"subprocess spawned: {args[0] if args else kwargs}")

    monkeypatch.setattr(main_tui_launch.subprocess, "run", refuse_spawn)


def test_windows_bootstraps_managed_node_without_bash(monkeypatch, tmp_path, no_node_on_path):
    node_dir = tmp_path / "node"
    node_dir.mkdir()
    npm = node_dir / "npm.cmd"
    npm.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(main_tui_launch.sys, "platform", "win32")
    monkeypatch.setattr(hermes_constants, "bootstrap_hermes_managed_node", lambda: str(npm))
    monkeypatch.setenv("PATH", "C:\nowhere")

    main_tui_launch._ensure_tui_node()

    parts = os.environ["PATH"].split(os.pathsep)
    assert str(node_dir.resolve()) in parts
    assert parts.index(str(node_dir.resolve())) < parts.index("C:\nowhere")


def test_windows_bootstrap_failure_is_quiet(monkeypatch, no_node_on_path):
    monkeypatch.setattr(main_tui_launch.sys, "platform", "win32")
    monkeypatch.setattr(hermes_constants, "bootstrap_hermes_managed_node", lambda: None)
    before = os.environ.get("PATH", "")

    main_tui_launch._ensure_tui_node()  # no bash, no raise; only existing dirs may be prepended

    for entry in os.environ["PATH"].split(os.pathsep):
        if entry not in before.split(os.pathsep):
            assert os.path.isdir(entry)
