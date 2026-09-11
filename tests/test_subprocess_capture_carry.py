"""Real subprocess capture plus delegated skill environment preservation."""
import os
import subprocess
import sys

import pytest

from hermes_cli._subprocess_compat import run_text_capture


def test_capture_preserves_input_environment_cwd_and_utf8(tmp_path):
    env = dict(os.environ, HERMES_CARRY_TEST="present", PYTHONIOENCODING="utf-8")
    result = run_text_capture(
        [sys.executable, "-c", "import os,sys; print(os.getcwd()); print(os.environ['HERMES_CARRY_TEST']); print(sys.stdin.read())"],
        cwd=tmp_path, env=env, input="olá", timeout=20,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == [str(tmp_path), "present", "olá"]
    assert result.stderr == ""


def test_capture_timeout_does_not_drain_descendant_pipe_forever():
    with pytest.raises(subprocess.TimeoutExpired):
        run_text_capture(
            [sys.executable, "-c", "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); time.sleep(30)"],
            timeout=0.5,
        )


def test_inline_shell_carries_delegated_environment(monkeypatch, tmp_path):
    from agent import delegation_context, skill_preprocessing
    calls = []
    monkeypatch.setattr(delegation_context, "delegated_child_subprocess_env", lambda: {"HERMES_CARRY_TEST": "scoped"})
    def capture(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "captured", "")
    monkeypatch.setattr(skill_preprocessing, "run_text_capture", capture)
    assert skill_preprocessing.run_inline_shell("example", tmp_path, 3) == "captured"
    assert calls == [(["bash", "-c", "example"], {"cwd": str(tmp_path), "timeout": 3, "env": {"HERMES_CARRY_TEST": "scoped"}})]
