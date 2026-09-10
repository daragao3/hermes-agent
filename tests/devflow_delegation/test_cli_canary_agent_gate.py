"""The AGENT CANARY GATE on ``devflow_delegation.cli``.

NEW FILE on purpose: ``tests/devflow_delegation/test_cli.py`` is edited by
several concurrent sessions, and none of these cases belong to any existing
class there.

WHAT THESE TESTS CAN AND CANNOT SEE. The gate's whole job is to refuse when the
process looks like an agent session -- and this suite RUNS inside one, so the
ambient environment can only ever produce the POSITIVE answer. Every case below
therefore drives ``enforce_canary_agent_gate`` with a synthetic ``environ`` and
``cwd``. That is not a convenience: the negative case (a clean human shell) is
not expressible from here any other way, and a gate whose "allow" branch is
never exercised is a gate that could be refusing everything.

The complement -- that the gate is actually WIRED, and wired at the
typed-command seam rather than somewhere that would break the existing suite --
is checked separately by the ``test_wiring_*`` cases at the bottom, which read
the module source. Behaviour tests alone cannot catch an unwired gate.
"""
import io
import re
from pathlib import Path

import pytest

from devflow_delegation import cli
from hermes_cli._agent_session import EXIT_REFUSED_AGENT_ACTION

# A single agent marker is enough; the detector matches on PRESENCE.
AGENT_ENV = {"CLAUDECODE": "1"}
CLEAN_ENV = {"PATH": "/usr/bin", "HOME": "/home/diego"}
CLEAN_CWD = "/home/diego/devflow-canary/canary-repo"
AGENT_CWD = r"C:\Users\diego\.hermes\agent-src\.claude\worktrees\some-name"

CANARY = ["executor-canary", "--i-understand-this-opens-a-real-pr", "--request-id", "dwr_x"]


def _run(argv, environ, cwd):
    """Drive the gate, returning (raised_exit_code_or_None, printed_text)."""
    lines = []
    try:
        cli.enforce_canary_agent_gate(
            argv, environ=environ, cwd=cwd, printer=lines.append,
        )
    except SystemExit as exc:
        return exc.code, "\n".join(str(x) for x in lines)
    return None, "\n".join(str(x) for x in lines)


# -- refusal ------------------------------------------------------------------

def test_refuses_on_environment_evidence():
    code, out = _run(CANARY, AGENT_ENV, CLEAN_CWD)
    assert code == EXIT_REFUSED_AGENT_ACTION
    assert "REFUSED: 'executor-canary'" in out
    assert "CLAUDECODE" in out


@pytest.mark.parametrize("marker", [
    "CLAUDECODE",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_DISABLE_CRON",
    "CLAUDE_CODE_ENTRYPOINT",
])
def test_refuses_on_presence_not_truthiness(marker):
    # Claude Code exports CLAUDE_CODE_DISABLE_CRON with an EMPTY value, so a
    # truthiness test on the value misses a real agent session entirely. Each
    # marker below is set to "" and must still be evidence on its own.
    code, out = _run(CANARY, {marker: ""}, CLEAN_CWD)
    assert code == EXIT_REFUSED_AGENT_ACTION, marker
    assert marker in out


def test_refuses_on_worktree_cwd_evidence_with_a_clean_environment():
    # The two axes are independent: a session whose environment carries no
    # marker at all is still caught by the worktree path.
    code, out = _run(CANARY, CLEAN_ENV, AGENT_CWD)
    assert code == EXIT_REFUSED_AGENT_ACTION
    assert "working directory is inside an agent worktree" in out


def test_refusal_exit_code_is_the_shared_family_number():
    # One number means one thing across `hermes update`, scripts/release.py,
    # refresh-ci-snapshot.ps1 and this gate. Assert the VALUE too, so renaming
    # the constant in one place cannot silently re-point the family.
    code, _ = _run(CANARY, AGENT_ENV, CLEAN_CWD)
    assert code == EXIT_REFUSED_AGENT_ACTION == 30


def test_refusal_names_the_override_and_the_ungated_alternative():
    _, out = _run(CANARY, AGENT_ENV, CLEAN_CWD)
    assert cli.CANARY_OVERRIDE_ENV in out
    assert "executor-shadow" in out
    # It must say plainly that nothing happened, or the reader will go looking
    # for a half-built worktree to clean up.
    assert "Nothing has been read, leased, built, committed, published or opened." in out


def test_refusal_does_not_claim_to_be_an_authorization_boundary():
    # The override is documented as standing IN FOR a grant, not as routing
    # around one. If this sentence is ever dropped the gate starts reading like
    # a permission system it cannot be.
    _, out = _run(CANARY, AGENT_ENV, CLEAN_CWD)
    assert "the operator standing in for one" in out


# -- allow --------------------------------------------------------------------

def test_allows_a_clean_human_shell():
    # The case that cannot be produced from inside this suite any other way.
    code, out = _run(CANARY, CLEAN_ENV, CLEAN_CWD)
    assert code is None
    assert out == ""


@pytest.mark.parametrize("value", ["1", "yes", " 1 "])
def test_override_allows_it(value):
    env = dict(AGENT_ENV)
    env[cli.CANARY_OVERRIDE_ENV] = value
    code, out = _run(CANARY, env, AGENT_CWD)
    assert code is None
    assert out == ""


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_override_does_not_count(value):
    # An accidentally-exported empty variable must not disarm the gate.
    env = dict(AGENT_ENV)
    env[cli.CANARY_OVERRIDE_ENV] = value
    code, _ = _run(CANARY, env, CLEAN_CWD)
    assert code == EXIT_REFUSED_AGENT_ACTION


