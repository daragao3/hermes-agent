"""Pins the DIVERGENCE GATE: ``hermes update``'s apply path refuses when the
reset it would fall back to would DISCARD local commits.

WHAT IS BEING PROTECTED, AND WHO FROM. ``cmd_update`` runs ``git pull --ff-only
origin <branch>`` and, when that fails, ``git reset --hard origin/<branch>``.
The auto-stash it takes first saves uncommitted CHANGES; it does not save
COMMITS. So on a checkout whose ``origin`` is not the repository the local
history descends from, the fast-forward can never succeed and every local commit
is deleted from the working tree. Measured on this box 2026-09-10 at agent-src
main e916f4d19f: origin is NousResearch/hermes-agent (upstream, not the fork)
and main is 2,493 ahead of it -- so that is 2,493 commits, and ``hermes update
--check`` prints an invitation to run exactly that command. Unlike the agent
gate in ``test_update_agent_session_gate``, this hazard is NOT agent-specific:
it is the operator's working tree too.

THE --check EXEMPTION AND THE FAIL-OPEN ARE HALF THESE TESTS. ``--check`` is
read-only and must never be gated. And when the count cannot be established
(no ``origin/<branch>`` ref, git missing, unborn HEAD) the gate must stand DOWN,
not refuse: if ``origin/<branch>`` does not resolve then ``reset --hard
origin/<branch>`` cannot either, so ``cmd_update`` fails on its own error path
without touching the tree -- while a refusal there would break the ordinary
first-update-after-clone. ``test_unresolvable_origin_ref_stands_down`` is the
case a careless "refuse unless proven safe" implementation breaks.

WHY NO TEST HERE RUNS GIT. Every case drives ``runner``, an injected
``(cmd, cwd) -> (returncode, stdout)``. The suite runs out of a real checkout of
the very repo whose update path is under test, so a test that shelled out to git
could fetch, reset or otherwise mutate it. The wiring cases replace the handler
itself, so nothing past the gate executes in either direction.
"""

from __future__ import annotations

import argparse
import inspect

import pytest

from hermes_cli import _agent_session, _update_divergence
from hermes_cli import update_cmd as cli_main
from hermes_cli.subcommands.update import build_update_parser


class FakeGit:
    """An injected git that answers from configuration and records its calls."""

    def __init__(
        self,
        *,
        origin_ref=True,
        local_branch=True,
        head=True,
        count="3",
        rev_list_code=0,
        fetch_code=0,
    ):
        self.origin_ref = origin_ref
        self.local_branch = local_branch
        self.head = head
        self.count = count
        self.rev_list_code = rev_list_code
        self.fetch_code = fetch_code
        self.calls = []

    def __call__(self, cmd, cwd):
        self.calls.append(list(cmd))
        if "fetch" in cmd:
            return self.fetch_code, ""
        if "rev-parse" in cmd:
            target = cmd[-1]
            if target.startswith("refs/remotes/origin/"):
                return (0 if self.origin_ref else 1), ""
            if target.startswith("refs/heads/"):
                return (0 if self.local_branch else 1), ""
            if target == "HEAD":
                return (0 if self.head else 1), ""
            return 1, ""
        if "rev-list" in cmd:
            return self.rev_list_code, self.count
        return 1, ""

    @property
    def rev_list_range(self):
        for cmd in self.calls:
            if "rev-list" in cmd:
                return cmd[-1]
        return None

    @property
    def fetched(self):
        return any("fetch" in cmd for cmd in self.calls)


def args_for(**kwargs):
    return argparse.Namespace(**{"check": False, "branch": None, **kwargs})


# ---------------------------------------------------------------------------
# Branch resolution -- must agree with main._resolve_update_branch
# ---------------------------------------------------------------------------

def test_branch_defaults_to_main():
    assert _update_divergence.resolve_branch(args_for()) == "main"


def test_branch_honors_the_flag():
    assert _update_divergence.resolve_branch(args_for(branch="dev")) == "dev"


def test_whitespace_only_branch_is_the_default():
    assert _update_divergence.resolve_branch(args_for(branch="   ")) == "main"


def test_missing_branch_attribute_is_the_default():
    assert _update_divergence.resolve_branch(argparse.Namespace()) == "main"


