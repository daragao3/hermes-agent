"""Pins the AGENT UPDATE GATE: ``hermes update``'s apply path refuses from an
agent session, and refuses nowhere else -- above all not on ``--check``.

WHAT IS BEING PROTECTED. The apply path stashes local changes, tries ``git pull
--ff-only origin <branch>``, falls back to ``git reset --hard origin/<branch>``
when the histories have diverged, drops the stash it made, and can reach ``git
push origin main --force-with-lease`` through the fork-sync helper. None of that
is visible to ~/.claude/hooks/block-destructive-git.py, which reads the ARGV of
the command an agent runs: ``hermes update`` carries no git verb (loops
gitguard-script-file-argument-gap-20260909).

THE --check EXEMPTION IS THE POINT OF HALF THESE TESTS. ``hermes update
--check`` is read-only and is how a session is *supposed* to answer "is there an
update?". A gate that swallowed it would push sessions toward the apply path or
toward hand-rolled git, so ``test_check_path_is_never_gated`` is as important as
the refusal itself -- and it is the case a careless "just refuse cmd_update"
implementation breaks.

WHY THE BEHAVIOURAL CASES CANNOT PUBLISH OR RESET. They call the real
``cmd_update`` with the real gate, and replace the first callable PAST the gate
(``_install_hangup_protection``) with a marker exception. A gate that stops
firing raises ``_ReachedPastGate`` here instead of stashing and resetting the
checkout this test is running out of. Nothing downstream of the gate can execute
in either direction.
"""

from __future__ import annotations

import argparse
import inspect
import os

import pytest

from hermes_cli import _agent_session
from hermes_cli import main as cli_main
from hermes_cli.subcommands.update import build_update_parser

CLEAN_ENV = {"PATH": "/usr/bin", "HOME": "/home/diego", "CLAUDIA_HOME": "x"}
AGENT_ENV = {"PATH": "/usr/bin", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "abc"}
HUMAN_CWD = r"C:\Users\diego\.hermes\agent-src"
AGENT_CWD = r"C:\Users\diego\.hermes\agent-src\.claude\worktrees\gate"


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------

def test_clean_env_and_repo_root_is_not_evidence():
    assert _agent_session.agent_session_evidence(CLEAN_ENV, HUMAN_CWD) == []


def test_agent_env_alone_is_evidence():
    evidence = _agent_session.agent_session_evidence(AGENT_ENV, HUMAN_CWD)
    assert len(evidence) == 1 and "CLAUDECODE" in evidence[0]


def test_agent_worktree_cwd_alone_is_evidence():
    evidence = _agent_session.agent_session_evidence(CLEAN_ENV, AGENT_CWD)
    assert len(evidence) == 1 and "worktree" in evidence[0]


def test_both_axes_report_both_lines():
    assert len(_agent_session.agent_session_evidence(AGENT_ENV, AGENT_CWD)) == 2


def test_an_empty_valued_marker_still_counts():
    """CLAUDE_CODE_DISABLE_CRON is exported EMPTY by Claude Code."""
    assert _agent_session.agent_session_evidence({"CLAUDE_CODE_DISABLE_CRON": ""}, HUMAN_CWD)


def test_a_non_roster_claude_variable_is_not_evidence():
    assert _agent_session.agent_session_evidence({"CLAUDE_MEMORY_TOMBSTONE_WARN": "1"}, HUMAN_CWD) == []


@pytest.mark.parametrize(
    "cwd",
    [
        # Contains the literal ".claude/worktrees" yet is not a path segment:
        # a substring test passes this, a segment test does not. The
        # dot-separated look-alike below does NOT discriminate (a substring
        # test rejects it too) and is kept only as a second guard.
        r"C:\repo\team.claude\worktrees-archive",
        r"C:\repo\my.claude.worktrees-notes",
        r"C:\repo\claude\worktrees\x",
    ],
)
def test_look_alike_paths_are_not_evidence(cwd):
    assert _agent_session.agent_session_evidence(CLEAN_ENV, cwd) == []


def test_forward_slash_cwd_is_normalised():
    assert len(_agent_session.agent_session_evidence(CLEAN_ENV, "C:/repo/.claude/worktrees/x")) == 1