def test_the_update_override_does_not_authorize_a_canary():
    # Authorizing a self-update must never also authorize publishing a branch
    # and opening a PR. Distinct variables, deliberately.
    from hermes_cli._agent_session import OVERRIDE_ENV as UPDATE_OVERRIDE

    assert UPDATE_OVERRIDE != cli.CANARY_OVERRIDE_ENV
    env = dict(AGENT_ENV)
    env[UPDATE_OVERRIDE] = "1"
    code, _ = _run(CANARY, env, CLEAN_CWD)
    assert code == EXIT_REFUSED_AGENT_ACTION


# -- scope: only executor-canary ----------------------------------------------

@pytest.mark.parametrize("sub", [
    "executor", "executor-shadow", "status", "delegate", "reconcile",
    "triage", "gate", "transition", "adopt-history",
])
def test_every_other_subcommand_is_untouched(sub):
    # None of these acts outside this machine; gating them would be friction
    # with no safety gain, and executor-shadow in particular is the documented
    # ungated alternative the refusal points at.
    code, out = _run([sub, "--actor", "x"], AGENT_ENV, AGENT_CWD)
    assert code is None
    assert out == ""


def test_no_subcommand_at_all_is_untouched():
    for argv in ([], ["--help"], ["-h"], None):
        code, _ = _run(argv, AGENT_ENV, AGENT_CWD)
        assert code is None, argv


def test_the_gated_name_appearing_as_a_flag_value_is_not_the_subcommand():
    # `executor-shadow --actor executor-canary` must run. The scan takes the
    # FIRST non-option token, which is the subcommand for this parser.
    code, _ = _run(
        ["executor-shadow", "--actor", "executor-canary"], AGENT_ENV, AGENT_CWD,
    )
    assert code is None


def test_subcommand_scan_skips_leading_options():
    assert cli._subcommand_of(["-h", "executor-canary"]) == "executor-canary"
    assert cli._subcommand_of(["executor-canary", "--request-id", "x"]) == "executor-canary"
    assert cli._subcommand_of([]) == ""
    assert cli._subcommand_of(None) == ""


# -- the detector's segment rule, at this gate's own boundary -------------------

@pytest.mark.parametrize("cwd", [
    # ".claude" and "worktrees" must be ADJACENT PATH SEGMENTS, not a substring
    # anywhere in the path. Each of these contains both words and is not a
    # worktree.
    "/home/diego/team.claude/worktrees-archive/repo",
    "/home/diego/notclaude/worktrees/repo",
    "/home/diego/.claudex/worktrees/repo",
    "/home/diego/worktrees/.claude/repo",
])
def test_a_lookalike_path_is_not_worktree_evidence(cwd):
    code, _ = _run(CANARY, CLEAN_ENV, cwd)
    assert code is None, cwd


@pytest.mark.parametrize("cwd", [
    r"C:\Users\diego\.hermes\agent-src\.claude\worktrees\x",
    "/home/diego/.hermes/agent-src/.claude/worktrees/x",
    "/home/diego/repo/.claude/worktrees/x/nested/deeper",
])
def test_a_real_worktree_path_is_evidence_on_both_separators(cwd):
    code, _ = _run(CANARY, CLEAN_ENV, cwd)
    assert code == EXIT_REFUSED_AGENT_ACTION, cwd


# -- wiring (source-level: behaviour tests cannot see an unwired gate) ---------

def _cli_source() -> str:
    return io.open(
        Path(cli.__file__), encoding="utf-8", newline="",
    ).read().replace("\r\n", "\n")


def test_wiring_the_gate_is_called_from_the_main_block_before_main():
    # An unwired gate passes every behaviour test above and refuses nothing.
    src = _cli_source()
    tail = src[src.index('if __name__ == "__main__":'):]
    assert "enforce_canary_agent_gate(sys.argv[1:])" in tail, (
        "the gate is not called from the __main__ block"
    )
    assert tail.index("enforce_canary_agent_gate") < tail.index("SystemExit(main())"), (
        "the gate must run BEFORE main() -- argparse, the executor import and the "
        "ledger open all happen inside main()"
    )


def test_wiring_the_gate_is_not_called_from_main_or_the_canary_command():
    # THE PLACEMENT REGRESSION THIS FILE EXISTS FOR. Moving the gate inside
    # main(), _cmd_executor_canary, run_executor_tick or _stage_commit_push
    # fails ~20 tests in test_executor.py and 2 in test_cli.py, because those
    # drive the canary path programmatically against a real local bare remote
    # while the suite itself runs inside an agent session. Those failures would
    # look like the gate "working", so assert the placement directly.
    src = _cli_source()
    body = src[src.index("def main(argv=None) -> int:"):src.index('if __name__ == "__main__":')]
    assert "enforce_canary_agent_gate" not in body, (
        "the gate must not be called from inside main(); cli.main([...]) is a "
        "programmatic caller and two existing tests use it end-to-end"
    )
    canary_cmd = src[src.index("def _cmd_executor_canary("):src.index("def _cmd_gate(")]
    assert "enforce_canary_agent_gate" not in canary_cmd

    executor_src = io.open(
        Path(cli.__file__).with_name("executor.py"), encoding="utf-8", newline="",
    ).read()
    assert "enforce_canary_agent_gate" not in executor_src
    assert "agent_session_evidence" not in executor_src


def test_wiring_the_detector_is_imported_not_re_implemented():
    # scripts/release.py carries the one deliberate copy (it runs standalone).
    # A third would only be a third thing to drift.
    src = _cli_source()
    assert "from hermes_cli._agent_session import" in src
    assert not re.search(r"^def agent_session_evidence\b", src, re.M)
    assert "CLAUDECODE" not in src, (
        "marker names belong to hermes_cli._agent_session, not here"
    )