def test_resolve_branch_matches_main_s_resolver():
    """Pins the duplication. The seam cannot import main, so the two are kept
    in step by this test rather than by a shared call."""
    for value in (None, "", "   ", "dev", " dev "):
        ns = args_for(branch=value)
        from hermes_cli.main_install_repair import _resolve_update_branch
        assert _update_divergence.resolve_branch(ns) == _resolve_update_branch(ns)


# ---------------------------------------------------------------------------
# Counting what would be discarded
# ---------------------------------------------------------------------------

def test_counts_local_commits_not_on_origin():
    git = FakeGit(count="2493\n")
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) == 2493


def test_zero_when_history_is_contained_in_origin():
    git = FakeGit(count="0\n")
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) == 0


def test_counts_against_the_local_branch_when_it_exists():
    """cmd_update switches to <branch> before resetting, so the local branch --
    not the currently checked-out HEAD -- is what would be discarded."""
    git = FakeGit(local_branch=True)
    _update_divergence.commits_that_would_be_discarded("main", runner=git)
    assert git.rev_list_range == "refs/remotes/origin/main..refs/heads/main"


def test_falls_back_to_head_when_the_local_branch_is_absent():
    git = FakeGit(local_branch=False, head=True)
    _update_divergence.commits_that_would_be_discarded("main", runner=git)
    assert git.rev_list_range == "refs/remotes/origin/main..HEAD"


def test_unresolvable_origin_ref_is_undetermined():
    git = FakeGit(origin_ref=False)
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) is None


def test_unborn_head_is_undetermined():
    git = FakeGit(local_branch=False, head=False)
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) is None


def test_failed_rev_list_is_undetermined():
    git = FakeGit(rev_list_code=1)
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) is None


def test_non_numeric_count_is_undetermined():
    git = FakeGit(count="not-a-number")
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) is None


def test_it_fetches_before_counting():
    """Without this the remote-tracking ref can be stale and the refusal would
    report the wrong number."""
    git = FakeGit()
    _update_divergence.commits_that_would_be_discarded("main", runner=git)
    assert git.fetched


def test_fetch_can_be_suppressed():
    git = FakeGit()
    _update_divergence.commits_that_would_be_discarded("main", runner=git, fetch=False)
    assert not git.fetched


def test_offline_fetch_failure_still_evaluates():
    """A stale ref cannot turn a real divergence into a 0, so an offline box
    still gets a (conservative) answer rather than a stand-down."""
    git = FakeGit(fetch_code=1, count="7")
    assert _update_divergence.commits_that_would_be_discarded("main", runner=git) == 7


def test_the_branch_is_threaded_into_every_ref():
    git = FakeGit()
    _update_divergence.commits_that_would_be_discarded("dev", runner=git)
    assert git.rev_list_range == "refs/remotes/origin/dev..refs/heads/dev"


# ---------------------------------------------------------------------------
# The override
# ---------------------------------------------------------------------------

def test_override_unset_is_inactive():
    assert not _update_divergence.override_active({})


def test_override_empty_is_inactive():
    assert not _update_divergence.override_active({"HERMES_ALLOW_DIVERGENT_UPDATE": ""})


def test_override_whitespace_is_inactive():
    assert not _update_divergence.override_active({"HERMES_ALLOW_DIVERGENT_UPDATE": "  "})


def test_override_set_is_active():
    assert _update_divergence.override_active({"HERMES_ALLOW_DIVERGENT_UPDATE": "1"})


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_refuses_when_commits_would_be_discarded():
    git = FakeGit(count="2493")
    with pytest.raises(SystemExit) as excinfo:
        _update_divergence.enforce_divergence_gate(
            args_for(), runner=git, environ={}, printer=lambda *_: None
        )
    assert excinfo.value.code == _update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE


def test_the_refusal_exit_code_is_31_and_not_the_agent_gate_s_30():
    assert _update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE == 31
    assert (
        _update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE
        != _agent_session.EXIT_REFUSED_AGENT_ACTION
    )


def test_proceeds_when_nothing_would_be_discarded():
    git = FakeGit(count="0")
    _update_divergence.enforce_divergence_gate(args_for(), runner=git, environ={})


def test_stands_down_when_undetermined():
    """FAIL OPEN. An unresolvable origin/<branch> means reset --hard cannot
    resolve it either, so cmd_update fails harmlessly on its own path."""
    git = FakeGit(origin_ref=False)
    _update_divergence.enforce_divergence_gate(args_for(), runner=git, environ={})


