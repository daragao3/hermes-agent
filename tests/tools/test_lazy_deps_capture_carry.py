import subprocess
from unittest.mock import create_autospec

import pytest

from hermes_cli import _subprocess_compat as capture
from tools import lazy_deps as ld


def test_capture_preserves_checked_failure_and_timeout(monkeypatch):
    run = create_autospec(capture.run_text_capture)
    run.return_value = subprocess.CompletedProcess(["fake"], 4, "out", "err")
    monkeypatch.setattr(capture, "run_text_capture", run)
    with pytest.raises(subprocess.CalledProcessError) as error:
        ld._run_installer(["fake"], timeout=7, check=True)
    assert (error.value.returncode, error.value.stdout, error.value.stderr) == (4, "out", "err")
    run.assert_called_once_with(["fake"], timeout=7)
    run.side_effect = subprocess.TimeoutExpired("fake", 7)
    with pytest.raises(subprocess.TimeoutExpired):
        ld._run_installer(["fake"], timeout=7)


def test_pip_and_bootstrap_use_real_interpreter(monkeypatch):
    monkeypatch.setattr(ld, "_lazy_install_target", lambda: None)
    monkeypatch.setattr(ld, "_uv_binary", lambda: None)
    monkeypatch.setattr(ld, "real_executable", lambda: "real-python.exe")
    monkeypatch.setattr(ld, "_warm_installed_bytecode", lambda *a: None)
    run = create_autospec(capture.run_text_capture)
    run.side_effect = [subprocess.CompletedProcess([], 1, "", "missing pip"),
                       subprocess.CompletedProcess([], 0, "", ""),
                       subprocess.CompletedProcess([], 0, "", "")]
    monkeypatch.setattr(capture, "run_text_capture", run)
    assert ld._venv_pip_install(("fake-package==1",)).success
    commands = [call.args[0] for call in run.call_args_list]
    assert commands == [["real-python.exe", "-m", "pip", "--version"],
                        ["real-python.exe", "-m", "ensurepip", "--upgrade", "--default-pip"],
                        ["real-python.exe", "-m", "pip", "install", "fake-package==1"]]
