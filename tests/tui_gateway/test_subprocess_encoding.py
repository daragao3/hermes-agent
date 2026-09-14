"""Regression tests for UTF-8 encoding hardening in tui_gateway/server.py (#53137).

On Windows with a non-UTF-8 system locale (e.g. GBK on Chinese Windows),
text-mode subprocess reads defaulted to the locale encoding. When a child
process emitted bytes invalid in that locale, an unhandled UnicodeDecodeError
crashed the reader thread / gateway thread.

#53137 added encoding="utf-8", errors="replace" to every text-mode subprocess
call in tui_gateway/server.py. These tests assert that the kwargs survive so
the crash class cannot silently regress.

# Test pattern adapted from @devorun's PR #52700 (salvage convention).
"""

from __future__ import annotations

import sys

from unittest.mock import MagicMock, patch

import hermes_cli._subprocess_compat as _subprocess_compat
import tui_gateway.server as server


# ── helpers ──────────────────────────────────────────────────────────────

def _make_completed_process() -> MagicMock:
    """A CompletedProcess-like mock with str stdout/stderr (text=True contract)."""
    cp = MagicMock()
    cp.stdout = ""
    cp.stderr = ""
    cp.returncode = 0
    return cp


# ── _SlashWorker.Popen path ──────────────────────────────────────────────

def test_slash_worker_popen_uses_utf8_replace():
    """The slash-worker subprocess.Popen must pass encoding="utf-8" and
    errors="replace" so invalid bytes in child stdout/stderr don't raise
    UnicodeDecodeError inside the drain threads (#53137).
    """
    with patch.dict("sys.modules", {
        "hermes_constants": MagicMock(
            get_hermes_home=MagicMock(return_value="/tmp/hermes_test")
        ),
    }):
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value.stdout = MagicMock()
            mock_popen.return_value.stderr = MagicMock()

            from tui_gateway.server import _SlashWorker

            _SlashWorker(
                session_key="test_key",
                model="test-model",
            )

            assert mock_popen.called, "Popen was not invoked"
            kwargs = mock_popen.call_args[1]
            assert kwargs.get("encoding") == "utf-8", (
                f"slash-worker Popen must set encoding='utf-8' (got {kwargs.get('encoding')!r})"
            )
            assert kwargs.get("errors") == "replace", (
                f"slash-worker Popen must set errors='replace' (got {kwargs.get('errors')!r})"
            )


# ── captured-exec handlers (cli.exec / shell.exec / quick-command) ───────
#
# These three no longer call ``subprocess.run`` themselves. This fork routes
# every captured exec through ``hermes_cli._subprocess_compat.run_text_capture``
# (a fork-owned helper: present at 8586e305a2^1, absent at ^2), which spawns
# with *binary* pipes and does the decode itself in ``_read_text`` --
# ``content.decode("utf-8", errors="replace")``. The #53137 invariant is
# therefore still enforced, one layer down; ``encoding=``/``errors=`` kwargs on
# ``subprocess.run`` are simply the wrong shape to assert against now.
#
# So these tests pin the ROUTING (the handler reaches the helper that owns the
# decode), and ``test_run_text_capture_replaces_invalid_utf8`` below pins the
# GUARANTEE itself against a real child process.
#
# Patching ``subprocess.run`` here would not merely miss -- it would pass
# vacuously. ``hermes_cli.banner.check_for_updates`` runs ``_git_run`` on a
# background thread at import, and those calls land in the mock: a
# ``patch("subprocess.run")`` assertion in this file reads *banner's* kwargs,
# and ``call_args`` (the last call) is whichever one that daemon thread
# happened to make last. Measured 2026-09-14: 4 calls, one of them with no
# encoding kwarg at all.


def _patch_capture():
    """Patch the fork's captured-exec seam; returns the mock."""
    return patch.object(
        _subprocess_compat, "run_text_capture", return_value=_make_completed_process()
    )


def test_cli_exec_routes_through_run_text_capture():
    """cli.exec must reach the utf-8/replace-decoding capture helper (#53137)."""
    handler = server._methods["cli.exec"]
    with _patch_capture() as mock_capture:
        # Non-interactive argv that passes _cli_exec_blocked.
        handler(1, {"argv": ["--version"]})
        assert mock_capture.called, "cli.exec did not reach run_text_capture"


def test_shell_exec_routes_through_run_text_capture():
    """shell.exec must reach the utf-8/replace-decoding capture helper (#53137)."""
    handler = server._methods["shell.exec"]
    with _patch_capture() as mock_capture:
        # A harmless, non-dangerous command that passes the approval gate.
        with patch("tools.approval_detection.detect_hardline_command", return_value=(False, "")),              patch("tools.approval_detection.detect_dangerous_command", return_value=(False, None, "")):
            handler(1, {"command": "echo hello"})
        assert mock_capture.called, "shell.exec did not reach run_text_capture"


def test_quick_command_exec_routes_through_run_text_capture():
    """A quick_command of type 'exec' dispatched via command.dispatch must
    reach the utf-8/replace-decoding capture helper (#53137)."""
    handler = server._methods["command.dispatch"]
    with _patch_capture() as mock_capture,          patch("tui_gateway.server._load_cfg", return_value={
             "quick_commands": {"runcmd": {"type": "exec", "command": "echo hi"}}
         }),          patch("tools.environments.local._sanitize_subprocess_env", return_value={"PATH": "/usr/bin"}):
        handler(1, {"name": "runcmd", "arg": "", "session_id": ""})
        assert mock_capture.called, "quick-command exec did not reach run_text_capture"


# ── the #53137 guarantee itself, against a real child ────────────────────

def test_run_text_capture_replaces_invalid_utf8():
    """Invalid bytes in child stdout must decode to U+FFFD, never raise.

    This is the actual regression #53137 guarded: on a non-UTF-8 system locale
    a child emitting undecodable bytes crashed the reader thread. Asserted
    behaviourally rather than by kwarg shape, so it survives the next refactor
    of how the spawn is spelled.
    """
    child = (
        "import sys; "
        "sys.stdout.buffer.write(b'ok' + bytes([255, 254, 128]) + b'end')"
    )
    result = _subprocess_compat.run_text_capture(
        [sys.executable, "-c", child],
        timeout=60,
    )
    assert result.returncode == 0
    assert isinstance(result.stdout, str)
    assert "ok" in result.stdout and "end" in result.stdout
    assert "�" in result.stdout, (
        f"invalid bytes must decode to U+FFFD (got {result.stdout!r})"
    )