def test_check_is_never_gated_even_when_diverged():
    git = FakeGit(count="2493")
    _update_divergence.enforce_divergence_gate(
        args_for(check=True), runner=git, environ={}
    )
    assert not git.calls, "--check must not even ask git"


def test_override_bypasses_the_refusal():
    git = FakeGit(count="2493")
    _update_divergence.enforce_divergence_gate(
        args_for(), runner=git, environ={"HERMES_ALLOW_DIVERGENT_UPDATE": "1"}
    )


def test_refusal_names_the_count_and_the_branch():
    text = "\n".join(_update_divergence.refusal_lines("main", 2493))
    assert "2493" in text
    assert "origin/main" in text
    assert "reset --hard origin/main" in text


def test_refusal_honors_a_non_default_branch():
    text = "\n".join(_update_divergence.refusal_lines("dev", 4))
    assert "reset --hard origin/dev" in text
    assert "origin/main" not in text


def test_refusal_says_commits_are_not_protected_by_the_stash():
    text = "\n".join(_update_divergence.refusal_lines("main", 2))
    assert "not protect" in text.lower() or "does NOT protect" in text


def test_refusal_is_singular_for_one_commit():
    text = "\n".join(_update_divergence.refusal_lines("main", 1))
    assert "1 local commit on" in text


def test_refusal_offers_the_override():
    text = "\n".join(_update_divergence.refusal_lines("main", 3))
    assert _update_divergence.OVERRIDE_ENV in text


def test_refusal_points_at_the_remote_topology():
    """The usual cause on a fork is origin pointing at upstream; the refusal has
    to say so or the reader fixes the symptom."""
    text = "\n".join(_update_divergence.refusal_lines("main", 3))
    assert "remote -v" in text


# ---------------------------------------------------------------------------
# Wiring -- the real parser, with nothing past the gate able to run
# ---------------------------------------------------------------------------

class _ReachedPastGate(Exception):
    pass


def build_real_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    def handler(args):
        raise _ReachedPastGate()

    build_update_parser(subparsers, cmd_update=handler)
    return parser


def test_the_gate_is_wired_into_the_real_dispatch(monkeypatch):
    monkeypatch.setattr(_agent_session, "enforce_update_gate", lambda args: None)
    monkeypatch.setattr(
        _update_divergence,
        "commits_that_would_be_discarded",
        lambda branch, **kw: 2493,
    )
    monkeypatch.delenv("HERMES_ALLOW_DIVERGENT_UPDATE", raising=False)

    args = build_real_parser().parse_args(["update"])
    with pytest.raises(SystemExit) as excinfo:
        args.func(args)
    assert excinfo.value.code == _update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE


def test_the_handler_runs_when_the_gate_passes(monkeypatch):
    """The shared-stash gate (added after this one) is neutralized for the same
    reason this suite neutralizes the agent gate: left live it shells out to real
    git in the very checkout these tests run from, which is dirty and has 17
    linked worktrees, so it would refuse with exit 32 in exactly the case that
    asserts the DIVERGENCE gate let the command through. Its own wiring and
    ordering are pinned in tests/hermes_cli/test_update_shared_stash_gate.py."""
    from hermes_cli import _update_worktrees

    monkeypatch.setattr(_agent_session, "enforce_update_gate", lambda args: None)
    monkeypatch.setattr(
        _update_divergence, "commits_that_would_be_discarded", lambda branch, **kw: 0
    )
    monkeypatch.setattr(
        _update_worktrees, "enforce_shared_stash_gate", lambda args: None
    )
    args = build_real_parser().parse_args(["update"])
    with pytest.raises(_ReachedPastGate):
        args.func(args)


def test_check_reaches_the_handler_through_both_gates(monkeypatch):
    monkeypatch.setattr(_agent_session, "enforce_update_gate", lambda args: None)
    args = build_real_parser().parse_args(["update", "--check"])
    with pytest.raises(_ReachedPastGate):
        args.func(args)


