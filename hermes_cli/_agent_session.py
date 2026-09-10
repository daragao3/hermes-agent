"""Refuse ``hermes update``'s destructive apply path from an agent session.

WHY THIS EXISTS. ``hermes update`` is a self-update command whose apply path is
destructive BY DESIGN: it stashes local changes, tries ``git pull --ff-only
origin <branch>``, and when that fails because the histories diverged it falls
through to ``git reset --hard origin/<branch>``. It also drops the stash it
made, and -- if an ``upstream`` remote exists -- offers to sync the fork back
with ``git push origin main --force-with-lease``.

Every one of those is invisible to the machine-wide guard at
``~/.claude/hooks/block-destructive-git.py``. That hook reads the ARGV of the
command an agent runs, and ``hermes update`` carries no git verb: the calls are
``subprocess.run(git_cmd + [...])`` inside this package. A content scan of
launched scripts was measured over 436 of them on 2026-09-09 and rejected --
it fires on prose in the claim-gate and commit wrappers while missing the real
callers, this one included. Record: loops
``gitguard-script-file-argument-gap-20260909``.

THIS GATE IS NARROWER THAN IT LOOKS, AND DELIBERATELY SO.

  * ``hermes update --check`` is read-only and is NOT gated: the caller checks
    this only after the ``--check`` early return, so the "is there an update?"
    question keeps working from anywhere.
  * It is not an authorization boundary and cannot be one -- anything that can
    run ``hermes update`` can set the override variable. Like the hook it
    complements, it stops an ACCIDENT.
  * Codex sessions are NOT detected. Their environment has never been measured
    on this box, and a guessed marker that never fires is worse than a
    documented gap.

WHAT IT DOES NOT PROTECT AGAINST, which matters more than what it does.
The destructive outcome above is not agent-specific: on a checkout whose
``origin`` is not the repository the local history descends from, ``hermes
update`` will diverge, reset --hard, and discard every local commit -- for a
human operator exactly as much as for an agent. This gate stops one of those
two callers. It must not be read as making the command safe. See the
``AGENT UPDATE GATE`` note in the caller and the refusal text below.

A SECOND COPY OF THIS DETECTOR lives in ``scripts/release.py``, on purpose:
that file is run as a standalone script and does not import this package. The
two are kept deliberately identical in behaviour -- same markers, same segment
matching, same exit code -- so a session that has met one recognises the other.
The third of the family is jobflow-platform's
``scripts/ops/refresh-ci-snapshot.ps1``.
"""

from __future__ import annotations

import os

#: Process exit code for a refusal. Shared with ``scripts/release.py`` and with
#: jobflow-platform's refresh-ci-snapshot.ps1, so one number means one thing
#: across every gate of this family.
EXIT_REFUSED_AGENT_ACTION = 30

#: Set this to any non-empty value to publish/update anyway. An environment
#: variable rather than a CLI flag on purpose: ``hermes_cli/main.py`` is the
#: single most conflict-heavy file in the pending 0.21.1 upgrade merge, and a
#: new argparse flag would add surface to its option block for no behavioural
#: gain. It also cannot be reached by a stray tab-completion.
OVERRIDE_ENV = "HERMES_ALLOW_AGENT_UPDATE"

#: Variables Claude Code exports into every tool it runs. Matched on PRESENCE,
#: not value -- CLAUDE_CODE_DISABLE_CRON is exported EMPTY, so a truthiness test
#: on the value would miss a real agent session.
_AGENT_ENV_EXACT = ("CLAUDECODE", "CLAUDE_AGENT_SDK_VERSION")
_AGENT_ENV_PREFIX = "CLAUDE_CODE_"


