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

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-windows-footguns.py"


# TIMEOUT BUDGET, re-set 2026-09-15 when tests/ and evals/ joined `--all`.
#
# The scan went from 1932 files to 6651, i.e. ~7.9s to ~17.5s of per-line work
# on an idle box -- already past the old `timeout=20`, and this box measured
# 44.7s for the same scan while loaded, so a bound near the true cost is a
# flake generator, not a hang detector.
#
# The ORDER of the two bounds is the part that matters. pyproject sets
# `--timeout=30 --timeout-method=thread`; a thread watchdog cannot interrupt a
# blocked `subprocess.run`, so when it wins the race it dumps a stack ending in
# `threading._wait_for_tstate_lock` and, observed on this box, can take the
# whole session down with an INTERNALERROR instead of failing one test. So the
# per-test mark must sit ABOVE the subprocess bound, and the subprocess bound
# must be what actually fires: `subprocess.TimeoutExpired` names the scan.
_SCAN_TIMEOUT_S = 150
_TEST_TIMEOUT_S = 180
assert _SCAN_TIMEOUT_S < _TEST_TIMEOUT_S, "the subprocess bound must fire first"


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_full_repo_scan_has_no_unsuppressed_windows_footguns():
    """Mirrors check_subprocess_stdin.py's wrapper: run the real checker
    against the whole repo (--all) and require a clean exit, so this test
    file — not just institutional memory — is what catches the next
    bare os.killpg/signal.SIGKILL-style regression."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--all"],
        capture_output=True,
        text=True,
        # See _SCAN_TIMEOUT_S above: a hang detector, not a performance
        # budget. Scan cost is pinned in test_footgun_prefilter.py; what this
        # test asserts is the exit status.
        timeout=_SCAN_TIMEOUT_S,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, (
        f"Windows footgun check failed:\n{result.stdout}\n{result.stderr}"
    )


def _load_linter_module():
    # Same shape as tests/scripts/test_footgun_prefilter.py: register in
    # sys.modules BEFORE exec_module so @dataclass can resolve __module__.
    spec = importlib.util.spec_from_file_location("check_windows_footguns", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_windows_footguns"] = mod
    spec.loader.exec_module(mod)
    return mod


def _tracked_python_files() -> set[str]:
    out = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.py", "*.pyw", "*.pyi"],
        cwd=REPO_ROOT,
        text=True, encoding="utf-8", errors="replace",
    )
    return {rel for rel in (p.strip() for p in out.split("\0")) if rel}


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_all_covers_every_tracked_first_party_python_file():
    """`--all` must not silently stop covering a package.

    The list this replaced was eight hardcoded package names that never grew a
    `tui_gateway/` entry, so `tui_gateway/host_supervisor.py` carried a bare
    `os.kill(pid, 0)` indefinitely while CONTRIBUTING.md banned the pattern and
    lint.yml ran this script as a blocking gate. `--all` reported
    "No Windows footguns found" the entire time; the same checkout, pointed at
    that one file, exited 1. Nothing in the suite could tell the difference,
    because every test asserted the EXIT STATUS of a scan whose FILE SET was
    the broken part. This asserts the file set, as `--all` itself computes it.
    """
    linter = _load_linter_module()

    # Drive the REAL `--all` code path, not get_all_scan_files() directly.
    # Asserting against the helper is vacuous: it passes with `--all` still
    # wired to the old hardcoded root list, which is the one regression this
    # test exists to catch (confirmed by mutating main() and watching an
    # earlier version of this test stay green).
    seen: list[Path] = []
    real_scan_file = linter.scan_file
    linter.scan_file = lambda path, footguns: (seen.append(path), real_scan_file(path, footguns))[1]
    try:
        linter.main(["--all"])
    finally:
        linter.scan_file = real_scan_file
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in seen}
    expected = {
        rel for rel in _tracked_python_files()
        if rel.split("/", 1)[0] not in linter.ALL_SCAN_SKIP_TOP_LEVEL
        and linter.should_scan_file(REPO_ROOT / rel)
    }
    missing = expected - scanned
    assert not missing, (
        "--all no longer covers tracked first-party Python files: "
        f"{sorted(missing)[:20]}"
    )


@pytest.mark.timeout(_TEST_TIMEOUT_S)
def test_all_never_descends_into_agent_worktrees_or_stale_venvs():
    """The named-root list excluded `.claude/worktrees/` (one checkout per
    agent session on this box) and the stale venvs by accident of never naming
    them. The git-derived list must keep that property on purpose -- a scan
    that walked the worktrees would multiply its own cost by the fleet size and
    report other sessions' in-flight edits as findings in this tree."""
    files = _load_linter_module().get_all_scan_files()
    assert files, "--all resolved to an empty file set"

    # RELATIVE to REPO_ROOT, deliberately. This checkout is itself inside
    # `.claude/worktrees/`, so an absolute-substring test flags every file in
    # the tree and is not a test of anything (it failed that way when written).
    strays = []
    for path in files:
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()  # raises if outside
        if rel.startswith((".claude/", ".venv/", "venv/")) or "/site-packages/" in rel:
            strays.append(rel)
    assert not strays, f"--all reached into a nested checkout or venv: {strays[:10]}"


def test_all_scan_skip_list_is_pinned():
    """test_all_covers_every_tracked_first_party_python_file derives what it
    expects FROM ALL_SCAN_SKIP_TOP_LEVEL, so adding a package to that set would
    silence it rather than fail it -- the same shape as the drift that started
    this. Pin the set here so growing it costs a deliberate edit to a test whose
    name says what it is guarding.

    It held {"tests", "evals"} while a measured 2996-finding backlog was worked
    down. That reached zero on 2026-09-15, so the set is now pinned EMPTY: any
    entry at all re-opens the hole the git-derived file list closed.
    """
    linter = _load_linter_module()
    assert linter.ALL_SCAN_SKIP_TOP_LEVEL == set(), (
        "--all stopped scanning a top-level tree. The skip list is empty by "
        "design -- the tests/evals backlog that justified it is gone. "
        "Excluding anything here hides first-party code from a blocking gate."
    )