def test_degenerate_inputs_return_empty_and_do_not_raise():
    assert _agent_session.agent_session_evidence({}, "") == []


# ---------------------------------------------------------------------------
# The override
# ---------------------------------------------------------------------------

def test_override_requires_a_non_empty_value():
    assert _agent_session.override_active({}) is False
    assert _agent_session.override_active({_agent_session.OVERRIDE_ENV: ""}) is False
    assert _agent_session.override_active({_agent_session.OVERRIDE_ENV: "   "}) is False
    assert _agent_session.override_active({_agent_session.OVERRIDE_ENV: "1"}) is True


# ---------------------------------------------------------------------------
# The wiring, through the REAL parser dispatch
#
# The gate wraps the handler that `hermes update` dispatches to, NOT the inside
# of cmd_update. Gating inside cmd_update broke 34 existing tests -- they call
# cmd_update(args) directly as a library function while this suite runs inside
# an agent session, so every apply-path test hit the refusal (measured: 7
# failures on main, 41 on the branch). These tests therefore build the real
# parser with a stub handler and invoke `args.func(args)`, which is exactly what
# hermes does, and prove that a direct cmd_update call stays ungated.
# ---------------------------------------------------------------------------

class _ReachedHandler(Exception):
    """The real update handler was reached -- the gate allowed the command."""


