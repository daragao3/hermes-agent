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

    env = SimpleNamespace(_exec=MagicMock())
    ModalEnvironment._modal_upload(env, str(host_file), EVIL_REMOTE)

    cmd = env._exec.call_args_list[0][0][0]
    mkdir_part = cmd.split(" && ")[0]
    assert mkdir_part == f"mkdir -p {shlex.quote(EVIL_PARENT)}"
    assert "\\" not in mkdir_part


def test_scp_upload_uses_posix_parent(tmp_path, monkeypatch):
    host_file = tmp_path / "token.txt"
    host_file.write_text("secret", encoding="utf-8")

    monkeypatch.setattr(
        "tools.environments.ssh.run_capture",
        lambda cmd, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    env = SimpleNamespace(
        _run_ssh=MagicMock(),
        _target_flags=lambda flag: [],
        control_socket="/tmp/cs",
        port=22,
        key_path=None,
        user="root",
        host="example.com",
    )
    SSHEnvironment._scp_upload(env, str(host_file), EVIL_REMOTE)

    mkdir_cmd = env._run_ssh.call_args_list[0][0][0]
    assert mkdir_cmd == f"mkdir -p {shlex.quote(EVIL_PARENT)}"
    assert "\\" not in mkdir_cmd
