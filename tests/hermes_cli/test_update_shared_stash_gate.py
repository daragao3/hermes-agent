"""Pins the SHARED-STASH GATE: ``hermes update``'s apply path refuses when its
autostash would land on a stash stack shared with linked worktrees.

WHAT IS BEING PROTECTED. ``_stash_local_changes_if_needed`` pushes a uniquely
named autostash and then reads ``git rev-parse --verify refs/stash`` back as the
ref it will later apply and drop. ``refs/stash`` is the stack TIP, not "the entry
I just wrote", and the stash stack lives in the COMMON git dir -- shared by every
linked worktree rather than per-worktree like HEAD and the index. A concurrent
``git stash push`` from any other worktree, landing in that window, therefore
hands the update a SIBLING's sha. It then applies that sibling's working tree
into this checkout, resolves it to the sibling's ``stash@{n}``, drops it, and
leaves the operator's own autostash on the stack unrestored -- every command at
exit 0, with nothing to notice.

MEASURED 2026-09-10 in a throwaway two-worktree repo (git 2.55.0.windows.5): one
sibling push moved ``refs/stash`` off the autostash entry, and ``git stash apply
<captured ref>`` wrote the sibling's content into the main checkout, exit 0.
``~/.hermes/agent-src`` has 17 linked worktrees.

THE TWO-HALF SCOPE IS MOST OF THIS SUITE. The gate fires only on DIRTY *AND*
SHARED. A clean tree never stashes, so it is never at risk, and refusing there
would break the ordinary update for anyone who happens to keep a worktree.
``package-lock.json`` churn is discounted because ``_discard_lockfile_churn``
restores it before the stash logic runs -- counting it would refuse on a tree
the product itself treats as clean. ``test_lockfile_churn_alone_does_not_arm``
is the case a naive "status is non-empty" implementation breaks.

AND THE FAIL-OPEN. When either half cannot be established the gate stands DOWN.
A guard that cannot read the repo must not be why a single-worktree user cannot
update, and the hazard needs a linked worktree to exist at all.

WHY NO TEST HERE RUNS GIT. Every case drives ``runner``, an injected
``(cmd, cwd) -> (returncode, stdout)``. This suite runs out of a real checkout of
the very repo whose update path is under test -- and that checkout is dirty and
has 17 worktrees, so a test that shelled out to git would both mutate it and
answer from the machine rather than from the case. The wiring cases replace the
handler itself, so nothing past the gate executes in either direction.
"""

from __future__ import annotations

import argparse
import inspect

import pytest

from hermes_cli import _agent_session, _update_divergence, _update_worktrees
from hermes_cli import main as cli_main
from hermes_cli.subcommands.update import build_update_parser


class FakeGit:
    """An injected git that answers from configuration and records its calls."""

    def __init__(self, *, worktrees=2, status="", status_code=0, worktree_code=0):
        self.worktrees = worktrees
        self.status = status
        self.status_code = status_code
        self.worktree_code = worktree_code
        self.calls = []

    def __call__(self, cmd, cwd):
        self.calls.append(list(cmd))
        if "worktree" in cmd:
            if self.worktree_code != 0:
                return self.worktree_code, ""
            body = "".join(
                f"worktree /path/{i}\nHEAD 0000\nbranch refs/heads/b{i}\n\n"
                for i in range(self.worktrees)
            )
            return 0, body
        if "status" in cmd:
            return self.status_code, self.status
        return 1, ""

    @property
    def asked_status(self):
        return any("status" in cmd for cmd in self.calls)


def args_for(**kwargs):
    return argparse.Namespace(**{"check": False, "branch": None, **kwargs})


DIRTY = " M hermes_cli/main.py\n"


# ---------------------------------------------------------------------------
# Counting the worktrees that share the stack
# ---------------------------------------------------------------------------

def test_a_plain_clone_shares_with_nobody():
    git = FakeGit(worktrees=1)
    assert _update_worktrees.linked_worktree_count(runner=git) == 0


def test_linked_worktrees_are_counted_without_the_main_checkout():
    git = FakeGit(worktrees=18)
    assert _update_worktrees.linked_worktree_count(runner=git) == 17


def test_worktree_count_is_unknown_when_git_fails():
    git = FakeGit(worktree_code=128)
    assert _update_worktrees.linked_worktree_count(runner=git) is None


def test_worktree_count_is_unknown_when_output_has_no_entries():
    """Not zero. Empty output means the question went unanswered -- git always
    lists at least the main checkout -- and zero would read as 'safe'."""
    git = FakeGit(worktrees=0)
    assert _update_worktrees.linked_worktree_count(runner=git) is None


# ---------------------------------------------------------------------------
# Would the apply path actually stash?
# ---------------------------------------------------------------------------

def test_clean_tree_would_not_stash():
    assert _update_worktrees.would_autostash(runner=FakeGit(status="")) is False


def test_dirty_tree_would_stash():
    assert _update_worktrees.would_autostash(runner=FakeGit(status=DIRTY)) is True


def test_untracked_files_would_stash():
    """The autostash is --include-untracked, so untracked files are at risk too."""
    git = FakeGit(status="?? notes.md\n")
    assert _update_worktrees.would_autostash(runner=git) is True