def test_the_agent_gate_runs_before_the_divergence_gate(monkeypatch):
    """Ordering matters: the agent gate is a cheap env read, the divergence gate
    shells out to git and fetches."""
    from hermes_cli import _update_worktrees

    order = []
    monkeypatch.setattr(
        _agent_session, "enforce_update_gate", lambda args: order.append("agent")
    )
    monkeypatch.setattr(
        _update_divergence,
        "enforce_divergence_gate",
        lambda args: order.append("divergence"),
    )
    # The third gate would otherwise run for real against this checkout, which
    # is dirty and has linked worktrees -- see the note in
    # test_the_handler_runs_when_the_gate_passes.
    monkeypatch.setattr(
        _update_worktrees, "enforce_shared_stash_gate", lambda args: None
    )
    args = build_real_parser().parse_args(["update"])
    with pytest.raises(_ReachedPastGate):
        args.func(args)
    assert order == ["agent", "divergence"]


def test_cmd_update_itself_carries_no_divergence_gate():
    """Pins the seam. Gating inside cmd_update broke 34 existing tests when the
    agent gate was first written -- the suite calls it directly as a library
    function. This must stay a dispatch-level wrap."""
    from hermes_cli.main import cmd_update
    source = inspect.getsource(cmd_update)
    assert "_update_divergence" not in source
    assert "enforce_divergence_gate" not in source


def test_main_py_carries_no_gate_and_only_the_check_advisory_call():
    """hermes_cli/main.py is the worst-conflicted file in the pending 0.21.1
    upgrade merge, so this feature is bounded there rather than forbidden.

    THE GATE still adds ZERO surface -- it lives entirely at the dispatch seam.
    What main.py gained afterwards is the ``--check`` ADVISORY, and only because
    ``_cmd_update_check`` lives here and cannot be moved without touching far
    more of this file. The bound: ONE import, inside ONE small helper, and no
    gate symbol anywhere. If a future change starts spelling the policy out in
    main.py, this goes red.
    """
    source = inspect.getsource(cli_main)
    assert "enforce_divergence_gate" not in source, "the GATE must stay at the seam"
    assert source.count("from hermes_cli._update_divergence import") == 1

    helper = inspect.getsource(cli_main._print_update_check_tail)
    assert "from hermes_cli._update_divergence import" in helper
    assert len(helper.splitlines()) <= 25, "the helper must stay a call, not a policy"


# ---------------------------------------------------------------------------
# --check's ADVISORY. Residual (1) of the gate work: --check is read-only and
# ungated (correctly), but it ended with "Run 'hermes update' to install" while
# that command refuses with exit 31 -- a dead end with no stated reason. This
# changes WHAT IS PRINTED and nothing else. --check stays read-only, still
# exits 0, and is still the only half of `hermes update` a diverged checkout
# can safely run; turning the report into a refusal would take that away too.
# ---------------------------------------------------------------------------

INVITATION = "  Run 'hermes update' to install."


def test_advisory_is_the_plain_invitation_when_not_diverged():
    git = FakeGit(count="0")
    lines = _update_divergence.check_advisory_lines(
        "main",
        compare_ref="upstream/main",
        runner=git,
        environ={},
        update_command="hermes update",
    )
    assert lines == [INVITATION]


def test_advisory_replaces_the_invitation_when_the_apply_path_would_refuse():
    git = FakeGit(count="2496")
    lines = _update_divergence.check_advisory_lines(
        "main", compare_ref="upstream/main", runner=git, environ={}
    )
    text = "\n".join(lines)
    assert "2496" in text
    assert "REFUSE" in text
    assert str(_update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE) in text
    assert "reset --hard origin/main" in text
    assert INVITATION not in lines, "must not still invite a command that refuses"


def test_advisory_stands_down_when_the_count_cannot_be_established():
    """Same fail-open as the gate. No origin/<branch> ref means the apply path
    would not reset either, so the ordinary invitation is the truthful answer."""
    git = FakeGit(origin_ref=False)
    lines = _update_divergence.check_advisory_lines(
        "main", runner=git, environ={}, update_command="hermes update"
    )
    assert lines == [INVITATION]


def test_advisory_honors_the_override_without_asking_git():
    """With the override set the apply path really will proceed, so inviting it
    is the truthful answer -- and there is nothing to count."""
    git = FakeGit(count="2496")
    lines = _update_divergence.check_advisory_lines(
        "main",
        runner=git,
        environ={"HERMES_ALLOW_DIVERGENT_UPDATE": "1"},
        update_command="hermes update",
    )
    assert lines == [INVITATION]
    assert not git.calls


