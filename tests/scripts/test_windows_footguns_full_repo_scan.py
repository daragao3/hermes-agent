"""Full-repo self-scan wrapper for scripts/check-windows-footguns.py.

scripts/check_subprocess_stdin.py has had a pytest wrapper (see
tests/tools/test_subprocess_stdin_guard.py's test_all_tui_subprocess_calls_
have_stdin) that runs the checker with its default full-scan behavior and
asserts a clean exit — so a normal pytest run of that file catches
regressions even when no one remembers to run the standalone script by hand.
check-windows-footguns.py had no equivalent: only a narrow rule-level test
(tests/scripts/test_footgun_subprocess_encoding.py, scoped to the
text=True/encoding= rule) existed, so a bare ``os.killpg``/``signal.SIGKILL``
regression (caught by CI running the real script with --all, not by any
local pytest run) shipped in the T1-T3 npx-agent-browser hardening commit
before anyone ran the script directly. This closes that gap the same way
the stdin guard already closes its equivalent one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-windows-footguns.py"


def test_full_repo_scan_has_no_unsuppressed_windows_footguns():
    """Mirrors check_subprocess_stdin.py's wrapper: run the real checker
    against the whole repo (--all) and require a clean exit, so this test
    file — not just institutional memory — is what catches the next
    bare os.killpg/signal.SIGKILL-style regression."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--all"],
        capture_output=True,
        text=True,
        # Must stay UNDER pyproject's `--timeout=30` per-test cap, not above
        # it: pytest-timeout fires first and, with --timeout-method=thread,
        # cannot interrupt a blocked subprocess.run cleanly -- it dumps a
        # stack ending in threading._wait_for_tstate_lock, which reads like a
        # deadlock in this test and says nothing about the scan. A bound here
        # instead raises subprocess.TimeoutExpired, which names the scan.
        #
        # The old value was 60 -- above the cap, so unreachable, and in any
        # case a performance budget rather than a hang detector: the scan took
        # ~113s then and the gate could not report the five real footguns it
        # had found. It measures ~5.6s since the prefilter landed, so 20s is
        # ~3.5x headroom. Scan cost is pinned in test_footgun_prefilter.py;
        # what this test asserts is the exit status.
        timeout=20,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f"Windows footgun check failed:\n{result.stdout}\n{result.stderr}"
    )