def agent_session_evidence(environ=None, cwd=None):
    """Why this looks like an agent session, as zero or more human sentences.

    An EMPTY list means "no evidence", which is the only thing a caller may
    treat as a green light.

    Both inputs are parameters rather than reads of the ambient process, so the
    tests can drive every branch with synthetic values -- including the negative
    case, which cannot otherwise be expressed from inside an agent session.
    """
    environ = os.environ if environ is None else environ
    cwd = os.getcwd() if cwd is None else cwd

    evidence = []

    markers = sorted(
        name
        for name in environ
        if name in _AGENT_ENV_EXACT or name.startswith(_AGENT_ENV_PREFIX)
    )
    if markers:
        shown = ", ".join(markers[:4])
        if len(markers) > 4:
            shown += f", +{len(markers) - 4} more"
        evidence.append(f"environment: {len(markers)} agent marker(s) set -- {shown}")

    if cwd:
        # Match a whole path SEGMENT, so a directory merely named
        # "team.claude/worktrees-archive" is not evidence.
        parts = cwd.replace("\\", "/").split("/")
        for i in range(len(parts) - 1):
            if parts[i] == ".claude" and parts[i + 1] == "worktrees":
                evidence.append(f"working directory is inside an agent worktree: {cwd}")
                break

    return evidence


def override_active(environ=None) -> bool:
    """True when the operator has deliberately allowed an agent-run update."""
    environ = os.environ if environ is None else environ
    return bool(environ.get(OVERRIDE_ENV, "").strip())


def refusal_lines(evidence, project_root=None, branch: str = "main") -> list[str]:
    """The refusal, as lines. Separated from printing so tests can read it."""
    lines = [
        "",
        "=" * 72,
        "  REFUSED: 'hermes update' from what looks like an agent session",
        "=" * 72,
        "",
    ]
    lines += [f"  * {item}" for item in evidence]
    lines += [
        "",
        "Nothing has been stashed, pulled, reset or dropped.",
        "",
        "WHY. The apply path of this command is destructive by design: it stashes your",
        "changes, tries a fast-forward pull, and if the histories have diverged it runs",
        f"    git reset --hard origin/{branch}",
        "then drops the stash it made. Those calls are made inside this package, so the",
        "machine-wide git guard never sees them -- no block, no pending id, no grant.",
        "",
        "DO THIS INSTEAD:",
        "",
        "  1. Ask what an update would do, which is read-only and is NOT gated:",
        "         hermes update --check",
        "",
        "  2. Leave the apply to Diego, at a moment when losing the working tree is",
        "     acceptable and no other session is mid-merge.",
        "",
        f"OVERRIDE. If Diego has authorized THIS update:  {OVERRIDE_ENV}=1 hermes update",
        "  It is not a way around the grant -- it is the operator standing in for one.",
        "",
        "READ THIS EVEN IF YOU ARE A HUMAN WHO HIT THIS BY ACCIDENT.",
        "This gate stops agent sessions. It does NOT make the command safe, and the",
        "danger it is guarding is not agent-specific: if this checkout's 'origin' is not",
        "the repository your local history descends from, the fast-forward CANNOT",
        "succeed, so the reset --hard above is not a fallback -- it is the guaranteed",
        "outcome, and it discards every local commit from the working tree. Check with:",
        "",
        "    git -C <repo> remote -v",
        f"    git -C <repo> rev-list --count origin/{branch}..HEAD   # what would be discarded",
        "",
    ]
    if project_root is not None:
        lines.append(f"  (this checkout: {project_root})")
        lines.append("")
    return lines


def enforce_update_gate(args, *, project_root=None, printer=print) -> None:
    """Refuse ``hermes update``'s apply path from an agent session.

    Called from the CLI dispatch in ``hermes_cli/subcommands/update.py``, NOT
    from inside ``cmd_update``. That placement is deliberate and was arrived at
    the hard way: gating inside ``cmd_update`` broke 34 existing tests, which
    call it directly as a library function while the suite itself runs inside an
    agent session (measured 7 failures on main vs 41 on the branch). The
    accident worth preventing is someone TYPING ``hermes update``; a
    programmatic caller is already doing something deliberate. Gating the
    dispatch needs no pytest special-case, adds no new bypass, and leaves
    ``hermes_cli/main.py`` -- the most conflict-heavy file in the pending 0.21.1
    upgrade merge -- completely untouched.

    Returns normally when the command may proceed. Calls ``sys.exit`` otherwise.
    """
    import sys

    if getattr(args, "check", False):
        return  # --check is read-only; never gated.
    if override_active():
        return

    evidence = agent_session_evidence()
    if not evidence:
        return

    branch = (getattr(args, "branch", None) or "main").strip() or "main"
    for line in refusal_lines(evidence, project_root=project_root, branch=branch):
        printer(line)
    sys.exit(EXIT_REFUSED_AGENT_ACTION)