def test_staged_changes_would_stash():
    git = FakeGit(status="M  hermes_cli/main.py\n")
    assert _update_worktrees.would_autostash(runner=git) is True


def test_status_failure_is_unknown_not_clean():
    git = FakeGit(status_code=128)
    assert _update_worktrees.would_autostash(runner=git) is None


def test_lockfile_churn_alone_does_not_arm():
    """_discard_lockfile_churn restores these before the stash logic runs, so the
    tree the update sees is clean. Counting them would refuse every update on a
    box that has ever run npm."""
    git = FakeGit(status=" M package-lock.json\n M ui/package-lock.json\n")
    assert _update_worktrees.would_autostash(runner=git) is False


def test_lockfile_churn_beside_a_dirty_package_json_does_arm():
    """That pair is a real dependency edit -- the helper deliberately leaves it
    alone, so it really will be stashed."""
    git = FakeGit(status=" M ui/package.json\n M ui/package-lock.json\n")
    assert _update_worktrees.would_autostash(runner=git) is True


def test_staged_lockfile_is_not_treated_as_churn():
    """The helper only restores UNSTAGED tracked diffs, so a staged lockfile
    survives to be stashed."""
    git = FakeGit(status="M  package-lock.json\n")
    assert _update_worktrees.would_autostash(runner=git) is True


def test_lockfile_churn_plus_a_real_edit_arms():
    git = FakeGit(status=" M package-lock.json\n M hermes_cli/main.py\n")
    assert _update_worktrees.would_autostash(runner=git) is True


def test_renamed_path_is_read_from_the_destination():
    git = FakeGit(status="R  old.py -> new.py\n")
    assert _update_worktrees.would_autostash(runner=git) is True


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------

def _enforce(git, *, environ=None, **kwargs):
    _update_worktrees.enforce_shared_stash_gate(
        args_for(**kwargs),
        printer=lambda *a: None,
        runner=git,
        environ={} if environ is None else environ,
    )


def test_refuses_when_dirty_and_shared():
    git = FakeGit(worktrees=18, status=DIRTY)
    with pytest.raises(SystemExit) as excinfo:
        _enforce(git)
    assert excinfo.value.code == _update_worktrees.EXIT_REFUSED_SHARED_STASH


def test_proceeds_on_a_clean_tree_even_with_worktrees():
    _enforce(FakeGit(worktrees=18, status=""))


def test_proceeds_when_dirty_but_unshared():
    _enforce(FakeGit(worktrees=1, status=DIRTY))


def test_proceeds_when_the_worktree_count_is_unknown():
    _enforce(FakeGit(worktree_code=128, status=DIRTY))


def test_proceeds_when_the_status_is_unknown():
    _enforce(FakeGit(worktrees=18, status_code=128))


def test_check_is_never_gated():
    """--check is read-only and never stashes. It must reach the handler even on
    the dirtiest shared checkout there is."""
    _enforce(FakeGit(worktrees=18, status=DIRTY), check=True)


def test_check_does_not_even_ask_git():
    git = FakeGit(worktrees=18, status=DIRTY)
    _enforce(git, check=True)
    assert git.calls == []


def test_the_override_lets_it_through():
    git = FakeGit(worktrees=18, status=DIRTY)
    _enforce(git, environ={_update_worktrees.OVERRIDE_ENV: "1"})


def test_the_override_does_not_ask_git():
    git = FakeGit(worktrees=18, status=DIRTY)
    _enforce(git, environ={_update_worktrees.OVERRIDE_ENV: "1"})
    assert git.calls == []


def test_a_whitespace_override_is_not_an_override():
    git = FakeGit(worktrees=18, status=DIRTY)
    with pytest.raises(SystemExit):
        _enforce(git, environ={_update_worktrees.OVERRIDE_ENV: "   "})


def test_the_clean_tree_check_is_skipped_when_nothing_is_shared():
    """Ordering: the worktree count is the cheaper question and the one that
    makes the hazard possible at all, so a plain clone never pays for a status."""
    git = FakeGit(worktrees=1, status=DIRTY)
    _enforce(git)
    assert not git.asked_status


# ---------------------------------------------------------------------------
# What the refusal says
# ---------------------------------------------------------------------------

def test_refusal_states_that_nothing_was_touched():
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert "Nothing has been fetched, stashed, pulled, reset or dropped" in text


def test_refusal_names_the_override():
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert _update_worktrees.OVERRIDE_ENV in text


def test_refusal_explains_that_refs_stash_is_the_tip():
    """The whole defect in one sentence. Without it the reader has no way to tell
    this from 'you have uncommitted changes', which git says harmlessly all day."""
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert "refs/stash is the TIP" in text


def test_refusal_says_the_failure_is_silent():
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert "exit 0" in text


def test_refusal_counts_the_worktrees():
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert "17 linked worktrees" in text


def test_refusal_reads_as_english_for_a_single_worktree():
    text = "\n".join(_update_worktrees.refusal_lines(1))
    assert "1 linked worktree" in text
    assert "shares its stash stack" in text
    assert "worktrees" not in text.split("DO THIS INSTEAD")[0]


