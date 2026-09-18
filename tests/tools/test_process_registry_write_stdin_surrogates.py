"""Sibling regression test for #79178: background-PTY stdin must round-trip
surrogateescape content instead of crashing on the strict UTF-8 encode."""
import shlex
import time

import pytest

from tests.timeout_budget import scaled
from tools.process_registry import ProcessRegistry


def _assert_posix_surrogateescape_roundtrip(tmp_path):
    registry = ProcessRegistry()
    out = tmp_path / "out.bin"
    script = tmp_path / "read_stdin.py"
    # readline(): a PTY never delivers EOF, so read one line (canonical mode
    # delivers it after the newline we send).
    script.write_text(
        f"import sys\nopen({str(out)!r}, 'wb').write(sys.stdin.buffer.readline())\n"
    , encoding="utf-8")
    session = registry.spawn_local(
        f"python3 {shlex.quote(str(script))}",
        cwd=str(tmp_path),
        use_pty=True,
    )
    if session._pty is None:
        registry.kill_process(session.id)
        pytest.skip("ptyprocess not available; PTY path not exercised")
    try:
        result = registry.write_stdin(
            session.id, b"\xff".decode("utf-8", "surrogateescape") + "\n"
        )
        assert result["status"] == "ok", result
        # Wait for the CONTENT, and not for the file to exist. The child runs
        # open(out,'wb').write(...). open() creates the file empty, and the
        # bytes arrive only after the PTY delivers the line. The previous wait
        # stopped at out.exists(), which the empty file already satisfies, so
        # the read returned b'' when the parent won that gap.
        #
        # On a 144-worker runner the gap is wide enough to lose every time.
        # This test failed both attempts in CI, and not one time only. It also
        # loses 6 times in 25 runs on an idle 16-core machine.
        deadline = time.monotonic() + 30
        got = b""
        while time.monotonic() < deadline:
            try:
                got = out.read_bytes()
            except FileNotFoundError:
                got = b""
            if got == b"\xff\n":
                break
            time.sleep(0.05)
        assert got == b"\xff\n"
    finally:
        registry.kill_process(session.id)


@pytest.mark.linux_only
def test_linux_pty_surrogateescape_roundtrip(tmp_path):
    _assert_posix_surrogateescape_roundtrip(tmp_path)


@pytest.mark.macos_only
def test_macos_pty_surrogateescape_roundtrip(tmp_path):
    _assert_posix_surrogateescape_roundtrip(tmp_path)


@pytest.mark.windows_only
# The READY window alone (60 s) can exceed the 30 s addopts cap under load;
# the runner hit pytest-timeout inside the wait loop's time.sleep(0.05).
@pytest.mark.timeout(scaled(120))
def test_windows_pty_rejects_surrogate_and_remains_usable(tmp_path):
    registry = ProcessRegistry()
    out = tmp_path / 'valid.txt'
    script = tmp_path / 'read_unicode.py'
    # The child prints READY before blocking on stdin, and the test waits
    # for it instead of writing straight after spawn: input written while the
    # `bash -lic` shell is still initialising its ConPTY console is discarded,
    # so both writes below used to land on nobody and valid.txt never appeared
    # (FileNotFoundError; 5/5 red at 100% host load on 2026-09-18, on either
    # side of the PTY watchdog fix). Same handshake as
    # TestStdinHelpers.test_close_stdin_allows_eof_driven_process_to_finish.
    script.write_text(
        "import sys\n"
        "print('READY', flush=True)\n"
        f"open({str(out)!r}, 'w', encoding='utf-8').write(sys.stdin.readline())\n",
        encoding='utf-8',
    )
    session = registry.spawn_local(f'python3 {shlex.quote(str(script))}', cwd=str(tmp_path), use_pty=True)
    try:
        assert session._pty is not None, 'Windows acceptance requires the real PTY backend'
        # Start window for a login shell + interpreter under ConPTY: READY
        # measured up to ~21 s on a 100%-loaded Windows host (2026-09-18);
        # 60 s is ~3x the worst measurement.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if 'READY' in registry.poll(session.id)['output_preview']:
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                'PTY child never printed READY -- startup failed: '
                f'{registry.poll(session.id)!r}'
            )
        rejected = registry.write_stdin(session.id, '\udcff\n')
        assert rejected['status'] == 'error'
        assert registry.write_stdin(session.id, 'valid\n')['status'] == 'ok'
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if out.exists() and out.read_text(encoding='utf-8') == 'valid\n':
                break
            time.sleep(0.05)
        assert out.read_text(encoding='utf-8') == 'valid\n'
    finally:
        registry.kill_process(session.id)
