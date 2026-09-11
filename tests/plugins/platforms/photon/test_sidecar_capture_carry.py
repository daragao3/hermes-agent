import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from hermes_cli import _subprocess_compat as capture
from plugins.platforms.photon import adapter


def test_reinstall_uses_bounded_capture_and_fallback_in_active_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: "fake-npm.cmd")
    monkeypatch.setattr(adapter, "_sidecar_dir", lambda: tmp_path)
    run = Mock(side_effect=[SimpleNamespace(returncode=1, stderr="ci failed", stdout=""),
                            SimpleNamespace(returncode=0, stderr="", stdout="installed")])
    monkeypatch.setattr(capture, "run_text_capture", run)
    direct = Mock(side_effect=AssertionError("unbounded subprocess capture forbidden"))
    monkeypatch.setattr(adapter.subprocess, "run", direct)
    adapter._reinstall_sidecar_deps()
    assert [call.args[0] for call in run.call_args_list] == [
        ["fake-npm.cmd", "ci"], ["fake-npm.cmd", "install"]]
    for call in run.call_args_list:
        assert call.kwargs["cwd"] == str(tmp_path)
        assert call.kwargs["timeout"] == adapter._NPM_REINSTALL_TIMEOUT
        assert "capture_output" not in call.kwargs
    direct.assert_not_called()


def test_reinstall_timeout_is_bounded_and_does_not_launch_another_install(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter.shutil, "which", lambda name: "fake-npm.cmd")
    monkeypatch.setattr(adapter, "_sidecar_dir", lambda: tmp_path)
    run = Mock(side_effect=subprocess.TimeoutExpired("fake-npm", adapter._NPM_REINSTALL_TIMEOUT))
    monkeypatch.setattr(capture, "run_text_capture", run)
    adapter._reinstall_sidecar_deps()
    run.assert_called_once()