def test_refusal_offers_committing_as_the_way_out():
    """The recommendation has to be a way to make the tree CLEAN, because that is
    the condition the gate actually tests."""
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert "commit" in text.lower()


def test_refusal_teaches_apply_by_sha_not_by_selector():
    """If the operator stashes by hand instead, they walk into the same shared
    stack -- so the manual route has to carry the safe recovery idiom."""
    text = "\n".join(_update_worktrees.refusal_lines(17))
    assert "git stash apply <sha>" in text
    assert "stash@{0}" in text


def test_refusal_names_the_checkout():
    text = "\n".join(_update_worktrees.refusal_lines(17, project_root="/repo"))
    assert "/repo" in text


# ---------------------------------------------------------------------------
# Exit codes are distinguishable
# ---------------------------------------------------------------------------

def test_all_three_gate_exit_codes_are_distinct():
    """A caller reading the exit code must be able to tell WHICH gate refused."""
    codes = {
        _agent_session.EXIT_REFUSED_AGENT_ACTION,
        _update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE,
        _update_worktrees.EXIT_REFUSED_SHARED_STASH,
    }
    assert len(codes) == 3


def test_the_three_gates_use_distinct_overrides():
    overrides = {
        _update_divergence.OVERRIDE_ENV,
        _update_worktrees.OVERRIDE_ENV,
    }
    assert len(overrides) == 2


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


def _stub_earlier_gates(monkeypatch):
    monkeypatch.setattr(_agent_session, "enforce_update_gate", lambda args: None)
    monkeypatch.setattr(
        _update_divergence, "enforce_divergence_gate", lambda args: None
    )


def test_the_gate_is_wired_into_the_real_dispatch(monkeypatch):
    _stub_earlier_gates(monkeypatch)
    monkeypatch.setattr(_update_worktrees, "linked_worktree_count", lambda **kw: 17)
    monkeypatch.setattr(_update_worktrees, "would_autostash", lambda **kw: True)
    monkeypatch.delenv(_update_worktrees.OVERRIDE_ENV, raising=False)

    args = build_real_parser().parse_args(["update"])
    with pytest.raises(SystemExit) as excinfo:
        args.func(args)
    assert excinfo.value.code == _update_worktrees.EXIT_REFUSED_SHARED_STASH


def test_the_handler_runs_when_the_gate_passes(monkeypatch):
    _stub_earlier_gates(monkeypatch)
    monkeypatch.setattr(_update_worktrees, "linked_worktree_count", lambda **kw: 0)
    args = build_real_parser().parse_args(["update"])
    with pytest.raises(_ReachedPastGate):
        args.func(args)


def test_check_reaches_the_handler_through_all_three_gates(monkeypatch):
    _stub_earlier_gates(monkeypatch)
    monkeypatch.setattr(_update_worktrees, "linked_worktree_count", lambda **kw: 17)
    monkeypatch.setattr(_update_worktrees, "would_autostash", lambda **kw: True)
    args = build_real_parser().parse_args(["update", "--check"])
    with pytest.raises(_ReachedPastGate):
        args.func(args)


def test_the_shared_stash_gate_runs_last(monkeypatch):
    """Ordering is deliberate: the two earlier gates guard COMMIT loss and agent
    misuse; this one guards uncommitted changes and is the least severe. It also
    means a diverged checkout reports the divergence first, which is the bigger
    problem."""
    order = []
    monkeypatch.setattr(
        _agent_session, "enforce_update_gate", lambda args: order.append("agent")
    )
    monkeypatch.setattr(
        _update_divergence,
        "enforce_divergence_gate",
        lambda args: order.append("divergence"),
    )
    monkeypatch.setattr(
        _update_worktrees,
        "enforce_shared_stash_gate",
        lambda args: order.append("shared-stash"),
    )
    args = build_real_parser().parse_args(["update"])
    with pytest.raises(_ReachedPastGate):
        args.func(args)
    assert order == ["agent", "divergence", "shared-stash"]


def test_cmd_update_itself_carries_no_shared_stash_gate():
    """Pins the seam. Gating inside cmd_update broke 34 existing tests when the
    agent gate was first written -- the suite calls it directly as a library
    function. This must stay a dispatch-level wrap."""
    source = inspect.getsource(cli_main.cmd_update)
    assert "_update_worktrees" not in source
    assert "enforce_shared_stash_gate" not in source


def test_main_py_gains_no_surface_at_all():
    """hermes_cli/main.py is the single most conflict-heavy file in the pending
    0.21.1 upgrade merge -- and upstream has moved this whole stash family OUT
    of it into hermes_cli/update_cmd_stash.py, so an edit here would land as a
    delete/modify conflict on a function upstream deleted. Unlike the divergence
    gate, which had to add one --check advisory call, this feature touches
    main.py NOWHERE. That is the bound; if it ever stops being true, the reason
    had better be better than convenience."""
    source = inspect.getsource(cli_main)
    assert "_update_worktrees" not in source
    assert "enforce_shared_stash_gate" not in source
