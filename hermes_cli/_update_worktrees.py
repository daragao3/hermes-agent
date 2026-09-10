"""Refuse ``hermes update``'s apply path when its autostash would land on a
stash stack SHARED with linked worktrees.

WHY THIS EXISTS. The apply path calls ``_stash_local_changes_if_needed``
(``hermes_cli/main.py``) before pulling, which runs::

    git stash push --include-untracked -m hermes-update-autostash-<UTC>
    git rev-parse --verify refs/stash          # <-- captured as stash_ref

``refs/stash`` is the stack TIP, not "the entry I just wrote", and the stash
stack lives in the COMMON git dir -- it is shared by every linked worktree, not
per-worktree like HEAD or the index. So any concurrent ``git stash push`` from
another worktree, landing between those two commands, makes the captured
``stash_ref`` point at SOMEONE ELSE'S entry. Everything downstream then acts on
the wrong stash, and every command still exits 0:

  * ``_restore_stashed_changes`` runs ``git stash apply <their sha>`` -- their
    working tree is written into this checkout instead of the operator's own;
  * ``_resolve_stash_selector`` maps that sha to THEIR ``stash@{n}``;
  * ``_restore_stashed_changes`` / ``_discard_stashed_changes`` then
    ``git stash drop`` it -- destroying an entry this process never created;
  * the operator's real autostash is left on the stack, unrestored and
    unmentioned, so their local changes simply vanish from the tree.

MEASURED 2026-09-10 in a throwaway two-worktree repo (git 2.55.0.windows.5):
after ``stash push`` from the main checkout, one push from a linked worktree
moved ``refs/stash`` from the autostash entry to the sibling's, and
``git stash apply <captured ref>`` wrote the SIBLING's file content into the
main checkout at exit 0. This box has 17 linked worktrees on
``~/.hermes/agent-src``.

WHY A GATE AND NOT THE ONE-LINE FIX. Matching the unique ``-m`` name in
``git stash list`` instead of reading the tip is a ~6-line correction, and it is
the right end state -- but it belongs in ``hermes_cli/main.py``, which upstream
0.21.1 has already EMPTIED of this whole family (they now live in
``hermes_cli/update_cmd_stash.py``). Editing the ``main.py`` copy while that
merge is in flight would hand its holder a delete/modify conflict on a function
upstream deleted. Upstream's rewritten copy carries the same race, so the
correction is filed against it and applied after the merge lands; this gate is
what protects the operator until then, and it costs ``main.py`` nothing.

SCOPE: DIRTY *AND* SHARED. A clean tree never stashes, so it is never at risk,
and refusing there would break the ordinary update. This gate fires only when
both halves hold. ``package-lock.json`` churn is excluded because
``_discard_lockfile_churn`` restores it before the stash logic runs -- counting
it would refuse updates on a tree the product itself considers clean.

FAIL OPEN, DELIBERATELY -- same reasoning as ``_update_divergence``. When
either half cannot be established (git missing, an OSError, unparseable output)
this gate stands down rather than refusing. A guard that cannot read the repo
must not be the reason a single-worktree user cannot update; the hazard it
covers requires a linked worktree to exist at all, so silence is the safe
default here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Process exit code for a refusal. DISTINCT from
#: ``_agent_session.EXIT_REFUSED_AGENT_ACTION`` (30) and
#: ``_update_divergence.EXIT_REFUSED_DIVERGENT_UPDATE`` (31): three gates guard
#: the same command for three different reasons, and a caller reading the exit
#: code must be able to tell them apart.
EXIT_REFUSED_SHARED_STASH = 32

#: Set to any non-empty value to update anyway, accepting the risk. An
#: environment variable rather than a CLI flag for the same reason as the other
#: two gates: ``hermes_cli/main.py``'s option block is the worst-conflicted
#: region of the pending 0.21.1 merge and gains nothing from another flag.
OVERRIDE_ENV = "HERMES_ALLOW_SHARED_STASH_UPDATE"

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


def _porcelain_path(line: str) -> str:
    """The path out of one ``git status --porcelain`` line.

    Rename/copy entries read ``R  old -> new``; the destination is what is
    dirty, so that is what is returned.
    """
    body = line[3:] if len(line) > 3 else ""
    if " -> " in body:
        body = body.split(" -> ", 1)[1]
    return body.strip().strip('"')


def _ignorable_lockfile_churn(lines) -> set:
    """Paths ``_discard_lockfile_churn`` will restore before any stash happens.

    Mirrors that helper's rule: a tracked modification to ``package-lock.json``
    counts as churn only when the ``package.json`` beside it is NOT also dirty
    (a real dependency edit dirties both, and must not be discarded). Anything
    untracked or staged is left out -- that helper only runs ``git checkout --``
    over unstaged tracked diffs.
    """
    dirty_package_dirs = {
        Path(_porcelain_path(line)).parent
        for line in lines
        if _porcelain_path(line).endswith("package.json")
    }
    churn = set()
    for line in lines:
        path = _porcelain_path(line)
        # " M" == modified in the worktree, not staged. That is exactly the set
        # `git diff --name-only` reports, which is what the helper acts on.
        if line[:2] != " M":
            continue
        if not path.endswith("package-lock.json"):
            continue
        if Path(path).parent in dirty_package_dirs:
            continue
        churn.add(path)
    return churn


def would_autostash(*, cwd=None, runner=None):
    """True when the apply path would push an autostash. None if undeterminable.

    Deliberately evaluated AFTER discounting lockfile churn, so this answers
    "will ``_stash_local_changes_if_needed`` actually stash" rather than the
    weaker "is the tree dirty right now".
    """
    cwd = PROJECT_ROOT if cwd is None else cwd
    runner = _default_runner if runner is None else runner

    code, out = runner(_git_cmd() + ["status", "--porcelain"], cwd)
    if code != 0:
        return None
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        return False
    churn = _ignorable_lockfile_churn(lines)
    return any(_porcelain_path(line) not in churn for line in lines)


def linked_worktree_count(*, cwd=None, runner=None):
    """How many LINKED worktrees share this repo's stash stack. None if unknown.

    ``git worktree list --porcelain`` emits one ``worktree <path>`` line per
    tree, the first being the main checkout -- which owns the stack rather than
    sharing it, so it is not counted. A plain clone therefore returns 0 and this
    gate is inert for it.
    """
    cwd = PROJECT_ROOT if cwd is None else cwd
    runner = _default_runner if runner is None else runner

    code, out = runner(_git_cmd() + ["worktree", "list", "--porcelain"], cwd)
    if code != 0:
        return None
    total = sum(1 for line in out.splitlines() if line.startswith("worktree "))
    if total == 0:
        return None
    return total - 1


def override_active(environ=None) -> bool:
    """True when the operator has deliberately accepted the risk."""
    environ = os.environ if environ is None else environ
    return bool(environ.get(OVERRIDE_ENV, "").strip())


def refusal_lines(worktrees: int, project_root=None) -> list[str]:
    """The refusal, as lines. Separated from printing so tests can read it."""
    plural = "worktree" if worktrees == 1 else "worktrees"
    share = "shares" if worktrees == 1 else "share"
    lines = [
        "",
        "=" * 72,
        "  REFUSED: 'hermes update' would autostash onto a SHARED stash stack",
        "=" * 72,
        "",
        f"  * This checkout has uncommitted changes, and {worktrees} linked"
        f" {plural}",
        f"    {share} its stash stack.",
        "",
        "Nothing has been fetched, stashed, pulled, reset or dropped. Your working",
        "tree is exactly as you left it.",
        "",
        "WHY. This command stashes your changes before pulling, then reads back",
        "the entry it just wrote:",
        "",
        "    git stash push --include-untracked -m hermes-update-autostash-<UTC>",
        "    git rev-parse --verify refs/stash",
        "",
        "But refs/stash is the TIP of the stack, and the stack is shared by every",
        "linked worktree -- it is not per-worktree the way HEAD and the index are.",
        "A 'git stash push' from any other worktree in between makes that second",
        "command return SOMEONE ELSE'S entry. The update then applies their stash",
        "into this checkout, drops it, and silently leaves yours behind -- all at",
        "exit 0, with no error to notice.",
        "",
        "DO THIS INSTEAD:",
        "",
        "  1. See what would be stashed:",
        "",
        "         git -C <repo> status",
        "",
        "  2. Commit it, so the update has nothing to stash:",
        "",
        "         git -C <repo> add -A && git -C <repo> commit -m 'wip'",
        "",
        "     (a clean tree never autostashes, and this gate then stands down)",
        "",
        "  3. Or stash it yourself under a name you can find again:",
        "",
        "         git -C <repo> stash push -u -m my-work",
        "         git -C <repo> stash list --format='%gd %H %gs'",
        "",
        "     Recover it later with 'git stash apply <sha>' -- by SHA, not by",
        "     'stash@{0}', which another worktree's push will have renumbered.",
        "",
        "  4. See who else shares this stack:  git -C <repo> worktree list",
        "",
        "OVERRIDE. To update anyway and accept the risk:",
        f"    {OVERRIDE_ENV}=1 hermes update",
        "",
    ]
    if project_root is not None:
        lines.append(f"  (this checkout: {project_root})")
        lines.append("")
    return lines


def enforce_shared_stash_gate(
    args, *, project_root=None, printer=print, runner=None, environ=None
) -> None:
    """Refuse the apply path when the autostash would share a stash stack.

    Returns normally when the command may proceed. Calls ``sys.exit`` otherwise.
    """
    if getattr(args, "check", False):
        return  # --check is read-only; it never stashes.
    if override_active(environ):
        return

    root = PROJECT_ROOT if project_root is None else project_root

    worktrees = linked_worktree_count(cwd=root, runner=runner)
    if not worktrees:  # 0 linked worktrees, or None == unknown. Stand down.
        return

    if not would_autostash(cwd=root, runner=runner):  # clean, or unknown.
        return

    for line in refusal_lines(worktrees, project_root=root):
        printer(line)
    sys.exit(EXIT_REFUSED_SHARED_STASH)
