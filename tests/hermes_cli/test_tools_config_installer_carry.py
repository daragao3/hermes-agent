"""Installer callers retain bounded capture through the extracted modules."""
import subprocess
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("uv", ["managed-uv", None])
def test_pip_installer_keeps_managed_resolution_and_bounded_capture(monkeypatch, uv):
    from hermes_cli import tools_config_cua as installer
    monkeypatch.setattr("hermes_cli.managed_uv.ensure_uv", lambda: uv)
    monkeypatch.setattr(installer, "real_executable", lambda: "real-python")
    capture = MagicMock(return_value=subprocess.CompletedProcess([], 0, "installed", ""))
    probe = MagicMock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr("hermes_cli._subprocess_compat.run_text_capture", capture)
    monkeypatch.setattr(installer.subprocess, "run", probe)
    monkeypatch.setattr(installer.subprocess, "Popen", MagicMock(side_effect=AssertionError("unmocked installer")))
    assert installer._pip_install(["test-package"], timeout=17).returncode == 0
    command = capture.call_args.args[0]
    assert command == ([uv, "pip", "install", "test-package"] if uv else
                       ["real-python", "-m", "pip", "install", "test-package"])
    assert capture.call_args.kwargs["timeout"] == 17
    if uv:
        assert capture.call_args.kwargs["env"]["VIRTUAL_ENV"]
        probe.assert_not_called()
    else:
        assert probe.call_args.kwargs["stdout"] == subprocess.DEVNULL
        assert probe.call_args.kwargs["stderr"] == subprocess.DEVNULL


def test_chromium_install_uses_bounded_capture_and_invalidates_readiness(monkeypatch):
    from hermes_cli import tools_config_post_setup as setup
    from tools import browser_tool
    capture = MagicMock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("hermes_cli._subprocess_compat.run_text_capture", capture)
    monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=AssertionError("unmocked installer")))
    monkeypatch.setattr(browser_tool, "_cached_chromium_installed", False)
    setup._install_chromium(["browser-test", "install"])
    capture.assert_called_once_with(["browser-test", "install"], cwd=str(setup.PROJECT_ROOT), timeout=600)
    assert browser_tool._cached_chromium_installed is None