def _dispatch(monkeypatch, tmp_path, argv, *, agent_env: bool, agent_cwd: bool,
              override: bool = False):
    """Parse `argv` with the real update parser and call the dispatched func.

    The dispatch wraps the handler in THREE gates -- this one, the divergence
    gate (hermes_cli/_update_divergence) and the shared-stash gate
    (hermes_cli/_update_worktrees), both added later. This suite is about the
    agent gate, so the other two are neutralized here: left live they would
    shell out to real git in the very checkout these tests run from, and --
    because that checkout IS diverged from its origin, AND is a dirty checkout
    with linked worktrees -- would refuse with exit 31 or 32 in precisely the
    cases that assert the agent gate LET THE COMMAND THROUGH. Their own wiring,
    including the order the three run in, is pinned in
    tests/hermes_cli/test_update_divergence_gate.py and
    tests/hermes_cli/test_update_shared_stash_gate.py.
    """
    from hermes_cli import _update_divergence, _update_worktrees

    monkeypatch.setattr(
        _update_divergence, "enforce_divergence_gate", lambda args: None
    )
    monkeypatch.setattr(
        _update_worktrees, "enforce_shared_stash_gate", lambda args: None
    )

    for name in [n for n in os.environ
                 if n in _agent_session._AGENT_ENV_EXACT
                 or n.startswith(_agent_session._AGENT_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(_agent_session.OVERRIDE_ENV, raising=False)
    if agent_env:
        monkeypatch.setenv("CLAUDECODE", "1")
    if override:
        monkeypatch.setenv(_agent_session.OVERRIDE_ENV, "1")

    workdir = tmp_path / ".claude" / "worktrees" / "probe" if agent_cwd else tmp_path / "plain"
    workdir.mkdir(parents=True)
    monkeypatch.chdir(workdir)

    def _handler(args):
        raise _ReachedHandler()

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_update_parser(subparsers, cmd_update=_handler)
    args = parser.parse_args(argv)
    return args.func(args)


def test_agent_session_apply_is_refused(monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        _dispatch(monkeypatch, tmp_path, ["update"], agent_env=True, agent_cwd=True)
    assert excinfo.value.code == _agent_session.EXIT_REFUSED_AGENT_ACTION == 30


def test_env_axis_alone_refuses(monkeypatch, tmp_path):
    """Environment marker, ordinary cwd -- the axes work independently."""
    with pytest.raises(SystemExit) as excinfo:
        _dispatch(monkeypatch, tmp_path, ["update"], agent_env=True, agent_cwd=False)
    assert excinfo.value.code == 30


def test_cwd_axis_alone_refuses(monkeypatch, tmp_path):
    """Agent worktree cwd with the environment scrubbed."""
    with pytest.raises(SystemExit) as excinfo:
        _dispatch(monkeypatch, tmp_path, ["update"], agent_env=False, agent_cwd=True)
    assert excinfo.value.code == 30


def test_check_path_is_never_gated(monkeypatch, tmp_path):
    """--check is read-only and must keep working from an agent session.

    This is the case a careless "refuse the update handler outright" breaks, and
    it is the one that would push sessions toward hand-rolled git instead.
    """
    with pytest.raises(_ReachedHandler):
        _dispatch(monkeypatch, tmp_path, ["update", "--check"], agent_env=True, agent_cwd=True)


def test_override_lets_the_apply_through(monkeypatch, tmp_path):
    with pytest.raises(_ReachedHandler):
        _dispatch(monkeypatch, tmp_path, ["update"], agent_env=True, agent_cwd=True,
                  override=True)


def test_non_agent_apply_is_untouched(monkeypatch, tmp_path):
    with pytest.raises(_ReachedHandler):
        _dispatch(monkeypatch, tmp_path, ["update"], agent_env=False, agent_cwd=False)


def test_branch_flag_reaches_the_refusal(monkeypatch, tmp_path, capsys):
    """The refusal must name the branch that would actually be reset."""
    with pytest.raises(SystemExit):
        _dispatch(monkeypatch, tmp_path, ["update", "--branch", "release-1.2"],
                  agent_env=True, agent_cwd=True)
    assert "reset --hard origin/release-1.2" in capsys.readouterr().out


def test_calling_cmd_update_directly_is_NOT_gated(monkeypatch, tmp_path):
    """The seam that keeps the existing suite green.

    34 tests drive cmd_update(args) directly from inside an agent session. If
    the gate ever migrates back into cmd_update, they all start refusing --
    which is how this gate was first written, and how it was caught.
    """
    for name in ("CLAUDECODE",):
        monkeypatch.setenv(name, "1")
    workdir = tmp_path / ".claude" / "worktrees" / "probe"
    workdir.mkdir(parents=True)
    monkeypatch.chdir(workdir)

    source = inspect.getsource(cli_main.cmd_update)
    assert "_agent_session" not in source, (
        "the gate belongs on the CLI dispatch, not inside cmd_update -- "
        "putting it here refuses every library-level caller, including 34 tests"
    )


# ---------------------------------------------------------------------------
# The refusal text and structure
# ---------------------------------------------------------------------------

def test_refusal_names_the_evidence_route_and_override():
    text = "\n".join(_agent_session.refusal_lines(["synthetic evidence"], branch="main"))
    assert "synthetic evidence" in text
    assert "hermes update --check" in text
    assert _agent_session.OVERRIDE_ENV in text
    assert "reset --hard origin/main" in text
    assert "Nothing has been stashed, pulled, reset or dropped." in text


def test_refusal_warns_that_the_danger_is_not_agent_specific():
    """The gate stops one of two callers. A refusal that let a human read it as
    "the command is now safe" would be worse than no gate at all."""
    text = "\n".join(_agent_session.refusal_lines(["x"]))
    assert "does NOT make the command safe" in text
    assert "not agent-specific" in text


def test_refusal_honours_the_branch():
    text = "\n".join(_agent_session.refusal_lines(["x"], branch="release-1.2"))
    assert "reset --hard origin/release-1.2" in text


def test_gate_runs_before_the_handler_is_called():
    """Source order in the dispatch wrapper.

    Every behavioural test above stays green if the gate merely moves after the
    handler call, at which point it would refuse only once the stash, pull and
    reset had already happened -- making "nothing has been stashed" false.
    """
    source = inspect.getsource(build_update_parser)
    gate_at = source.index("_agent_session.enforce_update_gate(args)")
    call_at = source.index("return cmd_update(args)")
    assert gate_at < call_at, "the gate must run before the handler"


def test_check_returns_before_any_evidence_is_consulted():
    source = inspect.getsource(_agent_session.enforce_update_gate)
    check_at = source.index('getattr(args, "check", False)')
    evidence_at = source.index("agent_session_evidence()")
    assert check_at < evidence_at
