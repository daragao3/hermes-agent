"""Pins the AGENT PUBLISH GATE in scripts/release.py.

WHAT IS BEING PROTECTED. ``release.py --publish`` commits a version bump,
creates an annotated tag, and runs ``git push origin HEAD --tags``. On this
checkout ``origin`` is https://github.com/NousResearch/hermes-agent.git --
UPSTREAM, not the fork's own remote (``daragao3``) -- and the fork carries
thousands of commits origin does not have, so an accidental ``--publish``
offers the entire private fork and every local tag to the public upstream
repository. Nothing in the machine-wide git guard can stop it: that hook reads
the ARGV of the command an agent runs, and ``python scripts/release.py
--publish`` carries no git verb (loops gitguard-script-file-argument-gap-20260909).

WHY THESE TESTS ARE SHAPED THIS WAY. There is no safe way to run ``--publish``
for real: unlike jobflow-platform's refresh script, which can be pointed at a
ref that does not resolve, every path through this one ends at a push. So the
behavioural cases drive the REAL ``main()`` with the REAL gate, and make a
MISSED gate land on a sentinel instead of on git:

  * ``refuse_agent_publish`` is replaced by one marker exception,
  * ``next_available_tag`` -- the first callable after the gate -- by another.

Whichever marker escapes says exactly what happened, and nothing downstream of
the gate can execute either way. A gate that stops firing raises
``_ReachedPastGate`` here rather than tagging and pushing.

THE ORDERING TEST IS NOT DECORATION. A gate placed at the push site instead of
at the top would leave a committed version bump and an annotated tag behind,
so "nothing has been built" would be false. ``test_gate_precedes_every_mutation``
pins that by source order, because every behavioural case above would stay green
if the check merely moved downward.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

RELEASE_PY = Path(__file__).resolve().parents[2] / "scripts" / "release.py"


def _load_release_module():
    spec = importlib.util.spec_from_file_location("_release_gate_under_test", RELEASE_PY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def release():
    return _load_release_module()


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------

CLEAN_ENV = {"PATH": "/usr/bin", "HOME": "/home/diego", "CLAUDIA_HOME": "x"}
AGENT_ENV = {"PATH": "/usr/bin", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "abc"}
HUMAN_CWD = r"C:\Users\diego\.hermes\agent-src"
AGENT_CWD = r"C:\Users\diego\.hermes\agent-src\.claude\worktrees\release-publish-gate"


def test_clean_env_and_repo_root_is_not_evidence(release):
    assert release.agent_session_evidence(CLEAN_ENV, HUMAN_CWD) == []


def test_agent_env_alone_is_evidence(release):
    evidence = release.agent_session_evidence(AGENT_ENV, HUMAN_CWD)
    assert len(evidence) == 1
    assert "CLAUDECODE" in evidence[0]


def test_agent_worktree_cwd_alone_is_evidence(release):
    evidence = release.agent_session_evidence(CLEAN_ENV, AGENT_CWD)
    assert len(evidence) == 1
    assert "worktree" in evidence[0]


def test_both_axes_report_both_lines(release):
    assert len(release.agent_session_evidence(AGENT_ENV, AGENT_CWD)) == 2


def test_an_empty_valued_marker_still_counts(release):
    """Claude Code exports CLAUDE_CODE_DISABLE_CRON with an EMPTY value.

    A truthiness test on the value would miss a real agent session whose only
    surviving marker happened to be one of those.
    """
    assert release.agent_session_evidence({"CLAUDE_CODE_DISABLE_CRON": ""}, HUMAN_CWD)


def test_a_non_roster_claude_variable_is_not_evidence(release):
    """The roster is deliberately narrow.

    A broad CLAUDE* match would refuse for any session that merely has a
    Claude-adjacent variable set -- CLAUDE_MEMORY_TOMBSTONE_WARN is one that is
    set machine-wide here.
    """
    assert release.agent_session_evidence({"CLAUDE_MEMORY_TOMBSTONE_WARN": "1"}, HUMAN_CWD) == []


@pytest.mark.parametrize(
    "cwd",
    [
        # Contains the literal ".claude/worktrees" and is still not an agent
        # worktree: ".claude" is only the tail of a longer directory name and
        # "worktrees" only the head of one. A substring test passes this; a
        # segment test does not. This is the case that discriminates -- a
        # dot-separated look-alike does NOT, because a substring test rejects
        # that one too.
        r"C:\repo\team.claude\worktrees-archive",
        r"C:\repo\my.claude.worktrees-notes",
        r"C:\repo\claude\worktrees\x",
    ],
)
def test_look_alike_paths_are_not_evidence(release, cwd):
    assert release.agent_session_evidence(CLEAN_ENV, cwd) == []


def test_forward_slash_cwd_is_normalised(release):
    assert len(release.agent_session_evidence(CLEAN_ENV, "C:/repo/.claude/worktrees/x")) == 1


def test_degenerate_inputs_return_empty_and_do_not_raise(release):
    assert release.agent_session_evidence({}, "") == []


# ---------------------------------------------------------------------------
# The wiring, through the real main()
# ---------------------------------------------------------------------------

class _Refused(Exception):
    """refuse_agent_publish was reached."""


class _ReachedPastGate(Exception):
    """Execution got past the gate -- the sentinel a MISSED gate lands on."""


def _run_main(release, monkeypatch, argv, environ, cwd):
    monkeypatch.setattr("sys.argv", ["release.py", *argv])
    monkeypatch.setattr(release, "os", release.os)
    monkeypatch.setattr(release.os, "environ", environ)
    monkeypatch.setattr(release.os, "getcwd", lambda: cwd)

    def _refuse(evidence):
        raise _Refused(evidence)

    def _past(*_a, **_kw):
        raise _ReachedPastGate()

    monkeypatch.setattr(release, "refuse_agent_publish", _refuse)
    # The first callable after the gate. Nothing beyond it can run.
    monkeypatch.setattr(release, "next_available_tag", _past)

    return release.main()


def test_agent_session_publish_is_refused(release, monkeypatch):
    with pytest.raises(_Refused):
        _run_main(release, monkeypatch, ["--publish"], AGENT_ENV, AGENT_CWD)


def test_allow_agent_push_overrides_the_refusal(release, monkeypatch):
    with pytest.raises(_ReachedPastGate):
        _run_main(release, monkeypatch, ["--publish", "--allow-agent-push"], AGENT_ENV, AGENT_CWD)


def test_non_agent_publish_is_untouched(release, monkeypatch):
    with pytest.raises(_ReachedPastGate):
        _run_main(release, monkeypatch, ["--publish"], CLEAN_ENV, HUMAN_CWD)


def test_agent_session_without_publish_is_untouched(release, monkeypatch):
    with pytest.raises(_ReachedPastGate):
        _run_main(release, monkeypatch, [], AGENT_ENV, AGENT_CWD)


def test_the_real_refusal_exits_30(release, monkeypatch):
    """The exit code is the contract -- pin the real refuse_agent_publish."""
    monkeypatch.setattr(
        release, "git_result",
        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})(),
    )
    with pytest.raises(SystemExit) as excinfo:
        release.refuse_agent_publish(["synthetic evidence"])
    assert excinfo.value.code == release.EXIT_REFUSED_AGENT_PUBLISH == 30


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_allow_agent_push_is_a_real_flag(release):
    """If the flag is ever renamed, the refusal keeps telling operators to pass
    something that no longer binds -- which reads as an unbypassable gate rather
    than as a typo."""
    source = inspect.getsource(release.main)
    assert '"--allow-agent-push"' in source


def test_gate_precedes_every_mutation(release):
    """The gate must run before the version bump, the commit and the tag.

    Every behavioural test above stays green if the check merely moves
    downward, so source order is pinned explicitly. A gate at the push site
    would leave a committed bump and an annotated tag behind.
    """
    source = inspect.getsource(release.main)
    gate_at = source.index("if args.publish and not args.allow_agent_push:")

    for marker in (
        "update_version_files(",
        '"commit", "-m"',
        '"tag", "-a"',
        '"push", "origin"',
    ):
        assert gate_at < source.index(marker), f"gate must precede {marker!r}"


def test_the_push_site_still_exists(release):
    """Guards against the tests passing because the push was refactored away
    into something this file no longer describes."""
    assert '"push", "origin", "HEAD", "--tags"' in inspect.getsource(release.main)
