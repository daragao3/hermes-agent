"""Regression tests for issue #8340.

When a user command backgrounds a child process (``cmd &``, ``setsid cmd &
disown``, etc.), the backgrounded grandchild inherits the write-end of our
stdout pipe via fork().  Before the fix, the drain thread's blocking
``for line in proc.stdout`` would never see EOF until that grandchild
closed the pipe — causing the terminal tool to hang for the full lifetime
of the backgrounded service (indefinitely for a uvicorn server).

The fix switches ``_drain()`` to select()-based non-blocking reads and
stops draining shortly after bash exits even if the pipe hasn't EOF'd.

On Windows — where ``select()`` only works on sockets — the drain polls
``PeekNamedPipe`` (hermes_cli._subprocess_compat.windows_pipe_readable_bytes)
with the same stop-after-exit semantics, and ``_kill_process`` takes the
whole process tree (``taskkill /T /F``) instead of ``proc.terminate()``,
so a timed-out foreground child can't outlive the kill holding the
inherited pipe write-end.  This file guards both mechanisms and runs on
every platform.
"""
import os
import shlex
import sys
from types import SimpleNamespace
from pathlib import Path
import time

import pytest

from tools.environments.local import LocalEnvironment







@pytest.fixture
def local_env(tmp_path):
    env = LocalEnvironment(cwd=str(tmp_path))
    try:
        yield env
    finally:
        env.cleanup()




@pytest.fixture
def owned_child(tmp_path):
    """One disposable child; cooperative cleanup never scans or kills by name."""
    import psutil

    script = tmp_path / "owned-pipe-child.py"
    pid_file = tmp_path / "child.pid"
    stop_file = tmp_path / "stop-child"
    script.write_text(
        "import os, pathlib, time\n"
        "root = pathlib.Path(__file__).parent\n"
        "(root / 'child.pid').write_text(str(os.getpid()))\n"
        "deadline = time.monotonic() + 45\n"
        "while not (root / 'stop-child').exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.02)\n",
        encoding="utf-8",
    )

    def running():
        if not pid_file.exists():
            return False
        try:
            process = psutil.Process(int(pid_file.read_text()))
            argv = [arg.replace("\\", "/") for arg in process.cmdline()]
            return script.as_posix() in argv and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    command = f"{shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(script.as_posix())}"
    ready = f"while [ ! -s {shlex.quote(pid_file.as_posix())} ]; do sleep 0.01; done"
    try:
        yield SimpleNamespace(command=command, ready=ready, running=running, pid_file=pid_file)
    finally:
        stop_file.touch()
        deadline = time.monotonic() + 5
        while running() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not running(), "owned child did not acknowledge its stop file"

class TestBackgroundChildDoesNotHang:
    """Regression guard for issue #8340."""

    def test_plain_background_returns_promptly(self, local_env, owned_child):
        """Background child holds stdout open after its shell returns."""
        command = f"{owned_child.command} & {owned_child.ready}; echo hermes_8340_plain_bg"
        started = time.monotonic()
        result = local_env.execute(command, timeout=15)
        assert time.monotonic() - started < 10.0
        assert result["returncode"] == 0
        assert "hermes_8340_plain_bg" in result["output"]
        assert owned_child.pid_file.exists()


    @pytest.mark.skipif(os.name == "nt", reason="setsid/disown is a POSIX process-session contract")
    def test_setsid_disown_pattern_returns_promptly(self, local_env, owned_child):
        command = f"setsid {owned_child.command} > /dev/null 2>&1 < /dev/null & disown; {owned_child.ready}; echo started"
        started = time.monotonic()
        result = local_env.execute(command, timeout=15)
        assert time.monotonic() - started < 10.0
        assert result["returncode"] == 0
        assert "started" in result["output"]
        assert owned_child.pid_file.exists()



    def test_default_capture_is_full_fidelity_for_internal_consumers(
        self, local_env
    ):
        """Default execute() (no bounded_capture) must return complete output.

        Internal consumers — file-operation ``cat`` reads that feed the patch
        engine, code-execution RPC reads, log reads — rely on full-fidelity
        capture. Bounding them at tool_output.max_bytes would CORRUPT files
        on read-modify-write (#64435 review finding), so only the foreground
        terminal tool opts in via bounded_capture=True.
        """
        # ~200 KB — four times the default 50 KB cap.
        command = (
            "python3 -c \"import sys; "
            "sys.stdout.write('START-MARK\\n' + ('y' * 200000) + '\\nEND-MARK')\""
        )

        result = local_env.execute(command, timeout=10)

        assert result["returncode"] == 0
        assert "[OUTPUT TRUNCATED" not in result["output"]
        assert result["output"].startswith("START-MARK")
        assert result["output"].endswith("END-MARK")
        assert len(result["output"]) > 200000


    def test_utf8_multibyte_across_read_boundary(self, local_env):
        """Multibyte UTF-8 characters straddling a 4096-byte ``os.read()`` boundary
        must be decoded correctly via the incremental decoder — not lost to a
        ``UnicodeDecodeError`` fallback.  Regression for a bug in the first draft
        of the fix where a strict ``bytes.decode('utf-8')`` on each raw chunk
        wiped the entire buffer as soon as any chunk split a multi-byte char.
        """
        # 10000 "日" chars = 30000 bytes — guaranteed to cross multiple 4096
        # read boundaries, and most boundaries will land in the middle of the
        # 3-byte UTF-8 encoding of U+65E5.
        cmd = (
            'python3 -c \'import sys; '
            'sys.stdout.buffer.write(chr(0x65e5).encode("utf-8") * 10000); '
            'sys.stdout.buffer.write(b"\\n")\''
        )
        result = local_env.execute(cmd, timeout=10)
        assert result["returncode"] == 0
        # All 10000 characters must survive the round-trip
        assert result["output"].count("\u65e5") == 10000, (
            f"lost multibyte chars across read boundaries: got "
            f"{result['output'].count(chr(0x65e5))} / 10000"
        )
        # And the "[binary output detected ...]" fallback must NOT fire
        assert "binary output detected" not in result["output"]

    def test_invalid_utf8_uses_replacement_not_fallback(self, local_env):
        """Truly invalid byte sequences must be substituted with U+FFFD (matching
        the pre-fix ``errors='replace'`` behaviour of the old ``TextIOWrapper``
        drain), not clobber the entire buffer with a fallback placeholder.
        """
        # Write a deliberate invalid UTF-8 lead byte sandwiched between valid ASCII
        cmd = (
            'python3 -c \'import sys; '
            'sys.stdout.buffer.write(b"before "); '
            'sys.stdout.buffer.write(b"\\xff\\xfe"); '
            'sys.stdout.buffer.write(b" after\\n")\''
        )
        result = local_env.execute(cmd, timeout=15)
        assert result["returncode"] == 0
        assert "before" in result["output"]
        assert "after" in result["output"]
        assert "binary output detected" not in result["output"]

    def test_timeout_kill_does_not_orphan_children(self, local_env, owned_child):
        """The foreground timeout must terminate the actual child as well as bash."""
        started = time.monotonic()
        result = local_env.execute(owned_child.command, timeout=2)
        elapsed = time.monotonic() - started
        assert result["returncode"] == 124
        assert owned_child.pid_file.exists(), "child must have started before timing out"
        deadline = time.monotonic() + 5
        while owned_child.running() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not owned_child.running(), "foreground child survived the timeout tree kill"
        # execute's outer backstop includes 2s grace, then synchronous native
        # tree cleanup. Still return well before the child's 45s safety exit.
        assert elapsed < 12.0
