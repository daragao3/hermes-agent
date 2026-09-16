"""A git probe that STALLS (killed at ``_GIT_TIMEOUT``) must not be remembered as "not a repo".

Production defect, measured 2026-09-15 (loops session-cwd-follow-settled-worktree-branch-flaky-20260915,
MemPalace hermes/session-cwd-follow-git-probe-timeout-negative-cache-2026-09-15): ``bounded_git_probe``
collapsed "git answered rc!=0" and "bounded_probe_run timed out" into the same ``""``, and
``_RootCache.resolve`` cached any ``""`` for ``_NEG_TTL`` (30s). On a saturated box (p50 1.27s, 6/30
probes over the 1.5s bound) one stalled spawn made ``repo_root``/``common_repo_root`` answer "not a
repo" for 30s: the settle-follow refused the worktree and the session's branch/project label went
blank until the TTL lapsed. Now a stall is cached for ``_STALL_TTL`` only, and the 1.5s fail-open
bound (#68609) and the 30s TTL for GENUINE negatives are both untouched.

Mutation (must go red): in ``_RootCache.resolve`` make every empty value take ``_NEG_TTL`` again
(``ttl = _NEG_TTL``) -- the stall test's second call still reads the cached "" instead of the root.
"""

from __future__ import annotations

import pytest

from tui_gateway import git_probe


@pytest.fixture(autouse=True)
def _clean_cache():
    git_probe.invalidate()
    yield
    git_probe.invalidate()


def _outcome_script(monkeypatch, answers):
    """Patch the spawn seam with a scripted sequence of ``(stdout, stalled)`` outcomes."""
    calls = []

    def fake(argv, *, timeout):
        calls.append(list(argv))
        return answers.pop(0)

    monkeypatch.setattr(git_probe, "bounded_git_probe_outcome", fake)
    return calls


def test_run_git_marks_a_stalled_probe_distinctly_but_still_reads_as_empty(monkeypatch, tmp_path):
    _outcome_script(monkeypatch, [("", True), ("", False), ("main", False)])
    cwd = str(tmp_path)

    stalled = git_probe.run_git(cwd, "rev-parse", "--show-toplevel")
    assert stalled == "" and not stalled  # every ``== ""`` / ``or`` consumer is unchanged
    assert isinstance(stalled, git_probe._StalledProbe)

    negative = git_probe.run_git(cwd, "rev-parse", "--show-toplevel")
    assert negative == "" and not isinstance(negative, git_probe._StalledProbe)

    assert git_probe.run_git(cwd, "branch", "--show-current") == "main"


def test_stalled_probe_is_not_negative_cached_for_the_full_ttl(monkeypatch, tmp_path):
    # The brief's shape: one stall, then git answers. The second call lands INSIDE the old 30s
    # negative window and must re-probe (after the short stall TTL) instead of trusting the "".
    cwd = str(tmp_path)
    calls = _outcome_script(monkeypatch, [("", True), (cwd, False)])
    monkeypatch.setattr(git_probe, "_STALL_TTL", 0.0)  # expire at once; _NEG_TTL stays 30s
    assert git_probe._NEG_TTL == 30.0

    assert git_probe.repo_root(cwd) == ""  # the stalled probe: fail-open, no answer
    assert git_probe.repo_root(cwd) == cwd  # re-probed within the old 30s window
    assert git_probe.repo_root(cwd) == cwd  # positive: cached for the process
    assert len(calls) == 2


def test_stall_is_still_absorbed_briefly_so_a_burst_does_not_respawn(monkeypatch, tmp_path):
    # The single-flight economics the brief asked to weigh: a stall IS cached, just briefly, so a
    # burst of sidebar/session.info callers during one stall costs one spawn, not one each.
    cwd = str(tmp_path)
    calls = _outcome_script(monkeypatch, [("", True), (cwd, False)])
    monkeypatch.setattr(git_probe, "_STALL_TTL", 1000.0)

    assert git_probe.repo_root(cwd) == ""
    for _ in range(10):
        assert git_probe.repo_root(cwd) == ""
    assert len(calls) == 1

    git_probe._cache._neg[cwd] = 0.0  # the stall TTL lapses
    assert git_probe.repo_root(cwd) == cwd
    assert len(calls) == 2


def test_genuine_negative_keeps_the_long_ttl(monkeypatch, tmp_path):
    # rc!=0 ("not a repo") is a fact about the target: the 30s TTL that spares hundreds of non-repo
    # session cwds a re-spawn per sidebar open is preserved -- only STALLS are short-lived.
    cwd = str(tmp_path)
    calls = _outcome_script(monkeypatch, [("", False), (cwd, False)])
    monkeypatch.setattr(git_probe, "_STALL_TTL", 0.0)

    assert git_probe.repo_root(cwd) == ""
    assert git_probe.repo_root(cwd) == ""  # still cached: the stall TTL does not apply
    assert len(calls) == 1


def test_stalled_common_dir_probe_does_not_pin_the_toplevel_as_common_root(monkeypatch, tmp_path):
    # A stalled --git-common-dir probe used to fall back to the toplevel and cache THAT positively for
    # the process -- for a linked worktree, the wrong root forever. Now it expires and re-probes.
    cwd = str(tmp_path)
    common = str(tmp_path / "main")
    calls = _outcome_script(monkeypatch, [
        (cwd, False),                    # rev-parse --show-toplevel
        ("", True),                      # --git-common-dir: stalled
        (f"{common}/.git", False),       # --git-common-dir: answered on re-probe
    ])
    monkeypatch.setattr(git_probe, "_STALL_TTL", 0.0)

    assert git_probe.common_repo_root(cwd) == ""
    assert git_probe.common_repo_root(cwd) == common.replace("\\", "/")
    assert len(calls) == 3


def test_branch_does_not_pay_a_second_spawn_after_a_stall(monkeypatch, tmp_path):
    cwd = str(tmp_path)
    calls = _outcome_script(monkeypatch, [("", True)])
    out = git_probe.branch(cwd)
    assert out == "" and type(out) is str
    assert len(calls) == 1  # no rev-parse --short HEAD fallback after a stall

    calls = _outcome_script(monkeypatch, [("", False), ("abc123", False)])
    assert git_probe.branch(cwd) == "abc123"  # a genuine empty answer still falls back
    assert len(calls) == 2


def test_bounded_git_probe_outcome_reports_a_real_stall_and_not_a_spawn_failure():
    # Live-process control for the seam the unit tests script: only an overrun is a stall.
    import sys

    from hermes_cli._subprocess_compat import bounded_git_probe, bounded_git_probe_outcome

    assert bounded_git_probe_outcome([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3) == ("", True)
    assert bounded_git_probe_outcome(["definitely-not-a-real-binary-87134"], timeout=5) == ("", False)
    assert bounded_git_probe_outcome([sys.executable, "-c", "import sys; sys.exit(128)"], timeout=30) == ("", False)
    assert bounded_git_probe_outcome([sys.executable, "-c", "print('  x  ')"], timeout=30) == ("x", False)
    assert bounded_git_probe([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3) == ""  # contract kept
