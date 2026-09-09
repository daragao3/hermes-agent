"""Resolve the repo root for the zh-Hans parity gates, and REFUSE to guess.

WHY THIS FILE EXISTS. The original gates (2026-09-08 i18n sweep) each carried

    ROOT = r"C:/Users/diego/.hermes/agent-src/.claude/worktrees/<one worktree>"

pinned to the worktree that happened to author them. Every agent on this box
runs from its own per-session worktree, so running a gate in place from any
OTHER worktree silently checked the AUTHOR'S files and printed "0 FAIL" for work
the caller never made. That is a FALSE GREEN with no symptom -- not an error, not
a stack trace, just a clean report about the wrong tree. A sibling session hit it
the same day and wrote it up before this fix existed.

The pinned path is also why the gates were fragile in another way: they lived
loose in C:/Users/diego/ and were deleted within hours, taking three follow-up
tasks' tooling references with them. Hence living in the repo now.

RESOLUTION ORDER, most explicit first:
  1. an explicit root passed by the caller (--root, or the `root` argument)
  2. $HERMES_DOCS_ROOT
  3. `git rev-parse --show-toplevel` from the current directory -- so running a
     gate from inside ANY worktree checks THAT worktree, which is what the
     caller almost always means
  4. nothing else. There is deliberately NO hardcoded fallback: guessing is the
     bug this module exists to prevent.

Whatever the source, the result is VALIDATED (both docs trees must exist) and a
failure is loud. A gate that cannot locate the docs must exit non-zero, never
report a clean sweep of zero files.
"""
import os
import subprocess
import sys

EN_REL = "website/docs"
ZH_REL = "website/i18n/zh-Hans/docusaurus-plugin-content-docs/current"


class DocRootError(RuntimeError):
    pass


def _valid(root):
    return (os.path.isdir(os.path.join(root, EN_REL))
            and os.path.isdir(os.path.join(root, ZH_REL)))


def resolve_root(explicit=None, start=None):
    """Return an absolute repo root containing both docs trees, or raise."""
    tried = []

    def attempt(cand, how):
        if not cand:
            return None
        cand = os.path.abspath(cand)
        tried.append("%s: %s" % (how, cand))
        return cand if _valid(cand) else None

    for cand, how in (
        (explicit, "--root/argument"),
        (os.environ.get("HERMES_DOCS_ROOT"), "$HERMES_DOCS_ROOT"),
    ):
        got = attempt(cand, how)
        if got:
            return got

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start or os.getcwd(),
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0:
            got = attempt(out.stdout.strip(), "git rev-parse --show-toplevel")
            if got:
                return got
    except Exception as exc:                      # noqa: BLE001 - reported below
        tried.append("git rev-parse: %s" % exc)

    raise DocRootError(
        "could not locate a repo containing both docs trees.\n"
        "  looked for: %s AND %s\n"
        "  candidates tried:\n    %s\n"
        "  fix: run from inside a checkout, or pass --root <repo>, "
        "or set HERMES_DOCS_ROOT.\n"
        "  (there is no hardcoded fallback on purpose -- guessing a root is how "
        "these gates used to report a clean sweep of somebody else's worktree)"
        % (EN_REL, ZH_REL, "\n    ".join(tried) or "(none)")
    )


def take_root_arg(argv):
    """Strip a leading '--root <path>' from argv. Returns (root_or_None, argv)."""
    argv = list(argv)
    root = None
    if "--root" in argv:
        i = argv.index("--root")
        try:
            root = argv[i + 1]
        except IndexError:
            raise DocRootError("--root needs a path")
        del argv[i:i + 2]
    return root, argv


def require_pages(rels, what="pages"):
    """Refuse to report success over an empty page list.

    'N checked, 0 FAIL' with N==0 is the other false green these gates can
    produce -- a mistyped list file or a bad glob reads exactly like a pass.
    """
    rels = [r for r in rels if r.strip()]
    if not rels:
        raise DocRootError(
            "no %s to check -- refusing to report a clean result over an empty "
            "list. Check the list file or arguments." % what
        )
    return rels


def bootstrap(argv):
    """Common entry: resolve root + strip --root, or exit(2) loudly."""
    try:
        explicit, argv = take_root_arg(argv)
        return resolve_root(explicit), argv
    except DocRootError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        raise SystemExit(2)
