"""Remote sandbox paths must be POSIX regardless of the host OS.

The single-file upload helpers in the container/remote backends derive the
parent directory of a *remote* path in order to ``mkdir -p`` it before the
transfer.  Deriving it with :mod:`pathlib` yields ``WindowsPath`` semantics on
a Windows host, producing ``\\root\\.hermes`` for a remote Linux sandbox.

These tests pin the POSIX behaviour and the shell-quoting guarantee together:
the parent must stay a single quoted argument so metacharacters in a path
cannot break out into a second command.
"""

import shlex
from types import SimpleNamespace
from unittest.mock import MagicMock

from tools.environments.daytona import DaytonaEnvironment
from tools.environments.modal import ModalEnvironment
from tools.environments.ssh import SSHEnvironment

# A remote path whose directory component contains shell metacharacters.
EVIL_REMOTE = "/root/.hermes/skills/evil; touch /tmp/pwned/file.txt"
EVIL_PARENT = "/root/.hermes/skills/evil; touch /tmp/pwned"


def test_daytona_upload_uses_posix_parent(tmp_path):
    host_file = tmp_path / "token.txt"
    host_file.write_text("secret", encoding="utf-8")

    env = SimpleNamespace(_sandbox=MagicMock())
    DaytonaEnvironment._daytona_upload(env, str(host_file), EVIL_REMOTE)

    cmd = env._sandbox.process.exec.call_args_list[0][0][0]
    assert cmd == f"mkdir -p {shlex.quote(EVIL_PARENT)}"
    assert "\\" not in cmd


def test_modal_upload_uses_posix_parent(tmp_path):
    host_file = tmp_path / "token.txt"
    host_file.write_bytes(b"secret")

    captured = {}

    # _modal_upload now goes through the backend's own ``_exec`` (stdin-streamed
    # command runner); the mkdir text is what this test is about.
    def _fake_exec(cmd, stdin=None, timeout=None, **_kw):
        captured["cmd"] = cmd
        captured["stdin"] = stdin

    env = SimpleNamespace(_exec=_fake_exec)
    ModalEnvironment._modal_upload(env, str(host_file), EVIL_REMOTE)
    assert captured["stdin"]  # the file body rides stdin, not the command line

    mkdir_part = captured["cmd"].split(" && ")[0]
    assert mkdir_part == f"mkdir -p {shlex.quote(EVIL_PARENT)}"
    assert "\\" not in mkdir_part


def test_scp_upload_uses_posix_parent(tmp_path, monkeypatch):
    host_file = tmp_path / "token.txt"
    host_file.write_text("secret", encoding="utf-8")

    calls = []

    # The mkdir goes through the backend's ``_run_ssh``; the scp itself through
    # ``run_capture`` (stubbed so nothing is spawned).
    monkeypatch.setattr(
        "tools.environments.ssh.run_capture",
        lambda cmd, **kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    env = SimpleNamespace(
        _run_ssh=lambda cmd, timeout=None: calls.append(cmd),
        _target_flags=lambda flag: [],
        control_socket="/tmp/cs",
        port=22,
        key_path=None,
        user="root",
        host="example.com",
    )
    SSHEnvironment._scp_upload(env, str(host_file), EVIL_REMOTE)

    mkdir_arg = calls[0]
    assert mkdir_arg == f"mkdir -p {shlex.quote(EVIL_PARENT)}"
    assert "\\" not in mkdir_arg