def test_advisory_does_not_fetch():
    """--check has already fetched by the time this runs. A second network
    round-trip to say something advisory is not worth it, and the staleness it
    buys is one-directional: a stale origin ref is OLDER, so it can only make
    the count too HIGH, never turn a real divergence into a 0 and print the
    invitation this exists to withhold."""
    git = FakeGit(count="2496")
    _update_divergence.check_advisory_lines("main", runner=git, environ={})
    assert not git.fetched


def test_advisory_names_both_refs_when_they_differ():
    """--check counts behind upstream/<branch> on a fork; the apply path resets
    onto origin/<branch>. Two different true numbers read as a contradiction
    unless both refs are named."""
    text = "\n".join(
        _update_divergence.advisory_lines("main", 2496, compare_ref="upstream/main")
    )
    assert "upstream/main" in text
    assert "origin/main" in text


def test_advisory_omits_the_ref_note_when_the_refs_agree():
    text = "\n".join(
        _update_divergence.advisory_lines("main", 2496, compare_ref="origin/main")
    )
    assert "upstream" not in text
    assert "the count above is against" not in text


def test_advisory_honors_a_non_default_branch():
    text = "\n".join(
        _update_divergence.advisory_lines("dev", 4, compare_ref="origin/dev")
    )
    assert "reset --hard origin/dev" in text
    assert "origin/main" not in text


def test_advisory_reads_as_english_for_a_single_commit():
    text = "\n".join(
        _update_divergence.advisory_lines("dev", 1, compare_ref="origin/dev")
    )
    assert "1 local commit on 'dev' is" in text
    assert "commits on" not in text


def test_advisory_names_the_override():
    text = "\n".join(
        _update_divergence.advisory_lines("main", 2, compare_ref="origin/main")
    )
    assert _update_divergence.OVERRIDE_ENV in text


def test_advisory_says_the_stash_does_not_protect_commits():
    text = "\n".join(
        _update_divergence.advisory_lines("main", 2, compare_ref="origin/main")
    )
    assert "not commits" in text


def test_the_advisory_never_exits():
    """THE WHOLE POINT, and the constraint a careless "make --check honest"
    breaks: this REPORTS, it does not gate. --check must keep exiting 0 on a
    diverged checkout."""
    assert "sys.exit" not in inspect.getsource(
        _update_divergence.check_advisory_lines
    )
    assert "sys.exit" not in inspect.getsource(_update_divergence.advisory_lines)
    assert "sys.exit" not in inspect.getsource(cli_main._print_update_check_tail)


@pytest.mark.parametrize("behind", [0, 2, None])
def test_update_report_preserves_advisory_for_each_verdict(monkeypatch, behind):
    calls = []
    monkeypatch.setattr(cli_main, "_print_update_check_tail",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    cli_main._print_update_check_result(behind, "upstream/dev", branch="dev")
    assert calls == [(('dev', 'upstream/dev'), {'update_available': False} if behind == 0 else {})]


def test_the_helper_prints_exactly_what_the_advisory_returns(monkeypatch):
    printed = []
    monkeypatch.setattr(
        _update_divergence, "check_advisory_lines", lambda *a, **kw: ["A", "B"]
    )
    monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(a[0]))
    cli_main._print_update_check_tail("main", "upstream/main")
    assert printed == ["A", "B"]


def test_the_helper_passes_the_branch_and_the_compare_ref(monkeypatch):
    seen = {}

    def fake(branch, *, compare_ref=None, **kw):
        seen["branch"] = branch
        seen["compare_ref"] = compare_ref
        return []

    monkeypatch.setattr(_update_divergence, "check_advisory_lines", fake)
    cli_main._print_update_check_tail("dev", "origin/dev")
    assert seen == {"branch": "dev", "compare_ref": "origin/dev"}
# ---------------------------------------------------------------------------
# AHEAD BUT NOT BEHIND. The gate counts commits AHEAD of origin; --check's
# headline counts commits BEHIND it. Those are different questions, so a green
# "Already up to date." can sit directly above a `hermes update` that refuses
# with exit 31. Found 2026-09-10 while building a control for the advisory
# above: the first control was 1-ahead/0-behind, never reached the advisory,
# and read at a glance like the fix failing.
# ---------------------------------------------------------------------------


