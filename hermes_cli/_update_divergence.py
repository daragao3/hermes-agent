"""Refuse ``hermes update``'s apply path when it would DISCARD local commits.

WHY THIS EXISTS, AND WHY IT IS NOT ABOUT AGENTS. The apply path runs

    git pull --ff-only origin <branch>

and, when that fails because the histories diverged, falls through to

    git reset --hard origin/<branch>

The comment on that fallback reads "local changes are already stashed, reset to
match the remote exactly" -- true of uncommitted CHANGES, and false of local
COMMITS, which the autostash never touches. So on a checkout whose ``origin`` is
not the repository the local history descends from, every local commit is
discarded from the working tree, and the fast-forward that is supposed to make
this a rare fallback CANNOT succeed -- which makes the reset the guaranteed
outcome rather than the exceptional one.

MEASURED ON THIS BOX, 2026-09-10, agent-src main e916f4d19f:

    origin   = https://github.com/NousResearch/hermes-agent.git   (UPSTREAM)
    daragao3 = https://github.com/daragao3/hermes-agent.git       (the fork)
    main is 2,493 ahead of origin/main and 16,769 behind it.

That is 2,493 commits one ``hermes update`` would delete, for the operator
exactly as much as for an agent -- and ``hermes update --check``, which is
read-only and deliberately ungated, prints "Update available: 16769 commits
behind origin/main. Run 'hermes update' to install", i.e. it actively invites
the destructive command. This gate is the half that ``_agent_session`` explicitly
says it does not cover.

RENAMING THE REMOTES WOULD NOT HAVE FIXED THIS, which is worth recording because
it is the obvious-looking fix. ``daragao3/main`` is a STRICT ANCESTOR of
``origin/main`` (a stale 2026-08-09 sync of upstream) and carries none of the
local commits, so pointing ``origin`` at the fork leaves the histories diverged
-- 2,493 ahead, 5,006 behind -- and the same reset still fires, just onto an
older snapshot. The divergence is the hazard; the remote naming is a separate
(real) problem about push targets.

PLACEMENT. Same seam as the agent gate: the CLI dispatch in
``hermes_cli/subcommands/update.py``, NOT inside ``cmd_update``. Gating inside
``cmd_update`` broke 34 existing tests when the agent gate was first written,
because the suite calls it directly as a library function. ``main.py`` is also
the single most conflict-heavy file in the pending 0.21.1 upgrade merge, and
this module keeps it untouched.

FAIL OPEN, DELIBERATELY. When the count cannot be established -- no
``origin/<branch>`` ref, git missing, a detached or unborn HEAD -- this gate
stands down silently instead of refusing. That is safe here and is not the usual
"fail open is a bug": if ``origin/<branch>`` does not resolve then the
``git reset --hard origin/<branch>`` cannot resolve it either, so ``cmd_update``
fails on its own error path without touching the working tree. Refusing on an
unresolvable ref would instead break the ordinary first-update-after-clone case.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Process exit code for a refusal. DISTINCT from
#: ``_agent_session.EXIT_REFUSED_AGENT_ACTION`` (30) on purpose: these two gates
#: guard the same command for different reasons and a caller reading the exit
#: code must be able to tell "an agent ran this" from "this would have destroyed
#: local commits".
EXIT_REFUSED_DIVERGENT_UPDATE = 31

#: Set to any non-empty value to update anyway, accepting the loss. An
#: environment variable rather than a CLI flag for the same reason as the agent
#: gate: ``hermes_cli/main.py``'s option block is the worst-conflicted region of
#: the pending 0.21.1 merge and gains nothing from another flag.
OVERRIDE_ENV = "HERMES_ALLOW_DIVERGENT_UPDATE"

#: The repo this CLI is installed from. ``main.py`` computes PROJECT_ROOT the
#: same way; recomputed here so this module never imports ``main``.
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _default_runner(cmd, cwd):
    """Run ``cmd``, returning ``(returncode, stdout)``. Never raises."""
    try:
        completed = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, check=False
        )
    except OSError:
        return 1, ""
    return completed.returncode, completed.stdout or ""


def _git_cmd() -> list[str]:
    """Mirror the git invocation ``cmd_update`` builds for itself."""
    if sys.platform == "win32":
        return ["git", "-c", "windows.appendAtomically=false"]
    return ["git"]


def resolve_branch(args) -> str:
    """Same normalization as ``main._resolve_update_branch``.

    Duplicated rather than imported because importing ``main`` from the dispatch
    seam is exactly what this placement avoids. It is a pure expression over
    ``args.branch`` with no config lookup, so the two cannot drift semantically
    without the pinning test in the suite going red.
    """
    return (getattr(args, "branch", None) or "main").strip() or "main"


def local_update_ref(branch: str, *, cwd=None, runner=None):
    """The local ref ``git reset --hard`` would move, or None if there is none.

    ``cmd_update`` switches to ``<branch>`` before resetting, so when a local
    ``<branch>`` exists that -- not the currently checked-out HEAD -- is what
    would be discarded. Falls back to HEAD for the ordinary case of already
    being on the branch under a name git cannot resolve as a head.
    """
    cwd = PROJECT_ROOT if cwd is None else cwd
    runner = _default_runner if runner is None else runner
    git = _git_cmd()

    code, _ = runner(
        git + ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd
    )
    if code == 0:
        return f"refs/heads/{branch}"

    code, _ = runner(git + ["rev-parse", "--verify", "--quiet", "HEAD"], cwd)
    if code == 0:
        return "HEAD"
    return None


def commits_that_would_be_discarded(
    branch: str, *, cwd=None, runner=None, fetch: bool = True
):
    """How many local commits ``reset --hard origin/<branch>`` would delete.

    Returns an int, or None when the question cannot be answered (see FAIL OPEN
    in the module docstring).

    The fetch matters. This gate runs BEFORE ``cmd_update``'s own
    ``git fetch origin <branch>``, so without one the remote-tracking ref can be
    stale. A stale ref cannot turn a genuine divergence into a 0 -- if HEAD is
    contained in the old ``origin/<branch>`` it is contained in the new one too,
    and the fast-forward succeeds -- so the guard would still be safe. It would
    just be able to report the wrong NUMBER, and a refusal that misstates what
    is at stake is worse than one that does not. A failed fetch (offline) is not
    fatal: the stale ref is still evaluated, on the reasoning above.
    """
    cwd = PROJECT_ROOT if cwd is None else cwd
    runner = _default_runner if runner is None else runner
    git = _git_cmd()

    if fetch:
        runner(git + ["fetch", "origin", branch], cwd)

    code, _ = runner(
        git + ["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
        cwd,
    )
    if code != 0:
        return None

    local = local_update_ref(branch, cwd=cwd, runner=runner)
    if local is None:
        return None

    code, out = runner(
        git + ["rev-list", "--count", f"refs/remotes/origin/{branch}..{local}"], cwd
    )
    if code != 0:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def override_active(environ=None) -> bool:
    """True when the operator has deliberately accepted the loss."""
    environ = os.environ if environ is None else environ
    return bool(environ.get(OVERRIDE_ENV, "").strip())


def refusal_lines(branch: str, ahead: int, project_root=None) -> list[str]:
    """The refusal, as lines. Separated from printing so tests can read it."""
    commits = "commit" if ahead == 1 else "commits"
    lines = [
        "",
        "=" * 72,
        "  REFUSED: 'hermes update' would DISCARD local commits",
        "=" * 72,
        "",
        f"  * {ahead} local {commits} on '{branch}' are not on origin/{branch}.",
        "",
        "Nothing has been fetched into your working tree, stashed, pulled, reset or",
        "dropped. Your commits are exactly where they were.",
        "",
        "WHY. This command fast-forwards when it can:",
        "",
        f"    git pull --ff-only origin {branch}",
        "",
        "Your history has diverged from origin, so that CANNOT fast-forward, and the",
        "documented fallback is not a fallback here -- it is the guaranteed outcome:",
        "",
        f"    git reset --hard origin/{branch}",
        "",
        f"That would delete the {ahead} {commits} above from the working tree. The",
        "auto-stash this command takes first does NOT protect them: it saves uncommitted",
        "CHANGES, not commits.",
        "",
        "DO THIS INSTEAD:",
        "",
        "  1. See exactly what is at stake:",
        "",
        f"         git -C <repo> log --oneline origin/{branch}..{branch}",
        "",
        "  2. Check that 'origin' is the repository you actually meant to update from.",
        "     If this is a fork, 'origin' pointing at the UPSTREAM project is the usual",
        "     cause -- the product assumes origin=your fork, upstream=the project:",
        "",
        "         git -C <repo> remote -v",
        "",
        f"  3. Integrate rather than overwrite:  git -C <repo> merge origin/{branch}",
        "",
        f"OVERRIDE. To update anyway and accept losing those {commits}:",
        f"    {OVERRIDE_ENV}=1 hermes update",
        "",
    ]
    if project_root is not None:
        lines.append(f"  (this checkout: {project_root})")
        lines.append("")
    return lines


def enforce_divergence_gate(
    args, *, project_root=None, printer=print, runner=None, environ=None
) -> None:
    """Refuse the apply path when it would discard local commits.

    Returns normally when the command may proceed. Calls ``sys.exit`` otherwise.
    """
    if getattr(args, "check", False):
        return  # --check is read-only; never gated.
    if override_active(environ):
        return

    branch = resolve_branch(args)
    root = PROJECT_ROOT if project_root is None else project_root
    ahead = commits_that_would_be_discarded(branch, cwd=root, runner=runner)
    if not ahead:  # 0 commits, or None == could not determine. Stand down.
        return

    for line in refusal_lines(branch, ahead, project_root=root):
        printer(line)
    sys.exit(EXIT_REFUSED_DIVERGENT_UPDATE)