def test_up_to_date_says_nothing_when_the_apply_path_would_proceed():
    git = FakeGit(count="0")
    assert (
        _update_divergence.check_advisory_lines(
            "main", compare_ref="origin/main", update_available=False,
            runner=git, environ={},
        )
        == []
    )


def test_up_to_date_warns_when_the_apply_path_would_still_refuse():
    git = FakeGit(count="1")
    lines = _update_divergence.check_advisory_lines(
        "main", compare_ref="origin/main", update_available=False,
        runner=git, environ={},
    )
    text = "\n".join(lines)
    assert lines, "ahead-but-not-behind must not be silent"
    assert "refuse" in text.lower()
    assert str(_update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE) in text
    assert "origin/main" in text
    # ROUTING, not just content. Without these two the entry point could hand
    # back the SHOUTY refusal advisory here and no test would notice -- the
    # gentleness is pinned only against up_to_date_advisory_lines directly,
    # which a wrong route never reaches. (Mutation survivor, closed 2026-09-10.)
    assert "REFUSE" not in text, "must route to the gentle note, not the refusal"
    assert "reset --hard" not in text, "nothing can be reset with nothing to pull"


def test_up_to_date_never_prints_the_invitation():
    """There is no update to install, so inviting the command would be false
    twice over -- and it is the invitation this whole change removes."""
    git = FakeGit(count="7")
    lines = _update_divergence.check_advisory_lines(
        "main", update_available=False, runner=git, environ={}
    )
    assert INVITATION not in lines
    assert "Run '" not in "\n".join(lines), "no invitation, in any wording"


def test_up_to_date_stands_down_when_the_count_is_unknown():
    git = FakeGit(origin_ref=False)
    assert (
        _update_divergence.check_advisory_lines(
            "main", update_available=False, runner=git, environ={}
        )
        == []
    )


def test_up_to_date_honors_the_override():
    git = FakeGit(count="7")
    assert (
        _update_divergence.check_advisory_lines(
            "main", update_available=False, runner=git,
            environ={"HERMES_ALLOW_DIVERGENT_UPDATE": "1"},
        )
        == []
    )


def test_up_to_date_note_is_gentler_than_the_refusal_advisory():
    """Nothing is at risk in this state -- there is no update to pull, so
    nothing gets reset. Shouting here trains the reader to skip the loud
    version, which is the one that matters."""
    text = "\n".join(
        _update_divergence.up_to_date_advisory_lines("main", 3, compare_ref="origin/main")
    )
    assert "REFUSE" not in text, "reserve the shouty form for the real hazard"
    assert "reset --hard" not in text, "no reset can happen with nothing to pull"
    assert "nothing is at risk" in text.lower()


def test_up_to_date_note_names_both_refs_when_they_differ():
    text = "\n".join(
        _update_divergence.up_to_date_advisory_lines(
            "main", 3, compare_ref="upstream/main"
        )
    )
    assert "upstream/main" in text
    assert "origin/main" in text


def test_up_to_date_note_omits_the_ref_note_when_the_refs_agree():
    text = "\n".join(
        _update_divergence.up_to_date_advisory_lines("main", 3, compare_ref="origin/main")
    )
    assert "the headline above is against" not in text


def test_up_to_date_note_honors_a_non_default_branch():
    text = "\n".join(
        _update_divergence.up_to_date_advisory_lines("dev", 3, compare_ref="origin/dev")
    )
    assert "origin/dev..dev" in text
    assert "origin/main" not in text


def test_up_to_date_note_reads_as_english_for_a_single_commit():
    text = "\n".join(
        _update_divergence.up_to_date_advisory_lines("dev", 1, compare_ref="origin/dev")
    )
    assert "1 local commit on 'dev' is not" in text
    assert "protect it" in text
    assert "See it:" in text


def test_up_to_date_note_never_exits():
    assert "sys.exit" not in inspect.getsource(
        _update_divergence.up_to_date_advisory_lines
    )


def test_the_helper_passes_update_available_through(monkeypatch):
    seen = {}

    def fake(branch, *, compare_ref=None, update_available=True, **kw):
        seen["update_available"] = update_available
        return []

    monkeypatch.setattr(_update_divergence, "check_advisory_lines", fake)
    cli_main._print_update_check_tail("main", "origin/main", update_available=False)
    assert seen == {"update_available": False}
    cli_main._print_update_check_tail("main", "origin/main")
    assert seen == {"update_available": True}, "must default to the invitation arm"
